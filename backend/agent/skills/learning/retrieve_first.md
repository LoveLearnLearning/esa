---
name: retrieve_first
description: 用户学习概念或原理时，先做一次低成本主动回忆再针对缺口讲解
version: 1
category: pedagogy
priority: 82
autoload: false
triggers:
  - concept_learning
  - explanation_request
requires_tools:
  - get_mastery_level
  - record_learning_evidence
related_skills:
  - teach_back
---

# Retrieve First

目标：在讲解前先获得一条低成本诊断证据，并激活学生已有知识。

## 流程

1. 识别当前知识点 `kp_id`；不确定时不要硬写数据。
2. 如有必要调用 `get_mastery_level(kp_id)`，只用于决定问题难度。
3. 在正式讲解前，先问**一个**很短的主动回忆问题，例如：
   - “先不用查资料，你觉得这个概念最核心的一句话是什么？”
   - “你现在能说出它和 X 的一个区别吗？”
4. 用户回答后，只针对缺失/错误部分讲解。
5. 有可靠 `kp_id` 时，把这次表现记录为 `activity_type=retrieval`，可记录 `recall_score`。
6. 讲解后可转入 `teach_back`。

## 例外

- 用户明确说“直接讲，不要提问”：直接讲。
- 工程排障、代码交付、部署问题：不要套 Retrieve First。
- 用户只是问一个事实性短问题：不要为了教学流程增加摩擦。
