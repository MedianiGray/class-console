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
import sys
from pathlib import Path
from types import SimpleNamespace

from seed import SEED_DOCS, SEED_LOGS, SEED_ROSTER, SEED_TASKS
from version import VERSION

LAST_STARTUP_ISSUE = None

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
        # fromisoformat 不触发 strptime 的首次模块加载与正则编译，启动更稳。
        dl = datetime.date.fromisoformat(deadline.replace("/", "-").replace(".", "-"))
    except ValueError:
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


def _bom_numbers(data: dict) -> tuple:
    """BOM 数量与单价：数量必须大于 0，单价不能为负。"""
    try:
        qty = float(data.get("qty") if data.get("qty") not in ("", None) else 1)
    except (TypeError, ValueError):
        raise RepositoryError("数量应为数字")
    if qty <= 0:
        raise RepositoryError("数量应大于 0")
    try:
        unit_cost = float(data.get("unit_cost") if data.get("unit_cost") not in ("", None) else 0)
    except (TypeError, ValueError):
        raise RepositoryError("单价应为数字")
    if unit_cost < 0:
        raise RepositoryError("单价不能为负")
    return qty, unit_cost


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

# v0.31 项目底座：项目类型、阶段、状态与交付物状态。
PROJECT_KINDS = {
    "class": "班级材料",
    "media": "媒体内容",
    "competition": "赛事评审",
    "product": "产品研制",
    "data": "数据洞察",
    "event": "活动运营",
}
PROJECT_KIND_ORDER = tuple(PROJECT_KINDS)
PROJECT_STAGES = ("发现", "定义", "计划", "采集", "生产", "评审", "交付", "运营", "复盘")
PROJECT_STATUS = ("进行中", "已暂停", "已完成", "已归档")
DELIVERABLE_STATUS = ("待开始", "进行中", "待评审", "已通过", "已驳回")
COMPETITION_ROLES = ("队长", "队员", "指导教师", "其他")
# v0.35 产品模板：PRD / 架构、BOM、原型、测试、评审门。
PRODUCT_SPEC_KINDS = {"prd": "需求文档", "arch": "架构说明"}
PRODUCT_SPEC_DEFAULTS = {
    "prd": ("背景与问题", "目标用户", "产品目标", "功能范围",
            "非目标与边界", "验收标准", "风险与依赖"),
    "arch": ("总体架构", "模块与接口", "数据与存储", "部署与依赖"),
}
PRODUCT_BOM_KINDS = ("物料", "模块", "接口", "外包", "其他")
PRODUCT_PROTOTYPE_STATUS = ("待做", "进行中", "可用", "已冻结")
PRODUCT_TEST_RESULTS = ("未测", "通过", "不通过", "阻塞")
PRODUCT_TEST_SEVERITIES = ("高", "中", "低")
PRODUCT_REVIEW_GATES = ("立项评审", "方案评审", "样机评审", "发布评审")
PRODUCT_REVIEW_CONCLUSIONS = ("待评审", "通过", "有条件通过", "驳回")
PROJECT_TEMPLATES = {
    "class": (
        ("材料收集", "采集"), ("逐份审核", "评审"),
        ("归档落盘", "交付"), ("证据包 / 交接包", "交付"),
    ),
    "media": (
        ("输入清单", "采集"), ("预检参数", "计划"), ("批量转码", "生产"),
        ("输出质检", "评审"), ("交付包 + 哈希", "交付"),
    ),
    "competition": (
        ("报名与资格", "采集"), ("作品 / 方案", "生产"),
        ("评审标准对照", "评审"), ("提交校验", "交付"), ("答辩包", "交付"),
    ),
    "product": (
        ("需求 / PRD", "定义"), ("BOM / 架构", "计划"), ("原型 / 样品", "生产"),
        ("测试与问题", "评审"), ("发布包", "交付"), ("路演材料", "交付"),
    ),
    "data": (
        ("数据源清单", "采集"), ("清洗口径", "计划"),
        ("分析图表", "生产"), ("结论报告", "交付"),
    ),
    "event": (
        ("策划与审批", "定义"), ("通知与报名", "采集"),
        ("现场执行", "生产"), ("总结与结算", "复盘"),
    ),
}


def project_template(kind: str) -> list:
    """返回某类项目的交付物模板；未知类型回落到班级材料。"""
    items = PROJECT_TEMPLATES.get(_clean(kind), PROJECT_TEMPLATES["class"])
    return [{"name": name, "stage": stage, "status": "待开始",
             "required": True, "note": ""} for name, stage in items]


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
        try:
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
            # v0.31 项目底座：项目、交付物、资产、执行记录、质量门与项目事件。
            c.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT, kind TEXT, stage TEXT, status TEXT,
                    owner TEXT, start_date TEXT, due_date TEXT,
                    goal TEXT, note TEXT,
                    created_at TEXT, updated_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS project_deliverables (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, name TEXT, stage TEXT, status TEXT,
                    required INTEGER, note TEXT, sort_order INTEGER,
                    created_at TEXT, updated_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS project_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, name TEXT, path TEXT, kind TEXT,
                    size INTEGER, sha256 TEXT, note TEXT, created_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS project_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, deliverable_id INTEGER,
                    tool TEXT, params TEXT, status TEXT,
                    started_at TEXT, ended_at TEXT, output TEXT, log TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS project_gates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, deliverable_id INTEGER,
                    gate TEXT, status TEXT, note TEXT,
                    checked_at TEXT, checked_by TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS project_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, time TEXT, act TEXT,
                    who TEXT, detail TEXT
                )""")
            # v0.34 赛事模板：赛程、报名与评审矩阵；项目表仍是容器。
            c.execute("""
                CREATE TABLE IF NOT EXISTS competition_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, title TEXT, date TEXT, note TEXT,
                    done INTEGER, sort_order INTEGER,
                    created_at TEXT, updated_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS competition_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, name TEXT, sid TEXT, role TEXT,
                    contact TEXT, confirmed INTEGER, note TEXT,
                    sort_order INTEGER, created_at TEXT, updated_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS competition_rubric (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, criterion TEXT, weight INTEGER,
                    score INTEGER, evidence TEXT, note TEXT,
                    sort_order INTEGER, created_at TEXT, updated_at TEXT
                )""")
            # v0.35 产品模板：需求/架构、BOM、原型、测试与评审门。
            c.execute("""
                CREATE TABLE IF NOT EXISTS product_specs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, kind TEXT, section TEXT, content TEXT,
                    sort_order INTEGER, created_at TEXT, updated_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS product_bom (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, kind TEXT, name TEXT, spec TEXT,
                    qty REAL, unit TEXT, unit_cost REAL, source TEXT, note TEXT,
                    sort_order INTEGER, created_at TEXT, updated_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS product_protos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, name TEXT, version TEXT, path TEXT,
                    status TEXT, note TEXT, sort_order INTEGER,
                    created_at TEXT, updated_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS product_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, name TEXT, method TEXT, expected TEXT,
                    result TEXT, severity TEXT, issue TEXT, note TEXT,
                    sort_order INTEGER, created_at TEXT, updated_at TEXT
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS product_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER, gate TEXT, reviewer TEXT, date TEXT,
                    conclusion TEXT, note TEXT, sort_order INTEGER,
                    created_at TEXT, updated_at TEXT
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
        finally:
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
    @staticmethod
    def _docs_where(q="", cat="全部", status=None, form_type=None):
        """台账筛选条件：SQL 侧先筛，避免 5000 条全量搬进内存。"""
        q = _clean(q)
        cat = _clean(cat) or "全部"
        sql = " WHERE 1=1"
        args = []
        if cat and cat != "全部":
            sql += " AND cat = ?"
            args.append(cat)
        if status:
            sql += " AND status = ?"
            args.append(status)
        if form_type:
            sql += " AND COALESCE(NULLIF(form_type, ''), 'general') = ?"
            args.append(form_type)
        if q:
            like = "%" + _like_escape(q) + "%"
            sql += " AND (name LIKE ? ESCAPE '\\' OR who LIKE ? ESCAPE '\\' OR sid LIKE ? ESCAPE '\\')"
            args += [like, like, like]
        return sql, args

    def list_docs(self, q: str = "", cat: str = "全部", status=None,
                  form_type=None, limit=None, offset=0) -> list:
        where, args = self._docs_where(q, cat, status, form_type)
        conn = self._conn()
        try:
            sql = "SELECT * FROM docs" + where + " ORDER BY id DESC"
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                args += [int(limit), max(0, int(offset or 0))]
            rows = conn.execute(sql, args).fetchall()
            ids = {r["id"] for r in rows}
            att_map = self._attachment_map(conn, ids)
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

    def count_docs(self, q: str = "", cat: str = "全部", status=None,
                   form_type=None) -> int:
        where, args = self._docs_where(q, cat, status, form_type)
        conn = self._conn()
        try:
            return conn.execute("SELECT COUNT(*) AS n FROM docs" + where, args
                                ).fetchone()["n"]
        except sqlite3.Error as e:
            raise RepositoryError("读取材料数量失败：%s" % e)
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
    def _attachment_map(conn, doc_ids=None):
        if doc_ids is not None:
            ids = list(doc_ids)
            if not ids:
                return {}
            marks = ",".join("?" for _ in ids)
            rows = conn.execute(
                "SELECT * FROM attachments WHERE doc_id IN (%s) ORDER BY id" % marks,
                ids).fetchall()
        else:
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
            # 一次读出已有事件归属，避免 5000 条库启动时逐条 COUNT。
            existing = {r[0] for r in conn.execute(
                "SELECT DISTINCT doc_id FROM doc_events").fetchall()}
            for d in docs:
                if d["id"] in existing:
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
    def count_logs(self) -> int:
        conn = self._conn()
        try:
            return conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"]
        except sqlite3.Error as e:
            raise RepositoryError("读取日志数量失败：%s" % e)
        finally:
            conn.close()

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

    # ---------- 项目底座 v0.31 ----------
    def _project_event(self, conn, project_id, act, who="系统", detail=""):
        conn.execute("""INSERT INTO project_events
            (project_id,time,act,who,detail) VALUES (?,?,?,?,?)""",
            (project_id, now_full(), _clean(act), _clean(who), _clean(detail)))

    def _project_exists(self, project_id):
        conn = self._conn()
        try:
            return conn.execute("SELECT id FROM projects WHERE id=?",
                                (project_id,)).fetchone() is not None
        finally:
            conn.close()

    def list_projects(self, kind="全部", status="全部") -> list:
        sql = "SELECT * FROM projects"
        where, args = [], []
        kind = _clean(kind) or "全部"
        status = _clean(status) or "全部"
        if kind != "全部":
            where.append("kind=?")
            args.append(kind)
        if status != "全部":
            where.append("status=?")
            args.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += (" ORDER BY CASE status WHEN '进行中' THEN 0 WHEN '已暂停' THEN 1"
                " WHEN '已完成' THEN 2 ELSE 3 END, updated_at DESC, id DESC")
        conn = self._conn()
        try:
            rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        except sqlite3.Error as e:
            raise RepositoryError("读取项目失败：%s" % e)
        finally:
            conn.close()
        for p in rows:
            st = self.project_stats(p["id"])
            p.update({"total": st["total"], "done": st["done"],
                      "progress": st["progress"], "missing": st["missing"]})
        return rows

    def find_project(self, project_id) -> dict:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM projects WHERE id=?",
                               (project_id,)).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError("读取项目失败：%s" % e)
        finally:
            conn.close()
        if row is None:
            return None
        p = dict(row)
        p.update(self.project_stats(project_id))
        return p

    def add_project(self, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("项目数据格式不正确")
        name = _clean(data.get("name"))
        if not name:
            raise RepositoryError("项目名称不能为空")
        kind = _clean(data.get("kind")) or "class"
        if kind not in PROJECT_KINDS:
            raise RepositoryError("项目类型不在允许范围内")
        stage = _clean(data.get("stage")) or "定义"
        if stage not in PROJECT_STAGES:
            raise RepositoryError("项目阶段不在允许范围内")
        status = _clean(data.get("status")) or "进行中"
        if status not in PROJECT_STATUS:
            raise RepositoryError("项目状态不在允许范围内")
        start_date = normalize_deadline(data.get("start_date")) if data.get("start_date") else ""
        due_date = normalize_deadline(data.get("due_date")) if data.get("due_date") else ""
        now = now_full()
        conn = self._conn()
        try:
            cur = conn.execute("""INSERT INTO projects
                (name,kind,stage,status,owner,start_date,due_date,goal,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (name, kind, stage, status, _clean(data.get("owner")),
                 start_date, due_date, _clean(data.get("goal")),
                 _clean(data.get("note")), now, now))
            pid = cur.lastrowid
            self._project_event(conn, pid, "创建项目", _clean(data.get("owner")) or "系统")
            conn.commit()
            return pid
        except sqlite3.Error as e:
            raise RepositoryError("创建项目失败：%s" % e)
        finally:
            conn.close()

    def update_project(self, project_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("项目数据格式不正确")
        current = self.find_project(project_id)
        if current is None:
            raise RepositoryError("项目不存在")
        allowed = ("name", "kind", "stage", "status", "owner",
                   "start_date", "due_date", "goal", "note")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            value = data.get(key)
            if key == "name":
                value = _clean(value)
                if not value:
                    raise RepositoryError("项目名称不能为空")
            elif key == "kind":
                value = _clean(value)
                if value not in PROJECT_KINDS:
                    raise RepositoryError("项目类型不在允许范围内")
            elif key == "stage":
                value = _clean(value)
                if value not in PROJECT_STAGES:
                    raise RepositoryError("项目阶段不在允许范围内")
            elif key == "status":
                value = _clean(value)
                if value not in PROJECT_STATUS:
                    raise RepositoryError("项目状态不在允许范围内")
            elif key in ("start_date", "due_date"):
                value = normalize_deadline(value) if value else ""
            else:
                value = _clean(value)
            values[key] = value
        if not values:
            return
        values["updated_at"] = now_full()
        sets = ", ".join("%s=?" % k for k in values)
        conn = self._conn()
        try:
            conn.execute("UPDATE projects SET %s WHERE id=?" % sets,
                         list(values.values()) + [project_id])
            self._project_event(conn, project_id, "更新项目", "系统",
                                "、".join(k for k in values if k != "updated_at"))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新项目失败：%s" % e)
        finally:
            conn.close()

    def remove_project(self, project_id):
        current = self.find_project(project_id)
        if current is None:
            raise RepositoryError("项目不存在")
        conn = self._conn()
        try:
            for table in ("project_deliverables", "project_assets",
                          "project_runs", "project_gates", "project_events",
                          "competition_events", "competition_entries",
                          "competition_rubric", "product_specs", "product_bom",
                          "product_protos", "product_tests", "product_reviews"):
                conn.execute("DELETE FROM %s WHERE project_id=?" % table, (project_id,))
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除项目失败：%s" % e)
        finally:
            conn.close()
        try:
            self.add_log("删除项目", current.get("name", ""), "系统", "系统")
        except Exception:
            pass

    def list_deliverables(self, project_id) -> list:
        conn = self._conn()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM project_deliverables WHERE project_id=? "
                "ORDER BY sort_order, id", (project_id,)).fetchall()]
        except sqlite3.Error as e:
            raise RepositoryError("读取交付物失败：%s" % e)
        finally:
            conn.close()
        for d in rows:
            d["required"] = bool(d.get("required"))
        return rows

    def list_all_deliverables(self) -> list:
        conn = self._conn()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM project_deliverables ORDER BY project_id, sort_order, id").fetchall()]
        except sqlite3.Error as e:
            raise RepositoryError("读取交付物失败：%s" % e)
        finally:
            conn.close()
        for d in rows:
            d["required"] = bool(d.get("required"))
        return rows

    def add_deliverable(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("交付物数据格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        name = _clean(data.get("name"))
        if not name:
            raise RepositoryError("交付物名称不能为空")
        stage = _clean(data.get("stage")) or "生产"
        if stage not in PROJECT_STAGES:
            raise RepositoryError("交付物阶段不在允许范围内")
        status = _clean(data.get("status")) or "待开始"
        if status not in DELIVERABLE_STATUS:
            raise RepositoryError("交付物状态不在允许范围内")
        required = 1 if data.get("required", True) else 0
        now = now_full()
        conn = self._conn()
        try:
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM project_deliverables WHERE project_id=?",
                               (project_id,)).fetchone()
            sort_order = int(row["n"])
            cur = conn.execute("""INSERT INTO project_deliverables
                (project_id,name,stage,status,required,note,sort_order,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (project_id, name, stage, status, required,
                 _clean(data.get("note")), sort_order, now, now))
            did = cur.lastrowid
            self._project_event(conn, project_id, "添加交付物", "系统", name)
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?",
                         (now, project_id))
            conn.commit()
            return did
        except sqlite3.Error as e:
            raise RepositoryError("添加交付物失败：%s" % e)
        finally:
            conn.close()

    def update_deliverable(self, deliverable_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("交付物数据格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM project_deliverables WHERE id=?",
                               (deliverable_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("交付物不存在")
        allowed = ("name", "stage", "status", "required", "note", "sort_order")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "name":
                value = _clean(data.get(key))
                if not value:
                    raise RepositoryError("交付物名称不能为空")
            elif key == "stage":
                value = _clean(data.get(key))
                if value not in PROJECT_STAGES:
                    raise RepositoryError("交付物阶段不在允许范围内")
            elif key == "status":
                value = _clean(data.get(key))
                if value not in DELIVERABLE_STATUS:
                    raise RepositoryError("交付物状态不在允许范围内")
            elif key == "required":
                value = 1 if data.get(key) else 0
            elif key == "sort_order":
                try:
                    value = int(data.get(key))
                except (TypeError, ValueError):
                    raise RepositoryError("交付物排序应为整数")
            else:
                value = _clean(data.get(key))
            values[key] = value
        if not values:
            return
        values["updated_at"] = now_full()
        sets = ", ".join("%s=?" % k for k in values)
        conn = self._conn()
        try:
            conn.execute("UPDATE project_deliverables SET %s WHERE id=?" % sets,
                         list(values.values()) + [deliverable_id])
            self._project_event(conn, row["project_id"], "更新交付物", "系统",
                                row["name"] + " → " + values.get("status", ""))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?",
                         (now_full(), row["project_id"]))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新交付物失败：%s" % e)
        finally:
            conn.close()

    def remove_deliverable(self, deliverable_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM project_deliverables WHERE id=?",
                               (deliverable_id,)).fetchone()
            if row is None:
                raise RepositoryError("交付物不存在")
            conn.execute("DELETE FROM project_deliverables WHERE id=?",
                         (deliverable_id,))
            self._project_event(conn, row["project_id"], "删除交付物", "系统",
                                row["name"])
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?",
                         (now_full(), row["project_id"]))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除交付物失败：%s" % e)
        finally:
            conn.close()

    def project_stats(self, project_id) -> dict:
        conn = self._conn()
        try:
            row = conn.execute("""SELECT COUNT(*) AS total,
                SUM(CASE WHEN status='已通过' THEN 1 ELSE 0 END) AS done,
                SUM(CASE WHEN required=1 THEN 1 ELSE 0 END) AS required,
                SUM(CASE WHEN required=1 AND status='已通过' THEN 1 ELSE 0 END) AS required_done
                FROM project_deliverables WHERE project_id=?""",
                (project_id,)).fetchone()
            total = int(row["total"] or 0)
            done = int(row["done"] or 0)
            required = int(row["required"] or 0)
            required_done = int(row["required_done"] or 0)
            return {"total": total, "done": done, "required": required,
                    "required_done": required_done,
                    "progress": (round(done * 100.0 / total) if total else 0),
                    "missing": max(0, required - required_done)}
        except sqlite3.Error as e:
            raise RepositoryError("读取项目进度失败：%s" % e)
        finally:
            conn.close()

    def apply_project_template(self, project_id, kind=None) -> int:
        current = self.find_project(project_id)
        if current is None:
            raise RepositoryError("项目不存在")
        kind = _clean(kind) or current.get("kind") or "class"
        existing = {d["name"] for d in self.list_deliverables(project_id)}
        added = 0
        for item in project_template(kind):
            if item["name"] in existing:
                continue
            self.add_deliverable(project_id, item)
            added += 1
        return added

    def project_events(self, project_id, limit=50) -> list:
        conn = self._conn()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM project_events WHERE project_id=? "
                "ORDER BY id DESC LIMIT ?", (project_id, int(limit))).fetchall()]
        except sqlite3.Error as e:
            raise RepositoryError("读取项目记录失败：%s" % e)
        finally:
            conn.close()
        return rows

    def list_all_project_events(self) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM project_events ORDER BY id").fetchall()]
        finally:
            conn.close()

    def add_project_asset(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("资产数据格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        name = _clean(data.get("name"))
        if not name:
            raise RepositoryError("资产名称不能为空")
        conn = self._conn()
        try:
            cur = conn.execute("""INSERT INTO project_assets
                (project_id,name,path,kind,size,sha256,note,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (project_id, name, _clean(data.get("path")),
                 _clean(data.get("kind")), int(data.get("size") or 0),
                 _clean(data.get("sha256")), _clean(data.get("note")), now_full()))
            self._project_event(conn, project_id, "登记资产", "系统", name)
            conn.commit()
            return cur.lastrowid
        except (sqlite3.Error, TypeError, ValueError) as e:
            raise RepositoryError("登记资产失败：%s" % e)
        finally:
            conn.close()

    def list_project_assets(self, project_id) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM project_assets WHERE project_id=? ORDER BY id",
                (project_id,)).fetchall()]
        finally:
            conn.close()

    def add_project_run(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("执行记录格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        conn = self._conn()
        try:
            cur = conn.execute("""INSERT INTO project_runs
                (project_id,deliverable_id,tool,params,status,
                 started_at,ended_at,output,log) VALUES (?,?,?,?,?,?,?,?,?)""",
                (project_id, data.get("deliverable_id"),
                 _clean(data.get("tool")), _clean(data.get("params")),
                 _clean(data.get("status")) or "已结束",
                 _clean(data.get("started_at")) or now_full(),
                 _clean(data.get("ended_at")), _clean(data.get("output")),
                 _clean(data.get("log"))))
            self._project_event(conn, project_id, "执行", _clean(data.get("tool")) or "系统")
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("写入执行记录失败：%s" % e)
        finally:
            conn.close()

    def list_project_runs(self, project_id) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM project_runs WHERE project_id=? ORDER BY id DESC",
                (project_id,)).fetchall()]
        finally:
            conn.close()

    def set_project_gate(self, project_id, gate, status, deliverable_id=None,
                         note="", checked_by="") -> int:
        gate = _clean(gate)
        status = _clean(status)
        if not gate:
            raise RepositoryError("质量门名称不能为空")
        if status not in ("待检查", "通过", "不通过", "跳过"):
            raise RepositoryError("质量门状态不在允许范围内")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        conn = self._conn()
        try:
            row = conn.execute("""SELECT id FROM project_gates
                WHERE project_id=? AND gate=? AND
                (deliverable_id IS ? OR deliverable_id=?)""",
                (project_id, gate, deliverable_id, deliverable_id)).fetchone()
            if row:
                conn.execute("""UPDATE project_gates SET status=?,note=?,
                    checked_at=?,checked_by=? WHERE id=?""",
                    (status, _clean(note), now_full(),
                     _clean(checked_by) or "系统", row["id"]))
                gid = row["id"]
            else:
                cur = conn.execute("""INSERT INTO project_gates
                    (project_id,deliverable_id,gate,status,note,checked_at,checked_by)
                    VALUES (?,?,?,?,?,?,?)""",
                    (project_id, deliverable_id, gate, status, _clean(note),
                     now_full(), _clean(checked_by) or "系统"))
                gid = cur.lastrowid
            self._project_event(conn, project_id, "质量门", _clean(checked_by) or "系统",
                                gate + " · " + status)
            conn.commit()
            return gid
        except sqlite3.Error as e:
            raise RepositoryError("写入质量门失败：%s" % e)
        finally:
            conn.close()

    def list_project_gates(self, project_id) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM project_gates WHERE project_id=? ORDER BY id",
                (project_id,)).fetchall()]
        finally:
            conn.close()

    # ---------- v0.34 赛事：赛程 / 报名 / 评审矩阵 ----------
    def _competition_rows(self, table, project_id, order="sort_order, id") -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM %s WHERE project_id=? ORDER BY %s" % (table, order),
                (project_id,)).fetchall()]
        except sqlite3.Error as e:
            raise RepositoryError("读取赛事数据失败：%s" % e)
        finally:
            conn.close()

    def list_competition_events(self, project_id) -> list:
        return self._competition_rows("competition_events", project_id)

    def list_all_competition_events(self) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM competition_events ORDER BY project_id, sort_order, id").fetchall()]
        finally:
            conn.close()

    def add_competition_event(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("赛程数据格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        title = _clean(data.get("title"))
        if not title:
            raise RepositoryError("赛程事项不能为空")
        date_text = normalize_deadline(data.get("date")) if data.get("date") else ""
        now = now_full()
        conn = self._conn()
        try:
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM competition_events WHERE project_id=?",
                               (project_id,)).fetchone()
            cur = conn.execute("""INSERT INTO competition_events
                (project_id,title,date,note,done,sort_order,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (project_id, title, date_text, _clean(data.get("note")),
                 1 if data.get("done") else 0, int(row["n"]), now, now))
            self._project_event(conn, project_id, "添加赛程", "系统",
                                title + (" · " + date_text if date_text else ""))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("添加赛程失败：%s" % e)
        finally:
            conn.close()

    def update_competition_event(self, event_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("赛程数据格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM competition_events WHERE id=?",
                               (event_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("赛程事项不存在")
        allowed = ("title", "date", "note", "done", "sort_order")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "title":
                value = _clean(data.get(key))
                if not value:
                    raise RepositoryError("赛程事项不能为空")
            elif key == "date":
                value = normalize_deadline(data.get(key)) if data.get(key) else ""
            elif key == "done":
                value = 1 if data.get(key) else 0
            elif key == "sort_order":
                try:
                    value = int(data.get(key))
                except (TypeError, ValueError):
                    raise RepositoryError("赛程排序应为整数")
            else:
                value = _clean(data.get(key))
            values[key] = value
        if not values:
            return
        values["updated_at"] = now_full()
        conn = self._conn()
        try:
            conn.execute("UPDATE competition_events SET %s WHERE id=?" %
                         ", ".join("%s=?" % k for k in values),
                         list(values.values()) + [event_id])
            self._project_event(conn, row["project_id"], "更新赛程", "系统",
                                row["title"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新赛程失败：%s" % e)
        finally:
            conn.close()

    def remove_competition_event(self, event_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM competition_events WHERE id=?",
                               (event_id,)).fetchone()
            if row is None:
                raise RepositoryError("赛程事项不存在")
            conn.execute("DELETE FROM competition_events WHERE id=?", (event_id,))
            self._project_event(conn, row["project_id"], "删除赛程", "系统",
                                row["title"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除赛程失败：%s" % e)
        finally:
            conn.close()

    def list_competition_entries(self, project_id) -> list:
        rows = self._competition_rows("competition_entries", project_id)
        for r in rows:
            r["confirmed"] = bool(r.get("confirmed"))
        return rows

    def list_all_competition_entries(self) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM competition_entries ORDER BY project_id, sort_order, id").fetchall()]
        finally:
            conn.close()

    def add_competition_entry(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("报名数据格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        name = _clean(data.get("name"))
        if not name:
            raise RepositoryError("报名姓名不能为空")
        sid = _clean(data.get("sid"))
        role = _clean(data.get("role")) or "队员"
        if role not in COMPETITION_ROLES:
            raise RepositoryError("报名角色不在允许范围内")
        now = now_full()
        conn = self._conn()
        try:
            if sid:
                dup = conn.execute("SELECT id FROM competition_entries "
                                   "WHERE project_id=? AND sid=?", (project_id, sid)).fetchone()
                if dup is not None:
                    raise RepositoryError("该学号已在报名清单里")
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM competition_entries WHERE project_id=?",
                               (project_id,)).fetchone()
            cur = conn.execute("""INSERT INTO competition_entries
                (project_id,name,sid,role,contact,confirmed,note,sort_order,
                 created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (project_id, name, sid, role, _clean(data.get("contact")),
                 1 if data.get("confirmed") else 0, _clean(data.get("note")),
                 int(row["n"]), now, now))
            self._project_event(conn, project_id, "添加报名", "系统",
                                name + (" · " + role if role else ""))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("添加报名失败：%s" % e)
        finally:
            conn.close()

    def update_competition_entry(self, entry_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("报名数据格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM competition_entries WHERE id=?",
                               (entry_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("报名记录不存在")
        allowed = ("name", "sid", "role", "contact", "confirmed", "note")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "name":
                value = _clean(data.get(key))
                if not value:
                    raise RepositoryError("报名姓名不能为空")
            elif key == "role":
                value = _clean(data.get(key)) or "队员"
                if value not in COMPETITION_ROLES:
                    raise RepositoryError("报名角色不在允许范围内")
            elif key == "sid":
                value = _clean(data.get(key))
            elif key == "confirmed":
                value = 1 if data.get(key) else 0
            else:
                value = _clean(data.get(key))
            values[key] = value
        if "sid" in values and values["sid"]:
            conn = self._conn()
            try:
                dup = conn.execute("SELECT id FROM competition_entries WHERE project_id=? "
                                   "AND sid=? AND id<>?",
                                   (row["project_id"], values["sid"], entry_id)).fetchone()
            finally:
                conn.close()
            if dup is not None:
                raise RepositoryError("该学号已在报名清单里")
        if not values:
            return
        values["updated_at"] = now_full()
        conn = self._conn()
        try:
            conn.execute("UPDATE competition_entries SET %s WHERE id=?" %
                         ", ".join("%s=?" % k for k in values),
                         list(values.values()) + [entry_id])
            self._project_event(conn, row["project_id"], "更新报名", "系统", row["name"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新报名失败：%s" % e)
        finally:
            conn.close()

    def remove_competition_entry(self, entry_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM competition_entries WHERE id=?",
                               (entry_id,)).fetchone()
            if row is None:
                raise RepositoryError("报名记录不存在")
            conn.execute("DELETE FROM competition_entries WHERE id=?", (entry_id,))
            self._project_event(conn, row["project_id"], "删除报名", "系统", row["name"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除报名失败：%s" % e)
        finally:
            conn.close()

    def list_competition_rubric(self, project_id) -> list:
        return self._competition_rows("competition_rubric", project_id)

    def list_all_competition_rubric(self) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM competition_rubric ORDER BY project_id, sort_order, id").fetchall()]
        finally:
            conn.close()

    def add_competition_criterion(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("评审项数据格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        criterion = _clean(data.get("criterion"))
        if not criterion:
            raise RepositoryError("评审项名称不能为空")
        try:
            weight = int(data.get("weight") or 0)
        except (TypeError, ValueError):
            raise RepositoryError("权重应为整数")
        if weight < 0 or weight > 100:
            raise RepositoryError("权重应在 0–100 之间")
        score = data.get("score")
        if score in ("", None):
            score = None
        else:
            try:
                score = int(score)
            except (TypeError, ValueError):
                raise RepositoryError("自评分应为整数")
            if score < 0 or score > 100:
                raise RepositoryError("自评分应在 0–100 之间")
        now = now_full()
        conn = self._conn()
        try:
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM competition_rubric WHERE project_id=?",
                               (project_id,)).fetchone()
            cur = conn.execute("""INSERT INTO competition_rubric
                (project_id,criterion,weight,score,evidence,note,sort_order,
                 created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (project_id, criterion, weight, score, _clean(data.get("evidence")),
                 _clean(data.get("note")), int(row["n"]), now, now))
            self._project_event(conn, project_id, "添加评审项", "系统",
                                "%s · %d%%" % (criterion, weight))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("添加评审项失败：%s" % e)
        finally:
            conn.close()

    def update_competition_criterion(self, criterion_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("评审项数据格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM competition_rubric WHERE id=?",
                               (criterion_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("评审项不存在")
        allowed = ("criterion", "weight", "score", "evidence", "note")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "criterion":
                value = _clean(data.get(key))
                if not value:
                    raise RepositoryError("评审项名称不能为空")
            elif key == "weight":
                try:
                    value = int(data.get(key) or 0)
                except (TypeError, ValueError):
                    raise RepositoryError("权重应为整数")
                if value < 0 or value > 100:
                    raise RepositoryError("权重应在 0–100 之间")
            elif key == "score":
                value = data.get(key)
                if value in ("", None):
                    value = None
                else:
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        raise RepositoryError("自评分应为整数")
                    if value < 0 or value > 100:
                        raise RepositoryError("自评分应在 0–100 之间")
            else:
                value = _clean(data.get(key))
            values[key] = value
        if not values:
            return
        values["updated_at"] = now_full()
        conn = self._conn()
        try:
            conn.execute("UPDATE competition_rubric SET %s WHERE id=?" %
                         ", ".join("%s=?" % k for k in values),
                         list(values.values()) + [criterion_id])
            self._project_event(conn, row["project_id"], "更新评审项", "系统",
                                row["criterion"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新评审项失败：%s" % e)
        finally:
            conn.close()

    def remove_competition_criterion(self, criterion_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM competition_rubric WHERE id=?",
                               (criterion_id,)).fetchone()
            if row is None:
                raise RepositoryError("评审项不存在")
            conn.execute("DELETE FROM competition_rubric WHERE id=?", (criterion_id,))
            self._project_event(conn, row["project_id"], "删除评审项", "系统",
                                row["criterion"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除评审项失败：%s" % e)
        finally:
            conn.close()

    # ---------- v0.35 产品：PRD / 架构 / BOM / 原型 / 测试 / 评审 ----------
    def _product_rows(self, table, project_id) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM %s WHERE project_id=? ORDER BY sort_order, id" % table,
                (project_id,)).fetchall()]
        except sqlite3.Error as e:
            raise RepositoryError("读取产品数据失败：%s" % e)
        finally:
            conn.close()

    def list_all_product_rows(self, table) -> list:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM %s ORDER BY project_id, sort_order, id" % table).fetchall()]
        finally:
            conn.close()

    def list_product_specs(self, project_id, kind="") -> list:
        rows = self._product_rows("product_specs", project_id)
        kind = _clean(kind)
        return [r for r in rows if not kind or r.get("kind") == kind]

    def list_all_product_specs(self) -> list:
        return self.list_all_product_rows("product_specs")

    def add_product_spec(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("产品文档条目格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        kind = _clean(data.get("kind")) or "prd"
        if kind not in PRODUCT_SPEC_KINDS:
            raise RepositoryError("产品文档类型不在允许范围内")
        section = _clean(data.get("section"))
        if not section:
            raise RepositoryError("文档小节不能为空")
        now = now_full()
        conn = self._conn()
        try:
            dup = conn.execute("SELECT id FROM product_specs WHERE project_id=? "
                               "AND kind=? AND section=?", (project_id, kind, section)).fetchone()
            if dup is not None:
                raise RepositoryError("同一类型下已有同名小节")
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM product_specs WHERE project_id=? AND kind=?",
                               (project_id, kind)).fetchone()
            cur = conn.execute("""INSERT INTO product_specs
                (project_id,kind,section,content,sort_order,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?)""",
                (project_id, kind, section, _clean(data.get("content")),
                 int(row["n"]), now, now))
            self._project_event(conn, project_id, "添加文档小节", "系统",
                                "%s · %s" % (PRODUCT_SPEC_KINDS[kind], section))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("添加文档小节失败：%s" % e)
        finally:
            conn.close()

    def update_product_spec(self, spec_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("产品文档条目格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_specs WHERE id=?",
                               (spec_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("文档小节不存在")
        allowed = ("kind", "section", "content", "sort_order")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "kind":
                value = _clean(data.get(key)) or "prd"
                if value not in PRODUCT_SPEC_KINDS:
                    raise RepositoryError("产品文档类型不在允许范围内")
            elif key == "section":
                value = _clean(data.get(key))
                if not value:
                    raise RepositoryError("文档小节不能为空")
            elif key == "sort_order":
                try:
                    value = int(data.get(key))
                except (TypeError, ValueError):
                    raise RepositoryError("排序应为整数")
            else:
                value = _clean(data.get(key))
            values[key] = value
        if not values:
            return
        kind = values.get("kind", row["kind"])
        section = values.get("section", row["section"])
        if kind != row["kind"] or section != row["section"]:
            conn = self._conn()
            try:
                dup = conn.execute("SELECT id FROM product_specs WHERE project_id=? "
                                   "AND kind=? AND section=? AND id<>?",
                                   (row["project_id"], kind, section, spec_id)).fetchone()
            finally:
                conn.close()
            if dup is not None:
                raise RepositoryError("同一类型下已有同名小节")
        values["updated_at"] = now_full()
        conn = self._conn()
        try:
            conn.execute("UPDATE product_specs SET %s WHERE id=?" %
                         ", ".join("%s=?" % k for k in values),
                         list(values.values()) + [spec_id])
            self._project_event(conn, row["project_id"], "更新文档小节", "系统",
                                "%s · %s" % (PRODUCT_SPEC_KINDS.get(kind, kind), section))
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新文档小节失败：%s" % e)
        finally:
            conn.close()

    def remove_product_spec(self, spec_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_specs WHERE id=?",
                               (spec_id,)).fetchone()
            if row is None:
                raise RepositoryError("文档小节不存在")
            conn.execute("DELETE FROM product_specs WHERE id=?", (spec_id,))
            self._project_event(conn, row["project_id"], "删除文档小节", "系统",
                                row["section"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除文档小节失败：%s" % e)
        finally:
            conn.close()

    def list_product_bom(self, project_id) -> list:
        return self._product_rows("product_bom", project_id)

    def list_all_product_bom(self) -> list:
        return self.list_all_product_rows("product_bom")

    def add_product_bom(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("BOM 条目格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        kind = _clean(data.get("kind")) or "物料"
        if kind not in PRODUCT_BOM_KINDS:
            raise RepositoryError("BOM 类型不在允许范围内")
        name = _clean(data.get("name"))
        if not name:
            raise RepositoryError("BOM 名称不能为空")
        qty, unit_cost = _bom_numbers(data)
        now = now_full()
        conn = self._conn()
        try:
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM product_bom WHERE project_id=?",
                               (project_id,)).fetchone()
            cur = conn.execute("""INSERT INTO product_bom
                (project_id,kind,name,spec,qty,unit,unit_cost,source,note,
                 sort_order,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id, kind, name, _clean(data.get("spec")), qty,
                 _clean(data.get("unit")) or "件", unit_cost,
                 _clean(data.get("source")), _clean(data.get("note")),
                 int(row["n"]), now, now))
            self._project_event(conn, project_id, "添加 BOM", "系统",
                                "%s · %s" % (kind, name))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("添加 BOM 失败：%s" % e)
        finally:
            conn.close()

    def update_product_bom(self, bom_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("BOM 条目格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_bom WHERE id=?", (bom_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("BOM 条目不存在")
        allowed = ("kind", "name", "spec", "qty", "unit", "unit_cost",
                   "source", "note", "sort_order")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "kind":
                value = _clean(data.get(key)) or "物料"
                if value not in PRODUCT_BOM_KINDS:
                    raise RepositoryError("BOM 类型不在允许范围内")
            elif key == "name":
                value = _clean(data.get(key))
                if not value:
                    raise RepositoryError("BOM 名称不能为空")
            elif key in ("qty", "unit_cost"):
                try:
                    value = float(data.get(key) or 0)
                except (TypeError, ValueError):
                    raise RepositoryError("数量与单价应为数字")
                if value < 0 or (key == "qty" and value == 0):
                    raise RepositoryError("数量应大于 0，单价不能为负")
            elif key == "sort_order":
                try:
                    value = int(data.get(key))
                except (TypeError, ValueError):
                    raise RepositoryError("排序应为整数")
            else:
                value = _clean(data.get(key))
            values[key] = value
        if not values:
            return
        values["updated_at"] = now_full()
        conn = self._conn()
        try:
            conn.execute("UPDATE product_bom SET %s WHERE id=?" %
                         ", ".join("%s=?" % k for k in values),
                         list(values.values()) + [bom_id])
            self._project_event(conn, row["project_id"], "更新 BOM", "系统", row["name"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新 BOM 失败：%s" % e)
        finally:
            conn.close()

    def remove_product_bom(self, bom_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_bom WHERE id=?", (bom_id,)).fetchone()
            if row is None:
                raise RepositoryError("BOM 条目不存在")
            conn.execute("DELETE FROM product_bom WHERE id=?", (bom_id,))
            self._project_event(conn, row["project_id"], "删除 BOM", "系统", row["name"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除 BOM 失败：%s" % e)
        finally:
            conn.close()

    def list_product_protos(self, project_id) -> list:
        return self._product_rows("product_protos", project_id)

    def list_all_product_protos(self) -> list:
        return self.list_all_product_rows("product_protos")

    def add_product_proto(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("原型条目格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        name = _clean(data.get("name"))
        if not name:
            raise RepositoryError("原型名称不能为空")
        status = _clean(data.get("status")) or "待做"
        if status not in PRODUCT_PROTOTYPE_STATUS:
            raise RepositoryError("原型状态不在允许范围内")
        now = now_full()
        conn = self._conn()
        try:
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM product_protos WHERE project_id=?",
                               (project_id,)).fetchone()
            cur = conn.execute("""INSERT INTO product_protos
                (project_id,name,version,path,status,note,sort_order,
                 created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (project_id, name, _clean(data.get("version")), _clean(data.get("path")),
                 status, _clean(data.get("note")), int(row["n"]), now, now))
            self._project_event(conn, project_id, "添加原型", "系统",
                                name + (" · " + status if status else ""))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("添加原型失败：%s" % e)
        finally:
            conn.close()

    def update_product_proto(self, proto_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("原型条目格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_protos WHERE id=?",
                               (proto_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("原型不存在")
        allowed = ("name", "version", "path", "status", "note", "sort_order")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "name":
                value = _clean(data.get(key))
                if not value:
                    raise RepositoryError("原型名称不能为空")
            elif key == "status":
                value = _clean(data.get(key)) or "待做"
                if value not in PRODUCT_PROTOTYPE_STATUS:
                    raise RepositoryError("原型状态不在允许范围内")
            elif key == "sort_order":
                try:
                    value = int(data.get(key))
                except (TypeError, ValueError):
                    raise RepositoryError("排序应为整数")
            else:
                value = _clean(data.get(key))
            values[key] = value
        if not values:
            return
        values["updated_at"] = now_full()
        conn = self._conn()
        try:
            conn.execute("UPDATE product_protos SET %s WHERE id=?" %
                         ", ".join("%s=?" % k for k in values),
                         list(values.values()) + [proto_id])
            self._project_event(conn, row["project_id"], "更新原型", "系统", row["name"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新原型失败：%s" % e)
        finally:
            conn.close()

    def remove_product_proto(self, proto_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_protos WHERE id=?",
                               (proto_id,)).fetchone()
            if row is None:
                raise RepositoryError("原型不存在")
            conn.execute("DELETE FROM product_protos WHERE id=?", (proto_id,))
            self._project_event(conn, row["project_id"], "删除原型", "系统", row["name"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除原型失败：%s" % e)
        finally:
            conn.close()

    def list_product_tests(self, project_id) -> list:
        return self._product_rows("product_tests", project_id)

    def list_all_product_tests(self) -> list:
        return self.list_all_product_rows("product_tests")

    def add_product_test(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("测试条目格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        name = _clean(data.get("name"))
        if not name:
            raise RepositoryError("测试项名称不能为空")
        result = _clean(data.get("result")) or "未测"
        if result not in PRODUCT_TEST_RESULTS:
            raise RepositoryError("测试结果不在允许范围内")
        severity = _clean(data.get("severity")) or "中"
        if severity not in PRODUCT_TEST_SEVERITIES:
            raise RepositoryError("严重程度不在允许范围内")
        now = now_full()
        conn = self._conn()
        try:
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM product_tests WHERE project_id=?",
                               (project_id,)).fetchone()
            cur = conn.execute("""INSERT INTO product_tests
                (project_id,name,method,expected,result,severity,issue,note,
                 sort_order,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id, name, _clean(data.get("method")),
                 _clean(data.get("expected")), result, severity,
                 _clean(data.get("issue")), _clean(data.get("note")),
                 int(row["n"]), now, now))
            self._project_event(conn, project_id, "添加测试项", "系统",
                                name + (" · " + result if result else ""))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("添加测试项失败：%s" % e)
        finally:
            conn.close()

    def update_product_test(self, test_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("测试条目格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_tests WHERE id=?",
                               (test_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("测试项不存在")
        allowed = ("name", "method", "expected", "result", "severity",
                   "issue", "note", "sort_order")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "name":
                value = _clean(data.get(key))
                if not value:
                    raise RepositoryError("测试项名称不能为空")
            elif key == "result":
                value = _clean(data.get(key)) or "未测"
                if value not in PRODUCT_TEST_RESULTS:
                    raise RepositoryError("测试结果不在允许范围内")
            elif key == "severity":
                value = _clean(data.get(key)) or "中"
                if value not in PRODUCT_TEST_SEVERITIES:
                    raise RepositoryError("严重程度不在允许范围内")
            elif key == "sort_order":
                try:
                    value = int(data.get(key))
                except (TypeError, ValueError):
                    raise RepositoryError("排序应为整数")
            else:
                value = _clean(data.get(key))
            values[key] = value
        if not values:
            return
        values["updated_at"] = now_full()
        conn = self._conn()
        try:
            conn.execute("UPDATE product_tests SET %s WHERE id=?" %
                         ", ".join("%s=?" % k for k in values),
                         list(values.values()) + [test_id])
            self._project_event(conn, row["project_id"], "更新测试项", "系统", row["name"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新测试项失败：%s" % e)
        finally:
            conn.close()

    def remove_product_test(self, test_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_tests WHERE id=?",
                               (test_id,)).fetchone()
            if row is None:
                raise RepositoryError("测试项不存在")
            conn.execute("DELETE FROM product_tests WHERE id=?", (test_id,))
            self._project_event(conn, row["project_id"], "删除测试项", "系统", row["name"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除测试项失败：%s" % e)
        finally:
            conn.close()

    def list_product_reviews(self, project_id) -> list:
        return self._product_rows("product_reviews", project_id)

    def list_all_product_reviews(self) -> list:
        return self.list_all_product_rows("product_reviews")

    def add_product_review(self, project_id, data: dict) -> int:
        if not isinstance(data, dict):
            raise RepositoryError("评审记录格式不正确")
        if not self._project_exists(project_id):
            raise RepositoryError("项目不存在")
        gate = _clean(data.get("gate"))
        if gate not in PRODUCT_REVIEW_GATES:
            raise RepositoryError("评审门不在允许范围内")
        conclusion = _clean(data.get("conclusion")) or "待评审"
        if conclusion not in PRODUCT_REVIEW_CONCLUSIONS:
            raise RepositoryError("评审结论不在允许范围内")
        date_text = normalize_deadline(data.get("date")) if data.get("date") else ""
        now = now_full()
        conn = self._conn()
        try:
            row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n "
                               "FROM product_reviews WHERE project_id=?",
                               (project_id,)).fetchone()
            cur = conn.execute("""INSERT INTO product_reviews
                (project_id,gate,reviewer,date,conclusion,note,sort_order,
                 created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (project_id, gate, _clean(data.get("reviewer")), date_text,
                 conclusion, _clean(data.get("note")), int(row["n"]), now, now))
            self._project_event(conn, project_id, "添加评审门", "系统",
                                gate + (" · " + conclusion if conclusion else ""))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            raise RepositoryError("添加评审门失败：%s" % e)
        finally:
            conn.close()

    def update_product_review(self, review_id, data: dict):
        if not isinstance(data, dict):
            raise RepositoryError("评审记录格式不正确")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_reviews WHERE id=?",
                               (review_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RepositoryError("评审记录不存在")
        allowed = ("gate", "reviewer", "date", "conclusion", "note", "sort_order")
        values = {}
        for key in allowed:
            if key not in data:
                continue
            if key == "gate":
                value = _clean(data.get(key))
                if value not in PRODUCT_REVIEW_GATES:
                    raise RepositoryError("评审门不在允许范围内")
            elif key == "conclusion":
                value = _clean(data.get(key)) or "待评审"
                if value not in PRODUCT_REVIEW_CONCLUSIONS:
                    raise RepositoryError("评审结论不在允许范围内")
            elif key == "date":
                value = normalize_deadline(data.get(key)) if data.get(key) else ""
            elif key == "sort_order":
                try:
                    value = int(data.get(key))
                except (TypeError, ValueError):
                    raise RepositoryError("排序应为整数")
            else:
                value = _clean(data.get(key))
            values[key] = value
        if not values:
            return
        values["updated_at"] = now_full()
        conn = self._conn()
        try:
            conn.execute("UPDATE product_reviews SET %s WHERE id=?" %
                         ", ".join("%s=?" % k for k in values),
                         list(values.values()) + [review_id])
            self._project_event(conn, row["project_id"], "更新评审门", "系统", row["gate"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("更新评审门失败：%s" % e)
        finally:
            conn.close()

    def remove_product_review(self, review_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM product_reviews WHERE id=?",
                               (review_id,)).fetchone()
            if row is None:
                raise RepositoryError("评审记录不存在")
            conn.execute("DELETE FROM product_reviews WHERE id=?", (review_id,))
            self._project_event(conn, row["project_id"], "删除评审门", "系统", row["gate"])
            conn.commit()
        except sqlite3.Error as e:
            raise RepositoryError("删除评审门失败：%s" % e)
        finally:
            conn.close()

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
        projects = self.list_projects()
        deliverables = self.list_all_deliverables()
        project_events = self.list_all_project_events()
        comp_events = self.list_all_competition_events()
        comp_entries = self.list_all_competition_entries()
        comp_rubric = self.list_all_competition_rubric()
        prod_specs = self.list_all_product_specs()
        prod_bom = self.list_all_product_bom()
        prod_protos = self.list_all_product_protos()
        prod_tests = self.list_all_product_tests()
        prod_reviews = self.list_all_product_reviews()
        return {"app": "class-console", "version": VERSION,
                "exportedAt": datetime.datetime.now().isoformat(timespec="seconds"),
                "counts": {"docs": len(docs), "logs": len(self.list_logs()),
                           "roster": len(self.list_roster()),
                           "tasks": len(self.list_tasks()),
                           "attachments": len(atts),
                           "templates": len(templates),
                           "projects": len(projects),
                           "project_deliverables": len(deliverables),
                           "project_events": len(project_events),
                           "competition_events": len(comp_events),
                           "competition_entries": len(comp_entries),
                           "competition_rubric": len(comp_rubric),
                           "product_specs": len(prod_specs),
                           "product_bom": len(prod_bom),
                           "product_protos": len(prod_protos),
                           "product_tests": len(prod_tests),
                           "product_reviews": len(prod_reviews)},
                "docs": docs, "logs": self.list_logs(),
                "roster": self.list_roster(), "tasks": self.list_tasks(),
                "attachments": atts, "templates": templates,
                "events": self.list_all_events(),
                "exemptions": self.list_exemptions(),
                "followups": self.list_followups(),
                "projects": projects,
                "project_deliverables": deliverables,
                "project_events": project_events,
                "competition_events": comp_events,
                "competition_entries": comp_entries,
                "competition_rubric": comp_rubric,
                "product_specs": prod_specs,
                "product_bom": prod_bom,
                "product_protos": prod_protos,
                "product_tests": prod_tests,
                "product_reviews": prod_reviews}

    def restore(self, docs: list, logs: list, roster=None, tasks=None,
                attachments=None, templates=None, events=None,
                exemptions=None, followups=None,
                projects=None, project_deliverables=None,
                project_events=None, competition_events=None,
                competition_entries=None, competition_rubric=None,
                product_specs=None, product_bom=None, product_protos=None,
                product_tests=None, product_reviews=None):
        if not isinstance(docs, list) or not isinstance(logs, list):
            raise RepositoryError("备份数据结构不正确")
        roster = roster if isinstance(roster, list) else []
        tasks = tasks if isinstance(tasks, list) else []
        attachments = attachments if isinstance(attachments, list) else []
        events = events if isinstance(events, list) else []
        exemptions = exemptions if isinstance(exemptions, list) else []
        followups = followups if isinstance(followups, list) else []
        projects = projects if isinstance(projects, list) else []
        project_deliverables = (project_deliverables
                                if isinstance(project_deliverables, list) else [])
        project_events = (project_events
                           if isinstance(project_events, list) else [])
        competition_events = (competition_events
                              if isinstance(competition_events, list) else [])
        competition_entries = (competition_entries
                               if isinstance(competition_entries, list) else [])
        competition_rubric = (competition_rubric
                              if isinstance(competition_rubric, list) else [])
        product_specs = product_specs if isinstance(product_specs, list) else []
        product_bom = product_bom if isinstance(product_bom, list) else []
        product_protos = product_protos if isinstance(product_protos, list) else []
        product_tests = product_tests if isinstance(product_tests, list) else []
        product_reviews = product_reviews if isinstance(product_reviews, list) else []
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
            conn.execute("DELETE FROM project_deliverables")
            conn.execute("DELETE FROM project_assets")
            conn.execute("DELETE FROM project_runs")
            conn.execute("DELETE FROM project_gates")
            conn.execute("DELETE FROM project_events")
            conn.execute("DELETE FROM competition_events")
            conn.execute("DELETE FROM competition_entries")
            conn.execute("DELETE FROM competition_rubric")
            conn.execute("DELETE FROM product_specs")
            conn.execute("DELETE FROM product_bom")
            conn.execute("DELETE FROM product_protos")
            conn.execute("DELETE FROM product_tests")
            conn.execute("DELETE FROM product_reviews")
            conn.execute("DELETE FROM projects")
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
            project_map = {}
            for p in projects:
                if not isinstance(p, dict):
                    continue
                name = _clean(p.get("name"))
                if not name:
                    continue
                kind = _clean(p.get("kind"))
                if kind not in PROJECT_KINDS:
                    kind = "class"
                stage = _clean(p.get("stage"))
                if stage not in PROJECT_STAGES:
                    stage = "定义"
                status = _clean(p.get("status"))
                if status not in PROJECT_STATUS:
                    status = "进行中"
                start_date = ""
                due_date = ""
                if p.get("start_date"):
                    try:
                        start_date = normalize_deadline(p.get("start_date"))
                    except Exception:
                        start_date = ""
                if p.get("due_date"):
                    try:
                        due_date = normalize_deadline(p.get("due_date"))
                    except Exception:
                        due_date = ""
                cur = conn.execute("""INSERT INTO projects
                    (name,kind,stage,status,owner,start_date,due_date,goal,note,
                     created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (name, kind, stage, status, _clean(p.get("owner")),
                     start_date, due_date, _clean(p.get("goal")),
                     _clean(p.get("note")),
                     _clean(p.get("created_at")) or now_full(),
                     _clean(p.get("updated_at")) or now_full()))
                project_map[str(p.get("id"))] = cur.lastrowid
            for d in project_deliverables:
                if not isinstance(d, dict):
                    continue
                pid = project_map.get(str(d.get("project_id")))
                if pid is None:
                    continue
                name = _clean(d.get("name"))
                if not name:
                    continue
                stage = _clean(d.get("stage"))
                if stage not in PROJECT_STAGES:
                    stage = "生产"
                status = _clean(d.get("status"))
                if status not in DELIVERABLE_STATUS:
                    status = "待开始"
                try:
                    sort_order = int(d.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO project_deliverables
                    (project_id,name,stage,status,required,note,sort_order,
                     created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (pid, name, stage, status,
                     1 if d.get("required", True) else 0,
                     _clean(d.get("note")), sort_order,
                     _clean(d.get("created_at")) or now_full(),
                     _clean(d.get("updated_at")) or now_full()))
            for ev in project_events:
                if not isinstance(ev, dict):
                    continue
                pid = project_map.get(str(ev.get("project_id")))
                if pid is None:
                    continue
                conn.execute("""INSERT INTO project_events
                    (project_id,time,act,who,detail) VALUES (?,?,?,?,?)""",
                    (pid, _clean(ev.get("time")) or now_full(),
                     _clean(ev.get("act")) or "恢复",
                     _clean(ev.get("who")) or "系统",
                     _clean(ev.get("detail"))))
            for ev in competition_events:
                if not isinstance(ev, dict):
                    continue
                pid = project_map.get(str(ev.get("project_id")))
                if pid is None:
                    continue
                title = _clean(ev.get("title"))
                if not title:
                    continue
                date_text = ""
                if ev.get("date"):
                    try:
                        date_text = normalize_deadline(ev.get("date"))
                    except Exception:
                        date_text = ""
                try:
                    sort_order = int(ev.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO competition_events
                    (project_id,title,date,note,done,sort_order,
                     created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (pid, title, date_text, _clean(ev.get("note")),
                     1 if ev.get("done") else 0, sort_order,
                     _clean(ev.get("created_at")) or now_full(),
                     _clean(ev.get("updated_at")) or now_full()))
            for en in competition_entries:
                if not isinstance(en, dict):
                    continue
                pid = project_map.get(str(en.get("project_id")))
                if pid is None:
                    continue
                name = _clean(en.get("name"))
                if not name:
                    continue
                role = _clean(en.get("role")) or "队员"
                if role not in COMPETITION_ROLES:
                    role = "其他"
                try:
                    sort_order = int(en.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO competition_entries
                    (project_id,name,sid,role,contact,confirmed,note,sort_order,
                     created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (pid, name, _clean(en.get("sid")), role,
                     _clean(en.get("contact")),
                     1 if en.get("confirmed") else 0, _clean(en.get("note")),
                     sort_order, _clean(en.get("created_at")) or now_full(),
                     _clean(en.get("updated_at")) or now_full()))
            for rb in competition_rubric:
                if not isinstance(rb, dict):
                    continue
                pid = project_map.get(str(rb.get("project_id")))
                if pid is None:
                    continue
                criterion = _clean(rb.get("criterion"))
                if not criterion:
                    continue
                try:
                    weight = max(0, min(100, int(rb.get("weight") or 0)))
                except (TypeError, ValueError):
                    weight = 0
                score = rb.get("score")
                if score in ("", None):
                    score = None
                else:
                    try:
                        score = max(0, min(100, int(score)))
                    except (TypeError, ValueError):
                        score = None
                try:
                    sort_order = int(rb.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO competition_rubric
                    (project_id,criterion,weight,score,evidence,note,sort_order,
                     created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (pid, criterion, weight, score, _clean(rb.get("evidence")),
                     _clean(rb.get("note")), sort_order,
                     _clean(rb.get("created_at")) or now_full(),
                     _clean(rb.get("updated_at")) or now_full()))
            for sp in product_specs:
                if not isinstance(sp, dict):
                    continue
                pid = project_map.get(str(sp.get("project_id")))
                if pid is None:
                    continue
                kind = _clean(sp.get("kind")) or "prd"
                if kind not in PRODUCT_SPEC_KINDS:
                    kind = "prd"
                section = _clean(sp.get("section"))
                if not section:
                    continue
                try:
                    sort_order = int(sp.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO product_specs
                    (project_id,kind,section,content,sort_order,
                     created_at,updated_at) VALUES (?,?,?,?,?,?,?)""",
                    (pid, kind, section, _clean(sp.get("content")), sort_order,
                     _clean(sp.get("created_at")) or now_full(),
                     _clean(sp.get("updated_at")) or now_full()))
            for bm in product_bom:
                if not isinstance(bm, dict):
                    continue
                pid = project_map.get(str(bm.get("project_id")))
                if pid is None:
                    continue
                kind = _clean(bm.get("kind")) or "物料"
                if kind not in PRODUCT_BOM_KINDS:
                    kind = "其他"
                name = _clean(bm.get("name"))
                if not name:
                    continue
                try:
                    qty = float(bm.get("qty") or 0)
                    unit_cost = float(bm.get("unit_cost") or 0)
                except (TypeError, ValueError):
                    qty, unit_cost = 0, 0
                if qty <= 0:
                    qty = 1
                if unit_cost < 0:
                    unit_cost = 0
                try:
                    sort_order = int(bm.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO product_bom
                    (project_id,kind,name,spec,qty,unit,unit_cost,source,note,
                     sort_order,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (pid, kind, name, _clean(bm.get("spec")), qty,
                     _clean(bm.get("unit")) or "件", unit_cost,
                     _clean(bm.get("source")), _clean(bm.get("note")), sort_order,
                     _clean(bm.get("created_at")) or now_full(),
                     _clean(bm.get("updated_at")) or now_full()))
            for pt in product_protos:
                if not isinstance(pt, dict):
                    continue
                pid = project_map.get(str(pt.get("project_id")))
                if pid is None:
                    continue
                name = _clean(pt.get("name"))
                if not name:
                    continue
                status = _clean(pt.get("status")) or "待做"
                if status not in PRODUCT_PROTOTYPE_STATUS:
                    status = "待做"
                try:
                    sort_order = int(pt.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO product_protos
                    (project_id,name,version,path,status,note,sort_order,
                     created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (pid, name, _clean(pt.get("version")), _clean(pt.get("path")),
                     status, _clean(pt.get("note")), sort_order,
                     _clean(pt.get("created_at")) or now_full(),
                     _clean(pt.get("updated_at")) or now_full()))
            for ts in product_tests:
                if not isinstance(ts, dict):
                    continue
                pid = project_map.get(str(ts.get("project_id")))
                if pid is None:
                    continue
                name = _clean(ts.get("name"))
                if not name:
                    continue
                result = _clean(ts.get("result")) or "未测"
                if result not in PRODUCT_TEST_RESULTS:
                    result = "未测"
                severity = _clean(ts.get("severity")) or "中"
                if severity not in PRODUCT_TEST_SEVERITIES:
                    severity = "中"
                try:
                    sort_order = int(ts.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO product_tests
                    (project_id,name,method,expected,result,severity,issue,note,
                     sort_order,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (pid, name, _clean(ts.get("method")), _clean(ts.get("expected")),
                     result, severity, _clean(ts.get("issue")), _clean(ts.get("note")),
                     sort_order, _clean(ts.get("created_at")) or now_full(),
                     _clean(ts.get("updated_at")) or now_full()))
            for rv in product_reviews:
                if not isinstance(rv, dict):
                    continue
                pid = project_map.get(str(rv.get("project_id")))
                if pid is None:
                    continue
                gate = _clean(rv.get("gate"))
                if gate not in PRODUCT_REVIEW_GATES:
                    continue
                conclusion = _clean(rv.get("conclusion")) or "待评审"
                if conclusion not in PRODUCT_REVIEW_CONCLUSIONS:
                    conclusion = "待评审"
                date_text = ""
                if rv.get("date"):
                    try:
                        date_text = normalize_deadline(rv.get("date"))
                    except Exception:
                        date_text = ""
                try:
                    sort_order = int(rv.get("sort_order") or 0)
                except (TypeError, ValueError):
                    sort_order = 0
                conn.execute("""INSERT INTO product_reviews
                    (project_id,gate,reviewer,date,conclusion,note,sort_order,
                     created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (pid, gate, _clean(rv.get("reviewer")), date_text,
                     conclusion, _clean(rv.get("note")), sort_order,
                     _clean(rv.get("created_at")) or now_full(),
                     _clean(rv.get("updated_at")) or now_full()))
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
    global LAST_STARTUP_ISSUE
    LAST_STARTUP_ISSUE = None
    db_path = app_data_dir() / "console.db"
    try:
        return LocalRepository(db_path)
    except Exception as e:
        isolated = ""
        try:
            if db_path.exists():
                stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                target = db_path.with_name("console.corrupt-%s.db" % stamp)
                db_path.rename(target)
                isolated = target.name
        except Exception as rename_error:
            print("隔离损坏数据库失败：%s" % type(rename_error).__name__,
                  file=sys.stderr)
        impact = ("程序已把原库改名为 %s 并新建空库；原数据没有被删除。"
                  % isolated) if isolated else \
                 "程序未能改名隔离；原库仍原样保留，没有被删除。"
        LAST_STARTUP_ISSUE = SimpleNamespace(
            what="启动时发现本机数据库损坏或无法打开（%s）。" % type(e).__name__,
            impact=impact,
            next_step="先到数据目录复制隔离文件留底，再从备份恢复或重新导入。",
            fallback="当前空库可以继续用；不要直接覆盖隔离文件。")
        return LocalRepository(db_path)
