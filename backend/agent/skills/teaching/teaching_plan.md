---
name: teaching_plan
description: 基于真实课程约束生成可执行、可调整的教学计划
version: 2
category: teaching
priority: 85
autoload: false
triggers: [teaching_plan, lesson_plan, curriculum_design]
requires_tools: [get_teaching_context]
related_skills: [assignment_design, classroom_context_review]
---
# 教学计划

先调用 `get_teaching_context` 获取当前授权班级、课程、学期和可选作业概要。工具失败时明确说明；用户提供了充分独立上下文时仍可起草通用计划，但不得把用户描述包装成系统班级数据。

仅在本轮提供了 `retrieve_knowledge`，并且计划必须依据指定教材/课程库、需要核对课程事实，或用户材料不足时调用它。已有充分材料时不要机械检索；所有检索内容遵守 `citation_mode`。

只澄清会实质改变计划的缺口：主题和学生阶段、课时长度/数量、已有基础、可用设备、必须覆盖的目标。然后输出：

- 2–4 个可观察的学习目标及完成标准；
- 按分钟或课时分配的活动、教师动作和学生产出；
- 与目标一一对应的形成性检查；
- 所需资源、替代方案和时间超支时的删减顺序；
- 根据课堂证据调整下一步的规则。

计划总时长必须与可用时间闭合。不要机械罗列“知识、技能、能力、素养”四类目标，不得假设不存在的设备、学生画像或课程标准，也不得把建议写成已经执行的教学事实。
