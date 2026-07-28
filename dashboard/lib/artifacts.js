// The artifacts volume, read-only. Everything is keyed by the path
// relative to the root; safePath is the only door in — nothing above
// the root is reachable no matter what the URL says.

import fs from "node:fs";
import path from "node:path";

export const ROOT = process.env.ARTIFACTS_ROOT || "/artifacts";

export function safePath(rel) {
  const cleaned = path.normalize(rel || ".").replace(/^(\.\.(\/|\\|$))+/, "");
  const abs = path.resolve(ROOT, cleaned);
  if (abs !== path.resolve(ROOT) && !abs.startsWith(path.resolve(ROOT) + path.sep)) {
    throw Object.assign(new Error("outside artifacts root"), { status: 400 });
  }
  return abs;
}

export function stat(rel) {
  try {
    return fs.statSync(safePath(rel));
  } catch {
    return null;
  }
}

export function list(rel) {
  const abs = safePath(rel);
  const entries = fs.readdirSync(abs, { withFileTypes: true });
  return entries
    .map((e) => {
      const s = fs.statSync(path.join(abs, e.name));
      return {
        name: e.name,
        dir: e.isDirectory(),
        size: s.size,
        mtime: s.mtime,
      };
    })
    .sort((a, b) => (a.dir !== b.dir ? (a.dir ? -1 : 1) : a.name.localeCompare(b.name)));
}

const TEXT_MAX = 2 * 1024 * 1024; // past this, download only

export function readText(rel) {
  const abs = safePath(rel);
  const s = fs.statSync(abs);
  if (s.size > TEXT_MAX) return null;
  return fs.readFileSync(abs, "utf-8");
}

export function kind(name) {
  if (name.endsWith(".md")) return "markdown";
  if (name.endsWith(".patch") || name.endsWith(".diff")) return "diff";
  if (name.endsWith(".json")) return "json";
  if (name.endsWith(".jsonl")) return "jsonl";
  if (name.endsWith(".yaml") || name.endsWith(".yml")) return "yaml";
  return "text";
}
