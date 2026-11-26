/* v0.26 右栏常驻上下文 + PWA 更新提示的浏览器走查。
 * 用法：先起本地服务，再 node tests/web_context_smoke.mjs
 * 可选环境变量：PORT / URL / OUT / OUT_NARROW / WIDTH / HEIGHT。
 */
import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = Number(process.env.PORT || 9245);
const PROFILE = `C:\\Users\\35342\\AppData\\Local\\Temp\\cc-v026-context-edge-${PORT}`;
const PAGE_URL = process.env.URL || "http://127.0.0.1:8781/web/";
const OUT = process.env.OUT || "C:\\Users\\35342\\Doubao\\chats\\2026-11-14\\new-chat\\v026-右栏常驻上下文.png";
const OUT_NARROW = process.env.OUT_NARROW || OUT.replace(/\.png$/, "-窄屏.png");
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
const evalJS = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.text + " " + (r.result.exceptionDetails.exception?.description || ""));
  return r.result?.result?.value;
};
await send("Runtime.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
await sleep(900);
for (let i = 0; i < 40; i++) {
  if (await evalJS(`document.readyState === "complete" && !!document.getElementById("drawer")`)) break;
  await sleep(400);
}
await evalJS(`document.querySelector('button[data-theme-mode="light"]')?.click(); true`);
await evalJS(`document.querySelector(".fr-dismiss")?.click(); true`);

const shotTo = async (file, clipWidth = WIDTH, clipHeight = HEIGHT, exact = false) => {
  const metrics = await send("Page.getLayoutMetrics");
  const contentH = Math.ceil(metrics.result?.cssContentSize?.height || clipHeight);
  const shotH = exact ? clipHeight : Math.min(1600, Math.max(clipHeight, contentH));
  const clip = { x: 0, y: 0, width: clipWidth, height: shotH, scale: 1 };
  let shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: !exact, clip });
  if (!shot.result?.data) shot = await send("Page.captureScreenshot", { format: "png" });
  if (shot.result?.data) { writeFileSync(file, Buffer.from(shot.result.data, "base64")); console.log("SHOT", file); }
  else console.log("SHOT_SKIPPED", JSON.stringify(shot).slice(0, 300));
};

const desktop = JSON.parse(await evalJS(`(async () => {
  const content = document.querySelector(".content");
  const basePad = getComputedStyle(content).paddingRight;
  await openDoc(1);
  await new Promise(r => setTimeout(r, 1000));
  const dr = document.getElementById("drawer").getBoundingClientRect();
  const pwa = document.getElementById("pwaUpdate");
  const firstHidden = pwa.hidden;
  const shown = showPwaUpdate();
  const pwaRect = pwa.getBoundingClientRect();
  const cs = getComputedStyle(content);
  const bento = document.querySelector("#view-dashboard .bento");
  const hero = document.querySelector("#view-dashboard .b-hero");
  const side = document.querySelector("#view-dashboard .b-side");
  return JSON.stringify({
    drawerShow: document.getElementById("drawer").classList.contains("show"),
    drawerLeft: Math.round(dr.left), drawerTop: Math.round(dr.top),
    drawerBottom: Math.round(window.innerHeight - dr.bottom), drawerW: Math.round(dr.width),
    bodyOpen: document.body.classList.contains("drawer-open"),
    maskDisplay: getComputedStyle(document.getElementById("drawerMask")).display,
    paddingRightBefore: basePad,
    paddingRight: cs.paddingRight,
    innerW: Math.round(content.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)),
    contentW: Math.round(content.getBoundingClientRect().width),
    bentoW: Math.round(bento.getBoundingClientRect().width),
    heroW: Math.round(hero.getBoundingClientRect().width),
    sideW: Math.round(side.getBoundingClientRect().width),
    sideRight: Math.round(side.getBoundingClientRect().right),
    pwaFirstHidden: firstHidden, pwaShown: shown && !pwa.hidden,
    pwaRight: Math.round(pwaRect.right), pwaW: Math.round(pwaRect.width),
    pwaText: pwa.querySelector(".pwa-copy b").textContent.trim()
  });
})()`));
console.log("DESKTOP", JSON.stringify(desktop));
if (!desktop.drawerShow || desktop.drawerW !== 360 || desktop.drawerTop < 50 ||
    desktop.drawerBottom < 30 || !desktop.bodyOpen || desktop.maskDisplay !== "none" ||
    desktop.paddingRight !== "392px" || !desktop.pwaFirstHidden ||
    !desktop.pwaShown || desktop.pwaRight > desktop.drawerLeft ||
    desktop.pwaText !== "新版本已准备好") {
  console.log("FAIL DESKTOP"); proc.kill(); process.exit(1);
}
await shotTo(OUT);

await evalJS(`document.getElementById("pwaLater").click(); true`);
const dismissed = await evalJS(`document.getElementById("pwaUpdate").hidden`);
if (!dismissed) { console.log("FAIL PWA_DISMISS"); proc.kill(); process.exit(1); }
await evalJS(`closeDrawer(); true`);
await sleep(260);
const closed = JSON.parse(await evalJS(`JSON.stringify({
  show: document.getElementById("drawer").classList.contains("show"),
  bodyOpen: document.body.classList.contains("drawer-open"),
  paddingRight: getComputedStyle(document.querySelector(".content")).paddingRight
})`));
console.log("CLOSED", JSON.stringify(closed));
if (closed.show || closed.bodyOpen || closed.paddingRight !== "28px") {
  console.log("FAIL CLOSED"); proc.kill(); process.exit(1);
}

await send("Emulation.setDeviceMetricsOverride", { width: 1180, height: 900, deviceScaleFactor: 1, mobile: false });
await sleep(450);
const mid = JSON.parse(await evalJS(`(async () => {
  await openDoc(1);
  await new Promise(r => setTimeout(r, 420));
  const dr = document.getElementById("drawer").getBoundingClientRect();
  return JSON.stringify({
    drawerW: Math.round(dr.width), drawerRight: Math.round(window.innerWidth - dr.right),
    bodyOpen: document.body.classList.contains("drawer-open"),
    maskShow: document.getElementById("drawerMask").classList.contains("show"),
    paddingRight: getComputedStyle(document.querySelector(".content")).paddingRight
  });
})()`));
console.log("MID", JSON.stringify(mid));
if (mid.bodyOpen || !mid.maskShow || mid.paddingRight !== "28px" || mid.drawerRight > 16) {
  console.log("FAIL MID"); proc.kill(); process.exit(1);
}
await evalJS(`closeDrawer(); true`);
await sleep(260);

await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await sleep(450);
const narrow = JSON.parse(await evalJS(`(async () => {
  await openDoc(1);
  pwaState.shown = false; pwaState.dismissed = false;
  showPwaUpdate();
  await new Promise(r => setTimeout(r, 420));
  const dr = document.getElementById("drawer").getBoundingClientRect();
  const pwa = document.getElementById("pwaUpdate").getBoundingClientRect();
  const footer = document.getElementById("drawerFooter").getBoundingClientRect();
  const cs = getComputedStyle(document.querySelector(".content"));
  return JSON.stringify({
    innerWidth: window.innerWidth,
    drawerW: Math.round(dr.width), drawerTop: Math.round(dr.top), drawerH: Math.round(dr.height),
    bodyOpen: document.body.classList.contains("drawer-open"),
    maskShow: document.getElementById("drawerMask").classList.contains("show"),
    pwaShown: !document.getElementById("pwaUpdate").hidden,
    pwaLeft: Math.round(pwa.left), pwaRight: Math.round(pwa.right),
    pwaBottomGap: Math.round(window.innerHeight - pwa.bottom),
    footerTop: Math.round(footer.top),
    overlapFooter: pwa.bottom > footer.top,
    paddingRight: cs.paddingRight,
    overflowX: document.documentElement.scrollWidth > window.innerWidth
  });
})()`));
console.log("NARROW", JSON.stringify(narrow));
if (narrow.drawerW !== 390 || narrow.drawerTop !== 0 || narrow.drawerH < 800 ||
    narrow.bodyOpen || !narrow.maskShow || !narrow.pwaShown ||
    narrow.pwaLeft < 10 || narrow.pwaRight > 380 || narrow.overlapFooter || narrow.overflowX) {
  console.log("FAIL NARROW"); proc.kill(); process.exit(1);
}
await shotTo(OUT_NARROW, 390, 844, true);

const errors = logs.filter((l) => /EXCEPTION|Uncaught|ReferenceError|TypeError/.test(l));
console.log("ERRORS", errors.length, errors.slice(0, 3).join(" | "));
proc.kill();
process.exit(errors.length ? 1 : 0);
