# ESA Flutter 客户端

> 最后核对：2026-09-08，代码基线 `main@c485941`。

该目录是星知智链的 Flutter 多端客户端，不是 Flutter 模板工程。学生与教师登录后进入不同 Shell，共享认证、API、主题、会话和基础组件。

## 主要入口

| 路径 | 功能 |
|---|---|
| `lib/main.dart` | 应用启动、Session 恢复、主题和角色 Shell |
| `lib/state/app_state.dart` | 认证、Workspace、对话、分组、课表、学习、教学和科研状态编排 |
| `lib/api/api_client.dart` | REST、SSE、附件、教学、科研、个人知识库与 LSP URL 契约 |
| `lib/pages/home_shell.dart` | 学生学习/作业/日程/知识/资料库/科研入口 |
| `lib/pages/teacher_shell.dart` | 教师教学工作台与教学助手 |
| `lib/pages/research_project_page.dart` | 项目资料、写作与数据任务 |
| `lib/widgets/` | Composer、Markdown/LaTeX、工具卡、Monaco、附件预览、记忆与 Profile |
| `lib/theme/` | 深浅色主题、移动端尺寸与上下文样式 |

## API 地址

`ApiClient` 的默认值：

- Flutter Web：同源 `/api`
- 原生平台：`https://esa.lovelearnlearning.cn/api`

本地开发使用编译参数覆盖：

```bash
flutter run --dart-define=ESA_API_BASE=http://127.0.0.1:51024/api
```

Web release 脚本固定使用同源 `/api`：

```bash
./scripts/build_web_release.sh
```

## 运行

需要与 `pubspec.yaml` 匹配的 Flutter/Dart SDK：

```bash
flutter pub get
flutter run
```

应用代码中的 `kOfflineMode` 当前为 `false`，默认连接真实后端。不要为演示临时改成离线假数据后再把结果描述为真实系统运行。

## 测试与构建

```bash
flutter analyze
flutter test --concurrency=1
flutter build web --release --dart-define=ESA_API_BASE=/api
```

视觉审计依赖固定浏览器、字体和视口；跨环境 golden 漂移应单独报告，不能通过覆盖基线掩盖布局问题。

2026-09-08 当前工作机没有可用的 `flutter` 命令，因此本轮未复跑 analyze/test/build。最近一次有记录的完整前端验证是 2026-09-05 的历史审查，不能作为当前源代码的新结论。

## Web 部署

- Nginx 必须原样代理 `/api`，并为 SSE 关闭缓冲、为 LSP WebSocket 配置 Upgrade。
- `client_max_body_size` 不得低于后端附件上限 200 MiB。
- release 脚本会生成预压缩资源；服务端使用 `gzip_static on` 才会直接返回。
- Service Worker 策略必须与发布流程一致，避免旧 `main.dart.js` 长期缓存。

完整接口见仓库根目录 `API.md`，移动端实现规则见 `docs/mobile-design-system.md`。
