# 子代理系统 (Delegation)

**文件**: `core/sub_agent.py`
**类**: `SubAgentPool`

## 职责

- 管理子 Agent 的创建和生命周期
- 控制并发数量，防止资源耗尽
- 子 Agent 独立运行，共享父 Agent 的工具集和 LLM 配置

## 为什么需要子代理？

复杂任务可以拆解为多个独立子任务并行执行：

```
父 Agent: "查一下系统信息和磁盘空间"
      │
      ├── delegate_task("查系统名称和版本")  → 子 Agent #1
      │     └── shell("uname -a")
      │
      └── delegate_task("查磁盘使用情况")    → 子 Agent #2
            └── shell("df -h")
```

## 类结构

```python
class SubAgentPool:
    def __init__(self, api_key=None, base_url=None, tools=None,
                 max_concurrent=3, parent_agent=None):
        self.max_concurrent = max_concurrent  # 并行上限
        self._running = {}                    # 运行中的任务

    async def delegate(self, task, context="") -> str:
        """创建子 Agent 执行子任务"""

    def running_count(self) -> int:
        """当前运行中的子 Agent 数量"""

    @property
    def is_busy(self) -> bool:
        """是否达到并发上限"""
```

## 关键设计

### 并发控制
```python
if len(self._running) >= self.max_concurrent:
    # 等待一个完成，腾出位置
    done, _ = await asyncio.wait(
        self._running.values(),
        return_when=asyncio.FIRST_COMPLETED
    )
```

### 子 Agent 隔离
每个子 Agent 是独立的 `Agent()` 实例，有自己的对话上下文：
- 子 Agent 的 system prompt 更简洁，只专注于完成任务
- 子 Agent 的执行结果作为字符串返回给父 Agent
- 子 Agent 的错误不会影响父 Agent

## 注册为工具

```python
agent.register_tool(
    "delegate_task",
    "将子任务交给独立的子 Agent 执行，可并行处理多个独立任务",
    sub_pool.delegate, DELEGATE_TASK_SCHEMA
)
```

## Schema

```python
DELEGATE_TASK_SCHEMA = {
    "properties": {
        "task": {"type": "string", "description": "子任务描述"},
        "context": {"type": "string", "description": "附加上下文"},
    },
    "required": ["task"],
}
```

## 限制

| 限制 | 默认值 | 说明 |
|------|--------|------|
| max_concurrent | 3 | 同时运行的子 Agent 上限 |
| max_spawn_depth | 1 (隐式) | 子 Agent 不会自己再建子 Agent |

## 与 Hermes 的对应关系

| Hermes | Spider |
|--------|--------|
| `delegation.max_concurrent_children` | `SubAgentPool(max_concurrent=)` |
| `delegate_task` tool | `SubAgentPool.delegate()` |
| 子 Agent 独立上下文 | 每个子 Agent 新建 `Agent()` 实例 |
