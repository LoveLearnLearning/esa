# ESA 前后端接口文档

> 在这里记录前后端网络 endpoint 前端照此对接 后端改动接口时同步更新本文档

- Base URL(开发环境): `http://127.0.0.1:8000`
- 启动命令: `uvicorn backend.core.web.webAPI:app --reload`
- 交互式调试: 启动后访问 `http://127.0.0.1:8000/docs`
- 通信格式: 请求和响应均为 JSON `Content-Type: application/json`
- 时间格式: 统一为 UTC ISO 8601 字符串 例如 `2026-07-24T05:22:08.123456+00:00`

## 认证约定

登录成功后获得 `session_id` 之后所有需要登录的接口都必须携带请求头:

```
Authorization: Bearer <session_id>
```

认证失败统一返回 `401` 会话有效期 2 小时 前端收到 401 应清除本地 token 并跳转登录页

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

---

## 规划中接口(chat 路由 尚未实现)

以下接口均需要认证 只能访问属于当前登录用户的对话

### GET /conversations — 历史对话列表

响应 `200` 按最近更新排序:

```json
[
  {
    "conversation_id": "uuid",
    "user_id": "用户uuid",
    "title": "对话标题",
    "created_at": "...",
    "updated_at": "..."
  }
]
```

### POST /conversations — 新建对话

请求体(`title` 可省略 默认 "新对话"):

```json
{ "title": "线性代数问题" }
```

响应 `201`: 单个对话对象 结构同上

### PATCH /conversations/{conversation_id} — 重命名对话

请求体: `{ "title": "新标题" }` 成功响应 `204`

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

注意: 该接口内部调用模型推理 耗时较长 前端需要 loading 状态 后续可能改为流式返回

对话不存在或不属于当前用户: `404`
