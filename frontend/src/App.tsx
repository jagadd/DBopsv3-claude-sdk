import { useRef, useState } from "react";
import { streamChat } from "./api";

type Item =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "tool"; name: string; input: unknown; result?: string; isError?: boolean }
  | { kind: "status"; text: string };

const SAMPLES = [
  "Check the dbatools environment",
  "Connect to sql01 and list databases with size and recovery model",
  "What would it take to install SQL Server 2022 Developer on a new machine named sql02?",
];

export function App() {
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [allowChanges, setAllowChanges] = useState(false);
  const sessionId = useRef<string | undefined>(undefined);
  const abort = useRef<AbortController | undefined>(undefined);

  const append = (item: Item) => setItems((prev) => [...prev, item]);
  const appendText = (text: string) =>
    setItems((prev) => {
      const last = prev[prev.length - 1];
      if (last?.kind === "assistant") return [...prev.slice(0, -1), { ...last, text: last.text + text }];
      return [...prev, { kind: "assistant", text }];
    });
  const attachResult = (result: string, isError: boolean) =>
    setItems((prev) => {
      const i = prev.findLastIndex((it) => it.kind === "tool" && it.result === undefined);
      if (i < 0) return prev;
      const next = [...prev];
      next[i] = { ...(prev[i] as Extract<Item, { kind: "tool" }>), result, isError };
      return next;
    });

  async function send(message: string) {
    if (!message.trim() || busy) return;
    setInput("");
    setBusy(true);
    append({ kind: "user", text: message });
    abort.current = new AbortController();
    try {
      await streamChat(
        { message, sessionId: sessionId.current, allowChanges },
        (e) => {
          switch (e.event) {
            case "session":
              sessionId.current = e.data.sessionId;
              break;
            case "text":
              appendText(e.data.text);
              break;
            case "tool_use":
              append({ kind: "tool", name: e.data.name.replace("mcp__dbatools__", ""), input: e.data.input });
              break;
            case "tool_result":
              attachResult(
                typeof e.data.content === "string" ? e.data.content : JSON.stringify(e.data.content, null, 2),
                e.data.isError,
              );
              break;
            case "done":
              append({ kind: "status", text: `${e.data.subtype} · ${e.data.turns} turns · $${e.data.costUsd?.toFixed(4)}` });
              break;
            case "error":
              append({ kind: "status", text: `Error: ${e.data.message}` });
              break;
          }
        },
        abort.current.signal,
      );
    } catch (err) {
      if (!abort.current?.signal.aborted) append({ kind: "status", text: `Error: ${(err as Error).message}` });
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    abort.current?.abort();
    sessionId.current = undefined;
    setItems([]);
  }

  return (
    <div className="app">
      <header>
        <h1>dbatools Agent</h1>
        <label className={allowChanges ? "danger" : ""}>
          <input type="checkbox" checked={allowChanges} onChange={(e) => setAllowChanges(e.target.checked)} />
          Allow changes
        </label>
        <button onClick={reset}>New session</button>
      </header>

      <main>
        {items.length === 0 && (
          <div className="samples">
            {SAMPLES.map((s) => (
              <button key={s} onClick={() => send(s)}>{s}</button>
            ))}
          </div>
        )}
        {items.map((it, i) => {
          switch (it.kind) {
            case "user":
              return <div key={i} className="msg user">{it.text}</div>;
            case "assistant":
              return <div key={i} className="msg assistant">{it.text}</div>;
            case "tool":
              return (
                <details key={i} className={`tool ${it.isError ? "error" : ""}`}>
                  <summary>{it.result === undefined ? "⏳" : it.isError ? "✗" : "✓"} {it.name}</summary>
                  <pre>{JSON.stringify(it.input, null, 2)}</pre>
                  {it.result && <pre>{it.result}</pre>}
                </details>
              );
            case "status":
              return <div key={i} className="status">{it.text}</div>;
          }
        })}
      </main>

      <form onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
          placeholder="Ask about a SQL Server instance, or plan an install…"
          rows={2}
        />
        {busy ? <button type="button" onClick={() => abort.current?.abort()}>Stop</button> : <button type="submit">Send</button>}
      </form>
    </div>
  );
}
