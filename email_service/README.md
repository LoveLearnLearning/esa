# ESA 独立邮件服务

> 最后核对：2026-09-08，代码基线 `main@c485941`。

本服务部署在独立服务器，接收超算 ESA 后端的认证请求，再通过 Resend 投递验证码。
它不保存用户、密码或验证码验证状态，也不向前端开放。

## 配置

复制 `.env.example` 中的变量到服务器环境。用 `openssl rand -hex 32` 生成
`MAIL_SERVICE_TOKEN`，并把同一个值通过超算进程环境配置为
`ESA_EMAIL_SERVICE_TOKEN`；不要修改受 Git 跟踪的 `config.py` 保存密钥。

```bash
MAIL_SERVICE_TOKEN=<随机服务令牌>
RESEND_API_KEY=re_xxxxxxxxx
MAIL_FROM=星知智链 <verify@notify.lovelearnlearning.cn>
```

## 启动

邮件服务器只需要 `email_service/` 目录。在该目录执行：

```bash
docker build -t esa-mail-service .
docker run --env-file .env -p 127.0.0.1:8080:8080 esa-mail-service
```

在 Nginx 或 Caddy 上为该端口提供 HTTPS，例如使用
`mail-api.lovelearnlearning.cn`。超算进程环境中的 `ESA_EMAIL_SERVICE_URL` 填写这个
HTTPS 地址，并将 `ESA_EMAIL_PROVIDER=service`。
服务令牌会保护投递接口；还应在云防火墙中尽可能只允许超算出口 IP 访问该域名。

验证码摘要 Secret 由 ESA 后端单独使用，配置为
`ESA_EMAIL_VERIFICATION_SECRET`，必须与 `MAIL_SERVICE_TOKEN` 使用不同随机值。
TTL、冷却、尝试次数和小时限额当前在后端代码中固定为 600 秒、60 秒、5 次、
每邮箱 5 次/小时和每 IP 20 次/小时；`.env` 不能覆盖这些值。

健康检查为 `GET /health`。内部投递接口是
`POST /internal/v1/verification-email`，仅供 ESA 后端调用。
