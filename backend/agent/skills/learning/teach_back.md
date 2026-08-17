---
name: teach_back
description: 讲解后让学生用自己的话复述，并评价理解完整度
version: 2
category: pedagogy
priority: 80
autoload: false
triggers:
  - understanding_check
  - teach_back
requires_tools:
  - record_learning_evidence
related_skills:
  - error_diagnosis
---

# Teach Back

不要问“懂了吗？”。让学生产生可观察的理解证据。

## 流程

1. 只提出一个聚焦的复述任务，例如：
   “不用看上面的解释，用自己的话说明为什么这里需要栈。”
2. 等学生复述后，从四方面判断：
   - 核心概念覆盖
   - 因果/逻辑关系
   - 术语使用
   - 是否出现关键误区
3. 给出短反馈：先指出正确部分，再指出最关键缺口。
4. 有可靠 `kp_id` 且学生已经完成复述时，调用一次 `record_learning_evidence` 记录：
   - `activity_type=teach_back`
   - `explanation_score=0-1`
   - `independent`
   - 如存在明确误区，记录 `error_type/misconception`
5. 如果解释正确但只会原题，可后续再做迁移测试；本 Skill 不把“会复述”直接等同于“会迁移”。

如果用户是在请求讲解而不是主动要求复述，先完整讲解，再把复述作为可选下一步；
不得用“你先解释一下”替代本轮答案。写入工具失败时仍给出理解反馈，并明确本次没有保存。

不得根据语言表达风格差异武断判断学生“不理解”。
