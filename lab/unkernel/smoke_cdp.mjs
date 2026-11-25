import { spawn } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PROFILE = 'C:\\Users\\35342\\AppData\\Local\\Temp\\cc-unkernel-lab-edge';
const OUT = process.env.OUT || 'C:\\Users\\35342\\Doubao\\chats\\2026-11-14\\new-chat\\unkernel-本地引擎验证台.png';
const WIDTH = Number(process.env.WIDTH || 1440);
const HEIGHT = Number(process.env.HEIGHT || 1100);
rmSync(PROFILE, { recursive: true, force: true });
mkdirSync(PROFILE, { recursive: true });
const proc = spawn(EDGE, [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  '--no-default-browser-check',
  '--remote-debugging-port=9224',
  `--user-data-dir=${PROFILE}`,
  `--window-size=${WIDTH},${HEIGHT}`,
  'http://127.0.0.1:8780/',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 60; i++) {
  try {
    const list = await (await fetch('http://127.0.0.1:9224/json/list')).json();
    const page = list.find((x) => x.type === 'page');
    if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
  } catch {}
  await sleep(250);
}
if (!wsUrl) { console.log('NO_CDP'); proc.kill(); process.exit(1); }

const ws = new WebSocket(wsUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let id = 0;
const pending = new Map();
const logs = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === 'Runtime.consoleAPICalled') logs.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
  if (m.method === 'Runtime.exceptionThrown') logs.push('EXCEPTION ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
};
const send = (method, params = {}) => new Promise((resolve) => {
  const n = ++id; pending.set(n, resolve);
  ws.send(JSON.stringify({ id: n, method, params }));
});
const evalJS = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.text);
  return r.result?.result?.value;
};
await send('Runtime.enable');
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
await sleep(2000);

const support = await evalJS('document.getElementById("supportPill").textContent');
console.log('SUPPORT', support);
await evalJS('document.getElementById("bootBtn").click(); true');

let state = '';
for (let i = 0; i < 60; i++) {
  await sleep(1000);
  state = await evalJS('document.getElementById("status").textContent');
  if (i % 5 === 0) console.log('BOOT_WAIT', i + 1, state);
  if (state === '运行中' || state === '启动失败') break;
}
if (state !== '运行中') {
  console.log('BOOT_FAILED', await evalJS('document.getElementById("errtext").textContent'));
  console.log(logs.join('\n'));
  proc.kill();
  process.exit(1);
}

await evalJS('document.getElementById("cmdInput").value="help"; document.getElementById("cmdForm").requestSubmit(); true');
await sleep(500);
await evalJS('document.getElementById("cmdInput").value="uname -a"; document.getElementById("cmdForm").requestSubmit(); true');
await sleep(800);
await evalJS('document.getElementById("cmdInput").value="free"; document.getElementById("cmdForm").requestSubmit(); true');
await sleep(800);
const report = await evalJS(`JSON.stringify({
  boot: document.getElementById("bootNumber").textContent,
  status: document.getElementById("status").textContent,
  stats: document.getElementById("stats").textContent,
  uptime: document.getElementById("uptime").textContent,
  support: document.getElementById("supportPill").textContent,
  tail: Array.from(document.querySelectorAll("#term .line")).slice(-16).map(x=>x.textContent).join("\\n")
})`);
console.log('REPORT', report);

const metrics = await send('Page.getLayoutMetrics');
const height = Math.max(HEIGHT, Math.min(2600, Math.ceil(metrics.result.cssContentSize?.height || HEIGHT)));
const shot = await send('Page.captureScreenshot', {
  format: 'png',
  captureBeyondViewport: true,
  clip: { x: 0, y: 0, width: WIDTH, height, scale: 1 },
});
writeFileSync(OUT, Buffer.from(shot.result.data, 'base64'));
console.log('SHOT', OUT, 'height=' + height);
console.log('CONSOLE', logs.join('\n'));
proc.kill();
process.exit(0);
