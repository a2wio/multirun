// One run: what it did (turns, live or replayed), what it changed
// (diffs), and whether it worked (checks). The turn stream arrives
// over ws either way — replay and live are the same wire.

import { esc, fmtDur, fmtTime, fmtTokens, page, statePill, statTile } from "./ui.js";

const PHASE_ORDER = [
  "pending",
  "provisioning",
  "spawned",
  "running",
  "diffing",
  "teardown",
  "done",
  "failed",
];

function phaseChips(events) {
  if (events.length < 2) return "";
  const chips = [];
  for (let i = 0; i < events.length; i++) {
    const cur = events[i];
    const next = events[i + 1];
    const dur = next
      ? (new Date(next.at) - new Date(cur.at)) / 1000
      : null;
    const terminal = !next;
    chips.push(`<span class="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span class="font-mono text-[12px] ${terminal ? (cur.state === "failed" ? "text-bad" : cur.state === "done" ? "text-ok" : "text-run") : "text-sub"}">${esc(cur.state)}</span>
      ${dur != null && dur >= 1 ? `<span class="font-mono text-[11px] text-mute">${fmtDur(dur)}</span>` : ""}
    </span>`);
  }
  return `<div class="flex items-center gap-2 flex-wrap mt-3 text-mute">
    ${chips.join('<span class="text-edge2">→</span>')}
  </div>`;
}

function checksSection(checks) {
  if (!checks?.checks?.length) return "";
  return `<section class="mt-8">
    <h2 class="text-[11px] uppercase tracking-wider text-mute mb-3">checks · ${checks.passed}/${checks.total} passed</h2>
    <div class="space-y-2">
      ${checks.checks
        .map(
          (c) => `
      <details class="bg-panel border ${c.pass ? "border-edge" : "border-bad/40"} rounded-md">
        <summary class="px-4 py-2.5 flex items-center gap-3">
          <span class="font-mono text-[12px] ${c.pass ? "text-ok" : "text-bad"}">${c.pass ? "✓ pass" : "✗ fail"}</span>
          <span class="font-mono text-[13px] text-ink">${esc(c.name)}</span>
          <span class="font-mono text-[11px] text-mute ml-auto">${c.seconds}s · exit ${c.exit}</span>
        </summary>
        <pre class="px-4 pb-3 font-mono text-[12px] text-sub whitespace-pre-wrap break-words">${esc(c.tail || "(no output)")}</pre>
      </details>`,
        )
        .join("")}
    </div>
  </section>`;
}

function filesSection(fanout, runId, files) {
  if (!files.length) return "";
  return `<section class="mt-8">
    <h2 class="text-[11px] uppercase tracking-wider text-mute mb-3">artifacts</h2>
    <div class="flex flex-wrap gap-2">
      ${files
        .map(
          (f) => `<a href="/artifacts/${encodeURIComponent(fanout)}/${encodeURIComponent(runId)}/${encodeURIComponent(f.name)}"
        class="px-3 py-1.5 rounded border border-edge bg-panel font-mono text-[12px] text-sub hover:text-ink hover:border-edge2">
        ${esc(f.name)} <span class="text-mute">${(f.size / 1024).toFixed(1)}k</span></a>`,
        )
        .join("")}
    </div>
  </section>`;
}

function dbDiffSection(schemaDiff, dataDiff) {
  const tables = dataDiff?.tables ? Object.entries(dataDiff.tables) : [];
  const touched = tables.filter(
    ([, d]) => d.added || d.removed || d.only_in,
  );
  if (!schemaDiff && !touched.length) return "";
  return `<section class="mt-8">
    <h2 class="text-[11px] uppercase tracking-wider text-mute mb-3">what it did to the data</h2>
    ${
      touched.length
        ? `<div class="flex flex-wrap gap-2 mb-3">${touched
            .map(
              ([t, d]) => `<span class="px-2.5 py-1 rounded bg-panel border border-edge font-mono text-[12px]">
              <span class="text-ink">${esc(t)}</span>
              ${d.only_in ? `<span class="text-accent"> new table</span>` : ""}
              ${d.added ? `<span class="text-ok"> +${d.added}</span>` : ""}
              ${d.removed ? `<span class="text-bad"> −${d.removed}</span>` : ""}
            </span>`,
            )
            .join("")}</div>`
        : ""
    }
    ${
      schemaDiff
        ? `<details open class="bg-panel border border-edge rounded-md">
            <summary class="px-4 py-2.5 font-mono text-[12px] text-sub">schema.diff</summary>
            <pre class="px-4 pb-3 font-mono text-[12px] overflow-x-auto">${diffColor(schemaDiff)}</pre>
          </details>`
        : ""
    }
  </section>`;
}

export function diffColor(text) {
  return String(text)
    .split("\n")
    .map((line) => {
      const e = esc(line);
      if (line.startsWith("+")) return `<span class="diff-add">${e}</span>`;
      if (line.startsWith("-")) return `<span class="diff-del">${e}</span>`;
      if (line.startsWith("@@")) return `<span class="diff-hunk">${e}</span>`;
      return `<span class="text-sub">${e}</span>`;
    })
    .join("\n");
}

export function runPage({ run, events }, { checks, files, schemaDiff, dataDiff, active }) {
  const { fanout, run_id } = run;
  const meta = run.meta || {};
  const finished = ["done", "failed"].includes(run.state);
  const body = `
  <div class="flex items-baseline justify-between mb-2">
    <h1 class="font-mono text-xl text-ink">run ${esc(run_id)}</h1>
    ${statePill(run.state)}
  </div>
  ${phaseChips(events)}
  <div class="grid grid-cols-2 md:grid-cols-5 gap-3 mt-6">
    ${statTile("model", `<span class="text-base">${esc(run.model ?? "—")}</span>`)}
    ${statTile("turns", run.num_turns ?? "—")}
    ${statTile("wall", fmtDur(run.wall_seconds))}
    ${statTile("tokens", `<span class="text-base">${fmtTokens(run.tokens_in)} <span class="text-mute">in</span> · ${fmtTokens(run.tokens_out)} <span class="text-mute">out</span></span>`)}
    ${statTile("cost", meta.total_cost_usd != null ? "$" + Number(meta.total_cost_usd).toFixed(2) : "—")}
  </div>

  <section class="mt-8">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-[11px] uppercase tracking-wider text-mute">turns</h2>
      <span id="stream-status" class="font-mono text-[11px] ${finished ? "text-mute" : "text-run"}">${finished ? "replay" : "connecting…"}</span>
    </div>
    <div hx-ext="ws" ws-connect="/ws/turns/${encodeURIComponent(fanout)}/${encodeURIComponent(run_id)}">
      <div id="turns" class="bg-panel border border-edge rounded-md px-4 py-2 max-h-[70vh] overflow-y-auto divide-y divide-edge/50"></div>
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
  </section>

  ${checksSection(checks)}
  ${dbDiffSection(schemaDiff, dataDiff)}
  ${filesSection(fanout, run_id, files)}

  ${
    events.length
      ? `<details class="mt-8">
      <summary class="text-sub hover:text-ink text-xs uppercase tracking-wider">state history</summary>
      <table class="mt-3 font-mono text-[12px] tabular-nums">
        ${events
          .map(
            (e) => `<tr><td class="pr-6 text-sub py-0.5">${fmtTime(e.at)}</td><td>${statePill(e.state)}</td></tr>`,
          )
          .join("")}
      </table>
    </details>`
      : ""
  }`;
  return page({
    title: `${fanout} / ${run_id}`,
    active: "instances",
    crumbs: [
      ["/instances", "instances"],
      [`/instances/${encodeURIComponent(fanout)}`, fanout],
      [null, `run ${run_id}`],
    ],
    body,
    activeRuns: active,
  });
}
