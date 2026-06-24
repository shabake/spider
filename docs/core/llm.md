# LLM 接口封装

**文件**: `core/llm.py`
**类**: `LLM`, `LLMResponse`

LLM 层负责与 DeepSeek API 通信，是 Agent 的"大脑"。

## 职责

- 封装 OpenAI SDK 调用
- 支持流式 (streaming) 和非流式响应
- 解析 tool calls
- 统一响应格式

## 类结构

### LLMResponse

`LLMResponse` 将 OpenAI SDK 的原始响应解析为统一结构：

```python
class LLMResponse:
    content: str          # LLM 的文本回复
    tool_calls: list      # [{id, name, arguments}]
    is_done: bool         # 是否应停止循环
    finish_reason: str    # "stop" | "tool_calls" | ...

    # 解析逻辑
    # - finish_reason == "stop"       → is_done = True
    # - finish_reason == "tool_calls" → is_done = False
    # - 有 content 无 tool_calls      → is_done = True
```

### LLM

```python
class LLM:
    def __init__(self, model="deepseek-v4-flash",
                 api_key=None, base_url="https://api.deepseek.com/v1"):
        self.model = model
        self.client = OpenAI(api_key=api_key or env, base_url=base_url)

    def think(self, messages, tools=None) -> LLMResponse:
        """非流式调用"""

    def think_stream(self, messages, tools=None,
                     on_content=None, on_tool=None) -> dict:
        """流式调用"""
```

## 方法详解

### `think(messages, tools)`
非流式调用，适用于不需要实时输出的场景。

```python
response = llm.think(
    messages=[{"role": "user", "content": "你好"}],
    tools=[{"type": "function", "function": {...}}]
)
print(response.content)      # LLM 文本回复
print(response.tool_calls)   # [] 或 [{id, name, arguments}]
print(response.is_done)      # True/False
```

### `think_stream(messages, tools, on_content, on_tool)`
流式调用，实时输出 LLM 的回复内容。

```python
def on_content(chunk):
    print(chunk, end="", flush=True)  # 实时打印每个 token

def on_tool(tool_calls):
    print(f"\n调用工具: {tool_calls}")

result = llm.think_stream(messages, tools, on_content, on_tool)
```

返回字典：
```python
{
    "content": "完整的回复文本",
    "tool_calls": [{"id": "...", "name": "shell", "arguments": {...}}],
    "is_done": True/False,
}
```

## 支持的模型

默认使用 `deepseek-v4-flash`，实际上任何兼容 OpenAI API 格式的模型都可以替换：

```python
# 替换为其他模型
llm = LLM(
    model="deepseek-chat",
    api_key="sk-xxx",
    base_url="https://api.deepseek.com/v1"
)
```

## 与 Hermes 的对应关系

| Hermes | Spider |
|--------|--------|
| `openai` SDK 直接调用 | `LLM` 封装类 |
| streaming 配置 | `think_stream()` |
| 无统一 response 包装 | `LLMResponse` 解析 |
| 多 provider 支持 | 通过 `model`/`base_url` 参数 |
