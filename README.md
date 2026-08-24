# ESA - 面向计算机学科建设的可信教学研智能体

ESA（Efficient Study Agent）服务于计算机学科的一流本科建设：以课程知识图谱、可追溯检索和受控智能体为底座，让学生学习、教师教学与科研协作不再是三个割裂的工具，而是一条由真实证据驱动的闭环。

它不把大模型当作“万能聊天框”。每次可靠的作答、教师复核和科研资料处理都被约束在明确的角色、课程、班级或项目边界中，并在需要时回到知识点、掌握度和下一步教学行动。

> 当前聚焦计算机学科。完整竞赛产品叙事、评审映射和可对外使用的表述见 [PRODUCT_NARRATIVE.md](PRODUCT_NARRATIVE.md)。后端接口以 [API.md](API.md) 为准；待完成事项以 [TODO.md](TODO.md) 为准。

## 三个真实场景

| 场景 | 用户问题 | ESA 的闭环 |
|---|---|---|
| 助学 | 学生需要符合自身基础的讲解、练习与复习路径 | 将课程问答和真实作答映射到个人知识地图、掌握度、前置知识点与后续练习。 |
| 助教 | 教师要高效处理开放题，又不能把评分责任交给模型 | 教师建班、发布作业，AI 提供受约束的分析建议，教师复核并发布，正式反馈再回流学生与班级学情。 |
| 助研 | 科研检索、趋势判断与写作需要效率，更需要证据边界 | 项目化地组织资料、arXiv 前沿追踪和写作任务；缺少来源时明确标记，禁止虚构文献、数据和结论。 |

## 核心能力

- **计算机学科知识底座**：覆盖程序设计、数据结构与算法、系统、操作系统、网络、数据库、编译、软件工程和人工智能导论等课程的知识点及前置依赖。
- **个性化学习支持**：Student Model V2、个人知识地图、掌握度、薄弱点、提示历史与复习建议共同调节讲解和练习；未知知识不被误判为薄弱。
- **教师主导的作业诊断**：支持简答题和代码文本题、批量 AI 分析、逐题教师复核、反馈发布及班级薄弱知识点和前置根因分析。AI 不会自动发布成绩或提前改写学生掌握度。
- **有边界的科研辅助**：研究项目、项目画像、文献检索、前沿追踪、研究数据与写作任务均有资源范围；写作助手仅使用已提供材料，不编造引用、实验数据或结论。
- **可追溯、可治理**：RAG 返回来源定位；学习、教学和科研空间使用独立身份、资源和能力视图；关键教学操作写入只追加审计记录。
- **统一课表入口**：支持文件识别与华科统一身份认证导入；教务凭据仅用于当次 HTTPS 请求，不写入 ESA 数据库。
- **可运行的工程基础**：FastAPI、vLLM、Flutter 和 SQLite 支持多用户认证、持久化、SSE 流式交互、受控工具调用、跨 Worker 对话串行化和 Web/macOS/iOS 构建。

## 推荐 Demo

用教师与学生两个真实账号完成以下流程，最能展示 ESA 的产品价值：

```text
教师创建班级并发布带知识点标签的作业
  -> 学生提交答案
  -> ESA 输出结构化分析建议
  -> 教师复核得分、错因与知识点并发布反馈
  -> 反馈回流个人掌握度和班级学情
  -> 学生获得针对性讲解与练习，教师看到薄弱点及前置关系
```

详见 [TEACHING_STUDENT_DEMO.md](TEACHING_STUDENT_DEMO.md)。

## 可信边界

- RAG 结果必须提供真实来源定位；没有检索证据时不得伪造引用。
- 教师只能访问本人班级的教学证据，不能读取学生私人对话、记忆、科研项目或无关附件。
- 学生只能读取自己的提交和已发布反馈；教师确认前的 AI 建议、评分规则和参考答案不会暴露给学生。
- 用户、会话、记忆和项目资源按身份隔离；AI 生成内容、数据脱敏和部署合规材料需在提交前按赛题要求完善。

## 项目地图

```text
backend/                  FastAPI、Agent、vLLM、RAG、工具、工作流与数据存储
frontend/                 Flutter 多端前端
PRODUCT_NARRATIVE.md      竞赛方案、答辩与 Demo 可复用的产品叙事
TEACHING_STUDENT_DEMO.md  教师端与学生端的可运行闭环和双账号脚本
API.md                    前后端接口约定
TODO.md                   唯一待办清单与已知边界
DATASET_GENERATION.md     Qwen3.5/LLaMA-Factory 数据集方案
OPTIMIZATION_NOTES.md     已完成的工程优化、修复与验证记录
documents/HUST_TIMETABLE_IMPORT.md  华科教务导入调研、配置与验收说明
REQUEST.md                项目需求和阶段状态
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

### 配置 You.com MCP 搜索

`web_search` 通过后端随生命周期启动的本地 STDIO 子进程调用 You.com 官方 MCP，
不再依赖 SearXNG。先确保超算环境安装 Node.js 18 以上版本，并安装新增的 Python
依赖：

```bash
python -m pip install -r requirements.txt
node --version
npx --version
```

在启动 Slurm 作业或后端前设置 API Key：

```bash
export YDC_API_KEY='你的 You.com API Key'
./backend/scripts/run_esa_stack.sh
```

后端固定启动 `npx --yes @youdotcom-oss/mcp@3.5.0`，并通过
`YDC_ALLOWED_TOOLS=you-search` 只开放搜索工具。FastAPI 启动时初始化 MCP Session，
退出时关闭 Session、stdin 和整个子进程组；生命周期与用户请求日志使用
`owner=MCP` 写入 `logs/backend.log`。Key 只从超算进程环境读取，不写入仓库或日志。

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

超算不需要 `.env`。复制只在服务器本地存在、已被 Git 忽略的私有配置：

```bash
cp backend/core/utils/config_private.example.py backend/core/utils/config_private.py
chmod 600 backend/core/utils/config_private.py
```

然后在 `config_private.py` 中填写邮件服务地址、服务令牌和验证码 Secret。
不要修改受 Git 跟踪的 `config.py` 来保存密钥。

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
./frontend/scripts/build_web_release.sh
```

脚本会构建 `frontend/build/web/`，为 JS、WASM、JSON、SVG、CSS 和 HTML 生成 `.gz`
预压缩文件，并在根目录创建 `frontend-web.tar.gz`。压缩包解压后只有一个 `esa/`
顶层目录。禁用 Flutter PWA 缓存可避免替换静态文件后浏览器继续运行旧版
`main.dart.js`。Nginx 必须启用 `gzip_static on;` 才会直接返回预压缩文件，完整配置见
[`deploy/nginx/esa-web.conf.example`](deploy/nginx/esa-web.conf.example)。

聊天附件默认最大 200 MB，后端配置为 `ESA_USER_ATTACHMENT_MAX_BYTES=209715200`。
Nginx 的 `/api/` 代理也必须配置 `client_max_body_size 200m;`，修改后执行
`sudo nginx -t && sudo systemctl reload nginx`。上传阶段只保存源文件；PDF、Word、PPT、
Excel 和图片会在聊天过程中由模型选择对应 Skill 和 Tool 后解析。文件保存在
`backend/data/user/{user_id}/{conversation_id}/{attachment_id}/`，主动删除附件或对话时清理。

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
