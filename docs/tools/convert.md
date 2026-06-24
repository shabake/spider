# 文档格式转换工具

**文件**: `tools/convert.py`
**函数**: `docx_to_pdf()`, `pdf_to_docx()`

## 功能

- Word (.docx) → PDF
- PDF → Word (.docx)

## 自动后端选择

工具自动检测可用的转换后端，优先级：

| 优先级 | 后端 | 安装方式 | 转换质量 |
|--------|------|---------|---------|
| 1 | LibreOffice | `brew install libreoffice` | ⭐⭐⭐ 保留排版 |
| 2 | Python 库 | `pip3 install python-docx PyMuPDF fpdf2` | ⭐⭐ 纯文本 |

## 函数

### docx_to_pdf

```python
async def docx_to_pdf(input_path: str, output_path: str = None) -> str:
```

- `input_path`: .docx 文件路径
- `output_path`: 输出路径（可选，默认同目录）

### pdf_to_docx

```python
async def pdf_to_docx(input_path: str, output_path: str = None) -> str:
```

## Schema

```python
DOCX_TO_PDF_SCHEMA = {
    "properties": {
        "input_path": {"type": "string", "description": "输入的 Word 文件路径"},
        "output_path": {"type": "string", "description": "输出的 PDF 路径（可选）"},
    },
    "required": ["input_path"],
}
```

## 错误处理

| 场景 | 提示 |
|------|------|
| 文件不存在 | ❌ 文件不存在 |
| 格式不支持 | ❌ 需要 .docx / .pdf |
| 无可用后端 | 提示安装 LibreOffice 或 Python 库 |
