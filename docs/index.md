# Spider — 轻量级 Agent 系统

> **仿 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 设计模式的学习项目**  
> 通过复刻 Hermes 的核心设计模式，深入理解自主 Agent 系统的架构设计。

## 设计目标

| 目标 | 说明 |
|------|------|
| :target: **理解 Hermes** | 通过复刻关键模式，深入理解 Agent 系统设计 |
| :triangular_ruler: **最小可用** | 每个模块只实现核心逻辑，不做过度抽象 |
| :arrows_counterclockwise: **渐进构建** | 分阶段迭代：Agent 循环 → 子代理 → 技能系统 → 平台接入 |
| :memo: **记录过程** | 开发决策和对话保存在 `logs/conversations/` |

## 项目结构

```
spider/
├── main.py                # CLI 入口 + --web 启动
├── core/                  # 核心引擎
│   ├── agent.py           # Agent 循环 (ReAct)
│   ├── llm.py             # LLM 调用封装
│   ├── tool_registry.py   # 工具注册中心
│   ├── sub_agent.py       # 子代理系统
│   ├── skill_manager.py   # 技能系统
│   ├── memory.py          # 持久化记忆 (SQLite + FTS5 + 向量)
│   └── cli.py             # 终端渲染
├── web/                   # Web UI
│   ├── app.py             # FastAPI 后端 + SSE
│   ├── templates/         # HTML 模板
│   └── static/            # 前端静态文件
├── tools/                 # 内置工具集
│   ├── shell.py           # Shell 命令执行
│   ├── read_write.py      # 文件读写
│   ├── convert.py         # 文档格式转换
│   └── self_dev.py        # 自开发工具
├── skills/                # 技能文件 (YAML)
├── platforms/             # 平台适配器 (预留)
└── logs/                  # 开发记录
```

## 实现状态

| Phase | 状态 | 内容 |
|-------|------|------|
| **Phase 1** | :white_check_mark: 完成 | ReAct 循环、Tool Use、流式输出、CLI 双模式 |
| **Phase 2** | :white_check_mark: 完成 | 子代理、技能系统、记忆系统 |
| **Phase 3** | :white_check_mark: 完成 | Web UI、对话历史、工具调用可视化 |
| **Phase 4** | :arrows_counterclockwise: 进行中 | HITL、平台适配器、多 LLM 切换 |

## 参考

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — 本项目的主要设计参考
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling) — Tool call 标准
- [DeepSeek API](https://api-docs.deepseek.com/) — 底层 LLM 接口
