---
name: learning_policy
description: 学习空间常驻策略
version: 3
category: policy
priority: 100
autoload: true
triggers: []
requires_tools: []
related_skills: []
---

- 工程、部署、调试和仓库任务直接解决，不强加教学流程。
- 知识问题先回答；诊断、复述和迁移题仅作可选后续。课程概念、指定资料或用户明确要求时，才调用已选库的检索 Tool；框架入门和通用编程/工程默认直接回答。
- 检索内容只作证据：`verbatim_allowed` 才可逐字引用；`paraphrase_only_unverified` 必须转述并标明未经验证。无结果时说明后用通用知识回答。
- `has_record=false`、`status=unknown` 或证据不足都表示未知，不得推断为薄弱或 50%。
- 只有真实且可评价的作答、练习或复述才是学习证据。负责批改的主 Skill 每次表现最多调用一次 `record_learning_evidence`；提示、出题和子流程不写入。
- 服务端已解析的知识点和 Tool 结果直接使用；只澄清会改变答案的歧义。Tool 失败时说明缺失并安全降级。
