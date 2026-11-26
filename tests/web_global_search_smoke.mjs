/* v0.26 第三块：全局搜索（同学 / 任务 / 材料 / 附件）的浏览器走查。
 * 用法：先起本地服务，再 node tests/web_global_search_smoke.mjs
 * 可选环境变量：PORT / URL / OUT / OUT_PERSON / OUT_NARROW / WIDTH / HEIGHT。
 */
import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = Number(process.env.PORT || 9244);
const PROFILE = `C:\\Users\\35342\\AppData\\Local\\Temp\\cc-v026-global-edge-${PORT}`;
const PAGE_URL = process.env.URL || "http://127.0.0.1:8781/web/";
const OUT = process.env.OUT || "C:\\Users\\35342\\Doubao\\chats\\2026-11-14\\new-chat\\v026-第三块-全局搜索.png";
const OUT_PERSON = process.env.OUT_PERSON || OUT.replace(/\.png$/, "-同学.png");
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
  if (await evalJS(`document.readyState === "complete" && !!document.getElementById("globalSearch")`)) break;
  await sleep(400);
}
await evalJS(`document.querySelector('button[data-theme-mode="light"]')?.click(); true`);
await evalJS(`document.querySelector(".fr-dismiss")?.click(); true`);

const typeQuery = async (value) => {
  await evalJS(`(() => {
    const i = document.getElementById("globalSearch");
    i.value = ${JSON.stringify(value)};
    i.dispatchEvent(new Event("input", { bubbles:true }));
    i.focus();
    return true;
  })()`);
  await sleep(320);
};
const snapshot = async () => JSON.parse(await evalJS(`JSON.stringify({
  show: document.getElementById("gsPop").classList.contains("show"),
  title: document.getElementById("gsTitle").textContent.trim(),
  groups: Array.from(document.querySelectorAll("#gsList .cmdk-group")).map(x => x.textContent.trim()),
  items: Array.from(document.querySelectorAll("#gsList .cmdk-item")).map(x => ({
    kind: x.querySelector(".ci-kind").textContent.trim(),
    title: x.querySelector(".ci-t").textContent.trim(),
    sub: x.querySelector(".ci-s")?.textContent.trim() || ""
  })),
  popW: Math.round(document.getElementById("gsPop").getBoundingClientRect().width),
  popRight: Math.round(document.getElementById("gsPop").getBoundingClientRect().right),
  innerWidth: window.innerWidth,
  overflowX: document.documentElement.scrollWidth > window.innerWidth
})`));

await typeQuery("团务");
const taskMat = await snapshot();
console.log("TASK_MATERIAL", JSON.stringify(taskMat));
const taskChecks = [
  taskMat.show,
  taskMat.groups.includes("任务"),
  taskMat.groups.includes("材料"),
  taskMat.items.some((x) => x.kind === "任务" && x.title === "十月团日材料收集"),
  taskMat.items.some((x) => x.kind === "材料" && x.title === "团日活动申报表"),
  !taskMat.overflowX
];
if (taskChecks.some((x) => !x)) { console.log("FAIL TASK_MATERIAL"); proc.kill(); process.exit(1); }

const shotTo = async (file, clipWidth = WIDTH) => {
  const metrics = await send("Page.getLayoutMetrics");
  const contentH = Math.ceil(metrics.result?.cssContentSize?.height || HEIGHT);
  const clip = { x: 0, y: 0, width: clipWidth, height: Math.min(1600, Math.max(HEIGHT, contentH)), scale: 1 };
  let shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip });
  if (!shot.result?.data) shot = await send("Page.captureScreenshot", { format: "png" });
  if (shot.result?.data) { writeFileSync(file, Buffer.from(shot.result.data, "base64")); console.log("SHOT", file); }
  else console.log("SHOT_SKIPPED", JSON.stringify(shot).slice(0, 300));
};
await shotTo(OUT);

const clickedTask = await evalJS(`(() => {
  const input = document.getElementById("globalSearch");
  input.dispatchEvent(new KeyboardEvent("keydown", { key:"Enter", bubbles:true }));
  return JSON.stringify({
    modal: document.getElementById("mask").classList.contains("show"),
    title: document.getElementById("modalTitle").textContent.trim(),
    taskTitle: document.getElementById("tkTitle")?.value || ""
  });
})()`).then(JSON.parse);
console.log("ENTER_TASK", JSON.stringify(clickedTask));
if (!clickedTask.modal || clickedTask.taskTitle !== "十月团日材料收集") {
  console.log("FAIL ENTER_TASK"); proc.kill(); process.exit(1);
}
await evalJS(`closeModal(); true`);
await typeQuery("团务");
const keys = await evalJS(`(() => {
  const input = document.getElementById("globalSearch");
  input.dispatchEvent(new KeyboardEvent("keydown", { key:"ArrowDown", bubbles:true }));
  const down = document.querySelector("#gsList .cmdk-item.on")?.querySelector(".ci-t").textContent.trim() || "";
  input.dispatchEvent(new KeyboardEvent("keydown", { key:"ArrowUp", bubbles:true }));
  const up = document.querySelector("#gsList .cmdk-item.on")?.querySelector(".ci-t").textContent.trim() || "";
  input.dispatchEvent(new KeyboardEvent("keydown", { key:"Escape", bubbles:true }));
  return JSON.stringify({
    down, up,
    closed: !document.getElementById("gsPop").classList.contains("show")
  });
})()`).then(JSON.parse);
console.log("KEYS", JSON.stringify(keys));
if (keys.down !== "团日活动申报表" || keys.up !== "十月团日材料收集" || !keys.closed) {
  console.log("FAIL KEYS"); proc.kill(); process.exit(1);
}
await typeQuery("团务");
const allToPalette = await evalJS(`(() => {
  document.getElementById("gsAll").click();
  return JSON.stringify({
    popClosed: !document.getElementById("gsPop").classList.contains("show"),
    palette: document.getElementById("cmdkMask").classList.contains("show"),
    query: document.getElementById("cmdkInput").value,
    groups: Array.from(document.querySelectorAll("#cmdkList .cmdk-group")).map(x => x.textContent.trim())
  });
})()`).then(JSON.parse);
console.log("ALL_TO_PALETTE", JSON.stringify(allToPalette));
if (!allToPalette.popClosed || !allToPalette.palette || allToPalette.query !== "团务" ||
    !allToPalette.groups.includes("任务") || !allToPalette.groups.includes("材料")) {
  console.log("FAIL ALL_TO_PALETTE"); proc.kill(); process.exit(1);
}
await evalJS(`closeCommandPalette(); true`);
await evalJS(`switchView("dashboard"); true`);
await sleep(200);

await typeQuery("王浩宇");
const person = await snapshot();
console.log("PERSON", JSON.stringify(person));
if (!person.show || !person.groups.includes("同学") || !person.items.some((x) => x.kind === "同学" && x.title === "王浩宇")) {
  console.log("FAIL PERSON"); proc.kill(); process.exit(1);
}
await shotTo(OUT_PERSON);

const clickedPerson = await evalJS(`(() => {
  const item = Array.from(document.querySelectorAll("#gsList .cmdk-item")).find(x =>
    x.querySelector(".ci-kind").textContent.trim() === "同学" &&
    x.querySelector(".ci-t").textContent.trim() === "王浩宇");
  if (!item) return JSON.stringify({ clicked:false });
  item.click();
  return JSON.stringify({
    clicked:true,
    view: state.current,
    rosterVisible: document.getElementById("view-roster").classList.contains("active"),
    focusSid: document.querySelector("#view-roster .mx-row.focus")?.dataset.sid || "",
    popClosed: !document.getElementById("gsPop").classList.contains("show")
  });
})()`).then(JSON.parse);
console.log("CLICK_PERSON", JSON.stringify(clickedPerson));
if (!clickedPerson.clicked || clickedPerson.view !== "roster" || !clickedPerson.rosterVisible || clickedPerson.focusSid !== "250217" || !clickedPerson.popClosed) {
  console.log("FAIL CLICK_PERSON"); proc.kill(); process.exit(1);
}
await sleep(2600);
await evalJS(`switchView("dashboard"); true`);
await sleep(200);

await typeQuery("docx");
const file = await snapshot();
console.log("FILE", JSON.stringify(file));
if (!file.show || !file.groups.includes("附件") || !file.items.some((x) => x.kind === "文件" && x.title === "新闻稿.docx")) {
  console.log("FAIL FILE"); proc.kill(); process.exit(1);
}

await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await sleep(450);
await typeQuery("docx");
const narrow = await snapshot();
console.log("NARROW", JSON.stringify(narrow));
if (!narrow.show || !narrow.groups.includes("附件") || narrow.overflowX) {
  console.log("FAIL NARROW"); proc.kill(); process.exit(1);
}
await shotTo(OUT_NARROW, 390);

const errors = logs.filter((l) => /EXCEPTION|Uncaught|ReferenceError|TypeError/.test(l));
console.log("ERRORS", errors.length, errors.slice(0, 3).join(" | "));
proc.kill();
process.exit(errors.length ? 1 : 0);
