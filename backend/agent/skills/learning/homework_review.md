---
name: homework_review
description: 批改作业或答案
version: 4
category: pedagogy
priority: 95
autoload: false
triggers: [homework_review, submitted_attempt]
requires_tools: [record_learning_evidence, get_weak_prerequisites]
related_skills: [error_diagnosis, progressive_hint]
---

# 作业批改

区分题目、要求和学生作答；只有题目时询问答案或按要求讲解，不写证据。给结论、正确部分、首个关键错误和修改方法。作答可评价且有可靠 `kp_id` 时，由本 Skill 调用一次 `record_learning_evidence`；部分正确用可靠度/误区表达。仅需验证前置时查 `get_weak_prerequisites`，子诊断不重复写入。保存失败要说明。输出“结论—依据—修改—下一步”。
