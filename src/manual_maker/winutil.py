"""Win32 ヘルパー（ctypes のみ使用）。"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
kernel32.GetConsoleWindow.restype = wintypes.HWND

GA_ROOT = 2
GA_ROOTOWNER = 3
DWMWA_EXTENDED_FRAME_BOUNDS = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def union(self, other: Rect) -> Rect:
        return Rect(
            min(self.left, other.left),
            min(self.top, other.top),
            max(self.right, other.right),
            max(self.bottom, other.bottom),
        )

    def intersect(self, other: Rect) -> Rect:
        return Rect(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )


def set_dpi_aware() -> None:
    """物理ピクセル座標に統一する（pynput / mss / Win32 の座標系を揃える）。"""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()


def window_from_point(x: int, y: int) -> int | None:
    hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return None
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def foreground_window() -> int | None:
    return user32.GetForegroundWindow() or None


def root_owner(hwnd: int) -> int:
    return user32.GetAncestor(hwnd, GA_ROOTOWNER) or hwnd


def window_rect(hwnd: int) -> Rect:
    """見えない枠を除いた実際のウィンドウ矩形。"""
    r = wintypes.RECT()
    hr = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)
    )
    if hr != 0:
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return Rect(r.left, r.top, r.right, r.bottom)


def window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, n + 1)
    return buf.value


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def process_name(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def app_process_name(hwnd: int) -> str:
    """UWP アプリ（ApplicationFrameHost 配下）は実体のプロセス名を返す。"""
    pid = window_pid(hwnd)
    name = process_name(pid)
    if name.lower() != "applicationframehost.exe":
        return name
    found: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(child, _):
        cpid = window_pid(child)
        if cpid != pid:
            found.append(process_name(cpid))
            return False
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), cb, 0)
    return found[0] if found and found[0] else name


def print_window(hwnd: int):
    """他のウィンドウに隠れていてもウィンドウ内容を取得する（PrintWindow）。PIL Image を返す。"""
    from PIL import Image

    gdi32 = ctypes.WinDLL("gdi32")
    full = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(full))
    w, h = full.right - full.left, full.bottom - full.top
    if w <= 0 or h <= 0:
        return None
    hdc_win = user32.GetWindowDC(wintypes.HWND(hwnd))
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(hdc_mem, bmp)
    try:
        PW_RENDERFULLCONTENT = 2
        if not user32.PrintWindow(wintypes.HWND(hwnd), hdc_mem, PW_RENDERFULLCONTENT):
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
            ]

        bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(hdc_mem, bmp, 0, h, buf, ctypes.byref(bih), 0)
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(wintypes.HWND(hwnd), hdc_win)
    # 見えない枠を除いた範囲に切り抜く
    r = window_rect(hwnd)
    return img.crop((r.left - full.left, r.top - full.top, r.right - full.left, r.bottom - full.top))


def console_window() -> int | None:
    return kernel32.GetConsoleWindow() or None


def virtual_screen() -> Rect:
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return Rect(x, y, x + w, y + h)


def monitor_rect_at(x: int, y: int) -> Rect:
    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    hmon = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    r = info.rcMonitor
    return Rect(r.left, r.top, r.right, r.bottom)
