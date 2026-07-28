// trace.jsonl -> display events. The runner streams every Agent SDK
// message to disk as it happens; this is the one place that knows the
// wire shapes, so the views never do.
//
// One trace line can yield several events (an assistant message holds
// thinking + text + tool calls). Unknown shapes degrade to nothing
// rather than crashing the stream — the trace outlives SDK versions.

export function parseLine(line) {
  let d;
  try {
    d = JSON.parse(line);
  } catch {
    return []; // partial line mid-append; the tailer retries it whole
  }
  const m = d.message || {};
  switch (d.type) {
    case "SystemMessage": {
      const data = m.data || {};
      if (m.subtype !== "init") return [];
      return [
        {
          kind: "init",
          model: data.model || "",
          cwd: data.cwd || "",
          tools: Array.isArray(data.tools) ? data.tools.length : 0,
          session: data.session_id || "",
        },
      ];
    }
    case "AssistantMessage": {
      const out = [];
      for (const block of m.content || []) {
        if (typeof block.thinking === "string" && block.thinking) {
          out.push({ kind: "thinking", text: block.thinking });
        } else if (typeof block.text === "string" && block.text) {
          out.push({ kind: "text", text: block.text });
        } else if (block.name) {
          out.push({ kind: "tool_use", name: block.name, input: block.input || {} });
        }
      }
      return out;
    }
    case "UserMessage": {
      const out = [];
      const content = Array.isArray(m.content) ? m.content : [];
      for (const block of content) {
        if (!block.tool_use_id) continue;
        out.push({
          kind: "tool_result",
          error: Boolean(block.is_error),
          text: resultText(block.content),
        });
      }
      return out;
    }
    case "ResultMessage":
      return [
        {
          kind: "result",
          error: Boolean(m.is_error),
          turns: m.num_turns ?? null,
          duration_ms: m.duration_ms ?? null,
          cost: m.total_cost_usd ?? null,
          text: typeof m.result === "string" ? m.result : "",
        },
      ];
    default:
      return [];
  }
}

function resultText(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((c) => (typeof c === "string" ? c : c?.text || ""))
      .filter(Boolean)
      .join("\n");
  }
  return "";
}
