# -*- coding: utf-8 -*-
"""文件预览缩略图：交给 Windows Shell 生成，不引入 PDF 渲染库。

Shell 对图片、PDF、Office 文档通常会返回资源管理器同款缩略图；
取不到时返回 None，界面退回「用系统打开」。
"""

import ctypes
import os
import sys


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", ctypes.c_ushort), ("bmBitsPixel", ctypes.c_ushort),
                ("bmBits", ctypes.c_void_p)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort),
                ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint),
                ("biSizeImage", ctypes.c_uint), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint),
                ("biClrImportant", ctypes.c_uint)]


def _factory():
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        ole32.CoInitialize.restype = ctypes.c_long
        ole32.CoInitialize.argtypes = [ctypes.c_void_p]
        shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
        shell32.SHCreateItemFromParsingName.argtypes = [
            ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(_GUID),
            ctypes.POINTER(ctypes.c_void_p)]
        gdi32.GetObjectW.restype = ctypes.c_int
        gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_void_p]
        gdi32.GetDIBits.restype = ctypes.c_int
        gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_uint, ctypes.c_uint,
                                    ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_uint]
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        user32.GetDC.restype = ctypes.c_void_p
        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        return ole32, shell32, gdi32, user32, wintypes
    except Exception:
        return None


def shell_thumbnail(path, size=260):
    """返回 Pillow RGB 图；不可用 / 取不到时返回 None。"""
    api = _factory()
    if api is None or not str(path or "").strip():
        return None
    if not os.path.isfile(path):
        return None
    ole32, shell32, gdi32, user32, wintypes = api
    try:
        ole32.CoInitialize(None)
    except Exception:
        pass

    iid = _GUID(0xBCC18B79, 0xBA16, 0x442F,
                (ctypes.c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59,
                                     0xC3, 0x0C, 0x46, 0x3B))
    item = ctypes.c_void_p()
    try:
        hr = shell32.SHCreateItemFromParsingName(
            os.path.abspath(path), None, ctypes.byref(iid), ctypes.byref(item))
        if hr != 0 or not item:
            return None
        vtbl = ctypes.cast(item, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, _SIZE,
                                       ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_void_p))(vtbl[0][3])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[0][2])
        hbm = ctypes.c_void_p()
        ask = _SIZE(int(size), int(size))
        hr = get_image(item, ask, 0x1, ctypes.byref(hbm))  # BIGGERSIZEOK
        release(item)
        item = ctypes.c_void_p()
        if hr != 0 or not hbm:
            return None

        bm = _BITMAP()
        if not gdi32.GetObjectW(hbm, ctypes.sizeof(_BITMAP), ctypes.byref(bm)):
            gdi32.DeleteObject(hbm)
            return None
        w, h = int(bm.bmWidth), int(bm.bmHeight)
        if w <= 0 or h <= 0 or w > 4096 or h > 4096:
            gdi32.DeleteObject(hbm)
            return None
        hdc = user32.GetDC(None)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = (ctypes.c_ubyte * (w * h * 4))()
        ok = gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(bmi), 0)
        user32.ReleaseDC(None, hdc)
        gdi32.DeleteObject(hbm)
        if not ok:
            return None
        from PIL import Image
        return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).copy()
    except Exception:
        try:
            if item:
                vtbl = ctypes.cast(item, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[0][2])(item)
        except Exception:
            pass
        return None
