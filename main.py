#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
屏幕 OCR 客户端（全屏一键识别，离线）
====================================
- 全局快捷键触发全屏 OCR，结果自动复制到剪贴板（一键复制全部）。
- 弹出原生结果窗口：可鼠标框选部分文字后 Ctrl+C 进行“选择复制”；
  也可点“复制全部”按钮复制整段。
- ESC 退出程序。
- 全程离线，不依赖任何云端 API。OCR 引擎使用 RapidOCR（ONNX 推理）。

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
    print(f"[提示] 未检测到 pywin32（{_e}），结果将输出到控制台。")

# ===================== 配置区 =====================
HOTKEY = "<ctrl>+<alt>+o"   # 识别快捷键
EXIT_KEY = "<esc>"          # 退出快捷键
MONITOR = 1                 # 1 = 主显示器；0 = 全部显示器（拼接大图，较慢）
AUTO_COPY_ALL = True        # OCR 后自动复制全部到剪贴板（一键复制全部）
SHOW_WINDOW = True          # 是否弹出结果窗口（支持框选复制）
# =================================================

_engine = None
_lock = threading.Lock()


def get_engine():
    """懒加载 RapidOCR 引擎（模型随包内置，离线）。"""
    global _engine
    if _engine is None:
        print("[初始化] 加载 OCR 模型…")
        _engine = RapidOCR()
        print("[初始化] 模型就绪。")
    return _engine


def capture_screen(monitor_index):
    """用 mss 抓取指定显示器，返回 BGR 的 numpy 数组。"""
    with mss.mss() as sct:
        mon = sct.monitors[monitor_index]
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
        self.full_text = text
        if not (HAS_WIN32 and self.ready):
            print("---- OCR 结果（可框选复制）----")
            print(text)
            print("--------------------------------")
            return
        try:
            win32gui.SendMessage(self.edit, win32con.WM_SETTEXT, 0, text)
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


# ----------------- 核心逻辑 -----------------
def do_ocr():
    if not _lock.acquire(blocking=False):
        return  # 上一轮还在跑，忽略重复触发
    try:
        t0 = time.time()
        img = capture_screen(MONITOR)
        engine = get_engine()
        result, _ = engine(img)
        text = "\n".join([line[1] for line in result if line[1]]) if result else ""

        if text.strip():
            if AUTO_COPY_ALL:
                pyperclip.copy(text)
            dt = (time.time() - t0) * 1000
            print(f"[OCR] 识别 {len(result)} 行，用时 {dt:.0f}ms"
                  + ("，已复制全部到剪贴板。" if AUTO_COPY_ALL else "。"))
            if SHOW_WINDOW:
                result_win.show(text)
        else:
            print("[OCR] 未识别到文字。")
    except Exception as e:
        print(f"[OCR] 出错: {e}")
    finally:
        _lock.release()


def on_activate_ocr():
    threading.Thread(target=do_ocr, daemon=True).start()


def on_activate_exit():
    print("\n[退出] 收到 ESC，正在关闭…")
    os._exit(0)


def main():
    print("=" * 46)
    print("  屏幕 OCR 客户端（全屏一键识别 · 离线）")
    print("=" * 46)
    print(f"  识别快捷键 : {HOTKEY}")
    print(f"  退出快捷键 : {EXIT_KEY}")
    print(f"  识别范围   : {'全部显示器' if MONITOR == 0 else '主显示器'}")
    print(f"  自动复制全部 : {'开' if AUTO_COPY_ALL else '关'}")
    print(f"  结果窗口   : {'开' if SHOW_WINDOW and HAS_WIN32 else '关(控制台)'}")
    print("  按快捷键识别；结果窗口可框选复制或点'复制全部'；ESC 退出。")
    print("=" * 46)

    threading.Thread(target=ui_loop, daemon=True).start()

    hotkeys = keyboard.GlobalHotKeys({
        HOTKEY: on_activate_ocr,
        EXIT_KEY: on_activate_exit,
    })
    try:
        hotkeys.run()  # 阻塞，直到被 stop / 进程退出
    except KeyboardInterrupt:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
