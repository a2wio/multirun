// The front page: every fanout/smoke instance the bench has run.

import { esc, fmtAgo, fmtDur, fmtTime, fmtTokens, page, statTile } from "./ui.js";

export function instancesTable(rows) {
  if (!rows.length) {
    return `<div id="instances-table" class="text-mute py-12 text-center">
      nothing has run yet — publish a config and it lands here</div>`;
  }
  return `<div id="instances-table" hx-get="/instances?partial=1" hx-trigger="every 8s" hx-swap="outerHTML">
  <table class="w-full border-separate border-spacing-0">
    <thead>
      <tr class="text-left text-[11px] uppercase tracking-wider text-mute">
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
      <tr class="group cursor-pointer" onclick="location='/instances/${encodeURIComponent(r.fanout)}'">
        <td class="py-2 border-t border-edge pr-4">
          <a href="/instances/${encodeURIComponent(r.fanout)}" class="text-ink group-hover:text-accent">${esc(r.fanout)}</a>
        </td>
        <td class="py-2 border-t border-edge text-sub pr-4">${fmtTime(r.created_at)}</td>
        <td class="py-2 border-t border-edge text-right text-ink">${r.runs}</td>
        <td class="py-2 border-t border-edge text-right ${r.done ? "text-ok" : "text-mute"}">${r.done}</td>
        <td class="py-2 border-t border-edge text-right ${r.failed ? "text-bad" : "text-mute"}">${r.failed}</td>
        <td class="py-2 border-t border-edge text-right ${r.active ? "text-run" : "text-mute"}">${r.active}</td>
        <td class="py-2 border-t border-edge text-right ${
          r.checks_total === 0
            ? "text-mute"
            : r.checks_passed === r.checks_total
              ? "text-ok"
              : "text-warn"
        }">${r.checks_total ? `${r.checks_passed}/${r.checks_total}` : "—"}</td>
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
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
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
