# ESA 后端重构实施总方案

> 状态：已确认架构的实施基线
>
> 日期：2026-08-14
>
> 范围：Core Router、Workspace Agent Runtime、Skill/Tool 分域、教学与科研上下文、Research Workflow、Agent Action、CoreMemory，以及现有 API 的渐进迁移
>
> 本文规定实施顺序、模块归属、依赖关系、兼容策略和完成门槛。具体 CoreMemory 契约以 [CORE_MEMORY_DESIGN.md](CORE_MEMORY_DESIGN.md) 为准。

## 1. 目标

在不破坏现有 `/api`、Flutter、同步对话和 SSE 流式行为的前提下，将当前分散在 Web Router、`Agent`、Prompt、全局 Skill/Tool Registry 和业务 Store 中的 Workspace 逻辑收敛为以下主链路：

```text
FastAPI Web Router
→ Core Router
→ WorkspaceRoute
→ Workspace Agent Runtime
→ AgentRunSpec
→ Shared Agent
→ Model / Scoped Tool Executor
```

重构完成后应满足：

1. `backend/core/web/routers/` 只承担 HTTP、SSE、输入输出和消息持久化适配。
2. `backend/core/router/` 只承担可信身份、Workspace、资源绑定和 Agent Profile 路由。
3. `backend/agent/workspaces/` 根据 Route 装配当前 Workspace 的上下文、Prompt、Skill、Tool 和运行策略。
4. `backend/agent/agent.py` 只保留模型生命周期、协议处理、模型/Tool 循环、流式事件和结果序列化。
5. Learning、Teaching、Research 共用一套 Agent 执行循环，但具有不同的 Profile、上下文、Skill、Tool、Memory Policy 和 Action Policy。
6. 模型不能通过 Prompt、Skill 或 Tool 参数扩大服务端已经确定的身份、Workspace 和资源权限。

## 2. 固定边界

### 2.1 不修改内部实现的模块

以下模块视为内部库，只允许通过 Adapter 调用，不进入本次内部重构：

```text
backend/agent/DocIR/
backend/agent/rag/
backend/agent/mm/
backend/core/services/vllm_service.py
backend/core/stores/ 现有 SQLite 连接与基础设施语义
```

允许新增业务表、版本迁移、Store 和 Service，但不得借本次重构改写 DocIR、RAG、MM、vLLM 或 SQLite 基础设施内部算法和行为。

### 2.2 兼容性约束

- 保持现有 API 路径、状态码和 Flutter 主流程可用。
- 同步和流式对话必须使用同一个 Workspace Runtime。
- 用户消息、Tool 消息和 Assistant 消息的可见性语义保持兼容。
- 迁移期可以增加兼容 Adapter，但不能长期并存两套授权逻辑。
- 任何新表先通过版本迁移建立，再由新 Store 使用。
- 每个阶段都必须可独立合并、验证和回退；不得以一次性大改完成全链路。

### 2.3 权限不变量

```text
最终能力
= WorkspaceRoute 允许范围
∩ WorkspaceRuntimeProfile 声明范围
∩ 身份和资源授权
∩ Conversation Mode
∩ Memory / Action Policy
```

任何下游模块只能收窄权限，不能扩大权限。

以下值只来自服务端可信上下文，不能接受模型参数：

```text
user_id
username
workspace_type
conversation_id
project_id
class_id
assignment_id
attachment authorization
Store / Service 实例
```

## 3. 最终模块所有权

```text
backend/core/
├── router/
│   ├── models.py
│   ├── identity.py
│   ├── context.py
│   ├── workspace_registry.py
│   ├── workspace_profiles.py
│   ├── basic_router.py
│   └── errors.py
├── message/
│   ├── models.py
│   ├── renderer.py
│   └── prompts/
│       ├── learning.py
│       ├── teaching.py
│       └── research.py
├── workflows/
│   └── research/
│       ├── models.py
│       ├── facade.py
│       ├── frontier.py
│       ├── writing.py
│       ├── data_analysis.py
│       └── experiments.py
├── services/
│   ├── agent_action_service.py
│   └── research_project_profile_service.py
├── stores/
│   ├── agent_action_store.py
│   ├── research_project_profile_store.py
│   └── core_memory_store.py
└── web/routers/
    ├── chat.py
    ├── agent_actions.py
    └── memories.py

backend/agent/
├── agent.py
├── workspaces/
│   ├── models.py
│   ├── runtime.py
│   ├── profile_registry.py
│   ├── context_composer.py
│   ├── capability_runtime.py
│   ├── run_spec_builder.py
│   ├── learning_adapter.py
│   ├── legacy_adapter.py
│   └── profiles/
│       ├── learning.py
│       ├── teaching.py
│       └── research.py
├── memories/
│   ├── core_memory_models.py
│   ├── core_memory_service.py
│   ├── core_memory_policy.py
│   ├── core_memory_retrieval.py
│   └── profile_projection.py
├── skills/
│   ├── common/
│   ├── learning/
│   ├── teaching/
│   └── research/
└── tools/
    ├── context.py
    ├── common/
    ├── learning/
    ├── teaching/
    └── research/
```

目录根部保留 Catalog、Registry、契约校验和运行基础设施。Workspace 子目录只放该 Scope 的能力定义，不复制基础设施。

## 4. 核心数据契约

### 4.1 WorkspaceRoute

归属 `backend/core/router/models.py`，为不可变可信路由结果：

```text
workspace_type
agent_profile_id
skill_scopes
tool_scopes
prompt_key
profile_policy
memory_policy_id
resource_scope
action_policy
```

### 4.2 AgentTurnInput

归属 `backend/agent/workspaces/models.py`，包含当前轮已经授权的数据：

```text
route
identity
conversation_id
current_message
history
conversation_summary
conversation_mode
user_preferences
group_context
workspace_profile_context
authorized_attachments
request_metadata
```

它不包含 FastAPI `Request`、裸 Store 或万能上下文字典。

### 4.3 AgentRunSpec

Workspace Runtime 的最终不可变输出：

```text
messages
tool_schemas
tool_executor
execution_context
loop_policy
capability_fingerprint
run_metadata
```

Shared Agent 只消费该对象，不重新选择 Workspace、Profile、Skill Scope 或 Tool Scope。

### 4.4 ToolExecutionContext

归属 `backend/agent/tools/context.py`：

```text
user_id
conversation_id
workspace_route
authorized_resources
conversation_mode
runtime_dependencies
request_id
```

Tool Handler 从该对象获得可信身份和应用依赖，Tool 模块 import 时不得创建 Store 或连接数据库。

## 5. 依赖顺序

```text
阶段 0  基线与行为护栏
   ↓
阶段 1  共享契约与应用依赖容器
   ↓
阶段 2  Core Router 与资源路由
   ↓
阶段 3  Skill/Tool 分域与 Scoped Capability
   ↓
阶段 4  Prompt、Profile Registry 与 Context Composer
   ↓
阶段 5  Workspace Runtime、RunSpec 与 Shared Agent 切换
   ↓
阶段 6  Teaching/Research 资源画像与对话绑定
   ↓
阶段 7  Agent Action 与 Research Workflow Tool
   ↓
阶段 8  CoreMemory V2
   ↓
阶段 9  前端迁移、兼容层清理与总体验收
```

阶段 1 至阶段 5 是主干基础设施，必须按顺序实施。阶段 6 的数据模型可以在阶段 4 后并行准备，但在阶段 5 稳定前不得切换 Agent 使用。阶段 7 依赖阶段 3、5、6；阶段 8 依赖阶段 1、3、5。

## 6. 阶段 0：冻结基线与建立行为护栏

### 6.1 目的

在移动职责之前固定当前可观察行为，避免重构过程中用“代码能运行”代替“行为未回归”。

### 6.2 工作项

1. 记录当前后端、Flutter、同步对话和 SSE 测试基线。
2. 为 Learning、Teaching、Research 各增加最小对话特征测试。
3. 固定现有 Tool Schema、Skill 索引、Prompt Section 和流式事件快照。
4. 增加 Workspace 隔离负向测试：跨 Workspace Skill、Tool、项目、班级和附件访问必须失败。
5. 为旧 `Agent.run(...)`、`run_stream(...)` 和 `/me/memories` 建立兼容契约测试。
6. 记录当前 API 响应结构，不在本阶段修改业务实现。

### 6.3 完成门槛

- 当前完整测试基线有可复现命令和结果记录。
- 三个 Workspace 至少各有一个成功路径和一个越权路径测试。
- 同步与 SSE 对相同输入采用一致的消息持久化语义。
- 后续阶段所需的快照不是依赖字典插入顺序的偶然结果。

## 7. 阶段 1：共享契约与应用依赖

### 7.1 目的

先建立新架构的类型边界和依赖注入入口，但不切换生产调用路径。

### 7.2 工作项

新增并测试：

```text
backend/core/router/models.py
backend/core/router/errors.py
backend/agent/workspaces/models.py
backend/agent/tools/context.py
```

定义不可变的：

- `WorkspaceRoute`
- `TrustedIdentity`
- `ResourceScope`
- `AgentTurnInput`
- `WorkspaceRuntimeProfile`
- `ContextSection`
- `ComposedContext`
- `ResolvedCapabilities`
- `LoopPolicy`
- `AgentRunSpec`
- `ToolExecutionContext`

在应用生命周期中增加一个有类型的 Runtime Dependencies 组合对象，先包装现有 `app.state` 中已经创建的 Store/Service。第一阶段不要求一次性重写整个 `webAPI.lifespan()`，但新的 Tool 和 Runtime 不得继续新增任意 `app.state` 属性读取。

### 7.3 兼容策略

- 原 `PromptContext`、`MessageContext` 和 Agent 签名保持不变。
- 新契约先由单元测试和 Legacy Adapter 使用。
- 不在本阶段迁移数据库或移动 Skill/Tool 文件。

### 7.4 完成门槛

- 核心契约不可变，且集合在边界处复制或冻结。
- `ToolExecutionContext` 无法由模型参数覆盖。
- 新模块不依赖 FastAPI。
- 导入新模块不产生磁盘、数据库或模型副作用。

## 8. 阶段 2：Core Router 与资源路由

### 8.1 目的

让当前空置的 `backend/core/router/` 成为身份、Workspace 和资源绑定的唯一领域路由层。

### 8.2 模块

```text
backend/core/router/
├── identity.py
├── context.py
├── workspace_registry.py
├── workspace_profiles.py
└── basic_router.py
```

### 8.3 工作项

1. `identity.py` 只接受认证层产生的 `SessionPrincipal` 和已加载用户，不信任客户端角色字段。
2. `context.py` 表达已经校验的 Conversation、Research Project、Classroom、Assignment 和附件授权。
3. `workspace_registry.py` 固定合法 Workspace 与角色准入关系。
4. `workspace_profiles.py` 将 Workspace 和资源状态映射到 `agent_profile_id`、Scope 和 Policy ID。
5. `basic_router.py` 交叉校验身份、对话 Workspace、资源绑定和 Profile，输出 `WorkspaceRoute`。
6. Web 层先以 shadow mode 调用新 Router，并将结果与旧 `WorkspaceAccessPolicy` 判断对比；不立即删除旧判断。

### 8.4 明确边界

Core Router 不得：

- 使用 FastAPI `Request`；
- 解释自然语言意图；
- 加载 Skill 或执行 Tool；
- 拼接 Prompt；
- 运行 Workflow；
- 读取或写入 CoreMemory。

### 8.5 完成门槛

- 相同身份、Workspace 和资源上下文产生稳定 Route。
- Route/Profile 不一致时失败关闭，不回退 Learning。
- 所有跨用户、跨项目、跨班级和跨 Workspace 组合均有负向测试。
- shadow mode 无合法请求分歧后，Web 层才能将 Route 作为后续 Runtime 的可信输入。

## 9. 阶段 3：Skill/Tool 分域与 Scoped Capability

### 9.1 目的

建立“模型能看到什么”和“模型实际能执行什么”一致的能力视图，并去除 import 阶段的 Store 创建。

### 9.2 Skill 迁移

将现有 Skill 按语义移动到：

```text
backend/agent/skills/common/
backend/agent/skills/learning/
backend/agent/skills/teaching/
backend/agent/skills/research/
```

规则：

- 名称全局唯一。
- 目录 Scope 与声明 Scope 一致。
- `common + 当前 workspace` 构成 Workspace 候选集合。
- Skill index、autoload、PedagogyRouter 和 `load_skill` 使用同一个 `ScopedSkillView`。
- `requires_tools` 是依赖元数据，不是授权声明。

迁移期保留旧导入路径的薄 Re-export，但不保留第二份 Skill 文件。

### 9.3 Tool 迁移

将 Tool 定义按 Scope 迁移到：

```text
backend/agent/tools/common/
backend/agent/tools/learning/
backend/agent/tools/teaching/
backend/agent/tools/research/
```

根目录保留：

- Catalog 与注册契约；
- Schema 校验；
- 参数归一化；
- `ToolExecutionContext`；
- Scoped View 和 Executor 基础设施；
- Tool Schema 导出工具。

Tool 定义与运行依赖分离。现有 `memory_tools.py`、`mastery_tools.py` 和 `learning_tools.py` 中的全局 Store 先通过 Legacy Dependency Adapter 包装，再迁移为应用生命周期创建、每轮上下文注入。

### 9.4 CapabilityRuntime

实现：

```text
CompiledCapabilityView
    可缓存的 Skill 索引、autoload 正文、Tool Schema 和版本

BoundToolExecutor
    每轮绑定 user_id、conversation_id、授权资源和应用依赖
```

基础 Scope：

```text
Learning = common + learning
Teaching = common + teaching
Research = common + research
```

最终视图还要与 Route、Profile、Resource、Conversation Mode 和 Action Policy 求交集。

### 9.5 Fingerprint

```text
CapabilityFingerprint
= profile_fingerprint
+ Skill Catalog version
+ 排序后的 Skill 名称与版本
+ autoload Skill 版本
+ Tool Catalog version
+ 排序后的 Tool 名称与 Schema hash
+ Policy versions
+ 资源能力标记
```

具体用户 ID、项目 ID、班级 ID、附件 ID 和消息内容不进入 Fingerprint。

### 9.6 完成门槛

- 全局 Skill/Tool 名称唯一，启动校验失败时阻止启动。
- 等价能力集合产生字节一致的 Skill index 和 Tool Schema。
- `load_skill` 无法读取当前 View 外的 Skill。
- Executor 无法执行 Schema View 外的 Tool。
- Tool 模块 import 不创建 Store、不连接数据库。
- 旧 Tool Schema 快照除有意分类变化外保持兼容。

## 10. 阶段 4：Prompt、Profile Registry 与 Context Composer

### 10.1 Workspace Profile Registry

使用代码内版本化配置：

```text
learning.default.v1
teaching.default.v1
research.default.v1
```

配置位于：

```text
backend/agent/workspaces/profiles/
```

Profile 只声明 Prompt、Skill/Tool Scope、Context Policy、Profile Policy、Memory Policy、Action Policy 和 Loop Policy，不包含用户数据或 Store 实例。

Registry 精确解析 Core Router 选定的 `agent_profile_id`。不存在或 Workspace 不匹配时拒绝运行，禁止自动回退。

### 10.2 Prompt 模块

将 Prompt 模型和模板收敛到：

```text
backend/core/message/models.py
backend/core/message/renderer.py
backend/core/message/prompts/{learning,teaching,research}.py
```

Renderer 只渲染已经授权的 Section，不读取 Store、不做 Workspace 路由。

Prompt 的物理顺序固定为：

```text
稳定前缀
1. Agent 基础规则
2. Workspace 规则
3. Capability 使用规则
4. Action / Memory Policy 摘要
5. 稳定 autoload Skill
6. 稳定排序的 Skill 索引

半稳定上下文
7. 输出风格与语调
8. 通用用户画像投影
9. Workspace 专属画像
10. 分组指令或 Project Profile
11. 当前资源范围摘要

动态上下文
12. 会话摘要
13. 附件清单
14. Learning Strategy 输出
15. 最近历史
16. 当前用户消息
```

### 10.3 ContextComposer

`context_composer.py` 采用纯组合设计：

- 只接收 `AgentTurnInput` 和 `context_policy`；
- 不读取 Store、不调用模型、不处理 FastAPI；
- 不重新校验资源所有权；
- 使用 `trusted_system`、`restricted_user_config`、`untrusted_data` 三种信任等级；
- 依据 Workspace 白名单选择 Section；
- 超限时执行确定性裁剪，不临时调用 LLM 压缩。

### 10.4 Learning Adapter

保留现有 `PedagogyRouter`，但只通过 `learning_adapter.py` 产生动态教学策略增强：

```text
LearningContext
→ PedagogyRouter
→ ScopedSkillView 校验
→ 可选 strategy preload
→ StrategyAugmentation
```

Teaching 和 Research 不使用 Teaching Intent Classifier；由主模型在服务端限制的能力 View 内选择 Skill 和 Tool。

### 10.5 完成门槛

- Profile 配置启动时完整校验。
- ContextComposer 对相同输入产生稳定 Section。
- Project Profile、分组指令、摘要和附件均按正确信任等级渲染。
- Learning Adapter 无匹配或失败时可降级，不影响 Agent 可用性。
- Prompt 稳定前缀不包含用户 ID、消息、资源 ID 或检索结果。

## 11. 阶段 5：Workspace Runtime 与 Shared Agent 切换

### 11.1 RunSpecBuilder

`run_spec_builder.py` 确定性编译：

```text
WorkspaceRuntimeProfile
+ ComposedContext
+ ResolvedCapabilities
+ ToolExecutionContext
+ StrategyAugmentation
→ AgentRunSpec
```

第一版 Loop Policy：

```text
max_iterations = 3
parallel_tools = false
tool_error_policy = 将结构化错误返回模型
tool_timeout = 按 Tool 类别配置
```

只有未来明确标记为只读且互相独立的 Tool 才允许并行。

### 11.2 Runtime

`runtime.py` 固定流水线：

```text
校验 WorkspaceRoute
→ Registry 解析 Profile
→ Route/Profile 交叉校验
→ 解析 Scoped Capability View
→ 执行可选 Learning Adapter
→ ContextComposer 组合上下文
→ 绑定 ToolExecutionContext
→ RunSpecBuilder 编译
→ 返回 AgentRunSpec
```

Runtime 不处理 HTTP、消息落库、模型生成、Workflow 内部步骤或业务资源所有权查询。

### 11.3 Agent 收口

正式入口变为：

```text
Agent.run(run_spec)
Agent.run_stream(run_spec)
```

Agent 保留：

- vLLM 模型生命周期；
- Qwen 历史协议清理；
- 模型生成与输出解析；
- Tool 循环与流式事件；
- 终止限制和结果序列化。

从 Agent 中移除：

- Workspace 条件分支；
- `tool_schemas_for_workspace()`；
- Profile/Prompt 组装；
- PedagogyRouter 直接调用；
- 全局 `load_skill()`；
- 分散的用户与会话 ContextVar 设置。

### 11.4 Legacy Adapter

`legacy_adapter.py` 将旧 `PromptContext`、`MessageContext` 和旧 Agent 参数转换为 `AgentTurnInput`，然后必须进入同一个新 Runtime。

切换顺序：

1. 非流式和流式入口先共同委托 Legacy Adapter。
2. Learning Workspace 切换并验证现有教学策略和记忆行为。
3. Teaching Workspace 切换并验证课程班隔离。
4. Research Workspace 切换并验证项目隔离和附件能力。
5. Web Router 直接构造 `AgentTurnInput` 后，停止新增旧入口调用。

### 11.5 完成门槛

- 同步和流式使用同一个 Runtime 和 RunSpec Builder。
- Agent 本体不再感知 Workspace 业务。
- 三个 Workspace 的 Skill、Tool、Profile 和资源互相隔离。
- 旧 API 和 Flutter 行为无回归。
- 旧入口调用有指标，可以判断何时删除 Legacy Adapter。

## 12. 阶段 6：Teaching/Research 资源上下文

### 12.1 Teaching 对话绑定

业务关系固定为：

- 一个教师可以拥有多个课程班；
- 一个学生可以加入多个课程班；
- 一条对话最多聚焦一个课程班；
- 可选聚焦一个作业；
- 跨班级分析必须显式传入目标 ID，并逐班校验授权。

新增版本迁移和 Store 支持：

```text
classroom_conversation_bindings
├── conversation_id
├── class_id
├── assignment_id nullable
├── bound_by_user_id
├── created_at
└── updated_at
```

权限差异：

```text
Teaching Workspace
    教师必须拥有课程班，可访问授权的班级级数据

Learning Workspace
    学生必须是 active member，只能访问自己的提交和已发布反馈
```

绑定由 Web/Service 校验后作为可信 `TeachingContext` 交给 Core Router；Agent 不能自行改变绑定。

### 12.2 Research Project Profile

新增：

```text
research_project_profiles
├── project_id
├── user_id
├── agent_instructions Markdown
├── format_version
├── revision
├── created_at
└── updated_at
```

配套模块：

```text
backend/core/stores/research_project_profile_store.py
backend/core/services/research_project_profile_service.py
```

Project Profile 类似项目级 `AGENT.md`，但数据库是权威来源。它属于 `restricted_user_config`，不能覆盖系统安全规则、Workspace 权限或 Tool Scope。

### 12.3 User/Profile 组合

Runtime 最终可组合：

```text
共用用户画像
+ Workspace 专属用户画像
+ 当前资源画像
+ 分组自定义指令
```

资源画像不能复制进 CoreMemory：班级状态仍以 TeachingStore 为准，项目规则仍以 Research Project Profile 为准。

### 12.4 完成门槛

- 同一用户多个班级/项目不会发生上下文串用。
- Conversation 绑定和资源归属同时通过才允许注入。
- 未绑定项目的 Research 对话不注入任何 Project Profile。
- Teaching 不读取学生私人对话、CoreMemory 或无关 Workspace 画像。

## 13. 阶段 7：Agent Action 与 Research Workflow

### 13.1 Agent Action

先建立通用高影响动作确认机制：

```text
agent_action_requests
```

状态机：

```text
pending
→ approved
→ executing
→ succeeded / failed

pending
→ rejected / expired
```

模块：

```text
backend/core/stores/agent_action_store.py
backend/core/services/agent_action_service.py
backend/core/web/routers/agent_actions.py
```

约束：

- 参数保存为规范化快照；
- 批准时重新检查身份、资源和当前策略；
- 执行必须幂等；
- Teaching 发布、评分、反馈、成员变更等高影响写操作通过该机制或确定性业务流程确认；
- Memory Candidate 不与此表共表。

### 13.2 Research Workflow Facade

现有服务继续作为权威执行实现：

```text
FrontierTrackingService
ResearchWritingService
ResearchDataService
```

新增 Facade 统一 Web 与 Agent Tool 的入口：

```text
backend/core/workflows/research/
```

Facade 只适配和归一现有 Job，不重写内部服务，也不新增统一 Workflow Run 表。现有 Job 表继续是权威来源，Facade 只输出统一 `WorkflowRun` 视图。

### 13.3 强类型 Workflow Tool

每个 Workflow 暴露独立 Tool：

```text
start_frontier_tracking
start_research_writing
start_dataset_analysis
```

禁止使用：

```text
run_workflow(name, payload)
```

Agent 无权调用内部 `claim/complete/fail/requeue` 步骤。Workflow Start 需要确认时先创建 Agent Action；Action 的 `succeeded` 只表示 Job 创建成功，不表示 Workflow 已完成。

### 13.4 完成门槛

- Web 和 Agent Tool 通过同一个 Research Workflow Facade。
- Tool 参数强类型且不接受用户、Workspace 或项目授权字段。
- 重复批准或网络重试不会重复创建 Job。
- Job 最终状态仍从原有 Job Store 查询。
- 高影响动作在未确认前没有业务副作用。

## 14. 阶段 8：CoreMemory V2

完整设计见 [CORE_MEMORY_DESIGN.md](CORE_MEMORY_DESIGN.md)。本阶段只按已确认方案实施，不重新定义产品语义。

### 14.1 固定定义

CoreMemory 是：

> 用户拥有、跨对话长期保存、由 Agent 按需召回的稳定语义记忆。

第一版 Scope：

```text
global
workspace: learning / teaching / research
```

项目、课程班、对话、Mastery、作业、文档、Workflow 状态和附件不进入 CoreMemory。

### 14.2 实施子阶段

#### 8A. 新模型与 Store

通过版本迁移新增：

```text
core_memories
core_memory_candidates
core_memory_versions
core_memory_tombstones
必要的审计记录
```

所有权改用 `user_id`，并支持 Scope、revision、来源、状态、复核和过期字段。

#### 8B. Service、Policy 与 Retrieval

实现：

```text
CoreMemoryService
CoreMemoryPolicy
CoreMemoryRetrieval
ProfileProjection
```

第一版检索为确定性词法检索：默认 `limit=5`、总计不超过 600 tokens、单条正文不超过 160 tokens。

#### 8C. Candidate 与冲突

- 模型推断只创建 Candidate，不静默写入有效记忆。
- Candidate 独立存储，但复用统一的前端待确认体验。
- 更新使用 `expected_revision` 乐观并发。
- 相同内容幂等；补充或冲突内容进入 update/replace Candidate。
- 模型不得自动合并冲突内容。

#### 8D. 生命周期

严格区分：

```text
expires_at    明确失效
review_after  需要复核
suppressed    暂停使用、可恢复
forget        不可恢复地删除正文与派生数据
```

#### 8E. Tool 与 API

三个 Workspace 共用：

```text
backend/agent/tools/common/memory_tools.py
```

由 Workspace Memory Policy 控制内容和 Scope。

旧接口保留一个迁移周期并映射到 global：

```text
GET    /me/memories
PUT    /me/memories
DELETE /me/memories/{memory_key}
```

正式接口使用 `memory_id`，支持 Scope、Candidate、版本、抑制、恢复和遗忘。

### 14.3 缓存

检索缓存键至少包含：

```text
user_id
workspace_type
visible_scopes
normalized_query
category
limit
memory_revision
retrieval_version
```

默认短 TTL 约 60 秒。检索结果进入 Prompt 动态区，不破坏稳定前缀。

### 14.4 完成门槛

- global 与三个 Workspace Scope 严格隔离。
- 模型推断不能直接激活记忆。
- 遗忘清除当前、历史、候选正文、画像投影和索引。
- Profile Projection 失败不回滚主记忆写入。
- 旧 Flutter Memory Sheet 在迁移期继续可用。

## 15. 阶段 9：前端迁移与兼容层清理

### 15.1 前端迁移

1. 保持现有 Learning Memory Sheet 可用。
2. 增加三个 Workspace 共用的记忆管理入口。
3. 按 global 和当前 Workspace 分组展示记忆。
4. 增加 Candidate 接受/编辑/拒绝、抑制、恢复、版本查看和彻底遗忘。
5. Research Project 页面增加 Project Profile 管理入口。
6. Teaching/Research 对话创建或切换资源时，明确显示当前课程班、作业或项目绑定。
7. Agent Action 使用统一待确认交互，但与 Memory Candidate 保持不同业务文案和状态。

### 15.2 删除顺序

只有满足调用量归零和回归通过后，才能按顺序删除：

1. `tool_schemas_for_workspace()` 与 `_LEARNING_ONLY_TOOLS`。
2. 全局 `load_skill()` 运行入口。
3. Tool 模块中的 Store 单例和分散 ContextVar。
4. 旧 `Agent.run(input, user_name, prompt_ctx...)` 签名。
5. `PromptContext` 跨层使用。
6. `legacy_adapter.py`。
7. 旧 `/me/memories` API。
8. Skill/Tool 旧导入路径 Re-export。

不得为了“目录整洁”提前删除兼容层。每项删除都必须有调用量证据和针对性测试。

### 15.3 完成门槛

- Flutter 全部切换到正式 API 和资源绑定模型。
- 生产/演示环境旧入口调用量归零。
- 删除兼容层后完整后端、Flutter 和 Workspace 隔离测试通过。
- 文档、API 索引和部署说明反映最终架构。

## 16. 数据库迁移顺序

建议按以下顺序增加版本迁移：

```text
1. classroom_conversation_bindings
2. research_project_profiles
3. agent_action_requests
4. core_memories
5. core_memory_candidates
6. core_memory_versions
7. core_memory_tombstones 与审计支持
```

每次迁移要求：

- 从空库执行成功；
- 从当前受支持版本升级成功；
- 外键、唯一约束、Check 和索引可验证；
- 迁移失败不留下部分 Schema；
- 数据回填有数量、所有权和孤儿记录校验；
- 不在 Store import 或 Tool import 时隐式建表。

旧 CoreMemory 迁移到 `global` Scope。旧 `project` category 不自动转换成 Research Project Profile，因为旧记录没有可靠项目归属。

## 17. API 兼容矩阵

| 能力 | 迁移期 | 最终状态 |
|---|---|---|
| 对话同步 API | 路径和响应保持不变，内部转入 Runtime | 保留 |
| 对话 SSE API | 事件保持不变，内部转入 Runtime | 保留 |
| Workspace 列表 | 继续使用现有接口 | 保留，数据来自统一 Registry |
| `/me/memories` | global 兼容层 | 调用量归零后废弃 |
| `/me/core-memories` | 新增正式 API | 保留 |
| `/me/memory-candidates` | 新增 | 保留 |
| `/me/agent-actions` | 新增 | 保留 |
| Research 现有 Job API | 通过 Facade 适配，路径兼容 | 保留 |
| Agent Workflow Tool | 新增强类型入口 | 保留 |

## 18. 测试策略

### 18.1 单元测试

- WorkspaceRoute 组合与错误。
- Profile Registry 唯一性和启动校验。
- Scope 求交集与 Capability Fingerprint 稳定性。
- Scoped Skill 展示/加载一致性。
- Tool Schema/Executor 一致性。
- Context Section 信任等级、顺序和预算裁剪。
- Learning Adapter 推荐、预加载与降级。
- CoreMemory Policy、冲突、版本、删除和检索。
- Agent Action 状态机和幂等性。

### 18.2 集成测试

- Web → Core Router → Runtime → AgentRunSpec。
- 同步与 SSE 共用相同 Runtime。
- ToolExecutionContext 注入可信身份与资源。
- Teaching 班级/作业绑定。
- Research Project Profile 隔离。
- Workflow Tool → Action → Facade → Existing Job Store。
- 旧 CoreMemory API → 新 Service 兼容层。

### 18.3 安全负向测试

- 模型伪造 user/workspace/project/class/attachment 参数。
- Learning 加载 Teaching/Research Skill 或 Tool。
- Teaching 访问学生私人记忆或未发布反馈。
- Research 项目之间串用 Profile 和 Artifact。
- `load_skill` 路径穿越或读取 Scope 外 Skill。
- Tool Schema 可见但 Executor 不可用，或反向不一致。
- Candidate、Action 和 revision 重放。

### 18.4 回归门禁

每阶段至少执行：

```text
python -m pytest backend/tests -q
python -m ruff check backend email_service
python -m mypy backend/core backend/agent
flutter analyze
flutter test
```

DocIR、MM 和 RAG 的现有适配边界发生变化时，再运行它们各自的测试；不得修改内部测试来掩盖 Adapter 回归。

## 19. 可观测性与缓存验收

### 19.1 必要标识

每次 Agent Run 记录：

```text
request_id
conversation_id
workspace_type
agent_profile_id
profile_fingerprint
capability_fingerprint
prompt_version
tool names
action request ids
run outcome
latency
```

日志不得记录完整敏感 Prompt、CoreMemory 正文、学生答案或凭据。

### 19.2 关键指标

- Runtime prepare 延迟 P50/P95。
- Capability 编译缓存命中率。
- 等价请求稳定前缀 hash 一致率。
- Tool 拒绝、越权和 Schema 不匹配次数。
- Agent Action 接受、拒绝、过期和失败率。
- Workflow Job 创建幂等冲突次数。
- CoreMemory 检索命中率、空结果率、token 数和用户纠正率。
- Legacy Adapter 和旧 API 调用量。

### 19.3 Prefix Cache 原则

只通过稳定 Prompt 顺序、稳定 Skill 索引、稳定 Tool Schema 和版本 Fingerprint 提高缓存命中率。是否在 vLLM 侧显式启用 Prefix Cache 作为独立部署配置验证，不修改 `vllm_service.py` 内部实现。

## 20. 发布与回退策略

### 20.1 功能开关

迁移期间建议提供服务端开关：

```text
workspace_router_shadow_enabled
workspace_runtime_enabled
workspace_runtime_learning_enabled
workspace_runtime_teaching_enabled
workspace_runtime_research_enabled
core_memory_v2_enabled
research_workflow_tools_enabled
```

开关只选择新旧 Adapter，不得形成两套不同授权结果。新路径关闭时回退到原有完整路径；一旦某 Workspace 完成切换，后续权限修复只进入新路径。

### 20.2 每阶段回退

- 代码回退不自动回滚已经成功的前向数据库迁移。
- 新表在旧版本中无人使用即可保留。
- 新写入启用前必须确认旧代码不会误读新字段或新状态。
- 双写仅用于短期验证且必须有单一权威来源；禁止长期双写 CoreMemory、Action 或 Workflow Job。
- 回退不得恢复已被用户执行“遗忘”的 CoreMemory 正文。

## 21. 明确否决的方案

| 方案 | 否决原因 |
|---|---|
| 在 `Agent` 内继续增加 Workspace `if/else` | 权限、Prompt 和能力装配继续耦合。 |
| 每个 Workspace 复制 Agent 主循环 | 产生协议、流式和 Tool 行为漂移。 |
| Core Router 解释自然语言意图 | 身份/资源路由与任务选择职责混淆。 |
| 模型传入身份或资源标识 | 无法建立可信授权边界。 |
| Skill index 与 `load_skill` 使用不同 Scope | 模型可见能力和实际加载能力不一致。 |
| Tool Schema 与 Executor 使用不同 Registry | 产生可见但不可执行或隐藏但可调用的漏洞。 |
| Profile 缺失时回退 Learning | 掩盖配置错误并可能错误授权。 |
| Workspace Profile 存数据库动态编辑 | 第一版引入配置漂移、审计和缓存复杂度。 |
| Teaching Intent Classifier 决定 Tool | 主模型已经能在受限能力内选择；分类器不应成为权限层。 |
| 单一 `run_workflow(name, payload)` Tool | 参数松散、权限和审计不清晰。 |
| 新建统一 Workflow Run 权威表 | 与现有 Job Store 双重所有权。 |
| Candidate 与 Agent Action 共表 | 长期事实确认和高影响动作审批语义不同。 |
| CoreMemory 全量常驻 Prompt | token、隐私和缓存成本过高。 |
| 第一版 CoreMemory 使用向量库/模型重排 | 先用可解释的词法检索验证真实需求。 |
| 第一版默认并行 Tool | 写操作、依赖和确认动作容易竞态。 |
| 一次性删除所有兼容层 | 会破坏 Flutter 和现有调用方。 |

## 22. 最终验收标准

全部阶段完成的判定标准：

1. `backend/core/router/` 成为身份、Workspace 和资源路由的唯一领域入口。
2. 三个 Workspace 使用同一个 Shared Agent 循环和不同 Runtime Profile。
3. Agent 正式入口只接受 `AgentRunSpec`。
4. Skill index、autoload、PedagogyRouter 和 `load_skill` 使用同一 Scoped View。
5. Tool Schema 与 Executor 使用同一 Scoped View，并由 `ToolExecutionContext` 注入可信依赖。
6. Learning 保留教学策略增强；Teaching/Research 由模型在受限能力内自主选择。
7. Teaching 对话绑定课程班/作业，Research 对话绑定项目且加载 Project Profile。
8. Research Workflow 通过强类型 Tool、Agent Action 和现有 Job Store 执行。
9. CoreMemory V2 满足 Scope、Candidate、版本、遗忘、检索和用户控制契约。
10. 现有 `/api`、Flutter、同步和 SSE 行为完成回归。
11. Legacy Adapter、旧 ContextVar、全局 Tool Store 和旧 Workspace 分支均已删除。
12. DocIR、RAG、MM、SQLite 基础设施和 vLLM 内部实现未被改写。

## 23. 实施批次建议

为控制评审规模，建议按以下批次提交，而不是按一个巨大 PR 实施：

```text
PR 1  行为护栏与共享契约
PR 2  Core Router shadow mode
PR 3  Skill Catalog 分域与 ScopedSkillView
PR 4  Tool Catalog、ToolExecutionContext 与依赖注入
PR 5  Prompt/Profile/ContextComposer
PR 6  Workspace Runtime、RunSpec 和 Learning 切换
PR 7  Teaching/Research Runtime 切换与资源绑定
PR 8  Agent Action 与 Research Workflow Facade/Tools
PR 9  CoreMemory 新表、Store、Service 与兼容 API
PR 10 CoreMemory Candidate/版本/前端管理
PR 11 兼容层删除、文档和总体验收
```

每个 PR 必须保持主分支可运行。跨 PR 的临时 Adapter 应在引入时标注删除目标 PR，防止迁移层永久化。
