# ESA Language Server deployment

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

After updating the backend files, restart the existing ESA backend process.
No additional Python package is required for the WebSocket bridge.
