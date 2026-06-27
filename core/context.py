"""
上下文管理器 — 防止长对话 token 超限失忆

自动追踪消息长度，在接近上下文窗口上限时压缩早期对话。
支持多轮压缩，首次用 LLM 摘要，后续用截断（节省 token）。

保留：系统提示 + 最近 3 轮对话
"""

import logging

logger = logging.getLogger("spider.context")

# 简易 tiktoken 估算（BPE 分词器可用时更精确）
try:
    import tiktoken

    def _count_tokens(text: str) -> int:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

    def _count_tokens(text: str) -> int:
        # 保守估计：中英文混合 2 字符/token
        return max(1, len(text) // 2)


class ContextManager:
    """管理对话上下文，避免 token 溢出"""

    # 各模型的上下文窗口（预留 20% 给输出）
    MODEL_LIMITS = {
        "deepseek-v4-flash": (128000, 102400),     # total, trigger (80%)
        "deepseek-chat": (128000, 102400),
        "claude-opus-4-8": (200000, 160000),
        "claude-sonnet-4-6": (200000, 160000),
        "claude-haiku-4-5": (200000, 160000),
        "gpt-4o": (128000, 102400),
        "default": (128000, 102400),
    }

    def __init__(self, model: str = "deepseek-v4-flash"):
        self.model = model
        limits = self.MODEL_LIMITS.get(model, self.MODEL_LIMITS["default"])
        self._max_tokens = limits[0]
        self._trigger_tokens = limits[1]
        # 二级触发（更紧急时用截断而非 LLM 摘要）
        self._emergency_tokens = int(self._max_tokens * 0.92)
        self._compress_count = 0  # 压缩次数
        self._recent_keep = 6     # 保留的最近消息数

    @property
    def total_tokens(self) -> int:
        return self._max_tokens

    @property
    def trigger_tokens(self) -> int:
        return self._trigger_tokens

    def estimate_tokens(self, messages: list[dict]) -> int:
        """估算消息列表的 token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "") or ""
            total += _count_tokens(content)
            # tool_calls 参数
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    args = tc.get("function", {}).get("arguments", "{}")
                    total += _count_tokens(str(args))
            if msg.get("name"):
                total += _count_tokens(msg.get("name", ""))
            # 每条消息的开销
            total += 4
        return total

    def should_compress(self, messages: list[dict]) -> bool:
        """是否需要压缩上下文"""
        estimated = self.estimate_tokens(messages)
        return estimated > self._trigger_tokens

    async def compress(self, messages: list[dict], llm) -> list[dict]:
        """压缩上下文：支持多轮，策略逐级收紧"""
        if len(messages) <= 5:
            return messages

        system = messages[0]

        # 保留最近 N 条消息
        recent_start = max(self._recent_keep, len(messages) - self._recent_keep)
        recent = messages[recent_start:]
        to_compress = messages[1:recent_start]

        if not to_compress:
            return messages

        self._compress_count += 1
        is_emergency = self.estimate_tokens(messages) > self._emergency_tokens

        if is_emergency or self._compress_count > 1:
            # ── 紧急/二次压缩：直接截断（不调用 LLM） ──────────
            summary = f"(前 {len(to_compress)} 条消息已自动截断以节省上下文)"
        else:
            # ── 首次压缩：LLM 摘要 ────────────────────────────
            summary = await self._llm_summarize(to_compress, llm)

        compressed = [
            system,
            {
                "role": "system",
                "content": f"📋 以下为早前内容的摘要（自动压缩以节省上下文）：\n{summary}",
            },
        ] + recent

        saved = len(messages) - len(compressed)
        before = self.estimate_tokens(messages)
        after = self.estimate_tokens(compressed)

        # 如果压缩后仍然超限，减少保留的消息数
        if after > self._trigger_tokens and self._recent_keep > 2:
            self._recent_keep -= 2
            logger.info(f"上下文仍超限，保留消息数降至 {self._recent_keep}")

        logger.info(
            f"上下文压缩 (#{self._compress_count}): "
            f"移除 {saved} 条消息, "
            f"{before} → {after} tokens "
            f"(节省 {before - after})"
        )

        return compressed

    async def _llm_summarize(self, messages: list[dict], llm) -> str:
        """用 LLM 生成摘要"""
        text_parts = []
        for m in messages:
            role = m["role"]
            content = m.get("content", "") or ""
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    text_parts.append(f"[assistant 调用了 {fn.get('name', '?')}]")
            if content:
                text_parts.append(f"[{role}] {content[:300]}")
        summary_text = "\n".join(text_parts)
        if not summary_text.strip():
            return "(无内容)"

        try:
            resp = llm.think([
                {
                    "role": "system",
                    "content": "你是一个对话摘要助手。用2-3句中文概括以下对话中已经完成的任务和发现的关键信息。只输出摘要，不要其他内容。",
                },
                {"role": "user", "content": f"请概括以下对话内容：\n\n{summary_text}"},
            ])
            return resp.content or "(摘要生成失败)"
        except Exception as e:
            logger.warning(f"摘要生成失败: {e}")
            return f"(摘要生成失败)"
