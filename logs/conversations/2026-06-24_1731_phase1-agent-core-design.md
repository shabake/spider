# 2026-06-24 17:31 — Phase 1: Agent 核心循环设计

## 讨论内容
设计了 Spider Agent 的核心 ReAct 循环架构，仿照 Hermes 的 Agent 系统。

## 关键决策
- 使用 `deepseek-v4-flash` 作为默认模型（走 DeepSeek 官方 API）
- 最大 turn 数设为 30，防止无限循环
- Tool call 格式严格遵循 OpenAI 标准，方便兼容不同 LLM 提供商
- 流式输出 (streaming) 为默认模式，提供实时反馈
- 系统采用模块化：`LLM` / `ToolRegistry` / `Agent` 三层分离

## 实现了哪些 Hermes 设计模式
| 模式 | 文件 | 说明 |
|------|------|------|
| ReAct 循环 | `core/agent.py` | `think → tool_call → observe → loop` |
| Tool System | `core/tool_registry.py` | 函数 + JSON Schema 注册 |
| Tool as Function | `tools/shell.py`, `tools/read_write.py` | shell 执行、文件读写 |

## 代码产出
- `core/agent.py` — Agent 核心循环
- `core/llm.py` — LLM 调用封装 (含 streaming)
- `core/tool_registry.py` — 工具注册中心
- `tools/shell.py` — Shell 执行工具
- `tools/read_write.py` — 文件读写工具
- `main.py` — CLI 入口

## 待办 (Phase 2)
- 子代理 (Delegation): `core/sub_agent.py`
- 技能系统 (Skill Manager): `core/skill_manager.py`
