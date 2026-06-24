# Shell 工具

**文件**: `tools/shell.py`
**函数**: `execute_shell()`

## 功能

执行 shell 命令并返回输出（stdout + stderr）。

## 定义

```python
async def execute_shell(command: str, timeout: int = 60) -> str:
```

参数：
- `command` — 要执行的 shell 命令字符串
- `timeout` — 超时秒数（默认 60s）

返回：
- 命令的 stdout + stderr 输出
- 命令退出码（非零时附加）

## Schema

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

## 使用示例

直接使用：
```python
from tools.shell import execute_shell
result = await execute_shell("ls -la")
print(result)
```

通过 Agent：
```python
agent.register_tool("shell", "执行 shell 命令", execute_shell, SHELL_TOOL_SCHEMA)
result = await agent.run("查看当前目录文件")
```

## 错误处理

| 场景 | 返回值 |
|------|--------|
| 空命令 | `Error: empty command` |
| 命令超时 | `Error: command timed out after 60s` |
| 命令不存在 | `Error: command not found - ...` |

## 安全说明

- 命令以当前用户权限执行
- 有 60 秒超时保护，防止命令挂死
- 超时后进程会被 kill
