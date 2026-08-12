# ESA - Efficient Study Agent

ESA 是一个面向学习场景的多用户 Agent 项目，由 FastAPI 后端、vLLM 推理服务和 Flutter 多端前端组成。

> 文档状态：2026-08-09。后端接口以 [API.md](API.md) 为准，剩余任务以
> [TODO.md](TODO.md) 为准，已完成的工程改造见
> [OPTIMIZATION_NOTES.md](OPTIMIZATION_NOTES.md)。

## 当前能力

- 邮箱验证码注册、邮箱或用户名登录、老用户绑定邮箱、修改密码和 7 天会话保持
- Qwen3.5-122B 主模型通过 vLLM 异步引擎提供推理
- 独占第 5 张 GPU 的 Qwen3.5-9B 辅助服务负责课表解析和离线对话压缩
- 对话与消息持久化、同步回复和 SSE 流式回复
- 同一对话跨 Worker 串行生成，不同对话可以并行
- 模型思考内容、工具调用、Markdown、LaTeX 与代码高亮展示
- 核心记忆管理、用户偏好、学情档案、Student Model V2、个人知识地图和复习推荐
- 多用户课表、第一周日期自动定位、PDF/图片/HTML 智能导入和移动端磁贴课表
- 数值计算、位运算、符号计算、Web 搜索和 arXiv 搜索等工具
- 对话分组与分组内自定义指令（后端已实现，含分组级风格/语调/指令覆盖用户级，前端待对接）
- Flutter Web、macOS、iOS 等多端构建基础

## 目录

```text
backend/                 FastAPI、Agent、vLLM、工具和数据存储
frontend/                Flutter 前端
API.md                   前后端接口约定
TODO.md                  当前待办
DATASET_GENERATION.md    Qwen3.5/LLaMA-Factory 数据集方案
GROUP_FEATURE.md         对话分组功能设计
MEMORY_PROMPT_ANALYSIS.md 记忆与提示词评估
OPTIMIZATION_NOTES.md    已完成的工程优化、修复与验证记录
REQUEST.md               项目需求和阶段状态
SUBMITTION.md            按时间追加的历史开发记录
```

## 启动后端

先在 `backend/core/utils/config.py` 配置主模型、辅助模型和推理参数。超算环境必须先通过
Slurm 获得 5 张 GPU（主模型 TP=4，辅助模型 TP=1），再从仓库根目录运行；不要在登录节点直接加载模型：

```bash
./run.sh
```

可复现的双模型启动实现位于 `backend/scripts/run_esa_stack.sh`。辅助服务仅监听
`127.0.0.1:51025`，不会对公网开放；它不可用时后端会保持启动，但课表智能导入和后台
对话压缩会暂时返回不可用。用户退出或超过 5 分钟没有认证请求后，后台会在保留最近
8 条原始消息及全部历史记录的前提下，为较早消息生成上下文摘要。

默认监听 `0.0.0.0:51024`，可通过 `HOST`、`PORT` 覆盖。生产 API 的
canonical prefix 是 `/api`；旧的无前缀路径仅作为迁移期兼容别名。也可以直接启动 ASGI 应用：

```bash
uvicorn backend.core.web.webAPI:app --host 0.0.0.0 --port 51024
```

## 启动前端

```bash
cd frontend
flutter pub get
flutter run
```

## 配置验证邮件（超算 + 独立邮件服务器）

验证码由超算上的 ESA 后端生成、摘要存储和校验；另一台服务器只运行
[`email_service`](email_service)，负责邮件模板和 Resend 投递。前端始终只访问 ESA，
不能直接访问邮件服务。两台服务器之间使用 HTTPS 和共享服务令牌认证。

先在 Resend 添加发信子域名 `notify.lovelearnlearning.cn`，再按 Resend 控制台给出的
准确值添加 SPF、DKIM DNS 记录，并等待状态变为 Verified。

在独立邮件服务器配置：

```bash
MAIL_SERVICE_TOKEN=<openssl rand -hex 32>
RESEND_API_KEY=re_xxxxxxxxx
MAIL_FROM=星知智链 <verify@notify.lovelearnlearning.cn>
```

将其部署在 HTTPS 地址（例如 `https://mail-api.lovelearnlearning.cn`），并只对外暴露
反向代理的 443 端口。邮件服务器只需复制 `email_service/` 目录，在该目录构建：

```bash
docker build -t esa-mail-service .
docker run --env-file .env -p 127.0.0.1:8080:8080 esa-mail-service
```

超算不需要 `.env`。在 `backend/core/utils/config.py` 的邮件配置区填写：

```python
EMAIL_PROVIDER = "service"
EMAIL_SERVICE_URL = "https://mail-api.lovelearnlearning.cn"
EMAIL_SERVICE_TOKEN = "与邮件服务器 MAIL_SERVICE_TOKEN 完全相同"
EMAIL_VERIFICATION_SECRET = "另一个 openssl rand -hex 32 生成值"
```

`EMAIL_VERIFICATION_SECRET` 和服务令牌必须使用两个不同的随机值。Resend API Key
只放在独立邮件服务器，不能放在超算或前端。未配置时验证码接口返回 `503`；投递失败
返回 `502`，验证码不会出现在日志或 API 响应中。

通过编译参数覆盖 API 地址：

```bash
flutter run --dart-define=ESA_API_BASE=http://127.0.0.1:51024/api
```

## 构建 Web

由 Nginx 将 `/api` 原样反向代理到后端时：

```bash
cd frontend
flutter build web --release --dart-define=ESA_API_BASE=/api
```

构建产物位于 `frontend/build/web/`。根目录的 `frontend-web.tar.gz` 是本地部署包，已被 Git 忽略。

## 开发约定

- 后端新增或修改接口时同步更新 [API.md](API.md)。
- 完成功能后同步勾选 [TODO.md](TODO.md)。
- 不提交数据库、日志、模型权重、密钥、集群本地启动/隧道脚本、Flutter 构建目录或
  `frontend-web.tar.gz`；这些内容由根目录 [.gitignore](.gitignore) 统一管理。
- 工具 Schema 从 `backend.agent.tools.tr.schemas` 获取；导出方法见 [DATASET_GENERATION.md](DATASET_GENERATION.md)。

提交前安装开发依赖并运行质量检查：

```bash
python -m pip install -r requirements-dev.txt
make quality
```
