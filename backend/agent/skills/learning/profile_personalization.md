---
name: profile_personalization
description: 有可靠学情数据时调整讲解、练习和提示难度
version: 5
category: policy
priority: 88
autoload: false
triggers: []
requires_tools:
  - get_mastery_level
related_skills: []
---

仅在 `get_mastery_level` 或已授权的学习上下文提供可靠数据时应用以下规则；没有记录时保持中性难度，不猜测用户水平。

- `has_record=false` 或缺少掌握度表示未知，不得当作默认 50，也不得据此称学生“薄弱”。
- `mastery < 40`：先讲直觉和一个最小例子，再给正式定义，不直接进入综合题。
- `40 <= mastery < 75`：正常讲解，聚焦核心机制、易错点，并给一个迁移问题。
- `mastery >= 75`：减少基础定义复述，增加边界条件、辨析、复杂度、迁移和综合应用。
- 前置数据为 `status=weak` 时才优先补真正的前置；`status=unknown` 只能标记为证据不足。
- `avg_hint_level >= 2` 时默认逐级提示；`independent_rate < 0.4` 时增加主动回忆和独立尝试机会。
- 用户明确要求的深度、格式和是否直接给解答优先于个性化默认值。
