// One instance: its runs side by side — the comparison is the point.

import { esc, fmtDur, fmtTime, fmtTokens, page, statePill } from "./ui.js";

function checksCell(meta) {
  const passed = meta?.checks_passed;
  const total = meta?.checks_total;
  if (total == null || total === 0) return `<span class="text-mute">—</span>`;
  const cls = passed === total ? "text-ok" : "text-warn";
  return `<span class="${cls}">${passed}/${total}</span>`;
}

export function runsTable(fanout, runs) {
  const maxTokens = Math.max(1, ...runs.map((r) => Number(r.tokens_out) || 0));
  const anyActive = runs.some((r) => !["done", "failed"].includes(r.state));
  const refresh = anyActive
    ? `hx-get="/instances/${encodeURIComponent(fanout)}?partial=1" hx-trigger="every 5s" hx-swap="outerHTML"`
    : "";
  return `<div id="runs-table" ${refresh}>
  <table class="w-full border-separate border-spacing-0">
    <thead>
      <tr class="text-left text-[11px] uppercase tracking-wider text-mute">
        <th class="pb-2 font-medium">run</th>
        <th class="pb-2 font-medium">state</th>
        <th class="pb-2 font-medium">model</th>
        <th class="pb-2 font-medium text-right">turns</th>
        <th class="pb-2 font-medium text-right">wall</th>
        <th class="pb-2 font-medium text-right">tokens in</th>
        <th class="pb-2 font-medium text-right">tokens out</th>
        <th class="pb-2 font-medium pl-3"></th>
        <th class="pb-2 font-medium text-right">checks</th>
        <th class="pb-2 font-medium pl-4">exit</th>
      </tr>
    </thead>
    <tbody class="font-mono text-[13px] tabular-nums">
      ${runs
        .map((r) => {
          const href = `/instances/${encodeURIComponent(fanout)}/runs/${encodeURIComponent(r.run_id)}`;
          const width = Math.round(((Number(r.tokens_out) || 0) / maxTokens) * 100);
          return `
      <tr class="group cursor-pointer" onclick="location='${href}'">
        <td class="py-2 border-t border-edge pr-4">
          <a href="${href}" class="text-ink group-hover:text-accent">${esc(r.run_id)}</a>
        </td>
        <td class="py-2 border-t border-edge pr-4">${statePill(r.state)}</td>
        <td class="py-2 border-t border-edge text-sub pr-4">${esc(r.model ?? "—")}</td>
        <td class="py-2 border-t border-edge text-right text-ink">${r.num_turns ?? "—"}</td>
        <td class="py-2 border-t border-edge text-right text-sub">${fmtDur(r.wall_seconds)}</td>
        <td class="py-2 border-t border-edge text-right text-sub">${fmtTokens(r.tokens_in)}</td>
        <td class="py-2 border-t border-edge text-right text-ink">${fmtTokens(r.tokens_out)}</td>
        <td class="py-2 border-t border-edge pl-3 w-24">
          <div class="h-1 rounded-full bg-edge overflow-hidden"><div class="h-full bg-accent/60" style="width:${width}%"></div></div>
        </td>
        <td class="py-2 border-t border-edge text-right">${checksCell(r.meta)}</td>
        <td class="py-2 border-t border-edge text-sub pl-4">${esc(r.exit_reason ?? "—")}</td>
      </tr>`;
        })
        .join("")}
    </tbody>
  </table>
  </div>`;
}

export function instancePage({ meta, runs, leaks }, { hasComparison, active }) {
  const fanout = meta.fanout;
  const body = `
  <div class="flex items-baseline justify-between mb-6">
    <div>
      <h1 class="font-mono text-xl text-ink">${esc(fanout)}</h1>
      <div class="text-sub mt-1">config <span class="font-mono">${esc(meta.name)}</span> · created ${fmtTime(meta.created_at)}</div>
    </div>
    <div class="flex gap-2">
      ${
        hasComparison
          ? `<a href="/artifacts/${encodeURIComponent(fanout)}/comparison.md" class="px-3 py-1.5 rounded border border-accent/40 text-accent hover:bg-accent/10 text-xs font-mono">comparison.md</a>`
          : ""
      }
      <a href="/artifacts/${encodeURIComponent(fanout)}" class="px-3 py-1.5 rounded border border-edge2 text-sub hover:text-ink hover:border-edge2 text-xs font-mono">artifacts/</a>
    </div>
  </div>
  ${
    leaks.length
      ? `<div class="mb-6 border border-warn/40 bg-warn/5 rounded-md px-4 py-3">
          <div class="text-warn text-xs font-medium uppercase tracking-wider mb-1">unreleased resources</div>
          <div class="font-mono text-[13px] text-sub">${leaks
            .map((l) => `run ${esc(l.run_id)}: ${esc(l.kind)} — ${esc(l.status)}`)
            .join("<br>")}</div>
        </div>`
      : ""
  }
  ${runsTable(fanout, runs)}
  <details class="mt-8">
    <summary class="text-sub hover:text-ink text-xs uppercase tracking-wider">submitted config</summary>
    <pre class="mt-3 bg-panel border border-edge rounded-md p-4 font-mono text-xs text-sub overflow-x-auto">${esc(meta.config_yaml)}</pre>
  </details>`;
  return page({
    title: fanout,
    active: "instances",
    crumbs: [
      ["/instances", "instances"],
      [null, fanout],
    ],
    body,
    activeRuns: active,
  });
}
