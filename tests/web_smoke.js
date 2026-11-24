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
    querySelector(){ return makeEl(); }, querySelectorAll(){ return []; }, addEventListener(){}
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
  console, setTimeout(){}, clearTimeout(){}, URL: { createObjectURL(){ return "blob:x"; }, revokeObjectURL(){} },
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

// 提醒中心快照：按岗位裁剪任务与名单，不做跨端推送
const remH = sandbox.reminderSnapshot();
assert("提醒快照含待审", remH.pending.length === 3);
assert("经办人提醒可含任务与名单", remH.canTask && remH.canRoster);
sandbox.state.role = "applicant";
sandbox.state.applicantSid = "250201";
const remA = sandbox.reminderSnapshot();
assert("申请人提醒不含任务", !remA.canTask && remA.tasks.length === 0);
assert("申请人提醒不含名单", !remA.canRoster && remA.absent.length === 0);
sandbox.state.role = "handler";
sandbox.state.applicantSid = "";

// 审批节点：提交 → 审核 → 归档，已归档节点带经办人与时间
const arcDoc = sandbox.listDocs().find(function(d){ return d.name === "反诈舞台剧剧照素材包"; });
const arcHtml = sandbox.approvalNodesHtml(arcDoc);
assert("已归档节点含归档动作", arcHtml.indexOf("通过并归档") >= 0 && arcHtml.indexOf("已登记") >= 0);
assert("归档节点带经办人", arcHtml.indexOf("覃祖悦") >= 0);
const pendDoc = sandbox.listDocs().find(function(d){ return d.status === "待审核"; });
const pendHtml = sandbox.approvalNodesHtml(pendDoc);
assert("待审节点提示等待处理", pendHtml.indexOf("等待经办人处理") >= 0);

// 申请人学号隔离：只看本人；未填学号不展示任何人的材料
sandbox.state.role = "applicant";
sandbox.state.applicantSid = "250201";
assert("申请人只看本人 2 条", sandbox.filteredDocs().length === 2);
assert("申请人统计只算本人", sandbox.stats(sandbox.visibleDocs()).total === 2);
sandbox.state.applicantSid = "";
assert("未填学号不展示材料", sandbox.filteredDocs().length === 0);
sandbox.state.role = "handler";
sandbox.state.applicantSid = "250201";
assert("经办人不受申请人学号影响", sandbox.filteredDocs().length === 7);
sandbox.state.applicantSid = "";

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

// 模板附加字段：新增 / 合并进表单 / 备份往返 / 旧备份保留现有配置
const cf = sandbox.addTemplateField("custom", { label:"佐证材料", type:"text", required:true });
const cfForm = sandbox.formTemplate("custom");
assert("附加字段写入模板", cfForm.fields.some(f => f.key === cf.key && f.label === "佐证材料" && f.required));
assert("附加字段 key 前缀", /^cf_/.test(cf.key));
let tplDup = false;
try { sandbox.addTemplateField("custom", { label:"佐证材料", type:"text" }); } catch (e) { tplDup = true; }
assert("同模板重名字段拦截", tplDup);
let tplSel = false;
try { sandbox.addTemplateField("custom", { label:"选项不足", type:"select", options:["A"] }); } catch (e) { tplSel = true; }
assert("下拉少于两项拦截", tplSel);
const tplBk = sandbox.backup();
assert("备份含模板字段", tplBk.templates.custom.some(f => f.label === "佐证材料"));
sandbox.restore(tplBk.docs, tplBk.logs, tplBk.roster, tplBk.tasks);
assert("旧备份缺模板保留现有配置", sandbox.templateCustom("custom").some(f => f.label === "佐证材料"));
sandbox.removeTemplateField("custom", cf.key);
assert("附加字段可删除", sandbox.templateCustom("custom").length === 0);
let builtinDel = false;
try { sandbox.removeTemplateField("custom", "name"); } catch (e) { builtinDel = true; }
assert("内置字段禁止删除", builtinDel);

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

// 已交口径：待审核/已归档算已交，只有已驳回进入需补交
const rs = sandbox.addRoster("250299", "需补交生");
const rc = sandbox.rosterCheck();
assert("已驳回归入需补交", rc.resubmit.some(r => r.sid === "250299"));
assert("需补交不计已交", rc.done === 6);
sandbox.removeRoster(rs.id);

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
let t3 = false; try { sandbox.addTask({ title:"x", deadline:"明天" }); } catch(e){ t3 = true; }
assert("非法日期格式拦截", t3);
const tf = sandbox.addTask({ title:"格式任务", deadline:"2026/12/01" });
assert("日期归一为 YYYY-MM-DD", tf.deadline === "2026-12-01");
sandbox.removeTask(tf.id);
let t4 = false; try { sandbox.updateTask(nt.id, { deadline:"2026-02-30" }); } catch(e){ t4 = true; }
assert("更新非法日期拦截", t4);
sandbox.toggleTask(nt.id);
assert("完成切换", sandbox.findTask(nt.id).done === true);
sandbox.updateTask(nt.id, { title:"改名任务" });
assert("更新任务标题", sandbox.findTask(nt.id).title === "改名任务");
sandbox.removeTask(nt.id);
assert("移除任务", sandbox.findTask(nt.id) === null);
const normT = sandbox.normalizeTask({ title:"x", cat:"c" }, 2);
assert("任务兜底范围与完成态", normT.scope === "全员" && normT.done === false && normT.id === 3);

// 文件夹监听：快照比对口径
const wEntries = [
  { rel:"a.pdf", name:"a.pdf", size:1024, mtime:1700000000000 },
  { rel:"b.jpg", name:"b.jpg", size:2048, mtime:1700000001000 },
  { rel:"c.docx", name:"c.docx", size:512, mtime:1700000002000 }
];
const first = sandbox.compareWatch(wEntries, {}, {});
assert("首次扫描全部记为新增", first.counts.new === 3 && first.items.length === 3);

const snap = sandbox.watchSnapshotOf(wEntries);
const secondEntries = [
  { rel:"a.pdf", name:"a.pdf", size:1024, mtime:1700000000000 },
  { rel:"b.jpg", name:"b.jpg", size:4096, mtime:1700000099000 },
  { rel:"d.png", name:"d.png", size:300, mtime:1700000003000 }
];
const second = sandbox.compareWatch(secondEntries, snap, {});
assert("二次扫描识别新增", second.counts.new === 1);
assert("二次扫描识别修改", second.counts.changed === 1);
assert("二次扫描识别不变", second.counts.kept === 1);
assert("二次扫描识别删除", second.counts.removed === 1 && second.removed[0].name === "c.docx");

const regHit = sandbox.compareWatch([{ rel:"e.x", name:"e.x", size:1, mtime:1 }], {}, { "e.x": true });
assert("已登记文件名不记为新增", regHit.items[0].state === "registered");
assert("去扩展名取材料名", sandbox.watchBaseName("班会签到表.pdf") === "班会签到表");
assert("大小换算 KB", sandbox.watchHumanSize(2048) === "2 KB");

sandbox.saveWatch("团日材料", snap, "11-18 10:00");
const wl = sandbox.loadWatch();
assert("监听目录名持久化", wl.dirName === "团日材料");
assert("监听基线持久化", Object.keys(wl.baseline).length === 3);
assert("已登记集合非空", Object.keys(sandbox.watchRegisteredSet()).length > 0);

// 备份/恢复结构
const bk = sandbox.backup();
assert("备份含 docs/logs/roster/tasks", Array.isArray(bk.docs) && Array.isArray(bk.logs) && Array.isArray(bk.roster) && Array.isArray(bk.tasks));
sandbox.restore(bk.docs, bk.logs);
assert("旧备份缺 roster 兜底空数组", Array.isArray(sandbox.store.roster) && sandbox.store.roster.length === 0);
sandbox.restore(bk.docs, bk.logs, bk.roster, bk.tasks);
assert("恢复名单回填", sandbox.listRoster().length === 8);
assert("恢复任务回填", sandbox.listTasks().length === 2);

// 列宽记忆与命令面板
assert("列宽下限收敛", sandbox.normalizeColWidth(10) === 60);
assert("列宽上限收敛", sandbox.normalizeColWidth(9999) === 520);
assert("列宽取整", sandbox.normalizeColWidth(137.6) === 138);
sandbox.colWidths.name = 333;
sandbox.saveColWidths();
assert("列宽写入本机", sandbox.loadColWidths().name === 333);
sandbox.colWidths.name = sandbox.defaultColWidth("name");
sandbox.saveColWidths();
assert("列宽恢复默认", sandbox.loadColWidths().name === 210);
const cgEmpty = sandbox.docsColgroupHtml();
assert("列组含复选框列", cgEmpty.indexOf('width:36px') >= 0);
const cmdHome = sandbox.buildCommandResults("");
const cmdGroups = cmdHome.map(function(x){ return x.group; });
assert("命令面板含视图与动作", cmdGroups.indexOf("跳转视图") >= 0 && cmdGroups.indexOf("常用动作") >= 0);
assert("命令面板首屏带最近材料", cmdGroups.indexOf("材料") >= 0);
const cmdDoc = sandbox.buildCommandResults("奖学金");
assert("命令面板可搜材料", cmdDoc.length === 1 && cmdDoc[0].kind === "doc");
const cmdExp = sandbox.buildCommandResults("导出");
assert("命令面板可搜动作", cmdExp.length === 1 && cmdExp[0].title.indexOf("导出") >= 0);
sandbox.state.role = "reviewer";
const cmdArc = sandbox.buildCommandResults(">归档");
assert(">归档 只返回动作", cmdArc.length >= 1 && cmdArc.every(function(x){ return x.kind === "act"; }));
assert(">归档 命中台账归档", cmdArc.some(function(x){ return x.title === "归档已选材料"; }));
assert(">归档 不混入材料", cmdArc.every(function(x){ return x.kind !== "doc"; }));

// 命名保存视图：筛选/排序/列宽/隐藏列一键还原、重名覆盖、删除
sandbox.docsFilter.q = "视图关键词"; sandbox.docsFilter.cat = "团务材料";
sandbox.docsFilter.type = "全部"; sandbox.docsFilter.status = "全部";
sandbox.docsFilter.sortKey = "name"; sandbox.docsFilter.sortDir = "asc";
sandbox.docsFilter.pageSize = 50; sandbox.docsFilter.density = "compact";
sandbox.colWidths.name = 333;
sandbox.saveHiddenCols(["file"]);
els["vName"].value = "冒烟视图";
let viewErr = null;
try { sandbox.saveNamedView(); } catch(e){ viewErr = e; }
assert("保存视图不抛错", viewErr === null);
const nv = sandbox.namedViews();
assert("命名视图已落库", nv.length === 1 && nv[0].name === "冒烟视图");
assert("视图快照含筛选", nv[0].filters.q === "视图关键词" && nv[0].filters.cat === "团务材料");
assert("视图快照含排序", nv[0].filters.sortKey === "name" && nv[0].filters.sortDir === "asc");
assert("视图快照含列宽", nv[0].widths.name === 333);
assert("视图快照含隐藏列", nv[0].hidden.indexOf("file") >= 0);
sandbox.docsFilter.q = ""; sandbox.docsFilter.cat = "全部";
sandbox.docsFilter.sortKey = "id"; sandbox.docsFilter.sortDir = "desc";
sandbox.colWidths.name = 210; sandbox.saveHiddenCols([]);
sandbox.applyNamedView(0);
assert("套用视图恢复筛选", sandbox.docsFilter.q === "视图关键词" && sandbox.docsFilter.cat === "团务材料");
assert("套用视图恢复排序", sandbox.docsFilter.sortKey === "name" && sandbox.docsFilter.sortDir === "asc");
assert("套用视图恢复列宽", sandbox.loadColWidths().name === 333);
assert("套用视图恢复隐藏列", sandbox.hiddenCols().indexOf("file") >= 0);
els["vName"].value = "冒烟视图"; sandbox.saveNamedView();
assert("同名视图覆盖不新增", sandbox.namedViews().length === 1);
sandbox.deleteNamedView(0);
assert("删除视图", sandbox.namedViews().length === 0);
sandbox.saveHiddenCols([]);
sandbox.colWidths.name = sandbox.defaultColWidth("name");
sandbox.saveColWidths();

// 完成矩阵：按名单出人，按五类出列，口径为有记录优先
const mxHtml = sandbox.rosterMatrix(sandbox.listRoster());
assert("矩阵表头含五类", ["团务材料","奖助材料","学分材料","宣传材料","班级事务"].every(function(c){ return mxHtml.indexOf(c) >= 0; }));
assert("矩阵含全部名单行", (mxHtml.match(/class="mx-row"/g) || []).length === sandbox.listRoster().length);
assert("矩阵标注无记录口径", mxHtml.indexOf("无记录不等于欠交") >= 0);
assert("矩阵已交格带样式", mxHtml.indexOf("mx-cell mx-ok") >= 0);


// 归档规则设计器：默认兼容、映射、变量与非法拦截
const arDoc = { name:"体测成绩统计表", cat:"团务材料", who:"刘一帆", sid:"250222", code:"团务-007" };
const arDefault = sandbox.archiveDefaultRule();
const arPath = sandbox.archivePreviewPath(arDoc, arDefault);
assert("默认规则路径沿用类别/学号姓名", arPath.indexOf("团务材料/250222-刘一帆") >= 0);
assert("默认文件名编号_材料名", arPath.endsWith("团务-007_体测成绩统计表.pdf"));
const arMap = sandbox.validateArchiveRule({
  dir_template:"{category}/{student}", file_template:"{sid}-{name}{ext}",
  category_map:{ "团务材料":"01-团务/证明材料" }
});
const arMapPath = sandbox.archivePreviewPath(arDoc, arMap);
assert("类别映射支持多级子目录", arMapPath.indexOf("01-团务/证明材料/250222-刘一帆") >= 0);
assert("文件名模板可改序并复用扩展名", arMapPath.endsWith("250222-体测成绩统计表.pdf"));
sandbox.saveArchiveRule(arMap);
assert("归档规则写入本机", sandbox.loadArchiveRule().category_map["团务材料"] === "01-团务/证明材料");
sandbox.saveArchiveRule(arDefault);
assert("归档规则恢复默认", Object.keys(sandbox.loadArchiveRule().category_map).length === 0);
function arReject(rule) {
  try { sandbox.validateArchiveRule(rule); return false; } catch(e){ return true; }
}
assert("拒绝绝对目录", arReject({ dir_template:"C:/越界" }));
assert("拒绝空目录模板", arReject({ dir_template:"" }));
assert("拒绝空文件名模板", arReject({ file_template:"" }));
assert("拒绝目录穿越", arReject({ dir_template:"../越界" }));
assert("拒绝文件名带目录", arReject({ file_template:"{name}/子目录" }));
assert("拒绝未知变量", arReject({ file_template:"{unknown}" }));
assert("拒绝映射穿越", arReject({ category_map:{ "团务材料":"../../越界" } }));
assert("空编号不留前导下划线", sandbox.archiveFileName({ name:"材料", cat:"团务材料" }, arDefault).indexOf("_材料") < 0);

// AI 助手：模型清单、镜像链路、系统提示、上下文与接口地址
assert("AI 模型清单三条", sandbox.AI_MODELS.length === 3);
sandbox.aiState.modelId = "Qwen2.5-0.5B-Instruct-q4f16_1-MLC";
const aiCfg05 = sandbox.aiLocalAppConfig();
assert("AI 权重走 hf-mirror", aiCfg05.model_list[0].model.indexOf("https://hf-mirror.com/mlc-ai/") === 0);
assert("AI 运行库走 jsDelivr", aiCfg05.model_list[0].model_lib.indexOf("cdn.jsdelivr.net/gh/mlc-ai/") >= 0);
assert("AI 0.5B 运行库对齐", aiCfg05.model_list[0].model_lib.endsWith("Qwen2-0.5B-Instruct-q4f16_1_cs1k-webgpu.wasm"));
sandbox.aiState.modelId = "DeepSeek-R1-Distill-Qwen-7B-q4f16_1-MLC";
const aiCfg7 = sandbox.aiLocalAppConfig();
assert("AI 7B 复用 Qwen2-7B 运行库", aiCfg7.model_list[0].model_lib.endsWith("Qwen2-7B-Instruct-q4f16_1_cs1k-webgpu.wasm"));
sandbox.aiState.modelId = "unknown-model";
assert("AI 未知模型回退默认", sandbox.aiLocalAppConfig().model_list[0].model_id === sandbox.AI_MODELS[0].id);
sandbox.aiState.modelId = sandbox.AI_MODELS[1].id;
const aiPrompt = sandbox.aiSystemPrompt();
assert("AI 提示禁止编造", aiPrompt.indexOf("不要编造") >= 0);
assert("AI 提示按通用材料链", aiPrompt.indexOf("接活—拆活—派活—收活—验活—汇总—定稿—交付—留底") >= 0);
assert("AI 提示不冒充已执行", aiPrompt.indexOf("不要声称已经提交") >= 0);
sandbox.state.role = "handler";
sandbox.aiState.includeDocs = true; sandbox.aiState.includeRoster = true; sandbox.aiState.includeTasks = true;
sandbox.aiState.taskNote = "";
const aiCtx = sandbox.aiBuildContext();
assert("AI 上下文含台账", aiCtx.indexOf("【当前材料台账】") >= 0);
assert("AI 上下文含名单", aiCtx.indexOf("【名单核对】") >= 0);
assert("AI 上下文含任务", aiCtx.indexOf("【任务跟踪】") >= 0);
sandbox.aiState.includeDocs = false; sandbox.aiState.includeRoster = false; sandbox.aiState.includeTasks = false;
assert("AI 上下文可全关", sandbox.aiBuildContext() === "");
assert("AI 空上下文有兜底", sandbox.aiRequestMessages()[0].content.indexOf("（未选择任何上下文）") >= 0);
sandbox.aiState.includeDocs = true; sandbox.aiState.includeRoster = true; sandbox.aiState.includeTasks = true;
sandbox.aiState.messages = [{role:"user", content:"拆任务"}, {role:"assistant", content:""}, {role:"assistant", content:"生成失败：x"}];
const aiReq = sandbox.aiRequestMessages();
assert("AI 消息只留一条 system", aiReq.filter(m => m.role === "system").length === 1 && aiReq[0].role === "system");
assert("AI 过滤空占位与失败气泡", aiReq.length === 2 && aiReq[1].role === "user");
sandbox.aiState.messages = [];
sandbox.aiState.apiBase = "https://api.deepseek.com/";
assert("AI 接口地址补全", sandbox.aiApiEndpoint() === "https://api.deepseek.com/chat/completions");
sandbox.aiState.apiBase = "https://api.deepseek.com/v1/chat/completions";
assert("AI 完整接口不重复拼接", sandbox.aiApiEndpoint() === "https://api.deepseek.com/v1/chat/completions");
sandbox.aiState.apiBase = "https://api.deepseek.com";

// 更多功能：辅助项收口、分类、按权限收敛
sandbox.state.role = "handler";
assert("更多入口分组为更多", sandbox.NAV_GROUPS[2].label === "更多");
assert("更多功能收纳三项辅助", sandbox.moreItems().length === 3);
assert("更多功能按两类分组", sandbox.moreMenuSections().length === 2);
assert("智能辅助只含 AI", sandbox.moreMenuSections()[0].items.length === 1 && sandbox.moreMenuSections()[0].items[0].key === "ai");
assert("文件与留痕含收集与日志", sandbox.moreMenuSections()[1].items.length === 2);
const moreHtml = sandbox.moreMenuHtml();
assert("更多菜单不混入主流程", moreHtml.indexOf("智能辅助") >= 0 && moreHtml.indexOf("文件与留痕") >= 0 && moreHtml.indexOf("工作台概览") < 0);
sandbox.state.role = "applicant";
assert("申请人更多入口只留 AI", sandbox.moreItems().length === 1 && sandbox.moreMenuSections().length === 1);
sandbox.state.role = "handler";

// 首次引导：示例数据不计进度、三步卡可收起、可从更多重看
sandbox.state.applicantSid = "";
sandbox.store.docs = sandbox.SEED_DOCS.map(function(d, i){ return Object.assign({id: i + 1}, d); });
sandbox.store.logs = sandbox.SEED_LOGS.map(function(l, i){ return Object.assign({id: i + 1}, l); });
sandbox.store.roster = sandbox.SEED_ROSTER.map(function(r, i){ return Object.assign({id: i + 1}, r); });
sandbox.store.tasks = sandbox.SEED_TASKS.map(function(t, i){ return Object.assign({id: i + 1}, t); });
sandbox.store.demo = true;
sandbox.firstRun.dismissed = false;
assert("种子标记示例数据", sandbox.store.demo === true && sandbox.store.docs.every(d => d.demo));
const fr0 = sandbox.firstRunProgress();
assert("示例数据不计上手进度", fr0.steps.filter(s => s.done).length === 0 && fr0.done === false);
const frHtml = sandbox.firstRunHtml();
assert("首导卡为三步", (frHtml.match(/<div class="step(?=[ "])/g) || []).length === 3);
assert("首导卡可收起", frHtml.indexOf("data-first-run-dismiss") >= 0);
assert("首导卡提示示例数据", frHtml.indexOf("示例数据") >= 0);
assert("首导卡可清示例", frHtml.indexOf("data-demo-clear") >= 0);
sandbox.firstRun.dismissed = true;
assert("收起后不再渲染首导", sandbox.firstRunHtml() === "");
sandbox.firstRun.dismissed = false;
assert("更多菜单带使用帮助", moreHtml.indexOf("data-more-help") >= 0 && moreHtml.indexOf("使用帮助") >= 0);

// 真实材料与归档才算完成；申请人只看本人步骤
sandbox.store.docs.push({id:99, name:"真实材料", status:"已归档", sid:"250201", demo:false});
const fr1 = sandbox.firstRunProgress();
assert("真实归档完成前两步", fr1.steps[0].done && fr1.steps[1].done && fr1.done === true);
sandbox.firstRun.dismissed = false;
sandbox.maybeCompleteFirstRun();
assert("真实归档后首导自动收起", sandbox.firstRun.dismissed === true);
sandbox.firstRun.seen = false;
sandbox.firstRun.dismissed = false;
sandbox.initFirstRun();
assert("已有真实数据的老用户不打扰", sandbox.firstRun.dismissed === true);
sandbox.firstRun.dismissed = false;
sandbox.state.role = "applicant";
sandbox.state.applicantSid = "250201";
const frA = sandbox.firstRunProgress();
assert("申请人文案只三步", frA.isApplicant && frA.steps[0].title.indexOf("学号") >= 0);
assert("申请人按本人学号计进度", frA.steps[0].done && frA.steps[1].done);
sandbox.state.role = "handler";
sandbox.state.applicantSid = "";
sandbox.store.docs.pop();

// A2 空态：统一标题 + 说明 + 主动作，且产品文案不再出现裸「暂无」
const emptySample = sandbox.emptyState(
  "还没有测试数据", "这里说明为什么为空以及下一步。",
  sandbox.emptyBtn("去做第一步", 'data-empty-go="dashboard"'));
assert("空态含统一标题", emptySample.indexOf('class="empty-title"') >= 0);
assert("空态含说明", emptySample.indexOf('class="empty-sub"') >= 0);
assert("空态含主动作", emptySample.indexOf('class="empty-actions"') >= 0 && emptySample.indexOf("去做第一步") >= 0);
assert("空态按钮保留动作属性", emptySample.indexOf('data-empty-go="dashboard"') >= 0);
assert("文件夹读取失败有恢复路径", html.indexOf("这个文件夹里的文件没有读出来") >= 0 && html.indexOf("watch.failed") >= 0);
assert("产品界面无裸暂无", !/暂无/.test(html));

// A3 错误态与恢复路径：存储失败、备份不匹配、错误四段、AI 失败脱敏
const a3Bk = sandbox.backup();
assert("备份带应用标识与条数", a3Bk.app === "class-console" && a3Bk.counts.docs === a3Bk.docs.length);
assert("损坏备份被结构校验拦截", sandbox.backupShapeIssue(null) !== "" && sandbox.backupShapeIssue({docs:"x", logs:[]}) !== "");
const a3Mismatch = JSON.parse(JSON.stringify(a3Bk));
a3Mismatch.counts.docs = a3Mismatch.docs.length + 1;
assert("导入预览条数不匹配拦截", sandbox.backupShapeIssue(a3Mismatch).indexOf("实际解析") >= 0);
const a3BadRow = JSON.parse(JSON.stringify(a3Bk));
a3BadRow.docs.push("不是对象");
assert("格式异常记录不导入", sandbox.backupShapeIssue(a3BadRow).indexOf("格式异常") >= 0);
const a3Copy = sandbox.errorCopyHtml("发生了什么", "影响范围", "下一步", "兜底");
assert("错误四段齐全", ["发生了什么","影响范围","下一步","兜底"].every(k => a3Copy.indexOf(k) >= 0));
assert("错误态有恢复动作区", sandbox.errorState("标题", "发生了什么", "影响范围", "下一步", "兜底", "<button>重试</button>").indexOf("重试") >= 0);
const a3Ai401 = sandbox.aiErrorInfo({status:401, message:"接口返回 401：Bearer sk-secret"});
assert("AI 401 归类为 Key 失效", a3Ai401.what.indexOf("Key 无效") >= 0);
assert("AI 错误不泄露 Key 与回包", JSON.stringify(a3Ai401).indexOf("sk-secret") < 0 && JSON.stringify(a3Ai401).indexOf("Bearer") < 0);
const a3AiNet = sandbox.aiErrorInfo(new TypeError("Failed to fetch"));
assert("AI 断网归为网络或跨域", a3AiNet.what.indexOf("请求没有到达") >= 0);

const a3OrigSet = localStorageStub.setItem;
const a3DocsBefore = sandbox.store.docs.length;
localStorageStub.setItem = function(){ const e = new Error("quota"); e.name = "QuotaExceededError"; throw e; };
sandbox.saveStore();
assert("配额满降级为内存态", sandbox.state.persist === false && sandbox.storageState.issue === "quota");
assert("存储失败不清空现有数据", sandbox.store.docs.length === a3DocsBefore);
assert("存储失败有常驻提示", sandbox.storageState.issue === "quota" && html.indexOf('id="storageNotice"') >= 0);
localStorageStub.setItem = a3OrigSet;
sandbox.saveStore();
assert("重试写入恢复持久化", sandbox.state.persist === true && sandbox.storageState.issue === null);

console.log("\n结果: " + pass + " 通过, " + fail + " 失败");
process.exit(fail ? 1 : 0);
