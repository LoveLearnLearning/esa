---
name: mastery_report
description: 用户询问掌握度、学习情况、学情或学习进度时使用
version: 2
category: learning_state
priority: 85
autoload: false
triggers:
  - mastery_report
requires_tools:
  - get_mastery_report
  - get_weak_prerequisites
  - get_learning_evidence_summary
related_skills: []
---

# 掌握度报告 Skill

1. 用户指定课程时调用 `get_mastery_report(course)`；未指定时返回全部。
2. 对最薄弱的少量知识点，可调用 `get_weak_prerequisites(kp_id)` 判断是否存在前置缺口。
3. 如用户想知道“为什么掌握度低/为什么总需要提示”，可调用
   `get_learning_evidence_summary(kp_id)` 补充独立完成率、提示等级和常见误区。
4. 不要把 mastery 当成精确概率或医学式诊断；它是系统内部学习状态估计。
5. 没有数据时明确说“证据不足”，不要用默认 50% 假装已经测过。
工具返回部分数据时，按已有数据生成报告并标注缺失项；不要因为某个可选的前置/证据查询失败而放弃总体报告。

输出建议：

```text
【总体】平均掌握度 / 已覆盖知识点
【薄弱】最需要处理的 3-5 个知识点
【原因】前置缺口 / 长期未复习 / 提示依赖 / 证据不足
【下一步】今天最值得做的 1-3 件事
```
