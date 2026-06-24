# 架构总览

Spider 采用分层架构，核心是 **Agent 引擎 → 工具系统 → LLM 接口** 三层模型。

```
┌──────────────────────────────────────────────────────────────┐
│                        Spider                                │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Agent    │  │ SubAgent │  │ Skill    │  │ Memory      │ │
│  │ Engine   │──│ Pool     │  │ Manager  │  │ Store       │ │
│  │ (ReAct)  │  │          │  │          │  │ (SQLite +   │ │
│  └────┬─────┘  └──────────┘  └──────────┘  │  FTS5 + Vec)│ │
│       │                                      └─────────────┘ │
│       ▼                                                       │
│  ┌────────────┐  ┌──────────┐  ┌──────────────┐             │
│  │ Tool       │  │ Skills   │  │ CLI          │             │
│  │ Registry   │  │ (YAML)   │  │ (Rich 终端)  │             │
│  │ ├─ shell   │  └──────────┘  └──────────────┘             │
│  │ ├─ file    │                                              │
│  │ ├─ convert │  ┌──────────────┐                            │
│  │ ├─ self_dev│  │ Web UI       │                            │
│  │ └─ ...     │  │ (FastAPI +   │                            │
│  └─────┬──────┘  │  SSE + HTML) │                            │
│        │         └──────────────┘                            │
│        ▼                                                      │
│  ┌──────────────────────┐                                    │
│  │ LLM 接口层           │  (DeepSeek / OpenAI API)           │
│  │ ├─ chat completions  │                                    │
│  │ └─ embeddings        │                                    │
│  └──────────────────────┘                                    │
└──────────────────────────────────────────────────────────────┘
```

## 核心架构模式

### 1. Agent 循环 (ReAct)

Agent 的核心是一个 **思考→行动→观察** 循环：

```
用户任务 → 系统提示 + 对话历史 + 工具定义
              │
              ▼
         ┌──────────┐
         │ LLM 思考  │  ← 自动注入相关记忆 + 匹配技能
         │ (think)   │
         └────┬─────┘
              │
          ┌───┴───┐
          │       │
          ▼       │ 需要工具？
     ┌────────┐   │
     │ 执行工具 │   │
     │ (act)   │   │
     └───┬────┘   │
         │        │
         ▼        │
     ┌────────┐   │
     │ 观察结果 │──┘  ← 工具结果加入对话上下文，继续循环
     │ (observe)│
     └────────┘
          │
          ▼ 任务完成
     ┌────────┐
     │ 返回结果 │
     └────────┘
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

工具注册后自动生成 OpenAI 兼容的 tool schema，LLM 可根据任务需要选择合适的工具调用。

### 3. 消息协议

对话历史使用 OpenAI 消息格式，兼容所有兼容 OpenAI API 的 LLM：

```
system   → 系统提示（角色设定 + 记忆注入 + 技能注入）
user     → 用户输入
assistant → LLM 回复或 tool_calls 请求
tool     → 工具执行结果
```

支持 DeepSeek 的 `reasoning_content` 字段（thinking mode）。

## 数据流

```
main.py                      CLI 入口 / Web 入口
   │
   ├─ Agent.run(task)        接收用户任务
   │     │
   │     ├─ Memory.recall()  自动检索相关记忆（语义 + 关键词混合）
   │     │
   │     ├─ SkillManager.find_matching()  匹配技能
   │     │     └─ 匹配成功 → 追加技能 prompt 到 system message
   │     │
   │     ├─ LLM.think()      向 LLM 发送当前对话上下文
   │     │     │
   │     │     └─ OpenAI SDK → DeepSeek API (流式/非流式)
   │     │
   │     ├─ [tool call]      如果 LLM 决定调用工具
   │     │     │
   │     │     ├─ [delegate_task]  创建子 Agent 执行
   │     │     │     └─ SubAgentPool.delegate()
   │     │     │           └─ Agent(child).run(subtask) → 返回结果
   │     │     │
   │     │     ├─ ToolRegistry.execute()  查找并执行工具
   │     │     │     └─ tool handler (shell/read_file/convert/self_dev)
   │     │     │
   │     │     └─ 结果 → 追加到 messages → 继续循环
   │     │
   │     └─ [stop]           LLM 决定结束，返回最终结果
   │
   ├─ CLI 输出                SpiderCLI (Rich Markdown 渲染)
   └─ Web UI 输出             FastAPI SSE 流 → 浏览器
```

## 文件职责

### 核心层 (core/)

| 文件 | 职责 | 关键类/函数 |
|------|------|-------------|
| `agent.py` | Agent 核心循环 | `Agent` |
| `llm.py` | LLM API 封装 | `LLM`, `LLMResponse` |
| `tool_registry.py` | 工具注册与调度 | `ToolRegistry`, `Tool` |
| `sub_agent.py` | 子代理并发执行 | `SubAgentPool` |
| `skill_manager.py` | 技能加载/匹配/保存 | `SkillManager`, `Skill` |
| `memory.py` | 持久化记忆存储 | `MemoryStore` |
| `cli.py` | 终端渲染（颜色 + Markdown） | `SpiderCLI` |

### 工具层 (tools/)

| 文件 | 职责 |
|------|------|
| `shell.py` | Shell 命令执行 |
| `read_write.py` | 文件读写操作 |
| `convert.py` | 文档格式转换 (docx↔PDF) |
| `self_dev.py` | 自开发工具集 |

### 展示层 (web/)

| 文件 | 职责 |
|------|------|
| `app.py` | FastAPI 后端 + SSE 流 + REST API |
| `templates/index.html` | 聊天界面模板 |
| `static/css/style.css` | Claude 风格深色主题 |
| `static/js/chat.js` | 前端交互逻辑 |
