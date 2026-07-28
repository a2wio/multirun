// What's happening right now. If something is running, the newest run's
// turn stream is embedded here — the point of this page is watching.

import { esc, fmtAgo, page, statePill } from "./ui.js";

function runsList(rows, title) {
  if (!rows.length) return "";
  return `<section class="mb-8">
    <h2 class="text-[11px] uppercase tracking-wider text-mute mb-3">${title}</h2>
    <div class="space-y-1.5">
      ${rows
        .map((r) => {
          const href = `/instances/${encodeURIComponent(r.fanout)}/runs/${encodeURIComponent(r.run_id)}`;
          return `<a href="${href}" class="flex items-center gap-4 px-4 py-2.5 bg-panel border border-edge rounded-md hover:border-edge2 group">
          ${statePill(r.state)}
          <span class="font-mono text-[13px] text-ink group-hover:text-accent">${esc(r.fanout)} / ${esc(r.run_id)}</span>
          <span class="font-mono text-[12px] text-mute">${esc(r.model ?? "")}</span>
          <span class="font-mono text-[12px] text-mute ml-auto">${fmtAgo(r.updated_at)}</span>
        </a>`;
        })
        .join("")}
    </div>
  </section>`;
}

export function livePartial(active, recent) {
  return `<div id="live-lists" hx-get="/live?partial=1" hx-trigger="every 5s" hx-swap="outerHTML">
    ${
      active.length
        ? runsList(active, `in flight · ${active.length}`)
        : `<div class="mb-8 text-mute py-8 text-center border border-dashed border-edge rounded-md">
            nothing in flight — the stream lights up when a run starts</div>`
    }
    ${runsList(recent, "recently finished")}
  </div>`;
}

export function livePage(active, recent) {
  const newest = active[0];
  const body = `
  ${livePartial(active, recent)}
  ${
    newest
      ? `<section>
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-[11px] uppercase tracking-wider text-mute">watching ${esc(newest.fanout)} / ${esc(newest.run_id)}</h2>
      <span id="stream-status" class="font-mono text-[11px] text-run">connecting…</span>
    </div>
    <div hx-ext="ws" ws-connect="/ws/turns/${encodeURIComponent(newest.fanout)}/${encodeURIComponent(newest.run_id)}">
      <div id="turns" class="bg-panel border border-edge rounded-md px-4 py-2 max-h-[60vh] overflow-y-auto divide-y divide-edge/50"></div>
    </div>
    <script>
      (function () {
        var el = document.getElementById('turns');
        var pinned = true;
        el.addEventListener('scroll', function () {
          pinned = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
        });
        new MutationObserver(function () {
          if (pinned) el.scrollTop = el.scrollHeight;
        }).observe(el, { childList: true, subtree: true });
      })();
    </script>
  </section>`
      : ""
  }`;
  return page({
    title: "live",
    active: "live",
    crumbs: [[null, "live"]],
    body,
    activeRuns: active.length,
  });
}
