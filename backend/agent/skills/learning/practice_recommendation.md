---
name: practice_recommendation
description: 推荐下一练习
version: 3
category: planning
priority: 84
autoload: false
triggers: [practice_recommendation]
requires_tools: [get_mastery_report, recommend_practice, get_learning_evidence_summary]
related_skills: [progressive_hint]
---

# 练习推荐

取得课程、范围、时间和目标；缺失且会改变推荐时才澄清。调用 `recommend_practice`，需要解释优先级时再调用 `get_mastery_report`/`get_learning_evidence_summary`。优先到期复习、可靠薄弱点和必要前置；未知项用诊断题确认。输出 1–3 个顺序练习块，含知识点、题型、数量/时长、完成标准和依据；推荐不写证据。
