# ESA 独立邮件服务

本服务部署在独立服务器，接收超算 ESA 后端的认证请求，再通过 Resend 投递验证码。
它不保存用户、密码或验证码验证状态，也不向前端开放。

## 配置

复制 `.env.example` 中的变量到服务器环境。用 `openssl rand -hex 32` 生成
`MAIL_SERVICE_TOKEN`，并把同一个值配置为超算 `config.py` 中的
`EMAIL_SERVICE_TOKEN`。

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
`mail-api.lovelearnlearning.cn`。超算 `config.py` 中的 `EMAIL_SERVICE_URL` 填写这个
HTTPS 地址。
服务令牌会保护投递接口；还应在云防火墙中尽可能只允许超算出口 IP 访问该域名。

健康检查为 `GET /health`。内部投递接口是
`POST /internal/v1/verification-email`，仅供 ESA 后端调用。
