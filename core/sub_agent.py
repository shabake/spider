"""
Spider 子代理系统 (Delegation)

类比 Hermes 的 delegation 模块：
- 主 Agent 将子任务委托给子 Agent
- 子 Agent 独立运行，共享主 Agent 的工具和配置
- 支持并发控制
- 支持 Profile 角色（子 Agent 使用指定角色的提示词和工具）

用法：
    pool = SubAgentPool(api_key=key, base_url=url, tools=tool_registry)
    result = await pool.delegate("查询磁盘空间")
    result = await pool.delegate("审查代码", profile="reviewer")
"""

import asyncio
import json
import time
import uuid
from .agent import Agent
from .llm import LLM


class SubAgentPool:
    """子代理池 — 管理并发子 Agent"""

    def __init__(self, api_key: str = None, base_url: str = None,
                 tools=None, max_concurrent: int = 3, parent_agent: Agent = None,
                 profile_loader=None):
        """
        Args:
            api_key: DeepSeek API Key
            base_url: API base URL
            tools: ToolRegistry 实例（共享父 Agent 的工具）
            max_concurrent: 最大并行子 Agent 数
            parent_agent: 父 Agent（用于共享配置）
            profile_loader: 可选的 profile 加载函数 (name) -> dict | None
        """
        self.api_key = api_key
        self.base_url = base_url
        self._tools = tools
        self.max_concurrent = max_concurrent
        self._parent = parent_agent
        self._running: dict[str, asyncio.Task] = {}
        self._results: dict[str, str] = {}
        self.profile_loader = profile_loader

    async def delegate(self, task: str, context: str = "", profile: str = "") -> str:
        """
        创建子 Agent 执行任务

        Args:
            task: 子任务描述
            context: 附加上下文（可选）
            profile: 角色名（可选），对应 profiles/{name}.yaml
                     指定后子 Agent 使用该角色的 system prompt 和工具白名单

        Returns:
            子 Agent 的执行结果
        """
        # 并发限制
        if len(self._running) >= self.max_concurrent:
            done, _ = await asyncio.wait(
                self._running.values(),
                return_when=asyncio.FIRST_COMPLETED
            )
            for d in done:
                tid = [k for k, v in self._running.items() if v == d][0]
                self._running.pop(tid, None)

        # 创建子 Agent（子 Agent 不弹确认，由主 Agent 管控）
        child = Agent(api_key=self.api_key, base_url=self.base_url, confirm_enabled=False)

        # 应用 Profile（如果有）
        profile_data = None
        if profile and self.profile_loader:
            profile_data = self.profile_loader(profile)

        if profile_data and profile_data.get("prompt"):
            child.SYSTEM_PROMPT = profile_data["prompt"].strip()
            prof_tools = profile_data.get("tools", None)
        else:
            child.SYSTEM_PROMPT = (
                "你是一个专注于完成子任务的 Spider 子代理。\n"
                "完成你的任务后，直接输出结果，不需要额外的解释。\n"
                "如果任务无法完成，说明原因即可。"
            )
            prof_tools = None

        # 注册工具（受 Profile 白名单控制）
        if self._tools:
            for name in self._tools.names:
                if prof_tools is not None and name not in prof_tools:
                    continue
                tool = self._tools.get(name)
                child.register_tool(name, tool.description, tool.handler, tool.parameters)

        # 应用 Profile 的风险覆盖
        if profile_data:
            overrides = profile_data.get("risk_overrides", {}) or {}
            for tool_name, risk in overrides.items():
                try:
                    child.tools.set_risk_override(tool_name, risk)
                except Exception:
                    pass

        # 拼接上下文
        full_task = task
        if context:
            full_task = f"{task}\n\n背景信息:\n{context}"

        # 异步执行
        task_id = str(uuid.uuid4())[:8]
        print(f"    └─ 子代理 [{task_id}] 开始: {task[:60]}...")

        async def run_child():
            try:
                result = await child.run(full_task, stream=False)
                return result
            except Exception as e:
                return f"子代理执行失败: {e}"

        future = asyncio.ensure_future(run_child())
        self._running[task_id] = future

        result = await future
        self._running.pop(task_id, None)
        self._results[task_id] = result

        print(f"    └─ 子代理 [{task_id}] 完成")
        return f"[子代理 {task_id} 的结果]:\n{result}"

    def running_count(self) -> int:
        """当前运行中的子 Agent 数量"""
        return len(self._running)

    @property
    def is_busy(self) -> bool:
        """是否达到并发上限"""
        return len(self._running) >= self.max_concurrent


# ── Tool Schema ─────────────────────────────────────────────

DELEGATE_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "要委托给子 Agent 的任务描述，越具体越好",
        },
        "context": {
            "type": "string",
            "description": "附加上下文，帮助子 Agent 理解任务背景",
        },
        "profile": {
            "type": "string",
            "description": "子 Agent 的角色名（对应 profiles/{name}.yaml）。"
                           "可选值: coding（编程）, reviewer（代码审查）, finance（财务）。"
                           "指定后子 Agent 使用该角色的专业技能和工具。"
                           "不指定则使用通用子代理。",
        },
    },
    "required": ["task"],
}
