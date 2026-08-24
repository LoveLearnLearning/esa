---
name: study_plan
description: 制定学习计划
version: 3
category: planning
priority: 83
autoload: false
triggers: [study_plan]
requires_tools: [get_mastery_report, recommend_practice, get_review_timing]
related_skills: [practice_recommendation]
---

# 学习计划

确认目标/考试日期、范围和每日时间，关键约束缺失先询问。用 `get_mastery_report` 查掌握报告；排复习日期时查 `get_review_timing`，需具体练习时查 `recommend_practice`。可靠薄弱点优先补前置，未知项安排短诊断，并留复习和缓冲。输出日期/周次任务、时长、完成标准和调整规则，总时长不超可用时间；计划不写证据。
