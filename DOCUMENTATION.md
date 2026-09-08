# ESA 文档索引与可信级别

> 最后核对：2026-09-08，代码基线 `main@6089606`。
>
> 本索引用于解决仓库中“现状文档、设计方案、历史审查和竞赛材料混在一起”的问题。判断系统当前行为时，优先顺序始终是：可执行代码与测试 > 运行配置 > 当前契约文档 > 历史记录。

## 1. 当前事实入口

| 文档 | 用途 | 可信边界 |
|---|---|---|
| `README.md` | 产品范围、代码地图、启动方式、条件性依赖 | 当前总入口 |
| `API.md` | HTTP/WebSocket/SSE 契约与路由目录 | 路由以 FastAPI OpenAPI 和 Router 代码为最终事实 |
| `REQUEST.md` | 当前产品需求、已实现能力与验收目标 | 只描述当前版本，不保留旧计划状态 |
| `TODO.md` | 唯一当前待办清单 | 已完成事项不再留在未完成列表 |
| `.env.example` | 比赛/目标部署配置示例 | 示例值不等于代码默认值或线上实际值 |
| `COMPETITION_AUDIT.md` | 最近一次本机工程验证 | 每条结论带日期、环境与命令，不外推到目标服务器 |

## 2. 当前模块契约

| 文档 | 模块 |
|---|---|
| `backend/agent/DocIR/README.md` | 解析器无关文档中间表示 |
| `backend/agent/mm/README.md` | 会话附件摄取与多模态增强 |
| `backend/agent/rag/README.md` | Chunk、索引、检索和 Evidence 契约 |
| `backend/agent/rag/DEPLOYMENT.md` | RAG 部署与 manifest 校验 |
| `backend/agent/rag/chunk/README.md` | DocIR 到 ChunkCollection |
| `PERSONAL_KNOWLEDGE_BASE_API.md` | 个人知识库前后端契约 |
| `RAG_DocIR_mm_env.md` | DocIR/RAG/mm 环境与启动指南 |
| `deploy/LSP.md` | 浏览器到语言服务器的 WebSocket 部署 |
| `email_service/README.md` | 独立验证码投递服务 |
| `frontend/docs/mobile-design-system.md` | Flutter 移动端实现规范 |
| `backend/agent/skills/SKILLS.md` | Agent Skill 目录；这些 Markdown 是运行时提示资产，不是项目状态说明 |

## 3. 当前产品与竞赛说明

| 文档 | 用途 |
|---|---|
| `PRODUCT_NARRATIVE.md` | 对外产品定位、边界和评审表达 |
| `TEACHING_STUDENT_DEMO.md` | 教师/学生双账号教学闭环 |
| `DATASET_GENERATION.md` | 数据工程方法与当前定版产物索引 |
| `backend/scripts/dataset/docs/06-效果验证材料.md` | LoRA 固定考卷评测结果 |
| `documents/md/掌握度算法理论依据.md` | 历史算法研究记录；当前参数以 Student Model V2 源码为准 |
| `documents/md/文献综述.md` | 2026-07-31 文献整理；参赛引用前需重新核对原文 |

## 4. 已实施设计与验收记录

以下文档保留设计理由、迁移过程和验收项。它们不是当前待办清单；状态应结合 `TODO.md` 与代码判断。

- `BACKEND_REFACTOR_IMPLEMENTATION_PLAN.md`
- `CORE_MEMORY_DESIGN.md`
- `GROUP_FEATURE.md`
- `PERSONAL_KNOWLEDGE_BASE_IMPLEMENTATION_CHECKLIST.md`
- `OPTIMIZATION_NOTES.md`

## 5. 历史快照

以下文档按原日期保留，不应用其中的“未实现”“评分”或资源配置判断当前系统：

- `ARCHITECTURE_REVIEW.md`
- `MEMORY_PROMPT_ANALYSIS.md`
- `MEMORY_PROMPT_ANALYSIS_fix.md`
- `SUBMITTION.md`
- `documents/ESA_代码质量与竞赛需求完成度评估报告_2026-08-08.md`
- `feature_problem.md`
- `frontend_problem.md`
- `backend/agent/rag/try/PRODUCTION_INTEGRATION_REPORT.md`
- `docs/reports/DOCIR_FULL_CORPUS_EVALUATION_*.md`

历史文档中的路径、测试数、模型分配、公网状态和完成度只对其标注的代码快照成立。

## 6. 维护规则

1. 接口变化先改 Router/Schema 和测试，再更新 `API.md`。
2. 功能完成后立即更新 `TODO.md`；设计文档不承担当前任务状态。
3. 测试结论必须记录日期、Python/Flutter 环境、passed/failed/skipped 和未覆盖外部依赖。
4. `.env.example` 是目标部署示例。文档描述“默认”时必须区分代码默认、示例配置和线上配置。
5. 竞赛指标必须指向原始评测文件、考卷指纹或可重复命令；不把代码存在写成目标环境已验收。
6. 不在仓库文档中写入密钥、验证码、临时账号密码、真实学生数据或生产数据库内容。
