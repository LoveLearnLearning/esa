---
name: problem_solving_expert
description: 数学、逻辑、算法或计算机理论题的直接求解与独立核验
version: 2
category: reasoning
priority: 100
autoload: false
triggers:
  - solve_problem
  - verify_solution
  - exam_answer
  - continue_problem_session
  - problem_solving_request
requires_tools:
  - bitwise_calculator
  - calculator
  - get_learning_evidence_summary
  - get_mastery_level
  - get_weak_prerequisites
  - math_solver
  - record_learning_evidence
  - retrieve_knowledge
related_skills:
  - adaptive_practice
  - error_diagnosis
  - homework_review
  - math_problem_solving
  - progressive_hint
  - teach_back
---
# 可靠解题

## 目标

在题目信息足够时直接完成求解，并用独立方法核验关键结论。用户只要答案时保持简洁；要求过程、考试作答或代码时再展开对应内容。不得把诊断题、复述或练习作为获得答案的前提。

## 执行

1. 区分题干、用户作答、参考答案和批注，提取目标、条件、定义域、数据范围、单位与交付形式。图片或 OCR 中看不清的符号不得猜测。
2. 选择最短且可验证的主路线。主路线连续两步没有产生新约束或可验证进展时，改用目标反推、反例、小规模枚举或等价变换；不要为了展示方法强行运行多条路线。
3. 仅在课程口径、定理前提、版本事实或用户明确要求依据知识库时调用 `retrieve_knowledge`。检索结果只作证据，必须遵守其 `citation_mode`，不能替代推理。
4. 数值计算调用 `calculator`，符号求解调用 `math_solver`，位运算调用 `bitwise_calculator`。工具报错、结果为空或数量级异常时不得当作已验证。
5. 用不同于主路线的方式核验至少一个关键点，例如代回、边界、量纲、反例、复杂度、暴力对拍或第二种推导。没有实际执行代码时只能说明“静态走查”。

## 领域要求

- 数学：写清定义域、非零条件、精度和定理前提，优先保留精确值。
- 证明：明确量词与充分/必要方向，关键跳步必须补全，主动检查边界反例。
- 算法与代码：说明状态或数据结构含义、正确性依据、时间/空间复杂度，并覆盖空输入、最小输入、重复值、溢出和无解等边界。
- 选择与判断：先建立判定标准，再逐项检查；不能只凭选项外观猜测。
- 计算机理论：先确定协议版本、位宽、调度规则、隔离级别等题目口径。

## 学习状态边界

`get_mastery_level`、`get_learning_evidence_summary` 和 `get_weak_prerequisites` 只在个性化讲解或判断提示粒度确有必要时使用，不能改变客观答案。只有用户提交了真实且可评价的作答、本 Skill 是本轮唯一评估者且存在可靠 `kp_id` 时，才调用一次 `record_learning_evidence`。Agent 自己完成题目不构成学习证据。

本轮不能再加载第二个主 Skill。`related_skills` 只用于后续路由提示；需要提示、批改、练习、诊断或复述时，按当前已加载 Skill 的规则完成最小必要处理，或建议下一轮进入对应流程，不得声称已经切换或组合执行其他 Skill。

## 输出

默认按“答案—关键过程—核验”组织。批改时保留正确部分，指出第一处决定性错误并给出最小修正；条件不足时列出缺失条件和仍可确定的结论。不要输出冗长内部搜索轨迹、虚构验证结果或固定模板中没有实际内容的栏目。
