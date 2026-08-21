# ESA 个人知识库前后端接口契约

本文档对应前端“个人知识库”页面。学生和教师共用同一组接口，数据必须按当前登录用户隔离。前端不传 `user_id`，后端只能从 Bearer Session 中解析用户身份。

## 1. 通用约定

- API 前缀：`/api`（下文路径省略该前缀）
- 认证：`Authorization: Bearer <session_id>`
- 时间：ISO 8601 UTC，例如 `2026-08-21T08:30:00Z`
- `progress`：`0.0` 到 `1.0` 的浮点数，不是百分数
- 文件、chunk、index 统计仅包含当前用户的个人知识库
- 删除文件后应异步删除对应 chunk 和向量索引，并更新汇总统计
- 同一文件是否按 SHA-256 去重由后端决定；若去重，仍返回正常快照并避免重复索引

构建状态枚举：

| 值 | 含义 |
| --- | --- |
| `idle` | 没有文件或尚未开始构建 |
| `queued` | 已进入构建队列 |
| `building` | 正在解析、切块或建立索引 |
| `ready` | 当前所有文件索引可用 |
| `failed` | 构建失败，`error` 给出可展示原因 |

## 2. 数据结构

### KnowledgeBaseFile

```json
{
  "id": "kb-file-uuid",
  "filename": "数据结构讲义.pdf",
  "media_type": "application/pdf",
  "size_bytes": 3291451,
  "status": "ready",
  "progress": 1.0,
  "chunk_count": 48,
  "index_count": 48,
  "uploaded_at": "2026-08-21T08:30:00Z",
  "error": null
}
```

### PersonalKnowledgeBase

所有返回快照的接口都使用以下完整结构：

```json
{
  "file_count": 2,
  "chunk_count": 76,
  "index_count": 76,
  "status": "building",
  "progress": 0.72,
  "updated_at": "2026-08-21T08:31:12Z",
  "error": null,
  "files": [
    {
      "id": "kb-file-uuid",
      "filename": "数据结构讲义.pdf",
      "media_type": "application/pdf",
      "size_bytes": 3291451,
      "status": "ready",
      "progress": 1.0,
      "chunk_count": 48,
      "index_count": 48,
      "uploaded_at": "2026-08-21T08:30:00Z",
      "error": null
    }
  ]
}
```

汇总 `progress` 建议按文件字节数或构建任务权重计算；只要构建结果稳定且单调递增即可。`index_count` 表示已成功写入且可检索的向量/索引条目数。

## 3. 获取知识库快照

```http
GET /me/knowledge-base
Authorization: Bearer <session_id>
```

成功：`200 OK`，返回 `PersonalKnowledgeBase`。没有文件时也返回 `200`：

```json
{
  "file_count": 0,
  "chunk_count": 0,
  "index_count": 0,
  "status": "idle",
  "progress": 0.0,
  "updated_at": null,
  "error": null,
  "files": []
}
```

前端在 `queued/building` 状态下每 2 秒调用一次该接口，直至 `ready/failed`。

## 4. 批量添加文件

```http
POST /me/knowledge-base/files
Authorization: Bearer <session_id>
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `files` | file[] | 是 | 同名字段出现多次，支持多选批量上传 |

前端允许：`pdf, doc, docx, ppt, pptx, xls, xlsx, csv, txt, md, json, png, jpg, jpeg, webp`。

建议后端限制：单文件不超过 200 MB；单次最多 20 个文件；同时校验扩展名、MIME 和文件魔数。上传接口只负责可靠保存并创建异步构建任务，不应等待整个 DocIR/RAG 流程完成。

成功：`202 Accepted`，返回第 2 节定义的完整 `PersonalKnowledgeBase`。新文件通常处于 `queued`，知识库汇总状态也应为 `queued` 或 `building`。返回中的 `files` 必须是完整文件列表，不能只返回本次新增文件，也不能在 `file_count > 0` 时返回空数组。

## 5. 获取原始文件用于预览

```http
GET /me/knowledge-base/files/{file_id}/content
Authorization: Bearer <session_id>
```

成功：`200 OK`，响应体为原始二进制文件，不是 JSON。

响应头要求：

```http
Content-Type: application/pdf
Content-Length: 3291451
Content-Disposition: inline; filename*=UTF-8''%E6%95%B0%E6%8D%AE%E7%BB%93%E6%9E%84.pdf
Cache-Control: private, max-age=300
X-Content-Type-Options: nosniff
```

必须校验 `file_id` 属于当前用户。前端使用该接口预览 PDF、图片和文本；其他格式显示“暂不支持在线预览”，但仍可下载原文件。

## 6. 删除文件

```http
DELETE /me/knowledge-base/files/{file_id}
Authorization: Bearer <session_id>
```

成功：`204 No Content`。重复删除允许返回 `204` 或 `404`，前端都按已删除处理。删除应覆盖：

- 原始文件
- DocIR 中间产物
- chunks
- 向量/index 条目
- 文件构建任务和错误记录

## 7. 重新构建整个知识库

```http
POST /me/knowledge-base/rebuild
Authorization: Bearer <session_id>
Content-Type: application/json
```

请求体为空。成功：`202 Accepted`，返回最新 `PersonalKnowledgeBase`，状态为 `queued` 或 `building`。重建应保持原始文件不变，只重建解析产物、chunks 和索引。

## 8. 错误响应

统一使用现有 FastAPI 错误结构：

```json
{
  "detail": "文件格式不受支持"
}
```

| HTTP 状态 | 场景 |
| --- | --- |
| `400` | 空文件列表、知识库状态不允许该操作 |
| `401` | Session 无效或过期 |
| `404` | 文件不存在或不属于当前用户 |
| `409` | 同一知识库已有互斥构建任务（也可幂等返回现有任务） |
| `413` | 单文件或批次总大小超限 |
| `415` | 文件格式/MIME 不支持 |
| `422` | multipart 字段或参数不合法 |
| `429` | 上传或重建频率超限 |
| `500` | 持久化或构建服务内部错误 |
| `503` | DocIR、向量库或任务队列不可用 |

## 9. 前端已实现的方法

位置：`frontend/lib/api/api_client.dart`

| 前端方法 | 后端接口 |
| --- | --- |
| `getPersonalKnowledgeBase()` | `GET /me/knowledge-base` |
| `uploadPersonalKnowledgeBaseFiles(files)` | `POST /me/knowledge-base/files` |
| `fetchPersonalKnowledgeBaseFile(file)` | `GET /me/knowledge-base/files/{id}/content` |
| `deletePersonalKnowledgeBaseFile(id)` | `DELETE /me/knowledge-base/files/{id}` |
| `rebuildPersonalKnowledgeBase()` | `POST /me/knowledge-base/rebuild` |

后端完成后不需要修改前端字段名或路径即可联调。
