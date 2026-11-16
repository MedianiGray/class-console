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
assert("自动编号按类别前缀", /^学分-\d{3}$/.test(row.code));
assert("种子记录编号回填", sandbox.listDocs().every(function(d){ return /^[一-龥]+-\d{3}$/.test(d.code); }));
const manual = sandbox.addDoc({ name:"手改编号", cat:"团务材料", who:"甲", sid:"250233", code:"团务-999" });
assert("手填编号保留", manual.code === "团务-999");
assert("路径字段兜底", sandbox.normalizeDoc({ name:"n", path:"D:/x/a.pdf" }, 0).path === "D:/x/a.pdf");

// 模板材料：类型 / 扩展内容 / 附件 / 模板前缀编号 / 备份往返
const mt = sandbox.addDoc({ name:"学风建设班会", cat:"团务材料", who:"主持人",
  form_type:"meeting", extra:{topic:"学风建设", place:"301"},
  attachments:[{name:"合影.jpg", path:"", kind:"照片"}] });
assert("模板类型写入", mt.form_type === "meeting");
assert("模板扩展内容往返", mt.extra.topic === "学风建设" && mt.extra.place === "301");
assert("模板附件落库", mt.attachments.length === 1 && mt.attachments[0].name === "合影.jpg");
assert("模板编号前缀", /^班会-\d{3}$/.test(mt.code));
const mtRow = sandbox.findDoc(mt.id);
assert("模板详情附件清单", mtRow.attachments.length === 1);
const bakT = sandbox.backup();
sandbox.restore(bakT.docs, bakT.logs, bakT.roster, bakT.tasks);
const mt2 = sandbox.listDocs().find(d => d.name === "学风建设班会");
assert("模板备份往返", mt2.form_type === "meeting" && mt2.extra.topic === "学风建设" && mt2.attachments.length === 1);

// CSV 转义
assert("CSV 纯文本原样", sandbox.csvCell("普通文本") === "普通文本");
assert("CSV 逗号加引号", sandbox.csvCell("a,b") === '"a,b"');
assert("CSV 引号翻倍", sandbox.csvCell('说"你好"') === '"说""你好"""');
assert("CSV 换行包裹", sandbox.csvCell("行1\n行2") === '"行1\n行2"');
assert("CSV 空值兜底", sandbox.csvCell(null) === "");

// CSV 导入解析
const csvRows = sandbox.parseCsv('材料名称,类别,提交人,学号,说明,附件\n"证明,复印件",奖助材料,李雨桐,250203,备注,');
assert("CSV 解析表头与一行", csvRows.length === 2 && csvRows[1][0] === "证明,复印件");
assert("CSV 引号翻倍还原", sandbox.parseCsv('"说""你好""",x')[0][0] === '说"你好"');
const headIdx = sandbox.mapCsvHeader(["材料名称","类别","提交人","学号","提交时间","状态","附件","说明"]);
assert("CSV 表头列映射", headIdx.name === 0 && headIdx.who === 2 && headIdx.file === 6 && headIdx.note === 7);

// 列显隐偏好
sandbox.saveHiddenCols(["sid", "file"]);
assert("隐藏列记录", sandbox.hiddenCols().join(",") === "sid,file");
const vis = sandbox.visibleCols().map(c => c.key);
assert("可见列不含隐藏项", vis.indexOf("sid") < 0 && vis.indexOf("file") < 0);
assert("可见列保留名称", vis.indexOf("name") >= 0);
sandbox.saveHiddenCols([]);
assert("恢复全显", sandbox.visibleCols().length === 8);

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

// schema 校验与兜底
const vErr = sandbox.validateRecord("doc", { name: "", who: "", sid: "abc", cat: "" });
assert("校验拦截必填", vErr.name && vErr.who && vErr.cat);
assert("校验拦截学号格式", /纯数字/.test(vErr.sid));
const okErr = sandbox.validateRecord("doc", { name: "x", who: "y", sid: "250201", cat: "团务材料" });
assert("合法记录无校验错", Object.keys(okErr).length === 0);
const norm = sandbox.normalizeDoc({ name: "n", cat: "c" }, 3);
assert("兜底补默认状态", norm.status === "待审核" && norm.scope === "全员" && norm.id === 4);
const normR = sandbox.normalizeDoc({ name: "n", cat: "c", reason: "材料不全" }, 0);
assert("记录保留审核备注", normR.reason === "材料不全");
assert("备注缺省兜底空串", sandbox.normalizeDoc({ name: "n" }, 0).reason === "");
assert("动作配置齐全", sandbox.typeDef("doc").actions.map(a => a.key).join(",") === "archive,reject");

// 名单数据层与核对统计
assert("种子名单 8 人", sandbox.listRoster().length === 8);
assert("按学号查姓名", sandbox.findRosterBySid("250201").who === "覃祖悦");
const chk0 = sandbox.rosterCheck();
assert("核对应交人数", chk0.total === 8);
assert("核对已交人数", chk0.done === 6);
assert("核对未交人数", chk0.absent.length === 2);
assert("未交名单含赵晓孙倩", chk0.absent.map(r => r.sid).sort().join(",") === "250205,250210");

const newR = sandbox.addRoster("250230", "测试生");
assert("新增名单入列", sandbox.findRosterBySid("250230").who === "测试生");
let dupThrew = false; try { sandbox.addRoster("250230", "重复"); } catch (e) { dupThrew = true; }
assert("重复学号拦截", dupThrew);
let numThrew = false; try { sandbox.addRoster("abc", "非数字"); } catch (e) { numThrew = true; }
assert("学号非纯数字拦截", numThrew);
let emptyThrew = false; try { sandbox.addRoster("", "无名"); } catch (e) { emptyThrew = true; }
assert("空学号拦截", emptyThrew);
sandbox.removeRoster(newR.id);
assert("移除名单", sandbox.findRosterBySid("250230") === null);

const parsed = sandbox.parseRosterText("250231,钱七\n250232\t孙八\n\n250233，周九");
assert("粘贴/CSV 解析三行", parsed.length === 3 && parsed[2].who === "周九");

// 任务数据层与截止统计
assert("种子任务 2 条", sandbox.listTasks().length === 2);
const tst0 = sandbox.taskStats();
assert("任务总数", tst0.total === 2);
assert("任务已完成 1", tst0.done === 1);
assert("进行中 1", tst0.ongoing === 1);
const nt = sandbox.addTask({ title:"冒烟任务", cat:"宣传材料", deadline:sandbox.dateToday(), scope:"全员", note:"n" });
assert("新增任务入列", sandbox.findTask(nt.id) != null);
assert("今天截止计入临期", sandbox.taskStats().due === 1);
let t1 = false; try { sandbox.addTask({ title:"", deadline:"2026-12-01" }); } catch(e){ t1 = true; }
assert("缺标题拦截", t1);
let t2 = false; try { sandbox.addTask({ title:"x", deadline:"" }); } catch(e){ t2 = true; }
assert("缺截止日期拦截", t2);
sandbox.toggleTask(nt.id);
assert("完成切换", sandbox.findTask(nt.id).done === true);
sandbox.updateTask(nt.id, { title:"改名任务" });
assert("更新任务标题", sandbox.findTask(nt.id).title === "改名任务");
sandbox.removeTask(nt.id);
assert("移除任务", sandbox.findTask(nt.id) === null);
const normT = sandbox.normalizeTask({ title:"x", cat:"c" }, 2);
assert("任务兜底范围与完成态", normT.scope === "全员" && normT.done === false && normT.id === 3);

// 备份/恢复结构
const bk = sandbox.backup();
assert("备份含 docs/logs/roster/tasks", Array.isArray(bk.docs) && Array.isArray(bk.logs) && Array.isArray(bk.roster) && Array.isArray(bk.tasks));
sandbox.restore(bk.docs, bk.logs);
assert("旧备份缺 roster 兜底空数组", Array.isArray(sandbox.store.roster) && sandbox.store.roster.length === 0);
sandbox.restore(bk.docs, bk.logs, bk.roster, bk.tasks);
assert("恢复名单回填", sandbox.listRoster().length === 8);
assert("恢复任务回填", sandbox.listTasks().length === 2);

console.log("\n结果: " + pass + " 通过, " + fail + " 失败");
process.exit(fail ? 1 : 0);
