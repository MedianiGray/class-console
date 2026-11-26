/* v0.26 第二块：完成矩阵格子处置的浏览器走查。
 * 用法：先起本地服务，再 node tests/web_matrix_smoke.mjs
 * 可选环境变量：PORT / URL / OUT / OUT_TASK / OUT_NARROW / WIDTH / HEIGHT。
 * 会点开一个无记录格，生成一条催交任务，再验证任务台账；只写临时 profile。
 */
import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = Number(process.env.PORT || 9243);
const PROFILE = `C:\\Users\\35342\\AppData\\Local\\Temp\\cc-v026-matrix-edge-${PORT}`;
const PAGE_URL = process.env.URL || "http://127.0.0.1:8781/web/";
const OUT = process.env.OUT || "C:\\Users\\35342\\Doubao\\chats\\2026-11-14\\new-chat\\v026-第二块-矩阵格.png";
const OUT_TASK = process.env.OUT_TASK || OUT.replace(/\.png$/, "-任务台账.png");
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
  if (await evalJS(`document.readyState === "complete" && !!document.getElementById("view-roster")`)) break;
  await sleep(400);
}
await evalJS(`document.querySelector('button[data-theme-mode="light"]')?.click(); true`);
await evalJS(`document.querySelector(".fr-dismiss")?.click(); true`);

await evalJS(`switchView("roster"); rosterTab = "matrix"; renderRoster();
const cell = document.querySelector('.mx-cell[data-sid="250217"][data-cat="团务材料"]');
cell?.click();
true`);
await sleep(300);

const modal = JSON.parse(await evalJS(`JSON.stringify({
  show: document.getElementById("mask").classList.contains("show"),
  title: document.getElementById("modalTitle").textContent.trim(),
  body: document.getElementById("modalBody").innerText,
  buttons: Array.from(document.querySelectorAll("#modalActions button")).map(b => b.textContent.trim()),
  primary: !!document.querySelector("#modalActions button.primary"),
  cellSt: document.querySelector('.mx-cell[data-sid="250217"][data-cat="团务材料"]')?.dataset.st,
  taskCount: store.tasks.length,
  overflowX: document.documentElement.scrollWidth > window.innerWidth,
  bodyH: document.body.scrollHeight
})`));
console.log("MODAL", JSON.stringify(modal));
const checks = [
  modal.show,
  modal.title.includes("王浩宇"),
  modal.body.includes("团务材料"),
  modal.body.includes("无记录"),
  modal.body.includes("不等于一定欠交"),
  modal.buttons.includes("复制催交话术"),
  modal.buttons.includes("生成催交任务"),
  modal.primary,
  modal.cellSt === "—",
  !modal.overflowX
];
if (checks.some((x) => !x)) { console.log("FAIL MODAL_CONTRACT"); proc.kill(); process.exit(1); }

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

const generated = JSON.parse(await evalJS(`(() => {
  const btn = Array.from(document.querySelectorAll("#modalActions button")).find(b => b.textContent.trim() === "生成催交任务");
  if (!btn) return JSON.stringify({ clicked:false });
  const before = store.tasks.length;
  btn.click();
  const task = store.tasks.find(t => t.title === "催交：王浩宇 · 团务材料");
  return JSON.stringify({
    clicked:true, before, after:store.tasks.length,
    task: task ? { title:task.title, cat:task.cat, scope:task.scope, deadline:task.deadline, note:task.note } : null,
    modalClosed: !document.getElementById("mask").classList.contains("show"),
    toast: document.getElementById("toast")?.textContent || ""
  });
})()`));
console.log("GENERATED", JSON.stringify(generated));
const genChecks = [
  generated.clicked,
  generated.after === generated.before + 1,
  generated.task && generated.task.cat === "团务材料",
  generated.task && generated.task.scope === "本人",
  generated.task && /^\d{4}-\d{2}-\d{2}$/.test(generated.task.deadline),
  generated.task && generated.task.note.includes("无记录"),
  generated.modalClosed
];
if (genChecks.some((x) => !x)) { console.log("FAIL GENERATE_CONTRACT"); proc.kill(); process.exit(1); }

const revisit = JSON.parse(await evalJS(`(() => {
  document.querySelector('.mx-cell[data-sid="250217"][data-cat="团务材料"]')?.click();
  const body = document.getElementById("modalBody").innerText;
  const buttons = Array.from(document.querySelectorAll("#modalActions button")).map(b => b.textContent.trim());
  closeModal();
  return JSON.stringify({ body, buttons });
})()`));
console.log("REVISIT", JSON.stringify(revisit));
if (!revisit.buttons.includes("更新催交任务") || !revisit.body.includes("该格已有未完成任务")) {
  console.log("FAIL REVISIT_CONTRACT"); proc.kill(); process.exit(1);
}

await evalJS(`switchView("tasks"); refreshAll(); true`);
await sleep(300);
const taskView = JSON.parse(await evalJS(`JSON.stringify({
  rows: Array.from(document.querySelectorAll("#view-tasks tbody tr")).map(tr => tr.innerText),
  hasTask: document.getElementById("view-tasks").innerText.includes("催交：王浩宇 · 团务材料"),
  overflowX: document.documentElement.scrollWidth > window.innerWidth
})`));
console.log("TASK_VIEW", JSON.stringify(taskView));
if (!taskView.hasTask || taskView.overflowX) { console.log("FAIL TASK_VIEW"); proc.kill(); process.exit(1); }
await shotTo(OUT_TASK);

await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await sleep(400);
await evalJS(`switchView("roster"); rosterTab = "matrix"; renderRoster();
document.querySelector('.mx-cell[data-sid="250217"][data-cat="团务材料"]')?.click();
document.getElementById("toast")?.classList.remove("show");
true`);
await sleep(300);
const narrow = JSON.parse(await evalJS(`JSON.stringify({
  innerWidth: window.innerWidth,
  modalShow: document.getElementById("mask").classList.contains("show"),
  modalW: Math.round(document.querySelector(".modal").getBoundingClientRect().width),
  buttons: Array.from(document.querySelectorAll("#modalActions button")).map(b => b.textContent.trim()),
  overflowX: document.documentElement.scrollWidth > window.innerWidth,
  bodyH: document.body.scrollHeight
})`));
console.log("NARROW", JSON.stringify(narrow));
if (!narrow.modalShow || narrow.modalW > 390 || narrow.overflowX) { console.log("FAIL NARROW"); proc.kill(); process.exit(1); }
await shotTo(OUT_NARROW, 390);

const errors = logs.filter((l) => /EXCEPTION|Uncaught|ReferenceError|TypeError/.test(l));
console.log("ERRORS", errors.length, errors.slice(0, 3).join(" | "));
proc.kill();
process.exit(errors.length ? 1 : 0);
