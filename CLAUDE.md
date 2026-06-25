# Spider — 项目指南

## 项目简介
轻量级 Agent 系统，仿 Hermes Agent 设计模式的学习项目。
Python 实现，使用 DeepSeek API，支持 CLI/Web 两种交互模式。

## 开发规范

### 文档优先
- **改代码时顺手更新对应文档** — 每次修改功能或增减工具后，检查 `docs/` 下对应的 `.md` 文件是否需要同步更新
- 文档站用 MkDocs + Material 主题运行，本地预览：`python -m mkdocs serve`
- 目录结构见 `mkdocs.yml` 的 `nav` 配置

### 涉及工具变更时
- `tools/shell.py` / `tools/read_write.py` → 更新 `docs/工具集.md`
- 新增/修改核心模块 → 更新 `docs/核心模块.md`
- 新增/修改 API 参数或启动方式 → 更新 `docs/使用指南.md`

### 代码风格
- Python 3.10+ async/await
- 核心逻辑在 `core/`，工具在 `tools/`
- 工具注册使用 JSON Schema 格式

### Git
- Commit message 中文，用 emoji 分类头部（🎨 ✨ 🐛 📚 🔧）
- 提交前 review 改动
