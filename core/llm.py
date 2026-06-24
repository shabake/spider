"""
Spider LLM 封装层
负责与 DeepSeek API 通信，支持 streaming 和 tool calls
"""

import json
import logging
import os
from typing import Callable

from openai import OpenAI
from openai import AuthenticationError as OpenAIAuthError

logger = logging.getLogger("spider")


class AuthError(Exception):
    """API 认证失败"""
    pass


class Usage:
    """Token 用量统计"""

    def __init__(self, prompt_tokens=0, completion_tokens=0, total_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens

    def __str__(self):
        if self.total_tokens == 0:
            return ""
        return f"📊 输入 {self.prompt_tokens} · 输出 {self.completion_tokens} · 共 {self.total_tokens} tokens"

    def __bool__(self):
        return self.total_tokens > 0


class LLMResponse:
    """LLM 响应的统一封装"""

    def __init__(self, raw):
        self.raw = raw
        self.content = ""
        self.tool_calls = []
        self.is_done = False
        self.finish_reason = None
        self.reasoning_content = None
        self.usage = Usage()
        self._parse(raw)

    def _parse(self, raw):
        choice = raw.choices[0] if raw.choices else None
        if not choice:
            self.is_done = True
            return

        # Token 用量（非流式）
        if hasattr(raw, "usage") and raw.usage:
            self.usage = Usage(
                prompt_tokens=getattr(raw.usage, "prompt_tokens", 0),
                completion_tokens=getattr(raw.usage, "completion_tokens", 0),
                total_tokens=getattr(raw.usage, "total_tokens", 0),
            )

        # DeepSeek thinking mode — 保留 reasoning_content
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            self.reasoning_content = msg.reasoning_content

        # 文本内容
        if msg.content:
            self.content = msg.content

        # Tool calls
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = {}
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                self.tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args,
                })

        # 判断是否结束
        if self.finish_reason == "stop":
            self.is_done = True
        elif self.finish_reason == "tool_calls":
            self.is_done = False
        elif not self.tool_calls and self.content:
            self.is_done = True

    def to_assistant_message(self) -> dict:
        """构建 assistant 消息（包含 reasoning_content 以兼容 DeepSeek）"""
        msg = {"role": "assistant"}
        if self.content:
            msg["content"] = self.content
        else:
            msg["content"] = None
        if self.reasoning_content:
            msg["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
        return msg


class LLM:
    """LLM 调用封装，支持 tool use + embedding"""

    EMBEDDING_MODEL = os.environ.get("DEEPSEEK_EMBEDDING_MODEL", "deepseek-embedding")

    def __init__(self, model="deepseek-v4-flash", api_key=None, base_url="https://api.deepseek.com/v1"):
        self.model = model
        self.client = OpenAI(
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=base_url,
        )

    def get_embedding(self, text: str) -> list[float]:
        """
        生成文本的向量 embedding

        Args:
            text: 要编码的文本

        Returns:
            浮点数向量列表，失败时返回空列表
        """
        if not text or not text.strip():
            return []

        try:
            resp = self.client.embeddings.create(
                model=self.EMBEDDING_MODEL,
                input=text.strip()[:8000],  # 限制长度
            )
            return resp.data[0].embedding
        except Exception as e:
            logger.warning(f"Embedding 生成失败: {e}")
            return []

    def think(self, messages: list, tools: list[dict] = None) -> LLMResponse:
        """向 LLM 发送消息并获取响应"""
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            raw = self.client.chat.completions.create(**kwargs)
        except OpenAIAuthError:
            raise AuthError(
                "DeepSeek API 认证失败 ❌\n"
                "  原因：API Key 无效或未设置\n"
                "  解决：\n"
                "    export DEEPSEEK_API_KEY=\"sk-你的key\"\n"
                "    或 python3 main.py --api-key \"sk-你的key\" \"任务\""
            )
        return LLMResponse(raw)

    def think_stream(self, messages: list, tools: list[dict] = None,
                     on_content: Callable = None, on_tool: Callable = None):
        """流式思考，实时输出内容"""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            stream = self.client.chat.completions.create(**kwargs)
        except OpenAIAuthError:
            raise AuthError(
                "DeepSeek API 认证失败 ❌\n"
                "  原因：API Key 无效或未设置\n"
                "  解决：\n"
                "    export DEEPSEEK_API_KEY=\"sk-你的key\"\n"
                "    或 python3 main.py --api-key \"sk-你的key\" \"任务\""
            )

        full_content = ""
        tool_calls = {}
        finish_reason = None
        reasoning_content = None
        usage = Usage()

        for chunk in stream:
            # Token 用量（最后一个 chunk 携带）
            if hasattr(chunk, "usage") and chunk.usage:
                usage = Usage(
                    prompt_tokens=getattr(chunk.usage, "prompt_tokens", 0),
                    completion_tokens=getattr(chunk.usage, "completion_tokens", 0),
                    total_tokens=getattr(chunk.usage, "total_tokens", 0),
                )

            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            # 内容
            if delta.content:
                full_content += delta.content
                if on_content:
                    on_content(delta.content)

            # DeepSeek reasoning_content (thinking mode)
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_content = delta.reasoning_content

            # Tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": tc.id, "name": tc.function.name, "arguments": ""}
                    if tc.function.arguments:
                        tool_calls[idx]["arguments"] += tc.function.arguments

        # 组装最终结果
        result = {
            "content": full_content,
            "tool_calls": [],
            "is_done": finish_reason == "stop" or (not tool_calls and full_content),
            "reasoning_content": reasoning_content,
            "usage": usage,
        }

        for tc in tool_calls.values():
            args = {}
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                args = {"_raw": tc["arguments"]}
            result["tool_calls"].append({
                "id": tc["id"],
                "name": tc["name"],
                "arguments": args,
            })

        if on_tool and result["tool_calls"]:
            on_tool(result["tool_calls"])

        return result
