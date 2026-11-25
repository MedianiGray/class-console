/*
 * A4 网页性能基线。
 *
 * 直接启动本机 Chrome（headless），通过 CDP 在真实页面里测量：
 *   1. 本地文件打开到 DOMContentLoaded / 首帧
 *   2. 5000 条材料的筛选 + 当前页渲染
 *   3. 50 条/页时的页面滚动帧间隔
 *   4. JS 堆和渲染进程工作集
 *
 * 用法：node tests/perf_web.js
 * 退出码：0 全部达标；1 有指标未达标或测试失败。
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const PAGE = path.join(ROOT, "web", "index.html");
const TEST_TMP = process.platform === "win32"
  ? path.join(process.env.LOCALAPPDATA || os.homedir(), "Temp")
  : os.tmpdir();
const PAGE_COPY = path.join(TEST_TMP, "cc-perf-web", "index.html");
const RUNS = 3;
const LIMITS = {
  firstScreenMs: 1000,
  filterMs: 100,
  scrollFps: 50,
  tabMemoryMB: 150,
};

function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].filter(Boolean);
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error("未找到 Chrome/Edge，可用 CHROME_PATH 指定");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function safeRm(target) {
  for (let i = 0; i < 5; i++) {
    try {
      fs.rmSync(target, { recursive: true, force: true });
      return;
    } catch (err) {
      if (err.code !== "EBUSY" && err.code !== "EPERM" && err.code !== "ENOTEMPTY") throw err;
      if (i === 4) return;
      execFileSync("cmd", ["/c", "ping", "127.0.0.1", "-n", "2", "-w", "300"], { stdio: "ignore" });
    }
  }
}

class Cdp {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const item = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) item.reject(new Error(msg.error.message));
        else item.resolve(msg.result);
      }
    };
  }

  async open() {
    if (this.ws.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = () => reject(new Error("CDP WebSocket 连接失败"));
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression, awaitPromise = false) {
    const out = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise,
    });
    if (out.exceptionDetails) {
      throw new Error(out.exceptionDetails.text + ": " + (out.exceptionDetails.exception || {}).description);
    }
    return out.result.value;
  }

  close() {
    try { this.ws.close(); } catch (_) {}
  }
}

function killTree(pid) {
  try {
    if (process.platform === "win32") {
      execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      process.kill(-pid, "SIGKILL");
    }
  } catch (_) {}
}

function rendererWorkingSetMB(profileDir) {
  if (process.platform !== "win32") return null;
  const ps = [
    "$ErrorActionPreference='Stop'",
    "$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--type=renderer*' -and $_.CommandLine -like '*" + profileDir.replace(/'/g, "''") + "*' }",
    "$ids = @($p | ForEach-Object { $_.ProcessId })",
    "if ($ids.Count -eq 0) { 0 } else {",
    "  $perf = Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | Where-Object { $ids -contains $_.IDProcess }",
    "  ($perf | Measure-Object WorkingSetPrivate -Sum).Sum",
    "}",
  ].join("; ");
  try {
    const raw = execFileSync("powershell", ["-NoProfile", "-Command", ps], { encoding: "utf8" }).trim();
    const bytes = Number(raw);
    return Number.isFinite(bytes) && bytes > 0 ? +(bytes / 1048576).toFixed(1) : null;
  } catch (_) {
    return null;
  }
}

async function launch(profileDir) {
  const headed = process.env.PERF_HEADED === "1";
  const chrome = spawn(findChrome(), [
    headed ? "--window-position=-32000,-32000" : "--headless=new",
    headed ? "--window-size=1280,960" : null,
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--disable-features=Translate,MediaRouter",
    "--js-flags=--expose-gc",
    "--remote-debugging-port=0",
    "--user-data-dir=" + profileDir,
    "about:blank",
  ].filter(Boolean), { stdio: ["ignore", "ignore", "pipe"] });

  const port = await new Promise((resolve, reject) => {
    let buf = "";
    const timer = setTimeout(() => reject(new Error("Chrome 启动超时，未拿到调试端口")), 15000);
    chrome.stderr.on("data", (chunk) => {
      buf += chunk.toString();
      const m = buf.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)/);
      if (m) {
        clearTimeout(timer);
        resolve(Number(m[1]));
      }
    });
    chrome.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error("Chrome 提前退出，退出码 " + code));
    });
  });

  let list;
  for (let i = 0; i < 20; i++) {
    try {
      list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      if (list.some((t) => t.type === "page")) break;
    } catch (_) {}
    await sleep(200);
  }
  const page = (list || []).find((t) => t.type === "page");
  if (!page) throw new Error("未找到可用的 Chrome 页面");
  return { chrome, cdp: new Cdp(page.webSocketDebuggerUrl) };
}

const SEED_AND_BENCH = String.raw`
(async () => {
  const orig = store.docs;
  const base = orig[0];
  const cats = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"];
  const statuses = ["待审核", "已归档", "已驳回", "待补材料"];
  const names = Array.from({ length: 40 }, (_, i) => String.fromCharCode(0x4e00 + (i % 80)) + "同学" + i);

  store.docs = Array.from({ length: 5000 }, (_, i) => {
    const d = JSON.parse(JSON.stringify(base));
    d.id = 900000 + i;
    d.name = "性能基线材料" + i;
    d.cat = cats[i % cats.length];
    d.who = names[i % names.length];
    d.sid = String(250000 + (i % 80));
    d.status = statuses[i % statuses.length];
    d.form_type = "general";
    d.created = "2026-11-" + String(1 + (i % 24)).padStart(2, "0") + " 10:00";
    d.note = "性能基线样本";
    return d;
  });

  switchView("docs");
  docsFilter.pageSize = 50;
  docsFilter.page = 1;

  function bench(label, q, cat, status) {
    docsFilter.q = q;
    docsFilter.cat = cat;
    docsFilter.status = status;
    docsFilter.page = 1;
    for (let w = 0; w < 2; w++) renderDocs();

    const render = [], filter = [];
    for (let n = 0; n < 7; n++) {
      let t0 = performance.now();
      const rows = filteredDocs();
      filter.push(performance.now() - t0);
      if (!Array.isArray(rows)) throw new Error("filteredDocs 返回异常");

      t0 = performance.now();
      renderDocs();
      render.push(performance.now() - t0);
      docsFilter.page = 1 + (n % 3);
    }
    render.sort((a, b) => a - b);
    filter.sort((a, b) => a - b);
    return {
      mode: label,
      matches: filteredDocs().length,
      filterMedianMs: +filter[3].toFixed(2),
      renderMedianMs: +render[3].toFixed(2),
      renderMaxMs: +render[6].toFixed(2),
    };
  }

  docsFilter.q = "";
  docsFilter.cat = "全部";
  docsFilter.status = "全部";
  docsFilter.page = 1;
  renderDocs();

  const benchResult = [
    bench("全部 5000", "", "全部", "全部"),
    bench("关键词命中", "同学7", "全部", "全部"),
    bench("类别+状态", "", "奖助材料", "待审核"),
  ];

  docsFilter.q = "";
  docsFilter.cat = "全部";
  docsFilter.status = "全部";
  docsFilter.page = 1;
  renderDocs();

  const frameGaps = await new Promise((resolve) => {
    const scroller = document.scrollingElement;
    const maxScroll = Math.max(0, scroller.scrollHeight - window.innerHeight);
    const gaps = [];
    let last = performance.now();
    let frames = 0;
    function step(now) {
      gaps.push(now - last);
      last = now;
      frames += 1;
      const ratio = frames / 119;
      window.scrollTo(0, Math.round(maxScroll * Math.min(1, ratio)));
      if (frames < 120) requestAnimationFrame(step);
      else resolve(gaps.slice(2));
    }
    window.scrollTo(0, 0);
    requestAnimationFrame(step);
  });
  frameGaps.sort((a, b) => a - b);
  const avgGap = frameGaps.reduce((a, b) => a + b, 0) / frameGaps.length;
  const scrollFps = +(1000 / avgGap).toFixed(1);
  const p95FrameMs = +frameGaps[Math.floor(frameGaps.length * 0.95)].toFixed(1);
  const longFrames = frameGaps.filter((g) => g > 33.3).length;

  if (typeof gc === "function") { gc(); await new Promise((r) => setTimeout(r, 80)); }
  const mem = performance.memory ? {
    jsHeapMB: +(performance.memory.usedJSHeapSize / 1048576).toFixed(1),
    jsHeapTotalMB: +(performance.memory.totalJSHeapSize / 1048576).toFixed(1),
  } : {};
  const domNodes = document.getElementsByTagName("*").length;
  const maxScroll = Math.max(0, document.scrollingElement.scrollHeight - window.innerHeight);

  store.docs = orig;
  return JSON.stringify({
    bench: benchResult,
    scroll: { scrollFps, p95FrameMs, longFrames, maxScroll, frames: frameGaps.length },
    memory: { ...mem, domNodes },
    renderedRows: document.querySelectorAll("tbody tr").length,
  });
})()
`;

async function oneRun(runNo) {
  const profileDir = path.join(TEST_TMP, "cc-perf-web-" + process.pid + "-" + runNo);
  safeRm(profileDir);
  fs.mkdirSync(profileDir, { recursive: true });

  let chrome;
  let cdp;
  try {
    const launched = await launch(profileDir);
    chrome = launched.chrome;
    cdp = launched.cdp;
    await cdp.open();
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    // 等浏览器自身初始化完成，只测“在已启动浏览器里打开页面”的耗时。
    await sleep(2500);
    const baselineRss = rendererWorkingSetMB(profileDir);

    const url = "file:///" + PAGE_COPY.replace(/\\/g, "/") + "?perf=" + Date.now() + "-" + runNo;
    await cdp.send("Page.navigate", { url });

    for (let i = 0; i < 60; i++) {
      const state = await cdp.eval("document.readyState");
      if (state === "complete") break;
      await sleep(100);
    }

    const timing = await cdp.eval(`JSON.stringify({
      dclMs: +performance.getEntriesByType("navigation")[0].domContentLoadedEventEnd.toFixed(1),
      loadMs: +performance.getEntriesByType("navigation")[0].loadEventEnd.toFixed(1),
      fcpMs: +(performance.getEntriesByType("paint").find(p => p.name === "first-contentful-paint") || {startTime: performance.now()}).startTime.toFixed(1)
    })`);
    const benchRaw = await cdp.eval(SEED_AND_BENCH, true);
    if (typeof benchRaw !== "string" || !benchRaw) throw new Error("性能脚本没有返回结果");
    const bench = JSON.parse(benchRaw);
    const ua = await cdp.eval("navigator.userAgent");
    const rss = rendererWorkingSetMB(profileDir);
    return { ...JSON.parse(timing), ...bench, rss, baselineRss, ua };
  } finally {
    if (cdp) cdp.close();
    if (chrome) {
      killTree(chrome.pid);
      await sleep(700);
    }
    safeRm(profileDir);
  }
}

function median(values) {
  const arr = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  return arr.length ? arr[Math.floor(arr.length / 2)] : null;
}

async function main() {
  if (!fs.existsSync(PAGE)) throw new Error("找不到 " + PAGE);
  fs.mkdirSync(path.dirname(PAGE_COPY), { recursive: true });
  fs.copyFileSync(PAGE, PAGE_COPY);
  const runs = [];
  for (let i = 1; i <= RUNS; i++) {
    process.stdout.write(`网页性能第 ${i}/${RUNS} 轮... `);
    const result = await oneRun(i);
    runs.push(result);
    console.log(`首屏 ${result.loadMs}ms，筛选 ${result.bench[2].renderMedianMs}ms，滚动 ${result.scroll.scrollFps}fps`);
  }

  const firstScreenMs = median(runs.map((r) => Math.max(r.dclMs, r.fcpMs)));
  const all5000Ms = median(runs.map((r) => r.bench[0].renderMedianMs));
  const filterMs = median(runs.map((r) => r.bench[2].renderMedianMs));
  const scrollFps = median(runs.map((r) => r.scroll.scrollFps));
  const p95FrameMs = median(runs.map((r) => r.scroll.p95FrameMs));
  const fullMemoryMB = median(runs.map((r) => r.rss).filter((v) => v != null));
  const baselineMemoryMB = median(runs.map((r) => r.baselineRss).filter((v) => v != null));
  const jsHeapMB = median(runs.map((r) => r.memory.jsHeapMB).filter((v) => v != null));

  const checks = [
    ["首屏可交互", firstScreenMs, LIMITS.firstScreenMs, "ms", firstScreenMs <= LIMITS.firstScreenMs],
    ["5000 条渲染（全部）", all5000Ms, LIMITS.filterMs, "ms", all5000Ms <= LIMITS.filterMs],
    ["5000 条筛选（类别+状态）", filterMs, LIMITS.filterMs, "ms", filterMs <= LIMITS.filterMs],
    ["50 条/页滚动帧率", scrollFps, LIMITS.scrollFps, "fps", scrollFps >= LIMITS.scrollFps],
    ["标签页内存（JS 堆）", jsHeapMB, LIMITS.tabMemoryMB, "MB", jsHeapMB != null && jsHeapMB <= LIMITS.tabMemoryMB],
  ];

  console.log("\n三轮明细：");
  console.log(`  浏览器：${runs[0].ua}`);
  for (const r of runs) {
    console.log(`  首屏 dcl=${r.dclMs}ms fcp=${r.fcpMs}ms 滚动=${r.scroll.scrollFps}fps p95=${r.scroll.p95FrameMs}ms 内存=${r.rss == null ? "N/A" : r.rss + "MB"}（空页 ${r.baselineRss == null ? "N/A" : r.baselineRss + "MB"}）`);
    console.log(`    ${r.bench.map((b) => `${b.mode} ${b.renderMedianMs}ms/${b.matches}条`).join("；")}；JS堆 ${r.memory.jsHeapMB || "N/A"}MB`);
  }
  console.log("\n中位数与判定：");
  for (const [name, value, limit, unit, ok] of checks) {
    console.log(`  ${ok ? "PASS" : "FAIL"} ${name}: ${value == null ? "N/A" : value + unit}（阈值 ${limit}${unit}）`);
  }
  console.log(`  参考：整页渲染进程私有工作集 ${fullMemoryMB == null ? "N/A" : fullMemoryMB + "MB"}（空白页基线 ${baselineMemoryMB == null ? "N/A" : baselineMemoryMB + "MB"}，含浏览器内核，不计入应用预算）`);

  const allPass = checks.every((c) => c[4]);
  console.log(`\nWEB PERF ${allPass ? "PASS" : "FAIL"}`);
  process.exitCode = allPass ? 0 : 1;
}

main().catch((err) => {
  console.error("WEB PERF ERROR:", err.message);
  process.exitCode = 2;
});
