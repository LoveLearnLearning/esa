---
name: progressive_hint
description: 学生卡住、没思路或明确请求提示时，逐级提供最小必要帮助
version: 2
category: pedagogy
priority: 94
autoload: false
triggers:
  - student_stuck
  - request_hint
requires_tools:
  - record_learning_evidence
related_skills:
  - error_diagnosis
---

# Progressive Hint

核心原则：**一次只给当前最小必要帮助**，避免提示直接变成答案。

## 提示等级

- Level 1：指出应回忆的概念/检查方向，不给具体步骤
- Level 2：指出方法或算法方向
- Level 3：给一个关键中间关系、伪代码骨架或关键式子
- Level 4：给相似例题/局部 worked example，但不替学生完成原题
- Level 5：完整 scaffold；只有多次尝试仍卡住，或用户明确要求时使用

## 流程

1. 先确认学生已经做到哪一步；如果上下文已经明确，不重复追问。
2. 从当前所需的最低 Level 开始。
3. 给完一个 Level 后停下，让学生继续尝试。
4. 学生的新尝试仍卡住时，最多升一级，不跨级倾倒答案。
5. 如果用户明确说“直接给完整解答”，尊重用户要求，不强行苏格拉底式拖延。

如果当前请求同时属于 `homework_review` 或 `adaptive_practice`，本 Skill 只负责提示层级，
由负责批改/练习的上层 Skill 统一写入一次证据；不要在同一轮再次调用
`record_learning_evidence`。工具不可用时仍给出当前最低级提示，并明确暂未保存学习记录。

## Learning Evidence

当本 Skill 独立处理一个已经产生新尝试的请求，且能够确认 `kp_id` 时，可以调用一次
`record_learning_evidence` 记录：

- `activity_type=hint`
- `hint_level=实际最高等级`
- `attempts=可确认的尝试次数`
- `independent=false`（只有提示已实质影响解题时）

仅仅“系统给了提示”但学生还没有新的表现时，不要记录 `correct=true/false`。
