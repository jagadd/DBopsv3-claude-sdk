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

export const config = {
  port: Number(process.env.PORT ?? 3001),
  model: process.env.CLAUDE_MODEL ?? "claude-opus-5-5",
  mcpServers: { dbatools: dbatoolsMcp() },
};
