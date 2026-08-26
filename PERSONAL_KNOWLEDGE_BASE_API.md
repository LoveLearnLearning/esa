# ESA 个人知识库前后端接口契约

本文档对应前端“个人知识库”页面。学生和教师共用同一组接口，数据必须按当前登录用户隔离。前端不传 `user_id`，后端只能从 Bearer Session 中解析用户身份。一个用户可以创建多个命名个人知识库；每轮对话至多选择其中一个，并可独立叠加系统公共知识库。

## 1. 通用约定

- API 前缀：`/api`（下文路径省略该前缀）
- 认证：`Authorization: Bearer <session_id>`
- 时间：ISO 8601 UTC，例如 `2026-08-21T08:30:00Z`
- `progress`：`0.0` 到 `1.0` 的浮点数，不是百分数
- 文件、chunk、index 统计仅包含当前用户指定的个人知识库
- 删除文件后应异步删除对应 chunk 和向量索引，并更新汇总统计
- 按“当前用户 + 具体个人知识库”范围做 SHA-256 去重；同一内容允许分别存在于知识库 A 和 B
- 同一知识库已有互斥上传或重建任务时统一返回 `409`
- 同一用户的上传、删除和重建按服务端 revision 顺序提交；不同用户可以并发处理

构建状态枚举：

| 值 | 含义 |
| --- | --- |
| `idle` | 没有文件或尚未开始构建 |
| `queued` | 已进入构建队列 |
| `building` | 正在解析、切块或建立索引 |
| `ready` | 当前所有文件索引可用 |
| `failed` | 构建失败，`error` 给出可展示原因 |

## 2. 数据结构

### PersonalKnowledgeBaseSummary

```json
{
  "id": "personal_kb_...",
  "name": "知识库 A",
  "file_count": 2,
  "chunk_count": 76,
  "index_count": 76,
  "updated_at": "2026-08-21T08:31:12Z"
}
```

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

汇总 `progress` 建议按文件字节数或构建任务权重计算；只要构建结果稳定且单调递增即可。`index_count` 表示已成功写入且当前可检索的 Qdrant Point 数；一个 Point 同时包含 Dense、BM25 Body 和 BM25 Heading 时仍计为 1。

## 3. 目录与知识库快照

```http
GET /me/knowledge-base/libraries
POST /me/knowledge-base/libraries
GET /me/knowledge-base/libraries/{knowledge_base_id}
```

目录 GET 返回 `PersonalKnowledgeBaseSummary[]`；首次访问会创建“默认知识库”。POST 请求
`{"name":"知识库 A"}` 并返回 `201`。名称在同一用户内不区分大小写且唯一。指定 ID
不存在或不属于当前用户统一返回 `404`。

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
旧路径 `/me/knowledge-base` 保留为默认知识库兼容入口。

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

MVP 前端和后端允许：`pdf, doc, docx, ppt, pptx, xls, xlsx, csv, txt, md, json, png, jpg, jpeg, webp`。Office、PDF 和图片按个人库解析配置进入 MinerU；`csv/txt/md/json` 可以使用受限原生解析器。后端仍须同时校验扩展名、MIME、内容特征和资源限制。

初始限制：单文件不超过 200 MB、单次最多 20 个文件、单批总大小不超过 1 GB、单用户最多 10 GB/1000 个文件。后端同时校验扩展名、MIME 和文件魔数。上传接口只负责可靠保存并创建异步构建任务，不应等待整个 DocIR/RAG 流程完成。

成功：`202 Accepted`，返回第 2 节定义的完整 `PersonalKnowledgeBase`。新文件通常处于 `queued`，知识库汇总状态也应为 `queued` 或 `building`。返回中的 `files` 必须是完整文件列表，不能只返回本次新增文件，也不能在 `file_count > 0` 时返回空数组。

命名知识库使用 `POST /me/knowledge-base/libraries/{knowledge_base_id}/files`；旧路径上传到
默认知识库。

## 5. 原文件、派生预览与下载

### 5.1 原文件流

```http
GET /me/knowledge-base/files/{file_id}/content
Authorization: Bearer <session_id>
```

成功：`200 OK`，响应体为原始二进制文件，不是 JSON。同时支持 `HEAD`、单段 `Range: bytes=...` 和 `If-Range`。合法 Range 返回 `206`；不可满足范围返回 `416` 并携带 `Content-Range: bytes */<size>`；多段或格式错误的 Range 返回 `400`。服务端从已经过所有权和路径校验的文件描述符按 64 KiB 分块发送，请求取消后关闭描述符。

响应头要求：

```http
Content-Type: application/pdf
Content-Length: 3291451
Content-Disposition: inline; filename*=UTF-8''%E6%95%B0%E6%8D%AE%E7%BB%93%E6%9E%84.pdf
Cache-Control: private, max-age=300
X-Content-Type-Options: nosniff
Content-Security-Policy: sandbox
Cross-Origin-Resource-Policy: same-origin
Accept-Ranges: bytes
ETag: "<source-sha256>"
```

必须校验 `file_id` 属于当前用户；不存在、属于其他用户、已 tombstone 或已进入用户清除流程均返回相同 `404`。持久化路径、文件大小、owner、权限或符号链接校验失败时返回不泄露路径的 `500`。

### 5.2 受控派生预览

```http
GET /me/knowledge-base/files/{file_id}/preview
Authorization: Bearer <session_id>
```

- 图片返回最长边不超过 1600 像素的 JPEG/PNG 缩略图，不把接近 200 MB 的原图送入客户端内存。
- TXT/Markdown/CSV/JSON 返回建库时生成、最多 512 KiB 的 UTF-8 文本预览。
- PDF 返回 MinerU/DocIR 提取的有界文本预览。
- Office 默认返回 MinerU/DocIR 文本预览；配置 `PERSONAL_KB_LIBREOFFICE_BIN` 后优先返回隔离转换并验证过的 PDF。转换不可用或失败会记录 warning 并安全降级为文本，不伪造 PDF。
- 派生物尚未生成返回 `409`；其他用户仍统一返回 `404`。
- Flutter 单项预览硬限制 8 MiB，LRU 总缓存限制 24 MiB；切换文件、取消请求和登出都会中止传输或清理缓存。

### 5.3 独立下载

```http
GET /me/knowledge-base/files/{file_id}/download
Authorization: Bearer <session_id>
```

下载接口复用同一所有权、HEAD、Range 和流式传输边界，但返回 `Content-Disposition: attachment`。客户端原件方法返回可取消的字节流，不再构造包含整份原文件的 `AttachmentContent.bodyBytes`。

## 6. 删除文件

```http
DELETE /me/knowledge-base/files/{file_id}
Authorization: Bearer <session_id>
```

成功：`204 No Content`。删除当前用户存在的文件返回 `204`；再次删除仍保留在数据库中的当前用户 tombstone 也返回 `204`。从未存在、tombstone 已完成清理或属于其他用户的 `file_id` 统一返回 `404`。

后端先同步写 tombstone 并从 GET 快照隐藏文件，再持久化异步清理任务。清理任务完成前不得删除其自身所需的文件记录、目标 revision 或错误状态。最终清理覆盖：

- 原始文件
- DocIR 中间产物
- chunks
- 向量/index 条目
- 文件构建任务和错误记录

物理删除并确认该文件 Point 数为 0 后，后端必须生成不含该数据的有效 Qdrant snapshot，并通过临时恢复或同等强度方式验证 snapshot 内也无法 count/query 到该文件；随后删除所有可能仍含该数据的旧 snapshot。删除隐私要求优先于常规 snapshot 保留数量。

## 7. 重新构建整个知识库

```http
POST /me/knowledge-base/rebuild
Authorization: Bearer <session_id>
Content-Type: application/json
```

请求体为空。成功：`202 Accepted`，返回最新 `PersonalKnowledgeBase`，状态为 `queued` 或 `building`。重建应保持原始文件不变，只重建解析产物、chunks 和索引。知识库没有文件时固定返回 `400`。
命名知识库入口为 `POST /me/knowledge-base/libraries/{knowledge_base_id}/rebuild`。

## 8. 错误响应

统一使用现有 FastAPI 错误结构：

```json
{
  "detail": "文件格式不受支持"
}
```

| HTTP 状态 | 场景 |
| --- | --- |
| `400` | `files` 字段存在但没有可用文件、文件为零字节，或空知识库执行 rebuild |
| `401` | Session 无效或过期 |
| `404` | 知识库/文件不存在或不属于当前用户 |
| `409` | 同一用户已有互斥上传或重建任务时再次 upload/rebuild |
| `413` | 单文件、批次或用户存储配额超限 |
| `415` | 文件格式/MIME 不支持 |
| `422` | 缺少必填 multipart `files` 字段，或其他请求结构/参数不合法 |
| `429` | 上传或重建频率超限 |
| `500` | 持久化或构建服务内部错误 |
| `503` | 个人知识库功能关闭，或 DocIR、向量库、任务队列等必需服务不可用 |

## 9. 前端已实现的方法

位置：`frontend/lib/api/api_client.dart`

| 前端方法 | 后端接口 |
| --- | --- |
| `listPersonalKnowledgeBases()` | `GET /me/knowledge-base/libraries` |
| `createPersonalKnowledgeBase(name)` | `POST /me/knowledge-base/libraries` |
| `getPersonalKnowledgeBase()` | `GET /me/knowledge-base` |
| `uploadPersonalKnowledgeBaseFiles(files)` | `POST /me/knowledge-base/files` |
| `fetchPersonalKnowledgeBaseFile(file)` | `GET /me/knowledge-base/files/{id}/content`；返回可取消字节流，可选择 download/Range |
| `fetchPersonalKnowledgeBasePreview(file)` | `GET /me/knowledge-base/files/{id}/preview`；仅收集有界派生物 |
| `deletePersonalKnowledgeBaseFile(id)` | `DELETE /me/knowledge-base/files/{id}` |
| `rebuildPersonalKnowledgeBase()` | `POST /me/knowledge-base/rebuild` |

`get/upload/rebuild` 方法可传 `knowledgeBaseId` 访问命名知识库。前端保留完整扩展名列表和 MIME 映射。文件点击调用受控 preview 接口而不是原文件 content 接口；原件 content/download 仅通过流式方法使用。桌面端和移动端 Widget 测试覆盖文本、PDF、图片、切换取消和失败路径。

## 10. 第二阶段 Evidence 定位约定

个人知识库检索结果的 Evidence 必须返回结构化 `locator`，不能让同一个字符串字段在不同格式下表达不同含义。统一包含 `schema_version` 和 `kind`，其余字段按格式确定：

| 来源格式 | `kind` | 必需定位字段 |
| --- | --- | --- |
| TXT | `text_lines` | 从 1 开始的 `start_line`、`end_line` |
| Markdown | `markdown_section` | `heading_path`、从 1 开始的行范围 |
| CSV | `csv_rows` | 从 1 开始的 `start_row`、`end_row`、`columns` |
| JSON | `json_pointer` | RFC 6901 `pointer` |
| PDF | `pdf_region` | 从 1 开始的 `page`、归一化到 `0..1` 的 `bbox` |
| 图片 | `image_region` | `asset_id`、OCR 区域、归一化 `bbox` |
| Office | `mineru_section` | MinerU `group_id`、`section_path`；可选页、幻灯片、工作表或单元格范围 |

locator schema 版本、格式映射规则和解析器版本必须进入建库流水线指纹；这些规则不兼容变更时，需要重建对应 Chunk 和索引。
