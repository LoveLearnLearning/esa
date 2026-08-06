# ESA - Efficient Study Agent

ESA 是一个面向学习场景的多用户 Agent 项目，由 FastAPI 后端、vLLM 推理服务和 Flutter 多端前端组成。

> 文档状态：2026-08-06。后端接口以 [API.md](API.md) 为准，剩余任务以 [TODO.md](TODO.md) 为准。

## 当前能力

- 用户注册、登录、退出、修改密码和 7 天会话保持
- 对话与消息持久化、同步回复和 SSE 流式回复
- 模型思考内容、工具调用、Markdown、LaTeX 与代码高亮展示
- 核心记忆管理、用户偏好、学情档案、掌握度报告和练习推荐
- 数值计算、位运算、符号计算、Web 搜索和 arXiv 搜索等工具
- 对话分组与分组内自定义指令（后端已实现，含分组级风格/语调/指令覆盖用户级，前端待对接）
- Flutter Web、macOS、iOS 等多端构建基础

## 目录

```text
backend/                 FastAPI、Agent、vLLM、工具和数据存储
frontend/                Flutter 前端
API.md                   前后端接口约定
TODO.md                  当前待办
TODO_REFACTOR.md         后端重构待办
DATASET_GENERATION.md    Qwen3.5/LLaMA-Factory 数据集方案
GROUP_FEATURE.md         对话分组功能设计
MEMORY_PROMPT_ANALYSIS.md 记忆与提示词评估
REQUEST.md               项目需求和阶段状态
SUBMITTION.md            历史开发记录
```

## 启动后端

先在 `backend/core/utils/config.py` 配置模型路径和推理参数，然后从仓库根目录运行：

```bash
python -m backend.main
```

默认监听 `0.0.0.0:51024`。也可以直接启动 ASGI 应用：

```bash
uvicorn backend.core.web.webAPI:app --host 0.0.0.0 --port 51024
```

## 启动前端

```bash
cd frontend
flutter pub get
flutter run
```

通过编译参数覆盖 API 地址：

```bash
flutter run --dart-define=ESA_API_BASE=http://127.0.0.1:51024
```

## 构建 Web

由 Nginx 将 `/api` 反向代理到后端时：

```bash
cd frontend
flutter build web --release --dart-define=ESA_API_BASE=/api
```

构建产物位于 `frontend/build/web/`。根目录的 `frontend-web.tar.gz` 是本地部署包，已被 Git 忽略。

## 开发约定

- 后端新增或修改接口时同步更新 [API.md](API.md)。
- 完成功能后同步勾选 [TODO.md](TODO.md)。
- 不提交数据库、日志、Flutter 构建目录或 `frontend-web.tar.gz`。
- 工具 Schema 从 `backend.agent.tools.tr.schemas` 获取；导出方法见 [DATASET_GENERATION.md](DATASET_GENERATION.md)。
