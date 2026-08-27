# Metadata / Context Projection 生产接入报告

## 1. Production Flow Before

改造前的真实生产链路如下：

```text
HTTP user message
  -> chat._prepare_message / _preflight_with_active_compression
  -> WorkspaceRuntime.prepare
  -> ExecutableAgentRun / BoundToolExecutor
  -> Agent._run_loop 或 Agent.run_stream
  -> LLM 选择 retrieve_knowledge
  -> BoundToolExecutor.execute
  -> unified_retrieval.retrieve_selected_knowledge
  -> ToolExecutionResult(model_content, display_content, audit_metadata)
  -> Agent._tool_result_channels
  -> serialize_tool_result(model_content)
  -> role=tool message
  -> LLM
```

关键生产节点：

| 文件 | 类 / 函数 | 数据与调用方向 |
|---|---|---|
| `backend/core/web/routers/chat.py` | `_prepare_message`, `_preflight_with_active_compression`, `_runtime_dependencies` | HTTP 请求、可信身份和会话历史进入 Agent Runtime。 |
| `backend/agent/workspaces/runtime.py` | `WorkspaceRuntime.prepare` | `AgentTurnInput` 编译为唯一的 `ExecutableAgentRun`。 |
| `backend/agent/tools/rag_tool.py` | `retrieve_knowledge` 注册 | LLM Tool 参数仍只有 `query`, `top_k`, `similarity_threshold`；`query` 是 LLM 生成的检索 query。 |
| `backend/agent/workspaces/capability_runtime.py` | `BoundToolExecutor.execute` | 将服务端绑定的用户、知识库范围与 Tool 参数传给统一检索。 |
| `backend/agent/rag/unified_retrieval.py` | `retrieve_selected_knowledge` | 正常检索、融合、排序并产生完整三通道结果。 |
| `backend/core/utils/models.py` | `ToolExecutionResult` | frozen dataclass，分别保存 `model_content`, `display_content`, `audit_metadata`。 |
| `backend/agent/agent.py` | `_tool_result_channels`, `serialize_tool_result`, `_run_loop`, `run_stream` | 只把 `model_content` stringify 成真正发给 LLM 的 `role=tool.content`；可见 Tool message 使用 `display_content`，同时携带私有 model/audit 字段供持久化。 |
| `backend/core/web/routers/chat.py` | `chat_store.append_messages`, HTTP response filtering | 完整私有 Tool 字段写入 store；HTTP 响应继续去除 `model_content`, `audit_metadata`, `request_id`, `run_id`。 |

原始当前用户消息和会话历史在 `AgentTurnInput` 中仍然可见，而检索工具收到的是后续由 LLM 生成的 query。该差异决定 Router 必须放在 `WorkspaceRuntime.prepare`，不能依赖 Tool query 猜原始意图。

## 2. Production Flow After

接入后的路径是：

```text
AgentTurnInput(current user message + bounded recent user context)
  -> WorkspaceRuntime._retrieval_projection_context
  -> ContextRouter.route
  -> immutable RouteDecision
  -> ToolExecutionContext.retrieval_projection_context
  -> 正常 Agent Loop 和正常 retrieve_knowledge
  -> 完整 ToolExecutionResult
  -> BoundToolExecutor retrieve_knowledge branch
  -> CanonicalMetadataAdapter
  -> MetadataProjector
  -> ContextSerializer(compact_json.v1)
  -> 新 ToolExecutionResult(projected model_content,
                             original display_content,
                             original provenance + projection audit)
  -> Agent 原有序列化
  -> compact role=tool.content
  -> LLM
```

Router 在任何检索调用之前每轮执行一次。Projector 只在统一检索已经完成后执行。没有新增 LLM generation、Tool call、Tool schema 或 Agent Loop 分支。

## 3. Files Changed

| 文件 | 修改原因 / 新职责 |
|---|---|
| `.env.example` | 文档化独立模型上下文契约；默认 `off`，通过显式 `rule` 灰度启用。 |
| `backend/core/utils/config.py` | 通过现有配置体系校验 `off | rule`，在训练/评测迁移完成前安全默认 `off`，非法值启动时失败。 |
| `deploy/rag/a800-kb-v1.env` | 显式关闭尚未完成目标模型训练/评测准入的投影。 |
| `backend/agent/rag/context_routing.py` | 新增 Profile、Router 输入/输出、可替换 Protocol、窄规则 Bootstrap Router。 |
| `backend/agent/rag/context_projection.py` | 新增 canonical adapter、确定性 projector、serializer、中间件、token metrics、预算保护和 fail-open helpers。 |
| `backend/agent/rag/contracts/retrieve_knowledge_model_context_v1.schema.json` | 定义独立的模型可见 `retrieve_knowledge.model_context.v1` 及四种 Profile 的精确结构。 |
| `backend/agent/tools/context.py` | 在 frozen runtime dependencies 中注入 Router/mode，在 frozen per-turn execution context 中显式承载 projection context。 |
| `backend/agent/workspaces/runtime.py` | 从原始用户请求和受限历史预路由，校验 Router 返回并构造单轮不可变上下文。 |
| `backend/agent/workspaces/capability_runtime.py` | 在 `retrieve_knowledge` 完整返回之后投影，捕获优化层异常并回退旧视图。 |
| `backend/core/web/routers/chat.py` | 将官方配置和可选 `app.state.retrieval_context_router` 注入现有 runtime dependency seam。 |
| `backend/agent/rag/README.md` | 记录生产数据流、开关与 fail-open 运维语义。 |
| `backend/agent/rag/tests/test_context_routing.py` | Router、否定和审计字段单测。 |
| `backend/agent/rag/tests/test_context_projection.py` | 四种 Profile、正式 Schema/golden fixture、源版本门禁、serializer、缺失字段、三通道、预算与 fallback 单测。 |
| `backend/agent/rag/tests/fixtures/*.json` | 固定 `unified.v1 -> model_context.v1` 的四种 Profile 输出。 |
| `backend/agent/rag/tests/test_context_projection_runtime.py` | 全路径、ToolMessage、flag、异常、无效返回、并发和多次 Tool call 测试。 |
| `backend/agent/rag/tests/test_official_config.py` | 冻结官方生产默认 mode。 |
| `backend/agent/rag/try/production_benchmark.py` | 使用生产组件和生产 token estimator 重跑接入后 benchmark。 |
| `backend/agent/rag/try/results/production_integration_benchmark.json` | 可复现的明细、质量检查、Router bad case 和 Tool schema hash。 |

没有修改 Dense/BM25/Fusion/RRF/Reranker、Chunking、DocIR、Qdrant、Top-K 或 query rewrite 实现。

## 4. Router Design

最终接口位于 `context_routing.py`：

```python
@dataclass(frozen=True, slots=True)
class RetrievalRouteInput:
    current_user_message: str
    recent_user_messages: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class RouteDecision:
    profile: MetadataProfile
    router_type: str
    router_version: str
    reason_code: str
    matched_rule: str | None = None
    confidence: float | None = None

class ContextRouter(Protocol):
    def route(self, route_input: RetrievalRouteInput) -> RouteDecision: ...
```

生产 Bootstrap 使用 `RuleBasedContextRouter`。它仅做高精度显式命中：默认 `MINIMAL`，来源请求为 `SOURCE`，页/章/定位请求为 `LOCATION`，明确 debug metadata 请求为 `FULL`。局部否定检测使“不用给我出处”“无需页码”等回到 `MINIMAL`。`FULL` 的规则优先且刻意收窄，普通“分数”只有同时存在检索/debug 上下文才会触发。

Router 输入使用未改写的当前用户消息，以及最多四条最近 user 消息；每条历史消息截断到 1000 字符。历史只为未来 Router 提供有限上下文，不进入 Tool schema。当前 v1 规则只分类当前消息，避免扩大自然语言规则库。

Router 返回值会在 Runtime 边界验证为真实 `RouteDecision`。异常或无效对象均不会让 RAG 失败，而是生成带 fallback reason 的 projection context。

## 5. Projection Design

`CanonicalMetadataAdapter` 从当前统一检索的 model/display 两个 view 建立窄 canonical item，不依赖 DocIR 内部字段树。`MetadataProjector` 是纯确定性字段选择器；不理解 query、不重新排序、不调用模型。

真实模型视图如下：

| Profile | 发给模型的字段 |
|---|---|
| `MINIMAL` | 每条 `ref`, `content`, `citation_mode`。保留 `citation_mode` 是现有逐字引用安全策略所必需。 |
| `SOURCE` | MINIMAL + `source`，存在时加 `author`；不加入 page、URL、ID、score。 |
| `LOCATION` | SOURCE + `section`, `page`；已有 page 时不发送体积较大的 bbox/locator，只有缺 page 时才发送已有 `location`。 |
| `FULL` | 每条正文 + 合并且有界于当前 model/display item 的 debug `metadata`，并保留 result-level retrieval metadata；这是高成本调试路径。 |

短引用 `C1/C2/...` 按原 ranking 顺序稳定产生。完整 `short ref -> source_ref/chunk_id/scope/document/location/citation policy` 映射只保存在 `audit_metadata.metadata_projection.ref_registry`，不会进入 LLM 上下文。

生产 Serializer 选择结构化 `compact_json.v1`，让现有 Agent 的统一 JSON serializer 无需变化，同时保留 citation/location 的明确语义。模型 payload 明确携带 `contract_version=retrieve_knowledge.model_context.v1` 和 `source_contract_version=retrieve_knowledge.unified.v1`。Benchmark 也实现了 Compact Text 比较：MINIMAL/SOURCE/LOCATION 分别为 118/151/196 tokens，低于带正式版本 envelope 的 Compact JSON 214/259/322；本轮未选择文本，因为它会改变泛型 Agent Tool observation 语义。FULL 的 Compact Text 数字不具可比性，因为该实验文本格式不表达 debug metadata。

## 6. RouteDecision Propagation

传递路径完全显式：

```text
WorkspaceRuntime.prepare
  -> RetrievalProjectionContext(frozen)
  -> ToolExecutionContext.retrieval_projection_context (frozen)
  -> ExecutableAgentRun.tool_executor
  -> BoundToolExecutor.execute
```

没有 global mutable state、contextvar 或 conversation-global profile。每次 `prepare` 创建新的不可变 projection context；两个并发 turn 的 executor 各持有自己的对象。并发测试同时执行 A=`MINIMAL` 与 B=`LOCATION`，两边 profile、query 和 audit registry 均保持隔离。

同一 Agent turn 内的多次 `retrieve_knowledge` 调用共享该 turn 的原始用户意图策略，但各自从本次完整 result 重建短引用和 audit registry。它不会泄漏到下一轮。若未来要求“同一 turn 内不同 retrieval call 使用不同意图”，需要引入受信的 per-call intent seam；当前已批准的 per-turn architecture 不阻塞该扩展。

## 7. Backward Compatibility

| 项目 | 结果 |
|---|---|
| LLM Tool 数量 | 不变；没有 Projection Tool。 |
| `retrieve_knowledge` Tool schema | 不变；属性仍为 `query`, `top_k`, `similarity_threshold`，required 仍为 `query`。Benchmark schema SHA-256 为 `0916e8712b611cafce29d04863e926463e1c523c15a64332b802518ced5726ef`。 |
| Retrieval / ranking | 不变；投影发生在 `retrieve_selected_knowledge` 返回完整结果之后。 |
| Agent Loop / generation 次数 | 不变；仍是原有 append-only loop 与统一 Tool result serialization。 |
| `display_content` | ON 时保留原对象；OFF 时返回原始 `ToolExecutionResult` 对象。 |
| `audit_metadata` provenance | 原有顶层键和值/对象引用保留；ON 时仅新增 `metadata_projection` observability。OFF 时完全不增加。 |
| HTTP contract | 公共响应的字段过滤和 display payload 不变；私有 model/audit 字段仍按原路径持久化。 |
| 配置关闭语义 | `RAG_METADATA_PROJECTION_MODE=off` 跳过 Router 和 middleware，返回完全相同的旧三通道对象。 |
| 契约身份 | 完整源结果保持 `retrieve_knowledge.unified.v1`；显式开启时模型视图为独立的 `retrieve_knowledge.model_context.v1`。默认 `off`，避免训练/评测迁移前静默改变模型 observation。 |

因此“只有 model_content 被投影”指业务数据通道；audit 只按需求增加非模型可见的 telemetry，不删除或改写原 provenance。

## 8. Failure / Fallback

所有优化层故障都以旧 `model_content` 为安全基线：

| 情况 | 行为 |
|---|---|
| Router 抛异常 | Runtime 记录 `router_error:<type>`，检索照常执行，middleware 返回旧 model/display。 |
| Router 返回错误类型 | 当作 `router_error:TypeError`，与异常相同地 fail open。 |
| RouteDecision 缺失 | 返回旧 model/display，audit 记录显式 fallback reason。 |
| Adapter / Projector / Serializer 抛异常 | `BoundToolExecutor` 捕获整个 projection middleware，返回旧 model/display 并记录 `projection_error:<type>`。 |
| 源契约版本缺失或未知 | 不尝试适配或重新标记，直接返回旧 model/display；audit 记录缺失或不支持的源版本。 |
| Token counter 抛异常 | observability 自动使用生产 `estimate_tokens` fallback，不影响 retrieval。 |
| Projected candidate 超过原结果 `budget.limit` | 拒绝 candidate，返回旧 model/display，audit 记录 `projected_model_budget_exceeded`、candidate tokens 与 limit。无有效 limit 时保护上限为 2048。 |
| source/author/section/page/location 缺失 | 保留真实已有字段，用 `None` 表示缺失；不编造 metadata，并在 audit `missing_metadata` 列出缺项。 |
| Projection audit 本身无法安全附加 | 保守返回原始 result。 |

Retrieval 自身的原有错误语义不被 middleware 吞掉；只对 Projection optimization 失败做 fail-open。

## 9. Tests

本轮新增覆盖包括：

- Router 的四 Profile、显式否定、已知坏例“它来自哪本书？”、审计字段。
- Projector 的渐进字段集合、三通道保留、短引用、顺序、中文/引号/换行、缺失 metadata、关闭模式。
- 硬 token budget 超限时旧视图 identity 保留及 rejected candidate audit。
- Router exception、无效 Router return、Projector/Serializer exception 和 RouteDecision missing fallback。
- 从用户消息到 Router、真实 BoundToolExecutor、ToolMessage、可见 display 的端到端路径。
- Tool schema 冻结、feature flag exact rollback、同轮多次 Tool call、并发 turn 隔离。

实际执行结果：

| 命令 / 分组 | 结果 |
|---|---|
| 新 routing/projection/runtime + existing agent API/config + personal-only unified test | **41 passed in 2.48s** |
| Agent prompt / chat concurrency / workspace conformance / context isolation | **52 passed**（分文件执行均通过） |
| Agent/chat/context/prompt regression（此前本轮执行） | **31 passed** |
| Workspace/context broader regression（此前本轮执行） | **51 passed** |
| Workspace runtime architecture（排除独立 hang case） | **19 passed, 1 deselected** |
| Agent three-channel tests | **2 passed** |
| `git diff --check` | passed |
| `compileall`（全部本轮 Python production/benchmark 文件） | passed |

当前环境有几个与本 patch 无代码交集的既有 stall：`test_personal_recovery.py`、`test_load_skill_executes_only_through_the_bound_scoped_view`，以及当前重跑时 `test_selected_scopes_are_fused_by_rank_and_keep_separate_projections` 在 `asyncio.run` 关闭 default executor 阶段超时。最后一个测试的断言路径此前本轮曾通过，当前 faulthandler 显示等待发生在 Python `Runner.close`；同文件不使用 `asyncio.to_thread` 的 personal-only 测试通过。本次没有修改 `unified_retrieval.py` 或这些测试，故没有为掩盖环境 stall 改动生产逻辑。

本次独立契约复核还单独运行了 `test_workspace_api.py`；其第一项在注册请求的 Starlette `TestClient`/AnyIO portal 中等待并于 30 秒超时，尚未进入 Metadata Projection 路径。其余 Agent prompt、chat concurrency、workspace conformance 和 context isolation 文件分开运行均通过。

## 10. Token Benchmark

Benchmark 直接调用 production `MetadataProjectionMiddleware`、生产 `estimate_tokens` 和真实 `retrieve_knowledge` Tool schema。工作区没有已部署 Agent 模型的 tokenizer 文件，因此不能声称是目标模型精确 token；上线时 middleware 会优先使用注入 provider 的 `count_tokens`。

Fixture baseline model view 为 497 tokens；end-to-end proxy 计算“第一次模型输入 + Tool 返回后的第二次模型输入”，公共 system/history/无关 Tools 因所有 case 相同而省略。

| Case | Profile | Before | After | Saving | Saving % | E2E before | E2E after | E2E saving % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Projection OFF | OFF | 497 | 497 | 0 | 0.00% | 1125 | 1125 | 0.00% |
| 普通问答 | MINIMAL | 497 | 214 | 283 | 56.94% | 1125 | 748 | 33.51% |
| 要求来源 | SOURCE | 497 | 259 | 238 | 47.89% | 1125 | 805 | 28.44% |
| 要求位置 | LOCATION | 497 | 322 | 175 | 35.21% | 1125 | 886 | 21.24% |
| 明确 debug | FULL | 497 | 949 | -452 | -90.95% | 1125 | 1701 | -51.20% |

完整可复现结果在 `results/production_integration_benchmark.json`。硬预算保护没有改变该 fixture：最大 FULL candidate 为 949，小于 2048。版本 envelope 有少量固定成本，但三种正常 Profile 仍保持显著节省。

## 11. Quality Findings

小型 production-component regression 的四项质量检查全部通过：

- MINIMAL 保留三条排名证据的全部正文和引用安全模式，可回答普通区别问题。
- SOURCE 中三条 source 均为“软件测试基础.pdf”，且没有误加 page/location。
- LOCATION 保留正确页码 12/13/14 与 section；已有页码时 bbox 仅留服务端。
- FULL 能看到 `retrieval_score=0.873` 等 debug metadata。

Router 数据集的 6 个代表 query 中 5 个正确：普通、来源、页码、否定、debug 均正确。既有坏例“它来自哪本书？”已由显式“哪本书”规则修复。

刻意保留的能力边界是：

```text
这个观点最早出现在哪里？
predicted = MINIMAL
expected  = LOCATION
```

“在哪里”可能表示文档位置、来源或抽象语境；继续添加宽规则会增加普通问答误触发。该 case 已写入 benchmark `bad_cases`，适合作为后续标注/微调样本。跨轮“你刚才这个说法是哪本书里的？”还需要稳定的 conversation-scoped provenance/tool-call registry 才能避免重新检索；这不阻塞当前单轮投影，也没有在本轮扩大实现范围。

## 12. Fine-tuning Readiness

当前结构已经可以把 Rule Router 替换为 Fine-tuned Router，而无需修改 Projector、Serializer、`retrieve_knowledge`、`BoundToolExecutor` 或 Agent Loop。Web runtime 已提供 `app.state.retrieval_context_router` dependency seam；未来实现只需遵守：

```python
ContextRouter.route(RetrievalRouteInput) -> RouteDecision
```

并返回受支持的 `MetadataProfile`。现有 audit 已包含 query、有限 recent user context、predicted/corrected profile slots、router type/version/rule/confidence，可离线生成 bad-case 数据。训练/部署前的操作项是准备标注数据、校准低置信度 provenance 策略，并决定是否继续用可信硬规则保护高成本 FULL；这些不是生产组件替换的代码阻塞项。

`model_context.v1` 的正式 Schema 与 deterministic golden fixtures 已生成，但仓库当前没有带真实 provenance 的成功检索训练 observation；现有 dataset 生成器明确禁止伪造这类来源。因此本次没有把测试 fixture 冒充训练数据，也没有宣称完成目标模型迁移。生产默认保持 `off`，待真实语料导出、训练数据重生成和目标模型评测通过后，才在部署中显式切换为 `rule`。

最终验收矩阵：

- [x] Metadata Projection 已真正接入生产路径。
- [x] 不新增 LLM Tool。
- [x] Router 在检索前执行。
- [x] Projector 在检索后执行。
- [x] 只有 `model_content` 被投影。
- [x] `display_content` 行为不变。
- [x] 原 `audit_metadata` provenance 行为不变；仅新增非模型可见 observability。
- [x] `retrieve_knowledge` Tool Schema 不变。
- [x] Retrieval ranking 不变。
- [x] Feature Flag 可以关闭整个优化。
- [x] 关闭后回退到旧对象/旧行为。
- [x] Router 接口可被 FineTunedRouter 替换。
- [x] Projection failure 不导致 RAG 整体失败。
- [x] RouteDecision 无 global state，并发隔离测试通过。
- [x] Token benchmark 有生产组件真实执行结果。
- [x] 回归测试已实际执行并记录结果。
- [x] 生产代码不存在无关大范围重构。
