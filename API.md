# ESA API 契约与路由目录

> 最后核对：2026-09-13，代码基线 `main@41cfff0`。
>
> 本文是人工导航，不复制全部 Pydantic 字段。精确请求体、响应体、枚举、必填项和状态码以运行中的 `/docs`、`/openapi.json`、`backend/core/web/routers/` 与 `backend/core/web/schemas.py` 为最终事实。

## 1. 基础约定

- 本地 Base URL：`http://127.0.0.1:51024/api`
- Flutter Web 默认 Base URL：同源 `/api`
- canonical 路径：所有业务 HTTP 路由均位于 `/api`
- 兼容路径：代码默认 `ESA_ENABLE_LEGACY_API_ROUTES=true`，会注册无 `/api` 别名但不写入 OpenAPI；新客户端不得依赖
- 认证：`Authorization: Bearer <session_id>`
- 时间：UTC ISO 8601
- 普通响应：JSON 或无响应体
- 流式响应：`text/event-stream`
- LSP：WebSocket `/api/lsp/{language}`

2026-09-13 由 `app.openapi()` 生成的目录包含 `119` 个 path、`148` 个 HTTP operation；LSP WebSocket 不计入 OpenAPI operation 数。

## 2. 错误与权限

FastAPI 业务错误通常使用：

```json
{ "detail": "可展示错误说明" }
```

| 状态码 | 当前语义 |
|---:|---|
| `400` | 业务输入不成立、验证码错误、状态迁移非法 |
| `401` | Bearer 缺失/无效/过期；用户不存在或已停用；登录失败 |
| `403` | 已认证但账号角色不允许进入该入口 |
| `404` | 资源不存在或不属于当前用户；避免泄露归属 |
| `409` | 名称/状态/revision/互斥任务冲突，或派生预览尚未就绪 |
| `413` | 请求或文件超过服务端限制 |
| `422` | Pydantic 请求校验失败 |
| `429` | 验证码或其他限流，可能带 `Retry-After` |
| `502` | 上游邮件/模型等依赖调用失败 |
| `503` | 条件性服务未配置或未启用 |

停用账号重新登录和复用旧 Session 的当前实现均返回 `401`，并撤销旧 Session。对应测试已在 `c485941` 与这一统一认证失败契约对齐。

## 3. 健康与内部指标

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 仅证明 HTTP 进程存活，不验证模型、Qdrant、MinerU 或邮件 |
| `GET` | `/internal/metrics` | JSON 运行指标；配置 Token 后需要内部鉴权 |
| `GET` | `/internal/metrics/personal-knowledge-base` | 个人知识库指标 |
| `GET` | `/internal/metrics/prometheus` | Prometheus 文本格式 |

## 4. 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/auth/email/send-code` | 发送注册验证码；邮件服务未配置时 `503` |
| `POST` | `/auth/register` | 邮箱验证码注册，角色为 `student` 或 `teacher` |
| `POST` | `/auth/login` | 用户名或邮箱登录，返回 Session |
| `POST` | `/auth/email/bind/send-code` | 已登录账号发送邮箱绑定验证码 |
| `POST` | `/auth/email/bind` | 绑定或更换邮箱 |
| `POST` | `/auth/logout` | 撤销当前 Session，`204` |
| `POST` | `/auth/change-password` | 修改密码并撤销该用户全部 Session，`204` |

登录请求最小示例：

```json
{ "username": "user@example.com", "password": "correct-password" }
```

后续请求头：

```text
Authorization: Bearer <session_id>
```

## 5. Workspace 与审批动作

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/workspaces` | 返回账号角色可用 Workspace、默认项和能力清单 |
| `GET` | `/me/agent-actions` | 列出当前用户待审批/历史动作 |
| `GET` | `/me/agent-actions/{action_id}` | 动作详情 |
| `POST` | `/me/agent-actions/{action_id}/approve` | 重新校验资源后批准并执行 |
| `POST` | `/me/agent-actions/{action_id}/reject` | 拒绝动作 |

## 6. 对话、消息与附件

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET/POST` | `/conversations` | 列表/创建；支持 Workspace、分组、科研项目绑定 |
| `GET/PATCH/DELETE` | `/conversations/{conversation_id}` | 详情、标题/置顶/分组更新、删除 |
| `GET` | `/conversations/{conversation_id}/messages` | 可见消息历史 |
| `POST` | `/conversations/{conversation_id}/messages` | 同步 Agent Turn |
| `POST` | `/conversations/{conversation_id}/messages/stream` | SSE Agent Turn |
| `POST` | `/conversations/{conversation_id}/code/execute` | 受控代码执行；沙箱不可用时明确失败 |
| `POST` | `/conversations/{conversation_id}/attachments` | multipart 上传源文件 |
| `POST` | `/conversations/{conversation_id}/attachments/{attachment_id}/prepare` | 幂等触发/等待解析 |
| `GET` | `/conversations/{conversation_id}/attachments/{attachment_id}/status` | `stored/parsing/ready/failed` |
| `GET` | `/conversations/{conversation_id}/attachments/{attachment_id}` | 下载源附件 |
| `DELETE` | `/conversations/{conversation_id}/attachments/{attachment_id}` | 删除附件与派生状态 |

消息请求可以携带本轮 `attachment_ids`、知识源选择、任务模式和修订目标。服务端在写入用户消息前完成资源归属和依赖可用性预检。

SSE 事件由 `backend/core/web/sse.py` 和前端 `ApiClient` 共同定义。客户端必须容忍心跳、思考增量、正文增量、工具状态、错误和完成事件，并在连接中断后保留已接收内容。

## 7. 对话分组

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET/POST` | `/groups` | 列表/创建 |
| `PUT` | `/groups/order` | 重排 |
| `PATCH/DELETE` | `/groups/{group_id}` | 重命名、置顶、指令/风格/项目绑定更新或删除 |

删除分组不会删除对话；对话回落到未分组。所有读写按当前用户隔离。

## 8. 偏好、Profile 与记忆

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET/PATCH` | `/me/preferences` | 回答风格、语调等偏好 |
| `GET/PATCH/DELETE` | `/me/profile` | Profile 读取、更新、清空 |
| `PATCH` | `/me/profile/explicit` | 用户显式画像字段 |
| `GET` | `/me/profile/sources` | 画像字段来源 |
| `DELETE` | `/me/profile/inferred/{field_key}` | 删除单个推断字段 |
| `GET` | `/me/profile/export` | 导出 Profile |
| `GET` | `/me/profile/stats` | 用户统计 |
| `GET/PATCH` | `/me/memory-settings` | 长期记忆开关与模式 |
| `GET/POST` | `/me/core-memories` | CoreMemory 列表/显式创建 |
| `PATCH/DELETE` | `/me/core-memories/{memory_id}` | 更新/遗忘 |
| `POST` | `/me/core-memories/{memory_id}/suppress` | 暂停召回 |
| `POST` | `/me/core-memories/{memory_id}/restore` | 恢复召回 |
| `GET` | `/me/core-memories/{memory_id}/versions` | 版本历史 |
| `POST` | `/me/core-memories/{memory_id}/versions/{revision}/restore` | 恢复历史版本 |
| `GET` | `/me/memory-candidates` | 推断候选列表 |
| `POST` | `/me/memory-candidates/{candidate_id}/accept` | 接受候选并事务写入 |
| `POST` | `/me/memory-candidates/{candidate_id}/reject` | 拒绝候选 |
| `GET/PUT` | `/me/memories` | 兼容层列表/写入 |
| `DELETE` | `/me/memories/{memory_key}` | 兼容层删除 |

## 9. 学习、课表与规划

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/me/learning/mastery` | 掌握度报告 |
| `GET` | `/me/learning/recommendations` | 练习建议 |
| `GET/POST` | `/me/learning/courses` | 个人课程列表/添加 |
| `GET` | `/me/learning/course-catalog` | 课程图谱目录 |
| `PATCH/DELETE` | `/me/learning/courses/{course_name}` | 绑定 canonical 课程/删除 |
| `GET` | `/me/learning/knowledge-map` | 课程知识地图 |
| `GET` | `/me/learning/knowledge-points/{kp_id}` | 知识点详情与证据摘要 |
| `GET` | `/me/learning/review-queue` | 复习队列 |
| `GET` | `/me/schedule` | 当前课表快照 |
| `POST` | `/me/schedule/tables` | 新建课表 |
| `PATCH/DELETE` | `/me/schedule/tables/{table_id}` | 重命名/删除 |
| `POST` | `/me/schedule/tables/{table_id}/activate` | 激活课表 |
| `PUT` | `/me/schedule/courses` | 保存课程 |
| `DELETE` | `/me/schedule/courses/{course_id}` | 删除课程 |
| `PUT` | `/me/schedule/settings` | 学期开始、教学周等设置 |
| `POST` | `/me/schedule/import` | 文件/结构化课表导入 |
| `POST` | `/me/schedule/import/hust/challenge` | 创建短期 HUST CAS challenge |
| `POST` | `/me/schedule/import/hust/complete` | 一次性完成登录、查询和导入 |
| `GET` | `/me/planner` | 目标与待办快照 |
| `POST` | `/me/planner/todos` | 新建待办 |
| `PATCH/DELETE` | `/me/planner/todos/{todo_id}` | 更新/删除待办 |
| `POST` | `/me/planner/goals` | 新建目标 |
| `PATCH/DELETE` | `/me/planner/goals/{goal_id}` | 更新/删除目标 |

## 10. 个人与公共知识库

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/me/knowledge-base` | 默认个人库兼容摘要 |
| `GET/POST` | `/me/knowledge-base/libraries` | 命名个人库列表/创建 |
| `GET` | `/me/knowledge-base/libraries/{knowledge_base_id}` | 指定个人库摘要 |
| `POST` | `/me/knowledge-base/files` | 上传到默认个人库 |
| `POST` | `/me/knowledge-base/libraries/{knowledge_base_id}/files` | 上传到指定个人库 |
| `GET` | `/me/knowledge-base/files/{file_id}/content` | 原文件读取；支持受控范围 |
| `GET` | `/me/knowledge-base/files/{file_id}/download` | 下载别名 |
| `GET` | `/me/knowledge-base/files/{file_id}/preview` | 受控预览派生物 |
| `DELETE` | `/me/knowledge-base/files/{file_id}` | 提交删除 mutation |
| `POST` | `/me/knowledge-base/rebuild` | 重建默认个人库 |
| `POST` | `/me/knowledge-base/libraries/{knowledge_base_id}/rebuild` | 重建指定个人库 |
| `GET` | `/knowledge-base/public/documents/{document_id}/content` | 读取已登记公共知识文档 |

个人库代码默认关闭；`.env.example` 为目标部署显式开启。前端不得从页面是否存在推断后端服务已就绪。

## 11. 科研项目与能力

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET/POST` | `/research/projects` | 项目列表/创建 |
| `GET/PATCH` | `/research/projects/{project_id}` | 详情/更新/归档 |
| `GET/PUT` | `/research/projects/{project_id}/profile` | 项目级 Agent 指令，revision 控制 |
| `GET/POST` | `/research/projects/{project_id}/frontier-jobs` | 前沿追踪列表/创建 |
| `GET` | `/research/frontier-jobs/{job_id}` | 追踪状态和结果 |
| `GET/POST` | `/research/projects/{project_id}/documents` | 文档列表/创建 |
| `GET/PATCH` | `/research/documents/{document_id}` | 当前版本/更新元数据 |
| `GET` | `/research/documents/{document_id}/versions` | 文档版本历史 |
| `POST` | `/research/documents/{document_id}/writing-jobs` | 大纲、综述、润色、格式检查任务 |
| `GET` | `/research/writing-jobs/{job_id}` | 写作任务状态 |
| `GET/POST` | `/research/projects/{project_id}/datasets` | 数据集列表/上传 |
| `GET` | `/research/datasets/{dataset_id}` | 数据画像 |
| `GET/POST` | `/research/datasets/{dataset_id}/analysis-jobs` | 分析任务列表/创建 |
| `GET` | `/research/analysis-jobs/{job_id}` | 分析结果 |

## 12. 教师端

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/teaching/overview` | 教学概览 |
| `GET/POST` | `/teaching/classes` | 班级列表/创建 |
| `GET` | `/teaching/classes/{class_id}` | 班级详情 |
| `GET` | `/teaching/classes/{class_id}/knowledge-points` | 班级 canonical course 完整知识点目录；来自课程知识图谱，不依赖班级已有证据；仅班级教师可读，不暴露学生数据 |
| `POST` | `/teaching/classes/{class_id}/invitations` | 按精确用户名邀请 |
| `DELETE` | `/teaching/classes/{class_id}/members/{student_id}` | 移除学生 |
| `POST` | `/teaching/classes/{class_id}/assignments` | 创建草稿作业 |
| `POST` | `/teaching/assignments/{assignment_id}/publish` | 发布作业 |
| `GET` | `/teaching/assignments/{assignment_id}/submissions` | 提交列表 |
| `POST` | `/teaching/assignments/{assignment_id}/analyze` | 批量 AI 分析 |
| `GET` | `/teaching/submissions/{submission_id}` | 提交、AI 建议与教师状态 |
| `POST` | `/teaching/submissions/{submission_id}/analyze` | 单份 AI 分析 |
| `POST` | `/teaching/submissions/{submission_id}/review` | 教师逐题复核 |
| `POST` | `/teaching/submissions/{submission_id}/publish-feedback` | 发布正式反馈并写学习证据 |
| `GET` | `/teaching/classes/{class_id}/dashboard` | 仅聚合已发布反馈 |
| `GET` | `/teaching/classes/{class_id}/students/{student_id}` | 受限学生教学证据详情 |

## 13. 学生教学端

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/student/classes` | 已加入/待处理班级 |
| `POST` | `/student/classes/join` | 兼容加入入口 |
| `POST` | `/student/invitations/{membership_id}/respond` | 接受或拒绝邀请 |
| `GET` | `/student/assignments` | 当前学生可见作业 |
| `GET` | `/student/assignments/{assignment_id}` | 作业详情；隐藏评分规则与未发布反馈 |
| `POST` | `/student/assignments/{assignment_id}/submissions` | 提交最新正式答案 |
| `GET` | `/student/submissions/{submission_id}` | 本人提交和已发布反馈 |

## 14. LSP WebSocket

```text
wss://<host>/api/lsp/<language>
```

连接后第一条消息携带现有 Session Token，由后端鉴权后再启动 stdio language server。C/C++ 使用 `clangd`，Python 使用 `pyright-langserver --stdio`。缺少可执行文件时只禁用对应语言，Monaco 保留本地编辑能力。详细部署见 `deploy/LSP.md`。

## 15. 修改接口时的维护流程

1. 修改 Router/Schema/Service。
2. 增加或更新契约测试。
3. 运行 `python -m pytest` 和目标前端测试。
4. 用 `from backend.core.web.webAPI import app; app.openapi()` 检查 path、operationId 和 Schema。
5. 更新本文的路由目录与特殊语义，不手工复制容易漂移的大段模型定义。
