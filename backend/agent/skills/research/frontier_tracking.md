---
name: frontier_tracking
description: 判断何时需要前沿追踪，形成 query/time window，解释异步 action 与项目绑定
version: 1
category: research
priority: 85
autoload: false
triggers: [frontier_tracking, research_frontier, literature_frontier]
requires_tools: [start_frontier_tracking, retrieve_knowledge]
related_skills: [research_grounding]
---

# 前沿追踪

## 1. 触发条件
用户请求追踪研究前沿、文献调研、研究热点分析或领域发展脉络时触发。

## 2. 任务澄清
1. **明确追踪目标**：研究领域、具体问题、关注维度（热点/趋势/代表工作/方法演进）
2. **确定时间窗口**：近1年/3年/5年或自定义时间段
3. **确认项目绑定**：检查是否已绑定科研项目（`project_id`）

## 3. Query 构建
从用户请求中提取：
- **核心关键词**：2-5个领域核心术语
- **扩展词**：同义词、上位/下位概念
- **排除词**：不相关的歧义领域

## 4. 异步 Action 机制
`start_frontier_tracking` 是异步 action，需向用户解释：
1. **审批流程**：action 需要审批后才执行
2. **项目绑定**：action 绑定到当前科研项目，结果归档到项目
3. **异步执行**：提交后不会立即返回结果，系统会在后台完成追踪
4. **结果获取**：追踪完成后会通知用户，结果可从项目上下文获取

## 5. 执行流程
1. 调用 `retrieve_knowledge` 检索已有相关资料，了解当前知识状态
2. 构建追踪 query 和时间窗口
3. 调用 `start_frontier_tracking` 提交异步追踪请求
4. 向用户说明 action 状态和后续步骤

## 6. 输出规范
```text
【追踪目标】
明确的研究领域和关注维度

【Query 构建】
核心关键词、扩展词、时间窗口

【Action 状态】
已提交追踪请求，绑定到项目 [project_id]
预计完成时间：[时间]
后续步骤：[说明]
```

## 7. 禁止事项
- 未绑定项目时不得提交追踪请求
- 不得伪造追踪结果
- 不得跳过任务澄清直接提交
- 不得承诺即时返回结果
