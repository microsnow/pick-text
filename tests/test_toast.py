# -*- coding: utf-8 -*-
"""Toast 提示回归测试（针对两个已修复的缺陷）。

1) 内容可见：Rectangle() 会用 DC 当前画刷填充内部，若不先 SelectObject(NULL_BRUSH)，
   默认白色画刷会覆盖深色底 —— 白字落在白底上，表现为"有框但没内容"。
2) 自动关闭：必须用 PostMessage(hwnd, WM_TIMER)；PostThreadMessage 投递的消息
   hwnd 为 NULL，不会被窗口过程收到，消息循环将永久阻塞 —— toast 不消失。

运行：
    python -m pytest tests/test_toast.py -v
    python tests/test_toast.py          # 无 pytest 时也可直接跑
"""
import os
import re
import sys
import threading
import time

import pytest

import win32api
import win32con
import win32gui

MAIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")

_TOAST_NS = {"win32api": win32api, "win32con": win32con, "win32gui": win32gui,
             "threading": threading, "HAS_WIN32": True,
             "__name__": "toast_under_test"}


def _load_toast_module():
    """抽取 main.py 中的 Toast 相关源码执行，避免导入 rapidocr 等重依赖。"""
    src = open(MAIN, encoding="utf-8").read()
    seq = src[src.index("# Toast 窗口类名自增"):
              src.index("# ----------------- 选区预设存储")]
    body = src[src.index("# ----------------- 轻量 Toast 提示"):
               src.index("# ----------------- 核心逻辑 -----------------")]
    ns = dict(_TOAST_NS)
    exec(compile(seq + body, "<toast>", "exec"), ns)
    return ns


NS = _load_toast_module()
ToastWindow = NS["ToastWindow"]


def _render_offscreen(toast, w, h):
    """把 toast._paint 画到离屏位图并读回像素（绕开屏幕合成/DPI 干扰）。

    分层窗口(WS_EX_LAYERED)用 GetWindowDC/PrintWindow 常抓不到内容，
    故直接猴补 BeginPaint 让绘制落到我们自己的内存 DC 上。
    """
    import win32ui
    src = win32gui.GetDC(0)
    udc = win32ui.CreateDCFromHandle(src)
    mdc = udc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(udc, w, h)
    mdc.SelectObject(bmp)
    hdc = mdc.GetSafeHdc()
    win32gui.ReleaseDC(0, src)

    real_begin, real_end = win32gui.BeginPaint, win32gui.EndPaint
    win32gui.BeginPaint = lambda h: (hdc, None)
    win32gui.EndPaint = lambda h, ps: None
    try:
        toast._paint(hwnd=1)
    finally:
        win32gui.BeginPaint, win32gui.EndPaint = real_begin, real_end

    bits = bmp.GetBitmapBits(True)
    px = [(bits[i + 2], bits[i + 1], bits[i])
          for i in range(0, len(bits), 4)]
    for fn in (mdc.DeleteDC, udc.DeleteDC):
        try:
            fn()
        except Exception:
            pass
    return px


# ---------------------------------------------------------------- 内容可见性
@pytest.mark.parametrize("text,kind", [
    ("已复制 3 行", "ok"),
    ("未识别到文字", "error"),
    ("快捷键已更新并生效", "info"),
])
def test_toast_content_is_visible(text, kind):
    """内部应为深色底 + 白色文字；若被白色画刷覆盖则白字不可见。"""
    w, h = 260, 46
    toast = ToastWindow(text, 0, 0, w, h, 1000, kind=kind)
    px = _render_offscreen(toast, w, h)

    inner = [p for i, p in enumerate(px)
             if 6 < (i % w) < w - 6 and 6 < (i // w) < h - 6]
    dark = sum(1 for p in inner if abs(p[0] - 30) < 14
               and abs(p[1] - 30) < 14 and abs(p[2] - 30) < 14)
    white = sum(1 for p in inner if p[0] > 235 and p[1] > 235 and p[2] > 235)

    assert dark > len(inner) * 0.5, (
        f"内部深色底仅 {dark}/{len(inner)} —— 白色画刷覆盖了背景，白字将不可见")
    assert white > 30, f"内部白色文字像素仅 {white} —— 文字未绘制出来"


# ------------------------------------------------------------------ 自动关闭
@pytest.mark.parametrize("duration_ms", [600, 1200])
def test_toast_auto_closes(duration_ms):
    """到点后消息循环必须自行退出（窗口会自行销毁）。"""
    toast = ToastWindow("自动关闭测试", 200, 200, 220, 44, duration_ms,
                        kind="ok")
    t0 = time.time()
    th = threading.Thread(target=toast.run, daemon=True)
    th.start()
    th.join(timeout=duration_ms / 1000.0 + 3.0)

    assert not th.is_alive(), (
        "消息循环未退出 —— toast 不会自动消失（检查 _on_timeout 是否用 "
        "PostMessage(hwnd, ...) 而非 PostThreadMessage(thread_id, ...)）")
    elapsed = time.time() - t0
    assert elapsed < duration_ms / 1000.0 + 2.0, f"退出过慢：{elapsed:.2f}s"


def test_multiple_toasts_close_independently():
    """多条 toast 并发时应各自按时消失，不互相干扰、也不残留。"""
    n = 5
    for i in range(n):
        NS["show_toast"]("并发提示 %d" % i, 700)

    def count_toast_windows():
        found = []
        win32gui.EnumWindows(
            lambda h, e: found.append(h)
            if win32gui.GetClassName(h).startswith("OCRToast_") else None,
            None)
        return len(found)

    time.sleep(0.4)
    assert count_toast_windows() > 0, "toast 窗口未创建"
    time.sleep(2.0)
    assert count_toast_windows() == 0, "仍有 toast 窗口残留"


def test_post_thread_message_would_not_dispatch():
    """回归依据：PostThreadMessage 的消息 hwnd 为 NULL，不会进入窗口过程。

    若哪天有人把 _on_timeout 改回 PostThreadMessage，这条会提醒修复方式。
    用 AST 只取函数体里的真实调用，天然排除 docstring/注释里的说明文字。
    """
    import ast

    assert hasattr(win32gui, "PostMessage"), "win32gui.PostMessage 不可用"
    src = open(MAIN, encoding="utf-8").read()
    body = src[src.index("# ----------------- 轻量 Toast 提示"):
               src.index("# ----------------- 核心逻辑 -----------------")]
    fn_src = body[body.index("def _on_timeout"):body.index("def _force_quit")]

    calls = set()
    for node in ast.walk(ast.parse(fn_src.strip())):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                calls.add(f.attr)
            elif isinstance(f, ast.Name):
                calls.add(f.id)

    assert "PostMessage" in calls, (
        "_on_timeout 必须用 PostMessage 投递 WM_TIMER（当前调用：%s）"
        % sorted(calls))
    assert "PostThreadMessage" not in calls, (
        "_on_timeout 不得使用 PostThreadMessage —— hwnd 为 NULL 不会被分发，"
        "toast 将永不消失（当前调用：%s）" % sorted(calls))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--no-header"]))