import { query, type CanUseTool, type SDKMessage } from "@anthropic-ai/claude-agent-sdk";
import { config } from "./config.js";

const SYSTEM_PROMPT = `You are a SQL Server DBA assistant. You operate SQL Server instances exclusively through the dbatools MCP tools.

Workflow:
1. Use list_dbatools_commands to find the right command, and get_dbatools_command_help to confirm parameters before invoking.
2. Prefer read-only commands (Get-*, Test-*, Find-*) to inspect state before proposing any change.
3. For installs on a new machine (Install-DbaInstance) or any change/destructive command, first explain exactly what will run and why, then call it with confirm: true only if the user has allowed changes.
4. Summarize results concisely; show tables in markdown when helpful.`;

const READ_ONLY_TOOLS = [
  "mcp__dbatools__list_dbatools_commands",
  "mcp__dbatools__get_dbatools_command_help",
  "mcp__dbatools__check_dbatools_environment",
];

function permissionGate(allowChanges: boolean): CanUseTool {
  return async (toolName, input) => {
    if (toolName === "mcp__dbatools__invoke_dbatools_command" && input.confirm === true && !allowChanges) {
      return {
        behavior: "deny",
        message: "The user has not enabled changes. Explain the proposed change and ask them to enable 'Allow changes'.",
      };
    }
    return { behavior: "allow", updatedInput: input };
  };
}

export function runAgent(prompt: string, opts: { sessionId?: string; allowChanges: boolean; abort: AbortController }) {
  return query({
    prompt,
    options: {
      model: config.model,
      systemPrompt: SYSTEM_PROMPT,
      mcpServers: config.mcpServers,
      tools: [],
      allowedTools: READ_ONLY_TOOLS,
      canUseTool: permissionGate(opts.allowChanges),
      resume: opts.sessionId,
      includePartialMessages: true,
      abortController: opts.abort,
      settingSources: [],
    },
  }) as AsyncIterable<SDKMessage>;
}
