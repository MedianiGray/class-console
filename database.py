# -*- coding: utf-8 -*-
"""
数据访问层（本地 SQLite 实现）

预留联网 / 上云说明：
  - 所有界面只调用 Repository 的方法，不直接碰 SQL。
  - 后续需要对接远程服务时，新增 RemoteRepository 并实现同一组方法：
      list_docs / add_doc / archive_doc / reject_doc / list_logs /
      add_log / stats / backup / restore
    再在上层按 DATA_BACKEND 切换即可，界面与业务流程不用改。
  - 本地数据库文件放在用户应用数据目录，不写程序安装目录，避免只读/权限问题。
"""

import os
import json
import sqlite3
import datetime
import uuid
from pathlib import Path

from seed import SEED_DOCS, SEED_LOGS, SEED_ROSTER, SEED_TASKS

# 预留开关：local = 本地 SQLite；remote = 未来对接远程服务（待实现）
DATA_BACKEND = "local"


def app_data_dir() -> Path:
    """返回本机应用数据目录（跨平台）。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        p = Path(base) / "ClassConsole"
    else:
        p = Path.home() / ".class-console"
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_str() -> str:
    d = datetime.datetime.now()
    return "%02d-%02d %02d:%02d" % (d.month, d.day, d.hour, d.minute)


def now_full() -> str:
    """审计用完整时间，含年份，便于跨年排序与筛选。"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def date_today() -> str:
    d = datetime.date.today()
    return d.strftime("%Y-%m-%d")


def _deadline(offset: int) -> str:
    d = datetime.date.today() + datetime.timedelta(days=offset)
    return d.strftime("%Y-%m-%d")


def days_until(deadline: str):
    """返回截止日距今天的天数；空日期返回 None。"""
    deadline = _clean(deadline)
    if not deadline:
        return None
    try:
        dl = datetime.datetime.strptime(deadline, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (dl - datetime.date.today()).days


def normalize_deadline(value) -> str:
    """把常见日期写法统一为 YYYY-MM-DD；空值返回空串，非法值抛错。"""
    raw = _clean(value)
    if not raw:
        return ""
    parsed = None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            parsed = datetime.datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if parsed is None or not (1900 <= parsed.year <= 2100):
        raise RepositoryError("截止日期格式应为 YYYY-MM-DD，例如 2026-11-30")
    return parsed.strftime("%Y-%m-%d")


class RepositoryError(RuntimeError):
    """数据读写失败，供界面捕获并提示，避免直接崩溃。"""


def _clean(value) -> str:
    """统一转为去首尾空白的字符串，None / 非字符串兜底为空串。"""
    if value is None:
        return ""
    return str(value).strip()


def _full_time(value) -> str:
    """把旧的 MM-DD HH:MM 补成含年份时间；已是完整格式则原样返回。"""
    text = _clean(value)
    if not text:
        return date_today() + " 00:00"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text
    if len(text) >= 5 and text[2] == "-":
        return "%d-%s" % (datetime.date.today().year, text)
    return text


def _parse_full_time(value):
    """解析完整或旧式时间；失败返回 None，供 24 小时限频判断。"""
    text = _clean(value)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.datetime.strptime(_full_time(text), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _like_escape(text: str) -> str:
    """转义 LIKE 通配符，避免用户输入 % _ 被当作模糊匹配。"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# 类别 → 编号前缀（编号形如 团务-001）
CAT_PREFIX = {
    "团务材料": "团务", "奖助材料": "奖助", "学分材料": "学分",
    "宣传材料": "宣传", "班级事务": "事务",
}

# 服务层：免交 / 延期、催交与回执。
EXEMPT_KINDS = ("免交", "延期")
RECEIPT_RESPONSES = ("已提交", "校外交", "稍后补")
SERVICE_ACTS = ("催交", "回执", "免交", "延期", "恢复应交", "交接包")
CHASE_COOLDOWN_HOURS = 24


def code_prefix(cat: str) -> str:
    return CAT_PREFIX.get(_clean(cat), "材料")


# 表单模板：内置标准预案 + 自定义材料。
# fields: key 字段键, label 显示名, type 控件类型(text/textarea/date/select/sid/file),
#         required 是否必填, options 选项(select)。
FORM_TEMPLATES = {
    "meeting": {
        "label": "主题班会记录", "prefix": "班会",
        "fields": [
            {"key": "topic", "label": "班会主题", "type": "text", "required": True},
            {"key": "meeting_date", "label": "日期", "type": "date"},
            {"key": "place", "label": "地点", "type": "text"},
            {"key": "host", "label": "主持人", "type": "text"},
            {"key": "recorder", "label": "记录人", "type": "text"},
            {"key": "expected", "label": "应到人数", "type": "text"},
            {"key": "attended", "label": "实到人数", "type": "text"},
            {"key": "process", "label": "班会过程", "type": "textarea"},
            {"key": "summary", "label": "活动小结", "type": "textarea"},
        ],
    },
    "dorm": {
        "label": "宿舍走访记录", "prefix": "走访",
        "fields": [
            {"key": "visit_date", "label": "走访日期", "type": "date"},
            {"key": "building", "label": "楼栋", "type": "text"},
            {"key": "dorm_no", "label": "宿舍号", "type": "text"},
            {"key": "visitor", "label": "走访人", "type": "text"},
            {"key": "situation", "label": "走访情况", "type": "textarea"},
            {"key": "rectify", "label": "需整改事项", "type": "textarea"},
        ],
    },
    "pledg": {
        "label": "班级承诺书", "prefix": "承诺",
        "fields": [
            {"key": "pledge_items", "label": "承诺事项", "type": "textarea", "required": True},
            {"key": "class_name", "label": "班级", "type": "text"},
            {"key": "sign_date", "label": "签署日期", "type": "date"},
        ],
    },
    "talk": {
        "label": "违纪约谈记录", "prefix": "约谈",
        "fields": [
            {"key": "talk_who", "label": "学生姓名", "type": "text", "required": True},
            {"key": "talk_sid", "label": "学号", "type": "sid"},
            {"key": "violation", "label": "违纪事项", "type": "textarea"},
            {"key": "talk_time", "label": "约谈时间", "type": "text"},
            {"key": "talk_place", "label": "地点", "type": "text"},
            {"key": "counselor", "label": "约谈人", "type": "text"},
            {"key": "content", "label": "谈话内容", "type": "textarea"},
            {"key": "opinion", "label": "处理意见", "type": "textarea"},
            {"key": "statement", "label": "学生表态", "type": "textarea"},
            {"key": "focus", "label": "是否重点关注", "type": "select",
             "options": ["否", "是"]},
        ],
    },
    "custom": {"label": "自定义材料", "prefix": "事务", "fields": []},
}

FORM_PREFIX = {k: v["prefix"] for k, v in FORM_TEMPLATES.items()}
FORM_TYPES = ("general",) + tuple(FORM_TEMPLATES)
TEMPLATE_FIELD_TYPES = ("text", "textarea", "date", "select")


def form_template(form_type: str) -> dict:
    return FORM_TEMPLATES.get(_clean(form_type), FORM_TEMPLATES["custom"])


class LocalRepository:
    """本地 SQLite 仓库。远程方案实现同名方法后可无缝替换。"""

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        self._init_db()
        self._backfill_codes()
        self._backfill_events()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, cat TEXT, who TEXT, sid TEXT, note TEXT,
                file TEXT, path TEXT, code TEXT, time TEXT,
                status TEXT, scope TEXT, reason TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT, who TEXT, role TEXT, act TEXT, obj TEXT, src TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS roster (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sid TEXT, who TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, cat TEXT, scope TEXT, deadline TEXT,
                note TEXT, done INTEGER
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER, name TEXT, path TEXT, kind TEXT, time TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS template_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                form_type TEXT, key TEXT, label TEXT, type TEXT,
                required INTEGER, options TEXT,
                UNIQUE(form_type, key)
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS doc_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER, time TEXT, act TEXT,
                who TEXT, role TEXT, detail TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS exemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sid TEXT, who TEXT, cat TEXT, kind TEXT,
                reason TEXT, until TEXT, time TEXT, actor TEXT, role TEXT,
                UNIQUE(sid, cat)
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sid TEXT, who TEXT, cat TEXT, act TEXT, channel TEXT,
                msg TEXT, time TEXT, response TEXT, note TEXT, actor TEXT
            )""")
        # 旧库迁移：补齐 reason / code / path / form_type / extra 列（已存在则忽略）
        cols = [r[1] for r in c.execute("PRAGMA table_info(docs)").fetchall()]
        for miss in ("reason", "code", "path", "form_type", "extra", "arch"):
            if miss not in cols:
                c.execute("ALTER TABLE docs ADD COLUMN %s TEXT" % miss)
        conn.commit()
        if c.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"] == 0:
            for row in SEED_DOCS:
                c.execute("""INSERT INTO docs
                    (name,cat,who,sid,note,file,time,status,scope)
                    VALUES (?,?,?,?,?,?,?,?,?)""", row)
        if c.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0:
            for row in SEED_LOGS:
                c.execute("""INSERT INTO logs
                    (time,who,role,act,obj,src) VALUES (?,?,?,?,?,?)""", row)
        if c.execute("SELECT COUNT(*) AS n FROM roster").fetchone()["n"] == 0:
            for sid, who in SEED_ROSTER:
                c.execute("INSERT INTO roster (sid, who) VALUES (?,?)", (sid, who))
        if c.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 0:
            for title, cat, scope, note, done, offset in SEED_TASKS:
                c.execute("""INSERT INTO tasks
                    (title,cat,scope,deadline,note,done) VALUES (?,?,?,?,?,?)""",
                    (title, cat, scope, _deadline(offset), note, done))
        conn.commit()
        conn.close()

    # ---------- 模板附加字段 ----------
    def template_custom(self, form_type: str) -> list:
        """返回某模板的用户附加字段；内置字段仍在 FORM_TEMPLATES。"""
        form_type = _clean(form_type) or "custom"
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM template_fields WHERE form_type=? ORDER BY id",
                (form_type,)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["required"] = bool(d.get("required"))
                try:
                    d["options"] = json.loads(d.get("options") or "[]")
                except (ValueError, TypeError):
                    d["options"] = []
                out.append(d)
            return out
        except sqlite3.Error as e:
            raise RepositoryError("读取模板字段失败：%s" % e)
        finally:
            conn.close()

    def add_template_field(self, form_type: str, label: str, ftype="text",
                           required=False, options=None):
        form_type = _clean(form_type)
        label = _clean(label)
        ftype = _clean(ftype) or "text"
        if form_type not in FORM_TYPES:
            raise RepositoryError("未知模板类型")
        if not label:
            raise RepositoryError("字段名称不能为空")
        if ftype not in TEMPLATE_FIELD_TYPES:
            raise RepositoryError("未知字段类型")
        opts = options if isinstance(options, list) else []
        opts = [_clean(x) for x in opts if _clean(x)]
        if ftype == "select" and not opts:
            raise RepositoryError("下拉字段至少需要一个选项")
        key = "cf_" + uuid.uuid4().hex[:8]
        conn = self._conn()
        try:
            cur = conn.execute(
                """INSERT INTO template_fields
                   (form_type,key,label,type,required,options) VALUES (?,?,?,?,?,?)""",
                (form_type, key, label, ftype, 1 if required else 0,
                 json.dumps(opts, ensure_ascii=False)))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("写入模板字段失败：%s" % e)
        finally:
            conn.close()

    def remove_template_field(self, field_id: int):
        conn = self._conn()
        try:
            conn.execute("DELETE FROM template_fields WHERE id=?", (field_id,))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除模板字段失败：%s" % e)
        finally:
            conn.close()

    def form_template(self, form_type: str) -> dict:
        """内置模板 + 用户附加字段；不改动全局 FORM_TEMPLATES。"""
        form_type = _clean(form_type) or "custom"
        base = FORM_TEMPLATES.get(form_type, FORM_TEMPLATES["custom"])
        return {
            "label": base["label"],
            "prefix": base["prefix"],
            "fields": list(base["fields"]) + self.template_custom(form_type),
        }

    # ---------- 材料 ----------
    def list_docs(self, q: str = "", cat: str = "全部") -> list:
        q = _clean(q)
        cat = _clean(cat) or "全部"
        conn = self._conn()
        try:
            sql = "SELECT * FROM docs WHERE 1=1"
            args = []
            if cat and cat != "全部":
                sql += " AND cat = ?"
                args.append(cat)
            if q:
                like = "%" + _like_escape(q) + "%"
                sql += " AND (name LIKE ? ESCAPE '\\' OR who LIKE ? ESCAPE '\\' OR sid LIKE ? ESCAPE '\\')"
                args += [like, like, like]
            sql += " ORDER BY id DESC"
            rows = conn.execute(sql, args).fetchall()
            att_map = self._attachment_map(conn)
            out = []
            for r in rows:
                d = dict(r)
                d["attachments"] = att_map.get(d["id"], [])
                d["extra"] = self._parse_extra(d.get("extra"))
                out.append(d)
            return out
        except sqlite3.Error as e:
            raise RepositoryError("读取材料失败：%s" % e)
        finally:
            conn.close()

    @staticmethod
    def _parse_extra(raw):
        if not raw:
            return {}
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def _attachment_map(conn):
        rows = conn.execute("SELECT * FROM attachments ORDER BY id").fetchall()
        amap = {}
        for r in rows:
            amap.setdefault(r["doc_id"], []).append(dict(r))
        return amap

    def list_attachments(self, doc_id: int) -> list:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE doc_id=? ORDER BY id",
                (doc_id,)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise RepositoryError("读取附件失败：%s" % e)
        finally:
            conn.close()

    def next_code(self, cat: str = "", form_type: str = "") -> str:
        """生成下一个编号：模板前缀优先，否则类别前缀 + 三位流水号。"""
        prefix = FORM_PREFIX.get(_clean(form_type)) or code_prefix(cat)
        maxn = 0
        for d in self.list_docs():
            code = d.get("code") or ""
            if code.startswith(prefix + "-"):
                tail = code.split("-", 1)[1]
                if tail.isdigit():
                    maxn = max(maxn, int(tail))
        return "%s-%03d" % (prefix, maxn + 1)

    def _backfill_codes(self):
        """旧库 / 种子记录缺编号时，按类别顺序补齐。"""
        conn = self._conn()
        try:
            rows = conn.execute("SELECT id, cat, code FROM docs").fetchall()
            used = {}
            for r in rows:
                prefix = code_prefix(r["cat"])
                code = _clean(r["code"])
                if code:
                    used.setdefault(prefix, set()).add(code)
                    continue
                maxn = 0
                for c in used.get(prefix, set()):
                    if c.startswith(prefix + "-") and c.split("-", 1)[1].isdigit():
                        maxn = max(maxn, int(c.split("-", 1)[1]))
                maxn += 1
                new_code = "%s-%03d" % (prefix, maxn)
                used.setdefault(prefix, set()).add(new_code)
                conn.execute("UPDATE docs SET code=? WHERE id=?", (new_code, r["id"]))
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
        finally:
            conn.close()

    def _backfill_events(self):
        """旧库 / 种子记录没有流转事件时，按提交时间与当前状态补一条最小链。"""
        conn = self._conn()
        try:
            docs = conn.execute(
                "SELECT id,time,status,reason,who,file FROM docs").fetchall()
            for d in docs:
                if conn.execute("SELECT COUNT(*) AS n FROM doc_events WHERE doc_id=?",
                                (d["id"],)).fetchone()["n"]:
                    continue
                t = _full_time(d["time"])
                detail = ("附件：" + d["file"]) if _clean(d["file"]) else ""
                conn.execute("""INSERT INTO doc_events
                    (doc_id,time,act,who,role,detail) VALUES (?,?,?,?,?,?)""",
                    (d["id"], t, "提交", _clean(d["who"]), "申请人", detail))
                if d["status"] in ("已归档", "已驳回", "待补材料"):
                    act = "归档" if d["status"] == "已归档" else "驳回"
                    conn.execute("""INSERT INTO doc_events
                        (doc_id,time,act,who,role,detail) VALUES (?,?,?,?,?,?)""",
                        (d["id"], t, act, "系统", "历史回填",
                         _clean(d["reason"]) or "由旧记录状态补录"))
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
        finally:
            conn.close()

    def list_events(self, doc_id) -> list:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM doc_events WHERE doc_id=? ORDER BY id",
                (doc_id,)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise RepositoryError("读取流转记录失败：%s" % e)
        finally:
            conn.close()

    def list_all_events(self) -> list:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM doc_events ORDER BY id").fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise RepositoryError("读取流转记录失败：%s" % e)
        finally:
            conn.close()

    def add_event(self, doc_id, act, who="", role="", detail="", time=None):
        conn = self._conn()
        try:
            conn.execute("""INSERT INTO doc_events
                (doc_id,time,act,who,role,detail) VALUES (?,?,?,?,?,?)""",
                (doc_id, _clean(time) or now_full(), _clean(act),
                 _clean(who) or "系统", _clean(role) or "本机", _clean(detail)))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("写入流转记录失败：%s" % e)
        finally:
            conn.close()

    def doc_timeline(self, doc) -> list:
        """返回一条材料从提交到归档/驳回的完整事件链，旧的按时间。"""
        if not isinstance(doc, dict):
            return []
        events = self.list_events(doc.get("id"))
        if not events:
            t = _full_time(doc.get("time"))
            events.append({"doc_id": doc.get("id"), "time": t, "act": "提交",
                           "who": doc.get("who") or "", "role": "申请人",
                           "detail": ""})
        return sorted(events, key=lambda x: (str(x.get("time") or ""),
                                             x.get("id") or 0))

    def add_doc(self, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("提交数据格式不正确")
        name = _clean(data.get("name"))
        cat = _clean(data.get("cat"))
        who = _clean(data.get("who"))
        sid = _clean(data.get("sid"))
        note = _clean(data.get("note"))
        file_name = _clean(data.get("file"))
        path = _clean(data.get("path"))
        code = _clean(data.get("code"))
        form_type = _clean(data.get("form_type")) or "general"
        extra_raw = data.get("extra")
        if isinstance(extra_raw, dict):
            extra = json.dumps(extra_raw, ensure_ascii=False)
        else:
            extra = _clean(extra_raw)
        if not code:
            code = self.next_code(cat, form_type)
        scope = _clean(data.get("scope")) or "全员"
        reason = _clean(data.get("reason"))
        if not name or not cat or not who:
            raise RepositoryError("材料名称、类别、姓名不能为空")
        row = (name, cat, who, sid, note, file_name, path, code,
               now_str(), "待审核", scope, reason, form_type, extra)
        conn = self._conn()
        try:
            cur = conn.execute("""INSERT INTO docs
                (name,cat,who,sid,note,file,path,code,time,status,scope,reason,
                 form_type,extra)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
            doc_id = cur.lastrowid
            for att in (data.get("attachments") or []):
                if not isinstance(att, dict):
                    continue
                conn.execute("""INSERT INTO attachments
                    (doc_id,name,path,kind,time) VALUES (?,?,?,?,?)""",
                    (doc_id, _clean(att.get("name")), _clean(att.get("path")),
                     _clean(att.get("kind")), now_str()))
            actor = _clean(data.get("actor")) or who
            actor_role = _clean(data.get("actor_role")) or "申请人"
            detail = note or (("附件：" + file_name) if file_name else "")
            conn.execute("""INSERT INTO doc_events
                (doc_id,time,act,who,role,detail) VALUES (?,?,?,?,?,?)""",
                (doc_id, now_full(), "提交", actor, actor_role, detail))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("写入材料失败：%s" % e)
        finally:
            conn.close()
        return doc_id

    def _get_doc(self, conn, doc_id):
        return conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()

    def archive_doc(self, doc_id, reason=None, actor="", role=""):
        conn = self._conn()
        try:
            row = self._get_doc(conn, doc_id)
            if not row:
                return None
            conn.execute("UPDATE docs SET status='已归档', reason=? WHERE id=?",
                         (_clean(reason), doc_id))
            conn.execute("""INSERT INTO doc_events
                (doc_id,time,act,who,role,detail) VALUES (?,?,?,?,?,?)""",
                (doc_id, now_full(), "归档", _clean(actor) or "系统",
                 _clean(role) or "本机", _clean(reason) or "审核通过，已归档"))
            conn.commit()
            return dict(row)
        except sqlite3.Error as e:
            raise RepositoryError("归档失败：%s" % e)
        finally:
            conn.close()

    def set_arch(self, doc_id, path, actor="", role=""):
        """记录材料归档后的实际文件路径，并写入归位节点。"""
        conn = self._conn()
        try:
            conn.execute("UPDATE docs SET arch=? WHERE id=?", (_clean(path), doc_id))
            if _clean(path):
                conn.execute("""INSERT INTO doc_events
                    (doc_id,time,act,who,role,detail) VALUES (?,?,?,?,?,?)""",
                    (doc_id, now_full(), "归位", _clean(actor) or "系统",
                     _clean(role) or "本机", _clean(path)))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("写入归档路径失败：%s" % e)
        finally:
            conn.close()

    def reject_doc(self, doc_id, reason=None, actor="", role=""):
        conn = self._conn()
        try:
            row = self._get_doc(conn, doc_id)
            if not row:
                return None
            conn.execute("UPDATE docs SET status='已驳回', reason=? WHERE id=?",
                         (_clean(reason), doc_id))
            conn.execute("""INSERT INTO doc_events
                (doc_id,time,act,who,role,detail) VALUES (?,?,?,?,?,?)""",
                (doc_id, now_full(), "驳回", _clean(actor) or "系统",
                 _clean(role) or "本机", _clean(reason) or "材料需补交"))
            conn.commit()
            return dict(row)
        except sqlite3.Error as e:
            raise RepositoryError("驳回失败：%s" % e)
        finally:
            conn.close()

    # ---------- 日志 ----------
    def list_logs(self, q: str = "", act: str = "全部", who: str = "") -> list:
        q, act, who = _clean(q), _clean(act) or "全部", _clean(who)
        conn = self._conn()
        try:
            sql = "SELECT * FROM logs WHERE 1=1"
            args = []
            if act and act != "全部":
                sql += " AND act = ?"
                args.append(act)
            if q:
                like = "%" + _like_escape(q) + "%"
                sql += (" AND (time LIKE ? ESCAPE '\\' OR who LIKE ? ESCAPE '\\'"
                        " OR role LIKE ? ESCAPE '\\' OR act LIKE ? ESCAPE '\\'"
                        " OR obj LIKE ? ESCAPE '\\' OR src LIKE ? ESCAPE '\\')")
                args += [like] * 6
            if who:
                like = "%" + _like_escape(who) + "%"
                sql += " AND who LIKE ? ESCAPE '\\'"
                args.append(like)
            sql += " ORDER BY id DESC"
            rows = conn.execute(sql, args).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise RepositoryError("读取日志失败：%s" % e)
        finally:
            conn.close()

    def add_log(self, act: str, obj: str, who: str, role: str, src: str = "本机"):
        conn = self._conn()
        try:
            conn.execute("INSERT INTO logs (time,who,role,act,obj,src) VALUES (?,?,?,?,?,?)",
                         (now_str(), _clean(who), _clean(role), _clean(act),
                          _clean(obj), _clean(src) or "本机"))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("写入日志失败：%s" % e)
        finally:
            conn.close()

    # ---------- 名单 ----------
    def list_roster(self) -> list:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM roster ORDER BY sid").fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise RepositoryError("读取名单失败：%s" % e)
        finally:
            conn.close()

    def find_roster_by_sid(self, sid: str):
        sid = _clean(sid)
        return next((r for r in self.list_roster() if r["sid"] == sid), None)

    def add_roster(self, sid: str, who: str):
        sid, who = _clean(sid), _clean(who)
        if not sid:
            raise RepositoryError("学号不能为空")
        if not who:
            raise RepositoryError("姓名不能为空")
        if not sid.isdigit():
            raise RepositoryError("学号须为纯数字")
        if self.find_roster_by_sid(sid):
            raise RepositoryError("该学号已在名单中")
        conn = self._conn()
        try:
            conn.execute("INSERT INTO roster (sid, who) VALUES (?,?)", (sid, who))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("写入名单失败：%s" % e)
        finally:
            conn.close()

    def remove_roster(self, rid: int):
        conn = self._conn()
        try:
            conn.execute("DELETE FROM roster WHERE id=?", (rid,))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("移除名单失败：%s" % e)
        finally:
            conn.close()

    def roster_check(self) -> dict:
        roster = self.list_roster()
        docs = self.list_docs()
        roster_sids = {r["sid"] for r in roster}
        # 已交 = 有材料在待审核或已归档；只有已驳回不算已交，进入需补交
        submitted = {_clean(d.get("sid")) for d in docs
                     if _clean(d.get("sid")) and d.get("status") in ("待审核", "已归档")}
        rejected = {_clean(d.get("sid")) for d in docs
                    if _clean(d.get("sid")) and d.get("status") == "已驳回"}
        absent = [r for r in roster if r["sid"] not in submitted]
        resubmit = [r for r in roster if r["sid"] in rejected and r["sid"] not in submitted]
        extra = [d for d in docs if _clean(d.get("sid")) and d["sid"] not in roster_sids]
        return {"total": len(roster), "done": len(roster) - len(absent),
                "absent": absent, "resubmit": resubmit, "extra": extra}

    # ---------- 服务层：免交 / 延期 ----------
    def _student_name(self, sid, who=""):
        who = _clean(who)
        if who:
            return who
        row = self.find_roster_by_sid(_clean(sid))
        return _clean(row.get("who")) if row else ""

    def list_exemptions(self, active_only=False) -> list:
        """返回免交 / 延期登记；延期到期后不再算有效。"""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM exemptions ORDER BY time DESC, id DESC").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError("读取免交 / 延期失败：%s" % e)
        finally:
            conn.close()
        today = date_today()
        out = []
        for r in rows:
            d = dict(r)
            d["active"] = (d.get("kind") == "免交" or
                           (d.get("kind") == "延期" and
                            _clean(d.get("until")) >= today and
                            bool(_clean(d.get("until")))))
            d["state"] = d.get("kind") if d["active"] else "已到期"
            if active_only and not d["active"]:
                continue
            out.append(d)
        return out

    def exemption_map(self, active_only=True) -> dict:
        """按 (学号, 类别) 取当前有效登记，供矩阵直接判格。"""
        return {(r.get("sid"), r.get("cat")): r
                for r in self.list_exemptions(active_only=active_only)}

    def set_exemption(self, sid, who, cat, kind, reason="", until="",
                      actor="", role="", time=None):
        """登记免交或延期；同一学生同一类别只保留最新一条。"""
        sid, cat, kind = _clean(sid), _clean(cat), _clean(kind)
        reason = _clean(reason)
        if not sid:
            raise RepositoryError("学号不能为空")
        if cat not in CAT_PREFIX:
            raise RepositoryError("未知材料类别")
        if kind not in EXEMPT_KINDS:
            raise RepositoryError("登记类型只能是免交或延期")
        if not reason:
            raise RepositoryError("请填写免交 / 延期原因")
        until = normalize_deadline(until) if kind == "延期" else ""
        if kind == "延期":
            if not until:
                raise RepositoryError("延期需要填写截止日期")
            if until < date_today():
                raise RepositoryError("延期日期不能早于今天")
        who = self._student_name(sid, who)
        t = _full_time(time or now_full())
        conn = self._conn()
        try:
            conn.execute("DELETE FROM exemptions WHERE sid=? AND cat=?", (sid, cat))
            conn.execute("""INSERT INTO exemptions
                (sid,who,cat,kind,reason,until,time,actor,role)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (sid, who, cat, kind, reason, until, t,
                 _clean(actor) or "系统", _clean(role) or "系统"))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise RepositoryError("登记免交 / 延期失败：%s" % e)
        finally:
            conn.close()
        obj = "%s %s %s" % (who or sid, sid, cat)
        try:
            self.add_log(kind, obj, _clean(actor) or "系统",
                         _clean(role) or "系统", src="本机")
        except Exception:
            pass
        return self.exemption_map().get((sid, cat)) or {}

    def remove_exemption(self, sid, cat, actor="", role=""):
        """取消免交 / 延期，恢复该类别应交。"""
        sid, cat = _clean(sid), _clean(cat)
        conn = self._conn()
        changed = 0
        try:
            cur = conn.execute("DELETE FROM exemptions WHERE sid=? AND cat=?",
                               (sid, cat))
            changed = cur.rowcount
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise RepositoryError("取消登记失败：%s" % e)
        finally:
            conn.close()
        if changed:
            try:
                self.add_log("恢复应交", "%s %s" % (sid, cat),
                             _clean(actor) or "系统", _clean(role) or "系统",
                             src="本机")
            except Exception:
                pass
        return bool(changed)

    # ---------- 服务层：催交与回执 ----------
    def chase_state(self, sid, now=None) -> dict:
        """同一学生 24 小时内只提醒一次；催交或回执都算一次联系。"""
        sid = _clean(sid)
        conn = self._conn()
        try:
            row = conn.execute("""SELECT * FROM followups
                WHERE sid=? AND act IN ('催交','回执')
                ORDER BY id DESC LIMIT 1""", (sid,)).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError("读取催交记录失败：%s" % e)
        finally:
            conn.close()
        if not row:
            return {"allowed": True, "last": "", "remain_min": 0,
                    "last_act": "", "response": ""}
        last = dict(row)
        seen = _parse_full_time(last.get("time"))
        now = now or datetime.datetime.now()
        if seen is None:
            return {"allowed": True, "last": _clean(last.get("time")),
                    "remain_min": 0, "last_act": _clean(last.get("act")),
                    "response": _clean(last.get("response"))}
        gap = now - seen
        limit = datetime.timedelta(hours=CHASE_COOLDOWN_HOURS)
        if gap < limit:
            remain = int((limit - gap).total_seconds() // 60) + 1
            return {"allowed": False, "last": _clean(last.get("time")),
                    "remain_min": remain, "last_act": _clean(last.get("act")),
                    "response": _clean(last.get("response"))}
        return {"allowed": True, "last": _clean(last.get("time")),
                "remain_min": 0, "last_act": _clean(last.get("act")),
                "response": _clean(last.get("response"))}

    def add_followup(self, sid, who, cats, msg, channel="微信 / 群公告",
                     actor="", role="", at=None):
        """登记一次催交；不足 24 小时直接拒绝，避免反复追赶。"""
        sid, msg = _clean(sid), _clean(msg)
        cats = _clean(cats)
        if not sid or not msg:
            raise RepositoryError("催交对象与话术不能为空")
        for cat in [x.strip() for x in cats.replace("、", ",").split(",") if x.strip()]:
            if cat not in CAT_PREFIX:
                raise RepositoryError("未知材料类别：%s" % cat)
        state = self.chase_state(sid, now=_parse_full_time(at) if at else None)
        if not state["allowed"]:
            raise RepositoryError(
                "距上次联系不足 24 小时，还需等待约 %d 分钟；同一学生每天只提醒一次。"
                % state["remain_min"])
        who = self._student_name(sid, who)
        t = _full_time(at or now_full())
        conn = self._conn()
        try:
            conn.execute("""INSERT INTO followups
                (sid,who,cat,act,channel,msg,time,response,note,actor)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sid, who, cats, "催交", _clean(channel) or "微信 / 群公告",
                 msg, t, "", "", _clean(actor) or "系统"))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise RepositoryError("登记催交失败：%s" % e)
        finally:
            conn.close()
        try:
            self.add_log("催交", "%s %s（%s）" % (who or sid, sid, cats),
                         _clean(actor) or "系统", _clean(role) or "系统",
                         src="本机")
        except Exception:
            pass
        return self.chase_state(sid)

    def add_receipt(self, sid, who, cat, response, note="",
                    actor="", role="", at=None):
        """登记同学回执；不直接改材料状态，只停止无意义追赶并留痕。"""
        sid, cat, response = _clean(sid), _clean(cat), _clean(response)
        if not sid:
            raise RepositoryError("学号不能为空")
        if cat not in CAT_PREFIX:
            raise RepositoryError("未知材料类别")
        if response not in RECEIPT_RESPONSES:
            raise RepositoryError("回执类型不正确")
        who = self._student_name(sid, who)
        t = _full_time(at or now_full())
        conn = self._conn()
        try:
            conn.execute("""INSERT INTO followups
                (sid,who,cat,act,channel,msg,time,response,note,actor)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sid, who, cat, "回执", "回执登记", "", t,
                 response, _clean(note), _clean(actor) or "系统"))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise RepositoryError("登记回执失败：%s" % e)
        finally:
            conn.close()
        try:
            self.add_log("回执", "%s %s（%s）%s" % (
                who or sid, sid, cat, response),
                _clean(actor) or "系统", _clean(role) or "系统", src="本机")
        except Exception:
            pass
        return True

    def latest_receipts(self) -> dict:
        """按 (学号, 类别) 取最近一条回执，矩阵用来区分「已交」与「待核实」。"""
        conn = self._conn()
        try:
            rows = conn.execute("""SELECT * FROM followups
                WHERE act='回执' ORDER BY id DESC""").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError("读取回执失败：%s" % e)
        finally:
            conn.close()
        out = {}
        for r in rows:
            key = (r["sid"], r["cat"])
            if key not in out:
                out[key] = dict(r)
        return out

    def list_followups(self) -> list:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM followups ORDER BY time DESC, id DESC").fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise RepositoryError("读取催交 / 回执失败：%s" % e)
        finally:
            conn.close()

    def service_feed(self, limit=200) -> list:
        """服务留痕统一流水：催交、回执、免交、延期、交接包。"""
        items = []
        for i, r in enumerate(self.list_followups()):
            if r.get("act") == "回执":
                detail = "%s%s" % (r.get("response") or "回执",
                                   (" · " + r["note"]) if r.get("note") else "")
            else:
                detail = r.get("msg") or ""
            items.append({
                "time": r.get("time", ""), "kind": r.get("act", ""),
                "who": r.get("who", ""), "sid": r.get("sid", ""),
                "cat": r.get("cat", ""), "detail": detail,
                "channel": r.get("channel", ""), "actor": r.get("actor", ""),
                "_seq": 100000 + i,
            })
        for i, r in enumerate(self.list_exemptions()):
            detail = r.get("reason") or ""
            if r.get("kind") == "延期":
                detail = "%s（至 %s）%s" % (detail, r.get("until") or "",
                                           "" if r.get("active") else "（已到期）")
            items.append({
                "time": r.get("time", ""), "kind": r.get("state", r.get("kind", "")),
                "who": r.get("who", ""), "sid": r.get("sid", ""),
                "cat": r.get("cat", ""), "detail": detail,
                "channel": "登记", "actor": r.get("actor", ""),
                "_seq": 200000 + i,
            })
        try:
            service_logs = [l for l in self.list_logs()
                            if l.get("act") in ("恢复应交", "交接包")]
        except Exception:
            service_logs = []
        for i, l in enumerate(service_logs):
            items.append({
                "time": l.get("time", ""), "kind": l.get("act", ""),
                "who": l.get("who", ""), "sid": "", "cat": "",
                "detail": l.get("obj", ""), "channel": (
                    "导出 / 导入" if l.get("act") == "交接包" else "登记"),
                "actor": l.get("who", ""), "_seq": 300000 + i,
            })
        items.sort(key=lambda x: (x.get("time", ""), x.get("_seq")), reverse=True)
        return items[:limit]

    def service_stats(self, days=7) -> dict:
        cutoff = (datetime.datetime.now() -
                  datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        fs = self.list_followups()
        chases = [f for f in fs if f.get("act") == "催交" and f.get("time", "") >= cutoff]
        receipts = [f for f in fs if f.get("act") == "回执" and f.get("time", "") >= cutoff]
        active = self.list_exemptions(active_only=True)
        return {"chases": len(chases), "receipts": len(receipts),
                "exempt": len([x for x in active if x.get("kind") == "免交"]),
                "deferred": len([x for x in active if x.get("kind") == "延期"]),
                "days": days}

    def nearest_deadline(self, cats) -> str:
        """取这些类别里最近的未完成任务截止日，用于催交话术。"""
        cats = set(cats if isinstance(cats, (list, tuple, set)) else [cats])
        dates = []
        for t in self.list_tasks():
            if t.get("done") or not _clean(t.get("deadline")):
                continue
            tcat = _clean(t.get("cat"))
            if tcat in cats or tcat in ("全部", "全员", ""):
                dates.append(t["deadline"])
        dates.sort()
        return dates[0] if dates else ""

    # ---------- 任务 ----------
    def list_tasks(self) -> list:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM tasks ORDER BY deadline, id").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["done"] = bool(d.get("done"))
                out.append(d)
            return out
        except sqlite3.Error as e:
            raise RepositoryError("读取任务失败：%s" % e)
        finally:
            conn.close()

    def find_task(self, tid: int):
        return next((x for x in self.list_tasks() if x["id"] == tid), None)

    def add_task(self, data: dict) -> int:
        title = _clean(data.get("title"))
        deadline = normalize_deadline(data.get("deadline"))
        if not title:
            raise RepositoryError("任务标题不能为空")
        if not deadline:
            raise RepositoryError("请选择截止日期")
        conn = self._conn()
        try:
            cur = conn.execute("""INSERT INTO tasks
                (title,cat,scope,deadline,note,done) VALUES (?,?,?,?,?,?)""",
                (title, _clean(data.get("cat")), _clean(data.get("scope")) or "全员",
                 deadline, _clean(data.get("note")), 1 if data.get("done") else 0))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("写入任务失败：%s" % e)
        finally:
            conn.close()

    def update_task(self, tid: int, data: dict):
        conn = self._conn()
        try:
            if conn.execute("SELECT 1 FROM tasks WHERE id=?", (tid,)).fetchone() is None:
                return None
            fields = {k: _clean(data.get(k)) for k in
                      ("title", "cat", "scope", "note") if data.get(k) is not None}
            if data.get("deadline") is not None:
                deadline = normalize_deadline(data.get("deadline"))
                if not deadline:
                    raise RepositoryError("请选择截止日期")
                fields["deadline"] = deadline
            if "done" in data:
                fields["done"] = 1 if data["done"] else 0
            if fields:
                sets = ", ".join("%s=?" % k for k in fields)
                conn.execute("UPDATE tasks SET %s WHERE id=?" % sets,
                             list(fields.values()) + [tid])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新任务失败：%s" % e)
        finally:
            conn.close()

    def remove_task(self, tid: int):
        conn = self._conn()
        try:
            conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("移除任务失败：%s" % e)
        finally:
            conn.close()

    def toggle_task(self, tid: int):
        conn = self._conn()
        try:
            conn.execute("UPDATE tasks SET done = 1 - done WHERE id=?", (tid,))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("切换任务状态失败：%s" % e)
        finally:
            conn.close()

    def task_stats(self) -> dict:
        tasks = self.list_tasks()
        ongoing = due = overdue = done = 0
        for t in tasks:
            if t["done"]:
                done += 1
                continue
            left = days_until(t["deadline"])
            if left is not None and left < 0:
                overdue += 1
            elif left is not None and left <= 2:
                due += 1
            ongoing += 1
        return {"total": len(tasks), "ongoing": ongoing, "due": due,
                "overdue": overdue, "done": done}

    # ---------- 统计 / 备份 ----------
    def stats(self) -> dict:
        conn = self._conn()
        try:
            total = conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"]
            pending = conn.execute("SELECT COUNT(*) AS n FROM docs WHERE status='待审核'").fetchone()["n"]
            archived = conn.execute("SELECT COUNT(*) AS n FROM docs WHERE status='已归档'").fetchone()["n"]
            rejected = conn.execute("SELECT COUNT(*) AS n FROM docs WHERE status='已驳回'").fetchone()["n"]
            return {"total": total, "pending": pending, "archived": archived, "rejected": rejected}
        except sqlite3.Error as e:
            raise RepositoryError("读取统计失败：%s" % e)
        finally:
            conn.close()

    def backup(self) -> dict:
        docs = self.list_docs()
        atts = []
        for d in docs:
            atts.extend(d.get("attachments") or [])
        templates = []
        for ft in FORM_TYPES:
            templates.extend(self.template_custom(ft))
        return {"docs": docs, "logs": self.list_logs(),
                "roster": self.list_roster(), "tasks": self.list_tasks(),
                "attachments": atts, "templates": templates,
                "events": self.list_all_events(),
                "exemptions": self.list_exemptions(),
                "followups": self.list_followups()}

    def restore(self, docs: list, logs: list, roster=None, tasks=None,
                attachments=None, templates=None, events=None,
                exemptions=None, followups=None):
        if not isinstance(docs, list) or not isinstance(logs, list):
            raise RepositoryError("备份数据结构不正确")
        roster = roster if isinstance(roster, list) else []
        tasks = tasks if isinstance(tasks, list) else []
        attachments = attachments if isinstance(attachments, list) else []
        events = events if isinstance(events, list) else []
        exemptions = exemptions if isinstance(exemptions, list) else []
        followups = followups if isinstance(followups, list) else []
        conn = self._conn()
        try:
            conn.execute("DELETE FROM docs")
            conn.execute("DELETE FROM logs")
            conn.execute("DELETE FROM roster")
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM attachments")
            conn.execute("DELETE FROM doc_events")
            conn.execute("DELETE FROM exemptions")
            conn.execute("DELETE FROM followups")
            if isinstance(templates, list):
                conn.execute("DELETE FROM template_fields")
                for tf in templates:
                    if not isinstance(tf, dict):
                        continue
                    ft = _clean(tf.get("form_type"))
                    if ft not in FORM_TYPES:
                        continue
                    key = _clean(tf.get("key")) or ("cf_" + uuid.uuid4().hex[:8])
                    label = _clean(tf.get("label"))
                    if not label:
                        continue
                    opts = tf.get("options") if isinstance(tf.get("options"), list) else []
                    conn.execute("""INSERT OR IGNORE INTO template_fields
                        (form_type,key,label,type,required,options) VALUES (?,?,?,?,?,?)""",
                        (ft, key, label, _clean(tf.get("type")) or "text",
                         1 if tf.get("required") else 0,
                         json.dumps(opts, ensure_ascii=False)))
            id_map = {}
            for d in docs:
                if not isinstance(d, dict):
                    continue
                cur = conn.execute("""INSERT INTO docs
                    (name,cat,who,sid,note,file,path,code,time,status,scope,reason,
                     form_type,extra,arch)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (_clean(d.get("name")), _clean(d.get("cat")), _clean(d.get("who")),
                     _clean(d.get("sid")), _clean(d.get("note")), _clean(d.get("file")),
                     _clean(d.get("path")), _clean(d.get("code")),
                     _clean(d.get("time")), _clean(d.get("status")) or "待审核",
                     _clean(d.get("scope")) or "全员", _clean(d.get("reason")),
                     _clean(d.get("form_type")) or "general", _clean(d.get("extra")),
                     _clean(d.get("arch"))))
                id_map[str(d.get("id"))] = cur.lastrowid
            for a in attachments:
                if not isinstance(a, dict):
                    continue
                new_id = id_map.get(str(a.get("doc_id")))
                if new_id is None:
                    continue
                conn.execute("""INSERT INTO attachments
                    (doc_id,name,path,kind,time) VALUES (?,?,?,?,?)""",
                    (new_id, _clean(a.get("name")), _clean(a.get("path")),
                     _clean(a.get("kind")), _clean(a.get("time")) or now_str()))
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                new_id = id_map.get(str(ev.get("doc_id")))
                if new_id is None:
                    continue
                conn.execute("""INSERT INTO doc_events
                    (doc_id,time,act,who,role,detail) VALUES (?,?,?,?,?,?)""",
                    (new_id, _clean(ev.get("time")) or now_full(),
                     _clean(ev.get("act")) or "提交", _clean(ev.get("who")),
                     _clean(ev.get("role")), _clean(ev.get("detail"))))
            for l in logs:
                if not isinstance(l, dict):
                    continue
                conn.execute("""INSERT INTO logs (time,who,role,act,obj,src)
                    VALUES (?,?,?,?,?,?)""",
                    (_clean(l.get("time")), _clean(l.get("who")), _clean(l.get("role")),
                     _clean(l.get("act")), _clean(l.get("obj")),
                     _clean(l.get("src")) or "本机"))
            for r in roster:
                if not isinstance(r, dict):
                    continue
                conn.execute("INSERT INTO roster (sid, who) VALUES (?,?)",
                             (_clean(r.get("sid")), _clean(r.get("who"))))
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                conn.execute("""INSERT INTO tasks
                    (title,cat,scope,deadline,note,done) VALUES (?,?,?,?,?,?)""",
                    (_clean(t.get("title")), _clean(t.get("cat")),
                     _clean(t.get("scope")) or "全员", _clean(t.get("deadline")),
                     _clean(t.get("note")), 1 if t.get("done") else 0))
            for x in exemptions:
                if not isinstance(x, dict):
                    continue
                sid, cat = _clean(x.get("sid")), _clean(x.get("cat"))
                kind = _clean(x.get("kind"))
                if not sid or cat not in CAT_PREFIX or kind not in EXEMPT_KINDS:
                    continue
                conn.execute("""INSERT OR REPLACE INTO exemptions
                    (sid,who,cat,kind,reason,until,time,actor,role)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (sid, _clean(x.get("who")), cat, kind,
                     _clean(x.get("reason")), _clean(x.get("until")),
                     _full_time(x.get("time")), _clean(x.get("actor")) or "系统",
                     _clean(x.get("role")) or "系统"))
            for f in followups:
                if not isinstance(f, dict):
                    continue
                sid, cat = _clean(f.get("sid")), _clean(f.get("cat"))
                act = _clean(f.get("act"))
                if not sid or not cat or act not in ("催交", "回执"):
                    continue
                conn.execute("""INSERT INTO followups
                    (sid,who,cat,act,channel,msg,time,response,note,actor)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (sid, self._student_name(sid, f.get("who")), cat, act,
                     _clean(f.get("channel")) or "本机", _clean(f.get("msg")),
                     _full_time(f.get("time")), _clean(f.get("response")),
                     _clean(f.get("note")), _clean(f.get("actor")) or "系统"))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise RepositoryError("导入备份失败：%s" % e)
        finally:
            conn.close()
        self._backfill_codes()
        self._backfill_events()


def build_repository():
    """工厂方法：预留远程切换。当前固定本地 SQLite。

    若库文件损坏导致初始化失败，先把损坏文件隔离改名，再重建空库，
    避免程序因旧库损坏而无法启动；隔离文件保留在本机便于排查。
    """
    db_path = app_data_dir() / "console.db"
    try:
        return LocalRepository(db_path)
    except Exception:
        try:
            if db_path.exists():
                stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                db_path.rename(db_path.with_name("console.corrupt-%s.db" % stamp))
        except Exception:
            pass
        return LocalRepository(db_path)
