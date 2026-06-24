# 🕷️ Spider

**轻量级 Agent 系统 — 仿 Hermes 设计模式的学习项目**

通过复刻 Hermes Agent 的核心设计模式（ReAct 循环、Tool Use、子代理、技能系统），
深入理解自主 Agent 系统的架构设计。

## 快速开始

```bash
cd /Users/mac/Desktop/Project/spider

# 安装依赖
pip install -r requirements.txt

# 设置 API Key
export DEEPSEEK_API_KEY="sk-xxxx"

# 交互式 CLI
python main.py -i

# 单次任务
python main.py "帮我看看当前目录有哪些文件"

# Web UI
python main.py --web
open http://127.0.0.1:8888
```

## 功能一览

### Phase 1 — Agent 核心
- ✅ **ReAct 循环**：思考 → 行动 → 观察，迭代解决问题
- ✅ **Tool Use**：统一的工具注册和执行系统（JSON Schema）
- ✅ **流式输出**：SSE 实时推送思考过程
- ✅ **CLI 双模式**：交互式 + 单次任务

### Phase 2 — 子代理 & 技能
- ✅ **子代理 (SubAgent)**：任务拆解、并行执行、上下文隔离
- ✅ **技能系统 (Skill Manager)**：经验保存为 YAML、关键词匹配自动触发
- ✅ **记忆系统**：SQLite 持久化 + FTS5 全文搜索 + 语义向量检索

### Phase 3 — Web UI
- ✅ **FastAPI 后端**：REST API + SSE 实时推送
- ✅ **Claude 风格前端**：深色主题、Markdown 渲染、代码高亮
- ✅ **对话历史管理**：浏览、加载、删除历史对话
- ✅ **工具调用可视化**：可折叠的参数/结果面板

### Phase 4 — 进行中
- 🔄 **Human-in-the-Loop**：关键操作前暂停等待用户确认
- 🔄 **平台适配器**：统一接口，支持 Web / CLI / 飞书 / Discord
- 🔄 **多 LLM 切换**：DeepSeek / OpenAI / Anthropic / Ollama

## 架构

```
Spider/
├── main.py              # 入口 CLI + Banner
├── core/                # 核心引擎
│   ├── agent.py         # Agent 循环 (ReAct)
│   ├── llm.py           # LLM 封装 (流式 + embedding)
│   ├── tool_registry.py # 工具注册中心
│   ├── sub_agent.py     # 子代理系统
│   ├── skill_manager.py # 技能管理器
│   └── memory.py        # 持久化记忆 (SQLite + FTS5 + 向量)
├── tools/               # 内置工具
│   ├── shell.py         # Shell 执行
│   ├── read_write.py    # 文件读写
│   ├── convert.py       # 文档转换 (docx/pdf)
│   └── self_dev.py      # 自开发工具 (find/map/review/edit/commit)
├── web/                 # Web UI
│   ├── app.py           # FastAPI 后端 + SSE
│   ├── static/          # 前端静态文件
│   └── templates/       # HTML 模板
├── platforms/           # 平台适配器 (进行中)
├── skills/              # 技能文件 (YAML)
└── logs/                # 开发日志
```

## 设计参考

| Hermes 模式 | Spider 实现 |
|------------|-------------|
| ReAct 循环 | `Agent.run()` — 思考→工具→观察→循环 |
| Tool System | `ToolRegistry` — JSON Schema 驱动的工具注册 |
| Delegation | `SubAgentPool` — 子代理并发执行 |
| Skill System | `SkillManager` — YAML 技能文件 + 关键词匹配 |
| Memory | `MemoryStore` — SQLite + FTS5 + 向量语义检索 |
| Platform Adapters | `platforms/` — 进行中 |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key（必填） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | API 地址 |
| `DEEPSEEK_EMBEDDING_MODEL` | `deepseek-embedding` | Embedding 模型 |
