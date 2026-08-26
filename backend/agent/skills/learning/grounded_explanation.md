---
name: grounded_explanation
description: 基于课程库讲解
version: 4
category: pedagogy
priority: 82
autoload: false
triggers: [concept_learning, explanation_request]
requires_tools: [retrieve_knowledge, get_mastery_level]
related_skills: [teach_back]
---

# 有依据的讲解

用明确问题调用 `retrieve_knowledge`，有可信 `kp_id` 直接使用；仅当掌握度会改变讲解时调用 `get_mastery_level`。命中后用自己的话直接回答结论、机制、最小例子和边界/易错点，来源只作证据。严格遵守 `citation_mode`：仅 `verbatim_allowed` 可逐字引述；`paraphrase_only_unverified` 必须转述、标明解析/OCR 未验证且不用引号。无结果或失败时说明未取得知识库证据，同轮用通用知识回答。复述题只能作为可选后续，本 Skill 不写学习证据。
