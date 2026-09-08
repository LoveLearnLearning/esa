# 竞赛交付前工程审查

> 最新审查：2026-09-08，代码基线 `main@c485941`。
>
> 本文只报告当前工作机实际执行结果。它不证明公网 Demo 的完整业务流程、模型服务、Qdrant、MinerU、邮件、沙箱或真实用户流程已经在比赛目标环境通过。

## 1. 当前结论

代码功能面已覆盖学习、教学、科研、附件、个人知识库、RAG、LSP、代码执行、记忆、数据集与 LoRA 评测主链路。本轮后端测试和静态质量门禁全部通过。当前阻断集中在 Flutter SDK 本机不可用、条件性外部依赖尚未完成统一目标环境验收，以及比赛要求的签字盖章、真实用户确认与视频录制仍需团队本人完成。

## 2. 2026-09-08 本机验证

### 后端测试收集

```text
python -m pytest --collect-only -q
-> 786 tests collected
-> 2 external MinerU regression tests skipped during collection summary
```

### 后端全量测试

```text
python -m pytest -q
-> 718 passed, 70 skipped, 3 warnings
-> 45.04s
```

停用用户复用旧 Session 的测试已经统一到当前 API 契约：不存在、过期或被停用账号的 Session 均撤销并返回 `401`。修复提交为 `c485941`。

70 个跳过项主要来自：外部 MinerU 多格式 fixture、真实 RAG corpus/evaluation artifacts 和本机未安装 `clangd`。这意味着核心单元/契约测试覆盖较广，但不能替代真实文档、真实索引和语言服务器验收。

3 个警告为 FastAPI/Starlette/httpx 弃用提示，不影响本轮执行结果，但应进入依赖升级计划。

### Flutter

```text
flutter analyze
flutter test --concurrency=1 --exclude-tags=visual
-> 当前工作机 PATH 中没有 flutter，可执行文件未找到
```

因此本轮没有新的 Flutter analyze/test/build 结论。仓库中存在既有 `frontend/build/`，但构建产物不能证明当前源代码在本机重新构建成功。

### 公网最小检查

```text
https://esa.lovelearnlearning.cn/            -> HTTP 200，页面标题“星知智链”
https://esa.lovelearnlearning.cn/api/health -> HTTP 200，{"status":"ok"}
```

该检查于 2026-09-08 执行，只证明首页和 HTTP 进程可访问，不证明模型回复、SSE、邮件、Qdrant、MinerU、沙箱或双角色教学流程已经验收。

### 技术报告证据校验

```text
python deliverables/technical-report/verify_report_claims.py
-> All report claims verified.
```

该脚本核验：知识库 V1 数量、运行时课程图谱数量、数据集/切分数量、人工拒绝裁定数量、440 道考卷指纹和 3 个真实评测 Case 的逐项得分。它不核验技术报告中的公网运行、截图、用户反馈或本轮测试总数。

## 3. 可核验代码事实

- OpenAPI：118 个 path、147 个 HTTP operation，另有 LSP WebSocket。
- 来源对齐知识库 V1：16 门课程、215 个知识点、186 条前置关系、16 个登记源、48 条标准答案、430 条检索标注、645 道题。
- 运行时完整课程图谱：47 门课程、479 个知识点、448 条前置关系。
- Agent 数据：1,421 条 IR；候选训练池 1,094 条；训练/验证/测试 1,003/43/48；440 道主考卷、55 道补充集。
- 评测考卷指纹：`d441611fb5556b53#440`。

以上数量由仓库数据和校验脚本确认。目标环境是否加载同一模型、LoRA、manifest 和数据仍需运行时证明。

## 4. 仍需目标环境验收

- 主模型与 LoRA 是否按预期加载，辅助模型是否可用，模型/适配器/考卷指纹是否匹配。
- MCP 包下载、`YDC_API_KEY`、arXiv、外网与超时降级。
- Qdrant collection/deployment generation、Embedding 维度、RAG 来源定位与前端来源卡片。
- MinerU、多格式 DocIR、视觉增强和大文件/异常文件路径。
- 个人知识库 mutation、recovery、snapshot、删除和跨用户隔离。
- 邮件验证码投递、限流、失败清理和临时评委账号。
- Bubblewrap 沙箱的 CPU、内存、时间、网络、进程和文件边界。
- `clangd`/`pyright` 的 LSP 认证、并发限额、断线和降级。
- Nginx TLS、SSE、WebSocket、200 MiB 上传、Service Worker/缓存和多浏览器移动端。

## 5. 比赛材料缺口

- 盖章并审核通过的报名表。
- 负责人签字或团队盖章的伦理与安全合规声明。
- 可直接体验的临时账号及独立密码交付方式。
- 模型适配器文件或 ServiceID 和校验信息。
- 至少 2 名真实目标用户本人确认的试用记录。
- 3 个典型问题的结构化记录表已生成；仍需补原始输出截图和人工签名判定归档。
- 不超过 3 分钟的真实应用交互视频。
- 赛题 9 月 5 日/9 月 15 日日期冲突的赛事方确认。

## 6. 历史验证记录

2026-09-05 的历史审查曾在隔离 Python 3.10.12 环境报告 `711 passed, 70 skipped`，并报告 222 项非视觉 Flutter 测试、`flutter analyze` 和 Web release 构建通过。该结果只对当日代码和工具链成立；2026-09-08 当前后端结果为 `718 passed, 70 skipped`，而 222 项前端结果仍只作为历史记录。
