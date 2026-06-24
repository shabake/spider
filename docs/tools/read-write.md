# 文件读写工具

**文件**: `tools/read_write.py`
**函数**: `read_file()`, `write_file()`, `list_files()`

## read_file

读取文件内容，支持行号范围控制。

```python
async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
```

参数：
- `path` — 文件路径（支持 `~` 展开）
- `offset` — 开始行号（从 0 开始）
- `limit` — 最大读取行数

返回：文件头信息 + 内容

### Schema
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

## write_file

写入文件（覆盖已有内容），自动创建父目录。

```python
async def write_file(path: str, content: str) -> str:
```

参数：
- `path` — 文件路径
- `content` — 要写入的内容

返回：`✅ 已写入 {path} ({n} 字符)`

### Schema
```python
WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "文件内容"},
    },
    "required": ["path", "content"],
}
```

## list_files

列出目录内容，显示文件和子目录。

```python
async def list_files(path: str = ".") -> str:
```

参数：
- `path` — 目录路径（默认当前目录）

返回格式：
```
📁 /path/to/dir/
  📁 subdir/
  📄 file.txt  (1234 bytes)
  📄 script.py  (567 bytes)
```

### Schema
```python
LIST_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "目录路径", "default": "."},
    },
}
```

## 错误处理

| 场景 | 返回值 |
|------|--------|
| 文件不存在 | `Error: file not found: {path}` |
| 路径是目录 | `Error: not a file: {path}` |
| 目录不存在 | `Error: path not found: {path}` |
| 写入权限不足 | `Error writing file: ...` |
