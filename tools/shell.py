"""
Shell 工具 — 执行终端命令
类比 Hermes 的 terminal 模块
"""

import asyncio
import shlex


async def execute_shell(command: str, timeout: int = 60) -> str:
    """
    执行 shell 命令

    Args:
        command: 要执行的命令
        timeout: 超时秒数

    Returns:
        命令输出(stdout + stderr)
    """
    if not command or not command.strip():
        return "Error: empty command"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                error_text = stderr.decode("utf-8", errors="replace")
                if error_text:
                    output += f"\n[stderr]\n{error_text}"
            if proc.returncode != 0:
                output += f"\n[exit code: {proc.returncode}]"
            return output.strip() or "(命令执行完成，无输出)"
        except asyncio.TimeoutError:
            proc.kill()
            return f"Error: command timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"Error: command not found - {e}"
    except Exception as e:
        return f"Error: {e}"


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
