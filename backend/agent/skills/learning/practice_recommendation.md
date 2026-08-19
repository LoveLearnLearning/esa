---
name: practice_recommendation
description: 用户问今天练什么、请求推荐练习或制定刷题顺序时使用
version: 2
category: planning
priority: 84
autoload: false
triggers:
  - practice_recommendation
requires_tools:
  - get_mastery_report
  - recommend_practice
  - get_learning_evidence_summary
related_skills:
  - progressive_hint
---

# 练习推荐 Skill

1. 确定课程与距考试周数；上下文已有时不要重复询问。课程确实无法判断时只问一个聚焦问题；
   距考试时间未知且用户只想日常练习时，可采用“无临近考试”的保守排序并明确这个假设，
   不要为了一个非关键参数阻塞推荐。
2. 调用 `get_mastery_report(course)` 获取总体状态。
3. 调用 `recommend_practice(course, weeks_to_exam)` 获取 Top 推荐。
4. 每次最多推荐 5 个知识点，优先解释“为什么现在练它”。
5. 如果某知识点长期表现为高提示依赖，可调用
   `get_learning_evidence_summary(kp_id)`，把“独立完成”作为下一轮目标。
6. `weak_prerequisites` 非空时，先安排最深层前置，再回到目标知识点。

工具无数据时不要伪造排名：给出一组低风险诊断练习作为冷启动方案，并说明完成后才能形成个性化排序。
工具只返回部分结果时使用现有结果，不重复调用同一个 Tool。

不要只按“掌握度最低”排序，也不要让高掌握度知识点无限过度练习。
