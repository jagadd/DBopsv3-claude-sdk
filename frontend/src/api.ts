export type AgentEvent =
  | { event: "session"; data: { sessionId: string; mcpServers: { name: string; status: string }[] } }
  | { event: "text"; data: { text: string } }
  | { event: "tool_use"; data: { name: string; input: unknown } }
  | { event: "tool_result"; data: { isError: boolean; content: unknown } }
  | { event: "done"; data: { subtype: string; costUsd: number; turns: number } }
  | { event: "error"; data: { message: string } };

export async function streamChat(
  body: { message: string; sessionId?: string; allowChanges: boolean },
  onEvent: (e: AgentEvent) => void,
  signal: AbortSignal,
) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const event = frame.match(/^event: (.*)$/m)?.[1];
      const data = frame.match(/^data: (.*)$/m)?.[1];
      if (event && data) onEvent({ event, data: JSON.parse(data) } as AgentEvent);
    }
  }
}
