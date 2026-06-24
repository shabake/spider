#!/bin/bash
# Spider 依赖安装脚本

echo "🕷️ Spider 依赖安装"
echo "=================="

echo ""
echo "📦 安装 Python 转换库..."
python3 -m pip install python-docx PyMuPDF fpdf2 --break-system-packages 2>&1

echo ""
echo "🔔 可选：安装 LibreOffice（获得最好的转换质量）"
echo "   brew install libreoffice"
echo ""
echo "✅ 试试:"
echo "   python3 main.py \"把 ~/Desktop/test.docx 转成 PDF\""
