// Basic auth in front of everything, one user. The browser's cached
// credentials don't reliably ride along on websocket upgrades, so a
// successful basic-auth request also sets a cookie derived from the
// password — the upgrade handler accepts either. Rotate the password
// and every cookie dies with it.

import crypto from "node:crypto";

const USER = process.env.DASHBOARD_USERNAME || "";
const PASS = process.env.DASHBOARD_PASSWORD || "";
if (!USER || !PASS) {
  console.error("DASHBOARD_USERNAME / DASHBOARD_PASSWORD are required");
  process.exit(1);
}

const COOKIE = "mrdash";
const TOKEN = crypto.createHmac("sha256", PASS).update("mrdash-v1").digest("hex");

function timingSafeEqual(a, b) {
  const ha = crypto.createHash("sha256").update(a).digest();
  const hb = crypto.createHash("sha256").update(b).digest();
  return crypto.timingSafeEqual(ha, hb);
}

function basicOk(header) {
  if (!header || !header.startsWith("Basic ")) return false;
  const decoded = Buffer.from(header.slice(6), "base64").toString("utf-8");
  const idx = decoded.indexOf(":");
  if (idx < 0) return false;
  return (
    timingSafeEqual(decoded.slice(0, idx), USER) &&
    timingSafeEqual(decoded.slice(idx + 1), PASS)
  );
}

function cookieOk(header) {
  if (!header) return false;
  for (const part of header.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === COOKIE && timingSafeEqual(v.join("="), TOKEN)) return true;
  }
  return false;
}

export function middleware(req, res, next) {
  if (req.path === "/healthz") return next();
  if (cookieOk(req.headers.cookie)) return next();
  if (basicOk(req.headers.authorization)) {
    res.setHeader(
      "Set-Cookie",
      `${COOKIE}=${TOKEN}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=604800`,
    );
    return next();
  }
  res.setHeader("WWW-Authenticate", 'Basic realm="multirun"');
  res.status(401).send("auth required");
}

// for the ws upgrade path, where there is no express response to 401 with
export function requestOk(req) {
  return cookieOk(req.headers.cookie) || basicOk(req.headers.authorization);
}
