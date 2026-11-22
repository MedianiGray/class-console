# -*- coding: utf-8 -*-
"""全局视觉常量与主题：同一套 token 支撑浅色 / 深色，供入口与各视图共用。

与网页端 v0.12.0 的 token 命名对齐，改色只改这里。
"""

import json
import os
from pathlib import Path

FONT = "Microsoft YaHei"

# 浅色：三层表面（页面 / 表面 / 抬升），靠明度差与发丝线分层，不靠投影
LIGHT = {
    "bg": "#EDF0F5",
    "card": "#FFFFFF",
    "surface_alt": "#F7F9FC",
    "topbar": "#FFFFFF",
    "line": "#E2E8F0",
    "line_strong": "#CBD5E2",
    "edge": "#D8E0EA",
    "bg_soft": "#F1F4F9",
    "text": "#131A24",
    "muted": "#5E6976",
    "sub": "#94A0AD",
    "primary": "#3A58D8",
    "primary_hover": "#2C46BE",
    "primary_soft": "#EAEFFD",
    "green": "#128B4C",
    "orange": "#C87A08",
    "red": "#D23235",
    "zebra": "#FAFBFD",
    "th_bg": "#FFFFFF",
    "row_hover": "#F4F7FB",
    "tag_green": "#E8F6EE",
    "tag_orange": "#FDF2E1",
    "tag_red": "#FDEDED",
    "tag_muted": "#F0F2F6",
    "danger_line": "#EFBABA",
    "danger_bg": "#FDF0F0",
    "bulk_line": "#D5DDFA",
    "scroll": "#C3CEDB",
    "select": "#EAEFFD",
    "scrollbar": "#C3CEDB",
    "on_primary": "#FFFFFF",
    # 兼容旧键名
    "content": "#EDF0F5",
    "sidebar": "#FAFBFD",
    "sidebar_active": "#EAEFFD",
    "accent": "#3A58D8",
}

# 深色：页面最深、顶栏略抬、卡片再抬一层
DARK = {
    "bg": "#0F1115",
    "card": "#181B21",
    "surface_alt": "#1D2128",
    "topbar": "#14171C",
    "line": "#272C35",
    "line_strong": "#3B4350",
    "edge": "#0A0C0F",
    "bg_soft": "#20252D",
    "text": "#E9ECF2",
    "muted": "#97A2B1",
    "sub": "#6A7382",
    "primary": "#7B93FF",
    "primary_hover": "#93A8FF",
    "primary_soft": "#222A42",
    "green": "#4CBE86",
    "orange": "#DFA24B",
    "red": "#EF6E6E",
    "zebra": "#1B1F25",
    "th_bg": "#181B21",
    "row_hover": "#232833",
    "tag_green": "#16332A",
    "tag_orange": "#332A19",
    "tag_red": "#392326",
    "tag_muted": "#23272E",
    "danger_line": "#482B2E",
    "danger_bg": "#2C2022",
    "bulk_line": "#2B3450",
    "scroll": "#3A4049",
    "select": "#222A42",
    "scrollbar": "#3A4049",
    "on_primary": "#FFFFFF",
    # 兼容旧键名
    "content": "#0F1115",
    "sidebar": "#12151A",
    "sidebar_active": "#222A42",
    "accent": "#7B93FF",
}

# 各视图 import 的是这个 dict 对象本身；切主题原地改写，引用不失效。
C = dict(LIGHT)

# 强调色预设：同一套 token 换主色，避免为每种配色重写整套主题。
# 每项为 (主色, 悬停色, 淡底色) 的 light / dark 两版。
ACCENTS = {
    "azure": {"label": "湛蓝", "light": ("#3A58D8", "#2C46BE", "#EAEFFD"),
              "dark": ("#7B93FF", "#93A8FF", "#232B44")},
    "teal": {"label": "青碧", "light": ("#0E7C86", "#0A626B", "#E3F3F4"),
             "dark": ("#4CBFCB", "#6FD3DD", "#16333A")},
    "violet": {"label": "紫藤", "light": ("#6A4BD8", "#5738BE", "#F0ECFD"),
               "dark": ("#A48BFF", "#B8A4FF", "#252247")},
    "rose": {"label": "玫红", "light": ("#C22A63", "#A61F51", "#FCEAF0"),
             "dark": ("#F0729B", "#FF8FB1", "#3A1F2A")},
    "forest": {"label": "松绿", "light": ("#0F7A52", "#0A6242", "#E6F5EF"),
               "dark": ("#58C79A", "#74D7AE", "#17322A")},
    "graphite": {"label": "石墨", "light": ("#39434F", "#2A323C", "#EDF0F4"),
                 "dark": ("#B9C4D2", "#CBD5E1", "#2A2F36")},
    "amber": {"label": "琥珀", "light": ("#A9660B", "#8B5308", "#FCF2E2"),
              "dark": ("#E0A144", "#F0B35C", "#302518")},
    "sky": {"label": "天青", "light": ("#1273AE", "#0D5F91", "#E7F3FA"),
            "dark": ("#5AB0DE", "#78C3EC", "#172A34")},
    "indigo": {"label": "靛蓝", "light": ("#4B4FD6", "#3A3EB8", "#EDEDFB"),
               "dark": ("#8A8CF0", "#A2A4F7", "#22243A")},
    "coral": {"label": "珊瑚", "light": ("#BE4B2E", "#A03D25", "#FAECE7"),
              "dark": ("#E58A6D", "#F2A48B", "#33231D")},
}
ACCENT_DEFAULT = "azure"


def _to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _to_hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in rgb)


def _mix(a, b, w):
    """按 w 把 a 混向 b（w=0 全 a，w=1 全 b）。"""
    ra, rb = _to_rgb(a), _to_rgb(b)
    return _to_hex(tuple(ra[i] + (rb[i] - ra[i]) * w for i in range(3)))


def _shade(hex_color, k):
    """k>0 提亮、k<0 压暗。"""
    target = "#FFFFFF" if k > 0 else "#000000"
    return _mix(hex_color, target, abs(k))


def contrast_on(hex_color):
    r, g, b = _to_rgb(hex_color)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "#171E29" if lum > 0.62 else "#FFFFFF"

MODES = ("light", "dark", "system")
MODE_LABEL = {"light": "浅色", "dark": "深色", "system": "跟随"}

_theme_mode = "system"
_resolved = "light"
_applied = False
_accent = ACCENT_DEFAULT
_density = "cozy"


def _settings_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "ClassConsole" / "settings.json"


def _read_settings():
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_settings(data):
    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_mode():
    mode = _read_settings().get("theme")
    return mode if mode in MODES else "system"


def load_accent():
    """返回已保存的强调色：预设名或 #RRGGBB。"""
    val = _read_settings().get("accent")
    if isinstance(val, str) and (val in ACCENTS or _is_hex(val)):
        return val
    return ACCENT_DEFAULT


def load_ui(key, default):
    val = _read_settings().get("ui", {})
    if isinstance(val, dict):
        return val.get(key, default)
    return default


def save_ui(key, value):
    data = _read_settings()
    ui = data.get("ui")
    if not isinstance(ui, dict):
        ui = {}
    ui[key] = value
    data["ui"] = ui
    _write_settings(data)


def _is_hex(val):
    if not isinstance(val, str) or len(val) != 7 or not val.startswith("#"):
        return False
    try:
        int(val[1:], 16)
        return True
    except ValueError:
        return False


def save_mode(mode):
    data = _read_settings()
    data["theme"] = mode
    _write_settings(data)


def save_accent(accent):
    data = _read_settings()
    data["accent"] = accent
    _write_settings(data)


def _apply_accent(accent, resolved_mode):
    """把强调色落到 primary / hover / soft / select 四个 token 上。"""
    global _accent
    preset = ACCENTS.get(accent)
    if preset:
        primary, hover, soft = preset["light" if resolved_mode == "light" else "dark"]
        _accent = accent
    else:
        base = accent if _is_hex(accent) else ACCENTS[ACCENT_DEFAULT]["light"][0]
        if resolved_mode == "light":
            primary = base
            hover = _shade(base, -0.16)
            soft = _mix(base, C["card"], 0.90)
        else:
            primary = _shade(base, 0.30)
            hover = _shade(base, 0.44)
            soft = _mix(primary, C["card"], 0.80)
        _accent = base.upper()
    C["primary"] = primary
    C["primary_hover"] = hover
    C["primary_soft"] = soft
    C["select"] = soft
    C["sidebar_active"] = soft
    C["bulk_line"] = _mix(primary, C["bg"], 0.55)
    C["accent"] = primary
    C["on_primary"] = contrast_on(primary)
    C["hero"] = _mix(primary, C["card"], 0.94 if resolved_mode == "light" else 0.86)
    C["hero_line"] = _mix(primary, C["line"], 0.82)
    C["accent_ink"] = primary


def system_is_dark():
    """Windows 系统「深色」偏好；读不到就按浅色处理。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        finally:
            winreg.CloseKey(key)
        return int(value) == 0
    except Exception:
        return False


def resolve(mode):
    if mode == "system":
        return "dark" if system_is_dark() else "light"
    return mode if mode in ("light", "dark") else "light"


def apply(mode, accent=None):
    """按前置模式换 token，返回实际生效的浅色/深色。"""
    global _theme_mode, _resolved, _applied
    _theme_mode = mode if mode in MODES else "system"
    _resolved = resolve(_theme_mode)
    C.clear()
    C.update(DARK if _resolved == "dark" else LIGHT)
    _apply_accent(accent or _accent or ACCENT_DEFAULT, _resolved)
    _applied = True
    return _resolved


def is_applied():
    return _applied


def mode():
    return _theme_mode


def resolved():
    return _resolved


def accent():
    return _accent


def set_mode(mode):
    apply(mode, _accent)
    save_mode(_theme_mode)


def set_accent(accent):
    apply(_theme_mode, accent)
    save_accent(_accent)


def density():
    return _density


def set_density(value):
    global _density
    _density = value if value in ("compact", "cozy", "relaxed") else "cozy"
    save_ui("density", _density)


def row_height():
    return {"compact": 28, "cozy": 32, "relaxed": 36}.get(_density, 32)


def init_from_settings():
    """启动时一次性读取主题 / 强调色 / 密度，不写回设置文件。"""
    global _density
    _density = load_ui("density", "cozy")
    return apply(load_mode(), load_accent())


def apply_tk_defaults(root):
    """让 tk 原生控件（Text / Listbox / Toplevel）也吃主题色。"""
    pairs = [
        ("*Frame*Background", C["bg"]),
        ("*Label*Background", C["bg"]),
        ("*Text*Background", C["card"]),
        ("*Text*Foreground", C["text"]),
        ("*Text*InsertBackground", C["text"]),
        ("*Text*selectBackground", C["select"]),
        ("*Text*selectForeground", C["text"]),
        ("*Text*highlightColor", C["primary"]),
        ("*Text*highlightBackground", C["line"]),
        ("*Listbox*Background", C["card"]),
        ("*Listbox*Foreground", C["text"]),
        ("*Listbox*selectBackground", C["select"]),
        ("*Listbox*selectForeground", C["text"]),
        ("*Toplevel*Background", C["bg"]),
        ("*TCombobox*Listbox*Background", C["card"]),
        ("*TCombobox*Listbox*Foreground", C["text"]),
        ("*TCombobox*Listbox*selectBackground", C["select"]),
        ("*TCombobox*Listbox*selectForeground", C["text"]),
        ("*TButton*highlightBackground", C["bg"]),
        ("*Menu*Background", C["card"]),
        ("*Menu*Foreground", C["text"]),
    ]
    for pattern, value in pairs:
        try:
            root.option_add(pattern, value)
        except Exception:
            pass


def setup_ttk(root):
    """ttk 控件统一到当前 token；切主题后重新调用即可。"""
    from tkinter import ttk

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", font=(FONT, 10), background=C["bg"], foreground=C["text"],
                    fieldbackground=C["card"], bordercolor=C["line"],
                    lightcolor=C["line"], darkcolor=C["line"],
                    troughcolor=C["bg"], focuscolor=C["primary"],
                    selectbackground=C["select"], selectforeground=C["text"],
                    insertcolor=C["text"], arrowcolor=C["muted"])

    style.configure("TFrame", background=C["bg"])
    style.configure("TLabelframe", background=C["bg"], bordercolor=C["line"])
    style.configure("TLabelframe.Label", background=C["bg"], foreground=C["text"])

    style.configure("TLabel", font=(FONT, 10), background=C["bg"], foreground=C["text"])
    style.configure("Muted.TLabel", foreground=C["muted"], font=(FONT, 9),
                    background=C["bg"])
    style.configure("Sub.TLabel", font=(FONT, 9), foreground=C["sub"],
                    background=C["bg"])
    style.configure("Eyebrow.TLabel", font=(FONT, 9), foreground=C["sub"],
                    background=C["bg"])
    style.configure("Title.TLabel", font=(FONT, 21, "bold"), foreground=C["text"],
                    background=C["bg"])
    style.configure("Card.TFrame", background=C["card"])
    style.configure("Card.TLabel", background=C["card"], foreground=C["text"])
    style.configure("CardMuted.TLabel", background=C["card"], foreground=C["muted"],
                    font=(FONT, 9))

    # 按钮：默认 / 主要 / 危险 / 无边框文字按钮
    style.configure("TButton", padding=(12, 6), relief="flat", background=C["card"],
                    foreground=C["text"], bordercolor=C["line"], borderwidth=1,
                    font=(FONT, 10))
    style.map("TButton",
              background=[("active", C["surface_alt"]), ("disabled", C["bg"])],
              foreground=[("disabled", C["sub"])],
              bordercolor=[("disabled", C["line"])],
              lightcolor=[("active", C["surface_alt"])],
              darkcolor=[("active", C["surface_alt"])])
    style.configure("Accent.TButton", background=C["primary"], foreground=C["on_primary"],
                    padding=(13, 7), relief="flat", borderwidth=0,
                    font=(FONT, 10, "bold"))
    style.map("Accent.TButton",
              background=[("active", C["primary_hover"]), ("disabled", C["bg_soft"])],
              foreground=[("disabled", C["sub"])],
              lightcolor=[("active", C["primary_hover"])],
              darkcolor=[("active", C["primary_hover"])])
    style.configure("Danger.TButton", background=C["card"], foreground=C["red"],
                    bordercolor=C["danger_line"], borderwidth=1, padding=(12, 6),
                    relief="flat")
    style.map("Danger.TButton",
              background=[("active", C["danger_bg"]), ("disabled", C["bg"])],
              foreground=[("disabled", C["sub"])],
              bordercolor=[("disabled", C["line"]), ("active", C["red"])],
              lightcolor=[("active", C["danger_bg"])],
              darkcolor=[("active", C["danger_bg"])])
    style.configure("Ghost.TButton", background=C["bg"], foreground=C["muted"],
                    borderwidth=0, padding=(9, 5), relief="flat", font=(FONT, 9))
    style.map("Ghost.TButton",
              background=[("active", C["bg_soft"]), ("disabled", C["bg"])],
              foreground=[("active", C["text"]), ("disabled", C["line"])])

    # 输入控件：聚焦时边框变强调色
    style.configure("TEntry", padding=(9, 6), bordercolor=C["line"], borderwidth=1,
                    fieldbackground=C["surface_alt"], foreground=C["text"],
                    insertcolor=C["text"])
    style.map("TEntry", bordercolor=[("focus", C["primary"])],
              fieldbackground=[("disabled", C["bg_soft"])],
              foreground=[("disabled", C["sub"])])
    style.configure("TCombobox", padding=(7, 4), bordercolor=C["line"], borderwidth=1,
                    background=C["surface_alt"], foreground=C["text"],
                    arrowcolor=C["muted"], fieldbackground=C["surface_alt"])
    style.map("TCombobox",
              fieldbackground=[("readonly", C["surface_alt"]), ("disabled", C["bg_soft"])],
              foreground=[("readonly", C["text"]), ("disabled", C["sub"])],
              background=[("readonly", C["surface_alt"]), ("active", C["surface_alt"])],
              arrowcolor=[("active", C["primary"])],
              bordercolor=[("focus", C["primary"])],
              selectbackground=[("readonly", C["surface_alt"])],
              selectforeground=[("readonly", C["text"])])
    style.configure("TSeparator", background=C["line"])

    # 表格：表头融入表面，不压深底色；行高留白给呼吸感
    style.configure("Treeview", rowheight=row_height(), background=C["card"],
                    fieldbackground=C["card"], foreground=C["text"],
                    bordercolor=C["card"], borderwidth=0, relief="flat",
                    lightcolor=C["card"], darkcolor=C["card"], font=(FONT, 10))
    style.map("Treeview",
              background=[("selected", C["select"])],
              foreground=[("selected", C["text"])])
    style.configure("Treeview.Heading", font=(FONT, 9, "bold"), foreground=C["sub"],
                    background=C["card"], padding=(10, 8), relief="flat",
                    borderwidth=0)
    style.map("Treeview.Heading",
              background=[("active", C["card"])],
              foreground=[("active", C["text"])])

    # 滚动条
    style.configure("Vertical.TScrollbar", background=C["scrollbar"],
                    troughcolor=C["bg"], bordercolor=C["bg"], arrowcolor=C["sub"],
                    gripcount=0, borderwidth=0)
    style.configure("Horizontal.TScrollbar", background=C["scrollbar"],
                    troughcolor=C["bg"], bordercolor=C["bg"], arrowcolor=C["sub"],
                    gripcount=0, borderwidth=0)
    style.map("Vertical.TScrollbar",
              background=[("active", C["muted"]), ("pressed", C["primary"])])
    style.map("Horizontal.TScrollbar",
              background=[("active", C["muted"]), ("pressed", C["primary"])])

    # 单选项（岗位切换备用）
    style.configure("TRadiobutton", background=C["sidebar"], foreground=C["muted"],
                    font=(FONT, 11), indicatorcolor=C["card"],
                    indicatorrelief="flat", focuscolor=C["primary"])
    style.map("TRadiobutton",
              background=[("active", C["sidebar"])],
              foreground=[("selected", C["primary"])],
              indicatorcolor=[("selected", C["primary"])])

    return style
