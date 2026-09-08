# ESA - 星知智链

ESA（Efficient Study Agent）是面向计算机学科教学、学习与科研协作的可信智能体平台。系统以课程知识图谱、学习证据、可追溯检索、受控工具和人工复核为基础，把学生个性化学习、教师作业诊断和科研项目辅助组织在明确的身份与资源边界内。

> 文档最后核对：2026-09-08，代码基线 `main@c485941`。请先阅读 [DOCUMENTATION.md](DOCUMENTATION.md) 了解文档可信级别。当前接口以 [API.md](API.md) 为导航、以 FastAPI OpenAPI 与 Router 代码为最终事实；当前待办只看 [TODO.md](TODO.md)。

## 当前可运行能力

| 领域 | 已实现能力 | 运行边界 |
|---|---|---|
| 学习 | 多轮/SSE 对话、知识地图、Student Model V2、掌握度、保持率、复习队列、练习推荐、课表/目标/待办 | 正式学习状态只由可评价证据更新 |
| 教学 | 教师建班、定向邀请、作业发布、学生提交、AI 结构化分析、教师复核、反馈发布、班级诊断 | AI 不自动决定或发布成绩 |
| 科研 | 项目、项目画像、前沿追踪、文档写作任务、数据集上传与分析任务 | 项目资源按当前用户隔离，缺证据不伪造引用或结论 |
| 对话与组织 | 认证、会话恢复、对话 CRUD、分组、置顶、移动、Workspace/项目绑定、附件上传与预览 | 同一对话跨 Worker 串行，不同对话可并行 |
| 文档与知识 | PDF/Office/图片附件、MinerU→DocIR、Chunk、公共/个人知识库、Evidence 来源定位 | RAG、mm、个人库是否可用取决于目标环境配置和索引 |
| 工具与执行 | 数学/位运算、arXiv、You.com MCP、记忆、学习工具、代码编辑、LSP WebSocket、受控沙箱 API | 沙箱代码存在但代码默认关闭；MCP 启动需要 `YDC_API_KEY` |
| 记忆与治理 | CoreMemory V2、候选记忆、版本、暂停/恢复/遗忘、Profile、审批动作、审计投影 | 读取和写入受用户、Workspace 与 memory mode 约束 |

## 代码地图

```text
backend/core/web/          FastAPI 应用、依赖注入、REST/SSE/WebSocket Router
backend/core/router/       身份、Workspace、资源绑定与运行路由
backend/core/services/     认证、教学、科研、附件、LSP、代码执行等服务
backend/core/stores/       SQLite Store 与迁移
backend/agent/             Agent Runtime、Tools、Skills、Learning、Memory
backend/agent/DocIR/       文档中间表示与 MinerU adapter
backend/agent/rag/         Chunk、索引、检索、Evidence 与个人知识库流水线
backend/agent/mm/          会话附件摄取和视觉增强
backend/scripts/dataset/   SFT/LoRA 数据、冻结考卷、评测与推理闸门实验
frontend/lib/              Flutter 学生端、教师端、科研空间与共享组件
email_service/             独立验证码邮件投递服务
data/knowledge_base/v1/    来源登记、课程、知识点、前置关系、题库与 gold 数据
```

## 运行配置要点

代码默认值与 `.env.example` 的目标部署示例不是一回事：

| 能力 | 代码默认 | `.env.example` | 说明 |
|---|---:|---:|---|
| `RAG_ENABLED` | `false` | `false` | 启用前必须有匹配的 collection 与 deployment manifest |
| `PERSONAL_KB_ENABLED` | `false` | `true` | 示例面向已准备 Qdrant/MinerU/持久盘的目标部署 |
| `MM_ENABLED` | `false` | `false` | 需要 MinerU 和辅助视觉模型服务 |
| `ESA_SANDBOX_ENABLED` | `false` | `false` | 需要 Bubblewrap 与受控依赖安装条件 |
| MCP | 代码固定启用 | 通过 `YDC_API_KEY` 配置 | 没有 Key 时完整集群启动脚本会 fail-closed |
| LSP | 代码固定启用 | 按可执行文件探测 | 单个 language server 缺失只禁用对应语言 |
| `ESA_EMAIL_PROVIDER` | `disabled` | `disabled` | 设为 `service` 后必须提供服务 URL、Token 和验证码 Secret |

主模型代码默认值为 `Qwen/Qwen3.5-122B-A10B`，TP=2、PP=3；辅助模型为 `Qwen/Qwen3.5-9B`。完整集群脚本还会为辅助模型分配 1 张 GPU，并在本地 Transformers Embedding 启用时再分配 1 张 GPU。实际资源需求必须按启用的 RAG/mm/MinerU 拓扑重新计算，不能机械写成固定“8 卡”。

## 启动后端

安装依赖并从仓库根目录启动最小 FastAPI 进程：

```bash
python -m pip install -r requirements.txt
python -m backend.main
```

等价 ASGI 命令：

```bash
uvicorn backend.core.web.webAPI:app --host 0.0.0.0 --port 51024
```

Canonical API prefix 是 `/api`。默认仍注册无前缀兼容路由，但新客户端不得依赖它；生产反向代理必须保留 `/api`。健康检查为 `GET /api/health`，只证明 HTTP 进程存活。

目标超算的双模型/Qdrant/MinerU 编排入口：

```bash
ESA_ENV_FILE=/absolute/path/to/deployment.env \
  ./backend/scripts/run_esa_stack.sh
```

脚本会校验 GPU 数、MCP、Qdrant、manifest、模型服务和条件性依赖。不要在登录节点直接加载模型。

## 启动前端

Flutter Web 默认请求同源 `/api`；原生端默认使用代码中配置的 HTTPS API，可用编译参数覆盖：

```bash
cd frontend
flutter pub get
flutter run --dart-define=ESA_API_BASE=http://127.0.0.1:51024/api
```

Web release：

```bash
./frontend/scripts/build_web_release.sh
```

部署时参考 `deploy/nginx/esa-web.conf.example`。聊天附件上限代码默认 200 MiB，Nginx `client_max_body_size` 不得更小。

## 推荐 Demo

最稳定的竞赛主线是教师/学生双账号教学闭环：

```text
教师建班并邀请学生
→ 发布带知识点的作业
→ 学生提交
→ AI 生成结构化分析建议
→ 教师复核并发布反馈
→ 正式反馈写入学习证据
→ 学生继续针对性学习，教师查看班级诊断
```

具体操作与权限边界见 [TEACHING_STUDENT_DEMO.md](TEACHING_STUDENT_DEMO.md)。比赛提交材料、
双角色体验说明和 3 分钟视频脚本见 [deliverables/competition/README.md](deliverables/competition/README.md)。

## 质量检查

```bash
python -m pip install -r requirements-dev.txt
make quality
```

2026-09-08 在当前 Python 3.13 环境实测：`718 passed, 70 skipped, 3 warnings`，Ruff 与 mypy 同时通过。停用用户复用旧 Session 的测试已统一到 API 的 `401` 认证失败契约。当前环境没有 Flutter SDK，因此本轮未复跑 Flutter analyze/test/build；前端只保留 2026-09-05 的历史验证记录，详见 [COMPETITION_AUDIT.md](COMPETITION_AUDIT.md)。

## 开发约定

- 代码和测试是事实来源；设计文档、开发日志和旧审查不得覆盖当前实现。
- Router/Schema 改动后更新 `API.md`，功能状态改动后更新 `TODO.md`。
- 不提交 `.env`、密钥、数据库、日志、模型权重、运行时缓存、真实学生数据或临时账号密码。
- RAG 指标区分检索指标与端到端回答质量；代码存在区分于目标环境已启用和已验收。
- 模型生成的成绩、学习状态写入和科研结论必须保留人工确认或证据边界。
