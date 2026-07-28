// The multirun dashboard: a read-only window onto the bench. Reads the
// results db and the artifacts volume, renders html, tails traces over
// ws. It publishes nothing, kicks off nothing, and holds no state of
// its own — kill it whenever.

import http from "node:http";
import path from "node:path";
import express from "express";
import { WebSocketServer } from "ws";

import * as auth from "./lib/auth.js";
import * as db from "./lib/db.js";
import * as art from "./lib/artifacts.js";
import { parseLine } from "./lib/trace.js";
import { tail } from "./lib/tail.js";

import { instancesPage, instancesTable } from "./views/instances.js";
import { instancePage, runsTable } from "./views/instance.js";
import { runPage } from "./views/run.js";
import { livePage, livePartial } from "./views/live.js";
import { dirPage, filePage } from "./views/artifacts.js";
import { oobStatus, oobTurn, renderEvent } from "./views/turns.js";

const PORT = Number(process.env.PORT || 3000);

const app = express();
app.set("x-powered-by", false);
app.use(auth.middleware);

const wrap = (fn) => (req, res, next) => fn(req, res).catch(next);

app.get("/healthz", (req, res) => res.send("ok"));
app.get("/", (req, res) => res.redirect("/instances"));

app.get(
  "/instances",
  wrap(async (req, res) => {
    const [rows, active] = await Promise.all([db.instances(), db.activeRuns()]);
    if (req.query.partial) return res.send(instancesTable(rows));
    res.send(instancesPage(rows, active));
  }),
);

app.get(
  "/instances/:fanout",
  wrap(async (req, res) => {
    const data = await db.instance(req.params.fanout);
    if (!data.meta) return res.status(404).send("no such instance");
    if (req.query.partial) return res.send(runsTable(data.meta.fanout, data.runs));
    const [active, comparison] = [
      await db.activeRuns(),
      art.stat(path.join(req.params.fanout, "comparison.md")),
    ];
    res.send(
      instancePage(data, { hasComparison: Boolean(comparison), active: active.length }),
    );
  }),
);

app.get(
  "/instances/:fanout/runs/:run",
  wrap(async (req, res) => {
    const { fanout, run } = req.params;
    const data = await db.run(fanout, run);
    if (!data.run) return res.status(404).send("no such run");
    const dir = path.join(fanout, run);
    const files = art.stat(dir)?.isDirectory()
      ? art.list(dir).filter((e) => !e.dir)
      : [];
    const readJson = (name) => {
      try {
        const t = art.readText(path.join(dir, name));
        return t ? JSON.parse(t) : null;
      } catch {
        return null;
      }
    };
    const active = await db.activeRuns();
    res.send(
      runPage(data, {
        checks: readJson("checks.json"),
        dataDiff: readJson("data_diff.json"),
        schemaDiff: (() => {
          try {
            return art.readText(path.join(dir, "schema.diff"));
          } catch {
            return null;
          }
        })(),
        files,
        active: active.length,
      }),
    );
  }),
);

app.get(
  "/live",
  wrap(async (req, res) => {
    const [active, recent] = await Promise.all([db.activeRuns(), db.recentRuns()]);
    if (req.query.partial) return res.send(livePartial(active, recent));
    res.send(livePage(active, recent));
  }),
);

function relFromParams(req) {
  // regex route: everything after the prefix, still uri-encoded per segment
  return (req.params[0] || "")
    .split("/")
    .filter(Boolean)
    .map(decodeURIComponent)
    .join("/");
}

app.get(
  /^\/artifacts(?:\/(.*))?$/,
  wrap(async (req, res) => {
    const rel = relFromParams(req);
    const s = art.stat(rel);
    const active = await db.activeRuns();
    if (!s) return res.status(404).send("not found");
    if (s.isDirectory()) return res.send(dirPage(rel, art.list(rel), active.length));
    const text = art.readText(rel);
    res.send(
      filePage(
        rel,
        text == null
          ? { tooBig: true, size: s.size }
          : { kindName: art.kind(rel), text },
        active.length,
      ),
    );
  }),
);

app.get(/^\/raw\/(.*)$/, (req, res) => {
  const rel = relFromParams(req);
  const s = art.stat(rel);
  if (!s || !s.isFile()) return res.status(404).send("not found");
  res.type("text/plain; charset=utf-8");
  res.sendFile(art.safePath(rel));
});

app.use((err, req, res, next) => {
  console.error(err);
  res.status(err.status || 500).send(err.status ? err.message : "internal error");
});

// -- the live wire ------------------------------------------------------------

const server = http.createServer(app);
const wss = new WebSocketServer({ noServer: true });

server.on("upgrade", (req, socket, head) => {
  const m = req.url.match(/^\/ws\/turns\/([^/]+)\/([^/?]+)/);
  if (!m || !auth.requestOk(req)) {
    socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
    socket.destroy();
    return;
  }
  const fanout = decodeURIComponent(m[1]);
  const run = decodeURIComponent(m[2]);
  wss.handleUpgrade(req, socket, head, (ws) => streamTurns(ws, fanout, run));
});

const IDLE_RECHECK_MS = 45_000;

function streamTurns(ws, fanout, run) {
  const file = art.safePath(path.join(fanout, run, "trace.jsonl"));
  let sawResult = false;
  let caughtUp = false;
  let lastData = Date.now();
  let checking = false;
  let batch = [];

  const send = (html) => {
    if (ws.readyState === ws.OPEN) ws.send(html);
  };
  const flush = () => {
    if (batch.length) {
      send(batch.join(""));
      batch = [];
    }
  };
  const finish = (state) => {
    send(oobStatus(state ? `replay · ${state}` : "replay · complete", false));
    stop();
  };

  const stop = tail(file, {
    onLine(line) {
      lastData = Date.now();
      for (const ev of parseLine(line)) {
        const html = renderEvent(ev);
        if (html) batch.push(oobTurn(html));
        if (ev.kind === "result") sawResult = true;
      }
      // replay bursts thousands of events; batch per drain, not per line
      if (batch.length >= 200) flush();
    },
    onEof() {
      flush();
      if (!caughtUp) {
        caughtUp = true;
        if (!sawResult) send(oobStatus("live", true));
      }
      // a trace that ended cleanly is over; one that just went quiet
      // might be a run that died without a result — ask the db, don't
      // hold a "live" socket on a corpse
      const idle = Date.now() - lastData > IDLE_RECHECK_MS;
      if ((sawResult || idle) && !checking) {
        checking = true;
        db.runState(fanout, run)
          .catch(() => null)
          .then((state) => {
            checking = false;
            if (sawResult || (state && ["done", "failed"].includes(state))) {
              finish(state);
            }
          });
      }
    },
  });

  ws.on("close", stop);
  ws.on("error", stop);
}

server.listen(PORT, () => {
  console.log(`dashboard listening on :${PORT}, artifacts at ${art.ROOT}`);
});
