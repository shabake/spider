"""
Spider 工具注册中心
类比 Hermes 的 toolset 系统 — 工具以函数 + JSON Schema 注册，LLM 通过 tool_calls 调用

风险等级 (risk_level):
  safe      — 安全操作，直接执行（如 read_file, list_files）
  confirm   — 执行前需用户确认（如 shell, write_file）
  dangerous — 默认禁止，需手动放行（如 rm -rf / 等高风险）
"""

import json

RISK_SAFE = "safe"
RISK_CONFIRM = "confirm"
RISK_DANGEROUS = "dangerous"

# 风险等级颜色标签（用于显示）
RISK_LABELS = {
    RISK_SAFE: "🟢 safe",
    RISK_CONFIRM: "🟡 confirm",
    RISK_DANGEROUS: "🔴 dangerous",
}


class Tool:
    """单个工具的定义"""

    def __init__(self, name: str, description: str, handler, parameters: dict,
                 risk_level: str = RISK_SAFE):
        self.name = name
        self.description = description
        self.handler = handler
        self.parameters = parameters
        self.risk_level = risk_level  # safe | confirm | dangerous

    @property
    def schema(self) -> dict:
        """返回 OpenAI 格式的 tool schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    async def execute(self, arguments: dict) -> str:
        """执行工具并返回结果"""
        try:
            result = await self.handler(**arguments)
            return str(result)
        except Exception as e:
            return f"Error executing {self.name}: {e}"


class ToolRegistry:
    """工具注册中心 — 注册、查找、执行"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        # 用户自定义风险覆盖（工具名 → risk_level）
        self._risk_overrides: dict[str, str] = {}

    def register(self, name: str, description: str, handler, parameters: dict,
                 risk_level: str = RISK_SAFE):
        """注册一个工具

        Args:
            name: 工具名
            description: 描述
            handler: 异步处理函数
            parameters: JSON Schema 参数定义
            risk_level: 风险等级（safe/confirm/dangerous）
        """
        self._tools[name] = Tool(name, description, handler, parameters, risk_level)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def schemas(self) -> list[dict]:
        """返回所有工具的 OpenAI tool schema 列表"""
        return [t.schema for t in self._tools.values()]

    @property
    def names(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(self, tool_call: dict) -> str:
        """执行一个 tool call {id, name, arguments}"""
        tool = self.get(tool_call["name"])
        if not tool:
            return f"Error: unknown tool '{tool_call['name']}'. Available: {', '.join(self.names)}"
        return await tool.execute(tool_call["arguments"])

    def get_risk_level(self, name: str) -> str | None:
        """获取工具的风险等级（考虑用户覆盖）"""
        if name in self._risk_overrides:
            return self._risk_overrides[name]
        tool = self._tools.get(name)
        return tool.risk_level if tool else None

    def set_risk_override(self, name: str, risk_level: str):
        """用户自定义覆盖某个工具的风险等级"""
        if risk_level not in (RISK_SAFE, RISK_CONFIRM, RISK_DANGEROUS):
            raise ValueError(f"无效风险等级: {risk_level}")
        self._risk_overrides[name] = risk_level
