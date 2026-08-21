# ESA 个人知识库后端实现清单

本文档把 [PERSONAL_KNOWLEDGE_BASE_API.md](PERSONAL_KNOWLEDGE_BASE_API.md) 转换为可实施、可测试、可验收的任务清单。MVP 的 4 个管理接口、聊天 Agent 个人资料检索闭环，以及后续原文件/在线预览阶段均已进入同一验收记录。

部署事实和路径基线以 [SUPERCOMPUTER_ENVIRONMENT.md](SUPERCOMPUTER_ENVIRONMENT.md) 为准。该文档记录的是 2026-08-16 至 2026-08-17 的宿主机实测历史值；每个新 Slurm Job 仍须在宿主机执行只读检查，不能把历史 PID、GPU 分配或 `/tmp` 路径当作当前事实。

## 1. 范围与结论

### 1.1 当前必须交付

- [x] `GET /api/me/knowledge-base`
- [x] `POST /api/me/knowledge-base/files`
- [x] `DELETE /api/me/knowledge-base/files/{file_id}`
- [x] `POST /api/me/knowledge-base/rebuild`
- [x] 原始文件的用户隔离持久化
- [x] DocIR 解析、Chunk 构建、Embedding 和 Qdrant 写入的异步流水线
- [x] 构建任务、进度、统计和错误的持久化
- [x] 删除和重建的一致性、恢复与清理

### 1.2 第二阶段交付

- [x] 给 Agent 增加用户身份绑定的个人知识库检索能力
- [x] 返回可回查的 Evidence、文档名和定位信息
- [x] 明确个人库与 ESA 全局教材库的召回、融合和降级策略
- [x] 验证任何检索路径都不能读取其他用户的 Point

### 1.3 在线预览阶段（已实现）

- [x] `GET /api/me/knowledge-base/files/{file_id}/content`
- [x] PDF、图片、文本和 Office 在线预览
- [x] HEAD/Range、流式预览、缩略图和 Office 转 PDF
- [x] 前端 `AttachmentContent.bodyBytes` 的大文件内存问题改造

页面只请求受控 preview 派生物，不因点击而全量读取原件。后端不返回伪造文件；未就绪明确返回 `409`。

- [x] 前端文件点击调用有界 `fetchPersonalKnowledgeBasePreview()`，不直接调用原件流。
- [x] 更新桌面端和移动端 Widget 测试，覆盖正文、PDF/图片视图和切换取消。
- [x] content/download API client 返回可取消字节流，不构造整份原件 `bodyBytes`。

### 1.4 不在本次范围

- 课程“知识地图”及其 YAML 数据；它与文档 RAG 是不同系统。
- 把聊天附件自动永久加入个人知识库。
- 管理员查看或编辑所有用户的知识库。
- 文件在线协作编辑、版本对比和共享知识库。
- 在当前前端之外新增独立搜索调试页面或搜索 HTTP API。

## 2. 已讨论的推荐架构

### 2.1 用户与知识库模型

- 每个用户只有一个个人知识库，学生端和教师端共用。
- `user_id` 只从 Bearer Session 解析，任何请求体、查询参数和路径都不得接受 `user_id`。
- 文件元数据、任务状态、活跃索引代次和统计存入现有主 SQLite 数据库；不为个人库另建第二个 SQLite。
- 原始文件和 DocIR/Chunk 工件写入可配置的个人知识库根目录，不提交 Git。
- Qdrant 使用一个共享的个人知识库 collection，不按用户创建 collection。
- 每个 Qdrant Point 必须携带 `user_id`、`file_id`、`kb_generation_id` 和可见性字段。
- 所有 count、query、delete 和 payload 更新必须在索引适配器底层强制加入用户过滤条件。

选择共享 collection 的原因：避免用户数增长时产生大量 collection，同时便于统一模型、向量维度、备份和监控。代价是多租户过滤必须成为不可绕过的安全边界。

### 2.2 构建与切换

- 上传请求只保存文件、写元数据并创建任务，返回 `202`，不等待 DocIR/RAG 完成。
- 前端文件/知识库状态使用 `idle|queued|building|ready|failed`；内部 Job 状态独立使用 `queued|running|succeeded|failed|cancel_requested|cancelled`。
- 同一用户的上传、删除和重建按 `target_revision` 严格顺序提交；同一用户已有上传或重建任务时，再次上传或重建统一返回 `409`。删除仍可同步写 tombstone，并由有序 cleanup job 接在当前 revision 之后执行。
- 不同用户可以并发执行解析、Chunk 和 Embedding；写入共享 Qdrant collection 的短提交阶段按用户有序，并与全局 snapshot/collection 维护锁协调。
- 普通新增文件可以增量处理，但新 Point 在文件完整写入并校验前不可检索。
- `generation_id` 表示一次全量 rebuild 代次，不是不可变的完整文件集合指纹；普通增量上传写入当前 active generation，并记录独立的 `ingestion_revision`。
- 重建使用新的 staging generation；完整校验后原子更新 SQLite 中的 `active_generation_id`。
- 重建失败时继续使用旧的活跃 generation，不把整个知识库切到失败状态。
- 新 generation 激活后，再异步回收旧 generation，不能先删旧索引。

### 2.3 任务执行方式

- MVP 固定使用“SQLite 持久任务 + 进程内 `asyncio.Queue` 唤醒器”，不接入外部任务系统。
- 任务本身必须持久化，进程重启后将内部 `running` 恢复为 `queued` 并重新领取。
- `claim_job` 必须使用条件更新，保证多个进程不会同时执行同一任务。
- 生产启动固定为一个 Uvicorn worker 且关闭 reload；否则每个进程都会启动自己的个人库 worker。
- MinerU、Chunk、Embedding、Qdrant 等阶段边界必须检查 `cancel_requested`，不能把取消 `asyncio.to_thread()` 误认为底层同步工作已经停止。
- 在线检索和后台建库共享一个进程级 Embedding provider 及全局并发上限，不能每个任务加载一份模型。
- 当前拓扑固定为“每个 Slurm Job 只有一个活动 ESA 后端实例”，不设计多后端节点同时读写。
- “单机”只描述活动服务实例数量，不表示可以把持久数据放到节点 `/tmp`；Job 结束后节点临时目录会消失。
- 原文件、SQLite、DocIR/Chunk 工件和 Qdrant 备份必须放持久挂载；节点本地 ext4 只用于临时工作目录和 Qdrant 活动目录。

### 2.4 Agent 检索建议

第一阶段不修改冻结的全局 `retrieve_knowledge` B2 契约。第二阶段优先新增上下文感知的 `retrieve_personal_knowledge`：

- 工具参数只包含 `query`、`top_k` 等检索参数，不包含 `user_id`。
- 执行器从 `ToolExecutionContext.user_id` 获取用户身份。
- 个人库为空、未就绪或暂时不可用时返回明确空结果/降级信息，不能退化成无用户过滤的查询。
- 全局库和个人库先保持两个工具，待有检索评测后再决定是否做自动联邦融合。

这样可以保持现有全局知识库契约、训练数据和行为稳定，也能让个人资料的授权边界更清晰。

### 2.5 超算目录与进程布局

当前按“一次 Slurm Job 运行一个 ESA 后端、一个 Qdrant 进程”实施，不引入多后端写入协调。推荐目录布局如下；其中持久根目录只是候选值，正式配置前必须在当次 Job 的宿主机环境重新检查容量、挂载和写权限：

```text
/persist_data/home/chenxuzhao/esa-personal-knowledge-base/
  files/                 # 原始文件，权威数据
  artifacts/             # DocIR、Chunk、manifest，权威或可重建工件
  qdrant-snapshots/      # 个人 collection 的持久快照

${SLURM_TMPDIR:-/tmp}/esa-${SLURM_JOB_ID}/personal-kb/
  work/                  # 上传、解析和构建临时目录
  qdrant-storage/        # 当前 Job 的 Qdrant 活动 storage
  qdrant-snapshots/      # Qdrant 创建/恢复快照时的本地工作目录
  qdrant-temp/
```

- [ ] 首选 `PERSONAL_KB_ROOT=/persist_data/home/chenxuzhao/esa-personal-knowledge-base`；如当次宿主机检查不满足容量或写权限，再改用 `/remote_dir` 下经确认的持久目录。
- [ ] 启动前在宿主机只读核对 `findmnt -T /persist_data/home/chenxuzhao`、`df -hT /persist_data/home/chenxuzhao` 和 `test -d/-r/-w`；历史记录的约 515 GB 可用空间不能当作当前保证。
- [ ] 个人库沿用现有主 `user.db`；确认其当前路径跨 Job 持久，并把主数据库备份纳入部署要求。若以后迁往 `/persist_data`，迁移整个主数据库而不是拆出个人库数据库。
- [x] 不把原文件、主 SQLite、DocIR/Chunk manifest 或唯一一份 Qdrant 快照放在 `$SLURM_TMPDIR`/`/tmp`。
- [x] Qdrant 活动 storage 继续放节点本地 ext4，避免把 Qdrant 活动数据库直接放 NFS；持久层只保存可恢复的 snapshot。
- [x] 主 SQLite 位于 NFS 时默认使用 rollback journal（如 `DELETE`/`TRUNCATE`），不要未经宿主机锁与故障测试直接启用 WAL；保持单一活动写入实例。
- [ ] 持久根目录和用户目录权限设为 `0700`，文件、SQLite 备份和 snapshot 设为 `0600`，启动时检查实际权限与 owner。
- [x] 从本地 ext4 向 NFS 提交文件或工件时，先复制到目标持久目录内的 `.partial`，完成校验和 `fsync` 后再在同一文件系统内原子 rename；不能跨文件系统直接 `os.replace()`。
- [x] 文件、数据库事务和索引快照的提交顺序要有恢复记录；Job 被抢占后能判断应该恢复快照、补做快照，还是从权威工件重建。

## 3. 需要新增或扩展的模块

建议文件位置如下，实际命名可以按实现调整：

```text
backend/core/stores/personal_knowledge_base_store.py
backend/core/services/personal_knowledge_base_service.py
backend/core/web/routers/personal_knowledge_base.py
backend/agent/rag/indexes/personal_qdrant.py
backend/agent/rag/personal/ingestion.py
backend/agent/rag/personal/retrieval.py
backend/tests/test_personal_knowledge_base_api.py
backend/agent/rag/tests/test_personal_knowledge_base_index.py
```

复用边界：

- 复用 `UserAttachmentStore` 的流式写入、SHA-256、临时文件和原子 rename 思路，但不要复用它的 `conversation_id` 目录模型。
- 复用 `MultimodalIngestionService` 下层的 MinerU/DocIR、视觉补全、Chunk 和 Embedding 组件。
- 不直接复用 `MultimodalSessionService`；它是会话级、进程内状态，生命周期和个人知识库不一致。
- 不直接复用当前 `QdrantIndex` 的代次校验；它假设 collection 只含一个 generation，会拒绝多用户混合 Point。
- 复用 `ResearchDataService`/`ResearchWritingService` 的持久队列、领取任务、失败记录和重启恢复模式。

## 4. 配置清单

- [x] 增加 `PERSONAL_KB_ENABLED`，默认关闭或按部署策略明确默认值。
- [x] 增加 `PERSONAL_KB_ROOT`，指向不进 Git 的持久目录。
- [x] 增加 `PERSONAL_KB_MAX_FILE_BYTES=209715200`（200 MB）。
- [x] 增加 `PERSONAL_KB_MAX_BATCH_FILES=20`。
- [x] 增加 `PERSONAL_KB_MAX_BATCH_BYTES=1073741824`（1 GB），不能允许单批达到 20 × 200 MB。
- [x] 增加 `PERSONAL_KB_MAX_USER_BYTES=10737418240`（10 GB）和 `PERSONAL_KB_MAX_USER_FILES=1000`。
- [x] 增加 `PERSONAL_KB_QDRANT_COLLECTION`，不要与冻结的全局教材 collection 混用。
- [x] 增加个人 Qdrant snapshot 的持久目录、启动恢复策略、最大 10 分钟合并延迟和保留最近 3 份有效快照的配置。
- [x] 增加当前 Job 临时根目录，默认取 `$SLURM_TMPDIR`，仅在未提供时回退 `/tmp`。
- [x] 增加个人库解析配置，不用聊天附件的 `MM_ENABLED` 作为个人库是否可建库的开关。
- [x] 增加 `PERSONAL_KB_VISION_ENABLED`；MVP 默认允许关闭，视觉补全失败按可诊断降级处理。
- [x] 增加 worker 数量、Embedding 并发、任务超时和最大重试次数。
- [x] 增加解析展开大小、最大页数、最大图片数等资源限制。
- [x] 在 `.env.example` 中说明所有配置和运行工件路径。
- [x] 在启动校验中检查启用时所需目录、Qdrant、Embedding 和 DocIR 配置。

推荐共享全局 RAG 的 Embedding 模型配置与维度，但个人库使用独立 Qdrant collection，避免改变冻结的全局部署身份。

超算当前基线为 Qdrant `1.18.3`、`127.0.0.1:6333`、Embedding 模型 `/remote_dir/home/chenxuzhao/models/Qwen3-Embedding-4B`、维度 `2560`。这些值应作为部署默认参考而不是写死在代码中，启动时仍要校验模型路径、向量维度和服务可达性。

## 5. 数据库与状态模型

### 5.1 数据表

- [x] 增加版本化 migration，禁止只在 Store 初始化时静默建表。
- [x] `personal_knowledge_bases`
  - `user_id` 主键及用户外键
  - `status`、`progress`、`error`
  - `active_generation_id`、`building_generation_id`
  - `desired_revision`、`indexed_revision`
  - `file_count`、`chunk_count`、`index_count`
  - `created_at`、`updated_at`
- [x] `personal_knowledge_base_files`
  - `file_id` 主键、`user_id` 外键
  - 原始文件名、规范化后缀、MIME、字节数、SHA-256
  - 原始文件路径、DocIR/Chunk manifest 路径
  - `ingestion_revision`、`indexed_revision`
  - `status`、`progress`、`chunk_count`、`index_count`、`error`
  - `uploaded_at`、`updated_at`
  - 删除/取消状态或 tombstone 字段
- [x] `personal_knowledge_base_jobs`
  - `job_id`、`user_id`、`job_type`
  - 内部 `status`、`progress`、`generation_id`、`target_revision`
  - 目标文件 ID 列表或稳定 JSON payload
  - 尝试次数、错误、创建/开始/完成/更新时间
- [x] `personal_knowledge_base_generations`
  - `generation_id`、`user_id`、状态
  - rebuild 时的输入清单快照及 collection/embedding/chunk 配置指纹
  - chunk/index 数量
  - 创建、激活和回收时间
- [x] `personal_knowledge_base_collection_state`（单例行或等价全局状态）
  - 个人共享 collection 名称
  - `qdrant_mutation_seq`：已验证提交的最新全局变更高水位，只增不减
  - `snapshot_mutation_seq`：最新有效 snapshot 已覆盖的全局变更序号
  - snapshot dirty 标记、更新时间和最近错误
- [x] `personal_knowledge_base_mutations`（也可由具备同等字段和保留规则的 durable outbox 实现）
  - mutation ID、`user_id`、`target_revision`、操作类型和幂等 payload
  - 成功提交后分配的全局 `qdrant_mutation_seq`，并以唯一约束防止重复分配
  - 状态、尝试次数、错误和创建/应用时间
  - 至少保留到所有仍允许使用的有效 snapshot 都不再需要该记录；恢复旧 snapshot 时用它重放所有更大的 sequence
- [x] `personal_knowledge_base_snapshots` 或等价 manifest 记录：snapshot 文件、SHA-256、collection、Point 数、`qdrant_mutation_seq`、模型/索引指纹、locator schema 版本和创建时间。

### 5.2 约束与查询

- [x] 所有按 `file_id`、`job_id` 和 `generation_id` 的读写同时包含 `user_id` 条件。
- [x] 给 `(user_id, status)`、`(user_id, uploaded_at)`、`(user_id, sha256)` 建索引。
- [x] 通过数据库约束或条件更新保证每用户同一时刻只有一个 `running` mutation job；允许按 revision 排列多个 `queued` job，以便删除 tombstone 后把 cleanup 接到正在运行任务之后。
- [x] 同一用户只能领取最小的未完成 `target_revision`；低 revision 未成功、取消或完成恢复前，不得提交更高 revision。
- [x] 全局 collection 状态只有一行，并通过事务/条件更新单调推进 mutation sequence，禁止用任一用户的 revision 代替共享 collection 的 snapshot 进度。
- [x] 前端资源状态和内部 Job 状态分别通过 CHECK 约束限制，不能混用 `building/ready` 与 `running/succeeded`。
- [x] `file_count` 必须等于返回 `files` 数量；快照不能现场调用 Qdrant count。
- [x] `index_count` 明确定义为“已成功写入且当前可检索的 Qdrant Point 数”，不是 Dense 与两条 Sparse 向量数量之和。
- [x] 文件默认按 `uploaded_at DESC, file_id` 稳定排序。
- [x] 错误字段限制长度并保存可展示信息；完整堆栈只进入服务端日志。

### 5.3 去重决策

MVP 固定按用户内 SHA-256 去重：

- [x] 同一用户重复上传相同内容时返回已有文件，不重复解析和写向量。
- [x] 不跨用户复用逻辑文件记录或暴露命中信息。
- [x] 即使底层以后做内容寻址去重，授权、元数据和删除引用计数仍按用户隔离。
- [x] 相同内容即使文件名不同，也只保留首次上传的逻辑条目和文件名。
- [x] 在数据库中使用用户范围的唯一约束或条件唯一索引消除并发重复上传；批次内部重复文件采用同一语义。

## 6. 文件持久化与校验

- [x] 路径只使用服务端生成的 UUID，不直接把用户名或原始文件名作为目录。
- [x] 文件名先去除目录部分，拒绝 NUL、控制字符和超长名称。
- [x] 流式按块读取，同时计算 SHA-256 和字节数。
- [x] Starlette multipart spool 和解析临时文件显式使用 `$SLURM_TMPDIR`；反向代理和 ASGI 层在完整解析请求前限制请求体大小。
- [x] 持久原文件先写最终目标目录内的 `.uploading`，校验、`fsync` 后在同一 NFS 文件系统内原子 rename。
- [x] 批量上传先完成全部验证和可靠保存，再在一个数据库事务中创建文件与任务。
- [x] 批次中任一文件失败时清理本批临时文件，避免前端收到不明确的部分成功。
- [x] 接收上传前检查用户文件数/总字节配额、批次限制、持久盘和 `$SLURM_TMPDIR` 安全余量，并用预留记录避免并发超卖容量。
- [x] 同时校验扩展名、实际内容和安全的 MIME 推断，不能信任客户端 `Content-Type`。
- [x] Office 压缩包需要限制解压总大小、文件数量和压缩比，防止 zip bomb。
- [x] 图片需要限制像素数；PDF 需要限制页数和解析资源。
- [x] 原始文件目录和生成工件目录分离，删除时按精确目录清理。
- [x] 路径解析后必须 `relative_to(root)`，阻止路径穿越和符号链接逃逸。
- [x] Job 启动时扫描并按保留期清理无数据库记录的 `.uploading/.partial` 和孤立临时目录；不能误删仍在运行任务的路径。

前端当前 `_mimeFor` 不会为 `doc`、`ppt`、`xls`、`csv`、`txt`、`md`、`json` 生成精确 MIME，这些文件可能以 `application/octet-stream` 上传。后端不能仅因该 MIME 就拒绝合法文件，应结合后缀、魔数和受限文本探测；同时补齐前端 MIME 映射。

## 7. DocIR、Chunk 与索引流水线

### 7.1 摄取

- [x] 为每个文件创建确定性的工作目录和运行 manifest。
- [x] 个人库拥有独立的解析开关、MinerU 地址和生命周期检查，不能因为聊天附件配置 `MM_ENABLED=false` 就静默跳过解析或稳定失败。
- [x] 需要 MinerU 的格式在任务开始前检查 `127.0.0.1:51026`（或配置地址）是否可用；不可用时给出明确、可重试的任务错误。
- [x] 只复用 `MultimodalIngestionService` 下层组件；个人库所有成功文件都强制生成 Chunk/Index，不使用聊天附件的小文档 `direct` 路由。
- [x] 复用全局 RAG 进程所有的同一个 Embedding provider，并保持 backend、模型、查询指令、维度和配置指纹完全一致；在线查询和后台文档 Embedding 共用有界并发。
- [x] 调用现有 MinerU/DocIR 适配器并保留解析版本、来源 SHA-256 和质量问题。
- [x] 对无需 MinerU 的纯文本/Markdown/JSON/CSV 选择明确的原生解析器路径。
- [x] MVP 支持当前前端完整列表：`pdf, doc, docx, ppt, pptx, xls, xlsx, csv, txt, md, json, png, jpg, jpeg, webp`。
- [x] `doc/ppt/xls` 与现代 Office 一样进入 MinerU 链路；补齐旧版 Office MIME、OLE 内容识别、超时和资源限制，不能仅凭扩展名信任输入。
- [x] MinerU 按格式属于必需依赖；VLM 视觉补全允许关闭或失败降级，并记录 provider/config 指纹和 warning。若最终没有任何可检索文本，则任务明确失败。
- [x] DocIR 输出通过现有 ChunkBuilder 生成 ChunkCollection。
- [x] 生成工件采用临时目录加原子提交，失败工件不能被标记为 ready。
- [x] Evidence locator 使用带 `kind` 和 `schema_version` 的结构化对象，不用一个含义随格式变化的自由文本字段：
  - TXT：`text_lines`，记录从 1 开始的 `start_line/end_line`
  - Markdown：`markdown_section`，记录 `heading_path` 和从 1 开始的行范围
  - CSV：`csv_rows`，记录从 1 开始的 `start_row/end_row` 和 `columns`
  - JSON：`json_pointer`，记录符合 RFC 6901 的 `pointer`
  - PDF：`pdf_region`，记录从 1 开始的 `page` 和归一化到 `0..1` 的 `bbox`
  - 图片：`image_region`，记录 `asset_id`、OCR 区域及归一化 `bbox`
  - Office：`mineru_section`，记录 MinerU 稳定 `group_id/section_path`，并在可用时附带页、幻灯片、工作表或单元格范围
- [x] locator schema 版本、格式到 locator 的映射规则和解析器版本进入流水线指纹；规则变化时不得复用不兼容的 Chunk/索引工件。

现有 `SUPPORTED_SOURCE_SUFFIXES` 只覆盖 PDF、DOCX、PPTX、XLSX 和常见图片。实现时把 `doc`、`ppt`、`xls` 接入 MinerU，并给 `csv`、`txt`、`md`、`json` 增加受限原生解析器。每种格式都必须从真实源文件跑通 MinerU/原生解析、DocIR、Chunk 和索引，不能只扩大后缀 allowlist。

### 7.2 Qdrant 多租户适配器

- [x] 新建租户感知适配器，不改变冻结全局库的 `QdrantIndex` 行为。
- [x] Point ID 至少绑定 `user_id + generation_id + chunk_id`，防止相同 Chunk 在不同用户间覆盖。
- [x] payload 至少包含：
  - `scope = personal`
  - `user_id`
  - `file_id`
  - `kb_generation_id`
  - `ingestion_revision`
  - `chunk_id`
  - `visible`
  - 原 Chunk/Evidence payload
- [x] 为 `user_id`、`file_id`、`kb_generation_id`、`visible` 创建 payload index。
- [x] Dense、BM25 Body、BM25 Heading 查询统一合并以下过滤：
  - 当前 `user_id`
  - 当前活跃 generation
  - `visible = true`
  - 可选 content role
- [x] count、删除、清理和 verify 使用同一租户过滤构造器。
- [x] 禁止提供无 `user_id` 的个人库 query/delete 公共方法。
- [x] 文件写入完成并验证数量前保持 `visible = false`，提交后再切换可见性。
- [x] 删除时先令 Point 不可见，再异步删除，避免删除窗口继续被检索。

### 7.3 代次、revision 与原子性

- [x] generation ID 绑定用户、全量 rebuild 任务、Chunk 配置、Embedding 指纹和索引配置；普通增量上传不创建新 generation。
- [x] 每次上传、删除或 rebuild 在 SQLite 事务中递增 `desired_revision`，并创建带 `target_revision` 的幂等 Job/outbox。
- [x] 每个用户的 mutation job 按 `target_revision` 顺序执行；解析和 Embedding 可以跨用户并发，但同一用户不得越过尚未完成的低 revision 提交可见状态。
- [x] 普通上传 Point 使用当前 active generation 和文件 `ingestion_revision`；完成索引校验后推进文件及知识库 `indexed_revision`。
- [x] 重建写入 staging generation，不能覆盖当前 active generation。
- [x] 校验 Point 数、向量维度和 generation 数量后，在 SQLite 事务中切换 active generation。
- [x] 查询先读取用户 active generation，再带该 generation 查询 Qdrant。
- [x] SQLite 切换成功但旧 generation 清理失败时记录待清理任务，不回滚活跃代次。
- [x] Qdrant 写入失败时保留旧 generation，标记新 generation/job failed。
- [x] SQLite 和原始文件是权威数据；DocIR、Chunk、Qdrant 和 snapshot 均视为可核验、可重建的派生状态。
- [x] 明确定义跨 SQLite/Qdrant 的提交和崩溃恢复顺序；启动 reconcile 根据 `desired_revision` 与 `indexed_revision` 补写、隐藏或重建，不能依赖不存在的跨系统事务。
- [x] 每次可见性切换、物理删除、generation 切换或清理完成并通过 Qdrant 校验后，在短时全局 mutation 锁内单调推进 `qdrant_mutation_seq`；幂等重放不得重复推进序号。
- [x] Qdrant 变更与 sequence 更新之间发生崩溃时，通过 mutation journal/outbox 幂等重放并重新校验；不能假设 SQLite 与 Qdrant 存在跨系统事务。

### 7.4 Qdrant 持久化与跨 Job 恢复

- [x] 个人库使用独立 collection，例如 `esa_personal_kb_qwen3_4b`，不得写入全局只读 collection `esa_all_pdfs_qwen3_4b_20260816`。
- [x] 上传、删除或重建成功并切换可见状态后，将“需要快照”持久化到全局 collection 状态；快照创建失败时保持 dirty 状态和旧 `snapshot_mutation_seq`，但不否定已经持久化的 SQLite/原文件。
- [x] 连续变更防抖/合并为周期 snapshot，最大延迟 10 分钟，并在正常 shutdown 前尽力完成最后一次快照；snapshot 是恢复加速手段，不是原文件持久成功的前置条件。
- [x] snapshot/restore/collection 维护全局 single-flight；创建 snapshot 时，仅在 Qdrant 本地一致性快照生成并绑定当前 mutation sequence 的临界区持有全局 mutation 锁，随后复制 NFS、算 checksum 等耗时工作在锁外完成。解析和 Embedding 可继续运行，但不得在该临界区中途提交 collection 变更。
- [x] 快照先由本地 Qdrant 创建和校验，再复制为持久目录内的 `.partial` 文件，完成 SHA-256、Point 数、指纹校验和 `fsync` 后在同一持久文件系统内原子 rename；manifest 记录该快照覆盖的全局 `qdrant_mutation_seq`，成功后推进 `snapshot_mutation_seq`。
- [x] 保留最近 3 份有效 snapshot；新 snapshot 验证成功后再删除超出保留数的旧文件、checksum 和 manifest。
- [x] 每个 Job 启动时先恢复个人 collection 的最新有效快照，再启动个人库 worker 和对外 readiness。
- [x] 没有快照或快照损坏时，从持久原文件、兼容的 DocIR/Chunk manifest 和 generation 记录重建个人 collection；不得错误复用全局快照。
- [x] 恢复 snapshot 后，以 manifest 的全局 `qdrant_mutation_seq` 初始化本次 Job 的 restore cursor，按 sequence 顺序重放 mutation journal/outbox 直到 SQLite 的全局高水位，再逐用户 reconcile `desired_revision/indexed_revision`；全局高水位本身不得因恢复旧快照而回退，对外 readiness 在追平前保持 false。
- [x] journal/outbox 至少保留“当前仍保留的最旧有效 snapshot”之后的全部 mutation；只有删除了对应旧 snapshot、确认任何允许的恢复起点都不再需要这些记录后，才能压缩。不得因普通任务清理破坏 snapshot 后增量恢复链。
- [x] 扩展现有启动/恢复脚本，使其能分别恢复全局 collection 和个人 collection；当前只恢复单个全局 snapshot 的行为不够。
- [x] 删除个人文件或用户后，物理删除并以租户过滤确认 Point 数为 0，再生成覆盖该删除 mutation sequence 的有效干净 snapshot；随后删除所有序号早于该删除 mutation、可能仍含被删数据的 snapshot/checksum/manifest。删除隐私要求优先于“保留 3 份”，因此暂时只剩 1 份有效 snapshot 可以接受。
- [x] “干净 snapshot”必须针对 snapshot 内容验收：恢复到临时验证 collection（或使用 Qdrant 提供的同等强度验证）后，以 `user_id + file_id` count/query 均为 0；只检查生成前的在线 collection 不算完成。
- [x] Qdrant 启用每个 Job 的随机 API key。若 Slurm 节点不是独占的，使用动态端口并校验进程归属；固定无认证的 `127.0.0.1:6333` 只允许本机开发。
- [ ] 演练 Job 强制结束、最新快照损坏、快照生成中断和 SQLite 已提交但 snapshot 未完成四种恢复场景。

## 8. 异步任务与并发

- [x] `start()` 把内部 `running` 任务恢复为 `queued` 并重新提交；不得沿用其他 Service 的 `recover_interrupted=False`。
- [x] `stop()` 停止领取新任务，把活动任务推进到检查点或持久化为可恢复状态；不能仅取消外层 asyncio task。
- [x] `claim_job()` 使用 `UPDATE ... WHERE status='queued'` 原子领取。
- [x] claim 条件同时保证该 Job 是该用户最小的未完成 `target_revision`；失败重试、取消和恢复不得造成 revision 越序。
- [x] 每个阶段持久化进度：保存、解析、切块、Embedding、索引、校验、提交。
- [x] 聚合进度稳定、单调递增且范围为 `0.0..1.0`。
- [x] GET 快照只读 SQLite，不在每 2 秒轮询时连接模型或扫描 Qdrant。
- [x] 上传/重建并发策略固定为每用户一个互斥任务，冲突统一返回 `409`；不在 MVP 返回已有任务快照。
- [x] 不同用户可并发解析/Embedding；snapshot、restore、collection 创建/删除和共享 collection mutation 提交使用一个全局 single-flight 锁，锁外不得直接改 Qdrant 可见状态。
- [x] 删除与正在构建同一文件冲突时，先设置取消/tombstone，worker 在阶段边界检查。
- [x] 重试必须幂等；重复执行不能产生重复 Point 或错误统计。
- [x] 进程崩溃恢复测试覆盖：保存后崩溃、DocIR 后崩溃、部分 upsert 后崩溃、切换前后崩溃。

## 9. 四个管理接口与预览/下载接口

### 9.1 `GET /me/knowledge-base`

- [x] 使用 `CurrentSession`，不存在文件也返回 `200` 空快照。
- [x] 返回完整 `PersonalKnowledgeBase`，字段名与契约完全一致。
- [x] `files` 始终为完整列表，不能只返回正在构建或最近上传文件。
- [x] `file_count == len(files)`。
- [x] `queued/building` 状态支持前端每 2 秒轮询。
- [x] 不在请求内扫描文件系统、计算 Embedding 或执行 Qdrant count。

### 9.2 `POST /me/knowledge-base/files`

- [x] 接收重复字段名 `files` 的 multipart 批量文件。
- [x] 缺少 multipart `files` 字段返回框架级 `422`；字段存在但没有可用文件或包含零字节文件返回 `400`。
- [x] 限制单文件 200 MB、单批 20 个、单批 1 GB、单用户 10 GB/1000 个文件，并在超限时使用契约状态码。
- [x] 只接受 MVP 完整格式列表；列表外格式在可靠保存前返回 `415`。
- [x] 全批验证、保存和建任务成功后返回 `202` 完整快照。
- [x] 新文件状态为 `queued`，知识库状态为 `queued/building`。
- [x] 发生互斥任务冲突时不留下孤立文件或半条数据库记录。

### 9.3 `GET /me/knowledge-base/files/{file_id}/content`

该接口返回经过租户授权和路径完整性校验的原文件；页面使用独立的有界 preview 派生接口，下载使用独立 download 路径。

- [x] `PersonalKnowledgeBasePage` 文件点击发起有界 preview 请求，不直接读取原文件 content。
- [x] 桌面端和移动端显示真实派生预览，并覆盖 loading、失败、重试和取消。

预览阶段完成以下事项：

- [x] 用 `user_id + file_id` 校验所有权；跨用户访问与不存在统一返回 `404`。
- [x] 使用已授权文件描述符安全流式响应，并支持 HEAD/Range 和独立下载。
- [x] 设置准确的 Content-Type、长度、文件名及安全响应头。
- [x] PDF、图片、文本与 Office 分格式选择预览器，必要时生成受控的派生文件或缩略图。
- [x] 前端不再用 `bodyBytes` 一次性加载大文件，并为本地缓存设置大小和清理策略。

### 9.4 `DELETE /me/knowledge-base/files/{file_id}`

- [x] 删除当前用户存在的文件返回 `204`；再次删除当前用户尚保留的 tombstone 仍返回 `204`；从未存在、tombstone 已清理或属于其他用户统一返回 `404`。
- [x] 同步写 tombstone 并从 GET 快照隐藏，再异步处理 Qdrant 和文件工件。
- [x] cleanup job 完成前保留文件 tombstone、目标 revision 和错误记录，不能因级联删除把尚未执行的清理任务删掉。
- [x] cleanup 成功后按审计保留策略清理原文件、DocIR、Chunk、Point、旧任务和错误记录。
- [x] cleanup 只有在生成不含该文件 Point 的干净 snapshot，并清除所有可能含该数据的旧 snapshot 后才算完成；这一规则覆盖常规保留 3 份策略。
- [x] 清理失败进入可重试任务，不重新暴露已删除文件。
- [x] 更新汇总统计和知识库状态。
- [x] 删除最后一个文件后返回/保持 `idle`、零统计和空列表。

### 9.5 `POST /me/knowledge-base/rebuild`

- [x] 空请求体，成功返回 `202` 完整快照。
- [x] 没有文件时固定返回 `400`。
- [x] 不改动原始文件。
- [x] 创建新的 staging generation 并全量重建解析产物、Chunk 和索引。
- [x] 旧 generation 在新 generation 完整就绪前继续服务。
- [x] 失败时快照保留可展示错误，同时记录旧索引是否仍可查询。

## 10. FastAPI 与生命周期接线

- [x] 新 router 使用 `/me/knowledge-base` prefix，并加入 `business_router`。
- [x] router 只做认证、输入校验、状态码转换和响应，不承载构建逻辑。
- [x] lifespan 初始化 Store、文件存储、Qdrant 适配器和 Service。
- [x] lifespan 启动 worker、把内部 `running` 重排为 `queued`、执行 revision reconcile 后再报告个人库 ready。
- [x] 生产命令验证 Uvicorn worker 数量为 1 且 reload 关闭。
- [x] shutdown 停止接单、推进/重排活动任务并尝试最后一次 snapshot，再释放模型/HTTP 资源；Job 启动脚本保证此时 Qdrant 尚未停止。
- [x] `PERSONAL_KB_ENABLED=false` 时 4 个管理接口固定返回 `503`。
- [x] 健康检查保持轻量，不触发模型和 Qdrant 查询。
- [x] 增加 readiness/内部指标：队列长度、活动任务、成功/失败数、阶段耗时、待清理代次。

## 11. Agent 检索闭环（第二阶段）

- [x] 新增 `PersonalKnowledgeRetrievalService.search(user_id, query, ...)`。
- [x] `user_id` 由执行上下文注入，模型参数不可覆盖。
- [x] 新增 `retrieve_personal_knowledge` 工具 schema 和能力声明。
- [x] 在 `AgentRuntimeDependencies` 中注入个人库检索服务。
- [x] 在 `BoundToolExecutor` 中处理个人库工具并传入 `context.user_id`。
- [x] 学习、科研、教学 workspace 是否都暴露该工具，需要按产品策略明确；当前页面三者共用同一用户库，推荐全部可读。
- [x] 输出包含文件名、Evidence、结构化 locator、Chunk ID 和检索降级信息；locator 严格使用第 7.1 节的格式专用 schema。
- [x] 保持全局 `retrieve_knowledge` 与 `get_knowledge_base_stats` 冻结契约不变。
- [ ] 用真实问题集评估“个人库单独检索”和“全局 + 个人联邦检索”后，再决定是否合并工具。

## 12. 安全与隐私验收

- [x] API 跨用户读取文件返回 `404`，不泄露资源是否存在。
- [x] Qdrant 跨用户查询、count、删除、重建均有负向测试。
- [x] Point ID 不会因不同用户上传相同文档而冲突。
- [x] 日志不记录文档正文、Bearer token、完整查询结果或敏感原始路径。
- [x] 文件名进入日志时转义控制字符并限制长度。
- [x] 错误响应不包含绝对路径、堆栈、模型密钥或 Qdrant 地址中的凭据。
- [x] 上传校验覆盖伪造扩展名、MIME 欺骗、空文件、超限文件、zip bomb 和路径穿越。
- [x] 删除用户或执行数据清理时能枚举并删除其文件、任务、工件和全部向量。
- [x] 备份、恢复和数据保留策略覆盖 SQLite、原文件和 Qdrant 三者的一致性。
- [x] 持久根目录、原文件、工件、snapshot 和 checksum 的 owner/mode 验收为预期服务账号、`0700/0600`。
- [ ] 共享计算节点场景验证 Qdrant API key、动态端口和进程归属，防止同节点其他 Job 访问个人向量。

## 13. 测试清单

### 13.1 Store 与 Service 单元测试

- [x] 空知识库快照。
- [x] 批量文件记录与稳定排序。
- [x] SHA-256 去重。
- [x] 状态转换和非法转换。
- [x] 单用户只有一个 running mutation、多个 queued revision 严格有序，以及原子 claim。
- [x] 重启恢复 running 任务。
- [x] 进度单调和统计聚合。
- [x] 删除/取消与构建竞态。
- [x] staging generation 成功/失败切换。
- [x] 每用户 `desired_revision/indexed_revision` 与全局 `qdrant_mutation_seq/snapshot_mutation_seq` 分域推进、落后检测和启动 reconcile。
- [x] 同一用户 target revision 不越序，不同用户解析/Embedding 可并发，全局 snapshot/collection 维护保持 single-flight。
- [x] 从较旧 snapshot 恢复时通过 mutation journal 追平全局高水位；全局 sequence 不回退、未追平前 readiness 为 false，journal 不会早于最旧保留 snapshot 被清理。
- [x] tombstone 在 cleanup 完成前持续隐藏且不会删除自己的 cleanup job。

### 13.2 RAG 与 Qdrant 适配器测试

- [x] Point payload 和确定性 Point ID。
- [x] 两个用户相同 `chunk_id` 不覆盖。
- [x] 所有检索路线强制租户过滤。
- [x] content role 过滤与租户过滤正确合并，而不是互相覆盖。
- [x] 文件级隐藏、删除和 generation 清理。
- [x] 部分写入不会变成可检索状态。
- [x] 旧 generation 在重建期间仍可查询。
- [x] 使用假 Qdrant 验证请求 JSON；使用真实 Qdrant 的集成测试可按环境清晰 skip。
- [x] snapshot checksum/manifest、全局 mutation sequence、常规保留最近 3 份、落后 snapshot 恢复及删除数据不进入新 snapshot。
- [x] 删除后生成干净 snapshot，并清除所有可能含被删数据的历史 snapshot，即使因此暂时少于 3 份。
- [x] 干净 snapshot 临时恢复后，被删 `user_id + file_id` 的 count/query 都为 0；验证失败时不得清理最后一份已知有效的新快照或宣告 cleanup 成功。
- [x] 各格式 Evidence locator schema、1-based 范围、归一化 bbox、JSON Pointer 和 locator 指纹兼容性。

### 13.3 API 契约测试

- [x] 4 个 MVP 接口的成功状态码和字段完整性。
- [x] 未认证 `401`。
- [x] 跨用户 GET 不返回其他用户文件，跨用户 DELETE 与不存在统一返回 `404`。
- [x] 缺少 `files` 字段 `422`、字段存在但空/零字节 `400`、格式不支持 `415`、配额超限 `413`。
- [x] 用户总容量/文件数配额、并发上传/重建 `409` 和 multipart 临时空间不足。
- [x] 上传返回完整快照，不只返回新增文件。
- [x] 删除存在文件和仍保留 tombstone 均为 `204`；不存在、已清理或跨用户均为 `404`。
- [x] 空知识库 rebuild `400`，功能关闭 `503`，并发 upload/rebuild `409`。
- [x] 前端允许的每一种扩展名都有明确成功或受控失败测试。
- [ ] 使用真实 `doc/ppt/xls` fixture 覆盖 MinerU API、DocIR、Chunk 和 Qdrant 全链，不以改后缀或伪造 manifest 代替。
- [x] `queued/building/ready/failed` 快照可被前端模型正确解析。
- [x] Flutter 测试断言点击文件只调用有界 preview API，并覆盖文本、PDF、图片和取消。

### 13.4 端到端测试

- [x] 上传一个小型真实 fixture，等待 `ready`，断言 Chunk 和 Point 数大于零。
- [x] 查询只能命中该用户上传内容。
- [x] 另一用户相同查询无命中。
- [x] 删除后查询无命中，管理快照中不再出现该文件。
- [x] 重建后 generation 改变、内容仍可命中、旧 generation 最终被回收。
- [x] 后端在构建中重启后任务恢复并最终完成。
- [x] 恢复落后 snapshot 后自动补齐最近上传和删除，最终 `indexed_revision == desired_revision`。

### 13.5 预览测试

- [x] 文件 content 接口的认证、跨用户 `404`、响应头和二进制内容。
- [x] HEAD/Range、流式读取、取消请求和缓存清理。
- [x] 接近 200 MB 文件不会被客户端一次性读入内存。
- [x] PDF、图片、文本和 Office 的支持矩阵与受控失败行为。

建议验证命令：

```bash
python -m pytest backend/tests backend/agent/DocIR/tests backend/agent/rag/tests
cd frontend && flutter test test/personal_knowledge_base_page_test.dart
```

外部模型、MinerU 和 Qdrant 不可用时，集成测试必须明确 skip，不能用伪造 manifest 冒充成功。

## 14. 文档与运维清单

- [x] 保持 [PERSONAL_KNOWLEDGE_BASE_API.md](PERSONAL_KNOWLEDGE_BASE_API.md) 为前端 HTTP 契约来源。
- [x] 更新 `API.md`，加入 4 个管理接口、content/preview/download、Range 与状态码。
- [x] 保持前端完整扩展名列表，并补齐 `doc/ppt/xls/csv/txt/md/json` 的 MIME 映射。
- [x] 在 `backend/agent/rag/README.md` 说明个人库与冻结全局库的隔离关系。
- [x] 在部署文档记录文件根目录、SQLite、Qdrant collection、模型和备份要求。
- [x] 提供失败任务重试、孤立工件清理和 generation 回收命令。
- [x] 提供按用户审计文件/Chunk/Point 数量的只读运维检查。
- [x] 明确磁盘、Qdrant 容量告警和上传限流策略。
- [x] 部署文档固定单 Uvicorn worker、个人 Qdrant API key、独占节点或动态端口策略，以及 ESA/Qdrant shutdown 顺序。
- [x] 不提交原始用户文件、数据库、DocIR 工件、ChunkCollection、向量或模型权重。

## 15. 推荐实施顺序与完成标准

### 阶段 A：管理接口骨架

- Migration、Store、配额、文件存储、空快照、上传/删除/rebuild 路由。
- 使用假构建器验证 4 个 MVP 接口和状态轮询；前端补齐全部格式 MIME。后续阶段已让预览入口调用独立的有界 preview API。

完成标准：前端能完成文件管理和状态展示，4 个 MVP 接口不再出现 `404`；预览不属于本阶段完成标准。

### 阶段 B：真实异步建库

- 强制 Chunk 的个人摄取、可降级视觉补全、共享 Embedding、租户感知 Qdrant、revision reconcile、周期 snapshot、跨 Job 恢复、任务恢复和 generation 切换。

完成标准：真实 fixture 从上传到 `ready`，统计可核对，删除和重建无孤立可见 Point；新 Job 能从 snapshot 恢复并通过 revision 补齐最近变更。没有这条，不得宣称个人库已持久化交付。

### 阶段 C：Agent 检索

- 用户上下文检索工具、引用输出、权限和评测。

完成标准：当前用户聊天能引用个人文档，其他用户无法通过任何工具或查询路径读取该内容。

### 阶段 D：生产加固

- 单 Job 单后端/单 worker 拓扑下的限流、权限、监控、snapshot 保留清理、运维工具、容量与故障演练。

完成标准：重启、Qdrant 短暂不可用、部分写入、超限上传和删除竞态均有可重复验证结果。

### 阶段 E：在线预览（已完成）

- content 接口、流式/Range、分格式预览器、下载和前端内存治理。

完成标准：受支持的大文件无需 `bodyBytes` 全量载入即可预览，权限、缓存和失败路径通过独立验收。

## 16. 开工前需要最终确认的决策

- [x] 部署采用每个 Slurm Job 一个活动后端，原文件和工件使用单机服务可见的持久目录，不使用 Job 临时目录。
- [x] `PERSONAL_KB_ROOT` 默认使用 `/persist_data/home/chenxuzhao/esa-personal-knowledge-base`；每次部署仍须先做宿主机只读容量、挂载和权限检查，不通过时停止启动并显式改配已验证的持久目录。
- [x] 用户内 SHA-256 相同即去重，保留首次上传的逻辑条目和文件名。
- [x] 个人库表写入现有主 SQLite，不拆分第二个数据库；如需迁移则整体迁移主数据库。
- [x] generation 表示全量 rebuild 代次，普通上传在 active generation 增量写入并使用文件 revision。
- [x] SQLite 与原文件为权威数据，Qdrant/snapshot 为可重建派生状态，并使用 revision + reconcile 恢复。
- [x] 上传/重建冲突统一返回 `409`。
- [x] MVP 使用 SQLite 持久任务和单进程内队列，固定一个 Uvicorn worker，不接外部任务系统。
- [x] 个人摄取只复用 MM 下层组件，所有成功文档强制 Chunk/Index。
- [x] MinerU 按格式必需，VLM 允许关闭或失败降级；无任何可检索文本时任务失败。
- [x] MVP 支持前端完整格式列表；`doc/ppt/xls` 由 MinerU 解析并纳入真实全链 fixture 验收。
- [x] 初始配额为单文件 200 MB、单批 20 个/1 GB、单用户 10 GB/1000 个文件。
- [x] 个人 Qdrant 使用最大延迟 10 分钟、保留 3 份的周期快照，并通过 revision 补齐变更。
- [x] 在线预览不纳入初始 MVP；现已在阶段 E 完成原件流、派生预览和 200 MB 内存治理。
- [x] 共享 collection 使用全局 `qdrant_mutation_seq/snapshot_mutation_seq`，每用户只维护 `desired_revision/indexed_revision`，不使用每用户 `snapshot_revision`。
- [x] 同一用户 mutation 按 `target_revision` 有序提交；不同用户可并发解析/Embedding，snapshot 和 collection 维护全局 single-flight。
- [x] HTTP 语义固定：缺 `files` 为 `422`，空/零字节为 `400`，格式为 `415`，配额为 `413`，空库 rebuild 为 `400`，功能关闭为 `503`，并发上传/重建为 `409`；删除遵循明确的 `204/404` 规则。
- [x] 删除后的干净 snapshot 和历史敏感 snapshot 清理优先于常规保留 3 份策略。
- [x] Evidence 使用格式专用的结构化 locator，locator schema 和映射规则进入流水线指纹。
- [x] 第二阶段采用独立 `retrieve_personal_knowledge`，还是直接联邦到现有工具。
- [x] 个人库是否在学习、科研、教学三个 workspace 中全部可检索。

实现选择固定为独立 `retrieve_personal_knowledge`，并按 `common` 只读能力在学习、科研、教学三个 workspace 中开放；工具 schema 不含 `user_id`，执行时只使用受信任的 `ToolExecutionContext.user_id`。

MVP 已无待选的产品语义；部署前只需按环境完成 `/persist_data` 的宿主机核验，检查失败时不得静默回退临时目录。Agent 工具和 workspace 选择可以在 4 个管理接口和真实建库完成后再定；在线预览留到独立阶段讨论。
