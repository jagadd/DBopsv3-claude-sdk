# dbatools Agent App

A web app where a Claude Agent SDK agent manages SQL Server through the dbatools MCP server.

```
React (Vite, :5173) ──SSE──> Express + Claude Agent SDK (:3001) ──HTTPS / stdio──> dbatools MCP server ──> SQL Server
```

- **backend/** — `POST /api/chat` runs `query()` from `@anthropic-ai/claude-agent-sdk` and streams text, tool calls, and tool results as Server-Sent Events. Sessions continue via `resume`.
- **frontend/** — Chat UI with collapsible tool-call cards, an **Allow changes** toggle, and a **New session** button.

## Safety model

- All built-in Claude Code tools (Bash, file read/write, web) are disabled (`tools: []`). The agent can only use dbatools MCP tools.
- Discovery tools (`list_dbatools_commands`, `get_dbatools_command_help`, `check_dbatools_environment`) are auto-allowed.
- `invoke_dbatools_command` with `confirm: true` (Set-/New-/Install-/Remove-… commands) is denied by `canUseTool` unless **Allow changes** is ticked. Keep `DBATOOLS_SAFE_MODE=true` on the MCP server so this gate has effect.

## Setup

```bash
npm install && npm run install:all
cp backend/.env.example backend/.env   # set ANTHROPIC_API_KEY and DBATOOLS_MCP_URL
npm run dev                            # http://localhost:5173
```

Set `DBATOOLS_MCP_URL` to your HTTPS fork's MCP endpoint (and `DBATOOLS_MCP_TOKEN` if it requires a bearer token). Leave it empty and set `DBATOOLS_MCP_COMMAND` to use a local stdio server instead. The MCP host needs PowerShell 7 and the dbatools module, and must reach the SQL Server instances (or the target machine for `Install-DbaInstance`).

## Next steps

- Interactive approval: forward each `canUseTool` request to the UI and wait for Approve/Deny instead of the global toggle.
- Credential handling: keep SQL credentials server-side (vault/env) rather than in chat prompts.
- Auth on the backend and persistent session storage.
