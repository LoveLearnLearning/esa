---
name: mastery_report
description: 查询掌握度
version: 3
category: learning_state
priority: 85
autoload: false
triggers: [mastery_report]
requires_tools: [get_mastery_report, get_weak_prerequisites, get_learning_evidence_summary]
related_skills: []
---

# 掌握度报告

调用 `get_mastery_report`；用户指定知识点则聚焦它。仅 `has_record=true` 的数值可作为掌握度，未知状态单列“证据不足”，不得排成薄弱。需解释原因时才调用 `get_learning_evidence_summary` 或 `get_weak_prerequisites`。输出概况、可靠优势/薄弱点、未知项、建议和数据边界；报告不写学习证据。
