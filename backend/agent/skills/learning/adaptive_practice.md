---
name: adaptive_practice
description: 用户请求出题、开始或继续练习，或正在回答 Agent 上一轮练习题时使用
version: 1
category: pedagogy
priority: 98
autoload: false
triggers:
  - start_practice
  - continue_practice
  - submitted_practice_answer
requires_tools:
  - get_mastery_level
  - get_learning_evidence_summary
  - get_weak_prerequisites
  - record_learning_evidence
related_skills:
  - error_diagnosis
  - progressive_hint
---

# 自适应练习 Skill

目标：根据学生当前掌握状态每次生成一道合适的题，并把真实作答转换成一次可靠的学习证据。

## 开始或继续练习

1. 先确定一个可靠的 canonical `kp_id`。若“Resolved learning context”提供了 `resolved_kp_ids` 或 `pending_practice_kp_id`，它们是服务端已解析的可信值：直接使用，不得再次向用户确认。只有该可信上下文为空且无法从当前任务可靠确定时，才询问；不得猜测，也不得写入学习状态。
2. 在出题前调用 `get_mastery_level(kp_id)`。如需判断提示依赖和常见误区，再调用 `get_learning_evidence_summary(kp_id)`。
3. 根据返回的掌握状态选择难度：
   - 无记录或 `mastery < 40`：基础概念、识别题或单步骤题。
   - `40 <= mastery < 75`：标准应用题和常见易错点。
   - `mastery >= 75`：边界条件、辨析、迁移或综合题。
4. 每次只出一道题，不同时公布答案。题目必须以下列标记开头，使后续短回复仍能与当前练习关联：

```text
【练习题｜知识点：<canonical kp_id>】
```

5. 出题本身不是学习证据，不得调用任何写入工具。

## 处理学生作答

1. 如果最近一条 Agent 回复包含 `【练习题｜知识点：...】`，用户本轮即使只回复 `A`、`42`、一行公式、一段代码或“不会”，也应视为对该题的作答。
2. 从标记中读取 `kp_id`，结合原题、评分标准和学生的完整作答，判断正确、部分正确或错误。
3. 只在已有真实作答且可以可靠判断时，调用一次 `record_learning_evidence`：
   - `activity_type="practice"`
   - `correct`：必须来自实际批改结果。
   - `evidence_reliability`：开放题且过程完整可较高；选择题或有猜测可能时降低。
   - `hint_level`：本题实际用到的最高提示等级。
   - `attempts`：从本题对话中能够确认的尝试次数。
   - `independent`：是否未受实质提示或答案泄露影响。
   - 只有真有依据时才写 `error_type`和 `misconception`。
4. 同一次作答只能写入一次；禁止再调用 `record_answer`。
5. 工具返回 `saved=false` 时明确说明未保存，不得假装已经更新掌握度。

## 禁止写入的情况

- 用户只表示“准备学习”“打算做题”或“开始练习”。
- Agent 刚刚出题，学生还没有作答。
- 只给了提示，但学生尚未产生新的表现。
- 无法确定 `kp_id` 或无法判断正确性。

## 反馈格式

```text
【结果】正确 / 部分正确 / 错误
【关键点】最重要的判断依据
【下一步】继续尝试 / 一级提示 / 下一题
```

不要暴露原始工具协议、数据库字段或内部评分过程。
