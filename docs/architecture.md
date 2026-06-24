# 架构总览

Spider 采用分层架构，核心是 **Agent 引擎 → 工具系统 → LLM 接口** 三层模型。

```
┌─────────────────────────────────────────────────────┐
│                     Spider                           │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌──────────────┐   │
│  │  Agent     │  │  SubAgent  │  │  SKill       │   │
│  │  Engine    │──│  Pool      │  │  Manager     │   │
│  │  (ReAct)   │  │  (P2)      │  │  (P2)        │   │
│  └─────┬──────┘  └────────────┘  └──────────────┘   │
│        │                                              │
│        ▼                                              │
│  ┌────────────┐  ┌────────────┐  ┌──────────────┐   │
│  │  Tool      │  │  Skill     │  │  Memory      │   │
│  │  Registry  │  │  Files     │  │  Store       │   │
│  │  ├─ shell  │  │  (skills/) │  │  (Phase 3)   │   │
│  │  ├─ file   │  └────────────┘  └──────────────┘   │
│  │  ├─ convert│                                      │
│  │  └─ ...    │                                      │
│  └─────┬──────┘                                      │
│        ▼                                              │
│  ┌──────────────────┐                                 │
│  │  LLM 接口层      │  (DeepSeek API)                │
│  └──────────────────┘                                 │
└─────────────────────────────────────────────────────┘
```

## 核心架构模式

### 1. Agent 循环 (ReAct)

Agent 的核心是一个 **思考→行动→观察** 循环：

```
用户任务
    │
    ▼
┌──────────────────┐
│  LLM 思考         │  ← 输入：系统提示 + 对话历史 + 工具定义
│  (think)          │
└──────┬───────────┘
       │
        ┌───────┐
       ▼        │ 需要工具？
  ┌──────────┐  │
  │ 执行工具  │  │
  │ (act)    │  │
  └────┬─────┘  │
       │        │
       ▼        │
  ┌──────────┐  │
  │ 观察结果  │──┘  ← 工具结果加入对话上下文
  │ (observe) │
  └──────────┘
       │
       ▼ 任务完成
  ┌──────────┐
  │ 返回结果  │
  └──────────┘
```

### 2. 工具系统 (Tool System)

工具以 **函数 + JSON Schema** 注册，LLM 通过 `tool_calls` 调用：

```python
agent.register_tool(
    name="shell",
    description="执行 shell 命令",
    handler=execute_shell,
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
        },
        "required": ["command"],
    }
)
```

### 3. 消息协议

对话历史使用 OpenAI 消息格式，兼容所有兼容 OpenAI API 的 LLM：

```
system  → 系统提示（角色设定）
user    → 用户输入
assistant → LLM 回复或 tool_calls 请求
tool    → 工具执行结果
```

## 数据流

```
main.py                      CLI 入口
   │
   ├─ Agent.run(task)        接收用户任务
   │     │
   │     ├─ SkillManager.find_matching(task)  ← P2: 自动匹配技能
   │     │     └─ 匹配成功 → 追加技能 prompt 到 system message
   │     │
   │     ├─ LLM.think()      向 LLM 发送当前对话上下文
   │     │     │
   │     │     └─ OpenAI SDK → DeepSeek API
   │     │
   │     ├─ [tool call]      如果 LLM 决定调用工具
   │     │     │
   │     │     ├─ [delegate_task]  ← P2: 创建子 Agent 执行
   │     │     │     └─ SubAgentPool.delegate()
   │     │     │           └─ Agent(child).run(subtask) → 返回结果
   │     │     │
   │     │     ├─ ToolRegistry.execute()  查找并执行工具
   │     │     │     │
   │     │     │     └─ tool handler (shell/read_file/convert/...)
   │     │     │
   │     │     └─ 结果 → 追加到 messages 继续循环
   │     │
   │     └─ [stop]           LLM 决定结束，返回最终结果
   │
   └─ 打印结果
```

## 文件职责

| 文件 | 职责 | 关键类/函数 |
|------|------|-------------|
| `main.py` | CLI 入口、参数解析、启动方式 | `create_agent()`, `run_task()`, `interactive_mode()` |
| `core/agent.py` | Agent 核心循环 | `Agent` |
| `core/llm.py` | LLM API 封装 | `LLM`, `LLMResponse` |
| `core/tool_registry.py` | 工具注册与调度 | `ToolRegistry`, `Tool` |
| `tools/shell.py` | Shell 命令执行 | `execute_shell()` |
| `tools/read_write.py` | 文件读写操作 | `read_file()`, `write_file()`, `list_files()` |
