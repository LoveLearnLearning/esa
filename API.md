# ESA 前后端接口文档

> 在这里记录前后端网络 endpoint 前端照此对接 后端改动接口时同步更新本文档
>
> 最后核对：2026-08-12。

- Base URL（`python -m backend.main`）: `http://127.0.0.1:51024/api`
- 生产 Base URL: `https://esa.lovelearnlearning.cn/api`
- 开发启动命令: `uvicorn backend.core.web.webAPI:app --host 0.0.0.0 --port 51024 --reload`
- 交互式调试: 启动后访问 `http://127.0.0.1:51024/docs`
- 通信格式: 普通接口使用 JSON 流式消息接口响应 `text/event-stream`
- 时间格式: 统一为 UTC ISO 8601 字符串 例如 `2026-07-24T05:22:08.123456+00:00`

下文标题中的 `/auth/...`、`/conversations/...`、`/me/...` 均为相对 Base URL
的路径。例如 `POST /auth/login` 的实际 canonical wire path 是
`POST /api/auth/login`。迁移期仍可通过 `ESA_ENABLE_LEGACY_API_ROUTES=true`
启用旧的无 `/api` 前缀别名，但新客户端不得依赖这些别名。

## 认证约定

登录成功后获得 `session_id` 之后所有需要登录的接口都必须携带请求头:

```
Authorization: Bearer <session_id>
```

认证失败统一返回 `401` 会话有效期 7 天 前端收到 401 应清除本地 token 并跳转登录页

## 错误格式

所有错误响应体统一为 FastAPI 默认格式:

```json
{ "detail": "错误说明" }
```

| 状态码 | 含义                                                           |
| ------ | -------------------------------------------------------------- |
| 401    | 未登录 / 会话无效 / 会话过期 / 邮箱、用户名或密码错误          |
| 404    | 资源不存在或不属于当前用户                                     |
| 409    | 资源冲突，如用户名或邮箱已存在、分组达到上限                    |
| 429    | 验证码发送过于频繁，按 `Retry-After` 响应头稍后重试             |
| 422    | 请求体校验不通过 由 pydantic 自动返回                          |

---

## 运维接口

### GET /health — 存活检查

无需认证，成功响应 `200`：

```json
{ "status": "ok" }
```

该接口只表示 HTTP 进程存活，不访问数据库，也不调用主模型、辅助模型或 RAG。

---

## 已实现接口

### POST /auth/email/send-code — 发送注册验证码

无需认证。请求体：

```json
{ "email": "user@example.com" }
```

成功响应 `202`：

```json
{ "status": "accepted", "retry_after_seconds": 60 }
```

验证码默认 10 分钟有效、同一邮箱 60 秒内不可重发。验证码由业务后端生成和校验，
独立邮件服务器只负责投递。邮箱已注册返回 `409`，邮件服务未配置返回 `503`，
投递失败返回 `502`。

### POST /auth/register — 邮箱注册

无需认证

请求体:

```json
{
  "email": "user@example.com",
  "verification_code": "123456",
  "username": "feng",
  "password": "password123"
}
```

校验规则: `username` 1-32 位 `password` 8-128 位 不符合返回 422

成功响应 `201`:

```json
{ "user_id": "服务端生成的uuid", "username": "feng", "email": "user@example.com" }
```

验证码错误或过期返回 `400`，用户名或邮箱已存在返回 `409`。

### POST /auth/login — 登录

无需认证

请求体:

```json
{ "username": "user@example.com", "password": "password123" }
```

成功响应 `200`:

```json
{
    "session_id": "uuid 作为后续请求的 Bearer token",
    "user_id": "用户uuid",
    "username": "feng",
    "email": "user@example.com",
    "expires_at": "2026-07-24T07:22:08.123456+00:00"
}
```

`username` 字段兼容邮箱和用户名。老用户可继续用用户名登录；已绑定邮箱的用户也可
使用邮箱登录。失败返回 `401`，不区分具体原因。

注意: 密码原样发送 前端不要对密码做 trim 或其他改动

### POST /auth/email/bind/send-code — 发送绑定邮箱验证码

需要认证，请求和响应与发送注册验证码相同。邮箱已被使用返回 `409`。

### POST /auth/email/bind — 绑定或更换邮箱

需要认证。请求体：

```json
{ "email": "user@example.com", "verification_code": "123456" }
```

成功响应 `200`：`{ "email": "user@example.com" }`。

### POST /auth/logout — 登出

需要认证

无请求体 成功响应 `204` 无响应体

### POST /auth/change-password — 修改密码

需要认证。请求体：

```json
{
    "old_password": "old-password",
    "new_password": "new-password"
}
```

成功响应 `204`，并撤销该用户的全部已有会话，前端需要返回登录页。旧密码错误或新旧密码相同返回 `400`。

---

## Workspace 与科研项目接口

以下接口均需要认证。`account_role` 目前只允许 `student` 或 `teacher`：学生可进入学习、科研 Workspace，教师可进入教学、科研 Workspace。

### GET /workspaces — 当前账号可用 Workspace

响应 `200`：

```json
{
  "account_role": "student",
  "default_workspace": "learning",
  "workspaces": [
    {
      "type": "learning",
      "name": "学习空间",
      "description": "课程学习、练习、课表与知识掌握",
      "capabilities": ["chat", "schedule", "knowledge_map", "mastery"]
    },
    {
      "type": "research",
      "name": "科研空间",
      "description": "科研项目、文献、写作、趋势与数据分析",
      "capabilities": ["chat", "research_projects", "attachments"]
    }
  ]
}
```

### GET/POST /research/projects — 科研项目列表与创建

创建请求：

```json
{ "name": "多智能体科研", "description": "前沿追踪与论文写作" }
```

创建成功返回 `201`。列表默认只返回当前用户的活跃项目；`GET /research/projects?include_archived=true` 可包含归档项目。

### GET/PATCH /research/projects/{project_id} — 项目详情与更新

PATCH 可传 `name`、`description`、`status`，其中 `status` 为 `active` 或 `archived`。项目不存在或不属于当前用户均返回 `404`。

---

## 对话接口

以下接口均需要认证 只能访问属于当前登录用户的对话

### GET /conversations — 历史对话列表

可用 `workspace_type=learning|teaching|research` 过滤；服务端会校验当前账号是否有权进入该 Workspace。

响应 `200` 按最近更新排序:

```json
[
    {
        "conversation_id": "uuid",
        "user_id": "用户uuid",
        "title": "对话标题",
        "group_id": "分组uuid 或 null(未分组)",
        "workspace_type": "learning",
        "research_project_id": null,
        "created_at": "...",
        "updated_at": "..."
    }
]
```

### POST /conversations — 新建对话

请求体(`title` / `group_id` 均可省略 默认 "新对话" + 未分组):

```json
{
  "title": "线性代数问题",
  "group_id": "分组uuid",
  "workspace_type": "learning",
  "research_project_id": null
}
```

响应 `201`: 单个对话对象 结构同上

`group_id` 不存在或不属于当前用户: `404`。无权进入所选 Workspace 返回 `403`；科研项目不存在或不属于当前用户返回 `404`；非科研 Workspace 绑定科研项目返回 `422`。

### PATCH /conversations/{conversation_id} — 重命名或移动分组

请求体两字段均可选 至少提供一个 (`group_id` 传 `null` 表示移回未分组):

```json
{ "title": "新标题", "group_id": "分组uuid 或 null" }
```

成功响应 `204`; 空请求体: `422`; 对话不存在: `404`; `group_id` 非法: `404`

注意: 移动分组不刷新 `updated_at` 避免对话在时间区跳位

### DELETE /conversations/{conversation_id} — 删除对话

删除对话及其全部消息 成功响应 `204`

### GET /conversations/{conversation_id}/messages — 历史消息

响应 `200` 按时间顺序:

```json
[
    {
        "role": "user | assistant | tool",
        "content": "消息内容",
        "name": "工具名 仅 tool 消息有 其余为 null",
        "created_at": "..."
    }
]
```

### POST /conversations/{conversation_id}/messages — 发送消息

请求体:

```json
{
  "content": "用户输入的内容",
  "attachment_ids": ["本对话内已解析的 DocIR document_id"]
}
```

`attachment_ids` 可省略，单轮最多 3 个；附件不存在或不属于当前对话时返回 `404`。

响应 `200`: 本轮新产生的消息列表(用户消息 + 助手回复 + 工具结果) 结构同历史消息

注意: 该同步兼容接口会等待本轮模型与工具调用全部完成后再返回

对话不存在或不属于当前用户: `404`

### POST /conversations/{conversation_id}/attachments — 解析附件

使用 `multipart/form-data` 上传字段名为 `file` 的单个文件，最大 15 MB。支持 PDF、
DOCX、PPTX、XLSX 及 PNG/JPEG/WebP/BMP/GIF/TIFF。服务端执行
`MinerU → DocIR → VLM 派生描述`，短文档返回 `mode: direct`，长文档返回
`mode: rag`；响应包含 `id`、文件名、token/元素/页数和 DocIR 校验状态。

将响应 `id` 放进发送消息的 `attachment_ids` 后，后端才会把全文或当前查询的 RAG
证据注入本轮。`MM_ENABLED=false` 时返回 `503`。

### DELETE /conversations/{conversation_id}/attachments/{attachment_id}

释放当前对话内的临时附件句柄，成功响应 `204`。

### POST /conversations/{conversation_id}/messages/stream — 流式发送消息

请求头除认证信息外使用 `Content-Type: application/json`，请求体与同步接口相同:

```json
{ "content": "用户输入的内容" }
```

成功响应 `200`，响应类型为 `text/event-stream`。事件格式:

```text
event: reasoning
data: {"delta":"正在分析"}

event: content
data: {"delta":"回答正文"}

```

事件类型:

| event       | data              | 含义                   |
| ----------- | ----------------- | ---------------------- |
| `start`     | `conversation_id` | 服务端开始处理         |
| `reasoning` | `delta`           | 模型思考内容增量       |
| `content`   | `delta`           | 最终回答增量           |
| `tool`      | `name`, `content` | 工具执行结果           |
| `done`      | `conversation_id` | 本轮完成且消息已持久化 |
| `error`     | `detail`, `type`  | 流建立后发生生成错误   |

客户端必须按 SSE 空行分隔事件，并将同类 `delta` 按收到顺序追加，不能把每个增量作为独立消息。工具调用 XML 不会作为可见内容发送。

### 同一对话并发约定

同步与流式发送接口共用对话级租约。同一 `conversation_id` 的请求会跨协程和多个
Uvicorn worker 串行处理，从读取历史、写入用户消息直到助手消息持久化都保持顺序；
不同对话不互相阻塞。等待上一轮超过服务端时限时返回 `409`：

```json
{ "detail": "上一条消息仍在生成，请稍后重试" }
```

客户端收到该响应后不应自动重复追加用户消息，提示用户稍后重试即可。

---

## 对话分组接口

以下接口均需要认证 只能操作属于当前登录用户的分组

### GET /groups — 分组列表

响应 `200` 按最近更新排序 每组含对话数:

```json
[
    {
        "group_id": "uuid",
        "user_id": "用户uuid",
        "name": "分组名称",
        "description": "分组描述",
        "custom_instruction": "分组内自定义指令",
        "style": "concise | detailed | socratic 或 null(继承用户级)",
        "tone": "friendly | formal | encouraging | strict 或 null(继承用户级)",
        "conversation_count": 3,
        "created_at": "...",
        "updated_at": "..."
    }
]
```

### POST /groups — 新建分组

请求体(`name` 必填 1-20 字; `description` ≤100 字; `custom_instruction` ≤500 字; `style` / `tone` 可省略或为 null 表示继承用户级):

```json
{
    "name": "高数",
    "description": "高等数学复习",
    "custom_instruction": "用苏格拉底式提问引导我",
    "style": null,
    "tone": null
}
```

响应 `201`: 单个分组对象(含 `conversation_count: 0`)

`style` / `tone` 枚举非法: `400`; 字段超长/`name` 为空: `422`; 分组数量已达上限(20 个): `409`

### PATCH /groups/{group_id} — 更新分组

请求体为部分更新 以下字段均可选 (`style` / `tone` 传 `null` 表示改回继承用户级):

```json
{
    "name": "高等数学",
    "custom_instruction": "先给思路",
    "style": "socratic",
    "tone": null
}
```

响应 `200`: 最新分组对象; 不存在或不属于当前用户: `404`; 枚举非法: `400`

### DELETE /groups/{group_id} — 删除分组

删除分组 组内全部对话自动移回未分组(事务内完成) 成功响应 `204`; 不存在或不属于当前用户: `404`

### 分组指令生效说明（后端已实现，前端无需额外对接）

- 分组的 `custom_instruction` / `style` / `tone` 由后端在**发消息时自动生效**：`POST /conversations/{id}/messages` 与 `POST /conversations/{id}/messages/stream` 会根据该对话的 `group_id` 查出分组并注入 Prompt，前端**不需要**在发消息请求里传任何分组参数。
- 合并顺序：**系统 → 用户级（`/me/preferences`）→ 分组级（本接口）→ 当前消息**。分组级 `style` / `tone` 非 `null` 时覆盖用户级；指令按「用户补充要求」→「分组要求」顺序追加进 Prompt。
- 未分组对话、或分组已被删除时，行为与现状完全一致（全部继承用户级）。
- 前端只需提供分组编辑入口（指令编辑器 + 风格/语调选择），保存后立即对组内对话生效。

---

## 学习情况接口

以下接口均需要认证。

### GET /me/learning/mastery

可选查询参数 `course`。返回知识点总数、平均掌握度、薄弱点、优势点和需要复习的知识点。

### GET /me/learning/courses

返回当前用户已加入学习空间的课程，而不是返回全部全局课程。每项包含
`canonical_course`、`supported`、`source`，以及已评估、薄弱、待复习知识点数量和
平均掌握度。未匹配 canonical KG 的课表课程仍会保留，此时 `supported: false`；
未产生学习证据的课程，其 `average_mastery` 为 `null`。

### GET /me/learning/course-catalog

返回 ESA 全局支持的 canonical 课程目录。可选查询参数 `query` 做名称搜索；每项的
`added` 表示当前用户是否已加入。课程目录和 KG 为全局共享数据，不会按用户复制。

### POST /me/learning/courses

把一门或多门课程加入当前用户的学习空间：

```json
{
    "courses": [
        { "name": "数据结构", "source": "timetable" },
        { "name": "高等数学", "source": "manual" }
    ]
}
```

`source` 可为 `timetable` 或 `manual`。课表来源允许暂不受 KG 支持的课程，以便前端显示
明确的“不支持”状态；手动来源必须从 canonical 课程目录选择。后端会先用
`course_aliases.yaml` 做确定性别名解析，例如“数字电路技术”会关联到
“数字逻辑与数字电路”；不会使用可能误绑课程的自动模糊匹配。

### PATCH /me/learning/courses/{course_name}

将一个尚未匹配的课表课程手动关联到 canonical 课程，同时保留原课表显示名称：

```json
{ "canonical_course": "数字逻辑与数字电路" }
```

该关联只改变用户课程到全局 KG 的引用，不复制或修改 KG。

### DELETE /me/learning/courses/{course_name}

从当前用户的学习空间移除课程，成功响应 `204`；不会删除全局课程或知识图谱。

### GET /me/learning/knowledge-map

必填查询参数 `course`。返回课程知识图的 `nodes` 和 `edges`。边方向固定为
`prerequisite -> dependent`。未评估节点返回 `mastery_level: null`、
`status: "unseen"`，不会伪装成 50 分掌握度。

### GET /me/learning/knowledge-points/{kp_id}

返回单个知识点的规范信息、掌握度、记忆保持率、判断可信度、学习证据摘要和薄弱前置。
路径参数既可以是规范 `kp_id`，也可以是已配置的知识点名称或别名。

### GET /me/learning/review-queue

可选查询参数 `course`。按当前记忆保持率从低到高返回待复习知识点。

### GET /me/learning/recommendations

查询参数：`course`（必填）、`weeks_to_exam`（可选，默认 4）。返回按优先级排序的练习推荐。

---

## 课表接口

以下接口均需要认证，数据按用户隔离并存储在 SQLite。保存或导入课程时，会同步维护
`user_courses` 关联，使知识地图不需要再次录入课程。

每个用户可拥有多张课程表（`schedule_tables`），课程归属某一张课程表，且始终有一张
处于激活状态；没有课程表时服务端会自动创建"默认课表"，历史课程在迁移时归入其中。

### GET /me/schedule

返回当前用户的 `tables`（每项含 `id`、`name`、`is_active`）、`active_table_id`、
激活课程表下的 `courses` 和 `settings`。设置包括上午/下午/晚上的节数与开始时间、
单节时长、课间间隔，以及 `term_start_date`（第一教学周周一，`YYYY-MM-DD`）。前端据此
结合系统日期计算当前教学周和星期。作息设置为用户级，所有课程表共用。

### POST /me/schedule/tables

创建课程表：`{"name": "大二上", "activate": true}`（`activate` 缺省 true，创建后
立即切换为激活表）。返回 201 与新表信息。

### PATCH /me/schedule/tables/{table_id}

重命名课程表：`{"name": "新名称"}`。

### POST /me/schedule/tables/{table_id}/activate

切换激活课程表，返回与 `GET /me/schedule` 相同结构的快照。

### DELETE /me/schedule/tables/{table_id}

删除课程表及其全部课程；删除的是激活表时自动激活剩余最早创建的一张。最后一张课程表
不允许删除（409）。被删课程若不再出现于任何课程表，会同步清理 timetable 来源的用户
课程关联。

### PUT /me/schedule/courses

新增或更新一条课程安排。字段包括 `id`、`name`、`teacher`、`location`、`weekday`
（周一为 1）、`start_period`、`end_period`、`start_week`、`end_week` 和 `color_value`。
新课程写入当前激活课程表；更新已有课程保持其原课程表归属。

### DELETE /me/schedule/courses/{course_id}

删除课程安排。若相同名称的课表课程已全部删除，也会移除由课表自动创建且不再使用的
用户课程关联，不影响全局 canonical KG。

### PUT /me/schedule/settings

保存课表作息和第一周日期，返回服务端持久化后的完整设置。

### POST /me/schedule/import

使用 `multipart/form-data` 上传字段名为 `file` 的课表文件，最大 15 MB。启用 MM 时，
PDF、DOCX、PPTX、XLSX 与常见图片先经过 `MinerU → DocIR → Markdown`，再由本机辅助
模型做课程字段提取；响应的 `document.pipeline` 为 `docir`，并携带 document id、
校验状态、元素数与页数。HTML 以及未启用 MM 时的 PDF/图片保留兼容解析路径，响应为
`document.pipeline: legacy`。模型输出经过严格 Schema 校验后才会去重写入用户课表；
辅助模型不可用时返回 `502`，不会回退占用主模型。

---

## 长期记忆接口

以下接口均需要认证，并且只能管理当前用户的记忆。

### GET /me/memories

返回当前用户的全部长期核心记忆。

### PUT /me/memories

按 `memory_key` 新增或更新记忆：

```json
{
    "memory_key": "learning_goal",
    "content": "本学期重点学习操作系统",
    "category": "learning"
}
```

### DELETE /me/memories/{memory_key}

删除指定记忆，成功响应 `204`。

---

## 输出偏好接口

### GET /me/preferences

返回当前用户的回答风格、语调和自定义指令。

### PATCH /me/preferences

可更新 `preferred_style`、`preferred_tone` 和 `custom_instruction`。前端当前已完成对接。

## 学情档案接口

### GET /me/profile

返回 Profile V2 结构化画像视图，包括 `explicit`、`preferences`、`learning_state`、
`inferred_patterns`、`profile_version` 等分节。为兼容旧客户端，响应顶层同时保留：

- `major`
- `grade`
- `current_week`
- `total_weeks`
- `profile_enabled`

新客户端应优先使用分节字段；只需要编辑基础学情资料的客户端可以继续读取上述顶层字段。

### PATCH /me/profile

更新当前用户学情档案。档案开启时，Agent 会将相关学情信息注入本轮上下文。

请求字段均可选：`major`、`grade`、`current_week`、`total_weeks`、
`profile_enabled`。其中当前只接受 `major="cs"`，并要求
`current_week <= total_weeks`。

### PATCH /me/profile/explicit

Profile V2 的显式字段统一更新入口，可部分更新：

```json
{
    "major": "cs",
    "grade": "大二",
    "current_week": 6,
    "total_weeks": 18,
    "preferred_style": "concise",
    "preferred_tone": "friendly",
    "custom_instruction": "先给思路，再给答案"
}
```

成功时返回最新的完整 Profile V2 视图。该接口每个用户每分钟最多 10 次。

### GET /me/profile/sources

使用查询参数 `field_key` 查看一个推断画像字段的来源、置信度、支撑记忆 ID 和最后确认
时间。例如：`GET /me/profile/sources?field_key=learning_goal`。未命中时返回
`found: false`，不返回 404。

### DELETE /me/profile/inferred/{field_key}

抑制一个推断画像字段，使其后续不再注入 Prompt。该操作保留审计记录，不删除原始长期
记忆；字段不存在或已经被抑制时返回 `404`。成功响应：

```json
{ "deleted": true, "field_key": "learning_goal" }
```

### GET /me/profile/export

导出当前用户全部画像维度，包括 active 和 suppressed 记录。响应包含 `user_id`、
`exported_at` 和 `dimensions`。

### DELETE /me/profile?confirm=DELETE

物理删除当前用户的全部派生画像维度，并失效画像缓存。缺少精确的
`confirm=DELETE` 时返回 `400`。该接口不删除登录账户、长期记忆或记忆设置，每个用户
每分钟最多调用一次。

## 记忆与画像开关

### GET /me/memory-settings

返回：

```json
{
    "learning_profile_enabled": true,
    "inferred_profile_enabled": true,
    "default_conversation_mode": "normal"
}
```

### PATCH /me/memory-settings

上述字段均可部分更新。`default_conversation_mode` 只允许：

- `normal`：允许读取和写入长期状态
- `no_write`：允许读取，不写入长期状态
- `isolated`：不读取也不写入长期状态

成功时返回最新设置；该接口每个用户每分钟最多 10 次。

## Web 部署约定

Flutter Web 默认使用同源 `/api`。Nginx 必须把 `/api` 前缀原样转发到后端；
`proxy_pass` 末尾不能带 `/`，否则会剥离后端所需的 `/api`。SSE 代理必须关闭缓冲：

```nginx
# 运维指标不应通过公网前端域名暴露。
location ^~ /api/internal/ {
    return 404;
}

location ^~ /api/ {
    proxy_pass http://115.29.197.244:51024;
    proxy_http_version 1.1;
    client_max_body_size 20m;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```
