// The front page: every fanout/smoke instance the bench has run.
// Desktop gets the dense table; under md the same rows become cards —
// both live inside the one div htmx polls, so they refresh together.

import { emptyState, esc, fmtAgo, fmtDur, fmtTime, fmtTokens, page, statTile } from "./ui.js";

function checksText(r) {
  if (!r.checks_total) return `<span class="text-mute">—</span>`;
  const cls = r.checks_passed === r.checks_total ? "text-ok" : "text-warn";
  return `<span class="${cls}">${r.checks_passed}/${r.checks_total}</span>`;
}

function instanceCards(rows) {
  return `<div class="md:hidden space-y-2">
    ${rows
      .map((r) => {
        const href = `/instances/${encodeURIComponent(r.fanout)}`;
        return `
    <a href="${href}" class="block bg-panel border border-edge rounded-md px-4 py-3 active:bg-panel2">
      <div class="flex items-baseline justify-between gap-3">
        <span class="font-mono text-[13px] text-ink truncate">${esc(r.fanout)}</span>
        <span class="text-[11px] text-mute whitespace-nowrap">${fmtAgo(r.last_activity)}</span>
      </div>
      <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[12px] tabular-nums">
        <span class="text-sub">${r.runs} runs</span>
        <span class="${r.done ? "text-ok" : "text-mute"}">${r.done} done</span>
        <span class="${r.failed ? "text-bad" : "text-mute"}">${r.failed} failed</span>
        ${r.active ? `<span class="text-run">${r.active} active</span>` : ""}
        <span>checks ${checksText(r)}</span>
        <span class="text-sub">${fmtTokens(r.tokens_out)} tok</span>
        <span class="text-sub">${fmtDur(r.avg_wall)} avg</span>
      </div>
    </a>`;
      })
      .join("")}
  </div>`;
}

function instanceTable(rows) {
  return `<div class="hidden md:block overflow-x-auto">
  <table class="w-full border-separate border-spacing-0">
    <thead>
      <tr class="text-left text-[10px] uppercase tracking-[0.14em] text-mute">
        <th class="pb-2 font-medium">instance</th>
        <th class="pb-2 font-medium">created</th>
        <th class="pb-2 font-medium text-right">runs</th>
        <th class="pb-2 font-medium text-right">done</th>
        <th class="pb-2 font-medium text-right">failed</th>
        <th class="pb-2 font-medium text-right">active</th>
        <th class="pb-2 font-medium text-right">checks</th>
        <th class="pb-2 font-medium text-right">tokens out</th>
        <th class="pb-2 font-medium text-right">avg wall</th>
        <th class="pb-2 font-medium text-right">last activity</th>
      </tr>
    </thead>
    <tbody class="font-mono text-[13px] tabular-nums">
      ${rows
        .map(
          (r) => `
      <tr class="group cursor-pointer hover:bg-panel transition-colors" onclick="location='/instances/${encodeURIComponent(r.fanout)}'">
        <td class="py-2 border-t border-edge pr-4">
          <a href="/instances/${encodeURIComponent(r.fanout)}" class="text-ink group-hover:underline underline-offset-4 decoration-edge2">${esc(r.fanout)}</a>
        </td>
        <td class="py-2 border-t border-edge text-sub pr-4">${fmtTime(r.created_at)}</td>
        <td class="py-2 border-t border-edge text-right text-ink">${r.runs}</td>
        <td class="py-2 border-t border-edge text-right ${r.done ? "text-ok" : "text-mute"}">${r.done}</td>
        <td class="py-2 border-t border-edge text-right ${r.failed ? "text-bad" : "text-mute"}">${r.failed}</td>
        <td class="py-2 border-t border-edge text-right ${r.active ? "text-run" : "text-mute"}">${r.active}</td>
        <td class="py-2 border-t border-edge text-right">${checksText(r)}</td>
        <td class="py-2 border-t border-edge text-right text-sub">${fmtTokens(r.tokens_out)}</td>
        <td class="py-2 border-t border-edge text-right text-sub">${fmtDur(r.avg_wall)}</td>
        <td class="py-2 border-t border-edge text-right text-sub">${fmtAgo(r.last_activity)}</td>
      </tr>`,
        )
        .join("")}
    </tbody>
  </table>
  </div>`;
}

export function instancesTable(rows) {
  if (!rows.length) {
    return `<div id="instances-table">${emptyState(
      "nothing has run yet — publish a config and it lands here",
    )}</div>`;
  }
  return `<div id="instances-table" hx-get="/instances?partial=1" hx-trigger="every 8s" hx-swap="outerHTML">
    ${instanceCards(rows)}
    ${instanceTable(rows)}
  </div>`;
}

export function instancesPage(rows, active) {
  const totals = rows.reduce(
    (a, r) => ({
      runs: a.runs + r.runs,
      done: a.done + r.done,
      failed: a.failed + r.failed,
      tokens: a.tokens + Number(r.tokens_out),
    }),
    { runs: 0, done: 0, failed: 0, tokens: 0 },
  );
  const body = `
  <div class="grid grid-cols-2 md:grid-cols-4 gap-2 md:gap-3 mb-6 md:mb-8">
    ${statTile("instances", rows.length)}
    ${statTile("runs", totals.runs, `<span class="text-ok">${totals.done} done</span> · <span class="${totals.failed ? "text-bad" : ""}">${totals.failed} failed</span>`)}
    ${statTile("active now", active.length || "0")}
    ${statTile("tokens out", fmtTokens(totals.tokens), "all instances")}
  </div>
  ${instancesTable(rows)}`;
  return page({
    title: "instances",
    active: "instances",
    crumbs: [[null, "instances"]],
    body,
    activeRuns: active.length,
  });
}
