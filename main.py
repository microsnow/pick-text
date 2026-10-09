#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
屏幕 OCR 客户端（全屏一键识别 + 区域多选识别，离线）
=================================================
两种识别模式（均离线，OCR 引擎使用 RapidOCR / ONNX 推理）：

1) 全屏识别（默认快捷键 Ctrl+Alt+O）
   - 抓取整个屏幕，识别其中全部文字，自动复制到剪贴板。
   - 弹出原生结果窗口：可鼠标框选部分文字后 Ctrl+C 进行“选择复制”；
     也可点“复制全部”按钮复制整段。

2) 区域选择识别（默认快捷键 Ctrl+Alt+R）★新增
   - 屏幕变暗，鼠标左键拖拽即可框选一个区域；可多次拖拽框选多个区域。
- 右键 / Enter 确认：仅识别各区域中的内容，多个区域之间用换行隔开。
- 再次按 Ctrl+Alt+R 重选/取消本次选择；ESC 取消选区（不退出程序）。

依赖：mss / rapidocr-onnxruntime / pynput / pyperclip / numpy / pywin32

运行（在隔离 venv 中）：
    python main.py
"""

import os
import sys
import time
import threading

import numpy as np
import mss
import pyperclip
from pynput import keyboard
from rapidocr_onnxruntime import RapidOCR

try:
    import win32gui
    import win32con
    import win32api
    HAS_WIN32 = True
except Exception as _e:  # 无 pywin32 时退回控制台输出
    HAS_WIN32 = False
    print(f"[提示] 未检测到 pywin32（{_e}），区域选择等 GUI 功能将不可用。")

# ===================== 配置区 =====================
HOTKEY = "<ctrl>+<alt>+o"   # 全屏识别快捷键
REGION_HOTKEY = "<ctrl>+<alt>+r"  # 区域选择识别快捷键（可多选区域）
EXIT_KEY = "<esc>"          # 退出快捷键
MONITOR = 1                 # 1 = 主显示器；0 = 全部显示器（拼接大图，较慢）
AUTO_COPY_ALL = True        # OCR 后自动复制全部到剪贴板（一键复制全部）
SHOW_WINDOW = True          # 是否弹出结果窗口（支持框选复制）
REGION_ALPHA = 160          # 区域选择遮罩的暗化不透明度（0-255，越大越暗）
# =================================================

# 给界面显示用的人类可读快捷键
def _pretty(hk):
    return (hk.replace("<ctrl>", "Ctrl")
             .replace("<alt>", "Alt")
             .replace("<shift>", "Shift")
             .replace("<esc>", "Esc")
             .replace("+", "+"))

HOTKEY_PRETTY = _pretty(HOTKEY)
REGION_HOTKEY_PRETTY = _pretty(REGION_HOTKEY)
EXIT_KEY_PRETTY = _pretty(EXIT_KEY)


def _crlf(s):
    """统一转为 Windows 换行符 CRLF（幂等）。

    原生 EDIT 控件与 Windows 剪贴板均以 CRLF 为换行标准：仅用 LF(\\n) 时，
    复制框不显示换行、且粘贴到部分应用会多/少换行。本函数先把已有 CRLF 规整为
    LF 再统一转 CRLF，可重复调用不产生双重换行。
    """
    return s.replace("\r\n", "\n").replace("\n", "\r\n")


def _is_cjk(ch):
    """判断字符是否为中日韩/全角字符（用于同行的相邻片段是否补空格）。"""
    if not ch:
        return False
    o = ord(ch)
    return (0x2E80 <= o <= 0x9FFF) or (0xAC00 <= o <= 0xD7A3) \
        or (0xF900 <= o <= 0xFAFF) or (0xFE30 <= o <= 0xFE4F) \
        or (0xFF00 <= o <= 0xFFEF)

if HAS_WIN32:
    WM_REGION_CANCEL = win32con.WM_APP + 1  # 用于“再次按快捷键取消”的自定义消息

_engine = None
_lock = threading.Lock()

# 当前活动的区域选择器（供全局热键“取消”使用）
region_sel = None

# 每次区域选择用唯一窗口类名，避免“类已存在”(1410)——类一旦注册会常驻进程，
# 第二次 RegisterClass 使用相同名字即报错。用自增计数器保证名称唯一。
_region_class_seq = 0


def _next_region_class_name():
    global _region_class_seq
    _region_class_seq += 1
    return "OCRRegionSel_%d" % _region_class_seq


def get_engine():
    """懒加载 RapidOCR 引擎（模型随包内置，离线）。"""
    global _engine
    if _engine is None:
        print("[初始化] 加载 OCR 模型…")
        _engine = RapidOCR()
        print("[初始化] 模型就绪。")
    return _engine


def get_monitor(index):
    """返回 mss 的显示器字典 {left, top, width, height}（绝对坐标）。"""
    with mss.MSS() as sct:
        return sct.monitors[index]


def capture_screen(monitor_index):
    """用 mss 抓取指定显示器，返回 BGR 的 numpy 数组。"""
    with mss.MSS() as sct:
        mon = sct.monitors[monitor_index]
        shot = sct.grab(mon)
        arr = np.frombuffer(shot.bgra, dtype=np.uint8)
        arr = arr.reshape((shot.height, shot.width, 4))
        return arr[:, :, :3]  # BGR


def grab_monitor(mon):
    """用 mss 抓取指定显示器字典，返回 BGR 的 numpy 数组。"""
    with mss.MSS() as sct:
        shot = sct.grab(mon)
        arr = np.frombuffer(shot.bgra, dtype=np.uint8)
        arr = arr.reshape((shot.height, shot.width, 4))
        return arr[:, :, :3]  # BGR


# ----------------- 原生结果窗口（无 tkinter 依赖） -----------------
class ResultWindow:
    def __init__(self):
        self.hwnd = None
        self.edit = None
        self.full_text = ""
        self.ready = False
        self._inst = None
        self._atom = None

    def build(self):
        if not HAS_WIN32:
            return
        self._inst = win32api.GetModuleHandle(None)
        wc = win32gui.WNDCLASS()
        wc.hInstance = self._inst
        wc.lpszClassName = "OCRResultWnd"
        wc.lpfnWndProc = self._wndproc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_BTNFACE + 1
        self._atom = win32gui.RegisterClass(wc)

        cx = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        x = max(0, cx - 600)
        y = 40
        self.hwnd = win32gui.CreateWindow(
            self._atom,
            "OCR 结果 - 框选后 Ctrl+C 复制 / 点'复制全部'",
            win32con.WS_OVERLAPPEDWINDOW & ~win32con.WS_THICKFRAME & ~win32con.WS_MAXIMIZEBOX,
            x, y, 580, 400,
            0, 0, self._inst, None,
        )
        self.edit = win32gui.CreateWindow(
            "EDIT", "",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_BORDER
            | win32con.WS_VSCROLL | win32con.ES_MULTILINE
            | win32con.ES_AUTOVSCROLL | win32con.ES_WANTRETURN,
            10, 10, 560, 320, self.hwnd, 1, self._inst, None,
        )
        # 中文可读字体（失败则退回系统默认）
        try:
            lf = win32gui.LOGFONT()
            lf.lfHeight = -16
            lf.lfFaceName = "Microsoft YaHei"
            hf = win32gui.CreateFontIndirect(lf)
            win32gui.SendMessage(self.edit, win32con.WM_SETFONT, hf, 1)
        except Exception:
            pass
        win32gui.CreateWindow(
            "BUTTON", "复制全部",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            10, 340, 160, 34, self.hwnd, 2, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "关闭",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            180, 340, 160, 34, self.hwnd, 3, self._inst, None,
        )
        win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        self.ready = True

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_COMMAND:
            ctrl_id = wparam & 0xFFFF
            if ctrl_id == 2:          # “复制全部”按钮
                if self.full_text:
                    pyperclip.copy(self.full_text)
                    print("[OCR] 已复制全部到剪贴板。")
            elif ctrl_id == 3:        # “关闭”按钮
                win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
            return 0
        if msg == win32con.WM_CLOSE:  # 点标题栏 X：隐藏而非销毁
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def show(self, text):
        self.full_text = _crlf(text)
        if not (HAS_WIN32 and self.ready):
            print("---- OCR 结果（可框选复制）----")
            print(text)
            print("--------------------------------")
            return
        try:
            win32gui.SendMessage(self.edit, win32con.WM_SETTEXT, 0, self.full_text)
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
            win32gui.SetWindowPos(
                self.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )
            try:
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:
                pass
        except Exception as e:
            print(f"[UI] 显示窗口失败，退回控制台: {e}")
            print(text)

    def hide(self):
        if HAS_WIN32 and self.hwnd:
            try:
                win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
            except Exception:
                pass


result_win = ResultWindow()


def ui_loop():
    """在独立线程中构建并泵消息，保证窗口可交互。"""
    if not HAS_WIN32:
        return
    try:
        result_win.build()
        win32gui.PumpMessages()
    except Exception as e:
        print(f"[UI] 窗口线程异常: {e}")
        result_win.ready = False


# ----------------- 区域选择遮罩（多选区域） -----------------
class RegionSelector:
    """全屏暗化遮罩，鼠标拖拽框选多个矩形区域。

    交互：
      - 左键拖拽：新增一个区域（可多次拖拽，支持多选）
      - 右键 / Enter：确认，返回所有区域
      - Backspace：撤销上一个区域（需窗口获得焦点）
      - 再次按区域快捷键 / 自定义取消消息：放弃本次选择
      - ESC：退出整个程序（全局快捷键）
    区域坐标以“显示器左上角”为原点（与 mss 抓取坐标一致）。
    """

    def __init__(self):
        self.hwnd = None
        self.mon = None
        self.rects = []          # 已确认的区域 (x, y, w, h)，显示器相对坐标
        self.cur = None          # 正在拖拽的区域 (x, y, w, h)
        self.start = None        # 拖拽起点 (x, y)
        self.drawing = False
        self.confirmed = False
        self._inst = None
        self._atom = None
        self._class_name = None

    def _build(self, mon):
        self._inst = win32api.GetModuleHandle(None)
        wc = win32gui.WNDCLASS()
        wc.hInstance = self._inst
        wc.lpszClassName = _next_region_class_name()
        self._class_name = wc.lpszClassName
        wc.lpfnWndProc = self._wndproc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_CROSS)
        wc.hbrBackground = win32con.COLOR_WINDOW + 1
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        self._atom = win32gui.RegisterClass(wc)

        ex_style = win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST
        self.hwnd = win32gui.CreateWindowEx(
            ex_style, self._atom,
            "区域选择 - 拖拽框选 / 右键确认 / 再次按快捷键取消",
            win32con.WS_POPUP,
            mon["left"], mon["top"], mon["width"], mon["height"],
            0, 0, self._inst, None,
        )
        # 整窗统一半透明暗化（仅暗化，区域由 GDI 画亮色边框标识）
        win32gui.SetLayeredWindowAttributes(
            self.hwnd, 0, REGION_ALPHA, win32con.LWA_ALPHA
        )

    def _confirm(self):
        self.confirmed = True
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        except Exception:
            pass
        win32gui.PostQuitMessage(0)

    def _cancel(self):
        self.confirmed = False
        self.rects = []
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        except Exception:
            pass
        win32gui.PostQuitMessage(0)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_ERASEBKGND:
            # 我们自己用 FillRect 画暗化背景，跳过系统默认擦除，避免闪烁
            return 1
        if msg == WM_REGION_CANCEL:
            self._cancel()
            return 0
        if msg == win32con.WM_LBUTTONDOWN:
            x = win32api.LOWORD(lparam)
            y = win32api.HIWORD(lparam)
            self.start = (x, y)
            self.cur = (x, y, 0, 0)
            self.drawing = True
            win32gui.SetCapture(hwnd)
            return 0
        if msg == win32con.WM_MOUSEMOVE:
            if self.drawing and self.start:
                x = win32api.LOWORD(lparam)
                y = win32api.HIWORD(lparam)
                x0, y0 = self.start
                self.cur = (min(x0, x), min(y0, y), abs(x - x0), abs(y - y0))
                win32gui.InvalidateRect(hwnd, None, True)
            return 0
        if msg == win32con.WM_LBUTTONUP:
            if self.drawing and self.cur and self.cur[2] > 3 and self.cur[3] > 3:
                self.rects.append(self.cur)
            self.drawing = False
            self.cur = None
            try:
                win32gui.ReleaseCapture()
            except Exception:
                pass
            win32gui.InvalidateRect(hwnd, None, True)
            return 0
        if msg == win32con.WM_RBUTTONDOWN:   # 右键确认
            self._confirm()
            return 0
        if msg == win32con.WM_KEYDOWN:
            vk = wparam
            if vk == 13:            # Enter 确认
                self._confirm()
            elif vk == 8:           # Backspace 撤销上一个区域
                if self.rects:
                    self.rects.pop()
                win32gui.InvalidateRect(hwnd, None, True)
            return 0
        if msg == win32con.WM_PAINT:
            self._paint(hwnd)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _paint(self, hwnd):
        if self.mon is None:
            return
        hdc, ps = win32gui.BeginPaint(hwnd)
        w = self.mon["width"]
        h = self.mon["height"]
        # 暗化背景
        brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
        win32gui.FillRect(hdc, (0, 0, w, h), brush)
        win32gui.DeleteObject(brush)
        # 已确认区域：亮蓝边框
        pen = win32gui.CreatePen(win32con.PS_SOLID, 3, win32api.RGB(0, 191, 255))
        old = win32gui.SelectObject(hdc, pen)
        for r in self.rects:
            win32gui.Rectangle(hdc, r[0], r[1], r[0] + r[2], r[1] + r[3])
        win32gui.SelectObject(hdc, old)
        win32gui.DeleteObject(pen)
        # 正在拖拽的区域：金色边框
        if self.cur:
            p2 = win32gui.CreatePen(win32con.PS_SOLID, 2, win32api.RGB(255, 215, 0))
            o2 = win32gui.SelectObject(hdc, p2)
            win32gui.Rectangle(
                hdc, self.cur[0], self.cur[1],
                self.cur[0] + self.cur[2], self.cur[1] + self.cur[3],
            )
            win32gui.SelectObject(hdc, o2)
            win32gui.DeleteObject(p2)
        # 顶部提示栏
        bar_h = 40
        bb = win32gui.CreateSolidBrush(win32api.RGB(20, 20, 20))
        win32gui.FillRect(hdc, (0, 0, w, bar_h), bb)
        win32gui.DeleteObject(bb)
        lf = win32gui.LOGFONT()
        lf.lfHeight = -16
        lf.lfFaceName = "Microsoft YaHei"
        hf = win32gui.CreateFontIndirect(lf)
        oldf = win32gui.SelectObject(hdc, hf)
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
        win32gui.SetTextColor(hdc, win32api.RGB(255, 255, 255))
        hint = (f"已选 {len(self.rects)} 个区域   ·   左键拖拽框选(可多选)   ·   "
                f"右键/Enter 确认   ·   Esc 取消选区   ·   "
                f"再次按 {REGION_HOTKEY_PRETTY} 重选")
        win32gui.DrawText(
            hdc, hint, -1, (0, 0, w, bar_h),
            win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE,
        )
        win32gui.SelectObject(hdc, oldf)
        win32gui.DeleteObject(hf)
        win32gui.EndPaint(hwnd, ps)

    def select(self, mon):
        """构建遮罩并进入消息循环，返回 (confirmed: bool, rects: list)。"""
        self.mon = mon
        self.rects = []
        self.cur = None
        self.drawing = False
        self.confirmed = False
        self._build(mon)
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        win32gui.SetWindowPos(
            self.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
        )
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        win32gui.PumpMessages()  # 阻塞直到 PostQuitMessage
        try:
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
        except Exception:
            pass
        self.hwnd = None
        # 注销窗口类，避免再次触发时 RegisterClass 报“类已存在”(1410)
        try:
            if self._class_name is not None and self._inst is not None:
                win32gui.UnregisterClass(self._class_name, self._inst)
        except Exception:
            pass
        self._class_name = None
        return self.confirmed, self.rects


# ----------------- 核心逻辑 -----------------
def ocr_image(img):
    """对单张 BGR 图像做 OCR，返回换行拼接的文本。

    OCR 检测器有时会把**同一行**文本拆成多个框（如中英文混排处的断点），
    若直接按框逐行输出，会导致一个区域识别出多行。这里先把纵向重叠的框
    归并为“同一行”再拼接，从而保证“一行文字 → 一行输出”，同时不影响
    区域内本来就存在的多行（不同行纵向不重叠，仍各自成行）。
    """
    engine = get_engine()
    result, _ = engine(img)
    if not result:
        return ""

    # 收集每个检测框：x0, x1, y0, y1, text
    items = []
    for line in result:
        box, text = line[0], line[1]
        if not text or not text.strip():
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        items.append((min(xs), max(xs), min(ys), max(ys), text))
    if not items:
        return ""

    # 按纵向位置归并为“行”
    items.sort(key=lambda t: t[2])  # 按 y_top
    rows = []
    for it in items:
        x0, x1, y0, y1, text = it
        h = max(1.0, y1 - y0)
        placed = False
        for row in rows:
            ry0 = min(r[2] for r in row)
            ry1 = max(r[3] for r in row)
            rh = max(1.0, ry1 - ry0)
            inter = min(ry1, y1) - max(ry0, y0)
            # 纵向重叠超过较矮框高度的一半 → 判为同一行
            if inter > 0.5 * min(h, rh):
                row.append(it)
                placed = True
                break
        if not placed:
            rows.append([it])

    # 每行内按 x 从左到右拼接；行间按行首 y 从上到下输出
    rows.sort(key=lambda row: min(r[2] for r in row))
    lines = []
    for row in rows:
        row.sort(key=lambda t: t[0])
        merged = ""
        for (x0, x1, y0, y1, text) in row:
            if not merged:
                merged = text
            else:
                sep = "" if (_is_cjk(merged[-1]) or _is_cjk(text[0])) else " "
                merged += sep + text
        lines.append(merged)
    return "\n".join(lines)


def do_ocr():
    if not _lock.acquire(blocking=False):
        return  # 上一轮还在跑，忽略重复触发
    try:
        t0 = time.time()
        img = capture_screen(MONITOR)
        text = ocr_image(img)

        if text.strip():
            if AUTO_COPY_ALL:
                pyperclip.copy(_crlf(text))
            dt = (time.time() - t0) * 1000
            print(f"[OCR] 识别 {len(text.splitlines())} 行，用时 {dt:.0f}ms"
                  + ("，已复制全部到剪贴板。" if AUTO_COPY_ALL else "。"))
            if SHOW_WINDOW:
                result_win.show(text)
        else:
            print("[OCR] 未识别到文字。")
    except Exception as e:
        print(f"[OCR] 出错: {e}")
    finally:
        _lock.release()


def do_region_ocr():
    """区域选择模式：框选多个区域，仅识别区域内容，区域间换行隔开。"""
    global region_sel
    if not _lock.acquire(blocking=False):
        return  # 上一轮还在跑，忽略重复触发
    try:
        mon = get_monitor(MONITOR)
        sel = RegionSelector()
        region_sel = sel
        confirmed, rects = sel.select(mon)
        region_sel = None
        if not confirmed or not rects:
            return

        # 隐藏结果窗口，避免被截进屏幕
        result_win.hide()

        t0 = time.time()
        img = grab_monitor(mon)
        ih, iw = img.shape[:2]
        parts = []
        for (x, y, w, h) in rects:
            x0 = max(0, x)
            y0 = max(0, y)
            x1 = min(iw, x + w)
            y1 = min(ih, y + h)
            if x1 <= x0 or y1 <= y0:
                continue
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            t = ocr_image(crop)
            if t.strip():
                parts.append(t)

        # 多个区域的内容以换行隔开
        text = "\n".join(parts)

        if text.strip():
            if AUTO_COPY_ALL:
                pyperclip.copy(_crlf(text))
            dt = (time.time() - t0) * 1000
            n_lines = len(text.splitlines())
            print(f"[区域OCR] {len(rects)} 个区域 → 识别 {n_lines} 行，"
                  f"用时 {dt:.0f}ms"
                  + ("，已复制全部到剪贴板。" if AUTO_COPY_ALL else "。"))
            if SHOW_WINDOW:
                result_win.show(text)
        else:
            print("[区域OCR] 未识别到文字。")
    except Exception as e:
        print(f"[区域OCR] 出错: {e}")
    finally:
        region_sel = None
        _lock.release()


def on_activate_ocr():
    threading.Thread(target=do_ocr, daemon=True).start()


def on_activate_region():
    global region_sel
    if not HAS_WIN32:
        print("[区域] 区域选择模式需要 pywin32（Windows）。已跳过。")
        return
    # 若已有选择在进行，再次按快捷键 = 取消
    if region_sel is not None and region_sel.hwnd:
        win32gui.PostMessage(region_sel.hwnd, WM_REGION_CANCEL, 0, 0)
        return
    threading.Thread(target=do_region_ocr, daemon=True).start()


def on_activate_exit():
    global region_sel
    # 区域选择进行中：ESC 仅取消当前选区、回到待机，不退出程序
    if region_sel is not None and getattr(region_sel, "hwnd", None):
        win32gui.PostMessage(region_sel.hwnd, WM_REGION_CANCEL, 0, 0)
        return
    print("\n[退出] 收到 ESC，正在关闭…")
    os._exit(0)


def main():
    print("=" * 46)
    print("  屏幕 OCR 客户端（全屏 + 区域多选 · 离线）")
    print("=" * 46)
    print(f"  全屏识别   : {HOTKEY_PRETTY}")
    print(f"  区域选择   : {REGION_HOTKEY_PRETTY}（可框选多个区域）")
    print(f"  退出快捷键 : {EXIT_KEY_PRETTY}")
    print(f"  识别范围   : {'全部显示器' if MONITOR == 0 else '主显示器'}")
    print(f"  自动复制全部 : {'开' if AUTO_COPY_ALL else '关'}")
    print(f"  结果窗口   : {'开' if SHOW_WINDOW and HAS_WIN32 else '关(控制台)'}")
    print("  全屏模式：按快捷键识别整屏；区域模式：拖拽框选多区域后右键确认。")
    print("  选区中按 Esc 取消选区；待机按 Esc 退出程序。")
    print("=" * 46)

    threading.Thread(target=ui_loop, daemon=True).start()

    hotkeys = keyboard.GlobalHotKeys({
        HOTKEY: on_activate_ocr,
        REGION_HOTKEY: on_activate_region,
        EXIT_KEY: on_activate_exit,
    })
    try:
        hotkeys.run()  # 阻塞，直到被 stop / 进程退出
    except KeyboardInterrupt:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
