# 对话分组 + 分组内自定义指令：完整实现设计文档

> 当前状态（2026-08-09）：后端数据表、迁移、API、对话移动和组级 Prompt 合并均已
> 实现；Flutter 分组管理界面仍待对接。本文保留需求、竞品分析和验收设计，文中标注
> “现状/缺口”的代码快照以 2026-08-06 为准，当前任务状态以 [TODO.md](TODO.md) 为准。
>
> 本文档由 GROUP_FEATURE.md 原需求文档升级而来，最后核对于 2026-08-06。
> 内容：项目全景分析（实测代码核对）、市场调研（4 款竞品优缺点分析）、技术栈实现方案、
> 功能模块划分、核心数据结构、API 接口定义、分阶段开发计划、质量验收标准、技术难点与解决方案。
> TODO.md 中「对话分组 + 分组内自定义指令」一节为本设计文档的待办清单。

---

## 第一部分：项目全景分析

### 1.1 技术栈与总体结构（依据源码实测）

| 层 | 技术 | 位置 |
|---|---|---|
| 后端框架 | Python 3 + FastAPI + SQLite | `backend/`，入口 `backend/core/web/webAPI.py` |
| 模型推理 | vLLM（同步 `generate` / 流式 `generate_stream`） | `backend/core/services/vllm_service.py` |
| 前端 | Flutter（Web / macOS / iOS / Android / Windows / Linux） | `frontend/lib/` |
| 数据存储 | SQLite 单文件 `backend/core/stores/data/user.db` | `backend/core/stores/` |

### 1.2 后端模块清单（含关键调用链）

| 模块 | 关键文件 | 现状（核对结论） |
|---|---|---|
| Agent 主循环 | `backend/agent/agent.py` | `run()` / `run_stream()` 可用；`_prepare_run` 组装消息并注入用户级偏好/学情档案 |
| Prompt 构建 | `backend/core/message/build_prompt.py` | `build_system_prompt` 注入 `preferred_style` / `preferred_tone` / `custom_instruction` / `user_profile_context`；指令追加在风格区块末尾 |
| 聊天存储 | `backend/core/stores/chat_store.py` | `conversations`（5 列，无 `group_id`）+ `messages`（6 列含 `is_visible`）；迁移模式：`PRAGMA table_info` 检查列是否存在后 `ALTER TABLE` |
| 用户存储 | `backend/core/stores/user_store.py` | `users` 表含偏好/指令/学情档案；老库迁移参考实现 |
| 会话/鉴权 | `backend/core/stores/session_store.py`、`backend/core/web/deps.py` | `get_current_session` 依赖注入，返回 `SessionPrincipal` |
| Web 路由 | `backend/core/web/routers/{auth,chat,preferences,learning,memories}.py` | REST 接口已就绪；`chat.py` 在 `send_message` / `stream_message` 中完成归属校验后调 Agent |
| Pydantic 模型 | `backend/core/web/schemas.py` | 请求/响应模型；`RenameRequest` 目前只允许 `title` |
| 应用装配 | `backend/core/web/webAPI.py` | `lifespan` 中初始化 4 个 Store + Agent，注册 5 组 router |
| 工具/记忆/Skill | `backend/agent/tools/`、`memories/`、`skills/` | 12+ 工具、核心记忆/临时记忆、6 个 skill；与本次功能无冲突 |

### 1.3 前端模块清单

| 模块 | 关键文件 | 现状（核对结论） |
|---|---|---|
| 状态管理 | `frontend/lib/state/app_state.dart` | 单一 `AppState extends ChangeNotifier`；持有 `conversations` / `_messages` / `activeId` / 本地 `_pinned`；登录后 `_afterLogin` 并行加载对话与偏好 |
| API 客户端 | `frontend/lib/api/api_client.dart` | 认证+对话+消息+SSE；含离线模式（`kOfflineMode` 假数据） |
| 数据模型 | `frontend/lib/models/models.dart` | `ChatConversation`（id/title/updatedAt/pinned 本地）；无分组字段 |
| 聊天页 | `frontend/lib/pages/chat_page.dart` | 顶栏 + 消息区 + 输入区；`HistoryDrawer` 为抽屉 |
| 历史侧边栏 | `frontend/lib/widgets/history_drawer.dart` | 时间自动分组（置顶/今天/本周/更早）+ 搜索 + 每行星标/重命名/删除 |
| 设置/记忆 | `frontend/lib/widgets/{profile_sheet,learning_dashboard,memory_sheet}.dart` | 已对接后端 |

### 1.4 对话数据流（现状实测）

```
前端发消息 → POST /conversations/{id}/messages(同步) 或 /messages/stream(SSE)
→ chat.py _load_owned 校验归属 → ChatStore.get_model_messages(历史)
→ Agent.run / run_stream(preferred_style, preferred_tone, custom_instruction, user_profile_context, total_weeks)
→ build_system_prompt() 组装 System Prompt（用户级指令在此注入）
→ vLLM 推理（可循环调用工具）→ 新消息写回 messages 表 → 返回/SSE 推送
```

### 1.5 与「对话分组 + 分组内自定义指令」相关的现状与缺口

| 现状 | 缺口 |
|---|---|
| `conversations` 表只有 5 列，无分组字段 | 无法按学科/课程/任务归类对话 |
| 自定义指令仅用户级（`users.custom_instruction` ≤500 字，全对话生效） | 无分组级指令，做不到「不同课不同要求」 |
| 侧边栏仅时间自动分组 + 本地置顶（`pinned` 不落后端） | 无用户自定义分组、无持久化分组 |
| `preferences.py` 已有风格/语调/指令接口与枚举校验 | 分组级风格/语调/指令未设计 |
| `build_system_prompt` 已支持注入用户级指令 | 需扩展分组级指令参数与优先级合并 |
| `chat_store.py` 的迁移模式（PRAGMA + ALTER）成熟 | `conversations` 加列可直接复用该模式 |

---

## 第二部分：市场调研（4 款同类型产品）

> 调研时点：2026-08。调研对象覆盖「分组整理 + 组内指令」两条核心能力线。

### 2.1 ChatGPT Projects（OpenAI）

**实现方式**：侧边栏独立的 Projects 入口，每个 Project 是一个扁平工作区，可上传文件（仅项目内可见）+ 设置 Custom Instructions（项目级指令，约 5,000 字符限制）；对话可通过「更改项目」迁移归属；同一项目内所有对话共享指令与文件。

**优点**
- 指令 + 知识文件 + 对话三合一，语义聚焦
- 对话归属可迁移，不是创建时固化
- 项目级指令对组内所有历史/新对话自动生效，无需重复粘贴背景

**缺点**
- 只支持一级扁平空间，不支持嵌套文件夹树，整理力有限
- 项目数量与免费/付费绑定，指令冲突时与全局指令的优先级说明不透明
- 项目内文件全部计入 token 消耗，文件多了成本高

**可借鉴**：① 分组=扁平工作区而非多级树；② 对话「移动到分组」交互；③ 指令保存即对组内全部对话生效。

### 2.2 Claude Projects（Anthropic）

**实现方式**：侧边栏 Projects 页，每个 Project 由三部分构成——Custom Instructions（项目指令）+ Files 知识库（RAG 自动检索，可将容量扩大 10 倍）+ 对话历史（项目内集中管理）。对话行 3-dot 菜单提供 Star / Rename / Change project / Remove from project / Delete。官方明确「不嵌套、无文件夹」。

**优点**
- 「指令 + 知识 + 对话」三合一模式最成熟，RAG 自动检索降低 token 成本
- 指令本质是「一套可复用行为约定」，切换项目即切换整套行为
- 免费档可用，3-dot 菜单交互范式成熟

**缺点**
- 明确不支持嵌套，多学科/多课程粒度较粗时难组织
- 知识文件随项目全量注入上下文，长指令/大文件有「指令被选择性忽略」的失效风险
- 移动对话在部分版本/客户端行为不一致（不支持直接移动的反馈存在）

**可借鉴**：① 3-dot 菜单完整操作集（星标/重命名/更换项目/删除）；② 分组描述（Description）用于展示卡片而非当指令用；③ 分组概念与现有时间分组共存不冲突。

### 2.3 Gemini Gems（Google）

**实现方式**：Gems 是「预设专属助手」，每个 Gem 有独立名称、描述、指令集和可选知识文件；使用时在对话开始前选择 Gem，Gem 指令优先级高于全局指令（全局指令=默认性格，Gem=分身）。

**优点**
- 指令作用域分层（全局 vs Gem）清晰，越具体越优先
- 内置模板（学习辅导/编程伙伴等）+ 一键复制克隆改指令，创建门槛低
- 免费可用，指令编写支持 PTCF 框架指导

**缺点**
- Gems 是「会话角色」，不是「对话归档容器」——没有把历史对话按 Gem 归组的整理能力
- 对话历史是纯时间流，无搜索、无标签，找旧对话困难
- 指令过长时模型可能选择性忽略（社区反馈）

**可借鉴**：① 「指令=可复用角色」心智，贴合本项目的教学场景（苏格拉底助教/批改模式）；② 指令模板库 + 一键填入；③ 全局级 < 组级 的优先级心智。

### 2.4 豆包 / Kimi / 通义千问（国内主流）

**实现方式**：豆包走「标签 + 智能体设定 + 自定义指令」轻量化路线（设置→自定义指令→新增指令）；Kimi 提供「常用语指令」模板化快速插入；通义千问在输入框右侧提供「指令中心」调用/新建自定义指令。均无真正意义上的对话分组树（部分以标签/收藏整理）。

**优点**
- 自定义指令入口浅、模板多，上手零门槛
- 指令中心集中管理可复用的「常用语」，贴合中文用户习惯

**缺点**
- 对话整理能力弱（无分组树/文件夹），对话列表依然随时间流堆叠
- 指令与对话隔离，无法做到「这个分组专属的指令」
- 多端体验碎片化

**可借鉴**：① 指令编辑器 + 模板 + 字数统计（低门槛）；② 分组语义用中文教育场景词（高数/线代/数据结构），而非项目/工作区等英文产品名词。

### 2.5 设计模式提炼（六条）

1. **分组模型取「一级扁平分组 + 未分组兜底」**：文件夹树整理力强但过度嵌套，Claude 明确不嵌套；教育场景建议一级分组。
2. **指令作用域三级叠加**：用户级（全局默认）→ 分组级（范围内生效）→ 当前消息（单次覆盖），越具体越优先。
3. **指令合并优先级**：系统默认 < 用户级 < 分组级 < 当前消息；冲突时「更具体、更新」者优先；指令编写遵循 RODES（Role / Objective / Details / Examples / Sense-check）。
4. **对话归属可迁移**：ChatGPT「更改项目」、Claude「Change project」均证明分组不是固化属性，必须支持「移动到分组」。
5. **分组管理交互范式**：hover 3-dot 菜单（重命名/编辑指令/删除/移动对话）；删除分组时「对话移回未分组」需确认弹窗。
6. **指令模板与字数统计**：Gemini/国内产品证明模板库 + 一键填入显著降低创建门槛。

---

## 第三部分：符合技术栈的实现方案（总览）

- **方案**：不新增独立分组表之外的重型服务；全部在现有 FastAPI + SQLite + Flutter 架构内扩展。
- **数据层**：新增 `groups` 表与 `GroupStore`；`conversations` 加可空 `group_id` 列 + 索引；老库迁移复用 `UserStore._initialize` 的 PRAGMA + ALTER 模式。
- **接口层**：新增 `/groups` 路由（CRUD）；扩展 `/conversations` 的创建/移动/列表。
- **Prompt 层**：`build_system_prompt` 增加分组级 style/tone/指令参数，按「系统 → 用户级 → 分组级 → 当前消息」顺序合并；无分组或分组无指令时行为与现状完全一致（向后兼容）。
- **前端**：新增 `ChatGroup` 模型与分组 API、`AppState` 增加 `groups`/`activeGroupId` 状态，`history_drawer` 重构为「分组区 + 时间区」双区。
- **兼容策略**：`group_id` 可空（NULL=未分组）；旧库/旧前端零感知；`GET /conversations` 新增字段不影响旧解析。

---

## 第四部分：功能模块划分

| 模块 | 归属 | 交付物 |
|---|---|---|
| M1 分组数据层 | 后端 | `backend/core/stores/group_store.py`；`groups` 表 + 迁移 |
| M2 对话归组数据层 | 后端 | `chat_store.py` 增加 `group_id` 读写；迁移 |
| M3 分组 API | 后端 | `backend/core/web/routers/groups.py`；扩展 `chat.py` |
| M4 Prompt 合并 | 后端 | `build_prompt.py` / `agent.py` / `chat.py` 参数扩展 |
| M5 前端模型与 API | 前端 | `models.dart` / `api_client.dart` |
| M6 前端状态 | 前端 | `app_state.dart`（groups / activeGroupId / 增删改移） |
| M7 前端侧边栏 | 前端 | `history_drawer.dart` 双区重构 + 弹窗组件 |
| M8 指令编辑器与模板 | 前端 | 分组设置弹窗 + 指令模板 |
| M9 文档与测试 | 全栈 | `API.md` 更新；后端 pytest + 前端 widget test |

---

## 第五部分：核心数据结构设计

### 5.1 `groups` 表（新增）

```sql
CREATE TABLE IF NOT EXISTS groups (
    group_id           TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    custom_instruction TEXT NOT NULL DEFAULT '',
    style              TEXT,              -- NULL = 继承用户级
    tone               TEXT,              -- NULL = 继承用户级
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_groups_user ON groups (user_id, updated_at);
```

字段约束：`name` 1-20 字（必填）；`description` ≤100 字（选填）；`custom_instruction` ≤500 字（选填）；`style` ∈ {concise, detailed, socratic}；`tone` ∈ {friendly, formal, encouraging, strict}（与用户偏好枚举一致）；每用户分组上限 20 个。

### 5.2 `conversations` 表（迁移加列）

```sql
-- 老库迁移：PRAGMA table_info(conversations) 检查后执行
ALTER TABLE conversations ADD COLUMN group_id TEXT;   -- NULL = 未分组
CREATE INDEX IF NOT EXISTS idx_conversations_group ON conversations (group_id);
```

### 5.3 `GroupStore` 方法签名

```python
class GroupStore(BaseSQLiteStore):
    _UPDATEABLE_FIELDS = frozenset({"name", "description", "custom_instruction", "style", "tone"})

    def create_group(self, user_id, name, description="", custom_instruction="",
                     style=None, tone=None, group_limit=None) -> dict | None
                     # group_limit 传入时事务内"计数+插入"同锁 超限返回 None
    def get_group(self, group_id) -> dict | None            # 含 conversation_count（子查询计数）
    def list_groups(self, user_id) -> list[dict]            # 含 conversation_count（LEFT JOIN）
    def update_group(self, group_id, **fields) -> bool      # 白名单过滤字段名 + 动态 SET
    def delete_group(self, group_id, user_id) -> bool       # 事务：组内对话置回未分组 + 删组
```

`list_groups` 的 `conversation_count` 用一条 `LEFT JOIN ... GROUP BY` 查询，避免 N+1：

```sql
SELECT g.*, COUNT(c.conversation_id) AS conversation_count
FROM groups g
LEFT JOIN conversations c ON c.group_id = g.group_id
WHERE g.user_id = ?
GROUP BY g.group_id
ORDER BY g.updated_at DESC
```

`get_group` 的 `conversation_count` 用标量子查询（`idx_conversations_group` 覆盖）：

```sql
SELECT g.*, (SELECT COUNT(*) FROM conversations c
             WHERE c.group_id = g.group_id) AS conversation_count
FROM groups g WHERE g.group_id = ?
```

`update_group` 只允许 `_UPDATEABLE_FIELDS` 白名单内的字段拼进 SET 子句（`updated_at` 由方法内部刷新，外部不可覆盖），杜绝字段名注入。

`delete_group` 事务原子性（同一 DB 文件，`with closing(self._connect()) as conn, conn:` 内完成两步）：

```sql
UPDATE conversations SET group_id = NULL WHERE group_id = ? AND user_id = ?;
DELETE FROM groups WHERE group_id = ? AND user_id = ?;
```

### 5.4 Prompt 合并规则（核心）

`build_system_prompt` 扩展参数（新增均可选，缺省时输出与现状逐字节一致）：

```python
def build_system_prompt(
    user_name=None, temp_memory=None, core_memory=None, skills_context=None,
    preferred_style="concise", preferred_tone="friendly", custom_instruction="",
    group_style=None, group_tone=None, group_custom_instruction="",
    user_profile_context=None,
) -> str
```

合并顺序与规则：

1. 系统 Prompt 基础规则（`SYSTEM_PROMPT`，不动）
2. 风格/语调：取 `group_style`（非空则覆盖）→ 否则 `preferred_style`；`group_tone` 同理
3. 自定义指令按序拼接：
   ```
   用户补充要求: <用户级 custom_instruction>
   分组要求: <分组级 group_custom_instruction>   （仅当非空时输出）
   ```
4. 用户学情档案区块（`user_profile_context`）位置不变
5. 当前消息（`input`）由消息序列自然处于最后

`agent.run` / `run_stream` 同步扩展 `group_style` / `group_tone` / `group_custom_instruction` 参数并在 `_prepare_run` 中透传；`chat.py` 在 `_load_owned` 拿到 `conversation["group_id"]` 后，若非空则查 `GroupStore.get_group` 取分组参数注入。同步接口与 SSE 流式接口两处都改。

---

## 第六部分：API 接口定义（与 API.md 契约对齐）

> 全部接口需认证（`Authorization: Bearer <session_id>`），只能操作本人资源；错误统一 `{"detail": "..."}`。

### 6.1 新增：分组接口

**GET /groups** — 分组列表（含对话数）

```json
[
  {
    "group_id": "uuid",
    "user_id": "用户uuid",
    "name": "高数",
    "description": "高等数学复习",
    "custom_instruction": "用苏格拉底式提问引导我",
    "style": null,
    "tone": null,
    "conversation_count": 3,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

**POST /groups** — 新建分组，请求体（全部可选除 name）：

```json
{
  "name": "高数",
  "description": "高等数学复习",
  "custom_instruction": "用苏格拉底式提问引导我",
  "style": null,
  "tone": null
}
```

响应 `201` 分组对象；校验失败 `422`；枚举非法 `400`；超出 20 个 `409`。

**PATCH /groups/{group_id}** — 部分更新（name/description/custom_instruction/style/tone 任一或全部），响应 `200` 最新分组对象；不存在或不属于本人 `404`。

**DELETE /groups/{group_id}** — 删除分组，事务内将组内对话 `group_id` 置 NULL（回未分组），响应 `204`；不存在或不属于本人 `404`。

### 6.2 扩展：对话接口

**POST /conversations** — 请求体改为可空：

```json
{ "title": "线性代数问题", "group_id": "uuid或省略" }
```

响应 `201` 对话对象（新增 `group_id` 字段）。`group_id` 不存在或不属于本人 → `404`。

**PATCH /conversations/{conversation_id}** — 语义从「仅重命名」扩展为「重命名 + 移动分组」，请求体两字段均可选（至少传一个）：

```json
{ "title": "新标题", "group_id": "uuid 或 null(移回未分组)" }
```

响应 `204`。`group_id` 非法 → `404`。前端 `renameConversation` 与新增 `moveConversation` 均走此接口。

**GET /conversations** — 返回元素新增 `group_id` 字段（`null` 表示未分组），排序规则不变（`updated_at DESC`）。移动分组不刷新 `updated_at`（仅新消息刷新），避免移动后对话在时间区跳位。

### 6.3 校验规则汇总

| 字段 | 规则 |
|---|---|
| name | 1-20 字（Pydantic `Field(min_length=1, max_length=20)`） |
| description | ≤100 字 |
| custom_instruction | ≤500 字（与用户级一致，路由层再截断兜底） |
| style / tone | 与 `preferences.py` 的 `VALID_STYLES` / `VALID_TONES` 一致；建议将枚举常量抽到 `schemas.py` 供两处共用 |
| 分组数量 | ≤20/用户，超出 `409` |

---

## 第七部分：分阶段开发计划与时间节点

> 里程碑 M1-M5。阶段工作量为相对估算，实际以联调与回归情况微调。

### 阶段一（M1）：后端数据层 + API（约 2-3 天）

1. 新增 `backend/core/stores/group_store.py`（`GroupStore`，含 `groups` 建表 + `idx_groups_user`）
2. `chat_store.py` `_initialize` 增加 `conversations` 加列迁移（PRAGMA 检查 + `ALTER TABLE ADD COLUMN group_id` + `idx_conversations_group`）
3. `GroupStore` 实现 CRUD、`conversation_count` 统计、`count_groups`、`delete_group` 事务迁移
4. `schemas.py` 新增 `GroupCreateRequest` / `GroupUpdateRequest` / `GroupOut`；扩展 `ConversationCreateRequest` / `RenameRequest`（改名 `ConversationPatchRequest`）；抽出共享风格/语调枚举常量
5. 新增 `backend/core/web/routers/groups.py`（GET/POST /groups、PATCH/DELETE /groups/{id}），注册到 `webAPI.py`
6. 扩展 `chat.py`：`POST /conversations` 接受 `group_id`；`PATCH /conversations/{id}` 支持 `group_id`；`GET /conversations` 返回 `group_id`
7. 更新 `API.md`；编写后端测试（见验收标准）

### 阶段二（M2）：前端分组管理（约 2-3 天）

1. `models.dart` 新增 `ChatGroup`；`ChatConversation` 增加 `groupId`（`fromJson` 容错缺省 `null`）
2. `api_client.dart` 新增 `listGroups` / `createGroup` / `updateGroup` / `deleteGroup`；`createConversation({groupId})`；`moveConversation(id, groupId)`（离线模式同步补假数据）
3. `app_state.dart`：新增 `groups` 列表、`activeGroupId`、`loadingGroups`；登录后随 `loadConversations` 并行 `loadGroups`；实现 `createGroup` / `updateGroup` / `deleteGroup` / `moveConversationToGroup`；`newConversation()` 携带 `activeGroupId`；删除分组后刷新对话列表
4. `history_drawer.dart` 重构为「分组区 + 时间区」双区：`未分组` 桶常驻 + 分组列表（含展开/折叠、对话数），分隔线下保留时间区（置顶/今天/本周/更早）；搜索跨全量
5. 新建分组弹窗、分组行 3-dot 菜单（重命名/编辑指令/删除）、移动对话分组选择器
6. 删除分组确认弹窗（提示「组内 N 个对话将移至未分组」）；空状态引导文案
7. 新建对话默认归入当前选中分组（`activeGroupId`）

### 阶段三（M3）：分组自定义指令全链路（约 1-2 天）

**后端已完成（M3.1-M3.3，2026-08-06）**：

- [x] `build_prompt.py` 增加 `group_style` / `group_tone` / `group_custom_instruction` 参数与合并规则（分组级 style/tone 非 `None` 时覆盖用户级；指令按「用户补充要求」→「分组要求」顺序追加）
- [x] `agent.py` `run` / `run_stream` / `_prepare_run` 增加分组参数并透传
- [x] `chat.py` `send_message` / `stream_message` 按 `conversation.group_id` 查分组并注入（新增 `_load_group_params` 辅助函数；分组已删除时防御性回退为未分组；`stream_message` 在创建 `event_stream` 前绑定局部变量）

**前端待办（M3.4-M3.5，留给前端开发）**：

- [ ] 分组设置弹窗：指令编辑器（0/500 字数统计）+ 风格/语调选择（继承/覆盖下拉）
- [ ] 指令模板库（课程助教 / 苏格拉底式提问 / 批改模式 / 刷题模式）一键填入
- [ ] 验证：分组指令只影响该组对话；与用户级指令合并顺序正确（见验收标准）

### 阶段四（M4）：文档、测试与打磨（约 1-2 天，可选 P2 功能另排）

1. 后端 pytest：`test_group_store.py`（CRUD/迁移/上限/删除事务）、`test_groups_api.py`（状态码/归属/校验）、`test_build_prompt.py`（合并顺序）
2. 前端 widget test：抽屉双区渲染、新建/删除/移动流程
3. 回归：无分组用户界面与现状一致；SSE 流式正常
4. 可选增强（另行排期）：拖拽归档、分组内搜索、智能分组建议、按课程推荐模板

### 时间节点总览

| 里程碑 | 内容 | 相对工作量 | 前置条件 |
|---|---|---|---|
| M1 | 后端数据层 + API | 2-3 天 | 无 |
| M2 | 前端分组管理 | 2-3 天 | M1 完成（前端可 mock 先行） |
| M3 | 分组指令全链路 | 1-2 天 | M1 完成 |
| M4 | 文档测试打磨 | 1-2 天 | M1-M3 完成 |

---

## 第八部分：质量验收标准

1. **零回归**：新用户/无分组用户界面与现状完全一致；`GET /conversations` 旧字段不破坏；同步与 SSE 两条发消息链路均正常。
2. **分组 CRUD**：建组/重命名/改描述/改指令/删除全流程可操作；删除分组后组内对话不丢失（回未分组），`conversation_count` 更新正确。
3. **归属校验**：跨用户访问分组/对话一律 `404`；非法 `group_id` 建对话/移动对话返回 `404`；分组数超 20 返回 `409`。
4. **指令合并**：分组指令对组内对话生效、组外不受影响；合并顺序为「系统 → 用户级 → 分组级 → 当前消息」，分组级 style/tone 覆盖用户级；无分组/分组无指令时 Prompt 与现状一致（可用单元测试断言 Prompt 文本差异）。
5. **接口契约**：所有新接口与 `API.md` 一致；`401` / `404` / `409` / `422` 语义正确；pydantic 校验生效。
6. **数据安全**：删除分组在事务内完成；DB 迁移幂等（重复启动不报错）；旧库升级后数据完整。
7. **前端体验**：抽屉双区渲染正确；新建对话默认归入当前分组；移动对话后列表与计数即时刷新；删除分组确认弹窗提示对话迁移数量。

---

## 第九部分：技术难点与解决方案

| # | 难点 | 风险 | 解决方案 |
|---|---|---|---|
| 1 | **老库迁移**：既有 `conversations` 表加列 | 迁移失败导致启动崩溃/数据丢失 | 复用 `UserStore._initialize` 成熟模式（`PRAGMA table_info` 检查 → `ALTER TABLE`）；迁移幂等；上线前用旧版 schema 的 DB 副本做迁移冒烟 |
| 2 | **删除分组原子性**：组内对话置回未分组 + 删组 | 中途失败产生孤儿 `group_id` | 同一连接事务内完成两步（`with closing(conn) as c, c:`）；先置回再删组；`rowcount` 校验 |
| 3 | **孤儿 `group_id` 引用**：SQLite 默认不启用外键约束 | 对话指向已删除分组 | 代码层约束：`POST /conversations` / `PATCH` 移动前校验 `get_group` 存在且归属本人；可选在连接上 `PRAGMA foreign_keys=ON` + 定义外键 |
| 4 | **`conversation_count` 统计**：每次列表查询聚合 | N+1 查询拖慢列表 | 单条 `LEFT JOIN ... GROUP BY` 一次取全；`idx_conversations_group(user_id, group_id)` 索引覆盖；分组数 ≤20 规模下开销可忽略 |
| 5 | **指令合并与模型遵循度** | 指令过长/冲突导致模型选择性忽略 | 长度上限 500 字；合并规则确定性写入文档并单测断言；Prompt 区块分隔清晰（`用户补充要求:` / `分组要求:` 独立成段）；遵循 RODES 指导用户编写 |
| 6 | **SSE 流式链路参数透传** | `run_stream` 是生成器，参数漏传或闭包捕获错误 | 三处签名同步扩展（`chat.py` → `agent.run_stream` → `_prepare_run` → `build_system_prompt`）；生成器闭包在创建 `event_stream` 前把分组参数绑定为局部变量；回归测试流式链路 |
| 7 | **前端双区抽屉重构** | 时间分组逻辑与分组区耦合、列表状态错乱 | 保持现有时间分组逻辑为独立函数；`AppState` 提供「按分组过滤」纯函数；分组增删改移动后统一 `notifyListeners` 并重载列表；widget test 覆盖 |
| 8 | **移动对话与时间排序语义** | 移动后 `updated_at` 刷新导致对话在时间区跳位 | 明确语义：移动分组只改 `group_id` 不刷新 `updated_at`；仅新消息刷新 |
| 9 | **兼容旧前端/旧数据** | 旧前端解析新字段崩溃、旧数据 `group_id` 列不存在 | `group_id` 可空 + `fromJson` 缺省 `null`；后端列表返回前显式 `dict(row)`（SQLite Row 无该列时报错——迁移先行保证列存在）；旧前端忽略多余字段（JSON 天然兼容） |
| 10 | **并发建组超上限 / 重名** | 双请求同时建第 21 个分组 | 上限校验下沉到 `GroupStore.create_group`：`BEGIN IMMEDIATE` 取写锁后「计数+插入」同事务完成，SQLite 串行化写入保证不超限，超限返回 `None` 由路由转 `409`；名称允许重名（不强制唯一，避免产品语义束缚） |
| 11 | **分组级 style/tone 的「继承」表达** | 前端需要区分「继承用户级」与「覆盖为空」 | 数据模型用 `null` 表示继承；前端下拉框额外提供「继承用户级（默认）」选项，保存时传 `null`；`PATCH` 用 `exclude_unset=True` 保证不传字段不改 |

---

## 第十部分：验收演示脚本（建议）

```text
1. 注册新用户 → 侧边栏仅「未分组」，界面与现状一致
2. 新建「高数」分组 → 新建对话自动归入「高数」→ 发消息「请用苏格拉底式提问引导我学导数」
   → 验证分组指令生效（回复为反问引导风格）
3. 新建「数据结构」分组 → 配置「先给思路，需要时再给代码」→ 新建对话发算法题 → 验证组间指令隔离
4. 把「高数」下的对话移动到「未分组」→ 列表与计数刷新
5. 删除「高数」分组 → 确认弹窗显示组内 N 个对话 → 确认后对话回「未分组」，分组消失
6. 同一账号下直接 GET /groups/其他用户分组 → 404
7. 建满 20 个分组后再建 → 409
8. 重启后端（迁移幂等）→ 数据完好，无报错
```

---

## 附：与既有文档的关系

- `TODO.md`「对话分组 + 分组内自定义指令」一节为本设计的待办清单，完成后逐项勾选。
- `API.md` 在 M1/M3 完成后同步更新本文第六部分的接口契约。
- 本文档替代原 GROUP_FEATURE.md 需求文档，保留其「现状与缺口」「用户场景」等有效内容并细化。
