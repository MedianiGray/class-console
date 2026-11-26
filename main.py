# -*- coding: utf-8 -*-
"""班级操作台 · 本地桌面版 入口。

运行：python main.py
打包 exe：在 Windows 上执行 build_exe.bat（详见说明.txt）。
"""

import sys
import os
import time
import ctypes
import traceback
import datetime
import tkinter as tk
from tkinter import messagebox

# 数据层与界面层在「品牌加载页已经画出来之后」再导入：
# 这两个模块连同 pathlib/json 约 70–120ms 的导入时间可以落到用户已经看到反馈之后。
import theme
from version import VERSION, VERSION_LABEL

CRASH_LOG_NAME = "crash.log"
_TRACE_FILE = os.environ.get("CC_STARTUP_TRACE")
_TRACE_T0 = time.perf_counter()


def _trace(label):
    """仅当设置 CC_STARTUP_TRACE 时记录启动分段，正常启动不写文件。"""
    if not _TRACE_FILE:
        return
    try:
        with open(_TRACE_FILE, "a", encoding="utf-8") as f:
            f.write("%.0f\t%s\n" % ((time.perf_counter() - _TRACE_T0) * 1000, label))
    except OSError:
        pass


def _show_loading_shell(root):
    """在数据与界面构建期间先画出一行品牌占位，避免双击后长时间无反馈。

    这里只用一个 Label：每多一档字号都要多一次字体解析，首帧的时间要留给主窗口。
    """
    root.configure(bg="#EDF0F5")
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    win_w = min(1220, max(960, sw - 80))
    win_h = min(860, max(620, sh - 70))
    root.geometry("%dx%d+%d+%d" % (win_w, win_h,
                                   max(0, (sw - win_w) // 2),
                                   max(0, (sh - win_h) // 3)))
    label = tk.Label(root, text="班级操作台\n正在打开本地工作台…",
                     bg="#EDF0F5", fg="#33404F",
                     font=(theme.FONT, 12, "bold"), justify="center")
    label.place(relx=0.5, rely=0.45, anchor="center")
    root.update_idletasks()
    root.update()
    _trace("loading-shell-painted")
    return label



def crash_log_path():
    from database import app_data_dir
    return app_data_dir() / CRASH_LOG_NAME


def record_crash(exc_type, exc, tb):
    """写本机 crash.log，返回路径；写失败时返回空串并保留 stderr。"""
    try:
        log = crash_log_path()
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n===== %s =====\n" %
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            traceback.print_exception(exc_type, exc, tb, file=f)
        return log
    except Exception as e:
        print("写 crash.log 失败：%s" % type(e).__name__, file=sys.stderr)
        return ""


def export_crash_log(parent, path=None):
    """让用户把 crash.log 另存到桌面等位置；成功返回目标路径。"""
    from tkinter import filedialog
    import shutil
    src = path or crash_log_path()
    try:
        if not src.exists():
            messagebox.showinfo("没有崩溃日志", "当前没有记录到崩溃日志。",
                                parent=parent)
            return ""
        dest = filedialog.asksaveasfilename(
            parent=parent, title="导出崩溃日志", defaultextension=".log",
            initialfile="class-console-crash-%s.log" %
                        datetime.date.today().strftime("%Y-%m-%d"),
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt")])
        if not dest:
            return ""
        shutil.copyfile(str(src), dest)
        return dest
    except OSError as e:
        messagebox.showerror("导出失败",
                             "未能写出日志文件：%s" % type(e).__name__,
                             parent=parent)
        return ""


def _show_unhandled(root, path):
    """未捕获异常的统一交代；不向界面暴露堆栈与路径。"""
    try:
        from ui_error import show_error
        show_error(
            root, "这一步没有完成",
            "界面操作执行时出错，细节已写入本机崩溃日志。",
            "当前这一步没有完成；已经保存的数据不会回滚，但出错前的这次改动可能没写入。",
            "先用其他页面继续，并导出一次备份；把崩溃日志发给维护者定位。",
            "关闭程序后重新打开，原数据库仍保留在本机数据目录；日志不会上传。",
            actions=[
                ("导出崩溃日志", lambda: export_crash_log(root, path)),
                ("继续使用", lambda: None),
            ])
    except Exception as e:
        messagebox.showerror(
            "这一步没有完成",
            "发生了什么：界面操作执行时出错，细节已写入本机崩溃日志。\n"
            "影响范围：当前这一步没有完成，已保存的数据不会回滚。\n"
            "下一步：继续用其他页面并导出备份，再把崩溃日志发给维护者。\n"
            "兜底：关闭后重新打开，原数据库仍在本机；日志不会上传。",
            parent=root if root else None)
        print("错误对话框显示失败：%s" % type(e).__name__, file=sys.stderr)


def _install_error_logger(root=None):
    """未捕获异常写 crash.log，并尽量给用户一个可操作的出口。"""
    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        path = record_crash(exc_type, exc, tb)
        if root is not None:
            try:
                root.after(0, lambda: _show_unhandled(root, path))
            except Exception as e:
                print("错误提示排队失败：%s" % type(e).__name__, file=sys.stderr)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook

    if root is not None:
        def tk_hook(exc_type, exc, tb):
            path = record_crash(exc_type, exc, tb)
            _show_unhandled(root, path)
        root.report_callback_exception = tk_hook


def enable_dpi_awareness():
    """声明 DPI 感知，避免 125%/150% 缩放下 Tk 按 100% 排布导致右侧被裁。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def center_window(root, w, h):
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 3)
    root.geometry("%dx%d+%d+%d" % (w, h, x, y))


def main():
    _trace("main-enter")
    enable_dpi_awareness()
    theme.init_from_settings()
    root = tk.Tk()
    root.title("班级操作台 · 正在打开…")
    _install_error_logger(root)
    try:
        from database import build_repository
        import database
        from ui_main import MainWindow
        # 过渡窗仍然保留：它先把窗口与字体栈热身一遍，主窗首帧反而更便宜（实测省 20–40ms），
        # 也保证首次建库时用户不至于对着空白桌面等 1.6 秒。
        loading = _show_loading_shell(root)
        _trace("imports-ready")
        repo = build_repository()
        _trace("repository-ready")
        # 分帧启动：先只建顶栏/侧栏骨架/标题/状态栏，首帧立即可见；导航与视图随后补。
        win = MainWindow(root, repo, staged=True, trace=_trace)
        _trace("window-shell-built")
        if loading is not None:
            loading.destroy()
        root.title("班级操作台 · v%s %s" % (VERSION, VERSION_LABEL))
        issue = getattr(database, "LAST_STARTUP_ISSUE", None)
        if issue:
            root.after(120, lambda: _show_startup_issue(root, issue))
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        center_window(root, min(1220, max(960, sw - 80)),
                      min(860, max(620, sh - 70)))
        root.minsize(960, 640)
        root.update_idletasks()
        root.update()
        _trace("window-shell-painted")
        # 外壳已经在屏幕上，再补页头、导航与当前视图；顶栏右侧与新手引导卡留到第三帧。
        def _finish_startup():
            _trace("content-start")
            win.finish_shell()
            root.update_idletasks()
            win.start_content()
            _trace("content-ready")
            _mark_content_ready()
            root.after(1, _finish_extras)

        def _finish_extras():
            """第三帧：低频控件与新手引导卡，晚一步不影响主内容可用。"""
            win.finish_shell_extras()
            root.update_idletasks()
            _trace("extras-ready")

        def _mark_content_ready():
            """仅性能测试用：CC_STARTUP_READY_FILE 存在时落一个标记，便于外部计时。"""
            path = os.environ.get("CC_STARTUP_READY_FILE")
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("%.0f\n" % ((time.perf_counter() - _TRACE_T0) * 1000))
            except OSError:
                pass

        root.after(1, _finish_startup)
        root.mainloop()
    except Exception as e:
        path = record_crash(type(e), e, e.__traceback__)
        messagebox.showerror(
            "启动失败",
            "发生了什么：程序初始化没有完成，常见原因是本机数据目录不可读写。\n"
            "影响范围：本次没有打开工作台；原有数据库文件没有被删除。\n"
            "下一步：检查数据目录权限或换一个可写位置，再重新打开。\n"
            "兜底：崩溃日志已写入本机（%s）；原数据库仍保留，可先复制留底。"
            % (CRASH_LOG_NAME if path else "写入失败，未生成日志"),
            parent=root)
        raise SystemExit(1)


def _show_startup_issue(root, issue):
    """数据库隔离重建后的开机说明；只显示一次。"""
    from ui_error import show_error
    show_error(
        root, "本机数据库曾无法读取",
        getattr(issue, "what", "启动时发现数据库无法读取。"),
        getattr(issue, "impact",
                "程序已隔离原文件并新建空库；原数据没有被删除。"),
        getattr(issue, "next_step",
                "先到数据目录确认隔离文件，再决定是否恢复旧库或从备份导入。"),
        getattr(issue, "fallback",
                "当前空库可以继续用；导入备份前不要覆盖隔离文件。"),
        actions=[("继续使用", lambda: None)])


if __name__ == "__main__":
    main()
