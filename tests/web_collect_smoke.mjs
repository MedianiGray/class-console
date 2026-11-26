/* v0.26 第一块：收材料扫描三行摘要的浏览器走查。
 * 用法：先起本地服务，再 node tests/web_collect_smoke.mjs
 * 可选环境变量：PORT / URL / OUT / OUT_NARROW / WIDTH / HEIGHT。
 * 只向页面注入一份内存中的扫描结果，不选真实文件夹、不读文件、不写台账。
 */
import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = Number(process.env.PORT || 9242);
const PROFILE = `C:\\Users\\35342\\AppData\\Local\\Temp\\cc-v026-collect-edge-${PORT}`;
const PAGE_URL = process.env.URL || "http://127.0.0.1:8781/web/";
const OUT = process.env.OUT || "C:\\Users\\35342\\Doubao\\chats\\2026-11-14\\new-chat\\v026-第一块-收集摘要.png";
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
  if (await evalJS(`document.readyState === "complete" && !!document.getElementById("view-collect")`)) break;
  await sleep(400);
}
await evalJS(`document.querySelector('button[data-theme-mode="light"]')?.click(); true`);
await evalJS(`document.querySelector(".fr-dismiss")?.click(); true`);

await evalJS(`switchView("collect");
watch.dirName = "团日材料";
watch.error = ""; watch.failed = 0; watch.selected = {};
watch.items = [
  { rel:"250203_李雨桐_团日记录.docx", name:"250203_李雨桐_团日记录.docx", size:18432, mtime:1770000000000, state:"new" },
  { rel:"陈思颖-团日活动照片.jpg", name:"陈思颖-团日活动照片.jpg", size:204800, mtime:1770000100000, state:"new" },
  { rel:"250222_刘一帆_签到表.pdf", name:"250222_刘一帆_签到表.pdf", size:51200, mtime:1770000200000, state:"changed" },
  { rel:"未命名.docx", name:"未命名.docx", size:3072, mtime:1770000300000, state:"kept" }
];
watch.removed = [{ rel:"250217_王浩宇_旧版.pdf", name:"250217_王浩宇_旧版.pdf", size:4096, mtime:1769999000000 }];
renderCollect();
true`);

await sleep(300);
const summary = JSON.parse(await evalJS(`JSON.stringify({
  show: document.getElementById("cSummary").classList.contains("on"),
  rows: Array.from(document.querySelectorAll("#cSummary .cs-row")).map(r => ({
    key: r.querySelector(".cs-key").textContent.trim(),
    val: r.querySelector(".cs-val").textContent.trim()
  })),
  tableRows: document.querySelectorAll("#cBody tr[data-rel]").length,
  firstRow: document.querySelector("#cBody tr[data-rel]").innerHTML,
  overflowX: document.documentElement.scrollWidth > window.innerWidth,
  bodyH: document.body.scrollHeight
})`));
console.log("SUMMARY", JSON.stringify(summary));

const checks = [
  summary.show,
  summary.rows.length === 3,
  summary.rows[0]?.key === "谁交了" && summary.rows[0]?.val.includes("李雨桐"),
  summary.rows[1]?.key === "缺什么" && summary.rows[1]?.val.includes("王浩宇"),
  summary.rows[2]?.key === "下一步" && summary.rows[2]?.val.includes("勾选 2 个新增文件入账"),
  summary.tableRows === 5,
  !summary.overflowX
];
if (checks.some((x) => !x)) { console.log("FAIL SUMMARY_CONTRACT"); proc.kill(); process.exit(1); }

const shotTo = async (file, clipWidth = WIDTH) => {
  const metrics = await send("Page.getLayoutMetrics");
  const contentH = Math.ceil(metrics.result?.cssContentSize?.height || HEIGHT);
  const clip = { x: 0, y: 0, width: clipWidth, height: Math.min(2200, Math.max(HEIGHT, contentH)), scale: 1 };
  let shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip });
  if (!shot.result?.data) shot = await send("Page.captureScreenshot", { format: "png" });
  if (shot.result?.data) { writeFileSync(file, Buffer.from(shot.result.data, "base64")); console.log("SHOT", file); }
  else console.log("SHOT_SKIPPED", JSON.stringify(shot).slice(0, 300));
};
await shotTo(OUT);

await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await sleep(500);
const narrow = JSON.parse(await evalJS(`JSON.stringify({
  summaryShow: document.getElementById("cSummary").classList.contains("on"),
  rows: document.querySelectorAll("#cSummary .cs-row").length,
  innerWidth: window.innerWidth,
  visualWidth: window.visualViewport ? Math.round(window.visualViewport.width) : 0,
  tableW: Math.round(document.querySelector(".collect-table").getBoundingClientRect().width),
  wrapW: document.querySelector("#view-collect .table-wrap").clientWidth,
  wrapScroll: document.querySelector("#view-collect .table-wrap").scrollWidth > document.querySelector("#view-collect .table-wrap").clientWidth,
  overflowX: document.documentElement.scrollWidth > window.innerWidth,
  bodyH: document.body.scrollHeight
})`));
console.log("NARROW", JSON.stringify(narrow));
if (!narrow.summaryShow || narrow.rows !== 3 || narrow.tableW < 700 || narrow.overflowX) { console.log("FAIL NARROW"); proc.kill(); process.exit(1); }
await shotTo(OUT_NARROW, 390);

const errors = logs.filter((l) => /EXCEPTION|Uncaught|ReferenceError|TypeError/.test(l));
console.log("ERRORS", errors.length, errors.slice(0, 3).join(" | "));
proc.kill();
process.exit(errors.length ? 1 : 0);
