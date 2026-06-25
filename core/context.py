"""
上下文管理器 — 防止长对话 token 超限失忆

自动追踪消息长度，在接近上下文窗口上限时压缩早期对话。
保留：系统提示 + 最近 2 轮对话
压缩：中间部分 → LLM 摘要 → 替换为一条摘要消息
"""

import json
import logging

logger = logging.getLogger("spider.context")


class ContextManager:
    """管理对话上下文，避免 token 溢出"""

    # 各模型的上下文窗口（预留 20% 给输出）
    MODEL_LIMITS = {
        "deepseek-v4-flash": (128000, 102400),   # total, trigger
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
        self._compressed = False  # 只压缩一次

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
            total += len(content)
            # tool_calls 参数
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    args = tc.get("function", {}).get("arguments", "{}")
                    total += len(str(args))
            # tool 调用的结果
            if msg.get("name"):
                total += len(msg.get("name", ""))
            # 每条消息的开销 (~4 tokens)
            total += 10
        # 混合中英文：保守按 2 字符/token
        return total // 2

    def should_compress(self, messages: list[dict]) -> bool:
        """是否需要压缩上下文"""
        if self._compressed:
            return False
        estimated = self.estimate_tokens(messages)
        return estimated > self._trigger_tokens

    async def compress(self, messages: list[dict], llm) -> list[dict]:
        """压缩上下文：摘要早期对话，保留最近内容"""
        if len(messages) <= 5:
            self._compressed = True
            return messages

        system = messages[0]
        # 保留最后 4 条消息（约 2 轮 user↔assistant 交换）
        recent_start = max(4, len(messages) - 4)
        recent = messages[recent_start:]
        to_compress = messages[1:recent_start]

        if not to_compress:
            self._compressed = True
            return messages

        # 提取摘要文本
        text_parts = []
        for m in to_compress:
            role = m["role"]
            content = m.get("content", "") or ""
            # 工具调用不参与摘要（保留文本消息即可）
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    text_parts.append(f"[assistant 调用了 {fn.get('name','?')}]")
            if content:
                # 只取前 300 字
                text_parts.append(f"[{role}] {content[:300]}")

        summary_text = "\n".join(text_parts)

        if not summary_text.strip():
            self._compressed = True
            return [system] + recent

        # 用 LLM 生成摘要（非流式，小调用）
        try:
            resp = llm.think([
                {
                    "role": "system",
                    "content": "你是一个对话摘要助手。用2-3句中文概括以下对话中已经完成的任务和发现的关键信息。只输出摘要，不要其他内容。",
                },
                {"role": "user", "content": f"请概括以下对话内容：\n\n{summary_text}"},
            ])
            summary = resp.content or "(摘要生成失败)"
        except Exception as e:
            logger.warning(f"上下文摘要生成失败: {e}")
            summary = f"(摘要生成失败: {e})"

        # 重建消息列表
        self._compressed = True
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
        logger.info(
            f"上下文压缩: 移除 {saved} 条消息, "
            f"{before} → {after} tokens "
            f"(节省 {before - after})"
        )

        return compressed
