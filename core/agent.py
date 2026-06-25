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
from .context import ContextManager
from .memory import (
    MemoryStore,
    RECALL_SCHEMA,
    SAVE_MEMORY_SCHEMA,
    LIST_CONVERSATIONS_SCHEMA,
)

logger = logging.getLogger("spider")


class Agent:
    """Agent 核心引擎"""

    SYSTEM_PROMPT = """你是一个名为 Spider 的 AI 助手。

你的核心能力：
1. 使用各种工具来完成任务（文件读写、Shell 执行、代码搜索等）
2. 将复杂任务拆解为多个步骤
3. 通过子代理并行执行独立子任务
4. 把有效经验保存为技能，下次复用
5. 通过持久化记忆记住用户偏好和项目信息

回复风格：
- 用中文回复，保持自然、友好的语气
- 思考过程保持简洁，直接展示结果
- 使用 markdown 格式让回答结构清晰（标题、列表、代码块）
- 回答完主动询问是否需要进一步帮助"""

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
        self._step_skills = []  # 匹配到的带步骤的技能
        self.mcp_manager = None  # MCPManager 实例（由 create_agent 注入）
        self.context = ContextManager(model=model)  # 上下文管理器
        self._usage = None  # 最新 token 用量

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

    async def _load_mcp(self):
        """首次运行时加载 MCP 工具"""
        if not self.mcp_manager:
            return
        try:
            await self.mcp_manager.load_config()
            self.mcp_manager.register_to(self.tools)
            self._mcp_loaded = True
        except Exception as e:
            logger.warning(f"  ⚠️  MCP 加载失败: {e}")
            self._mcp_loaded = True  # 避免重试

    def _setup_messages(self, task: str):
        """初始化消息列表，自动匹配技能 + 注入相关记忆"""
        system = self.SYSTEM_PROMPT

        # 注入相关记忆（自动 recall）
        if self.memory:
            memories = self.memory.recall(task, limit=3)
            if memories:
                system += f"\n\n📖 相关记忆:\n{memories}"

        # 技能匹配 — 分离出有步骤的技能
        self._step_skills = []
        matched = self.skill_manager.find_matching(task)
        prompt_parts = []
        for skill in matched:
            if skill.has_steps:
                self._step_skills.append(skill)
                prompt_parts.append(
                    f"📌 参考技能 [{skill.name}]: {skill.description}\n"
                    f"{skill.prompt}"
                )
            elif skill.prompt:
                prompt_parts.append(
                    f"📌 参考技能 [{skill.name}]: {skill.description}\n"
                    f"{skill.prompt}"
                )

        if prompt_parts:
            system += "\n\n" + "\n\n".join(prompt_parts)

        self.messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

    async def _execute_skill_steps(self, skill, cli=None) -> str:
        """按顺序执行技能的预定义步骤

        Args:
            skill: Skill 实例（需有 steps 属性）
            cli: 可选的 SpiderCLI 实例

        Returns:
            所有步骤的结果文本
        """
        results = []
        for i, step in enumerate(skill.steps):
            step_name = step.get("name", f"步骤{i+1}")
            tool_name = step.get("tool", "")
            params = step.get("params", {})

            if cli:
                cli.display_step(step_name, tool_name, params)

            # 查找工具
            tool = self.tools.get(tool_name)
            if not tool:
                msg = f"❌ [{step_name}] 工具 '{tool_name}' 不存在"
                results.append(msg)
                if cli:
                    cli.display_tool_result(msg)
                continue

            # 执行工具
            try:
                result = await tool.execute(params)
                output = f"📌 [{step_name}]\n{result}"
                results.append(output)
                if cli:
                    cli.display_tool_result(result)
            except Exception as e:
                msg = f"❌ [{step_name}] 执行失败: {e}"
                results.append(msg)
                if cli:
                    cli.display_tool_result(msg)

        return "\n\n".join(results)

    async def run(self, task: str, stream=True, on_event=None, cli=None) -> str:
        """
        主循环：思考 → 选工具 → 执行 → 观察 → 循环

        Args:
            task: 用户任务
            stream: 是否流式输出
            on_event: 可选回调 dict (用于 Web UI)
            cli: SpiderCLI 实例 (用于 CLI 模式)

        Returns:
            最终回复内容
        """
        # 首次运行时加载 MCP 工具
        if self.mcp_manager and not hasattr(self, '_mcp_loaded'):
            await self._load_mcp()

        self._setup_messages(task)
        self._turn = 0
        self._start_time = datetime.now()
        self._conv_id = None

        # 持久化：创建会话，保存用户消息
        if self.memory:
            self._conv_id = self.memory.create_conversation(summary=task[:200])
            self.memory.save_message(self._conv_id, "user", task)

        # 执行技能预制步骤（如果有）
        if self._step_skills:
            if cli:
                cli.info("🔄 执行技能步骤...")
            for skill in self._step_skills:
                step_results = await self._execute_skill_steps(skill, cli=cli)
                # 将步骤结果注入到会话上下文
                self.messages.insert(-1, {
                    "role": "system",
                    "content": f"以下是根据技能「{skill.name}」自动执行的结果：\n\n{step_results}"
                })

        if on_event and on_event.get("turn_start"):
            await on_event["turn_start"](0, self.max_turns)

        for turn in range(self.max_turns):
            self._turn = turn + 1
            if on_event and on_event.get("turn_start"):
                await on_event["turn_start"](self._turn, self.max_turns)

            if stream:
                response = await self._think_stream(on_event=on_event, cli=cli)
            else:
                response = await self._think()

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

                # CLI 模式：用 Markdown 渲染最终回复
                if cli and not stream:
                    cli.display_response(content)
                elif cli and stream:
                    cli.stream_done()

                if on_event and on_event.get("done"):
                    await on_event["done"](content, elapsed)
                return content

            # 执行工具
            tool_call_content = response.get("content", "")
            for tc in response["tool_calls"]:
                if cli:
                    cli.display_tool_call(tc["name"], tc["arguments"])
                if on_event and on_event.get("tool_call"):
                    await on_event["tool_call"](tc["name"], tc["arguments"])

                result = await self.tools.execute(tc)

                if cli:
                    cli.display_tool_result(result)
                if on_event and on_event.get("tool_result"):
                    await on_event["tool_result"](tc["name"], result)

                # 将 tool call + result 加入对话
                args_str = json.dumps(tc["arguments"], ensure_ascii=False)
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

                # 持久化
                if self.memory and self._conv_id:
                    self.memory.save_message(
                        self._conv_id, "assistant",
                        tool_call_content,
                        {"tool_calls": [{"name": tc["name"], "args": tc["arguments"]}]},
                    )
                    self.memory.save_message(self._conv_id, "tool", result)

            # 保存 token 用量
            self._usage = response.get("usage")

            # 检查是否需要压缩上下文
            if self.context.should_compress(self.messages):
                if cli:
                    cli.info(f"📐 自动压缩上下文（节省空间）...")
                self.messages = await self.context.compress(self.messages, self.llm)

        # 达到最大轮数
        msg = f"⚠️ 达到最大轮数 ({self.max_turns})，任务可能未完成。"
        if self.memory and self._conv_id:
            self.memory.update_conversation(self._conv_id, turn_count=self._turn)
        if on_event and on_event.get("done"):
            await on_event["done"](msg, self._elapsed())
        return msg

    async def _think(self) -> dict:
        """非流式思考"""
        try:
            response = self.llm.think(self.messages, self.tools.schemas)
        except Exception as e:
            return {"content": f"思考出错: {e}", "tool_calls": [], "is_done": True}
        result = {
            "content": response.content or "",
            "tool_calls": response.tool_calls,
            "is_done": response.is_done,
            "usage": response.usage if hasattr(response, "usage") else None,
        }
        if response.reasoning_content:
            result["reasoning_content"] = response.reasoning_content
        return result

    async def _think_stream(self, on_event=None, cli=None) -> dict:
        """流式思考"""
        accumulated = ""
        first_chunk = True

        def on_content(chunk):
            nonlocal accumulated, first_chunk
            if first_chunk:
                first_chunk = False
            accumulated += chunk
            # CLI 模式直接输出
            if cli:
                cli.stream_response(chunk)
            if on_event and on_event.get("thinking_chunk"):
                asyncio.create_task(on_event["thinking_chunk"](chunk))

        def on_tool(tcs):
            pass

        try:
            result = self.llm.think_stream(self.messages, self.tools.schemas,
                                           on_content=on_content, on_tool=on_tool)
        except Exception as e:
            if on_event and on_event.get("error"):
                asyncio.create_task(on_event["error"](f"思考出错: {e}"))
            return {"content": f"思考出错: {e}", "tool_calls": [], "is_done": True}

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
