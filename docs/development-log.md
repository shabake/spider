# 开发记录

本文档记录了 Spider 项目开发过程中有关键决策的对话。

## 对话索引

| 日期 | 主题 | 文件 |
|------|------|------|
| 2026-06-24 | Phase 1: Agent 核心循环设计 | [查看](logs/conversations/2026-06-24_1731_phase1-agent-core-design.md) |
| 2026-06-24 | Phase 1: 完成验证 | [查看](logs/conversations/2026-06-24_1750_phase1-complete.md) |
| 2026-06-24 | Phase 2: 子代理 + 技能系统 | [查看](logs/conversations/2026-06-24_phase2-subagent-skill.md) |
| 2026-06-24 | Phase 3: Web UI (FastAPI + SSE) | 本文档记录 |
| 2026-06-24 | Phase 4a: UI 大升级 + Human-in-the-Loop | CLI 极简重构 + Web Claude 风格 + HITL 基础 |

## 如何记录

每次有设计决策、架构讨论或重要的实现对话时：

1. 在 `logs/conversations/` 下创建 `YYYY-MM-DD_HHMMSS_topic.md`
2. 记录：讨论内容、关键决策、代码产出、下一步计划
3. 在本文件 `docs/development-log.md` 中添加索引

## 记录模板

```markdown
# YYYY-MM-DD HH:MM — 主题

## 讨论内容
...

## 关键决策
- ...

## 代码产出
- `path/to/file` — 说明
