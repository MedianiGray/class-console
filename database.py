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


class LocalRepository:
    """本地 SQLite 仓库。远程方案实现同名方法后可无缝替换。"""

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        self._init_db()

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
                file TEXT, time TEXT, status TEXT, scope TEXT, reason TEXT
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
        # 旧库迁移：补齐 docs.reason 列（已存在则忽略）
        cols = [r[1] for r in c.execute("PRAGMA table_info(docs)").fetchall()]
        if "reason" not in cols:
            c.execute("ALTER TABLE docs ADD COLUMN reason TEXT")
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
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise RepositoryError("读取材料失败：%s" % e)
        finally:
            conn.close()

    def add_doc(self, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("提交数据格式不正确")
        row = (
            _clean(data.get("name")), _clean(data.get("cat")),
            _clean(data.get("who")), _clean(data.get("sid")),
            _clean(data.get("note")), _clean(data.get("file")),
            now_str(), "待审核", _clean(data.get("scope")) or "全员",
            _clean(data.get("reason")),
        )
        if not row[0] or not row[1] or not row[2]:
            raise RepositoryError("材料名称、类别、姓名不能为空")
        conn = self._conn()
        try:
            conn.execute("""INSERT INTO docs
                (name,cat,who,sid,note,file,time,status,scope,reason)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", row)
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("写入材料失败：%s" % e)
        finally:
            conn.close()

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
        submitted = {_clean(d.get("sid")) for d in docs if _clean(d.get("sid"))}
        absent = [r for r in roster if r["sid"] not in submitted]
        extra = [d for d in docs if _clean(d.get("sid")) and d["sid"] not in roster_sids]
        return {"total": len(roster), "done": len(roster) - len(absent),
                "absent": absent, "extra": extra}

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
        title, deadline = _clean(data.get("title")), _clean(data.get("deadline"))
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
                      ("title", "cat", "scope", "deadline", "note") if data.get(k) is not None}
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
        return {"docs": self.list_docs(), "logs": self.list_logs(),
                "roster": self.list_roster(), "tasks": self.list_tasks()}

    def restore(self, docs: list, logs: list, roster=None, tasks=None):
        if not isinstance(docs, list) or not isinstance(logs, list):
            raise RepositoryError("备份数据结构不正确")
        roster = roster if isinstance(roster, list) else []
        tasks = tasks if isinstance(tasks, list) else []
        conn = self._conn()
        try:
            conn.execute("DELETE FROM docs")
            conn.execute("DELETE FROM logs")
            conn.execute("DELETE FROM roster")
            conn.execute("DELETE FROM tasks")
            for d in docs:
                if not isinstance(d, dict):
                    continue
                conn.execute("""INSERT INTO docs
                    (name,cat,who,sid,note,file,time,status,scope,reason)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (_clean(d.get("name")), _clean(d.get("cat")), _clean(d.get("who")),
                     _clean(d.get("sid")), _clean(d.get("note")), _clean(d.get("file")),
                     _clean(d.get("time")), _clean(d.get("status")) or "待审核",
                     _clean(d.get("scope")) or "全员", _clean(d.get("reason"))))
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
