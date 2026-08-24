---
name: adaptive_practice
description: 出题或批改上一练习
version: 3
category: pedagogy
priority: 98
autoload: false
triggers: [start_practice, continue_practice, submitted_practice_answer]
requires_tools: [get_mastery_level, get_learning_evidence_summary, get_weak_prerequisites, record_learning_evidence]
related_skills: [error_diagnosis]
---

# 自适应练习

开始：优先用可信 `resolved_kp_ids`/`pending_practice_kp_id`；无可靠 `kp_id` 才询问。用 `get_mastery_level` 查掌握度，按需用 `get_learning_evidence_summary`/`get_weak_prerequisites` 查误区和前置；未知水平按基础题处理。每次只出一道、不公布答案，以 `【练习题｜知识点：<kp_id>】` 开头；出题不写证据。

作答：最近回复有练习标记时，短答案、“不会”、公式或代码均视为作答。可靠评价后调用一次 `record_learning_evidence`，填写实际正确性、提示、尝试、独立性和可靠度；误区须有依据。保存失败仍反馈并说明未保存。输出“结果—关键点—下一步”。
