// Browse the artifacts volume without ssh'ing into a pod. Markdown
// renders (comparison.md is the one that matters), diffs get color,
// everything else stays honest mono text.

import { marked } from "marked";
import { esc, fmtAgo, page } from "./ui.js";
import { diffColor } from "./run.js";

function crumbsFor(rel) {
  const crumbs = [["/artifacts", "artifacts"]];
  if (!rel) {
    crumbs[0] = [null, "artifacts"];
    return crumbs;
  }
  const parts = rel.split("/");
  let acc = "";
  for (let i = 0; i < parts.length; i++) {
    acc += (acc ? "/" : "") + parts[i];
    crumbs.push(
      i === parts.length - 1
        ? [null, parts[i]]
        : [`/artifacts/${acc.split("/").map(encodeURIComponent).join("/")}`, parts[i]],
    );
  }
  return crumbs;
}

export function dirPage(rel, entries, active) {
  const base = rel ? `/artifacts/${rel.split("/").map(encodeURIComponent).join("/")}` : "/artifacts";
  const body = `
  <table class="w-full border-separate border-spacing-0">
    <thead>
      <tr class="text-left text-[11px] uppercase tracking-wider text-mute">
        <th class="pb-2 font-medium">name</th>
        <th class="pb-2 font-medium text-right">size</th>
        <th class="pb-2 font-medium text-right">modified</th>
      </tr>
    </thead>
    <tbody class="font-mono text-[13px] tabular-nums">
      ${entries
        .map(
          (e) => `
      <tr>
        <td class="py-2 border-t border-edge">
          <a href="${base}/${encodeURIComponent(e.name)}" class="${e.dir ? "text-ink" : "text-sub"} hover:text-accent">
            ${e.dir ? `<span class="text-mute">▸</span> ${esc(e.name)}/` : esc(e.name)}
          </a>
        </td>
        <td class="py-2 border-t border-edge text-right text-mute">${e.dir ? "—" : (e.size / 1024).toFixed(1) + "k"}</td>
        <td class="py-2 border-t border-edge text-right text-mute">${fmtAgo(e.mtime)}</td>
      </tr>`,
        )
        .join("")}
    </tbody>
  </table>
  ${entries.length === 0 ? `<div class="text-mute py-12 text-center">empty</div>` : ""}`;
  return page({
    title: rel || "artifacts",
    active: "artifacts",
    crumbs: crumbsFor(rel),
    body,
    activeRuns: active,
  });
}

export function filePage(rel, { kindName, text, tooBig, size }, active) {
  const rawHref = `/raw/${rel.split("/").map(encodeURIComponent).join("/")}`;
  let rendered;
  if (tooBig) {
    rendered = `<div class="text-mute py-12 text-center">
      ${(size / 1024 / 1024).toFixed(1)}MB is past the inline limit —
      <a class="text-accent" href="${rawHref}">download raw</a></div>`;
  } else if (kindName === "markdown") {
    rendered = `<article class="prose prose-invert prose-sm max-w-3xl
      prose-headings:font-mono prose-code:text-accent prose-pre:bg-panel prose-pre:border prose-pre:border-edge">
      ${marked.parse(text)}</article>`;
  } else if (kindName === "diff") {
    rendered = `<pre class="font-mono text-[12px] leading-relaxed overflow-x-auto">${diffColor(text)}</pre>`;
  } else if (kindName === "json") {
    let pretty = text;
    try {
      pretty = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      /* show as-is */
    }
    rendered = `<pre class="font-mono text-[12px] text-sub overflow-x-auto">${esc(pretty)}</pre>`;
  } else {
    rendered = `<pre class="font-mono text-[12px] text-sub whitespace-pre-wrap break-words">${esc(text)}</pre>`;
  }
  const runMatch = rel.match(/^([^/]+)\/([^/]+)\/trace\.jsonl$/);
  const body = `
  <div class="flex items-center gap-3 mb-5">
    ${
      runMatch
        ? `<a href="/instances/${encodeURIComponent(runMatch[1])}/runs/${encodeURIComponent(runMatch[2])}" class="px-3 py-1.5 rounded border border-accent/40 text-accent hover:bg-accent/10 text-xs font-mono">open as turn stream</a>`
        : ""
    }
    <a href="${rawHref}" class="px-3 py-1.5 rounded border border-edge2 text-sub hover:text-ink text-xs font-mono">raw</a>
  </div>
  <div class="bg-panel border border-edge rounded-md px-6 py-5">${rendered}</div>`;
  return page({
    title: rel,
    active: "artifacts",
    crumbs: crumbsFor(rel),
    body,
    activeRuns: active,
  });
}
