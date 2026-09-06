---
name: research_grounding
description: 基于可追溯证据区分来源事实、分析推断和生成建议
version: 2
category: research
priority: 80
autoload: false
triggers: [research_grounding, source_verification, fact_check]
requires_tools: [retrieve_knowledge]
related_skills: [frontier_tracking, research_writing, dataset_analysis]
---
# 科研溯源

把待核对内容拆成可验证主张，再调用 `retrieve_knowledge` 搜索与主张直接相关的证据。用户已经提供材料时也应先从材料中定位证据范围，避免用宽泛检索替代核对。

每条结果必须执行以下判断：

1. **相关性**：证据是否直接支持当前主张，还是只提供背景。
2. **来源与范围**：记录文件、页码/位置、适用对象、时间和方法限制；Tool 未返回的元数据不得补造。
3. **引用权限**：只有 `citation_mode=verbatim_allowed` 才能逐字引用；`paraphrase_only_unverified` 只能用自己的话转述，并明确说明文字解析或 OCR 未经验证，禁止加引号冒充原文。
4. **结论强度**：区分“证据直接陈述”“基于证据推断”“目前没有足够证据”。不要把相关性提升为因果，也不要虚构置信度数值。
5. **冲突**：可靠来源不一致时分别呈现范围和差异，不强行合并成单一结论。

输出优先采用“主张—证据—判断—限制”的紧凑结构。没有检索结果或 Tool 失败时明确说明没有取得知识库证据；可以提供通用分析方法，但不得生成不存在的来源、引文、页码或审核结论。
