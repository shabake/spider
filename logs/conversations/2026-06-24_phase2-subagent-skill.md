# 2026-06-24 Phase 2: 子代理 + 技能系统

## 讨论内容
实现 Spider 的子代理委托系统和技能管理系统。

## 关键决策
- 子代理使用独立的 Agent 实例，共享父 Agent 的工具
- 并发数上限 3，防止资源耗尽
- 技能采用 YAML 格式，存储在 skills/ 目录
- 技能自动匹配：任务文本命中 trigger 关键词时追加到 system prompt
- 内置 pyyaml 依赖，同时提供简易解析器作为 fallback

## 代码产出

### 新增文件
- `core/sub_agent.py` — SubAgentPool 子代理池
- `core/skill_manager.py` — SkillManager 技能管理器
- `skills/disk-check.yaml` — 示例技能

### 修改文件
- `core/agent.py` — 集成 SkillManager 自动匹配
- `main.py` — 注册 delegate_task、save_skill、list_skills 工具

## 参考的 Hermes 模式
- Hermes `delegation` 配置 → Spider `SubAgentPool`
- Hermes `skills/` 目录 → Spider `skills/` + `SkillManager`
