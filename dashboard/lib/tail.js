// Follow a jsonl file that another pod is appending to. No inotify —
// the volume is shared between pods and events don't cross that
// boundary reliably — just a poll against the file size, which is
// cheap and honest. Partial trailing lines stay in the buffer until
// their newline arrives, so a mid-append read never emits half a line.

import fs from "node:fs";

const POLL_MS = 700;

export function tail(file, { onLine, follow = true, onEof = () => {} }) {
  let offset = 0;
  let remainder = "";
  let stopped = false;
  let timer = null;

  function drain() {
    if (stopped) return;
    let st;
    try {
      st = fs.statSync(file);
    } catch {
      schedule(); // not born yet, or briefly gone
      return;
    }
    if (st.size < offset) {
      offset = 0; // truncated/replaced: start over rather than read garbage
      remainder = "";
    }
    if (st.size > offset) {
      const fd = fs.openSync(file, "r");
      try {
        const buf = Buffer.alloc(st.size - offset);
        const read = fs.readSync(fd, buf, 0, buf.length, offset);
        offset += read;
        const chunk = remainder + buf.toString("utf-8", 0, read);
        const lines = chunk.split("\n");
        remainder = lines.pop() ?? "";
        for (const line of lines) {
          if (line.trim() && !stopped) onLine(line);
        }
      } finally {
        fs.closeSync(fd);
      }
    }
    if (stopped) return;
    onEof();
    if (follow) schedule();
  }

  function schedule() {
    if (!stopped) timer = setTimeout(drain, POLL_MS);
  }

  drain();
  return function stop() {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}
