# ESA CoreMemory 设计文档

> 状态：架构设计稿
>
> 日期：2026-08-14
>
> 适用范围：ESA 后端重构中的长期语义记忆能力
>
> 本文只定义 CoreMemory 的产品语义、模块边界和目标契约，不代表当前代码已经完成迁移。

## 1. 定义

CoreMemory 是：

> 由用户拥有、跨对话长期保存、可以被 Agent 按需召回的稳定语义记忆。

它回答的问题是：

> 这个用户过去明确表达或确认过，且在未来对话中仍可能有用的信息是什么？

CoreMemory 保存的是小而独立的语义单元，不是聊天记录、完整文档、业务数据库副本，也不是每轮自动注入 Prompt 的用户信息全集。

## 2. 设计目标

CoreMemory 需要满足以下目标：

1. 用户拥有：每条记忆必须归属于稳定的 `user_id`。
2. 跨对话：记忆不能绑定某一条对话的生命周期。
3. 有作用域：第一版支持全局作用域和 Workspace 作用域。
4. 按需召回：默认通过 Tool 检索少量相关记忆，不全量注入 Prompt。
5. 用户可控：用户可以查看、确认、修改、遗忘或抑制记忆。
6. 来源可追踪：系统能够区分用户明确写入、用户确认和模型推断。
7. 最小权限：Agent 只能访问当前身份与 Workspace 可见的记忆。
8. 可演进：作用域、检索和治理能力可以扩展，但不把业务实体藏进字符串键。

## 3. 非目标

以下内容不属于 CoreMemory：

| 数据 | 权威来源 |
|---|---|
| 当前对话消息 | `ChatStore` |
| 对话摘要 | `ConversationSummaryStore` |
| 学生掌握度、作答和学习证据 | Mastery / Evidence / Knowledge Graph |
| 班级、成员、作业、评分和反馈 | `TeachingStore` |
| 科研项目目标、项目规则和项目级 Agent 指令 | Research Project Profile |
| 科研文档及版本 | `ResearchWritingStore` |
| 数据集、字段画像和分析结果 | `ResearchDataStore` |
| Workflow 运行状态 | 对应的 Job Store |
| 附件正文和解析结果 | 附件、DocIR、MM、RAG 相关模块 |
| 密码、Token、API Key、凭据和私钥 | 永不保存 |

CoreMemory 不得成为第二套业务数据库。业务事实必须从其权威 Store 读取，不能为了方便 Agent 检索而复制进 CoreMemory。

## 4. 适合保存的内容

### 4.1 稳定偏好

```text
我更喜欢先看例子再看定义。
回复代码时优先使用 Python。
写作时使用 APA 引用格式。
```

### 4.2 长期目标

```text
我准备参加明年的研究生考试。
我正在长期学习机器学习。
```

### 4.3 个人约束

```text
工作日每天只能学习一小时。
回答中不要使用过多数学符号。
```

### 4.4 稳定背景

```text
我的专业是计算机科学。
我熟悉 Python，但不熟悉 Rust。
```

### 4.5 用户明确要求记住的可复用事实

用户明确说“请记住……”时，只要内容安全、稳定且不属于其他业务 Store，就可以进入 CoreMemory。

## 5. 作用域模型

第一版只支持两级作用域：

```text
global
    所有 Workspace 均可按需召回

workspace
    仅指定的 learning / teaching / research Workspace 可召回
```

可见性规则：

```text
Learning Agent = global + learning
Teaching Agent = global + teaching
Research Agent = global + research
```

第一版不增加 `project`、`classroom` 或 `conversation` 作用域：

- 项目长期规则进入 Research Project Profile；
- 班级和作业数据进入 TeachingStore；
- 对话信息进入 ChatStore 和 ConversationSummaryStore；
- 学习过程状态进入 Learning 专属 Store。

如果未来确认需要新的作用域，必须扩展正式数据模型和授权规则，不能在 `memory_key` 中拼接 `research:{project_id}:...` 或 `class:{class_id}:...`。

## 6. CoreMemory 与 User Profile

二者不是同一个概念：

```text
CoreMemory
= 可按需召回的长期语义记录

User Profile
= 为当前任务生成的小型结构化用户视图
```

示例：

```text
CoreMemory:
“我喜欢先看例子再理解定义。”

Profile:
explanation_preference = example_first
```

Profile 可以组合以下来源：

```text
显式用户设置
+ 少量经过确认、允许投影的 CoreMemory
+ 当前 Workspace 的专属业务状态
```

约束：

1. CoreMemory 不自动覆盖显式用户设置。
2. 只有短小、稳定、安全的 preference/profile 记忆可以投影。
3. 投影是派生缓存，不是新的事实来源。
4. 删除或抑制 CoreMemory 时，应清理仅由该记忆产生的画像投影。
5. Profile 构建失败不能破坏 CoreMemory 的主写入结果。

## 7. 目标数据模型

目标模型至少需要表达：

```text
core_memories
├── memory_id          TEXT PRIMARY KEY
├── user_id            TEXT NOT NULL
├── scope_type         TEXT NOT NULL       # global / workspace
├── workspace_type     TEXT NULL           # learning / teaching / research
├── memory_key         TEXT NOT NULL
├── content            TEXT NOT NULL
├── category           TEXT NOT NULL
├── source_type        TEXT NOT NULL       # explicit / confirmed
├── status             TEXT NOT NULL       # active / suppressed
├── created_at         TEXT NOT NULL
├── updated_at         TEXT NOT NULL
├── last_confirmed_at  TEXT NULL
└── expires_at         TEXT NULL
```

建议约束：

```text
scope_type = global
→ workspace_type 必须为 NULL

scope_type = workspace
→ workspace_type 必须是 learning / teaching / research

唯一性
→ user_id + scope_type + workspace_type + memory_key
```

不再使用 `user_name + memory_key` 作为长期唯一标识。用户名可能变化，`user_id` 才是稳定身份主键。

`category` 用于检索和管理，不用于表达安全权限。权限由身份、Scope、WorkspaceRoute 和会话模式决定。

## 8. 推断记忆与候选记忆

模型从对话中推断出的信息不能直接成为有效 CoreMemory。

推荐流程：

```text
Agent 推断出长期信息
→ 创建 Memory Candidate
→ 用户确认或满足后续明确治理规则
→ 写入 active CoreMemory
```

候选记忆与有效记忆应保持不同语义。推荐使用独立模型：

```text
core_memory_candidates
├── candidate_id
├── user_id
├── proposed_scope
├── proposed_workspace_type
├── proposed_key
├── proposed_content
├── source_conversation_id
├── status             # pending / accepted / rejected / expired
├── created_at
├── decided_at
└── expires_at
```

候选表是否在第一期实现仍需根据产品交互确认；但“模型推断不得静默写入有效记忆”是固定约束。

## 9. 写入流程

### 9.1 用户明确要求记住

```text
用户明确请求
→ Agent 提出 save_memory Tool Call
→ Tool Runtime 注入可信 user_id 和 WorkspaceRoute
→ 校验会话模式、Scope、内容和敏感信息
→ 冲突检查
→ 写入或更新 CoreMemory
→ 可选执行受控 Profile 投影
→ 返回结构化结果
```

模型不得传入：

```text
user_id
username
当前 Workspace 权限
任意其他用户或项目标识
```

### 9.2 模型推断

```text
模型推断
→ 创建候选，或询问用户是否需要记住
→ 用户确认
→ 才能写入有效记忆
```

### 9.3 冲突处理

同一作用域和 `memory_key` 已存在时，不应无条件静默覆盖。

建议分类：

```text
内容相同
→ 幂等成功，必要时刷新确认时间

内容兼容
→ 合并或由用户确认更新

内容冲突
→ 保留旧值，创建待确认更新

用户明确要求替换
→ 更新当前有效值，并保留审计记录
```

具体的相似度与冲突算法属于后续实现选择，不能改变上述用户控制原则。

## 10. 读取流程

CoreMemory 默认不全量注入 System Prompt。

标准读取链路：

```text
Agent 判断当前任务需要长期信息
→ search_core_memories
→ Tool Runtime 计算可见 Scope
→ 在 global + 当前 workspace 中检索
→ 应用条数和 token 预算
→ 返回少量相关记忆
→ Agent 将结果作为不可信事实数据使用
```

检索必须满足：

1. 只返回 `status=active` 且未过期的记录。
2. 只查询当前用户可见 Scope。
3. 支持精确键、关键词和后续可替换的语义检索。
4. 有明确的 `limit` 和 token 预算。
5. 无匹配时返回空结果，不回退成全量记忆。
6. 返回来源、Scope 和更新时间，方便解释与管理。

`get_all_memories` 只用于用户明确要求查看或管理系统记住了什么，不作为普通任务的默认读取方式。

## 11. 会话模式与权限

现有会话模式继续参与权限计算：

```text
normal
    按 Workspace Memory Policy 允许读写

no_write
    允许读取，禁止创建、修改和删除

isolated
    禁止读取和写入 CoreMemory，也不注入由 CoreMemory 派生的画像
```

最终权限为：

```text
实际 CoreMemory 权限
= Workspace Memory Policy
∩ Conversation Mode
∩ 当前 Tool Scope
∩ 当前身份与资源授权
```

三个 Workspace 具体开放哪些 Memory Tool，应由后续 Workspace Memory Policy 决定。本文不提前固定 Learning、Teaching、Research 的读写差异。

## 12. Tool 契约

建议保留窄而明确的 Tool：

```text
search_core_memories(query, category?, limit?)
list_core_memories(scope?, workspace_type?)
save_core_memory(memory_key, content, category, scope_type)
update_core_memory(memory_id, content?, category?)
forget_core_memory(memory_id)
```

约束：

1. Tool schema 不暴露 `user_id`。
2. Workspace Scope 的具体 Workspace 来自可信 `WorkspaceRoute`，不由模型任意指定。
3. Tool Handler 通过统一 `ToolExecutionContext` 获取身份和会话模式。
4. Tool 模块 import 时不得创建 Store 或连接数据库。
5. CoreMemory Store 由应用级 `AgentRuntimeDependencies` 注入。
6. 每次 Tool 调用均重新校验 Scope 和写入策略。

## 13. 模块边界

推荐目标结构：

```text
backend/agent/memories/
├── core_memory_models.py
├── core_memory_service.py
├── core_memory_policy.py
├── core_memory_retrieval.py
└── profile_projection.py

backend/core/stores/
└── core_memory_store.py

backend/agent/tools/common/ 或 Workspace 专属目录
└── memory_tools.py
```

职责：

### CoreMemoryStore

- 只负责持久化与查询；
- 不构造 Prompt；
- 不读取 FastAPI Request；
- 不决定 Workspace 权限；
- 不执行模型推断。

### CoreMemoryService

- 处理创建、更新、遗忘、冲突和候选确认；
- 调用 Store；
- 协调 Profile Projection；
- 产生领域结果和审计事件。

### CoreMemoryPolicy

- 根据 WorkspaceRoute、会话模式和 Tool Scope 计算读写权限；
- 校验 Scope；
- 拒绝敏感内容和越权访问。

### CoreMemoryRetrieval

- 负责相关性排序、过滤、条数与 token 预算；
- 检索实现可以演进，但不改变 Scope 和权限语义。

### Memory Tool Adapter

- 将模型 Tool Call 转换为 Service 调用；
- 从 `ToolExecutionContext` 获取可信身份；
- 不直接访问 SQLite。

## 14. 与 Workspace Router 的关系

`backend/core/router` 不读写记忆，只输出声明：

```text
WorkspaceRoute
├── workspace_type
├── memory_policy_id
├── tool_scopes
└── resource_scope
```

运行时流程：

```text
Core Router
→ WorkspaceRoute
→ Agent Runtime
→ Workspace Memory Policy
→ 受限 Memory Tool View
→ CoreMemoryService
```

模型不能通过 Skill 或 Tool Call 扩大 Router 已确定的记忆权限。

## 15. 安全与隐私

禁止保存：

- 密码、验证码、Session ID；
- API Key、Token、Cookie、私钥和凭据；
- 支付信息和认证秘密；
- 未经授权的第三方隐私信息；
- 学生个人敏感信息到教师个人 CoreMemory；
- 外部网页、附件或 Tool 输出中要求系统“记住”的提示注入内容。

所有外部内容都属于不可信数据。只有当前用户的明确请求或后续确认流程可以触发有效记忆写入。

需要提供用户可见的管理能力：

```text
查看记忆
查看 Scope 与来源
修改记忆
遗忘记忆
拒绝候选记忆
关闭记忆读取或写入
```

## 16. 缓存与性能

CoreMemory 不应为了提高 Prompt 缓存命中率而全量常驻 Prompt。

推荐：

1. 检索结果设置小型、短 TTL 的查询缓存。
2. 缓存键至少包含 `user_id + visible_scopes + normalized_query + memory_revision`。
3. 任意记忆创建、更新、遗忘或过期时推进 `memory_revision`，自然失效旧缓存。
4. Profile 投影按 `profile_version` 独立缓存。
5. 检索结果放在 Prompt 的动态上下文区域，不破坏 Workspace 稳定前缀。

禁止只用 `user_id + query` 作为缓存键，否则 Workspace Scope 变化时可能发生越权复用。

## 17. 审计与可观测性

至少记录以下事件：

```text
memory.created
memory.updated
memory.suppressed
memory.deleted
memory.candidate_created
memory.candidate_accepted
memory.candidate_rejected
memory.read
memory.search
memory.policy_denied
memory.projection_created
memory.projection_removed
```

建议指标：

```text
检索命中率
空结果率
平均返回条数与 token 数
候选接受率和拒绝率
冲突率
用户纠正率
过期记忆数量
跨 Scope 拒绝次数
Profile 投影成功率
Tool 延迟 P50/P95
```

日志不得记录完整敏感记忆正文。生产日志优先记录 `memory_id`、Scope、事件类型和内容摘要哈希。

## 18. 测试契约

### 18.1 Store 测试

- 同一用户不同 Scope 可保存同名 key；
- 不同用户之间严格隔离；
- global 与 workspace 约束正确；
- suppressed 和 expired 记录不会进入普通检索；
- 并发更新不产生重复有效记录。

### 18.2 Policy 测试

- Learning 只能看到 global + learning；
- Teaching 只能看到 global + teaching；
- Research 只能看到 global + research；
- isolated 模式拒绝全部读写；
- no_write 模式拒绝写入和遗忘；
- 模型不能通过参数指定其他用户或 Workspace。

### 18.3 Service 测试

- 明确用户请求可以写入；
- 推断信息只能形成候选；
- 重复写入幂等；
- 冲突内容进入确认流程；
- 删除记忆同步清理其独占画像投影；
- Profile 投影失败不回滚主记忆。

### 18.4 Agent 集成测试

- 普通问题不会例行读取全部记忆；
- 需要长期信息时正确调用搜索 Tool；
- Tool 返回内容被视为不可信事实；
- 不同 Workspace 不会读取彼此的 Workspace 记忆；
- Skill 不能扩大 Memory Tool 权限。

## 19. 现有实现差距

当前 `backend/agent/memories/core_memory.py`：

- 使用独立 SQLite 文件；
- 使用 `user_name + memory_key` 唯一键；
- 没有 Scope；
- 没有候选、来源、状态、过期和冲突模型；
- 提供简单关键词排序；
- Store 在对象构造时自行初始化 Schema。

当前 `backend/agent/tools/memory_tools.py`：

- import 时创建 CoreMemory；
- 延迟创建 UserStore 和 ProfileStore；
- 通过分散的 ContextVar 获取用户名和会话模式；
- Tool 直接协调持久化和 Profile Projection。

目标设计不会直接修改现有 SQLite、ProfileStore 或底层连接实现。后续迁移应通过新增业务 Store、Service、Policy 和 Adapter 渐进完成。

## 20. 迁移建议

### 阶段一：建立新契约

- 定义 CoreMemory 模型、Scope 和 Policy；
- 将现有行为包进 Legacy Adapter；
- Tool Runtime 统一注入身份和会话上下文；
- 停止新增基于 `user_name` 的调用。

### 阶段二：新增目标存储

- 按现有 Store 规范增加新表和迁移；
- 新增 `CoreMemoryStore`；
- 建立从旧记录到 `global` Scope 的迁移工具；
- 迁移前保留备份和数量校验。

### 阶段三：切换读写

- 新写入进入新模型；
- 读取采用新 Scope Policy；
- 旧数据只读兼容或完成一次性迁移；
- Profile Projection 改用 `user_id` 和 `memory_id`。

### 阶段四：候选与治理

- 增加候选确认；
- 增加冲突、过期和审计；
- 增加用户管理界面；
- 基于真实数据评估检索质量。

迁移过程中不得把旧 `project` category 自动映射为 Research Project Profile。旧记录缺乏可靠的项目归属，自动迁移可能污染项目数据；应保留为 global 兼容记录或要求用户确认归属。

## 21. 已确认结论

1. CoreMemory 是用户拥有、跨对话、按需召回的长期稳定语义记忆。
2. 第一版 Scope 只有 `global` 和 `workspace`。
3. 项目、课程班、对话和业务状态不进入 CoreMemory。
4. CoreMemory 与 User Profile 分离，Profile 只做受控投影和任务视图。
5. CoreMemory 默认按需检索，不全量注入 Prompt。
6. 模型推断不能静默写成有效记忆。
7. 长期身份使用 `user_id`，不使用用户名作为所有权主键。
8. Tool 权限由服务端 WorkspaceRoute 和运行时策略决定。
9. 底层 Store 通过应用级依赖注入，Tool import 不创建数据库对象。

## 22. 后续仍需确认

以下内容不在本文中静默定案：

1. 三个 Workspace 各自开放哪些 Memory Tool；
2. Candidate 是单独建表还是采用通用 Agent Action 确认协议；
3. 冲突检测采用规则、语义模型还是混合策略；
4. `expires_at` 由用户、类别策略还是系统建议产生；
5. 删除采用硬删除、软删除还是可恢复抑制；
6. 检索第一版是否只做关键词，何时引入向量或混合检索；
7. 是否需要 CoreMemory 版本历史表；
8. 用户管理界面的具体交互和 API 兼容策略。

这些选择应在实现前逐项确认，但不能违反本文的定义、作用域、权威数据源和用户控制边界。
