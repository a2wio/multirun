// Render one trace event as HTML. Used only by the ws stream: replay
// and live are the same path, a burst of these followed (or not) by
// more — the client can't tell the difference and shouldn't.

import { esc } from "./ui.js";

const CLIP_LINES = 14;

function clipped(text, cls) {
  const lines = String(text).split("\n");
  if (lines.length <= CLIP_LINES) {
    return `<pre class="${cls} whitespace-pre-wrap break-words">${esc(text)}</pre>`;
  }
  const head = lines.slice(0, CLIP_LINES).join("\n");
  return `<details>
    <summary><pre class="${cls} whitespace-pre-wrap break-words">${esc(head)}</pre>
    <span class="text-mute text-[11px] font-mono">▸ ${lines.length - CLIP_LINES} more lines</span></summary>
    <pre class="${cls} whitespace-pre-wrap break-words">${esc(lines.slice(CLIP_LINES).join("\n"))}</pre>
  </details>`;
}

function toolInputSummary(name, input) {
  if (typeof input?.command === "string") return input.command;
  if (typeof input?.file_path === "string") return input.file_path;
  if (typeof input?.pattern === "string") return input.pattern;
  const json = JSON.stringify(input);
  return json === "{}" ? "" : json;
}

export function renderEvent(ev) {
  switch (ev.kind) {
    case "init":
      return `<div class="py-1.5 text-[12px] font-mono text-mute">
        session start · model ${esc(ev.model || "?")} · ${ev.tools} tools</div>`;
    case "thinking":
      return `<details class="py-1">
        <summary class="text-[11px] font-mono uppercase tracking-wider text-mute hover:text-sub">thinking · ${String(ev.text).length} chars</summary>
        <div class="mt-1 pl-3 border-l border-edge text-sub italic text-[13px] whitespace-pre-wrap break-words">${esc(ev.text)}</div>
      </details>`;
    case "text":
      return `<div class="py-2 pl-3 border-l-2 border-accent/50 text-ink text-[13px] whitespace-pre-wrap break-words">${esc(ev.text)}</div>`;
    case "tool_use": {
      const summary = toolInputSummary(ev.name, ev.input);
      const full = JSON.stringify(ev.input, null, 2);
      const needsFull = full.length > summary.length + 40 && full !== "{}";
      return `<div class="py-1 font-mono text-[12px]">
        <span class="text-run">→ ${esc(ev.name)}</span>
        <span class="text-sub break-all">${esc(summary.slice(0, 300))}${summary.length > 300 ? "…" : ""}</span>
        ${
          needsFull
            ? `<details class="inline"><summary class="text-mute text-[11px] inline hover:text-sub">· input</summary>
               <pre class="mt-1 pl-4 text-mute whitespace-pre-wrap break-words">${esc(full.slice(0, 4000))}</pre></details>`
            : ""
        }
      </div>`;
    }
    case "tool_result": {
      const cls = ev.error
        ? "font-mono text-[12px] text-bad/90"
        : "font-mono text-[12px] text-mute";
      return `<div class="py-1 pl-4">${clipped(ev.text || "(empty)", cls)}</div>`;
    }
    case "result":
      return `<div class="my-2 border ${ev.error ? "border-bad/40 bg-bad/5" : "border-ok/40 bg-ok/5"} rounded px-3 py-2 font-mono text-[12px] ${ev.error ? "text-bad" : "text-ok"}">
        ${ev.error ? "✗ error" : "✓ done"} · ${ev.turns ?? "?"} turns · ${ev.duration_ms != null ? Math.round(ev.duration_ms / 1000) + "s" : "?"}${ev.cost != null ? " · $" + Number(ev.cost).toFixed(2) : ""}
        ${ev.text ? `<div class="mt-1 text-sub whitespace-pre-wrap break-words font-sans text-[13px]">${esc(ev.text.slice(0, 2000))}</div>` : ""}
      </div>`;
    default:
      return "";
  }
}

// wrap for the htmx ws extension: everything arrives as an oob append
export function oobTurn(html) {
  return `<div hx-swap-oob="beforeend:#turns">${html}</div>`;
}

export function oobStatus(text, live) {
  return `<span id="stream-status" hx-swap-oob="true" class="font-mono text-[11px] ${
    live ? "text-run" : "text-mute"
  }">${esc(text)}</span>`;
}
