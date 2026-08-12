# ESA 代码架构审查

> 审查日期：2026-08-13  
> 审查范围：当前仓库中的 FastAPI 后端、Agent/记忆模块、SQLite Store、Flutter 前端及相关测试。  
> 本文只记录架构问题与改进方向，不包含业务代码修改。

## 1. 结论摘要

当前代码并非整体不可维护，`DocIR`、RAG 等部分已经有较清晰的目录划分和一定测试覆盖。主要问题集中在少数不断吸收职责的热点 Module：

1. 对话 Turn 的编排和持久化散落在 HTTP/SSE 路径中，失败与重试语义不完整。
2. SQLite Schema 同时由版本迁移和各 Store 初始化代码维护，存在双重所有权。
3. FastAPI 启动函数承担整个应用的依赖组装和生命周期管理，并通过无类型的 `app.state` 向外暴露。
4. Agent 工具在 import 时创建固定路径的全局 Store，形成隐式依赖和磁盘副作用。
5. Flutter 的 `AppState` 与 `ApiClient` 横跨几乎全部业务，已经成为 God Module。
6. 部分 Flutter 页面同时包含数据流程、交互状态、布局、绘制和算法，文件及测试表面持续扩大。

建议处理顺序：

1. 对话 Turn Module
2. Schema 单一所有权
3. 应用运行时与生命周期 Module
4. Agent 工具依赖注入
5. Flutter 状态和在线/离线 Adapter 拆分
6. 页面内部按用户流程深化

## 2. 审查用语

本文统一使用以下架构术语：

- **Module**：具有 Interface 和 Implementation 的函数、类、包或完整功能切片。
- **Interface**：调用方正确使用 Module 时必须知道的全部内容，包括类型、约束、顺序、错误模式和配置。
- **Implementation**：Module 内部实现。
- **Depth**：一个较小 Interface 能隐藏并提供多少行为。深 Module 提供高 Leverage；浅 Module 的 Interface 几乎与 Implementation 一样复杂。
- **Seam**：可以在不原地修改调用方的前提下替换行为的位置。
- **Adapter**：在 Seam 上满足某个 Interface 的具体实现。
- **Leverage**：调用方从 Module 深度中获得的能力复用。
- **Locality**：变更、故障、知识和验证集中在一个位置的程度。

## 3. 高优先级问题

### 3.1 对话 Turn 缺少统一的业务状态机

**涉及文件**

- `backend/core/web/routers/chat.py:227`
- `backend/core/web/routers/chat.py:520`
- `backend/core/web/routers/chat.py:555`
- `frontend/lib/state/app_state.dart:933`

**观察到的事实**

- `_prepare_message()` 同时执行归属校验、用户加载、历史压缩读取、用户消息写入、记忆设置读取、知识点解析、用户画像构建和分组参数合并。
- 用户消息在模型调用前通过 `get_compressed_model_history_and_append()` 持久化。
- 非流式路径和 SSE 路径分别调用 Agent、筛选生成消息并写入数据库。
- SSE 路径还单独维护租约释放、事件编码和错误映射。
- 前端在流中断后通过重新拉取全部消息判断是否恢复成功；失败后用户再次发送可能形成语义重复。

**风险**

- 模型失败时只保留用户消息是否属于预期行为，目前没有显式 Turn 状态表达。
- 客户端无法区分“服务端仍在生成”“生成失败”“已经生成但 SSE 丢失”和“请求从未被接受”。
- 缺少客户端提供的幂等键时，网络重试可能重复写入用户消息或重复执行工具副作用。
- 同步与流式路径的 Implementation 会随功能增长发生行为漂移。

这些是由当前结构推导出的高概率风险；本次审查没有复现数据重复的生产故障。

**建议方案**

建立一个深的“对话 Turn” Module，以单一 Interface 接受：

- `conversation_id`
- 当前用户
- 用户输入和附件引用
- 客户端生成的 `turn_id` 或幂等键
- 输出模式（同步结果或事件流）

该 Module 内部统一负责：

- 归属与输入校验
- Turn 租约
- 用户消息及 Turn 状态持久化
- 上下文和提示词构建
- Agent 执行
- 工具/助手消息持久化
- 完成、失败、取消状态
- 重试和断流后的结果查询

HTTP JSON 和 SSE 应成为同一 Seam 上的两个 Adapter。不要在模型推理期间长期持有 SQLite 写事务；应使用短事务更新持久化状态机，例如 `accepted -> running -> completed/failed`。

**收益**

- Turn 语义和故障处理获得 Locality。
- 同步、流式和未来的后台生成共享同一套 Implementation，获得更高 Leverage。
- 可以通过同一 Interface 测试幂等、模型异常、工具异常、客户端断开、Worker 崩溃及租约恢复。

### 3.2 SQLite Schema 存在双重所有权

**涉及文件**

- `backend/core/stores/migrations.py:887`
- `backend/core/stores/user_store.py:22`
- `backend/core/stores/chat_store.py:22`
- `backend/core/stores/schedule_store.py:95`
- `backend/core/stores/teaching_store.py:25`
- `backend/core/web/webAPI.py:115`

**观察到的事实**

- `migrations.py` 维护带版本号的建表、表重建、约束修复和迁移记录。
- `UserStore`、`ChatStore`、`ScheduleStore`、`TeachingStore` 等又在 `_initialize()` 中执行 `CREATE TABLE`、`PRAGMA table_info` 和 `ALTER TABLE`。
- 应用启动时先构造多个 Store，再调用 `run_migrations()`。
- 测试中也存在“先构造 Store，再运行迁移”的模式。

**风险**

- 同一字段、约束和索引的知识分散在多个 Implementation 中。
- 新数据库和历史数据库可能经过不同建库路径，最终 Schema 只是在当前测试样本中碰巧一致。
- Store 初始化提前修改数据库后，正式迁移再记录版本，会模糊某次迁移到底执行了什么。
- 外键、`CHECK`、触发器或表重建逻辑很容易只更新其中一份。

**建议方案**

让版本迁移 Module 成为生产数据库 Schema 的唯一所有者：

1. 应用启动首先运行迁移。
2. 迁移成功后再构造 Store。
3. Store `_initialize()` 不再建表或补列，只验证所需 Schema 版本，或者完全依赖组合阶段的保证。
4. 测试数据库统一通过一个 fixture 执行完整迁移。
5. 增加“从空库升级”和“从每个受支持历史版本升级”的 Schema 快照/约束测试。

迁移期间可暂时保留旧初始化代码作为兼容 Adapter，但必须设置删除节点，避免永久维护两套 Interface。

**收益**

- Schema 变更集中在一个位置，显著提高 Locality。
- Store 只负责业务数据访问，Interface 更窄、更深。
- 数据库升级路径可以独立验证，不再依赖 Store 构造顺序。

## 4. 中高优先级问题

### 4.1 FastAPI 启动函数是无类型的全局依赖容器

**涉及文件**

- `backend/core/web/webAPI.py:109`
- `backend/core/web/routers/chat.py:165`
- `backend/core/web/routers/preferences.py`
- `backend/core/web/routers/schedule.py`
- `backend/core/web/routers/research_capabilities.py`

**观察到的事实**

- `lifespan()` 创建并连接二十多个 Store、领域 Module、后台队列、模型、RAG 和多模态对象。
- 所有对象以动态属性形式写入 `app.state`。
- 多个路由直接读取 `request.app.state.<name>`，调用方必须知道属性名称及初始化顺序。
- 测试需要手工给 `app.state` 或 `SimpleNamespace` 填充一组隐式依赖。
- 压缩任务、RAG、多模态和研究任务在主 `try/finally` 之前启动或创建；若后续启动步骤抛错，已经启动的资源不一定进入清理逻辑。

**风险**

- `app.state` 实际 Interface 很大，但类型系统和构造函数都无法验证它。
- 添加一项依赖会扩散到启动、路由和大量测试 fixture。
- 部分初始化失败时可能遗留后台任务、连接或模型资源。
- 所有功能共享一个启动路径，测试一个小路由也容易被无关的 GPU/RAG 配置牵连。

**建议方案**

建立显式的应用运行时 Module，例如按以下领域组合内部对象：

- 身份与会话
- 对话与记忆
- 课表与学习状态
- 教学
- 科研
- 推理、RAG 与多模态基础设施

顶层 Runtime 只提供少量领域 Interface 和统一的 `start()/close()` 生命周期。FastAPI 的依赖函数作为 Seam，将对应领域 Module 注入路由；路由不再知道整个应用对象图。

生命周期实现应使用 `AsyncExitStack` 或等价的后进先出清理机制，使每个成功创建的资源立即注册清理动作，即使后续启动失败也能回收。

**收益**

- 依赖图和资源所有权获得 Locality。
- 测试只替换真正变化的 Adapter。
- 小型路由测试不需要启动模型、RAG 或无关后台任务。

### 4.2 Agent 工具在 import 阶段创建全局数据库对象

**涉及文件**

- `backend/agent/tools/mastery_tools.py:49`
- `backend/agent/tools/learning_tools.py:18`
- `backend/agent/tools/memory_tools.py:23`
- `backend/agent/memories/paths.py`

**观察到的事实**

- `mastery_tools.py` 在 import 时创建 `kg_store` 和 `mastery_store`。
- `learning_tools.py` 在 import 时创建 `evidence_store` 和 `learning_state_service`。
- `memory_tools.py` 在 import 时创建 `core_memory`，并通过缓存函数再次构造 `UserStore` 和 `ProfileStore`。
- 这些对象使用仓库内固定路径，与 `app.state` 中通过组合创建的 Store 并存。

**风险**

- import 具有磁盘和数据库副作用。
- 测试替换应用依赖时，Agent 工具仍可能访问真实路径。
- 同一进程内存在多套数据库对象及不同生命周期，故障定位困难。
- 工具注册、当前 Turn 上下文和持久化依赖耦合在同一 Module。

**建议方案**

将工具定义/Schema 与工具运行时分开：

1. 工具注册只声明名称、参数和描述，不创建 Store。
2. 应用组合阶段创建一个工具运行时并注入所需 Store。
3. 每个 Agent Turn 通过 `ContextVar` 或显式上下文携带用户、会话模式等短生命周期信息。
4. 测试注入临时数据库 Adapter。

目前确实存在生产数据库与测试数据库两种 Adapter，因此这是一个真实 Seam，不是为未来假设而过度抽象。

**收益**

- import 恢复为无副作用操作。
- 工具 Interface 可以独立做契约测试。
- 数据库路径、生命周期和事务策略集中管理。

## 5. 中优先级问题

### 5.1 Flutter `AppState` 是跨领域 God Module

**涉及文件**

- `frontend/lib/state/app_state.dart:19`
- `frontend/lib/state/app_state.dart:368`
- `frontend/lib/state/app_state.dart:603`
- `frontend/lib/state/app_state.dart:933`
- `frontend/lib/state/app_state.dart:1234`

**观察到的事实**

`AppState` 超过 1200 行，同时拥有：

- 登录、注册、会话恢复和本地凭据
- 课表服务器同步及旧缓存迁移
- 对话、消息、分组和工作空间
- SSE 解码后的打字机队列与断流恢复
- 科研项目
- 用户偏好、画像和主题设置

所有状态共享一个 `ChangeNotifier`，多数操作直接调用 `notifyListeners()`。

**风险**

- 任一领域变更都要求理解一个巨大 Interface。
- 无关页面可能因全局通知而重建。
- 加载、错误和并发状态容易相互覆盖，例如全局 `busy` 无法自然表达多个会话或多个领域并发。
- 测试某个小流程需要构造或继承巨型 `ApiClient`。

**建议方案**

按用户可理解的领域建立深 Module：

- `SessionState`
- `ChatState`
- `ScheduleState`
- `ResearchState`
- `PreferencesState`

顶层应用状态只组合这些 Module，不复制其内部字段。聊天 Module 内部继续隐藏消息缓存、创建去重、打字机队列和恢复逻辑，使页面只依赖一个较小 Interface。

**收益**

- 状态修改和 Widget 重建获得 Locality。
- 每个领域可以独立测试加载、失败、取消和并发。
- 删除某个领域 Module 后，其复杂度会重新出现在调用方，说明该 Module 确实能提供 Depth，而非简单转发。

### 5.2 Flutter `ApiClient` 混合在线协议和完整离线实现

**涉及文件**

- `frontend/lib/api/api_client.dart:38`
- `frontend/lib/api/api_client.dart:789`
- `frontend/lib/api/api_client.dart:1202`
- `frontend/lib/api/api_client.dart:1540`

**观察到的事实**

- `ApiClient` 超过 1500 行，覆盖认证、画像、课表、知识地图、对话、科研和教学端点。
- 大量方法内部包含 `kOfflineMode` 分支。
- 文件尾部保存离线会话、消息、分组、科研项目和模拟 Agent 回复。
- SSE 请求和普通 JSON 请求也由同一个类直接实现。

**风险**

- 每增加一个端点都要同时修改在线与离线分支，容易出现协议漂移。
- 当前测试主要验证基础 URL；巨型 Interface 的大多数错误映射、解析和离线一致性没有直接契约测试。
- 继承 `ApiClient` 制作测试假对象时，测试被迫依赖大量无关公开方法。

**建议方案**

按领域定义窄 Interface，并提供真实存在的 Adapter：

- HTTP Adapter
- Offline Adapter
- 测试 Fake Adapter

认证 Header、JSON 错误映射和 SSE 解码可以作为 HTTP Adapter 内部的共享 Implementation，不要暴露成页面需要理解的额外 Interface。

**收益**

- 在线和离线协议可以跑同一组契约测试。
- 页面状态测试只依赖所属领域 Interface。
- 网络实现的复用仍保留在内部，不需要复制底层 HTTP 代码。

### 5.3 页面 Module 承担过多流程和视觉职责

**涉及文件**

- `frontend/lib/pages/schedule_page.dart`
- `frontend/lib/pages/login_page.dart`
- `frontend/lib/widgets/profile_sheet.dart`
- `frontend/lib/pages/research_project_page.dart`

**观察到的事实**

- `schedule_page.dart` 约 1700 行，包含页面布局、课程冲突判断、课表导入目标选择、编辑表单、设置表单和自定义绘制。
- `login_page.dart` 约 1200 行，包含认证流程、动画/焦点控制和多个自定义 Painter。
- 其他若干页面/Widget 也在 800 至 900 行区间。

文件大本身不是缺陷；问题在于理解一个用户流程需要同时解析数据迁移、网络调用、表单规则和绘制代码。

**建议方案**

优先按完整用户流程形成深 Module，而不是机械地按 Widget 数量拆文件：

- 课表导入流程
- 课程编辑流程
- 时间网格布局与冲突计算
- 登录/注册流程状态
- 登录页纯视觉场景

只有真实变化或需要独立测试的地方才建立 Seam。单纯转发参数的小 Widget 经删除测试后如果只让复杂度消失，就不值得保留。

**收益**

- 表单规则、导入迁移和布局算法可脱离完整 Widget 树测试。
- 视觉调整不会触碰网络和持久化流程。
- 页面恢复为组合入口，内部 Module 提供更高 Leverage。

## 6. 建议实施路线

### 阶段一：先建立行为保护

1. 修复本地开发环境，使后端测试和静态检查可稳定运行。
2. 为对话 Turn 增加以下回归测试：
   - 同一 `turn_id` 重试不重复执行。
   - 模型在首个事件前失败。
   - 模型输出一半后失败。
   - 客户端断开但服务端完成。
   - Worker 在 `running` 状态退出后恢复。
3. 为数据库增加从空库和历史版本升级后的 Schema/外键/索引断言。
4. 为 Flutter 在线与离线 Adapter 建立共享契约测试。

### 阶段二：后端高风险重构

1. 引入对话 Turn 状态和幂等键。
2. 让同步与 SSE Adapter 共享 Turn Module。
3. 调整启动顺序为“运行迁移 -> 构造 Store -> 构造领域 Module -> 启动后台资源”。
4. 将 Store 中的 Schema 修改逻辑逐步删除。
5. 用可验证的 Runtime 取代散落的 `app.state` 属性。

### 阶段三：去除隐式全局依赖

1. 将 Agent 工具注册与运行时对象拆开。
2. 从组合根注入记忆、掌握度、知识图谱和学习证据 Store。
3. 确认所有测试只访问临时数据库，禁止 import 触碰仓库真实数据文件。

### 阶段四：前端按领域深化

1. 先从 `AppState` 提取 `ChatState`，因为它包含最多并发和恢复规则。
2. 再提取 `SessionState` 与 `ScheduleState`。
3. 将 `ApiClient` 拆为领域 Interface，并实现 HTTP/Offline Adapter。
4. 最后按用户流程缩小课表和登录页面；不要同时大改视觉表现。

## 7. 不建议的做法

- 不要仅因为文件行数大就机械拆成大量小文件；这通常会制造浅 Module，降低 Locality。
- 不要在每个 Store 前再增加一层一比一转发类；删除测试表明这种 Module 不提供 Depth。
- 不要为了“可替换”给只有一个实现且没有测试需求的对象都创建 Interface；一个 Adapter 通常只是一个假设 Seam。
- 不要在 LLM 推理全程持有 SQLite 写事务。
- 不要一次同时重构后端 Turn、数据库、前端状态和 UI；应通过纵向行为测试逐步替换。

## 8. 验证状态与限制

本次审查完成了静态结构、调用关系、Schema 所有权和现有测试写法检查，但未能获得完整质量门结果：

- `python -m pytest -q` 在收集前失败。当前 Python 环境自动加载 `jaxtyping`，导入 NumPy 时出现 `ModuleNotFoundError: No module named 'numpy._utils'`。
- 当前 Python 环境未安装 `ruff`，因此未运行 Ruff 检查。
- `.pytest_cache` 中存在若干历史失败节点，但缓存不能证明当前代码仍然失败，本文没有把它们作为代码缺陷依据。
- 仓库当前没有 `CONTEXT.md` 或 `docs/adr/`，因此本文依据 README、接口文档、目录命名和实际调用关系理解领域；后续作出关键架构决策时建议补充领域词汇和 ADR。

以上问题分为“已观察到的结构事实”和“由结构推导的风险”。在实现重构前，应先用回归测试确认希望保留的现有行为。
