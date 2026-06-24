"""
Spider 工具注册中心
类比 Hermes 的 toolset 系统 — 工具以函数 + JSON Schema 注册，LLM 通过 tool_calls 调用
"""

import json


class Tool:
    """单个工具的定义"""

    def __init__(self, name: str, description: str, handler, parameters: dict):
        self.name = name
        self.description = description
        self.handler = handler
        self.parameters = parameters

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

    def register(self, name: str, description: str, handler, parameters: dict):
        """注册一个工具"""
        self._tools[name] = Tool(name, description, handler, parameters)

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
