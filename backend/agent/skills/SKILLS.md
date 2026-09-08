# ESA Skill 规范

每个 Skill 使用 YAML frontmatter 声明契约。`backend/agent/tools/skills.py`
会在运行时校验 Skill -> Tool 和 Skill -> Skill 依赖，发现漂移时直接报错。

模板：

```md
---
name: progressive_hint
description: 学生卡住时提供逐级提示
version: 1
category: pedagogy
priority: 90
autoload: false
triggers:
  - student_stuck
requires_tools:
  - record_learning_evidence
related_skills:
  - error_diagnosis
---

# Skill 正文

写清楚触发条件、步骤、禁止事项、何时调用 Tool。
```

约束：

- `name`：小写字母/数字/下划线，必须唯一。
- `description`：只写“什么时候用、解决什么问题”，供主 Agent 做初筛。
- `autoload: true`：仅用于短、稳定、每轮都应生效的全局 policy，普通 Skill 禁止滥用。
- `requires_tools`：正文实际需要调用的 Tool 必须全部列出。
- `related_skills`：正文会转入/协作的 Skill 必须存在。
- Skill 只描述教学/任务流程；数据读写必须通过 Tool，不允许在 Skill 中假装已经写库。
