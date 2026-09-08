# ESA Language Server deployment

> Last verified against `main@c485941` on 2026-09-08. The application-level LSP switch is currently enabled in code; each language remains conditionally available based on its configured executable.

The browser connects to `wss://<frontend-host>/api/lsp/<language>`. Nginx
upgrades that endpoint and the ESA backend authenticates the first WebSocket
message with the existing session token before spawning a stdio language
server.

On the backend host, check which configured servers are available:

```bash
python -m backend.scripts.check_lsp_servers
```

For the C/C++ editor shown in ESA, `clangd` is required. Python uses
`pyright-langserver --stdio`. Commands for other languages are defined in
`backend/core/utils/config.py`; a missing executable disables only that
language and Monaco retains local completion.

The WebSocket authenticates the first client message with the existing ESA
Session. Configure the reverse proxy to preserve `/api/lsp/<language>` and pass
WebSocket `Upgrade`/`Connection` headers. The normal HTTP OpenAPI document does
not include this WebSocket route.

Current limits are defined in code: 24 total sessions, 2 sessions per user,
an 8-second authentication timeout, and a 2 MiB message limit. These are not
environment variables in the current implementation.

After updating the backend files, restart the existing ESA backend process.
No additional Python package is required for the WebSocket bridge.
