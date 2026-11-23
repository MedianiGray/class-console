# -*- coding: utf-8 -*-
"""Windows 原生文件拖入：不引入 tkdnd，直接用 WM_DROPFILES。

只在 Windows 上启用；其他系统或注册失败时返回 False，界面仍保留
「选择文件登记」入口。回调统一在主线程 after(0) 执行，避免在窗口过程里
重入 Tk。
"""

import ctypes
import sys

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
_state = {}


def _win():
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        user32.GetParent.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                           wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragFinish.argtypes = [wintypes.HANDLE]
        user32.CallWindowProcW.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                           wintypes.UINT, wintypes.WPARAM,
                                           wintypes.LPARAM]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             ctypes.c_void_p]
        return user32, shell32, wintypes
    except Exception:
        return None


def enable_drop(root, callback):
    """让主窗口接受拖入文件；返回是否注册成功。"""
    api = _win()
    if api is None:
        return False
    user32, shell32, wintypes = api
    try:
        top = root.winfo_toplevel()
        parent = user32.GetParent(top.winfo_id()) or top.winfo_id()
        hwnd = wintypes.HWND(parent)
        shell32.DragAcceptFiles(hwnd, True)
    except Exception:
        return False

    proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM)

    def _proc(hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            paths = []
            try:
                count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                for i in range(int(count or 0)):
                    length = shell32.DragQueryFileW(wparam, i, None, 0)
                    buf = ctypes.create_unicode_buffer(int(length) + 1)
                    shell32.DragQueryFileW(wparam, i, buf, int(length) + 1)
                    if buf.value:
                        paths.append(buf.value)
            except Exception:
                paths = []
            finally:
                try:
                    shell32.DragFinish(wparam)
                except Exception:
                    pass
            if paths:
                try:
                    root.after(0, lambda: callback(paths))
                except Exception:
                    pass
            return 0
        try:
            return user32.CallWindowProcW(_state.get("old"), hwnd, msg,
                                          wparam, lparam)
        except Exception:
            return 0

    callback_ref = proc_type(_proc)
    try:
        old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC,
                                       ctypes.cast(callback_ref, ctypes.c_void_p))
        if not old:
            return False
    except Exception:
        return False
    _state.update({"hwnd": hwnd, "old": ctypes.c_void_p(old),
                   "proc": callback_ref, "root": root})
    return True
