# 🕷️ Spider

**轻量级 Agent 系统 — 仿 Hermes 设计模式的学习项目**

通过复刻 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的核心设计模式（ReAct 循环、Tool Use、子代理、技能系统），深入理解自主 Agent 系统的架构设计。

## 快速开始

```bash
# 安装依赖
pip install openai pyyaml rich

# 设置 API Key
export DEEPSEEK_API_KEY="sk-xxxx"

# 交互式 CLI
python main.py -i

# Web UI
python main.py --web
# 访问 http://127.0.0.1:8888
```

## 能力一览

| 功能 | 说明 | 状态 |
|------|------|------|
| ReAct 循环 | 思考→行动→观察，最大 30 轮 | ✅ |
| Tool Use | shell、文件读写、文档转换等 18 个工具 | ✅ |
| 子代理 | 任务拆解，并行执行，最多 3 个并发 | ✅ |
| 技能系统 | 经验保存为 YAML，关键词触发自动匹配 | ✅ |
| 记忆系统 | SQLite + FTS5 + 向量语义搜索 | ✅ |
| Web UI | FastAPI + SSE，Claude 风格深色主题 | ✅ |
| 自开发 | self_find / self_edit / self_commit 等 | ✅ |
| MCP 扩展 | 支持社区 MCP 协议服务（computer-use 等） | ✅ |
| Human-in-the-Loop | 关键操作确认 | 🔄 |
| 多 LLM 切换 | DeepSeek / OpenAI / Claude | 📅 |
| 平台适配 | 飞书 / Discord / Telegram | 📅 |

## 文档

详细文档请见 [docs/](docs/index.md) 目录（MkDocs 文档站）：

- [快速开始](docs/快速开始.md) — 安装、配置、运行
- [使用指南](docs/使用指南.md) — 三种模式、场景示例、FAQ
- [架构设计](docs/架构设计.md) — 三层架构、数据流、模块依赖
- [核心模块](docs/核心模块.md) — Agent / LLM / 工具 / 子代理 / 技能 / 记忆
- [工具集](docs/工具集.md) — Shell / 文件 / 转换 / 自开发
- [设计模式](docs/设计模式.md) — Hermes 对照参考
- [路线图](docs/路线图.md) — 后续开发计划

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key（必填） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | API 地址 |
| `DEEPSEEK_EMBEDDING_MODEL` | `deepseek-embedding` | Embedding 模型 |

## 参考

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — 主要设计参考
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [DeepSeek API](https://api-docs.deepseek.com/)
