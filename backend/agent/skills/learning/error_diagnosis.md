---
name: error_diagnosis
description: 定位错误和误区
version: 2
category: pedagogy
priority: 92
autoload: false
triggers: [wrong_answer, repeated_error]
requires_tools: [get_weak_prerequisites, record_learning_evidence]
related_skills: [progressive_hint]
---

# 错误诊断

找出首个使后续失效的步骤，区分概念、条件、计算、表示和策略错误；给证据、最小修正及可复用检查规则。仅需验证前置时查 `get_weak_prerequisites`。只有本 Skill 是真实作答的主评估者、有可靠 `kp_id` 且结果可评价时才调用一次 `record_learning_evidence`；作为作业/练习的子诊断时不写。
