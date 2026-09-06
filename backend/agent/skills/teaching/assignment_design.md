---
name: assignment_design
description: 基于已授权课程上下文设计可执行、可评分的作业
version: 2
category: teaching
priority: 85
autoload: false
triggers: [assignment_design, homework_design, task_design]
requires_tools: [get_teaching_context]
related_skills: [grading_feedback, teaching_plan]
---
# 作业设计

先调用 `get_teaching_context`，只使用返回的班级、课程和作业概要。工具失败或没有绑定班级时，说明无法取得授权上下文；若用户已提供充分课程信息，可基于其材料起草，但不得伪造班级数据。

仅在本轮提供了 `retrieve_knowledge`，并且用户要求依据教材/课程库、需要核对课程口径，或现有材料不足以确定内容范围时调用它。用户已给出完整教学目标、材料和约束时不要机械检索。检索结果仅作证据并遵守 `citation_mode`。

设计前确认会改变结果的约束：学习目标、学生阶段、作业形式、预计用时、总分及允许资源。信息足够时直接设计，不重复追问工具已经返回的数据。

交付内容应包括：

- 可观察、可测量的学习目标；
- 题目、分值、考查点和难度梯度；
- 每题答案或评分要点，以及部分给分规则；
- 合理的预计完成时长，并说明这是基于题量和难度的估算，不是系统 ETA；
- 关键歧义、依赖资源和教师需要人工确认的内容。

默认不套固定题型比例；比例应由目标和作业类型决定。不得声称题目符合未取得的课程标准，不得伪造学生水平、知识库内容或完成时间，不得仅输出“知识/能力/素养目标”等空泛栏目。
