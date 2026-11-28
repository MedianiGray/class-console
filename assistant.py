# -*- coding: utf-8 -*-
"""助手逻辑层：把「一句话需求」接到项目已有的能力上。

两层路由：
1. 本地规则：不联网也能用。识别学号/姓名、缺项、催交、待审、谁没交、
   概览、打开视图、朗读，直接查本机台账后作答。
2. AI 意图：配好 API 时，只把「用户这句话 + 能力清单」发出去，让模型选
   一个意图和参数；台账数据、名单、材料内容一概不出本机，执行仍在这里。
   AI 不可用时静默回落本地规则，不阻断。

边界：只读 + 生成话术 + 朗读 + 切视图；不写台账、不改状态、不归档。
"""

import re

import ai
import service

# 能力清单：既是帮助文案，也是给 AI 的意图表
CAPS = (
    ("overview", "台账概览", "现在还缺多少材料"),
    ("status", "某人缺哪几类", "250223 还缺什么"),
    ("chase", "催交话术", "给他写催交话术"),
    ("doc_info", "当前这份材料", "这份什么情况"),
    ("pending", "待审清单", "有哪些待审的"),
    ("missing_people", "谁还没交", "谁还没交材料"),
    ("projects", "项目进度", "现在有哪些项目"),
    ("project_detail", "单个项目缺什么", "班级材料项目还缺什么"),
    ("open_view", "打开页面", "打开服务留痕"),
    ("speak", "朗读上一句", "念一下"),
    ("help", "能做什么", "你都能做什么"),
)

VIEWS = (
    ("dashboard", "概览", ("概览", "看板", "首页", "dashboard")),
    ("docs", "材料台账", ("台账", "材料台账", "材料")),
    ("files", "文件室", ("文件室", "文件")),
    ("submit", "提交材料", ("提交", "收材料", "提交材料")),
    ("roster", "名单核对", ("名单", "名单核对")),
    ("tasks", "任务跟踪", ("任务", "任务跟踪", "待办")),
    ("service", "服务留痕", ("服务", "服务留痕", "催交记录")),
    ("logs", "审计日志", ("日志", "审计", "记录")),
    ("projects", "项目工作台", ("项目", "项目工作台", "交付物")),
    ("media", "媒体工作台", ("媒体", "媒体工作台", "转码", "音频")),
    ("doctools", "文档工作台", ("文档工具", "文档工作台", "PDF", "拆分", "合并", "OCR",
                                "图片批处理", "转 Word", "转 PDF")),
)

SPEAK_WORDS = ("朗读", "念一下", "念一遍", "读一下", "读一遍", "念给我")
HELP_WORDS = ("能做什么", "你能干", "你会什么", "帮助", "怎么用", "help")
OPEN_WORDS = ("打开", "切到", "切换到", "去一下", "去 ")
OVERVIEW_WORDS = ("概览", "统计", "多少份", "什么情况", "整体", "总览", "进度")
PENDING_WORDS = ("待审", "待审核", "没审")
MISSING_WORDS = ("谁没交", "谁还没交", "谁缺", "缺人", "没交的有", "催谁")
CHASE_WORDS = ("催交", "催一下", "催 ", "写个话术", "话术", "提醒他交", "提醒她交")
STATUS_WORDS = ("还缺", "缺什么", "缺哪", "交了什么", "交了哪些", "状态", "查到")
# 指代：说话人省略了主语，得靠上一轮记住的人来补
PRONOUN_WORDS = ("他", "她", "这个人", "那位", "该同学", "这位", "刚才那位")
# 指代「当前这份材料」：要主窗口把选中的那份递进来
DOC_WORDS = ("这份", "这篇", "当前这份", "选中的")
# 写操作：认得出，但不做，明确回绝
WRITE_WORDS = ("归档", "驳回", "删除", "删掉", "清空", "改状态", "登记进台账")
WRITE_CUES = ("把", "帮我", "直接", "给我", "替我", "一下")

AI_SYSTEM = (
    "你是班级操作台的助手，只负责把用户的话翻译成一个意图，不要回答问题本身。"
    "可选意图：%s。"
    '只输出一个 JSON 对象：{"intent":"意图名","args":{...},"reply":"不超过20字的回应"}。'
    "args 可用键：sid（6位学号）、who（姓名）、view（页面名）、project（项目名）。"
    "用户可能省略主语（「他缺什么」「这份能归档吗」），这时把 args 留空，由本地上下文补。"
    "没有把握时 intent 用 unknown，不要编造学号和姓名。"
)


def _clean(value):
    return str(value or "").strip()


class Assistant(object):
    """无界面依赖的助手内核。界面负责拿结果去显示。"""

    def __init__(self, repo, cfg_loader=None, speak=None, open_view=None, context=None):
        self.repo = repo
        self.cfg_loader = cfg_loader or ai.load_config
        self.speak = speak
        self.open_view = open_view
        self.context = context        # 主窗口递进来的当前视图与选中材料
        self.ctx = {"person": None, "cats": [], "doc_id": None}   # 会话里记住的人
        self.last_text = ""      # 上一句可朗读的回复
        self.last_action = ""

    # ---------- 对外 ----------
    def capabilities(self):
        return ["「%s」%s" % (c[1], c[2]) for c in CAPS]

    def ai_ready(self):
        try:
            return bool(ai.api_ready(self.cfg_loader() or {}))
        except Exception:
            return False

    def ai_note(self):
        """没接 AI 时的一句话交代，别让人以为它听不懂是 bug。"""
        return "" if self.ai_ready() else "（未接 AI 通道，我按本地规则理解，不联网）"

    def brief_text(self):
        """主动开场：不问也先给一条今天的状态，纯本地查库。"""
        try:
            stats = self.repo.stats() or {}
        except Exception:
            stats = {}
        try:
            check = self.repo.roster_check() or {}
        except Exception:
            check = {}
        parts = ["待审 %s 份" % stats.get("pending", 0)]
        if check:
            left = len(check.get("absent") or []) + len(check.get("resubmit") or [])
            parts.append(("%s 人未交" % left) if left else "名单都齐了")
        return "今天：" + "、".join(parts) + "。"

    def help_text(self):
        lines = ["我能直接查本机台账、名单、任务和项目，也能替你把话术、朗读、切页面接起来。"]
        lines.append("AI 通道：%s" % ("已接上，能听懂更自由的说法"
                                   if self.ai_ready() else "未接，我按本地规则理解，不联网"))
        hotkey = getattr(self, "hotkey_note", "")
        lines.append("唤起：%s" % (hotkey or "点我，或用顶栏「✦ 助手」"))
        lines.append("展开时我会把你当前在哪一页、选中了谁都摆在上面；"
                     "没说清是谁，我会反问，不猜。")
        lines.append("窗口够宽时我嵌在窗口右侧那条，不压你正在看的详情；"
                     "窗口窄了才浮在角上。右键可以把这条改掉。")
        lines.append("试试这样说：")
        for cap in CAPS:
            if cap[0] == "help":
                continue
            lines.append("· %s —— 比如「%s」" % (cap[1], cap[2]))
        lines.append("说过一个人之后，可以直接说「他缺什么」「给他写话术」，我记得是谁。")
        lines.append("我不会改台账、不归档、不猜分类；要我登记请用提交材料页。")
        return "\n".join(lines)

    def handle(self, text):
        """返回 {'ok','text','action','source'}，永不抛异常。"""
        raw = _clean(text)
        if not raw:
            return {"ok": False, "text": "说一句就行。", "action": "", "source": "local"}
        try:
            local = self._local(raw)
            if local and local.get("action") != "unknown":
                return local
            intent, args, why = self._ai_intent(raw)
            if intent and intent != "unknown":
                return self._exec(intent, args, raw, source="api")
            if local:
                return local
            hint = "" if not self.ai_ready() else "（%s）" % (why or "本地规则未命中")
            return {"ok": False, "action": "unknown", "source": "local",
                    "text": "这句话我还没接上能力%s%s。可以问：谁还没交材料、250223 还缺什么、"
                            "这份什么情况、给他写条催交话术、打开服务留痕。"
                            % (hint, self.ai_note())}
        except Exception as e:                                  # 界面不能因为助手崩
            return {"ok": False, "action": "error", "source": "local",
                    "text": "助手内部出错了：%s" % e}

    def ask(self, text):
        result = self.handle(text)
        self.last_text = result.get("text") or ""
        self.last_action = result.get("action") or ""
        return result

    # ---------- 人 ----------
    def _roster(self):
        try:
            return self.repo.list_roster()
        except Exception:
            return []

    def _find_person(self, text):
        """先认 6 位学号，再认名单里的姓名；认不出返回 {}。"""
        m = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
        if m:
            sid = m.group(1)
            row = None
            try:
                row = self.repo.find_roster_by_sid(sid)
            except Exception:
                row = None
            return {"sid": sid, "who": _clean(row.get("who")) if row else ""}
        roster = self._roster()
        best = None
        for r in roster:
            name = _clean(r.get("who"))
            if len(name) >= 2 and name in text:
                if best is None or len(name) > len(best[1]):
                    best = (r, name)
        if best:
            return {"sid": _clean(best[0].get("sid")), "who": best[1]}
        return {}

    # ---------- 台账 ----------
    def _docs(self):
        try:
            return self.repo.list_docs()
        except Exception:
            return []

    def _exemptions(self):
        try:
            rows = self.repo.list_exemptions(active_only=True)
        except Exception:
            return {}
        return {(r.get("sid"), r.get("cat")): r for r in rows}

    def _receipts(self):
        try:
            return self.repo.latest_receipts() or {}
        except Exception:
            return {}

    def _docs_of(self, sid, docs=None):
        docs = docs if docs is not None else self._docs()
        return [d for d in docs if _clean(d.get("sid")) == sid]

    def student_status(self, sid, who=""):
        docs = self._docs()
        missing = service.missing_categories(docs, sid, self._exemptions(), self._receipts())
        done = []
        for cat in service.MATRIX_CATS:
            if cat in missing:
                continue
            st = service.cell_status(docs, sid, cat, self._exemptions(), self._receipts())
            if st:
                done.append("%s（%s）" % (cat, st))
        head = "%s %s" % (_clean(who) or "这个学号", sid)
        lines = [head]
        lines.append("已交/已处理：%s" % ("、".join(done) if done else "暂无"))
        lines.append("还缺：%s" % ("、".join(missing) if missing else "都齐了"))
        if missing:
            lines.append("要我写成催交话术，就说「给%s写催交话术」。" % (_clean(who) or sid))
        return "\n".join(lines), missing

    def doc_text(self, doc):
        """讲清「当前这份材料」是什么、同人还缺什么；只报事实，不给能不能归档的判断。"""
        doc = doc or {}
        who = _clean(doc.get("who"))
        sid = _clean(doc.get("sid"))
        cat = _clean(doc.get("cat"))
        st = _clean(doc.get("status"))
        lines = ["这份：%s %s · %s · %s" % (who or "?", sid or "?",
                                          cat or "?", st or "未标注")]
        meta = []
        if _clean(doc.get("time")):
            meta.append("提交 %s" % _clean(doc.get("time")))
        if _clean(doc.get("name")):
            meta.append("文件「%s」" % _clean(doc.get("name")))
        if _clean(doc.get("reason")):
            meta.append("驳回理由：%s" % _clean(doc.get("reason")))
        if meta:
            lines.append(" · ".join(meta))
        missing = []
        if sid:
            missing = service.missing_categories(
                self._docs(), sid, self._exemptions(), self._receipts())
            self.ctx["person"] = {"sid": sid, "who": who}
            self.ctx["cats"] = missing
            lines.append("同人其余：%s" % (("还缺 %s" % "、".join(missing))
                                        if missing else "都齐了"))
        return "\n".join(lines)

    def chase_for(self, sid, who="", cats=None):
        cats = cats or []
        if not cats:
            _, cats = self.student_status(sid, who)
        if not cats:
            return "%s 的材料都齐了，不用催。" % (_clean(who) or sid)
        msg = service.chase_message(_clean(who) or sid, cats)
        return msg + "\n\n（可直接复制发给对方；我不会自动发送。）"

    def overview_text(self):
        stats = {}
        try:
            stats = self.repo.stats()
        except Exception:
            stats = {}
        try:
            check = self.repo.roster_check()
        except Exception:
            check = {}
        try:
            svc = self.repo.service_stats(days=7)
        except Exception:
            svc = {}
        lines = ["台账共 %s 份：待审 %s、已归档 %s、已驳回 %s。" % (
            stats.get("total", 0), stats.get("pending", 0),
            stats.get("archived", 0), stats.get("rejected", 0))]
        if check:
            lines.append("名单 %s 人，已交 %s 人，未交 %s 人，需补交 %s 人。" % (
                check.get("total", 0), check.get("done", 0),
                len(check.get("absent") or []), len(check.get("resubmit") or [])))
        if svc:
            lines.append("近 7 天：催交 %s 次、回执 %s 条。" % (
                svc.get("chases", 0), svc.get("receipts", 0)))
        if stats.get("pending"):
            lines.append("下一步：先审待审 %s 份。" % stats.get("pending"))
        return "\n".join(lines)

    def pending_text(self, limit=6):
        rows = []
        try:
            rows = self.repo.list_docs(status="待审核", limit=limit)
        except Exception:
            rows = []
        if not rows:
            return "当前没有待审材料。"
        lines = ["待审 %d 份（按最新在前）：" % len(rows)]
        for d in rows:
            lines.append("· %s %s %s" % (_clean(d.get("sid")), _clean(d.get("who")),
                                         _clean(d.get("cat"))))
        lines.append("去「材料台账」逐份审，或说「打开台账」。")
        return "\n".join(lines)

    def missing_people_text(self, limit=8):
        try:
            check = self.repo.roster_check()
        except Exception:
            return "名单还没读出来。"
        absent = check.get("absent") or []
        resubmit = check.get("resubmit") or []
        if not absent and not resubmit:
            return "名单 %s 人，全部有材料记录。" % check.get("total", 0)
        lines = ["未交 %d 人 / 需补交 %d 人（共 %s 人）。" % (
            len(absent), len(resubmit), check.get("total", 0))]
        for r in absent[:limit]:
            lines.append("· 未交 %s %s" % (_clean(r.get("sid")), _clean(r.get("who"))))
        for r in resubmit[:limit]:
            lines.append("· 补交 %s %s" % (_clean(r.get("sid")), _clean(r.get("who"))))
        left = len(absent) + len(resubmit) - min(len(absent), limit) - min(len(resubmit), limit)
        if left > 0:
            lines.append("还有 %d 人，去「名单核对」看全表。" % left)
        lines.append("要话术就说「给某某写催交话术」。")
        return "\n".join(lines)

    def projects_text(self, limit=8):
        """项目层只报事实：到哪一步、完成率、缺几个必交物。"""
        try:
            rows = self.repo.list_projects()
        except Exception:
            return "项目层还没读出来。"
        if not rows:
            return ("还没有项目。去「项目工作台」新建一个，或套用班级材料模板；"
                    "建完再问我「班级材料项目还缺什么」。")
        lines = ["当前 %d 个项目（按进行中优先）：" % len(rows)]
        for p in rows[:limit]:
            lines.append("· %s｜%s｜%s｜%s%%（%s/%s）%s" % (
                _clean(p.get("name")), _clean(p.get("kind")), _clean(p.get("stage")),
                p.get("progress", 0), p.get("done", 0), p.get("total", 0),
                ("｜缺 %s 个必交物" % p.get("missing")) if p.get("missing") else ""))
        if len(rows) > limit:
            lines.append("另有 %d 个项目，去「项目工作台」看全部。" % (len(rows) - limit))
        lines.append("要看单个项目，就说「某某项目还缺什么」。")
        return "\n".join(lines)

    def project_detail_text(self, text=""):
        try:
            rows = self.repo.list_projects()
        except Exception:
            return "项目层还没读出来。"
        if not rows:
            return "还没有项目。先去「项目工作台」新建一个。"
        hit = None
        for p in rows:
            name = _clean(p.get("name"))
            if name and (name in text or (len(name) >= 4 and text in name)):
                hit = p
                break
        if not hit:
            hit = rows[0]
        try:
            items = self.repo.list_deliverables(hit.get("id"))
        except Exception:
            items = []
        lines = ["项目：%s（%s · %s · %s）" % (
            _clean(hit.get("name")), _clean(hit.get("kind")),
            _clean(hit.get("stage")), _clean(hit.get("status")))]
        lines.append("完成 %s/%s，进度 %s%%；必交缺 %s 个。" % (
            hit.get("done", 0), hit.get("total", 0),
            hit.get("progress", 0), hit.get("missing", 0)))
        if items:
            lines.append("交付物：")
            for d in items[:10]:
                mark = "✓" if _clean(d.get("status")) == "已通过" else "·"
                lines.append("%s %s｜%s｜%s%s" % (
                    mark, _clean(d.get("name")), _clean(d.get("stage")),
                    _clean(d.get("status")),
                    "（必交）" if d.get("required") else "（选做）"))
            if len(items) > 10:
                lines.append("另有 %d 项，去「项目工作台」看全部。" % (len(items) - 10))
        else:
            lines.append("还没有交付物；可以套用模板或手动添加。")
        lines.append("我只报进度，不改项目状态；要通过/驳回请去「项目工作台」。")
        return "\n".join(lines)

    def _project_in(self, text):
        try:
            rows = self.repo.list_projects()
        except Exception:
            return None
        best = None
        for p in rows:
            name = _clean(p.get("name"))
            if len(name) >= 2 and name in text:
                if best is None or len(name) > len(_clean(best.get("name"))):
                    best = p
        return best

    # ---------- 本地路由 ----------
    def _local(self, text):
        if any(w in text for w in HELP_WORDS):
            return self._ok("help", self.help_text())

        if any(w in text for w in SPEAK_WORDS):
            if not self.last_text:
                return self._ok("speak", "还没有可朗读的内容，先问我一句台账的事。")
            if self.speak:
                ok, info = self.speak(self.last_text)
                return self._ok("speak", "正在朗读上一句。" if ok else info)
            return self._ok("speak", "朗读不可用：没有接入语音层。")

        refused = self._refuse(text)
        if refused:
            return refused

        view = self._view_in(text)
        if view and any(w in text for w in OPEN_WORDS):
            return self._open(view[0], view[1])

        if any(w in text for w in DOC_WORDS) and not self._find_person(text):
            return self._doc_info(text)

        if self._project_in(text):
            return self._ok("project_detail", self.project_detail_text(text))
        if "项目" in text or "交付物" in text:
            if any(w in text for w in ("缺", "进度", "交付物", "卡", "怎么样", "到哪")):
                return self._ok("project_detail", self.project_detail_text(text))
            return self._ok("projects", self.projects_text())

        person = self._resolve_person(text)
        if person:
            if any(w in text for w in CHASE_WORDS):
                return self._chase(person)
            if any(w in text for w in STATUS_WORDS) or not any(
                    w in text for w in PENDING_WORDS + OVERVIEW_WORDS):
                return self._status(person)

        if any(w in text for w in PRONOUN_WORDS) and any(
                w in text for w in STATUS_WORDS + CHASE_WORDS):
            return self._ok("status", "你指的是哪位？给个姓名或学号，比如「250223 还缺什么」。")

        if any(w in text for w in MISSING_WORDS):
            return self._ok("missing_people", self.missing_people_text())
        if any(w in text for w in PENDING_WORDS):
            return self._ok("pending", self.pending_text())
        if any(w in text for w in OVERVIEW_WORDS):
            return self._ok("overview", self.overview_text())
        return None

    def _refuse(self, text):
        """认得出写操作，但明确不做——比含糊回 unknown 更不含糊。"""
        if any(w in text for w in WRITE_WORDS) and any(c in text for c in WRITE_CUES):
            return {"ok": False, "action": "unknown", "source": "local",
                    "text": "归档、驳回、删除这类操作我不替你做——台账是唯一事实源，改错了没人兜底。\n"
                            "要归档请到「材料台账」选中后点「归档」；要我先把该审的列出来，"
                            "就说「有哪些待审的」。"}
        return None

    def _resolve_person(self, text):
        """先认字面姓名/学号，再认指代（他/她/这个人）——指代取会话里记住的那个人。"""
        person = self._find_person(text)
        if person:
            return person
        if any(w in text for w in PRONOUN_WORDS):
            return dict(self.ctx.get("person") or {})
        return {}

    def _current_doc(self):
        if not self.context:
            return {}
        try:
            return (self.context() or {}).get("doc") or {}
        except Exception:
            return {}

    def _view_in(self, text):
        for key, label, words in VIEWS:
            for w in words:
                if w in text:
                    return key, label
        return None

    # ---------- 执行 ----------
    def _exec(self, intent, args, raw, source):
        args = args if isinstance(args, dict) else {}
        if intent == "help":
            return self._ok("help", self.help_text(), source)
        if intent == "overview":
            return self._ok("overview", self.overview_text(), source)
        if intent == "pending":
            return self._ok("pending", self.pending_text(), source)
        if intent == "missing_people":
            return self._ok("missing_people", self.missing_people_text(), source)
        if intent == "projects":
            return self._ok("projects", self.projects_text(), source)
        if intent == "project_detail":
            name = _clean(args.get("project"))
            return self._ok("project_detail",
                            self.project_detail_text(name or raw), source)
        if intent == "open_view":
            name = _clean(args.get("view")) or (_clean(args.get("page")))
            target = self._view_by_name(name) if name else self._view_in(raw)
            if not target:
                return self._ok("open_view", "要打开哪个页面？台账、服务留痕、名单核对、文件室都行。", source)
            return self._open(target[0], target[1], source)
        if intent == "speak":
            return self._ok("speak", self._speak_last(), source)
        if intent in ("status", "chase"):
            person = self._person_from_args(args) or self._resolve_person(raw)
            if not person:
                return self._ok(intent, "要先给学号或姓名，我才能查这个人。", source)
            return self._chase(person, source) if intent == "chase" else self._status(person, source)
        if intent == "doc_info":
            return self._doc_info(raw, source)
        return {"ok": False, "action": "unknown", "source": source,
                "text": "这个意图还没接上：%s" % intent}

    def _person_from_args(self, args):
        sid = _clean(args.get("sid"))
        who = _clean(args.get("who"))
        if sid and re.match(r"^\d{5,8}$", sid):
            row = None
            try:
                row = self.repo.find_roster_by_sid(sid)
            except Exception:
                row = None
            return {"sid": sid, "who": who or (_clean(row.get("who")) if row else "")}
        if who:
            for r in self._roster():
                if _clean(r.get("who")) == who:
                    return {"sid": _clean(r.get("sid")), "who": who}
        return {}

    def _view_by_name(self, name):
        if not name:
            return None
        for key, label, words in VIEWS:
            if name == key or name == label or any(w in name or name in w for w in words):
                return key, label
        return None

    def _doc_info(self, text, source="local"):
        doc = self._current_doc()
        if not doc:
            return self._ok("doc_info",
                            "现在没有选中的材料。先在「材料台账」点一行，"
                            "或直接说「250223 还缺什么」。" + self.ai_note(), source)
        out = self.doc_text(doc)
        if any(w in text for w in ("归档", "驳回")):
            out += "\n能不能归档要看类别与材料齐全度，这个判断我不替你做。"
        return self._ok("doc_info", out, source)

    def _status(self, person, source="local"):
        text, missing = self.student_status(person["sid"], person.get("who"))
        self.ctx["person"] = {"sid": person["sid"], "who": person.get("who", "")}
        self.ctx["cats"] = missing
        return self._ok("status", text, source, cats=missing)

    def _chase(self, person, source="local"):
        text = self.chase_for(person["sid"], person.get("who"))
        self.ctx["person"] = {"sid": person["sid"], "who": person.get("who", "")}
        return self._ok("chase", text, source)

    def _speak_last(self):
        if not self.last_text:
            return "还没有可朗读的内容，先问我一句台账的事。"
        if not self.speak:
            return "朗读不可用：没有接入语音层。"
        ok, info = self.speak(self.last_text)
        return "正在朗读上一句。" if ok else info

    def _open(self, key, label, source="local"):
        if not self.open_view:
            return self._ok("open_view", "这里没有主窗口，没法切页面。", source)
        try:
            self.open_view(key)
        except Exception as e:
            return self._ok("open_view", "切页面失败：%s" % e, source)
        return self._ok("open_view", "已切到「%s」。" % label, source)

    def _ok(self, action, text, source="local", **extra):
        out = {"ok": True, "action": action, "text": text, "source": source}
        out.update(extra)
        return out

    # ---------- AI 意图 ----------
    def _ai_intent(self, text):
        cfg = {}
        try:
            cfg = self.cfg_loader() or {}
        except Exception:
            cfg = {}
        if not ai.api_ready(cfg):
            return None, {}, "API 未启用"
        system = AI_SYSTEM % "、".join(c[0] for c in CAPS)
        parsed, why = ai.chat_json(system, text, cfg)
        if not parsed:
            return None, {}, why
        intent = _clean(parsed.get("intent"))
        args = parsed.get("args")
        return intent, args if isinstance(args, dict) else {}, ""
