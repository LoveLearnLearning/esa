---
name: error_diagnosis
description: 学生答案错误或部分正确时，定位错误来源和可复用误区
version: 1
category: pedagogy
priority: 92
autoload: false
triggers:
  - wrong_answer
  - repeated_error
requires_tools:
  - get_weak_prerequisites
  - record_learning_evidence
related_skills:
  - progressive_hint
---

# Error Diagnosis

把“做错了”拆成可行动的诊断，不要默认所有错误都是知识点不会。

## 错误类型

优先从以下类型判断：

- `conceptual`：定义、性质、条件边界理解错误
- `procedural`：步骤、计算、代码执行过程错误
- `strategic`：选择了不合适的方法或算法
- `representation`：题意建模、状态表示、变量含义错误
- `prerequisite`：当前错误主要由前置知识缺口导致
- `careless`：规则本身会，但出现可验证的局部执行失误
- `unknown`：证据不足

`careless` 只能在有证据表明学生理解规则、但本次局部执行失误时使用。
证据不足时宁可 `unknown`。

## 流程

1. 找出“第一处决定性错误”，不要只看最终答案。
2. 判断错误类型。
3. 写出一句具体 `misconception`，例如：
   - 好：`把二分查找的闭区间 [l,r] 和左闭右开 [l,r) 更新规则混用`
   - 差：`二分查找掌握不好`
4. 如果怀疑前置不足，调用 `get_weak_prerequisites` 验证。
5. 学生已经产生真实作答时，若本 Skill 独立负责本轮批改，调用
   `record_learning_evidence` 保存错误类型和误区；如果由 `homework_review` 或
   `adaptive_practice` 调用本 Skill，则把诊断字段交给上层 Skill 的那一次写入，避免重复计数。
6. 下一步默认转为一级 `progressive_hint`，除非用户明确要求完整解答。

`get_weak_prerequisites` 或写入工具失败时，不中断诊断：说明当前证据不足，继续给出基于作答本身
能够确认的局部反馈，不把失败包装成已更新状态。

不要根据一次错误推断长期人格、能力或学习态度。
