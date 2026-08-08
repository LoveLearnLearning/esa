---
name: study_plan
description: 根据学习目标、剩余时间和真实学习状态生成可执行复习计划
version: 2
category: planning
priority: 83
autoload: false
triggers:
  - study_plan
requires_tools:
  - get_mastery_report
  - recommend_practice
  - get_review_timing
related_skills:
  - practice_recommendation
---

# 学习计划 Skill

不要只靠 LLM 凭感觉排日程。计划应优先消费现有学习状态。

## 流程

1. 确认目标、考试/截止时间和每天可用时间；上下文已有时不要重复问。
2. 调用 `get_mastery_report(course)` 获取薄弱点、优势点和长期未复习内容。
3. 调用 `recommend_practice(course, weeks_to_exam)` 得到学习优先级。
4. 对进入近期计划的关键知识点调用 `get_review_timing(kp_id)`，避免把复习全部堆到考试前。
5. 按以下顺序排：
   - 已到复习阈值/即将遗忘
   - 薄弱前置
   - 高权重且中低掌握度
   - 综合/迁移练习
6. 每个学习块必须有可验证产出，例如：
   “完成 3 道二叉树遍历题，其中至少 2 道独立完成”，
   不要只写“复习二叉树 1 小时”。
7. 计划保留 10%-20% 缓冲时间，避免排满导致一次延期后整体崩溃。

输出优先按天/周给出：任务、预计时长、完成标准、复习触发点。
