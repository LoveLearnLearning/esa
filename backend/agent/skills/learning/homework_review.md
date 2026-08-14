---
name: homework_review
description: 用户提交作业、题目答案或代码作答并要求批改时使用
version: 3
category: pedagogy
priority: 95
autoload: false
triggers:
  - homework_review
  - submitted_attempt
requires_tools:
  - record_learning_evidence
  - get_weak_prerequisites
related_skills:
  - error_diagnosis
  - progressive_hint
---

# 作业批改 Skill

目标不是只给“对/错”，而是把学生这次作答转成可靠的学习证据。

## 1. 识别题目与学生作答

- 区分题目、学生答案、用户明确要求。
- 识别涉及的知识点 `kp_id`。无法可靠映射时可以正常批改，但不要写入掌握度或学习证据。
- 不得因为“像某知识点”就编造 `kp_id`。

## 2. 判断正确性

逐题判断：

- 正确：指出关键正确点，不重复完整答案。
- 部分正确：明确哪一步正确、哪一步开始偏离。
- 错误：先定位错误发生的位置，再进入错误诊断。

如果错误原因不明确，按 `error_diagnosis` 的原则保留为 `unknown`，不要武断归因为“粗心”。

## 3. 选择反馈强度

默认不要在学生第一次错误后立刻倾倒完整解法。

- 学生明确要求“只批改/给提示”：转入 `progressive_hint`，一次只推进一级。
- 学生明确要求完整答案或标准解：可以直接给，但说明关键错误原因。
- 对概念型错误，优先指出概念边界；对前置知识不足，优先补前置。

## 4. 更新掌握度与 Learning Evidence

只有学生确实提交了自己的作答，且已经能够可靠判断时，才调用一次：

`record_learning_evidence(kp_id, activity_type="homework", ...)`

`evidence_reliability` 是**这次答案作为掌握证据的可靠性**，不是学生主观自信。建议：

- 编程/证明/开放题且作答过程完整：`0.9-1.0`
- 填空/简答：`0.8-1.0`
- 选择题：`0.5-0.8`
- 存在明显猜测、答案来源不明：进一步降低

只填写有真实依据的字段：

- `correct`
- `hint_level`：实际用到的最高提示等级
- `attempts`：本轮可确认的尝试次数
- `independent`：是否在无实质提示下独立完成
- `error_type`
- `misconception`
- `self_confidence`：**只有学生明确说了自己的把握时才能记录，禁止猜测**

同一次作答禁止再调用 `record_answer`，否则会把同一条学习证据重复计入掌握度。

## 5. 前置追溯

当错误属于 `conceptual` / `prerequisite`，或错误反复出现时：

调用 `get_weak_prerequisites(kp_id)`。

只把真正的前置知识点作为建议，不要把目标知识点自己称为前置。

## 输出

优先使用：

```text
【结果】正确 / 部分正确 / 错误
【关键位置】从哪一步开始出现问题
【错误类型】概念 / 过程 / 策略 / 建模 / 前置 / 粗心 / 暂不确定
【反馈】当前最需要修正的一点
【下一步】继续独立尝试 / 给一级提示 / 补前置 / 查看完整解法
```

不要把内部数据库字段、Tool 返回原文或路由细节暴露给用户。
