# 竞赛交付前工程审查

> 审查日期：2026-09-05
>
> 范围：当前 `main` 分支 `5c8b652` 之后的未提交修复，以及后端和 Flutter 前端的可重复质量验证。

## 结论

本轮审查修复了认证隔离、个人知识库永久清理、沙箱前置校验、Flutter 异步状态竞态和测试稳定性问题。修复后，后端质量门禁和非视觉前端测试均通过，Web release 构建成功。

这份记录不等同于公网发布验收。真实模型、邮件、Qdrant、沙箱运行时、外部语料和部署链路仍需在比赛环境使用真实账号和配置执行人工验收。

## 已修复问题

### 后端与数据隔离

- 个人知识库 API 测试夹具显式注入 `app.state.user_store`，避免测试绕过生产认证依赖。
- 个人知识库用户永久清理现在删除 `personal_knowledge_base_catalogs`；对历史上已标记 `applied` 或 `completed` 的 purge 重试也会补清残留目录。
- purge 完成后继续保留用户访问和重新创建知识库的隔离栅栏，避免删除完成后重新写入旧租户。
- Qdrant 查询测试同时验证 `scope`、`visible` 和 `content_role`，不再依赖条件字典的顺序。
- 迁移测试依据 `MIGRATIONS` 注册表计算预期数量，不再硬编码历史版本数。
- 沙箱缺少 installer 时 fail-closed，并在启动子进程前返回明确错误；测试不再依赖当前 Python 环境是否恰好安装 pip。

### Flutter 可靠性

- 首页“继续学习”、注册验证码和教师新建班级按钮增加稳定测试 key，避免依赖 `FilledButton.icon` 等私有运行时类型。
- 注册邮箱发生变化时使旧验证码失效，覆盖验证码请求先后于邮箱变化的两种时序。
- `TeacherShell` 的概览加载、班级/分组/对话操作捕获会话身份，阻止登出或切换账号后的迟到响应回写。
- 教师弹窗使用弹窗内部管理的 `TextFormField`，避免外部 controller 在关闭动画期间提前释放。
- `AppState` 的分组创建、编辑、置顶、删除、对话移动、重命名和删除操作均阻止旧会话或已替换列表对象继续修改当前状态。
- 失败的教师侧边栏操作统一显示错误提示，避免接口失败静默。

## 验证证据

以下命令均在 2026-09-05 执行；后端 CI 等价检查使用隔离的 Python 3.10.12 环境 `/tmp/esa-ci-verification`。

### 后端

```text
python -m ruff check .       -> All checks passed!
python -m mypy              -> Success: no issues found in 5 source files
python -m compileall -q backend -> passed
python -m pytest -q         -> 711 passed, 70 skipped, 5 warnings
```

跳过项是环境或外部材料依赖：MinerU 多格式/PDF fixture、真实 RAG 语料和评测材料、`clangd`。警告主要来自 FastAPI/Starlette/httpx 弃用提示，以及一个测试中 asyncio 子进程在事件循环关闭时的清理告警；没有失败测试。

### 前端

```text
flutter test --concurrency=1 [排除 visual_audit_test.dart] -> 222 tests passed
flutter analyze                                      -> No issues found
flutter build web --release                          -> Built build/web
```

批量 Flutter 测试第一次受当前 shell 的 HTTP 代理变量影响，测试壳无法连接本机端口；清除 `http_proxy`、`https_proxy`、`HTTP_PROXY`、`HTTPS_PROXY` 和 `ALL_PROXY` 后串行执行通过。这是验证环境问题，不是应用测试失败。

视觉 golden 测试的 8 个截图在原始 `HEAD` 和本工作树上完全相同地失败：

```text
landing desktop 0.59%   landing mobile 1.44%
conversation desktop 0.67%   conversation mobile 1.52%
knowledge desktop 0.55%   knowledge mobile 0.66%
research desktop 0.48%   research mobile 1.59%
```

因此本轮没有覆盖或更新 goldens；这些失败属于当前渲染环境与既有截图基线漂移，仍应在比赛目标浏览器和固定渲染环境重新验收。

## 仍需人工验收

- 使用真实学生和教师账号完成注册、登录、登出、验证码、班级邀请、作业提交、教师复核和反馈发布全流程。
- 在配置真实邮件服务、主/辅模型、Qdrant 和附件存储后验证超时、错误降级、来源引用和数据隔离。
- 在安装 bubblewrap、installer 和资源限制工具的目标机器上执行真实沙箱命令，验证 CPU、内存、时间、网络和文件系统边界。
- 使用比赛要求的真实课程语料执行 MinerU、RAG 召回、重排和引用质量验收，并补齐当前跳过的外部 fixture。
- 在目标公网域名、HTTPS、Nginx SSE 代理、Flutter Web 缓存更新和多浏览器/移动端上执行发布验收。

## 未宣称完成的事项

`TODO.md` 中的公网 Demo、备份恢复、日志告警、生产级 LMS、真实语料评测、部署固化等事项仍保持未完成。代码修复和本地自动化通过不代表这些运行环境工作已完成。
