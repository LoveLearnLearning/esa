---
name: research_writing
description: 为已有授权科研文档提交改写、扩写或结构化编辑请求
version: 2
category: research
priority: 85
autoload: false
triggers: [research_writing, academic_writing, paper_writing]
requires_tools: [start_research_writing]
related_skills: [research_grounding]
---
# 科研写作

`start_research_writing` 只能处理已经存在且属于当前用户科研项目的 `document_id`，不能创建新文档。没有 `document_id` 时，应请用户先选择或创建文档，或者直接在对话中提供文本建议；不得声称已创建文档。

确认 `operation`、写作目标、目标读者、保留内容和来源文本。仅在本轮提供了 `retrieve_knowledge`，并且事实性内容需要证据、用户明确要求引用，或知识库材料是任务输入时调用它；单纯润色用户提供的文本不应无条件检索。检索内容只作证据并遵守 `citation_mode`，不得伪造引用。

参数充分时调用 `start_research_writing(document_id, operation, instruction, source_text)`。这是需要审批的异步 Action；只有 Tool 成功返回后才能报告请求已创建，并且只能引用返回的状态和标识。

不得承诺预计完成时间、完成通知或自动发表。不得把模型生成内容冒充用户原文或检索原文；涉及引用时清楚区分原文、转述和模型建议。
