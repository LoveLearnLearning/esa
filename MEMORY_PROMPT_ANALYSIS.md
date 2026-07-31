# 记忆功能与提示词系统 — 行业对标分析报告

> 负责模块：记忆系统（TempMemory / CoreMemory / 知识图谱 / 掌握度模型）+ 提示词系统（build_prompt / 风格语调 / 学情档案注入）
>
> 对标范围：MemGPT/Letta、LangChain Memory、OpenAI ChatGPT Memory、Mem0、Zep/Graphiti、LlamaIndex Memory、Khanmigo、ChatGPT Edu、Google Gemini、Anthropic Claude
>
> 资料时间：2024-2026 年公开资料 + WebSearch 检索

---

## 一、项目现状与行业标杆的详细对比分析

### 1.1 记忆系统架构对比

| 维度 | 本项目 ESA | 行业标杆（普遍做法） | 差距等级 |
|------|-----------|---------------------|---------|
| **记忆分层** | 两层扁平：TempMemory（内存，20条）+ CoreMemory（SQLite，无上限） | 三层分页：MemGPT core/archival/recall；LlamaIndex 短期FIFO+长期MemoryBlock；Zep Episode/Semantic/Community 三层图 | 🔴 严重 |
| **存储方式** | SQLite（core_memory.db / mastery.db / knowledge_graph.db） | 标杆组合：SQLite/Postgres + 向量库（pgvector/Chroma/FAISS）+ 图数据库（Neo4j/FalkorDB） | 🟡 中等 |
| **检索方式** | **全量注入**：`build_context` 返回用户全部核心记忆，无过滤 | 多信号混合检索：Mem0 语义+关键词+实体+图扩展+reranking；Zep cosine+BM25+BFS→RRF+MMR+cross-encoder | 🔴 严重 |
| **记忆管理策略** | 无自动遗忘、无摘要、无重要性评分、无冲突检测、无过期 | Mem0 两阶段 Extraction+Update（去重/合并/冲突检测）；Zep bi-temporal 时序事实管理（自动使旧事实失效）；LlamaIndex 自动 flush+压缩 | 🔴 严重 |
| **容量限制** | TempMemory 20条；CoreMemory **无上限**；无 token 预算 | Mem0 <7K token/查询；Zep ~1.6K token 达 71.2% 准确率；LlamaIndex 默认 token_limit=30000，ratio 0.7 | 🔴 严重 |
| **个性化能力** | ✅ 教育特化：知识图谱（473知识点/439边）+ 掌握度模型（BKT+HLR+Ebbinghaus）+ 学习档案（major/grade/week） | Khanmigo 集成 Khan Academy 进度系统；Duolingo 间隔重复+遗忘曲线；ChatGPT Edu 工作区隔离 | 🟢 较好 |
| **可视化管理** | 有 CRUD API（save/get/delete_core_memory）；**无前端 UI** | ChatGPT Memory Summary+Sources 页面；Mem0 Platform UI；Letta REST API+memory block 编辑器；Gemini Saved Info 页面 | 🟡 中等 |
| **隐私与安全** | ContextVar 用户隔离；参数化 SQL 防注入；**无加密、无临时对话、无保留期策略** | ChatGPT Edu FERPA 合规+不训练+180天保留+SSO；OpenAI Enterprise AES-256+TLS1.2+；Gemini Temporary Chat 72h 不留痕 | 🟡 中等 |

### 1.2 提示词系统对比

| 维度 | 本项目 ESA | 行业标杆（普遍做法） | 差距等级 |
|------|-----------|---------------------|---------|
| **结构设计** | 单一扁平字符串（~200 tokens），Markdown 标题分块 | Claude 4 XML 标签模块化（`<instructions>`/`<rules>`/`<constraints>`）；OpenAI `[RULE]`/`[EXAMPLE]` 括号标签；Gemini 3 官方建议"改掉长文叙述，改用 XML 标签" | 🔴 严重 |
| **风格/语调控制** | 3档风格×4档语调=12组合，每档**一句话描述** | OpenAI Structured Outputs JSON Schema 参数化（100% schema 合规）；Claude 自由文本+Styles模块+prefill；Gemini 温度+模板变量连续控制 | 🟡 中等 |
| **token 预算管理** | **无**：`build_system_prompt` 直接拼接所有区块，无计数、无截断 | Atlan 2026 指南："写任何 prompt 前先定 token 预算"；LangChain `ConversationTokenBufferMemory` 按时间+重要性截断；静态/动态分离启用 prompt caching（成本降 90%） | 🔴 严重 |
| **评估与优化** | **无评估框架**：无评估代码、无数据集、无 LLM-as-judge | RAGAS（faithfulness/relevancy）；DeepEval（toxicity/bias）；LangSmith/promptfoo A/B 测试+版本管理；LLM-as-judge JSON Schema 约束 | 🔴 严重 |
| **安全/宪法层级** | 无显式安全优先级 | OpenAI Model Spec 红线原则优先于一切；Anthropic CAI ~10 条原则+安全>伦理>指南>有用 显式优先级 | 🟡 中等 |
| **Socratic 实现** | `socratic` 枚举："用反问引导思考 不直接给答案"（一句话） | Khanmigo：先定位卡点→反问→渐进提示；反滥用：连续3次低努力回答后停止提示；用例题讲解非原题 | 🔴 严重 |
| **Few-Shot 示例** | 无 | Claude/Gemini/Khanmigo 均强调 few-shot 为"黄金法则"，1-2 例比纯描述更精准 | 🟡 中等 |
| **版本管理** | 硬编码在 `build_prompt.py`，无版本号 | 提示即代码：LangSmith/promptfoo/Braintrust dev/staging/prod 环境隔离+版本关联评估 | 🟡 中等 |

---

## 二、关键指标的量化评估

### 2.1 记忆系统评分卡（满分 100）

| 评估维度 | 权重 | 得分 | 加权 | 说明 |
|---------|------|------|------|------|
| 分层架构 | 15% | 20 | 3.0 | 仅两层扁平，无 archival/recall 分层 |
| 存储方式 | 10% | 60 | 6.0 | SQLite 持久化达标，缺向量库/图数据库 |
| 检索方式 | 15% | 15 | 2.25 | 全量注入，无相关性过滤/向量检索 |
| 记忆管理 | 15% | 20 | 3.0 | 无自动遗忘/摘要/冲突检测/过期 |
| 容量控制 | 10% | 25 | 2.5 | TempMemory 20条，CoreMemory 无上限无预算 |
| 个性化能力 | 15% | 75 | 11.25 | ✅ 教育特化（知识图谱+掌握度+学习档案） |
| 可视化管理 | 10% | 40 | 4.0 | 有 CRUD API，无前端 UI |
| 隐私安全 | 10% | 55 | 5.5 | 用户隔离+SQL防注入，缺加密/临时对话 |
| **总计** | 100% | — | **37.5/100** | — |

### 2.2 提示词系统评分卡（满分 100）

| 评估维度 | 权重 | 得分 | 加权 | 说明 |
|---------|------|------|------|------|
| 结构设计 | 20% | 25 | 5.0 | 扁平字符串，无 XML 标签/模块化 |
| 风格控制 | 15% | 40 | 6.0 | 枚举但每档一句话太粗 |
| token 预算 | 15% | 5 | 0.75 | 无计数/截断/优先级 |
| 评估框架 | 15% | 0 | 0.0 | 完全缺失 |
| 安全层级 | 10% | 20 | 2.0 | 无宪法/红线优先级 |
| Socratic 流程 | 10% | 15 | 1.5 | 一句话描述，无反滥用/渐进提示 |
| Few-Shot | 5% | 0 | 0.0 | 无示例 |
| 版本管理 | 10% | 10 | 1.0 | 硬编码无版本 |
| **总计** | 100% | — | **16.25/100** | — |

### 2.3 行业基准对比

| 指标 | 本项目 | 行业标杆 | 差距 |
|------|--------|---------|------|
| System Prompt 长度 | ~200 tokens | Khanmigo ~600-800 tokens；Claude 4 数千 tokens | 3-15 倍偏短 |
| 记忆检索 token | 全量（无上限） | Mem0 <7K；Zep ~1.6K 达 71.2% | 无预算控制 |
| 风格控制组合数 | 12 种（3×4） | OpenAI JSON Schema 无限组合 | 粒度粗 |
| 评估覆盖率 | 0% | RAGAS 5 指标；DeepEval 多维度 | 完全缺失 |
| 记忆准确率 | 未评估 | Mem0 92.5%（LoCoMo）；Zep 71.2%（LongMemEval） | 无基线 |
| 检索延迟 | 全量注入~0ms | OpenAI 0.9s；Mem0 1.4s；Zep 2.58s | 不可比（无检索） |
| 记忆条数上限 | 无限 | ChatGPT 无限但有 Summary 压缩；Mem0 <7K token | 无压缩 |
| 个性化深度 | 3档静态阈值 | TutorLLM 动态 KT（满意度+10%）；VARK 4模态（均分+5） | 静态 vs 动态 |

---

## 三、基于行业最佳实践的改进建议

### 3.1 P0 优先级（必须做，影响核心功能）

#### 建议 1：记忆检索引入 token 预算 + 相关性过滤

- **现状**：`CoreMemory.build_context` 一次性返回用户全部记忆，记忆多了会撑爆 system prompt
- **标杆做法**：Mem0 <7K token/查询；Zep ~1.6K token 达 71.2%；LlamaIndex `token_limit=30000` + `chat_history_token_ratio=0.7`
- **改进方案**：
  1. `build_context` 加 `max_tokens: int = 2000` 参数
  2. 按优先级排序：最近更新 > 高频访问 > 早期记忆
  3. 超 budget 时从低优先级开始截断
  4. 保留 `category` 维度的最小覆盖（每类至少 1 条）

#### 建议 2：System Prompt 模块化重构（XML 标签）

- **现状**：~200 tokens 单一扁平字符串
- **标杆做法**：Claude 4 XML 标签（`<role>`/`<rules>`/`<style>`/`<memory>`）；OpenAI `[RULE]`/`[EXAMPLE]` 括号标签；Gemini 3 官方建议 XML 标签
- **改进方案**：
  1. 将 `SYSTEM_PROMPT` 拆分为 `<role>`/`<rules>`/`<style>`/`<profile>`/`<memory>`/`<skills>` 模块
  2. 静态部分（role/rules）和动态部分（memory/profile/skills）分离
  3. 静态部分启用 prompt caching（成本降 90%，延迟降 85%）
  4. 关键规则放首尾（OpenAI 数据：中间指令遗忘率最高）

#### 建议 3：接入自动化评估框架

- **现状**：无评估代码、无数据集、无 LLM-as-judge
- **标杆做法**：RAGAS（faithfulness/relevancy/context precision）；DeepEval（toxicity/bias）；LLM-as-judge JSON Schema 约束
- **改进方案**：
  1. 引入 RAGAS 评估记忆检索质量（faithfulness + context precision）
  2. 构建 20-50 条教育场景测试用例
  3. 风格/语调切换效果用 LLM-as-judge 打分
  4. 接入 promptfoo 做 CI 门控（改动前后对比）

### 3.2 P1 优先级（应该做，影响 demo 效果）

#### 建议 4：Socratic 反滥用流程补全

- **现状**：`socratic` 枚举仅一句话"用反问引导 不直接给答案"
- **标杆做法**：Khanmigo 先定位卡点→反问→渐进提示；连续 3 次低努力回答后停止提示并反问"哪里不懂"
- **改进方案**：
  1. `socratic` 档展开为多步流程：定位卡点 → 反问 → 渐进提示 → 例题讲解
  2. 加反滥用规则：连续 N 次低努力回答后切换策略
  3. 用例题讲解而非原题（防作业代写）
  4. declarative knowledge 卡死时给选项

#### 建议 5：核心记忆加冲突检测 + 过期机制

- **现状**：相同 `memory_key` 覆盖旧值，无冲突检测；无过期清理
- **标杆做法**：Mem0 两阶段 Extraction+Update（向量比对去重/合并/冲突检测）；Zep bi-temporal（`valid_at`/`invalid_at`/`expired_at`）
- **改进方案**：
  1. `set` 前检查同 `memory_key` 旧值，内容差异大时保留版本历史
  2. 加 `expires_at` 字段，过期记忆自动排除
  3. 加 `access_count`/`last_accessed_at` 字段，低频记忆降权
  4. 定期清理任务（cron 或启动时检查）

#### 建议 6：Constitutional 安全优先级层级

- **现状**：无显式安全原则层级
- **标杆做法**：OpenAI Model Spec 红线原则优先于一切；Anthropic CAI 安全>伦理>指南>有用 显式优先级
- **改进方案**：
  1. System Prompt 加 `<safety>` 模块，定义红线（不代写作业答案/不泄露内部记忆/不编造）
  2. 明确优先级：安全 > 教育合规 > 用户偏好 > 有用性
  3. 冲突时按优先级裁决

### 3.3 P2 优先级（可以做，提升体验）

#### 建议 7：风格控制升级为参数化

- **现状**：3×4 枚举，每档一句话
- **标杆做法**：OpenAI Structured Outputs JSON Schema（100% 合规）；Claude 自由文本+Styles 模块
- **改进方案**：
  1. 每档风格展开为多条可执行规则（句长上限/是否给例子/是否分段/术语密度）
  2. 支持用户自定义规则模板
  3. 加 `response_length`（short/medium/long）和 `example_preference`（with/without）维度

#### 建议 8：掌握度从静态阈值升级为动态 KT

- **现状**：3 档静态阈值（<40 / 40-75 / ≥75）
- **标杆做法**：TutorLLM（RecSys 2024）动态 KT+RAG（满意度+10%，测验分+5%）；GRKT（KDD 2024）对话级 KT
- **改进方案**：
  1. 当前 MasteryStore 已有 BKT+HLR+Ebbinghaus，但注入 prompt 时只取 3 档
  2. 注入连续掌握度值 + 趋势（上升/下降/稳定）
  3. 加最近 N 次答题正确率时序

#### 建议 9：引入 VARK 学习风格适配

- **现状**：未实现
- **标杆做法**：IEEE Access 2024（450 学生，均分 70→75）；VARK 分布 Visual 29%/Aural 30%/Read-Write 27%/Kinesthetic 14%
- **改进方案**：
  1. `UserRecord` 加 `learning_style: str = "read_write"` 字段
  2. `build_system_prompt` 加 `learning_style` 参数
  3. 不同风格调整讲解策略（视觉→图示/类比；听觉→口诀/节奏；读写→定义/列表；动觉→实例/操作步骤）

---

## 四、与同类优秀案例的对标分析

### 4.1 教育领域 AI 对标

| 维度 | Khanmigo（行业标杆） | ChatGPT Edu | Duolingo Max | 本项目 ESA |
|------|---------------------|-------------|--------------|-----------|
| **Socratic 引导** | ✅ 强约束：never give answer；反滥用；渐进提示 | ❌ 通用对话 | ✅ Roleplay 引导 | 🟡 一句话描述 |
| **掌握度追踪** | ✅ Khan Academy 进度系统 | ❌ 无 | ✅ 间隔重复+遗忘曲线 | ✅ BKT+HLR+Ebbinghaus |
| **知识图谱** | ✅ Khan Academy 课程树 | ❌ 无 | ✅ 技能树 | ✅ 473知识点/439边 |
| **学习档案** | ✅ 教师仪表盘 | ✅ 工作区管理 | ✅ 错误分析 | 🟡 后端有，前端无 |
| **隐私合规** | ✅ 学生隐私保护 | ✅ FERPA+不训练+180天 | 🟡 数据用于产品 | 🟡 用户隔离，无合规认证 |
| **个性化深度** | 🟡 按学生兴趣定制 | ❌ 无 | ✅ Gamification+streak | ✅ 掌握度+教学进度 |
| **来源标注** | ❌ 未强调 | ❌ 无 | ❌ 无 | ✅ 有规则 |
| **AI 标识** | ❌ 未强调 | ❌ 无 | ❌ 无 | ✅ 有规则 |

**结论**：本项目在知识图谱/掌握度算法/来源标注/AI标识方面**超越多数教育 AI 产品**，但在 Socratic 流程完整性和前端可视化管理方面**显著落后于 Khanmigo**。

### 4.2 通用记忆系统对标

| 维度 | Mem0 | Zep | Letta/MemGPT | LlamaIndex | 本项目 |
|------|------|-----|-------------|-----------|--------|
| **准确率** | 92.5%（LoCoMo） | 71.2%（LongMemEval） | Leaderboard 评测 | 无公开数据 | 未评估 |
| **Token 效率** | <7K/查询 | ~1.6K 达 71.2% | 分页迭代 | 30K 预算+ratio | 全量无预算 |
| **延迟** | 1.4s p95 | 2.58s p95 | 分页迭代 | 取决于向量库 | ~0ms（全量） |
| **冲突检测** | ✅ 向量比对 | ✅ bi-temporal | ❌ LLM 自主 | ❌ 无 | ❌ 无 |
| **自动摘要** | ✅ 压缩 | ✅ 社区聚类 | ✅ 异步压缩 | ✅ FactExtraction | ❌ 无 |
| **图记忆** | ✅ Mem0g | ✅ Graphiti | ❌ 无 | ❌ 无 | ✅ 知识图谱 |
| **开源协议** | Apache 2.0 | 商业+社区版 | Apache 2.0 | MIT | 项目内部 |
| **CRUD API** | ✅ 完整 | ✅ MCP Server | ✅ REST API | ✅ 基础 | ✅ 3个工具 |
| **可视化管理** | ✅ Platform UI | ✅ Graphiti UI | ✅ memory block 编辑器 | ❌ 无 | ❌ 无 |

**结论**：本项目记忆系统在**教育特化能力（知识图谱+掌握度）方面领先通用方案**，但在**记忆管理工程化（冲突检测/自动摘要/token预算/检索）方面落后于 Mem0/Zep 1-2 代**。

### 4.3 提示词工程对标

| 维度 | OpenAI Model Spec | Anthropic Claude 4 | Google LearnLM | Khanmigo | 本项目 |
|------|-------------------|--------------------|----|----------|--------|
| **结构化** | 链式命令+红线 | XML 标签模块化 | PERA 框架+XML | 分段强约束 | 扁平字符串 |
| **长度** | 数千字 | 数千 tokens | 指南级 | ~600-800 tokens | ~200 tokens |
| **风格控制** | Structured Outputs | Styles+prefill | 温度+模板 | 枚举+强约束 | 3×4 枚举 |
| **安全层级** | ✅ 红线优先 | ✅ CAI 宪法 | ❌ 未强调 | ✅ 反滥用 | ❌ 无 |
| **Few-Shot** | ✅ 推荐 | ✅ 黄金法则 | ✅ 1-2 例 | ✅ 有示例 | ❌ 无 |
| **版本管理** | ✅ Model Spec 版本 | ✅ CAI 可审计 | ✅ Prompt Gallery | ❌ 内部 | ❌ 无 |
| **评估** | ✅ OpenAI Evals | ✅ RLAIF | ✅ 迭代策略 | ✅ A/B 测试 | ❌ 无 |

**结论**：本项目提示词系统在**结构化/安全层级/评估/版本管理方面全面落后于行业标杆**，但在**教育合规（来源标注+AI标识）方面有独到设计**。

---

## 五、具体可执行的优化方案

### 方案 1：记忆检索 token 预算 + 优先级截断（P0）

**目标**：防止 system prompt 膨胀，保证记忆注入可控

**改动文件**：
- `backend/agent/memories/core_memory.py`
- `backend/core/message/build_prompt.py`

**步骤**：
1. `CoreMemory.build_context` 加参数 `max_items: int = 20` 和 `max_tokens: int = 2000`
2. 查询时按 `updated_at DESC, access_count DESC` 排序
3. 遍历记忆累加 token 数（用 `len(content) // 3` 粗估），超 budget 时截断
4. 保证每类 `category` 至少保留 1 条（最小覆盖）
5. `build_system_prompt` 总 token 预算 = 风格(200) + 档案(500) + 核心(2000) + 临时(2000) + skills(1000) = 5700

**预计耗时**：约 1 小时

**验证**：构造 50 条核心记忆，验证 `build_context` 返回 token 数 ≤ 2000

---

### 方案 2：System Prompt XML 模块化重构（P0）

**目标**：提升指令遵循率，启用 prompt caching

**改动文件**：`backend/core/message/build_prompt.py`

**步骤**：
1. 将 `SYSTEM_PROMPT` 拆分为模块：
   ```
   <role>你是一个帮助学生学习的 Agent...</role>
   <safety>红线：不代写作业答案 / 不泄露内部记忆 / 不编造...</safety>
   <rules>记忆使用规则 / Skill 使用规则...</rules>
   <style>风格({style}) / 语调({tone}) / 用户补充要求...</style>
   <profile>用户学情档案...</profile>
   <memory>核心记忆 / 临时记忆...</memory>
   <skills>可用 Skills...</skills>
   ```
2. 静态部分（`<role>`/`<safety>`/`<rules>`）固定不变，启用 prompt caching
3. 动态部分（`<style>`/`<profile>`/`<memory>`/`<skills>`）按用户变化
4. 安全优先级显式声明：`安全 > 教育合规 > 用户偏好 > 有用性`

**预计耗时**：约 2 小时

**验证**：对比重构前后，LLM 对指令的遵循率（用 LLM-as-judge 打分）

---

### 方案 3：Socratic 反滥用流程补全（P1）

**目标**：防止学生通过反复"不知道"套出答案

**改动文件**：
- `backend/core/message/build_prompt.py`（`_STYLE_RULES["socratic"]`）
- `backend/agent/skills/profile_personalization.md`（加 Socratic 流程）

**步骤**：
1. `_STYLE_RULES["socratic"]` 展开为多步：
   ```
   socratic 流程：
   1. 先定位学生卡在哪一步（问"你做到哪一步卡住了"）
   2. 用反问引导思考（问"你觉得下一步应该做什么"）
   3. 渐进提示（给方向但不给答案）
   4. 如果连续 3 次学生回答"不知道"，停止给提示，反问"具体哪里不懂"
   5. 用相似例题讲解，不直接讲解原题
   ```
2. `profile_personalization.md` 加 Socratic 专用段落
3. 非 socratic 档也加基础约束："作业类问题优先引导思考，非紧急情况不直接给完整答案"

**预计耗时**：约 1.5 小时

**验证**：模拟学生连续 3 次回答"不知道"，验证 Agent 是否切换策略

---

### 方案 4：核心记忆冲突检测 + 过期机制（P1）

**目标**：避免记忆矛盾导致幻觉，自动清理过期记忆

**改动文件**：`backend/agent/memories/core_memory.py`

**步骤**：
1. `core_memories` 表加字段：`expires_at TEXT`、`access_count INTEGER DEFAULT 0`、`last_accessed_at TEXT`
2. `set` 方法：同 `memory_key` 旧值存在且内容差异 > 50% 时，旧值写入 `memory_history` 表（版本历史）
3. `build_context` 查询时排除 `expires_at < now` 的记忆
4. `build_context` 每次读取时 `access_count += 1`，更新 `last_accessed_at`
5. 加 `cleanup_expired(user_name)` 方法，删除过期记忆

**预计耗时**：约 2 小时

**验证**：写入冲突记忆，验证旧版本保留；设置过期时间，验证自动排除

---

### 方案 5：自动化评估框架接入（P0）

**目标**：量化记忆检索和提示词效果，建立基线

**新增文件**：`backend/tests/test_memory_prompt.py`

**步骤**：
1. 安装 `ragas` + `promptfoo`
2. 构建测试数据集（20 条教育场景用例）：
   - 用户有核心记忆时，Agent 是否引用
   - 风格切换后，输出是否符合风格
   - Socratic 档是否不给答案
   - 记忆冲突时是否用最新值
3. 用 LLM-as-judge 打分（JSON Schema 约束输出）
4. 评估指标：
   - 记忆引用率（应该引用的记忆是否引用）
   - 风格遵循率（输出是否符合选定风格）
   - 答案合规率（Socratic 档不给答案的比例）
5. 接入 CI：改动前后对比，回归报警

**预计耗时**：约 3 小时

**验证**：运行评估，输出基线报告

---

### 方案 6：前端偏好/学情档案对接（P1）

**目标**：让用户能在前端管理偏好和学情档案

**改动文件**：
- `frontend/lib/api/api_client.dart`（加偏好/档案 API 调用）
- `frontend/lib/widgets/profile_sheet.dart`（加偏好/档案设置 UI）
- `frontend/lib/models/models.dart`（加偏好/档案数据模型）

**步骤**：
1. `api_client.dart` 加 `getPreferences()` / `updatePreferences()` / `getProfile()` / `updateProfile()`
2. `models.dart` 加 `UserPreferences` 和 `UserProfile` 数据类
3. `profile_sheet.dart` 加设置区块：
   - 风格选择（concise/detailed/socratic 三选一）
   - 语调选择（friendly/formal/encouraging/strict 四选一）
   - 自定义指令（多行文本框，500 字限制）
   - 学情档案开关 + 专业/年级/教学周
4. 修改后即时调用 `PATCH` 接口更新

**预计耗时**：约 3 小时

**验证**：前端修改偏好，发消息验证 Agent 输出风格变化

---

## 附录：实施路线图

### 阶段一（立即执行，1-2 天）
- [ ] 方案 1：记忆检索 token 预算（1h）
- [ ] 方案 2：System Prompt XML 模块化（2h）
- [ ] 方案 5：评估框架接入（3h）

### 阶段二（近期执行，3-5 天）
- [ ] 方案 3：Socratic 反滥用流程（1.5h）
- [ ] 方案 4：核心记忆冲突检测+过期（2h）
- [ ] 方案 6：前端偏好/档案对接（3h）

### 阶段三（后续优化，1-2 周）
- [ ] 风格控制参数化升级
- [ ] 掌握度动态 KT 注入
- [ ] VARK 学习风格适配
- [ ] 提示词版本管理+A/B 测试

---

## 附录：行业标杆关键数据速查

### 记忆系统基准

| 系统 | 准确率 | Token/查询 | 延迟 p95 |
|------|--------|-----------|---------|
| Mem0 | 92.5%（LoCoMo） | <7K | 1.4s |
| Zep | 71.2%（LongMemEval） | ~1.6K | 2.58s |
| OpenAI Memory | 52.9%（LoCoMo） | 无上限 | 0.9s |
| LangMem | 58.1%（LoCoMo） | — | 60s |
| ChatGPT Dreaming V3 | 82.8%（2026） | — | — |

### 提示词工程基准

| 指标 | 行业基线 | 本项目 |
|------|---------|--------|
| System Prompt 长度 | 600-2000 tokens | ~200 tokens |
| Structured Outputs 合规率 | 100%（JSON Schema strict） | N/A（枚举） |
| Few-Shot 示例数 | 1-2 例 | 0 |
| 评估覆盖率 | 5+ 指标 | 0% |
| 个性化效果 | 满意度+10%（TutorLLM） | 未评估 |

### 教育领域基准

| 指标 | 行业数据 | 来源 |
|------|---------|------|
| VARK 个性化提升 | 均分 70→75（+5） | IEEE Access 2024 |
| KT+RAG 效果 | 满意度+10%，测验+5% | TutorLLM RecSys 2024 |
| SynthesizeMe persona | LLM-as-judge +4.4% | Stanford 2025 |
| Khanmigo Socratic | 拒绝给答案一致性高 | Khan Academy |
| ChatGPT Edu 保留期 | 180 天 | OpenAI 官方 |
