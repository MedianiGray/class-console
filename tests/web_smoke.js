/* 网页版回归冒烟（Node，无浏览器依赖）。
 * 每次改动 web/index.html 后运行：
 *     node tests/web_smoke.js
 * 全部通过退出码 0；任一断言失败以非零退出结束。
 * 仅在内存 mock 上校验数据层契约、CSV 转义、列偏好与草稿暂存，不读写本机真实缓存。
 */
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf-8");
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: script block not found"); process.exit(1); }
const code = m[1];

function makeEl() {
  return {
    value: "", textContent: "", innerHTML: "", style: {}, dataset: {},
    checked: false, indeterminate: false, disabled: false, files: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    onclick: null, onchange: null, appendChild(){}, remove(){}, click(){},
    querySelectorAll(){ return []; }, addEventListener(){}
  };
}
const els = {};
const documentStub = {
  getElementById(id){ if (!els[id]) els[id] = makeEl(); return els[id]; },
  querySelectorAll(){ return []; },
  querySelector(){ return makeEl(); },
  addEventListener(){}, createElement(){ return makeEl(); },
  body: { appendChild(){} }
};
const storeMap = new Map();
const localStorageStub = {
  getItem(k){ return storeMap.has(k) ? storeMap.get(k) : null; },
  setItem(k,v){ storeMap.set(k, String(v)); },
  removeItem(k){ storeMap.delete(k); }
};
const sandbox = {
  document: documentStub, localStorage: localStorageStub,
  console, setTimeout(){}, URL: { createObjectURL(){ return "blob:x"; }, revokeObjectURL(){} },
  Blob: function(){}, FileReader: function(){},
  Date, Math, JSON, Array, Object, String, Number, RegExp, Error, isNaN, parseInt, parseFloat
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

let pass = 0, fail = 0;
function assert(name, cond) {
  if (cond) { pass++; console.log("PASS " + name); }
  else { fail++; console.log("FAIL " + name); }
}

// 种子与统计
const st = sandbox.stats();
assert("种子材料 7 条", st.total === 7);
assert("待审核 3", st.pending === 3);
assert("已归档 4", st.archived === 4);
assert("已驳回 0", st.rejected === 0);
assert("日志 6 条", sandbox.listLogs().length === 6);

// 数据层回归
assert("关键词检索命中", sandbox.listDocs("覃祖悦").length === 2);
assert("类别筛选", sandbox.listDocs("", "宣传材料").length === 2);
let threw = false;
try { sandbox.addDoc({ name: "", cat: "团务材料", who: "x" }); } catch (e) { threw = true; }
assert("缺必填抛错", threw);
const row = sandbox.addDoc({ name: "冒烟材料", cat: "学分材料", who: "测试", sid: "250299", note: "n", file: "" });
assert("新增材料入列", sandbox.findDoc(row.id) != null);
sandbox.archiveDoc(row.id);
assert("归档状态", sandbox.findDoc(row.id).status === "已归档");
sandbox.rejectDoc(row.id);
assert("驳回状态", sandbox.findDoc(row.id).status === "已驳回");

// CSV 转义
assert("CSV 纯文本原样", sandbox.csvCell("普通文本") === "普通文本");
assert("CSV 逗号加引号", sandbox.csvCell("a,b") === '"a,b"');
assert("CSV 引号翻倍", sandbox.csvCell('说"你好"') === '"说""你好"""');
assert("CSV 换行包裹", sandbox.csvCell("行1\n行2") === '"行1\n行2"');
assert("CSV 空值兜底", sandbox.csvCell(null) === "");

// 列显隐偏好
sandbox.saveHiddenCols(["sid", "file"]);
assert("隐藏列记录", sandbox.hiddenCols().join(",") === "sid,file");
const vis = sandbox.visibleCols().map(c => c.key);
assert("可见列不含隐藏项", vis.indexOf("sid") < 0 && vis.indexOf("file") < 0);
assert("可见列保留名称", vis.indexOf("name") >= 0);
sandbox.saveHiddenCols([]);
assert("恢复全显", sandbox.visibleCols().length === 7);

// 草稿暂存
els["sName"].value = "草稿名称"; els["sWho"].value = "张三"; els["sSid"].value = "250201";
els["sCat"].value = "学分材料"; els["sNote"].value = "备注";
sandbox.submitFile = "demo.pdf";
sandbox.saveDraft();
const dr = sandbox.loadDraft();
assert("草稿回读名称", dr.name === "草稿名称");
assert("草稿回读学号", dr.sid === "250201");
assert("草稿回读附件名", dr.file === "demo.pdf");
sandbox.clearDraft();
assert("草稿已清除", Object.keys(sandbox.loadDraft()).length === 0);

// 台账偏好持久化
sandbox.docsFilter.q = "覃祖悦"; sandbox.docsFilter.cat = "宣传材料";
sandbox.docsFilter.density = "compact"; sandbox.docsFilter.pageSize = 25;
sandbox.savePrefs();
sandbox.docsFilter.q = ""; sandbox.docsFilter.cat = "全部";
sandbox.docsFilter.density = "comfortable"; sandbox.docsFilter.pageSize = 10;
sandbox.applyPrefs();
assert("偏好回填关键词", sandbox.docsFilter.q === "覃祖悦");
assert("偏好回填类别", sandbox.docsFilter.cat === "宣传材料");
assert("偏好回填密度", sandbox.docsFilter.density === "compact");
assert("偏好回填条数", sandbox.docsFilter.pageSize === 25);
assert("名称列冻结类", sandbox.renderCell({name:"x", sid:"1", time:"", status:"待审核"}, "name").indexOf("sticky-l1") >= 0);

// 备份/恢复结构
const bk = sandbox.backup();
assert("备份含 docs/logs", Array.isArray(bk.docs) && Array.isArray(bk.logs));

console.log("\n结果: " + pass + " 通过, " + fail + " 失败");
process.exit(fail ? 1 : 0);
