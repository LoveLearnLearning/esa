---
name: progressive_hint
description: 卡住时逐级提示
version: 3
category: pedagogy
priority: 94
autoload: false
triggers: [student_stuck, request_hint]
requires_tools: [record_learning_evidence]
related_skills: [error_diagnosis]
---

# 分级提示

一次给最小帮助：一级指出目标/方向；二级给关键关系或中间结构；三级展示核心步骤但保留最后答案。用户明确要完整解答或三级仍无法继续时给完整过程并标出卡点。先用已有题目和尝试，不重复询问。提示不写证据；用户随后产生可评价的新作答且本 Skill 是主评估者时，才调用一次 `record_learning_evidence` 并记录实际最高提示级别。
