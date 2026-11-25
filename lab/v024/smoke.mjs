import { spawn } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = Number(process.env.PORT || 9225);
const PROFILE = `C:\\Users\\35342\\AppData\\Local\\Temp\\cc-v024-edge-${PORT}`;
const OUT = process.env.OUT || 'C:\\Users\\35342\\Doubao\\chats\\2026-11-14\\new-chat\\v024-Bento借鉴版.png';
const PAGE_URL = process.env.URL || 'http://127.0.0.1:8781/lab/v024/';
const WIDTH = Number(process.env.WIDTH || 1440);
const HEIGHT = Number(process.env.HEIGHT || 1000);
rmSync(PROFILE, { recursive: true, force: true });
mkdirSync(PROFILE, { recursive: true });
const proc = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  `--window-size=${WIDTH},${HEIGHT}`, PAGE_URL,
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 60; i++) {
  try {
    const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
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
await sleep(1000);
for (let i = 0; i < 30; i++) {
  const ready = await evalJS(`document.readyState`);
  if (ready === 'complete' && await evalJS(`!!document.querySelector('button[data-theme-mode="light"]')`)) break;
  await sleep(500);
}
if (process.env.LIGHT) {
  await evalJS(`document.querySelector('button[data-theme-mode="light"]').click(); true`);
  await sleep(400);
}
if (process.env.DISMISS) {
  await evalJS(`document.querySelector('.fr-dismiss')?.click(); true`);
  await sleep(400);
}

const report = await evalJS(`(async()=>JSON.stringify({
  title: document.title,
  version: window.WEB_VERSION || '',
  current: document.querySelector('.nav button.active')?.textContent.trim(),
  cards: document.querySelectorAll('#view-dashboard .b-card').length,
  bento: !!document.querySelector('#view-dashboard .bento'),
  firstRun: !!document.querySelector('.first-run'),
  counts: Array.from(document.querySelectorAll('#view-dashboard .kpi .num')).map(x=>x.textContent),
  overflowX: document.documentElement.scrollWidth > window.innerWidth,
  bodyH: document.body.scrollHeight,
  manifest: document.querySelector('link[rel="manifest"]')?.getAttribute('href'),
  sw: (await navigator.serviceWorker.getRegistrations()).length,
  theme: document.documentElement.dataset.theme || 'system',
  console: 'ok'
}))()`);
console.log('REPORT', report);

// 切到台账再回看板，确认既有视图未被打断
await evalJS(`document.querySelector('.nav button[data-key="docs"]').click(); true`);
await sleep(600);
const docs = await evalJS(`JSON.stringify({current:window.state?.current, rows:document.querySelectorAll('#view-docs tbody tr').length})`);
console.log('DOCS', docs);
await evalJS(`document.querySelector('.nav button[data-key="dashboard"]').click(); true`);
await sleep(600);

// 申请人视角：常用入口必须按权限收窄，不能露出名单/任务/文件夹收集
await evalJS(`
  document.getElementById('applicantSid').value='250201';
  document.getElementById('applicantSid').oninput();
  var sel=document.getElementById('roleSelect'); sel.value='applicant'; sel.onchange();
  true`);
await sleep(700);
const applicant = await evalJS(`JSON.stringify({
  role:document.getElementById('roleSelect').value,
  entries:Array.from(document.querySelectorAll('#view-dashboard .b-entry a')).map(a=>a.textContent.replace('→','').trim()),
  collect:!!document.querySelector('#view-dashboard .b-entry a[data-go="collect"]')
})`);
console.log('APPLICANT', applicant);
await evalJS(`var sel=document.getElementById('roleSelect'); sel.value='handler'; sel.onchange(); true`);
await sleep(700);

const swReady = await evalJS(`Promise.race([navigator.serviceWorker.ready.then(()=>true), new Promise(r=>setTimeout(()=>r(false),3000))])`);
console.log('SW_READY', swReady);
const controlled = await evalJS(`!!navigator.serviceWorker.controller`);
console.log('SW_CONTROLLED', controlled);
if (!controlled) {
  await send('Page.reload');
  await sleep(1800);
}

const metrics = await send('Page.getLayoutMetrics');
const height = Math.max(HEIGHT, Math.min(3200, Math.ceil(metrics.result.cssContentSize?.height || HEIGHT)));
const shot = await send('Page.captureScreenshot', {
  format: 'png', captureBeyondViewport: true,
  clip: { x: 0, y: 0, width: WIDTH, height, scale: 1 },
});
writeFileSync(OUT, Buffer.from(shot.result.data, 'base64'));
console.log('SHOT', OUT, 'height=' + height);

// 断网重载：只验证静态壳与本地数据仍可用，不请求任何远端
await send('Network.enable');
await send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
await send('Page.reload', { ignoreCache: true });
let offlineReady = false;
for (let i = 0; i < 24; i++) {
  try {
    const ok = await evalJS(`document.readyState === 'complete' && !!document.querySelector('#view-dashboard')`);
    if (ok) { offlineReady = true; break; }
  } catch {}
  await sleep(500);
}
console.log('OFFLINE_READY', offlineReady);
const offline = await evalJS(`JSON.stringify({
  title:document.title,
  bento:!!document.querySelector('#view-dashboard .bento'),
  current:document.querySelector('.nav button.active')?.textContent.trim(),
  ready:document.readyState,
  firstRun:!!document.querySelector('.first-run'),
  counts:Array.from(document.querySelectorAll('#view-dashboard .kpi .num')).map(x=>x.textContent),
  cards:document.querySelectorAll('#view-dashboard .b-card').length,
  dash:document.querySelector('#view-dashboard')?.innerHTML.length,
  store:(localStorage.getItem('classconsole_web_v1')||'').length
})`);
console.log('OFFLINE', offline);
const offShot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(OUT.replace(/\.png$/i, '-offline.png'), Buffer.from(offShot.result.data, 'base64'));
await send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
console.log('CONSOLE', logs.join('\n'));
proc.kill();
process.exit(logs.some(x => x.startsWith('EXCEPTION')) ? 1 : 0);
