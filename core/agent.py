"""
Spider Agent 核心循环

类比 Hermes 的 Agent 系统：
- ReAct 循环 (思考→行动→观察)
- Tool use (通过 ToolRegistry)
- 子代理委托 (Phase 2)
- 技能固化 (Phase 2)
"""

import asyncio
import json
import logging
from datetime import datetime

from .llm import LLM
from .tool_registry import ToolRegistry
from .skill_manager import SkillManager
from .memory import (
    MemoryStore,
    RECALL_SCHEMA,
    SAVE_MEMORY_SCHEMA,
    LIST_CONVERSATIONS_SCHEMA,
)

logger = logging.getLogger("spider")


class Agent:
    """Agent 核心引擎"""

    SYSTEM_PROMPT = """你是一个名为 Spider 的 AI 助手。你有以下能力：
1. 使用各种工具来完成任务
2. 将复杂任务拆解为多个步骤
3. 如需更多信息，主动询问用户

始终用中文回复。思考过程保持简洁。"""

    def __init__(self, model="deepseek-v4-flash", max_turns=30,
                 api_key=None, base_url=None, memory_store=None):
        self.llm = LLM(model=model, api_key=api_key, base_url=base_url)
        self.tools = ToolRegistry()
        self.skill_manager = SkillManager()
        self.memory = memory_store  # MemoryStore 实例或 None
        self.max_turns = max_turns
        self.messages = []  # 对话历史
        self._turn = 0
        self._start_time = None
        self._conv_id = None  # 当前会话 ID

        # 持久化记忆工具
        if self.memory:
            self._register_memory_tools()

    def register_tool(self, name: str, description: str, handler, parameters: dict):
        """注册一个工具"""
        self.tools.register(name, description, handler, parameters)

    def set_system_prompt(self, prompt: str):
        """自定义 system prompt"""
        self.SYSTEM_PROMPT = prompt

    def _register_memory_tools(self):
        """注册持久化记忆相关的工具"""
        self.register_tool(
            "recall",
            "搜索以往的对话记忆和关键信息。"
            "当你觉得当前任务可能与之前做过的事情相关时使用，"
            "或者需要了解用户偏好、项目历史时使用。",
            self.memory.recall,
            RECALL_SCHEMA,
        )
        self.register_tool(
            "save_memory",
            "保存一条关键信息到长期记忆。"
            "当发现重要的用户偏好、项目配置、或者值得记住的任务结果时使用。"
            "保存后未来任何对话都可以回忆起来。",
            self._save_memory_wrapper,
            SAVE_MEMORY_SCHEMA,
        )
        self.register_tool(
            "conversations",
            "查看最近的对话历史记录。",
            self.memory.list_conversations,
            LIST_CONVERSATIONS_SCHEMA,
        )

    async def _save_memory_wrapper(self, content: str, category: str = "general"):
        """包装 save_memory，自动记录来源会话 ID"""
        return await self.memory.save_memory(content, category, source_conv_id=self._conv_id)

    def _setup_messages(self, task: str):
        """初始化消息列表，自动匹配技能 + 注入相关记忆"""
        system = self.SYSTEM_PROMPT

        # 注入相关记忆（自动 recall）
        if self.memory:
            memories = self.memory.recall(task, limit=3)
            if memories:
                system += f"\n\n📖 相关记忆:\n{memories}"

        # 技能匹配
        skill_prompts = self.skill_manager.get_skill_prompts(task)
        if skill_prompts:
            system += f"\n\n📚 参考技能提示:\n{skill_prompts}"

        self.messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

    async def run(self, task: str, stream=True, on_event=None) -> str:
        """
        主循环：思考 → 选工具 → 执行 → 观察 → 循环

        Args:
            task: 用户任务
            stream: 是否流式输出
            on_event: 可选回调 dict，格式:
                {
                    "thinking_chunk": async callable(chunk: str),
                    "thinking_done": async callable(content: str),
                    "reasoning_chunk": async callable(chunk: str),
                    "turn_start": async callable(turn: int, max_turns: int),
                    "tool_call": async callable(name: str, args: dict),
                    "tool_result": async callable(name: str, result: str),
                    "done": async callable(content: str, elapsed: str),
                    "error": async callable(msg: str),
                }

        Returns:
            最终回复内容
        """
        self._setup_messages(task)
        self._turn = 0
        self._start_time = datetime.now()
        self._conv_id = None

        # 持久化：创建会话，保存用户消息
        if self.memory:
            self._conv_id = self.memory.create_conversation(summary=task[:200])
            self.memory.save_message(self._conv_id, "user", task)

        print(f"\n🧠 Spider — 开始处理任务")
        print(f"{'='*50}")
        if on_event and on_event.get("turn_start"):
            await on_event["turn_start"](0, self.max_turns)

        for turn in range(self.max_turns):
            self._turn = turn + 1
            print(f"\n--- Turn {self._turn}/{self.max_turns} ---")
            if on_event and on_event.get("turn_start"):
                await on_event["turn_start"](self._turn, self.max_turns)

            if stream:
                response = await self._think_stream(on_event=on_event)
            else:
                print("  🤔 思考中...", end="", flush=True)
                response = await self._think()
                print("\r" + " " * 20 + "\r", end="", flush=True)

            # LLM 决定结束
            if response["is_done"]:
                content = response.get("content", "")
                # 持久化：保存最终回复
                if self.memory and self._conv_id:
                    self.memory.save_message(self._conv_id, "assistant", content)
                    self.memory.update_conversation(
                        self._conv_id, turn_count=self._turn,
                        summary=(content or "")[:200],
                    )
                elapsed = self._elapsed()
                usage = response.get("usage")
                print(f"\n{'='*50}")
                print(f"✅ 任务完成 (用时 {elapsed})", end="")
                if usage:
                    print(f"  |  {usage}", end="")
                print()  # 换行
                # 非流式模式下内容还没显示过，在这里打印
                if not stream and content:
                    print(f"\n🕷️ {content}")
                if on_event and on_event.get("done"):
                    await on_event["done"](content, elapsed)
                return content

            # 执行工具
            tool_call_content = response.get("content", "")
            for tc in response["tool_calls"]:
                args_str = json.dumps(tc["arguments"], ensure_ascii=False)
                print(f"  🔧 {tc['name']}({args_str})")
                if on_event and on_event.get("tool_call"):
                    await on_event["tool_call"](tc["name"], tc["arguments"])
                result = await self.tools.execute(tc)
                print(f"  📦 结果: {result[:200]}{'...' if len(result) > 200 else ''}")
                if on_event and on_event.get("tool_result"):
                    await on_event["tool_result"](tc["name"], result)

                # 将 tool call + result 加入对话
                msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": args_str},
                    }]
                }
                rc = response.get("reasoning_content")
                if rc:
                    msg["reasoning_content"] = rc
                self.messages.append(msg)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

                # 持久化：保存 assistant 思考 + tool 结果
                if self.memory and self._conv_id:
                    self.memory.save_message(
                        self._conv_id, "assistant",
                        tool_call_content,
                        {"tool_calls": [{
                            "name": tc["name"],
                            "args": tc["arguments"],
                        }]},
                    )
                    self.memory.save_message(
                        self._conv_id, "tool", result,
                    )

        # 达到最大轮数
        msg = f"⚠️ 达到最大轮数 ({self.max_turns})，任务可能未完成。"
        if self.memory and self._conv_id:
            self.memory.update_conversation(self._conv_id, turn_count=self._turn)
        if on_event and on_event.get("done"):
            await on_event["done"](msg, self._elapsed())
        return msg

    async def _think(self) -> dict:
        """非流式思考（不打印内容，由 run() 统一打印）"""
        try:
            response = self.llm.think(self.messages, self.tools.schemas)
        except Exception as e:
            return {"content": f"思考出错: {e}", "tool_calls": [], "is_done": True}
        # 不在这里打印，由 run() 统一在最后打印🕷️，避免重复
        result = {
            "content": response.content or "",
            "tool_calls": response.tool_calls,
            "is_done": response.is_done,
            "usage": response.usage if hasattr(response, "usage") else None,
        }
        if response.reasoning_content:
            result["reasoning_content"] = response.reasoning_content
        return result

    async def _think_stream(self, on_event=None) -> dict:
        """流式思考"""
        accumulated = ""
        first_chunk = True

        print("  🤔 思考中...", end="", flush=True)

        def on_content(chunk):
            nonlocal accumulated, first_chunk
            if first_chunk:
                first_chunk = False
                print("\r  💬 ", end="", flush=True)
            accumulated += chunk
            print(chunk, end="", flush=True)
            if on_event and on_event.get("thinking_chunk"):
                asyncio.create_task(on_event["thinking_chunk"](chunk))

        def on_tool(tcs):
            pass

        try:
            result = self.llm.think_stream(self.messages, self.tools.schemas,
                                            on_content=on_content, on_tool=on_tool)
        except Exception as e:
            # 出错时如果还在"思考中"状态，清除它
            if first_chunk:
                print("\r" + " " * 20 + "\r", end="", flush=True)
            if on_event and on_event.get("error"):
                asyncio.create_task(on_event["error"](f"思考出错: {e}"))
            return {"content": f"思考出错: {e}", "tool_calls": [], "is_done": True}

        # 没收到任何内容但也没出错（空回复）
        if first_chunk:
            print("\r" + " " * 20 + "\r  💬 ", end="", flush=True)

        print()  # 换行

        # 流式模式下 content 可能不完整，用 accumulated
        result["content"] = accumulated or result.get("content", "")
        if on_event and on_event.get("thinking_done"):
            asyncio.create_task(on_event["thinking_done"](result["content"]))
        return result

    def _elapsed(self) -> str:
        """返回已用时间"""
        if not self._start_time:
            return "0s"
        delta = datetime.now() - self._start_time
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        return f"{seconds // 60}m{seconds % 60}s"

    def get_conversation_log(self) -> str:
        """导出当前对话为可读格式"""
        lines = []
        for msg in self.messages:
            role = msg["role"].upper()
            if msg["role"] == "system":
                continue
            if msg["role"] == "user":
                lines.append(f"\n🙋 {msg['content']}\n")
            elif msg["role"] == "assistant":
                if msg.get("content"):
                    lines.append(f"\n🕷️ {msg['content']}")
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        fn = tc["function"]
                        lines.append(f"\n🔧 调用工具: {fn['name']}({fn['arguments']})")
            elif msg["role"] == "tool":
                lines.append(f"   → {msg['content'][:150]}")
        return "\n".join(lines)
