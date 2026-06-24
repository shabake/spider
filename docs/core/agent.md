# Agent 核心循环

**文件**: `core/agent.py`
**类**: `Agent`

Agent 是 Spider 的核心引擎，实现了 **ReAct (Reasoning + Acting)** 循环。

## 职责

- 接收用户任务并驱动 ReAct 循环
- 管理 LLM 会话上下文（消息历史）
- 调度工具执行
- 控制迭代轮数，防止无限循环

## 类结构

```python
class Agent:
    SYSTEM_PROMPT = """..."""

    def __init__(self, model="deepseek-v4-flash", max_turns=30,
                 api_key=None, base_url=None):
        self.llm = LLM(...)             # LLM 接口
        self.tools = ToolRegistry()     # 工具注册中心
        self.messages = []              # 对话历史
        self.max_turns = max_turns      # 最大轮数

    def register_tool(self, name, description, handler, parameters):
        """注册工具到 Agent"""

    async def run(self, task, stream=True) -> str:
        """主循环入口"""

    async def _think(self) -> dict:
        """非流式思考"""

    async def _think_stream(self) -> dict:
        """流式思考"""

    def get_conversation_log(self) -> str:
        """导出对话记录"""
```

## ReAct 循环详解

```
Agent.run(task)
  │
  ├── 初始化: system + user message
  │
  └── for turn in range(max_turns):
        │
        ├── LLM.think(messages, tools)
        │     │
        │     ├── finish_reason == "stop"  → 返回结果 ✅
        │     ├── finish_reason == "tool_calls" → 继续
        │     └── 有 content 无 tool_calls → 返回结果 ✅
        │
        ├── [对每个 tool_call]
        │     ├── ToolRegistry.execute(tc)
        │     ├── 追加 assistant 消息 (tool_call)
        │     └── 追加 tool 消息 (result)
        │
        └── 继续循环
```

## 关键方法

### `run(task, stream=True)`
主循环入口。参数：
- `task` — 用户任务字符串
- `stream` — 是否流式输出（默认开启）

返回 LLM 最终回复内容。

### `register_tool(name, description, handler, parameters)`
向 Agent 注册可用工具。参数直接透传给 `ToolRegistry.register()`。

### `set_system_prompt(prompt)`
自定义 system prompt，覆盖默认角色设定。

### `get_conversation_log()`
将当前会话导出为可读文本格式，包含用户、助手、工具调用的完整记录。

## 使用示例

```python
from core.agent import Agent
from tools.shell import execute_shell, SHELL_TOOL_SCHEMA

agent = Agent(api_key="sk-xxx")
agent.register_tool("shell", "执行命令", execute_shell, SHELL_TOOL_SCHEMA)

result = await agent.run("查看系统信息")
print(result)
```

## 错误处理

- 达到 `max_turns` 上限时返回警告信息
- 工具执行异常时错误信息会返回给 LLM，让 LLM 决定如何处理
- LLM API 调用异常会向上抛出，由调用方处理

## 与 Hermes 的对应关系

| Hermes | Spider |
|--------|--------|
| `agent.max_turns` | `Agent.max_turns` |
| CLI 主循环 | `Agent.run()` |
| `config.model` | `Agent.__init__(model=)` |
| Toolset 插件系统 | `Agent.register_tool()` |
