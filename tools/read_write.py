"""
文件读写工具
"""

import os


async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    """
    读取文件内容

    Args:
        path: 文件路径
        offset: 起始行号
        limit: 最大读取行数

    Returns:
        文件内容
    """
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    if not os.path.isfile(path):
        return f"Error: not a file: {path}"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total = len(lines)
        start = max(0, offset)
        end = min(total, start + limit)
        content = "".join(lines[start:end])
        info = f"File: {path} ({total} lines, showing {start+1}-{end})"
        return f"{info}\n{'-'*40}\n{content}"
    except Exception as e:
        return f"Error reading file: {e}"


async def write_file(path: str, content: str) -> str:
    """
    写入文件（会覆盖已有内容）

    Args:
        path: 文件路径
        content: 文件内容

    Returns:
        写入结果
    """
    path = os.path.expanduser(path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ 已写入 {path} ({len(content)} 字符)"
    except Exception as e:
        return f"Error writing file: {e}"


async def list_files(path: str = ".") -> str:
    """
    列出目录内容

    Args:
        path: 目录路径

    Returns:
        目录列表
    """
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"Error: path not found: {path}"
    if not os.path.isdir(path):
        return f"Error: not a directory: {path}"

    try:
        entries = os.listdir(path)
        entries.sort()
        lines = [f"📁 {path}/"]
        for entry in entries:
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                lines.append(f"  📁 {entry}/")
            else:
                size = os.path.getsize(full)
                lines.append(f"  📄 {entry}  ({size} bytes)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing directory: {e}"


READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径"},
        "offset": {"type": "integer", "description": "起始行号", "default": 0},
        "limit": {"type": "integer", "description": "最大读取行数", "default": 2000},
    },
    "required": ["path"],
}

WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "文件内容"},
    },
    "required": ["path", "content"],
}

LIST_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "目录路径", "default": "."},
    },
}
