---
name: dataset_analysis
description: 为已授权数据集选择方法并提交边界明确的分析请求
version: 2
category: research
priority: 85
autoload: false
triggers: [dataset_analysis, data_analysis, research_data_analysis]
requires_tools: [start_dataset_analysis]
related_skills: [research_grounding]
---
# 数据集分析

先从用户请求和已提供材料中确认研究问题、`dataset_id`、变量含义、分析类型与期望产出。缺少会导致方法完全不同的字段时再询问，不得猜测数据内容、样本量或授权状态。

仅在本轮提供了 `retrieve_knowledge`，并且需要核对统计方法前提、领域口径或用户明确要求知识库依据时调用它；用户已经给出完整方法或只是提交明确分析任务时不要机械检索。检索结果遵守 `citation_mode`。

选择方法时写清关键假设和参数，并把它们放入 `parameters`；随后调用 `start_dataset_analysis(dataset_id, analysis_type, parameters)`。该 Tool 创建需要审批的异步 Action，并由运行时校验项目和数据集授权。只有成功返回后才能报告请求已创建，且只能报告返回的状态、标识和字段。

不得虚构描述统计、显著性、图表或模型效果；这些必须来自真实分析结果。不得承诺 ETA、主动通知或自动导出。若输入数据不足，可先给分析方案，但不能假装已提交或已执行。
