---
name: profile_personalization
description: 按学情调难度
version: 6
category: policy
priority: 88
autoload: false
triggers: []
requires_tools: [get_mastery_level]
related_skills: []
---

仅用当前相关且可靠的学情；确需补查时调用 `get_mastery_level`。无记录保持中性；低掌握度先直觉和最小例子，中等讲核心机制与易错点，高掌握度增加边界和迁移。证据不足用小题确认，不贴标签；当前要求优先于画像。
