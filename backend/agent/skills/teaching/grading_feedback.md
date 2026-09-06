---
name: grading_feedback
description: 在授权范围内根据实际作答和评分标准生成教师批改建议
version: 2
category: teaching
priority: 85
autoload: false
triggers: [teacher_grading, batch_grading, feedback_generation]
requires_tools: [get_teaching_context]
related_skills: [assignment_design, classroom_context_review]
---
# 教师批改与反馈

先调用 `get_teaching_context` 确认当前班级和可选作业绑定。若工具拒绝、作业未绑定或用户没有提供待批改内容，应说明缺失项，不得编造学生、作答或分数。

仅在本轮提供了 `retrieve_knowledge`，并且用户要求依据课程资料、评分标准存于知识库，或需要核对专业事实时调用它。用户已经提供题目、答案和 rubric 时直接依据这些材料批改，不要机械检索。检索证据严格遵守 `citation_mode`。

批改顺序：

1. 分离题目、参考材料、评分标准和学生作答。
2. 检查评分标准是否足够；缺失时先给“建议评分规则”，不能伪装成正式规则。
3. 对照得分点给出命中证据、缺失证据和分值建议；主观题明确保留人工裁量。
4. 反馈先指出有效部分，再定位最重要的改进点，并给出学生可执行的修改动作。
5. 批量任务只汇总实际收到的记录；逐条失败要单独标记，不能静默跳过。

输出包含评分依据、分值建议、反馈文本和需人工确认项。不要输出“已遵守隐私保护”等无法验证的自我声明；不要承诺导出、发布、加密存储或进度跟踪，除非对应工具结果明确表明这些动作已经完成。
