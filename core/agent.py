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

    # StraTA 战略推理模式（通过 --strategy 启用）
    STRATEGY_PROMPT = """You are a strategic reasoning agent using a StraTA-style workflow.

For every task:
1. First infer the real objective behind the user's request.
2. Build a global strategy before answering.
3. Identify constraints, risks, hidden assumptions, and success criteria.
4. Break the task into execution phases.
5. Before each phase, check whether it still serves the global strategy.
6. After each phase, self-check for drift, shallow reasoning, impractical advice, or aesthetic-only answers without business value.
7. Revise internally.
8. Output only the corrected final answer.

Do not expose internal chain-of-thought. Provide concise strategic reasoning, clear decisions, and actionable results.
Prioritize practical usefulness, local context, commercial effect, feasibility, and user intent over generic answers."""

    def __init__(self, model="deepseek-v4-flash", max_turns=30,
                 api_key=None, base_url=None, memory_store=None,
                 strategy_mode=False, confirm_enabled=True,
                 plan_mode=False):
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
        self.strategy_mode = strategy_mode  # StraTA 战略推理模式
        self.confirm_enabled = confirm_enabled  # 人机交互确认开关
        self.plan_mode = plan_mode  # Plan-Then-Execute

        # 持久化记忆工具
        if self.memory:
            self._register_memory_tools()

    def register_tool(self, name: str, description: str, handler, parameters: dict,
                      risk_level: str = "safe"):
        """注册一个工具

        Args:
            name: 工具名
            description: 描述
            handler: 异步处理函数
            parameters: JSON Schema
            risk_level: 风险等级 safe（默认直接执行）| confirm（需确认）| dangerous（禁止）
        """
        self.tools.register(name, description, handler, parameters, risk_level=risk_level)

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
            risk_level="safe",
        )
        self.register_tool(
            "save_memory",
            "保存一条关键信息到长期记忆。"
            "当发现重要的用户偏好、项目配置、或者值得记住的任务结果时使用。"
            "保存后未来任何对话都可以回忆起来。",
            self._save_memory_wrapper,
            SAVE_MEMORY_SCHEMA,
            risk_level="safe",
        )
        self.register_tool(
            "conversations",
            "查看最近的对话历史记录。",
            self.memory.list_conversations,
            LIST_CONVERSATIONS_SCHEMA,
            risk_level="safe",
        )

    async def _save_memory_wrapper(self, content: str, category: str = "general"):
        """包装 save_memory，自动记录来源会话 ID"""
        return await self.memory.save_memory(content, category, source_conv_id=self._conv_id)

    async def _confirm_tool(self, tool_call: dict, cli=None, on_event=None) -> bool:
        """检查工具是否需要确认，如需则等待用户响应

        Args:
            tool_call: {id, name, arguments}
            cli: 可选的 SpiderCLI 实例
            on_event: 可选的事件回调

        Returns:
            True = 允许执行，False = 用户拒绝
        """
        name = tool_call["name"]
        risk = self.tools.get_risk_level(name)
        if risk == "safe":
            return True

        # 用户关闭了确认模式 — safe/confirm 都放行，dangerous 仍拦截
        if not self.confirm_enabled:
            return risk != "dangerous"

        # 构建确认信息
        args_str = ", ".join(f"{k}={v}" for k, v in tool_call.get("arguments", {}).items())
        message = f"🧑‍⚖️ 需要确认\n  🛠️  {name}({args_str})\n  风险等级: {risk}\n  确认执行？"

        # Web 模式：走 SSE 确认回调
        if on_event and on_event.get("confirm"):
            if risk == "dangerous":
                message = f"⚠️ 高风险操作\n  🛠️  {name}({args_str})\n  风险等级: {risk}\n  仅在你完全信任此操作时确认"
            return await on_event["confirm"](message)

        # CLI 模式：终端等待输入
        if cli:
            cli.muted(f"⚠️  需要确认 ({risk})")
            cli.muted(f"  🛠️  {name}({args_str})")
            if risk == "dangerous":
                cli.error("  ⚠️  高风险操作，请谨慎确认")

            # 暂停 Escape 监听，避免干扰 input()
            cli.stop_abort()
            try:
                # 清空 stdin 残留
                cli.drain_stdin()
                answer = input("  ▸ 继续执行？(y/N): ")
            finally:
                cli.watch_abort()

            return answer.strip().lower() in ("y", "yes", "是")

        # fallback：没有 CLI 也没有 Web，直接放行
        return True

    @staticmethod
    def _is_complex_task(task: str) -> bool:
        """判断任务是否复杂，需要先规划再执行"""
        if not task:
            return False
        # 长任务（超过 80 字）
        if len(task) > 80:
            return True
        # 包含多个要求（换行、数字列表、或中文顿号分隔）
        indicators = ["\n", "1.", "2.", "、", "并且", "同时", "分别", "先", "然后", "最后"]
        return any(ind in task for ind in indicators)

    async def _make_plan(self, task: str) -> str:
        """生成执行计划"""
        plan_prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个任务规划专家。分析以下任务，输出一个清晰的执行计划。\n"
                    "格式要求：\n"
                    "  1. 第一步：xxx\n"
                    "  2. 第二步：xxx\n"
                    "  ...\n\n"
                    "只输出计划，不需要额外解释。"
                ),
            },
            {"role": "user", "content": f"任务：{task}"},
        ]
        try:
            resp = self.llm.think(plan_prompt)
            return resp.content or "(计划生成失败)"
        except Exception as e:
            return f""

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

        # StraTA 战略推理模式 — 追加到系统提示
        if self.strategy_mode:
            system += "\n\n" + self.STRATEGY_PROMPT

        # 注入相关记忆（仅复杂任务自动 recall，简单任务不浪费 token）
        if self.memory and (self.plan_mode or len(task) > 30):
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
                # 风险确认
                fake_tc = {"name": tool_name, "arguments": params}
                if not await self._confirm_tool(fake_tc, cli=cli):
                    msg = f"⏭️ [{step_name}] 已跳过（用户拒绝）"
                    results.append(msg)
                    if cli:
                        cli.display_tool_result(msg)
                    continue

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

        # ── Plan-Then-Execute ──────────────────────────────────
        if self.plan_mode and self._is_complex_task(task):
            if cli:
                cli.info("📋 正在制定执行计划...")
            plan = await self._make_plan(task)
            if plan:
                # 将计划注入上下文
                self.messages.insert(-1, {
                    "role": "system",
                    "content": f"以下是执行计划，请按步骤执行：\n\n{plan}"
                })
                if cli:
                    cli.muted(f"📋 执行计划已生成")
                    for line in plan.strip().split("\n"):
                        if line.strip():
                            cli.muted(f"  {line.strip()}")

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

            # ── 执行工具（支持并行） ──────────────────────────────
            tool_call_content = response.get("content", "")
            tcs = response["tool_calls"]
            reasoning_rc = response.get("reasoning_content")

            # 1. 显示所有工具调用
            for tc in tcs:
                if cli:
                    cli.display_tool_call(tc["name"], tc["arguments"])
                if on_event and on_event.get("tool_call"):
                    await on_event["tool_call"](tc["name"], tc["arguments"])

            # 2. 风险确认检查（串行，每个都需要用户操作）
            approved = []
            for tc in tcs:
                ok = await self._confirm_tool(tc, cli=cli, on_event=on_event)
                approved.append(ok)

            # 3. 并行执行所有通过的工具
            run_indices = [i for i, ok in enumerate(approved) if ok]
            if run_indices:
                async def _run_one(i):
                    return await self.tools.execute(tcs[i])

                done = await asyncio.gather(*[_run_one(i) for i in run_indices])
                results_map = dict(zip(run_indices, done))
            else:
                results_map = {}

            results = []
            for i in range(len(tcs)):
                if i in results_map:
                    results.append(results_map[i])
                else:
                    results.append("❌ 已取消：用户拒绝了此操作")

            # 4. 显示结果 + 追加到对话
            for i, tc in enumerate(tcs):
                result = results[i]

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
                if reasoning_rc:
                    msg["reasoning_content"] = reasoning_rc
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
