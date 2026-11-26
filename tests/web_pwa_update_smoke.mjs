/* v0.26 PWA 更新链路走查：旧 SW 控制页面 → 换新 SW → 弹更新提示。
 * 用法：node tests/web_pwa_update_smoke.mjs
 * 用本地 HTTP 服务从 web/ 读文件，只把 sw.js 在测试中临时换成旧版本；
 * 不改仓库文件，不用真实账号，不调用模型。
 */
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = Number(process.env.PORT || 9251);
const CDP_PORT = PORT + 1;
const PROFILE = `C:\\Users\\35342\\AppData\\Local\\Temp\\cc-v026-pwa-edge-${PORT}`;
const WEB = path.resolve("web");
const OLD_SW = `const CACHE = 'cc-web-v025-shell-v1';
self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE)
    .then((cache) => cache.addAll(['./index.html']))
    .then(() => self.skipWaiting()));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});
`;
rmSync(PROFILE, { recursive: true, force: true });
mkdirSync(PROFILE, { recursive: true });

let phase = "old";
const server = createServer((req, res) => {
  const url = decodeURIComponent((req.url || "/").split("?")[0]);
  if (url === "/web/sw.js" && phase === "old") {
    res.writeHead(200, {
      "Content-Type": "text/javascript; charset=utf-8",
      "Cache-Control": "no-store",
    });
    res.end(OLD_SW);
    return;
  }
  let rel = url.startsWith("/web/") ? url.slice(5) : url.replace(/^\//, "");
  rel = rel.replace(/^\//, "");
  if (!rel || rel.endsWith("/")) rel += "index.html";
  const file = path.join(WEB, rel);
  if (!file.startsWith(WEB) || !existsSync(file)) {
    res.writeHead(404); res.end("not found"); return;
  }
  const ext = path.extname(file).toLowerCase();
  const type = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
  }[ext] || "application/octet-stream";
  const body = readFileSync(file);
  res.writeHead(200, {
    "Content-Type": type,
    "Cache-Control": ext === ".js" ? "no-store" : "no-cache",
  });
  res.end(body);
});
await new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(PORT, "127.0.0.1", resolve);
});
const PAGE_URL = `http://127.0.0.1:${PORT}/web/`;

const proc = spawn(EDGE, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${PROFILE}`,
  "--window-size=1280,900", PAGE_URL,
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 240; i++) {
  try {
    const list = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
    const page = list.find((x) => x.type === "page" && x.url.startsWith(PAGE_URL));
    if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
  } catch {}
  await sleep(250);
}
if (!wsUrl) { console.error("FAIL NO_CDP"); proc.kill(); server.close(); process.exit(1); }

const ws = new WebSocket(wsUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let id = 0;
const pending = new Map();
const logs = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === "Runtime.consoleAPICalled") logs.push(m.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
  if (m.method === "Runtime.exceptionThrown") logs.push("EXCEPTION " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
};
const send = (method, params = {}) => new Promise((resolve) => {
  const n = ++id; pending.set(n, resolve);
  ws.send(JSON.stringify({ id: n, method, params }));
});
const evalJS = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.text + " " + (r.result.exceptionDetails.exception?.description || ""));
  return r.result?.result?.value;
};
await send("Runtime.enable");
await send("Page.enable");

for (let i = 0; i < 40; i++) {
  if (await evalJS(`document.readyState === "complete" && !!document.getElementById("pwaUpdate")`)) break;
  await sleep(300);
}

// 首次加载没有控制者：安装旧 SW 后不弹更新提示
const first = JSON.parse(await evalJS(`(async () => {
  await navigator.serviceWorker.ready;
  return JSON.stringify({
    controller: !!navigator.serviceWorker.controller,
    hidden: document.getElementById("pwaUpdate").hidden,
    hadController: pwaState.hadController
  });
})()`));
console.log("FIRST", JSON.stringify(first));
if (first.hadController || !first.hidden) {
  console.log("FAIL FIRST_INSTALL"); proc.kill(); server.close(); process.exit(1);
}

// 重载后旧 SW 接管；此时 hadController 为真
await evalJS(`location.reload(); true`);
await sleep(1000);
for (let i = 0; i < 40; i++) {
  const ok = await evalJS(`document.readyState === "complete" && !!navigator.serviceWorker.controller && !!document.getElementById("pwaUpdate")`);
  if (ok) break;
  await sleep(300);
}
const controlled = JSON.parse(await evalJS(`JSON.stringify({
  controller: !!navigator.serviceWorker.controller,
  hidden: document.getElementById("pwaUpdate").hidden,
  hadController: pwaState.hadController
})`));
console.log("CONTROLLED", JSON.stringify(controlled));
if (!controlled.controller || !controlled.hadController || !controlled.hidden) {
  console.log("FAIL CONTROLLED"); proc.kill(); server.close(); process.exit(1);
}

// 换成仓库里的 v026 sw.js，强制检查更新
phase = "new";
const update = JSON.parse(await evalJS(`(async () => {
  const reg = await navigator.serviceWorker.getRegistration();
  let changed = false, shown = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => { changed = true; });
  const timer = setInterval(() => {
    const node = document.getElementById("pwaUpdate");
    if (node && !node.hidden) shown = true;
  }, 50);
  await reg.update();
  const t0 = Date.now();
  while (Date.now() - t0 < 9000 && !(changed && shown)) {
    await new Promise((r) => setTimeout(r, 100));
  }
  clearInterval(timer);
  let keys = await caches.keys();
  for (let i = 0; i < 30 && keys.includes("cc-web-v025-shell-v1"); i++) {
    await new Promise((r) => setTimeout(r, 100));
    keys = await caches.keys();
  }
  const node = document.getElementById("pwaUpdate");
  return JSON.stringify({
    changed, shown, hidden: node.hidden,
    text: node.querySelector(".pwa-copy b").textContent.trim(),
    hadController: pwaState.hadController,
    keys
  });
})()`));
console.log("UPDATE", JSON.stringify(update));
const hasNewCache = update.keys.includes("cc-web-v026-shell-v1");
const hasOldCache = update.keys.includes("cc-web-pwa-old-test");
if (!update.changed || !update.shown || update.hidden || update.text !== "新版本已准备好" ||
    !update.hadController || !hasNewCache || hasOldCache) {
  console.log("FAIL UPDATE_PROMPT"); proc.kill(); server.close(); process.exit(1);
}

const dismissed = await evalJS(`(() => {
  document.getElementById("pwaLater").click();
  return document.getElementById("pwaUpdate").hidden;
})()`);
console.log("DISMISSED", dismissed);
if (!dismissed) { console.log("FAIL DISMISS"); proc.kill(); server.close(); process.exit(1); }

const errors = logs.filter((l) => /EXCEPTION|Uncaught|ReferenceError|TypeError/.test(l));
console.log("ERRORS", errors.length, errors.slice(0, 3).join(" | "));
proc.kill();
server.close();
process.exit(errors.length ? 1 : 0);
