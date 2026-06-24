# 工具注册中心

**文件**: `core/tool_registry.py`
**类**: `Tool`, `ToolRegistry`

工具系统是 Agent 与外部世界交互的桥梁，采用 **函数 + JSON Schema** 注册模式。

## 职责

- 定义工具的标准化接口 (Tool)
- 提供工具的注册、查找、调度 (ToolRegistry)
- 自动生成 OpenAI 格式的 tool schema

## 设计理念

### 为什么用函数 + Schema？

LLM 本身无法直接执行代码或系统调用，它需要：
1. **知道有哪些工具可用** — `description` 字段
2. **知道怎么调用** — `parameters` (JSON Schema)
3. **把执行交给宿主** — tool_calls 机制

Spider 的工具系统遵循这一标准流程：
```
LLM 决定调用工具 → 返回 tool_calls → ToolRegistry.execute() → 结果返回 LLM
```

## 类结构

### Tool

```python
class Tool:
    def __init__(self, name, description, handler, parameters):
        self.name = name
        self.description = description
        self.handler = handler      # async function
        self.parameters = parameters  # JSON Schema

    @property
    def schema(self) -> dict:
        """OpenAI 格式的 tool schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    async def execute(self, arguments) -> str:
        """执行工具，返回字符串结果"""
```

### ToolRegistry

```python
class ToolRegistry:
    def register(self, name, description, handler, parameters):
        """注册工具"""

    def get(self, name) -> Tool | None:
        """按名称查找工具"""

    @property
    def schemas(self) -> list[dict]:
        """所有工具的 schema 列表"""

    async def execute(self, tool_call) -> str:
        """执行 tool_call，自动查找并运行"""
```

## Schema 定义示例

### Shell 工具
```python
SHELL_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "要执行的 shell 命令",
        },
        "timeout": {
            "type": "integer",
            "description": "超时秒数（默认 60）",
            "default": 60,
        },
    },
    "required": ["command"],
}
```

### 文件读取工具
```python
READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径"},
        "offset": {"type": "integer", "description": "起始行号", "default": 0},
        "limit": {"type": "integer", "description": "最大行数", "default": 2000},
    },
    "required": ["path"],
}
```

## 注册流程

```
工具函数 (async)  +  Schema (dict)
        │
        ▼
ToolRegister.register(name, description, handler, parameters)
        │
        ▼
ToolRegistry._tools[name] = Tool(name, description, handler, parameters)
        │
        ▼
Agent 启动循环时 → 读取 ToolRegistry.schemas → 传给 LLM
```

## 执行流程

```
LLM 返回: tool_call = {id, name="shell", arguments={command: "ls"}}
                              │
                              ▼
ToolRegistry.execute(tool_call)
         │
         ├── get("shell") → 找到 Tool
         │
         ├── Tool.execute({command: "ls"})
         │     │
         │     └── await handler(command="ls")  →  "file1.txt\nfile2.txt"
         │
         └── 返回结果字符串
```

## 内置工具

注册在 `main.py` 的 `create_agent()` 中：

| 工具名 | 描述 | handler | 来源 |
|--------|------|---------|------|
| `shell` | 执行 shell 命令 | `execute_shell()` | `tools/shell.py` |
| `read_file` | 读取文件内容 | `read_file()` | `tools/read_write.py` |
| `write_file` | 写入文件（覆盖） | `write_file()` | `tools/read_write.py` |
| `list_files` | 列出目录内容 | `list_files()` | `tools/read_write.py` |

## 扩展新工具

添加新工具只需三步：

```python
# 1. 定义处理函数
async def search_web(query: str) -> str:
    """网络搜索实现"""
    return "搜索结果..."

# 2. 定义 Schema
SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索关键词"},
    },
    "required": ["query"],
}

# 3. 注册到 Agent
agent.register_tool("search_web", "网络搜索", search_web, SEARCH_SCHEMA)
```

## 与 Hermes 的对应关系

| Hermes | Spider |
|--------|--------|
| `toolset` 插件 | `ToolRegistry` |
| 工具定义 (yaml) | `Tool` 类 + JSON Schema |
| `tool_call` 执行 | `ToolRegistry.execute()` |
| tool 执行结果处理 | 自动追加到 `messages` |
