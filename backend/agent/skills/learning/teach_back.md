---
name: teach_back
description: 复述检查理解
version: 3
category: pedagogy
priority: 80
autoload: false
triggers: [understanding_check, teach_back]
requires_tools: [record_learning_evidence]
related_skills: [error_diagnosis]
---

# Teach-back

让用户用自己的话说明一个核心概念、因果关系或步骤，不在问题中泄露答案。复述后指出正确点、缺失、误解和最小修正；证据不足则追问。有可靠 `kp_id` 且复述可评价时，由本 Skill 调用一次 `record_learning_evidence`，并设 `activity_type="teach_back"`；提问阶段不写入。保存失败仍反馈并说明未更新状态。
