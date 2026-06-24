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

# 运行单次任务
python main.py "帮我看看当前目录有哪些文件"

# 交互式模式
python main.py -i
```

## 架构

```
Spider/
├── main.py          # 入口 CLI
├── core/            # 核心引擎
│   ├── agent.py     # Agent 循环 (ReAct)
│   ├── llm.py       # LLM 调用封装
│   └── tool_registry.py  # 工具注册中心
├── tools/           # 内置工具
│   ├── shell.py     # Shell 执行
│   └── read_write.py  # 文件读写
├── logs/conversations/  # 对话记录
└── platforms/       # 平台适配器 (TODO)
```

## 功能

- [x] **Phase 1**: Agent 核心循环 (ReAct: 思考→行动→观察)
- [x] **Phase 1**: Tool Use (shell、文件读写)
- [x] **Phase 1**: 流式输出
- [x] **Phase 1**: 交互式 / 单次任务模式
- [ ] **Phase 2**: 子代理 (Delegation)
- [ ] **Phase 2**: 技能系统 (Skill Manager)
- [ ] **Phase 3**: 飞书机器人接入
- [ ] **Phase 3**: 持久化记忆 (SQLite)

## 设计参考

| Hermes 模式 | Spider 实现 |
|------------|-------------|
| ReAct 循环 | `Agent.run()` |
| Tool System | `ToolRegistry` |
| Delegation | Phase 2 |
| Skill System | Phase 2 |
| Platform Adapters | Phase 3 |
