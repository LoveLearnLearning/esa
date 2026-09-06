---
name: frontier_tracking
description: 为已绑定科研项目构造并提交可审计的前沿追踪请求
version: 2
category: research
priority: 85
autoload: false
triggers: [frontier_tracking, research_frontier, literature_frontier]
requires_tools: [start_frontier_tracking]
related_skills: [research_grounding]
---
# 前沿追踪

确认研究问题、时间窗口和结果规模；只有会改变查询的歧义才需要追问。当前运行时会校验科研项目绑定，模型不得自行提供或猜测 `project_id`。

本轮提供 `retrieve_knowledge`，且用户要求先盘点已有知识库材料或已有材料会影响检索式时，才调用它；纯粹提交新的前沿追踪任务时无需机械检索。检索结果遵守 `citation_mode`。

将问题压缩为明确 query，合理设置 `time_window_years` 和 `max_results`，然后调用 `start_frontier_tracking`。该 Tool 创建的是需要审批的异步 Action；只有 Tool 成功返回后才能说请求已创建，并应原样报告其状态或标识。

不得承诺完成时间、后台通知或最终结果质量，因为 Tool 契约不提供这些保证。调用失败时报告错误和可修正的参数，不得声称任务仍在运行。
