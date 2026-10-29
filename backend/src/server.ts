import express from "express";
import { config } from "./config.js";
import { runAgent } from "./agent.js";

const app = express();
app.use(express.json());

app.get("/api/health", (_req, res) => {
  const mcp = config.mcpServers.dbatools;
  res.json({
    ok: true,
    provider: config.provider,
    resource: config.resource,
    model: config.model,
    mcp: mcp.type === "http" ? mcp.url : "stdio",
  });
});

app.post("/api/chat", async (req, res) => {
  const { message, sessionId, allowChanges } = req.body ?? {};
  if (typeof message !== "string" || !message.trim()) {
    res.status(400).json({ error: "message is required" });
    return;
  }

  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
  const send = (event: string, data: unknown) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

  const abort = new AbortController();
  res.on("close", () => abort.abort());

  try {
    for await (const msg of runAgent(message, { sessionId, allowChanges: allowChanges === true, abort })) {
      switch (msg.type) {
        case "system":
          if (msg.subtype === "init") {
            send("session", { sessionId: msg.session_id, mcpServers: msg.mcp_servers });
          }
          break;
        case "stream_event":
          if (msg.event.type === "content_block_delta" && msg.event.delta.type === "text_delta") {
            send("text", { text: msg.event.delta.text });
          }
          break;
        case "assistant":
          for (const block of msg.message.content) {
            if (block.type === "tool_use") send("tool_use", { name: block.name, input: block.input });
          }
          break;
        case "user":
          if (Array.isArray(msg.message.content)) {
            for (const block of msg.message.content) {
              if (typeof block === "object" && block.type === "tool_result") {
                send("tool_result", { isError: block.is_error ?? false, content: block.content });
              }
            }
          }
          break;
        case "result":
          send("done", { subtype: msg.subtype, costUsd: msg.total_cost_usd, turns: msg.num_turns });
          break;
      }
    }
  } catch (err) {
    if (!abort.signal.aborted) send("error", { message: err instanceof Error ? err.message : String(err) });
  }
  res.end();
});

app.listen(config.port, () => console.log(`backend listening on http://localhost:${config.port}`));
