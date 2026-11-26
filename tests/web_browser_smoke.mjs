/* v0.26 浏览器冒烟：首屏四卡、顶栏 AI 入口、材料侧 AI 建议、窄屏不溢出、PWA 断网重载。
 * 用法：先起本地服务，再 node tests/web_browser_smoke.mjs
 * 可选环境变量：PORT / URL / OUT / OUT_PANEL / OUT_DRAWER / WIDTH / HEIGHT / LIGHT / DARK。
 * 只读页面与本地缓存；不调用模型、不写台账。
 * 断网检查先等 SW 接管，再离线重载并从隔离上下文读 DOM，避免旧执行上下文导致的假失败。
 */
import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = Number(process.env.PORT || 9240);
const PROFILE = `C:\\Users\\35342\\AppData\\Local\\Temp\\cc-v026-edge-${PORT}`;
const OUT = process.env.OUT || "C:\\Users\\35342\\Doubao\\chats\\2026-11-14\\new-chat\\v026-正式版-Bento.png";
const OUT_PANEL = process.env.OUT_PANEL || OUT.replace(/\.png$/, "-AI副驾.png");
const OUT_DRAWER = process.env.OUT_DRAWER || OUT.replace(/\.png$/, "-详情AI建议.png");
const PAGE_URL = process.env.URL || "http://127.0.0.1:8781/web/";
const WIDTH = Number(process.env.WIDTH || 1440);
const HEIGHT = Number(process.env.HEIGHT || 1100);
rmSync(PROFILE, { recursive: true, force: true });
mkdirSync(PROFILE, { recursive: true });
const proc = spawn(EDGE, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  `--window-size=${WIDTH},${HEIGHT}`, PAGE_URL,
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 240; i++) {
  try {
    const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    const page = list.find((x) => x.type === "page" && /\/web\/?($|[?#])/.test(x.url)) || list.find((x) => x.type === "page");
    if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
  } catch {}
  await sleep(250);
}
if (!wsUrl) { console.error("FAIL NO_CDP"); proc.kill(); process.exit(1); }

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
const evalJS = async (expression, contextId) => {
  const params = { expression, returnByValue: true, awaitPromise: true };
  if (contextId) params.contextId = contextId;
  const r = await send("Runtime.evaluate", params);
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.text + " " + (r.result.exceptionDetails.exception?.description || ""));
  return r.result?.result?.value;
};
await send("Runtime.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
await sleep(900);
for (let i = 0; i < 40; i++) {
  if (await evalJS(`document.readyState === "complete" && !!document.querySelector('button[data-theme-mode="light"]')`)) break;
  await sleep(400);
}
if (process.env.LIGHT) await evalJS(`document.querySelector('button[data-theme-mode="light"]')?.click(); true`);
if (process.env.DARK) await evalJS(`applyTheme("dark"); true`);
await evalJS(`document.querySelector(".fr-dismiss")?.click(); true`);
await sleep(500);

const base = JSON.parse(await evalJS(`JSON.stringify({
  title: document.title,
  version: window.WEB_VERSION || "",
  cards: document.querySelectorAll("#view-dashboard .b-card").length,
  briefs: document.querySelectorAll("#view-dashboard .b-brief-item").length,
  solid: document.querySelectorAll("#view-dashboard .btn.primary").length,
  aiBtn: !!document.getElementById("aiBtn"),
  topbarAction: !!document.getElementById("topbarAction"),
  overflowX: document.documentElement.scrollWidth > window.innerWidth,
  bodyH: document.body.scrollHeight
})`));
console.log("BASE", JSON.stringify(base));

const shotTo = async (file) => {
  const metrics = await send("Page.getLayoutMetrics");
  const contentH = Math.ceil(metrics.result?.cssContentSize?.height || HEIGHT);
  const clip = { x: 0, y: 0, width: WIDTH, height: Math.min(3200, Math.max(HEIGHT, contentH)), scale: 1 };
  let shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip });
  if (!shot.result?.data) shot = await send("Page.captureScreenshot", { format: "png" });
  if (shot.result?.data) { writeFileSync(file, Buffer.from(shot.result.data, "base64")); console.log("SHOT", file); }
  else console.log("SHOT_SKIPPED", JSON.stringify(shot).slice(0, 300));
};
await shotTo(OUT);

await evalJS(`document.getElementById("aiBtn").click(); true`);
await sleep(450);
const copilot = JSON.parse(await evalJS(`JSON.stringify({
  show: document.getElementById("aiCopilot").classList.contains("show"),
  context: document.getElementById("acpContext").textContent,
  quick: Array.from(document.querySelectorAll("#acpQuick button")).map(b=>b.textContent.trim()),
  drawer: document.getElementById("drawer").classList.contains("show")
})`));
console.log("COPILOT", JSON.stringify(copilot));

await evalJS(`closeAICopilot(); document.querySelector('.nav button[data-key="docs"]').click(); true`);
await sleep(650);
await evalJS(`openDoc(Number(document.querySelector("#view-docs tbody tr").dataset.id), "docs"); true`);
await sleep(450);
const drawer = JSON.parse(await evalJS(`JSON.stringify({
  show: document.getElementById("drawer").classList.contains("show"),
  aiBtns: document.querySelectorAll("#drawerBody [data-ai-doc]").length
})`));
console.log("DRAWER", JSON.stringify(drawer));
await shotTo(OUT_DRAWER);

await evalJS(`openAICopilot("doc", Number(document.querySelector("#view-docs tbody tr.clickable").dataset.id)); true`);
await sleep(450);
const docCopilot = JSON.parse(await evalJS(`JSON.stringify({
  show: document.getElementById("aiCopilot").classList.contains("show"),
  context: document.getElementById("acpContext").textContent,
  quick: Array.from(document.querySelectorAll("#acpQuick button")).map(b=>b.textContent.trim())
})`));
console.log("DOC_COPILOT", JSON.stringify(docCopilot));

await shotTo(OUT_PANEL);

await evalJS(`closeAICopilot(); if (typeof switchView === "function") switchView("dashboard"); true`);
await sleep(500);
const swReady = await evalJS(`Promise.race([navigator.serviceWorker.ready.then(()=>true), new Promise(r=>setTimeout(()=>r(false),3000))])`);
const swControlled = await evalJS(`!!navigator.serviceWorker.controller`);
console.log("SW", swReady, swControlled);
if (!swControlled) { await send("Page.reload"); await sleep(1600); }
await send("Network.enable");
await send("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
await send("Page.reload");
await sleep(600);
await send("Runtime.enable");
const frameTree = await send("Page.getFrameTree");
const frameId = frameTree.result?.frameTree?.frame?.id;
const world = frameId ? await send("Page.createIsolatedWorld", { frameId, worldName: "offline-check" }) : null;
const offCtx = world?.result?.executionContextId || null;
let offlineReady = false;
for (let i = 0; i < 24; i++) {
  try {
    if (await evalJS(`document.readyState === "complete" && !!document.querySelector("#view-dashboard .bento")`, offCtx)) { offlineReady = true; break; }
  } catch {}
  await sleep(400);
}
let offline;
try {
  const snapshot = JSON.parse(await evalJS(`JSON.stringify({
    title: document.title,
    cards: document.querySelectorAll("#view-dashboard .b-card").length,
    current: document.querySelector(".nav button.active")?.textContent.trim()
  })`, offCtx));
  offline = { ready: offlineReady, ...snapshot };
} catch (e) {
  console.log("OFFERR", e.message);
  offline = { ready: false, title: "EVAL_FAIL", cards: 0, current: "" };
}
console.log("OFFLINE", JSON.stringify(offline));

const errors = logs.filter((l) => /EXCEPTION|Uncaught|ReferenceError|TypeError/.test(l));
console.log("ERRORS", errors.length, errors.slice(0, 3).join(" | "));
proc.kill();
process.exit(errors.length || !offline.ready ? 1 : 0);
