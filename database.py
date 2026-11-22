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


def _like_escape(text: str) -> str:
    """转义 LIKE 通配符，避免用户输入 % _ 被当作模糊匹配。"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# 类别 → 编号前缀（编号形如 团务-001）
CAT_PREFIX = {
    "团务材料": "团务", "奖助材料": "奖助", "学分材料": "学分",
    "宣传材料": "宣传", "班级事务": "事务",
}


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


def form_template(form_type: str) -> dict:
    return FORM_TEMPLATES.get(_clean(form_type), FORM_TEMPLATES["custom"])


class LocalRepository:
    """本地 SQLite 仓库。远程方案实现同名方法后可无缝替换。"""

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        self._init_db()
        self._backfill_codes()

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
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("写入材料失败：%s" % e)
        finally:
            conn.close()
        return doc_id

    def _get_doc(self, conn, doc_id):
        return conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()

    def archive_doc(self, doc_id, reason=None):
        conn = self._conn()
        try:
            row = self._get_doc(conn, doc_id)
            if not row:
                return None
            conn.execute("UPDATE docs SET status='已归档', reason=? WHERE id=?",
                         (_clean(reason), doc_id))
            conn.commit()
            return dict(row)
        except sqlite3.Error as e:
            raise RepositoryError("归档失败：%s" % e)
        finally:
            conn.close()

    def set_arch(self, doc_id, path):
        """记录材料归档后的实际文件路径。"""
        conn = self._conn()
        try:
            conn.execute("UPDATE docs SET arch=? WHERE id=?", (_clean(path), doc_id))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("写入归档路径失败：%s" % e)
        finally:
            conn.close()

    def reject_doc(self, doc_id, reason=None):
        conn = self._conn()
        try:
            row = self._get_doc(conn, doc_id)
            if not row:
                return None
            conn.execute("UPDATE docs SET status='已驳回', reason=? WHERE id=?",
                         (_clean(reason), doc_id))
            conn.commit()
            return dict(row)
        except sqlite3.Error as e:
            raise RepositoryError("驳回失败：%s" % e)
        finally:
            conn.close()

    # ---------- 日志 ----------
    def list_logs(self) -> list:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM logs ORDER BY id DESC").fetchall()
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
        return {"docs": docs, "logs": self.list_logs(),
                "roster": self.list_roster(), "tasks": self.list_tasks(),
                "attachments": atts}

    def restore(self, docs: list, logs: list, roster=None, tasks=None, attachments=None):
        if not isinstance(docs, list) or not isinstance(logs, list):
            raise RepositoryError("备份数据结构不正确")
        roster = roster if isinstance(roster, list) else []
        tasks = tasks if isinstance(tasks, list) else []
        attachments = attachments if isinstance(attachments, list) else []
        conn = self._conn()
        try:
            conn.execute("DELETE FROM docs")
            conn.execute("DELETE FROM logs")
            conn.execute("DELETE FROM roster")
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM attachments")
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
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise RepositoryError("导入备份失败：%s" % e)
        finally:
            conn.close()
        self._backfill_codes()


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
