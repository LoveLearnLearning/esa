---
name: classroom_context_review
description: 在当前授权班级与作业概要内进行有证据的教学分析
version: 2
category: teaching
priority: 85
autoload: false
triggers: [classroom_review, teaching_analysis, class_performance]
requires_tools: [get_teaching_context]
related_skills: [grading_feedback, teaching_plan]
---
# 课堂上下文分析

必须先调用 `get_teaching_context`。它只提供当前授权班级及可选作业的概要字段，不提供成绩分布、提交明细、学生名单或学习行为数据；未从其他授权输入取得这些数据时，禁止生成平均分、完成率、趋势或个体结论。

仅在本轮提供了 `retrieve_knowledge`，并且需要核对分析方法、课程口径或用户明确要求知识库证据时调用它。分析用户提供的数据时不要无条件检索。检索结果必须遵守 `citation_mode`。

按实际证据分层输出：

1. **已知事实**：逐项说明来自 `get_teaching_context` 或用户材料的字段。
2. **可计算结论**：写明样本范围、计算口径和结果；缺少原始数据时不计算。
3. **合理推断**：明确标注推断及不确定性，不把相关性写成因果。
4. **数据缺口**：列出完成目标还需要的最小字段。
5. **下一步**：给出能由教师执行和验证的行动。

群体分析默认使用汇总信息。只有任务确实要求且当前输入已授权时才讨论单个学生；不要输出无依据的隐私、授权或“已匿名化”自我声明。
