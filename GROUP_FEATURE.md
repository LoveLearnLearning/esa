# 对话分组 + 分组内自定义指令：需求文档

> 本文档从 TODO.md 迁出（2026-08-01），TODO.md 中仅保留待办清单与本文档引用。
> 内容：项目全景分析、市场调研、功能需求、交互细节、技术要求、分阶段开发计划。

---

## 全景分析：项目架构与功能模块（2026-08-01 更新）

### 一、技术栈与总体结构

| 层 | 技术 | 位置 |
|---|---|---|
| 后端框架 | Python + FastAPI + SQLite | `backend/` 入口 `backend/core/web/webAPI.py` |
| 模型推理 | vLLM（同步 `generate` / 流式 `generate_stream`） | `backend/core/services/vllm_service.py` |
| 前端 | Flutter（多端，当前以聊天界面为主） | `frontend/lib/` |
| 数据存储 | SQLite（users / sessions / conversations / messages 四张表） | `backend/core/stores/` |

### 二、后端模块清单

| 模块 | 关键文件 | 现状 |
|---|---|---|
| Agent 主循环 | `agent/agent.py` | `run()` / `run_stream()` 可用，loop_times=3，注入用户级偏好/学情档案 |
| 核心记忆 | `agent/memories/core_memory.py` | SQLite 键值对，`get_all` 按 `updated_at DESC`（上限限制未做，见 TODO.md 后端 6） |
| 临时记忆 | `agent/memories/temp_memory.py` | 内存，20 条/用户上限 |
| 知识图谱与掌握度 | `agent/memories/{kg_loader,knowledge_graph,mastery_store}.py` | cs 学科种子数据、掌握度报告可用 |
| RAG | `agent/rag/` | loader/splitter/embedding(BGE)/hybrid+bm25/faiss 已实现 |
| Skill 框架 | `agent/skills/`（6 个 skill） | 可加载，`profile_personalization` 已接入学情档案 |
| 工具注册 | `agent/tools/` | 计算器/搜索/记忆/RAG/掌握度等 12+ 工具 |
| Prompt 构建 | `core/message/build_prompt.py` | 注入风格/语调/用户自定义指令/学情档案/记忆/Skill |
| 聊天存储 | `core/stores/chat_store.py` | `conversations` + `messages` 两表，含 is_visible 过滤 |
| Web 层 | `core/web/routers/{auth,chat,preferences}.py` | 认证 / 对话 CRUD+SSE / 偏好与学情档案接口均已就绪 |

### 三、前端模块清单

| 模块 | 关键文件 | 现状 |
|---|---|---|
| 状态管理 | `lib/state/app_state.dart` | ChangeNotifier：对话/消息/置顶(本地)/activeId |
| API 客户端 | `lib/api/api_client.dart` | 认证+对话+消息+SSE 流式，含离线模式 |
| 数据模型 | `lib/models/models.dart` | ChatMessage / ChatConversation（pinned 仅前端本地） |
| 聊天主界面 | `lib/pages/chat_page.dart` | 顶栏+消息区+输入区+空状态任务卡片 |
| 历史侧边栏 | `lib/widgets/history_drawer.dart` | 时间自动分组（置顶/今天/本周/更早）+ 搜索 |
| 偏好设置 | `lib/widgets/profile_sheet.dart` | 已有界面，后端偏好/档案接口已就绪（对接待完成，见 TODO.md 前端 4） |

### 四、对话数据流（现状）

```
前端发消息 → POST /conversations/{id}/messages 或 /messages/stream (SSE)
→ chat.py 校验归属 → ChatStore.get_model_messages(历史)
→ Agent.run / run_stream(preferred_style, preferred_tone, custom_instruction, user_profile_context, total_weeks)
→ build_system_prompt() 组装 System Prompt（用户级指令在此注入）
→ vLLM 推理（可调用工具） → 新消息写回 messages 表 → SSE 推送给前端
```

### 五、与「对话分组 + 分组内自定义指令」相关的现状与缺口

| 现状 | 缺口 |
|---|---|
| `conversations` 表只有 title，无分组字段 | 无法按学科/课程/任务归类对话 |
| 自定义指令仅用户级（`users.custom_instruction` ≤500 字，全对话生效） | 无分组级指令，做不到"不同课不同要求" |
| 侧边栏仅时间自动分组（今天/本周/更早）+ 本地置顶 | 无用户自定义分组树、无持久化分组 |
| `preferences.py` 已有风格/语调/用户指令接口 | 分组级风格/语调/指令未设计 |
| `build_system_prompt` 已支持注入用户级指令 | 需扩展分组级指令参数与优先级合并 |

---

## 市场调研：主流 Agent 产品「对话分组 + 分组内自定义指令」

### 一、调研对象与结论（2026-08 时点）

| 产品 | 分组模型 | 分组内自定义指令 | 关键交互 | 可借鉴点 |
|---|---|---|---|---|
| ChatGPT Projects | 扁平工作区 | 有（Project Instructions，5,000 字符） | 侧边栏 Projects 入口；对话可"更改项目" | 项目级指令 + 对话归属可迁移 |
| Claude Projects | 扁平工作区（明确不嵌套） | 有（Custom Instructions + 知识文件） | 3-dot 菜单：星标/重命名/更换项目/删除 | "指令+知识+对话"三合一；RAG 自动检索 |
| Gemini Gems | 独立 Gem 入口 | 有（name/description/instructions） | 会话开始时选择 Gem | 指令作为"可选会话角色" |
| 豆包 | 标签/轻量整理 | 角色/智能体设定 | 列表左滑删除、标签查找 | 低门槛标签化 |
| 聊夹（浏览器插件） | 多级文件夹树 | 无（纯管理） | 拖拽归档、多级文件夹、全文搜索、书签 | "文件夹树 + 拖拽 + 检索"的整理体验 |
| Claude Code Agent Teams / Codex Subagents | 会话级 Agent 分组 | 每个 Agent 一份指令文件（`developer_instructions` / CLAUDE.md） | 切换 Agent 即切换整套行为约定 | "指令文件"模式：分组=一套可复用行为约定 |

### 二、设计模式提炼（六条）

1. **分组模型分三类**：文件夹树（整理力强、可多级）、扁平工作区（Claude 明确不嵌套、语义聚焦）、标签（最轻量）。→ 教育场景建议一级分组 + "未分组"兜底，避免过度嵌套。
2. **指令作用域三级**：用户级（全局默认）→ 分组/项目级（范围内生效）→ 会话级（单次覆盖），三者叠加，越具体越优先。
3. **指令合并与优先级**：系统默认 < 用户级 < 分组级 < 当前消息；冲突时"更具体、更新"者优先。指令编写遵循 RODES（Role / Objective / Details / Examples / Sense-check），避免含糊与过长。
4. **对话归属可迁移**：Claude"Change project"、ChatGPT"更改项目"表明分组不是创建时的固化属性，必须支持"移动到分组"。
5. **发现与检索**：分组树 + 侧边栏搜索；分组内搜索、对话计数是常见增强。
6. **分组管理交互范式**：hover 3-dot 菜单（重命名/移动/删除）、拖拽归档、删除分组时"对话移回未分组"的安全确认。

### 三、对 ESA 的落地取舍

- 采用"分组（Group）"概念：一个分组 = 一门课程或一类任务；与现有时间自动分组不冲突，用户分组优先展示。
- 分组内自定义指令是核心卖点（贴合"高数助教 / 苏格拉底式讲解 / 批改模式"等教学场景）。
- 指令长度与用户级一致（≤500 字）；优先级：分组指令叠加在用户级指令之后。
- 分组管理入口放在历史侧边栏；未分组常驻兜底；删除分组需二次确认。

---

## 需求文档：对话分组 + 分组内自定义指令

### 一、实现目标

- G1 会话可按学科/课程/任务类型组织为多个分组，归属可迁移、可持久化。
- G2 每个分组可配置独立自定义指令（可选风格/语调），组内所有对话自动生效，无需重复粘贴上下文。
- G3 分组级指令与用户级偏好/学情档案正确合并：不影响其他分组、不篡改记忆/Skill 基础规则。
- G4 前后端全链路打通，API.md 同步更新。

### 二、用户场景

| 编号 | 场景 | 说明 |
|---|---|---|
| S1 | 按课程整理 | 建"高数 / 线性代数 / 概率论 / 数据结构"分组，各课复习对话各归其位 |
| S2 | 按任务类型整理 | "作业批改 / 错题分析 / 刷题 / 查课件"分组，检索一目了然 |
| S3 | 分组内指令 | "高数"组指令"用苏格拉底式提问引导我"；"数据结构"组指令"算法题先给思路，需要时再给代码" |
| S4 | 继承与区分 | 用户级指令"用中文回答、引用标注来源"全局生效；分组指令只补充该课专属要求 |
| S5 | 会话迁移 | 误建在默认分组的对话随时移动到目标分组 |
| S6 | 未分组兜底 | 未选择分组的对话进"未分组"，新用户无感可用 |

### 三、功能需求（按优先级）

**F1 分组 CRUD（P0）**
- 创建：名称（必填 ≤20 字）、描述（选填 ≤100 字）、自定义指令（选填 ≤500 字）
- 重命名 / 删除；删除时组内对话自动移回"未分组"（需确认弹窗）
- 分组上限 20 个/用户

**F2 对话归组与迁移（P0）**
- `conversations` 增加 `group_id`（NULL=未分组）
- 新建对话可指定 group_id（默认当前选中分组，否则未分组）
- 已有对话可移动分组（扩展 `PATCH /conversations/{id}`）

**F3 分组内自定义指令（P0）**
- 分组字段：`custom_instruction`（≤500 字）、可选 `style` / `tone`（缺省继承用户级）
- 该组所有对话（含历史）推理时注入该指令

**F4 指令合并与优先级（P0）**
- 合并顺序：系统 Prompt 基础规则 → 用户级风格/语调/指令 → 分组级指令（+分组级风格/语调）→ 当前消息
- 冲突原则：以更具体（分组级）与最新要求为准

**F5 侧边栏分组树（P1）**
- 顶部用户分组区（可折叠）+ 底部时间自动分组区（置顶/今天/本周/更早）
- 分组行：名称、对话数、展开/折叠箭头；"未分组"常驻兜底
- 选中分组后新建对话默认归入该组

**F6 分组管理入口与交互（P1）**
- "新建分组"按钮 → 弹窗
- 分组行 hover 3-dot 菜单：重命名 / 编辑指令 / 删除
- 对话行菜单新增"移动到分组"；拖拽归档（P2 可选）
- 删除确认弹窗："组内 N 个对话将移至未分组"

**F7 分组指令编辑器（P2）**
- 字段：名称/描述/指令；指令区 0/500 字数统计
- 模板快捷入口（课程助教 / 苏格拉底式提问 / 批改模式 等）一键填入
- 保存即对组内全部对话生效（后端持久化）

**F8 搜索范围（P2）**
- 侧边栏搜索默认全量；支持分组内搜索

**F9 智能分组建议（P3 可选）**
- 按标题关键词/知识点匹配建议分组；创建分组时按课程名推荐指令模板

### 四、交互细节

1. **侧边栏布局**（自上而下）：
   - 顶部：新建对话按钮 + 搜索框（现状保留）
   - 分组区：`未分组`（常驻）+ 用户分组列表，组名左侧箭头可展开/折叠；组名右侧显示对话数
   - 分隔线后：时间自动分组区（置顶/今天/本周/更早，现状保留）
   - 底部：用户条（现状保留）
2. **新建分组**：点击"新建分组"→ 弹窗输入名称（必填）、描述（选填）→ 创建后自动展开并高亮；指令可在创建时一并填写或后续编辑。
3. **移动对话**：对话行 3-dot 菜单 → "移动到分组" → 弹出分组选择器（含"未分组"）→ 选择后对话移入并刷新计数。
4. **编辑指令**：分组行 3-dot → "编辑指令" → 打开分组设置弹窗（名称/描述/指令 + 模板按钮 + 字数统计）→ 保存。
5. **删除分组**：3-dot → "删除" → 确认弹窗（提示"组内 N 个对话将移至未分组"）→ 确认后删除分组，对话迁移。
6. **空状态**：无任何分组时显示引导文案"创建分组，按课程或任务整理对话"。
7. **无感知兼容**：从未使用分组的用户看到的界面与现状完全一致（只有"未分组"桶），零学习成本。

### 五、技术要求 —— 后端

**数据模型**（`chat_store.py` 或新增 `group_store.py`）：

```sql
CREATE TABLE IF NOT EXISTS groups (
    group_id           TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    custom_instruction TEXT NOT NULL DEFAULT '',
    style              TEXT,              -- NULL 表示继承用户级
    tone               TEXT,              -- NULL 表示继承用户级
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_groups_user ON groups (user_id, updated_at);
```

`conversations` 表加列（老库迁移同 `UserStore._initialize` 模式）：
- `group_id TEXT`（NULL=未分组），加索引 `idx_conversations_group (user_id, group_id)`

**接口清单**（全部需认证、只允许操作本人资源）：

| 接口 | 方法 | 说明 |
|---|---|---|
| `/groups` | GET | 分组列表（含 conversation_count） |
| `/groups` | POST | 新建分组 |
| `/groups/{group_id}` | PATCH | 更新名称/描述/指令/风格/语调 |
| `/groups/{group_id}` | DELETE | 删除分组（组内对话移回未分组） |
| `/conversations` | POST | 请求体扩展可选 `group_id` |
| `/conversations/{id}` | PATCH | 请求体扩展可选 `group_id`（移动分组） |
| `/conversations` | GET | 返回元素扩展 `group_id` |

校验规则：name 1-20 字；description ≤100 字；custom_instruction ≤500 字；style/tone 枚举与 preferences 一致；分组数 ≤20（超出返回 409）。

**Prompt 注入链路**：
- `build_system_prompt` 新增参数 `group_custom_instruction: str = ""`（可选 `group_style`/`group_tone`），追加在用户级指令之后：`用户补充要求: ...\n分组要求: ...`。
- `agent.py` 的 `run` / `run_stream` 新增对应参数；`chat.py` 在 `send_message` / `stream_message` 中按 `conversation.group_id` 查分组并传入。
- 无分组或分组无指令时行为与现状完全一致（向后兼容）。

### 六、技术要求 —— 前端

| 项 | 说明 |
|---|---|
| 数据模型 | `models.dart` 新增 `ChatGroup`（id/name/description/customInstruction/style/tone/conversationCount/updatedAt）；`ChatConversation` 增加 `groupId` |
| API 客户端 | `api_client.dart` 新增 `listGroups` / `createGroup` / `updateGroup` / `deleteGroup`；`createConversation` / `renameConversation` 支持 `groupId` |
| 状态管理 | `app_state.dart` 新增 `groups` 列表 + `activeGroupId`；`loadGroups`（登录后随 `loadConversations` 加载）、`createGroup` / `updateGroup` / `deleteGroup` / `moveConversationToGroup`；`newConversation` 携带当前分组 |
| 组件 | `history_drawer.dart` 重构为「分组区 + 时间区」双区列表；新增分组行、3-dot 菜单、新建/编辑弹窗、移动分组选择器 |
| 兼容 | `ChatGroup.fromJson` 对旧后端缺失字段给出默认值；未分组对话 `groupId == null` 归入"未分组"桶 |

---

## 分阶段开发计划：对话分组 + 分组内自定义指令

### 阶段一（P0）：后端数据层与 API（约 1-2 天）

- [ ] 1. 新增 `groups` 表与 `GroupStore`（建表 + 老库迁移，模式参考 `UserStore._initialize`）
- [ ] 2. `conversations` 表加 `group_id` 列 + 索引（含迁移）
- [ ] 3. 实现 `GET/POST /groups`、`PATCH/DELETE /groups/{group_id}`（含归属校验、字段校验、分组上限）
- [ ] 4. `POST /conversations` 支持 `group_id`；`PATCH /conversations/{id}` 支持移动分组；列表返回 `group_id`
- [ ] 5. 删除分组时组内对话置回未分组（事务内完成）
- [ ] 6. 更新 `API.md` 接口文档

### 阶段二（P1）：前端分组管理（约 2-3 天）

- [ ] 1. `models.dart` 新增 `ChatGroup`，`ChatConversation` 加 `groupId`
- [ ] 2. `api_client.dart` 新增分组四个方法 + 对话分组参数
- [ ] 3. `app_state.dart` 新增 `groups` / `activeGroupId` 与增删改/移动逻辑，登录后加载
- [ ] 4. `history_drawer.dart` 重构为分组区 + 时间区；"未分组"桶常驻
- [ ] 5. 新建分组弹窗、分组行 3-dot 菜单（重命名/删除/编辑指令）、移动分组选择器
- [ ] 6. 删除分组确认弹窗（提示对话迁移）；空状态引导文案
- [ ] 7. 新建对话默认归入当前选中分组

### 阶段三（P2）：分组自定义指令全链路（约 1-2 天）

- [ ] 1. `build_system_prompt` 增加分组级指令/风格/语调参数与合并规则
- [ ] 2. `agent.run` / `run_stream` 增加分组参数；`chat.py` 按对话分组查指令并注入
- [ ] 3. 分组设置弹窗：指令编辑器（0/500 字数统计）+ 风格/语调选择（继承/覆盖）
- [ ] 4. 指令模板库（课程助教 / 苏格拉底式提问 / 批改模式 / 刷题模式）
- [ ] 5. 验证：分组指令只影响该组对话；与用户级指令合并顺序正确

### 阶段四（P3）：增强与打磨（可选）

- [ ] 1. 拖拽对话到分组
- [ ] 2. 分组内搜索
- [ ] 3. 智能分组建议（标题关键词/知识点匹配）
- [ ] 4. 按课程名自动推荐指令模板
- [ ] 5. 分组对话计数徽标、分组排序（手动/按活动）

### 验收标准

1. 新用户无分组时界面与现状一致，功能零回归；
2. 建组/移组/删除/重命名全流程可操作，删除分组对话不丢失（回未分组）；
3. 分组指令对组内对话生效、组外不受影响；与用户级指令正确合并；
4. 接口与 API.md 一致，所有接口 401/404/409/422 语义正确。
