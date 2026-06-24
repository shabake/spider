# 🕷️ Spider

**轻量级 Agent 系统 — 仿 Hermes 设计模式的学习项目**

Spider 是一个从零复刻 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 核心设计模式的教育项目，旨在深入理解自主 Agent 系统的架构原理。

## 设计目标

| 目标 | 说明 |
|------|------|
| 🎯 **理解 Hermes** | 通过复刻关键模式，深入理解 Agent 系统设计 |
| 📐 **最小可用** | 每个模块只实现核心逻辑，不做过度抽象 |
| 🔄 **渐进构建** | 分阶段迭代：Agent 循环 → 子代理 → 技能系统 → 平台接入 |
| 📝 **记录过程** | 开发决策和对话保存在 `logs/conversations/` |

## 快速开始

```bash
cd /Users/mac/Desktop/Project/spider

# 安装依赖
pip install openai pyyaml fastapi uvicorn --break-system-packages

# 设置 DeepSeek API Key
export DEEPSEEK_API_KEY="sk-xxxx"

# 单次任务模式
python main.py "帮我看看当前目录有哪些文件"

# 交互式模式
python main.py -i

# Web UI 模式 (浏览器访问 http://127.0.0.1:8888)
python main.py --web
```

## 项目结构

```
spider/
├── main.py                    # CLI 入口 + --web 启动
├── core/                      # 核心引擎
│   ├── agent.py               # Agent 循环 (ReAct)
│   ├── llm.py                 # LLM 调用封装 (streaming + tool calls)
│   ├── tool_registry.py       # 工具注册中心
│   ├── sub_agent.py           # 子代理系统 (Delegation) [P2]
│   ├── skill_manager.py       # 技能系统 (Skill Manager) [P2]
│   └── memory.py              # SQLite 持久化记忆 [P3]
├── web/                       # Web UI [P3]
│   ├── app.py                 # FastAPI 后端 + SSE 流
│   ├── templates/index.html   # 聊天界面
│   └── static/                # CSS + JS
├── tools/                     # 内置工具集
│   ├── shell.py               # Shell 命令执行
│   ├── read_write.py          # 文件读写操作
│   └── convert.py             # 文档格式转换
├── skills/                    # 技能文件
│   └── disk-check.yaml        # 示例技能
├── web/                       # Web UI
│   ├── app.py                 # FastAPI 后端
│   ├── static/                # 前端静态资源
│   └── templates/index.html   # 聊天界面
├── platforms/                 # 平台适配器 (预留)
├── docs/                      # 设计文档
└── logs/conversations/        # 开发记录
```

## 实现进度

### ✅ Phase 1 — Agent 核心 (已完成)

| 功能 | 说明 |
|------|------|
| ReAct 循环 | 思考→行动→观察，最大30轮 |
| Tool Use | shell、文件读写等内置工具 |
| 流式输出 | 实时显示 LLM 回复 |
| CLI 入口 | 单次任务 + 交互式模式 |

### ✅ Phase 2 — 扩展能力 (已完成)

| 功能 | 说明 |
|------|------|
| 子代理 (Delegation) | 主 Agent 可派生子 Agent 并行执行 |
| 技能系统 | 将方法保存为 YAML 技能，自动匹配 |
| 文档转换 | docx ↔ PDF |

### ✅ Phase 3 — 记忆 + Web (已完成)

| 功能 | 说明 |
|------|------|
| SQLite 持久化 | 对话历史、关键记忆存储 |
| 向量语义搜索 | embedding + cosine similarity 语义检索 |
| FTS5 + LIKE | 关键词搜索作为语义的补充和保底 |
| Web UI | FastAPI + SSE 实时聊天界面 |

### ✅ Phase 3.5 — 自我开发能力 (已完成)

| 功能 | 说明 |
|------|------|
| `self_map()` | 查看自己的项目结构和模块职责 |
| `self_find()` | 语义搜索自己的源码，找到函数/类/变量位置 |
| `self_validate()` | 语法验证，确保修改后的代码没错 |
| `self_review()` | git diff 审查，看看改了哪些文件 |
| `self_edit()` | 安全修改代码：自动备份→替换→语法验证→失败回滚 |
| `self_commit()` | 自动 git add → commit |

### 📅 Phase 4 — 能力增强 (计划中)

| 优先级 | 功能 | 说明 |
|--------|------|------|
| ⭐⭐⭐ | 人机交互中断 | Agent 执行关键操作前可等待用户确认/输入 |
| ⭐⭐⭐ | 平台适配器 | 统一接口适配飞书、Discord、Web 等多端 |
| ⭐⭐ | 工具权限体系 | 按风险等级分级：直接执行 / 需确认 / 禁止 |
| ⭐⭐ | 多 LLM 切换 | 通过配置文件切换 DeepSeek / OpenAI / Claude 等 |
| ⭐⭐ | Agent 状态序列化 | 中断恢复：Agent 可保存当前状态，下次继续 |
| ⭐ | 配置管理 | YAML 配置文件替代环境变量散养 |
| ⭐ | 插件化工具加载 | tools/ 目录下的 .py 自动注册为工具 |
| ⭐ | 单元测试 | 为核心模块编写测试 |
| ⭐ | 任务队列/调度 | 支持异步任务排队、定时触发 |
| ⭐ | 人机协作模式 | 从全自主到半自动可配置，关键步骤交给人决策 |

## 参考

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — 本项目的主要设计参考
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling) — Tool call 标准
- [DeepSeek API](https://api-docs.deepseek.com/) — 底层 LLM 接口
