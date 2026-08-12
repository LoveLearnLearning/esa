# ESA 教师端与学生端 Demo 说明

> 状态：2026-08-12。本文只描述仓库中已经实现的教学闭环。

## 1. 实现范围

本次实现了一条可用真实教师和学生账号演示的完整纵向流程：

```text
教师创建班级并输入学生精确用户名发起邀请
→ 学生确认加入
→ 教师创建并发布简答题或代码文本题作业
→ 学生逐题提交
→ 教师对单个提交或全部提交启动 AI 分析
→ 教师修改并确认逐题分数、评语和知识点
→ 教师发布反馈
→ 学生查看反馈并进入针对性学习
→ 正式作业证据更新个人掌握度
→ 教师查看班级薄弱知识点、前置根因和关注学生
```

现有学生课表、学习对话、个人课程和知识地图保持不变。班级课程只是教学关联，学生仍可查看个人学习空间内课程的全部知识点。

## 2. 界面入口

学生账号可进入：

- `学习空间 → 作业`：处理班级邀请、查看作业、提交答案和查看反馈。
- `学习空间 → 知识地图`：继续查看原有全部课程知识点及个人掌握状态。
- `学习空间 → 学习助手`：反馈发布后可进入针对性学习对话。

教师账号可进入：

- `教学空间 → 教学工作台`：查看班级数、待复核数和待发布反馈数。
- 班级详情：邀请学生、创建和发布作业、查看班级知识薄弱点及成员。
- 作业批改页：分析全部提交或单个提交，编辑复核结果并发布反馈。
- `教学空间 → 教学助手`：保留原有教学对话能力。

## 3. 角色和权限

- `account_role` 注册后固定为 `student` 或 `teacher`。
- 教师只能访问自己创建的班级及其作业和提交。
- 学生只有接受邀请后才能看到仍开放的班级作业。
- 学生只能读取自己的提交和已发布反馈。
- 未经教师发布的 AI 分析、参考答案、评分规则和复核结果不会返回学生端。
- 教师只能查看本班作业形成的结构化证据，不能访问学生私人对话、记忆、科研项目或无关附件。
- 无权访问和资源不存在统一使用 `404`；角色入口错误使用 `403`。
- 邀请、提交、分析、复核、反馈发布和学生详情访问写入只追加审计日志，不记录完整答案或敏感凭证。

## 4. 数据模型

教学数据与现有用户表共用一个 SQLite 数据库，由 `TeachingStore` 幂等创建：

| 表 | 责任 |
|---|---|
| `teaching_classes` | 单负责人班级、主课程、学期和归档状态 |
| `teaching_memberships` | 无邀请码邀请及待确认、活动、拒绝、移除状态 |
| `teaching_assignments` | 作业草稿、发布状态、总分和截止时间 |
| `teaching_questions` | 简答题/代码文本题、评分规则、参考答案和知识点 |
| `teaching_submissions` | 学生正式提交版本、分析和反馈状态 |
| `teaching_answers` | 逐题答案、AI 建议和教师最终裁决 |
| `teaching_evidence_publications` | 防止同一反馈重复写入学习证据 |
| `teaching_audit_log` | 关键教学操作审计 |

正式反馈发布时，每个有关联知识点的题目会生成 `homework` 学习证据，并调用现有 `MasteryStore.apply_evidence` 更新学生个人掌握度。成绩和掌握度保持为两个不同概念。

## 5. AI 分析与教师责任

- 客观事实、最终分数、错因、知识点和反馈都以教师复核结果为准。
- 辅助 Qwen 服务可用时，系统要求模型输出受约束的结构化 JSON 建议。
- 辅助服务不可用或输出无效时，系统使用低置信度确定性降级结果，明确要求人工复核。
- AI 不会自动发布成绩，也不会在教师确认前写入学生掌握度。
- “分析全部提交”按当前作业的每名学生最新提交执行，返回完成和失败数量。

## 6. 班级学情

班级看板只统计已经发布的正式反馈：

- 知识点平均得分率、薄弱人数、已评估人数和班级人数。
- 连续出现至少两条薄弱证据的关注学生。
- 对薄弱知识点沿现有知识图谱查找前置关系，优先展示已有证据确认薄弱的前置点；没有直接证据时标记为需要诊断，而不表述为确定因果。

当前看板按请求实时读取教学表，适合 Demo 规模；大班级生产环境应增加预计算快照。

## 7. API 索引

教师接口：

- `GET /api/teaching/overview`
- `GET /api/teaching/classes`
- `POST /api/teaching/classes`
- `GET /api/teaching/classes/{class_id}`
- `POST /api/teaching/classes/{class_id}/invitations`
- `DELETE /api/teaching/classes/{class_id}/members/{student_id}`
- `POST /api/teaching/classes/{class_id}/assignments`
- `POST /api/teaching/assignments/{assignment_id}/publish`
- `GET /api/teaching/assignments/{assignment_id}/submissions`
- `POST /api/teaching/assignments/{assignment_id}/analyze`
- `GET /api/teaching/submissions/{submission_id}`
- `POST /api/teaching/submissions/{submission_id}/analyze`
- `POST /api/teaching/submissions/{submission_id}/review`
- `POST /api/teaching/submissions/{submission_id}/publish-feedback`
- `GET /api/teaching/classes/{class_id}/dashboard`
- `GET /api/teaching/classes/{class_id}/students/{student_id}`

学生接口：

- `GET /api/student/classes`
- `POST /api/student/invitations/{membership_id}/respond`
- `GET /api/student/assignments`
- `GET /api/student/assignments/{assignment_id}`
- `POST /api/student/assignments/{assignment_id}/submissions`
- `GET /api/student/submissions/{submission_id}`

请求体和状态码详见 [API.md](API.md)。

## 8. 双账号 Demo 脚本

1. 注册一个教师账号和一个学生账号。
2. 教师进入教学工作台，创建与现有知识图谱课程同名的班级。
3. 教师在班级页输入学生的精确用户名并发送邀请。
4. 学生进入作业中心接受邀请。
5. 教师创建一题带知识点 ID 的诊断作业并发布。
6. 学生刷新作业中心，打开作业并提交答案。
7. 教师进入作业批改页，点击“分析全部提交”。
8. 教师点击“复核并调整”，修改得分、评语或知识点后确认。
9. 教师发布反馈。
10. 学生刷新作业中心查看逐题反馈；教师回到班级页查看知识点聚合。

## 9. 测试

推荐使用 Python 3.10 以上环境：

```powershell
$env:PYTHONUTF8='1'
python -m pytest backend/tests backend/agent/DocIR/tests backend/agent/mm/tests backend/agent/rag/chunk/tests -q
python -m ruff check backend email_service
cd frontend
flutter analyze
flutter test
```

2026-08-12 本机验证结果：

- 后端主测试集：`287 passed, 42 skipped`。
- Ruff：全仓通过。
- Flutter 定向静态分析：通过。
- 教学页面及受影响导航测试：`6 passed`。
- 后端完整 RAG 评测目录没有纳入上述 Windows 回归：部分测试依赖 Unix `resource` 模块，当前 `esa` 环境也未安装 `numpy`。

## 10. 已知限制和后续事项

当前 Demo 暂未实现：

- 多教师协作、助教角色和学校组织目录。
- 单选、多选、附件题、真实隔离代码执行和运行结果评分。
- 草稿自动保存、复杂迟交策略、撤回、教师豁免和作业改版。
- 反馈更正版本的完整前端流程。
- 学生跨场景个人证据授权。
- 大班级预计算快照、站外通知、完整预警处理台和独立审计页面。
- 教师端对学生详情的完整可视化页面；受限详情 API 已提供。

这些能力的数据边界已明确，但不属于本次可运行 Demo 的完成范围。
