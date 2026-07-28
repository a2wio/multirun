// Shared shell and small parts. Views are template literals over data —
// no engine, no build step; the browser gets tailwind and htmx off the
// CDN and that's the whole frontend.

const TZ = process.env.DASH_TZ || "Europe/Sofia";

export function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function fmtTime(d) {
  if (!d) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ,
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(d));
}

export function fmtAgo(d) {
  if (!d) return "—";
  const s = Math.max(0, (Date.now() - new Date(d).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function fmtDur(seconds) {
  if (seconds == null) return "—";
  const s = Math.round(Number(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function fmtTokens(n) {
  if (n == null) return "—";
  const v = Number(n);
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return String(v);
}

// state -> {dot, text} classes; the state NAME is always printed beside
// the dot, so color never carries the meaning alone
const STATES = {
  done: ["bg-ok", "text-ok"],
  failed: ["bg-bad", "text-bad"],
  running: ["bg-run animate-pulse", "text-run"],
  pending: ["bg-mute", "text-sub"],
};
const TRANSITIONAL = ["bg-warn", "text-warn"];

export function statePill(state) {
  const [dot, text] = STATES[state] || TRANSITIONAL;
  return `<span class="inline-flex items-center gap-1.5 whitespace-nowrap">
    <span class="h-1.5 w-1.5 rounded-full ${dot}"></span>
    <span class="${text} text-xs font-mono">${esc(state ?? "unknown")}</span>
  </span>`;
}

export function statTile(label, value, sub = "") {
  return `<div class="bg-panel border border-edge rounded-md px-4 py-3">
    <div class="text-[11px] uppercase tracking-wider text-mute">${esc(label)}</div>
    <div class="mt-1 font-mono text-2xl text-ink tabular-nums">${value}</div>
    ${sub ? `<div class="mt-0.5 text-xs text-sub">${sub}</div>` : ""}
  </div>`;
}

const NAV = [
  ["/instances", "instances"],
  ["/live", "live"],
  ["/artifacts", "artifacts"],
];

export function page({ title, active, crumbs = [], body, activeRuns = 0 }) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} · multirun</title>
<script src="https://cdn.tailwindcss.com?plugins=typography"></script>
<script>
tailwind.config = {
  theme: { extend: {
    colors: {
      bg: '#0a0c10', panel: '#10141b', panel2: '#151a23',
      edge: '#1c2330', edge2: '#2b3444',
      ink: '#dce3ec', sub: '#8b95a4', mute: '#5b6572',
      accent: '#00e599', ok: '#3fb98f', bad: '#f47067',
      run: '#58a6ff', warn: '#d4a72c',
    },
    fontFamily: {
      sans: ['Inter', 'system-ui', 'sans-serif'],
      mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
    },
  } }
}
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
<script src="https://unpkg.com/htmx-ext-ws@2.0.2/ws.js"></script>
<style>
  * { scrollbar-width: thin; scrollbar-color: #2b3444 transparent; }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: #2b3444; border-radius: 4px; }
  details > summary { cursor: pointer; list-style: none; }
  details > summary::-webkit-details-marker { display: none; }
  .diff-add { color: #3fb98f; } .diff-del { color: #f47067; }
  .diff-hunk { color: #58a6ff; }
</style>
</head>
<body class="bg-bg text-ink font-sans text-sm antialiased">
<div class="flex min-h-screen">
  <aside class="w-52 shrink-0 border-r border-edge bg-panel flex flex-col sticky top-0 h-screen">
    <a href="/instances" class="px-5 pt-5 pb-4 block">
      <div class="font-mono font-medium text-base text-ink">multirun<span class="text-accent">_</span></div>
      <div class="text-[11px] text-mute mt-0.5">agent bench</div>
    </a>
    <nav class="px-2 space-y-0.5">
      ${NAV.map(
        ([href, label]) => `
      <a href="${href}" class="flex items-center justify-between px-3 py-1.5 rounded ${
        active === label
          ? "bg-panel2 text-ink border-l-2 border-accent"
          : "text-sub hover:text-ink hover:bg-panel2 border-l-2 border-transparent"
      }">
        <span>${label}</span>
        ${
          label === "live" && activeRuns > 0
            ? `<span class="font-mono text-[10px] px-1.5 rounded-full bg-run/20 text-run">${activeRuns}</span>`
            : ""
        }
      </a>`,
      ).join("")}
    </nav>
    <div class="mt-auto px-5 py-4 text-[11px] text-mute border-t border-edge">
      read-only observer
    </div>
  </aside>
  <main class="flex-1 min-w-0">
    <header class="border-b border-edge px-8 py-3 flex items-center gap-2 text-sub sticky top-0 bg-bg/90 backdrop-blur z-10">
      ${crumbs
        .map(([href, label]) =>
          href
            ? `<a href="${href}" class="hover:text-ink">${esc(label)}</a><span class="text-mute">/</span>`
            : `<span class="text-ink font-medium">${esc(label)}</span>`,
        )
        .join("")}
    </header>
    <div class="px-8 py-6">${body}</div>
  </main>
</div>
</body>
</html>`;
}
