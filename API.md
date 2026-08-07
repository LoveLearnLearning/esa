# ESA 前后端接口文档

> 在这里记录前后端网络 endpoint 前端照此对接 后端改动接口时同步更新本文档
>
> 最后核对：2026-08-04。

- Base URL（`python -m backend.main`）: `http://127.0.0.1:51024`
- 开发启动命令: `uvicorn backend.core.web.webAPI:app --host 0.0.0.0 --port 51024 --reload`
- 交互式调试: 启动后访问 `http://127.0.0.1:51024/docs`
- 通信格式: 普通接口使用 JSON 流式消息接口响应 `text/event-stream`
- 时间格式: 统一为 UTC ISO 8601 字符串 例如 `2026-07-24T05:22:08.123456+00:00`

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

| 状态码 | 含义 |
|---|---|
| 401 | 未登录 / 会话无效 / 会话过期 / 用户名或密码错误 |
| 404 | 资源不存在或不属于当前用户 |
| 409 | 资源冲突 如用户名已存在 |
| 422 | 请求体校验不通过 由 pydantic 自动返回 |

---

## 已实现接口

### POST /auth/register — 注册

无需认证

请求体:

```json
{ "username": "feng", "password": "password123" }
```

校验规则: `username` 1-32 位 `password` 8-128 位 不符合返回 422

成功响应 `201`:

```json
{ "user_id": "服务端生成的uuid", "username": "feng" }
```

失败: `409` 用户名已存在

### POST /auth/login — 登录

无需认证

请求体:

```json
{ "username": "feng", "password": "password123" }
```

成功响应 `200`:

```json
{
  "session_id": "uuid 作为后续请求的 Bearer token",
  "user_id": "用户uuid",
  "username": "feng",
  "expires_at": "2026-07-24T07:22:08.123456+00:00"
}
```

失败: `401` 用户名或密码错误(不区分具体原因)

注意: 密码原样发送 前端不要对密码做 trim 或其他改动

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

## 对话接口

以下接口均需要认证 只能访问属于当前登录用户的对话

### GET /conversations — 历史对话列表

响应 `200` 按最近更新排序:

```json
[
  {
    "conversation_id": "uuid",
    "user_id": "用户uuid",
    "title": "对话标题",
    "group_id": "分组uuid 或 null(未分组)",
    "created_at": "...",
    "updated_at": "..."
  }
]
```

### POST /conversations — 新建对话

请求体(`title` / `group_id` 均可省略 默认 "新对话" + 未分组):

```json
{ "title": "线性代数问题", "group_id": "分组uuid" }
```

响应 `201`: 单个对话对象 结构同上

`group_id` 不存在或不属于当前用户: `404`

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
{ "content": "用户输入的内容" }
```

响应 `200`: 本轮新产生的消息列表(用户消息 + 助手回复 + 工具结果) 结构同历史消息

注意: 该同步兼容接口会等待本轮模型与工具调用全部完成后再返回

对话不存在或不属于当前用户: `404`

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

| event | data | 含义 |
|---|---|---|
| `start` | `conversation_id` | 服务端开始处理 |
| `reasoning` | `delta` | 模型思考内容增量 |
| `content` | `delta` | 最终回答增量 |
| `tool` | `name`, `content` | 工具执行结果 |
| `done` | `conversation_id` | 本轮完成且消息已持久化 |
| `error` | `detail`, `type` | 流建立后发生生成错误 |

客户端必须按 SSE 空行分隔事件，并将同类 `delta` 按收到顺序追加，不能把每个增量作为独立消息。工具调用 XML 不会作为可见内容发送。

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
{ "name": "高等数学", "custom_instruction": "先给思路", "style": "socratic", "tone": null }
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

### GET /me/learning/recommendations

查询参数：`course`（必填）、`weeks_to_exam`（可选，默认 4）。返回按优先级排序的练习推荐。

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

返回专业、年级、当前教学周、总教学周和档案开关。

### PATCH /me/profile

更新当前用户学情档案。档案开启时，Agent 会将相关学情信息注入本轮上下文。

## Web 部署约定

推荐把 Flutter Web 编译时的 `ESA_API_BASE` 设置为 `/api`，再由 Nginx 反向代理到 `127.0.0.1:51024`。SSE 代理必须关闭缓冲：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:51024/;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
}
```
