---
name: research_writing
description: 科研写作/改写/结构化编辑，处理 source_text、document_id、引用边界
version: 1
category: research
priority: 85
autoload: false
triggers: [research_writing, academic_writing, paper_writing]
requires_tools: [start_research_writing, retrieve_knowledge]
related_skills: [research_grounding]
---

# 科研写作

## 1. 触发条件
用户请求科研论文写作、段落改写、结构化编辑、摘要撰写、引言/方法/结果/讨论章节写作时触发。

## 2. 任务澄清
1. **写作类型**：全文/章节/段落/摘要/改写/润色
2. **目标文档**：新建文档或编辑已有文档（需 `document_id`）
3. **源文本处理**：用户提供的草稿、笔记、数据或参考内容
4. **引用要求**：是否需要引用、引用风格（APA/MLA/Chicago等）

## 3. 引用边界
1. **事实性陈述**：需要引用支持
2. **方法描述**：引用原始方法文献
3. **数据结果**：引用数据来源
4. **观点讨论**：区分个人观点和引用观点
5. **合理使用**：引用长度不超过合理范围，避免大段复制

## 4. 异步 Action 机制
`start_research_writing` 是异步 action，需向用户解释：
1. **审批流程**：action 需要审批后才执行
2. **项目绑定**：写作任务绑定到当前科研项目
3. **文档关联**：可关联已有文档（`document_id`）或创建新文档
4. **异步执行**：复杂写作任务在后台完成

## 5. 执行流程
1. 调用 `retrieve_knowledge` 检索相关文献和资料
2. 分析用户提供的源文本和写作要求
3. 构建写作任务参数（类型、目标、约束）
4. 调用 `start_research_writing` 提交写作请求
5. 向用户说明 action 状态和后续步骤

## 6. 输出规范
```text
【写作任务】
类型、目标文档、写作要求

【内容规划】
结构大纲、章节安排、关键论点

【引用处理】
需要引用的关键点、引用风格、边界说明

【Action 状态】
已提交写作请求，绑定到项目 [project_id]
文档ID：[document_id]（如适用）
预计完成时间：[时间]
```

## 7. 禁止事项
- 不得伪造引用来源
- 不得大段复制受版权保护的内容
- 不得混淆用户原创内容和引用内容
- 不得跳过引用边界说明
- 未绑定项目时不得提交写作请求
