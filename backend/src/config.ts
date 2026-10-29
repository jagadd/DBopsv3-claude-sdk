import "dotenv/config";
import type { McpServerConfig } from "@anthropic-ai/claude-agent-sdk";

function dbatoolsMcp(): McpServerConfig {
  const url = process.env.DBATOOLS_MCP_URL;
  if (url) {
    const headers: Record<string, string> = {};
    if (process.env.DBATOOLS_MCP_TOKEN) {
      headers.Authorization = `Bearer ${process.env.DBATOOLS_MCP_TOKEN}`;
    }
    return { type: "http", url, headers };
  }

  const command = process.env.DBATOOLS_MCP_COMMAND;
  if (!command) {
    throw new Error("Set DBATOOLS_MCP_URL (HTTPS) or DBATOOLS_MCP_COMMAND (stdio) in backend/.env");
  }
  return {
    type: "stdio",
    command,
    args: process.env.DBATOOLS_MCP_ARGS?.split(" ").filter(Boolean) ?? [],
    env: {
      DBATOOLS_SAFE_MODE: process.env.DBATOOLS_SAFE_MODE ?? "true",
      PATH: process.env.PATH ?? "",
    },
  };
}

// Claude Code (spawned by the Agent SDK) reads these Foundry variables from process.env itself;
// this only fails fast with a clear message when they're missing.
function foundry() {
  const { CLAUDE_CODE_USE_FOUNDRY, ANTHROPIC_FOUNDRY_RESOURCE, ANTHROPIC_FOUNDRY_BASE_URL, ANTHROPIC_FOUNDRY_API_KEY } =
    process.env;
  if (!CLAUDE_CODE_USE_FOUNDRY || CLAUDE_CODE_USE_FOUNDRY === "0") {
    throw new Error("Set CLAUDE_CODE_USE_FOUNDRY=1 in backend/.env");
  }
  if (!ANTHROPIC_FOUNDRY_RESOURCE && !ANTHROPIC_FOUNDRY_BASE_URL) {
    throw new Error("Set ANTHROPIC_FOUNDRY_RESOURCE (or ANTHROPIC_FOUNDRY_BASE_URL) in backend/.env");
  }
  if (!ANTHROPIC_FOUNDRY_API_KEY) {
    throw new Error("Set ANTHROPIC_FOUNDRY_API_KEY in backend/.env");
  }
  return { provider: "foundry" as const, resource: ANTHROPIC_FOUNDRY_RESOURCE ?? ANTHROPIC_FOUNDRY_BASE_URL };
}

export const config = {
  port: Number(process.env.PORT ?? 3001),
  ...foundry(),
  // On Foundry this is the deployment name.
  model: process.env.CLAUDE_MODEL ?? "claude-opus-5-5",
  mcpServers: { dbatools: dbatoolsMcp() },
};
