# 技能系统 (Skill Manager)

**文件**: `core/skill_manager.py`
**类**: `SkillManager`, `Skill`

## 职责

- 将有效经验保存为可复用的技能文件
- 根据任务文本自动匹配已有技能
- 技能存储在 `skills/` 目录，YAML 格式

## 为什么需要技能系统？

Agent 遇到同样的问题每次都从零思考。技能系统让它"长记性"：

```
第一次: "检查磁盘空间"
   → Agent 自己决定用 df -h，耗时 3 轮
   → 保存为 skill

第二次: "检查磁盘空间"  ⚡
   → 自动匹配 disk-check 技能
   → 直接用 df -h + df -hi，更快更准
```

## 技能文件格式

```yaml
# skills/disk-check.yaml
name: disk-check
description: 检查磁盘使用情况，关注高使用率分区
trigger: 磁盘|disk|空间|存储|容量
prompt: |
  使用 shell 工具执行 df -h 查看磁盘使用情况。
  重点关注使用率超过 80% 的分区。
  也执行 df -hi 查看 inode 使用情况。
tools:
- shell
created: 2026-06-24
```

| 字段 | 说明 |
|------|------|
| `name` | 技能唯一标识（用作文件名） |
| `description` | 简短描述技能用途 |
| `trigger` | 触发关键词，`\|` 分隔，命中任一个即匹配 |
| `prompt` | 技能提示词，注入到 system prompt |
| `tools` | 需要的工具列表 |
| `created` | 创建日期 |

## 类结构

### Skill

```python
class Skill:
    def __init__(self, name, description, trigger, prompt, tools=None, ...):
        ...

    def matches(self, task: str) -> bool:
        """检查 task 是否匹配 trigger 关键词"""
```

### SkillManager

```python
class SkillManager:
    def __init__(self, skills_dir="skills/"):
        self.skills_dir = skills_dir
        self._skills: list[Skill] = []

    def load_all(self):
        """加载 skills/ 目录下所有 .yaml 文件"""

    def find_matching(self, task: str) -> list[Skill]:
        """任务文本匹配技能"""

    def get_skill_prompts(self, task: str) -> str:
        """获取匹配技能的提示词（自动拼接）"""

    async def save(self, name, description, trigger, prompt, tools="") -> str:
        """保存新技能"""

    def list(self) -> str:
        """列出所有技能"""
```

## 自动匹配流程

```
Agent.run(task)
  │
  ├─ SkillManager.find_matching(task)
  │     │
  │     ├─ 遍历所有技能
  │     ├─ skill.matches(task)  → task.lower() 是否包含 trigger 关键词
  │     │
  │     └─ 匹配成功 ⇒ 追加到 system prompt
  │           system += f"📚 参考技能 [skill.name]: skill.prompt"
  │
  ├─ 正常 ReAct 循环（system prompt 已包含技能指导）
  │
  └─ 任务完成
```

## 注册为工具

```python
agent.register_tool(
    "save_skill",   "将当前经验保存为可复用的技能",
    skill_mgr.save, SAVE_SKILL_SCHEMA
)
agent.register_tool(
    "list_skills",  "列出所有已保存的技能",
    skill_mgr.list, LIST_SKILLS_SCHEMA
)
```

## 创建新技能

### 方式 1：Agent 自行保存

Agent 完成任务后，调用 `save_skill` 工具自动保存。

### 方式 2：手动创建

在 `skills/` 目录下新建 `.yaml` 文件：

```bash
touch skills/my-skill.yaml
# 按 YAML 格式填入 name/trigger/prompt 等字段
```

### 方式 3：通过 CLI

```bash
python3 main.py "查一下磁盘空间，然后把方法保存为技能"
```

## 与 Hermes 的对应关系

| Hermes | Spider |
|--------|--------|
| `~/hermes-skills/skills/` | `skills/` 目录 |
| skill.yaml 元数据 | `Skill` 类 + YAML 文件 |
| 技能自动匹配 | `SkillManager.find_matching()` |
| 技能热加载 | `SkillManager.load_all()` |
