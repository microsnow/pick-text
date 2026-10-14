#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
拾字（PickText）· 屏幕离线 OCR 取字工具（全屏一键识别 + 区域多选识别，离线）
====================================================================
两种识别模式（均离线，OCR 引擎使用 RapidOCR / ONNX 推理）：

1) 全屏识别（默认快捷键 Win+Alt+O）
   - 抓取整个屏幕，识别其中全部文字，自动复制到剪贴板。
   - 弹出原生结果窗口：可鼠标框选部分文字后 Ctrl+C 进行“选择复制”；
     也可点“复制全部”按钮复制整段（复制的是当前编辑框内容，含手动修改）。
   - 结果框可直接编辑，并支持一键“导出 TXT / 导出 MD”（原生“另存为”对话框，
     默认存到程序目录下的 exports/）。

2) 区域选择识别（默认快捷键 Win+Alt+Q）★新增
   - 屏幕变暗，鼠标左键拖拽即可框选一个区域；可多次拖拽框选多个区域。
- 右键 / Enter 确认：仅识别各区域中的内容，多个区域之间用换行隔开。
- 再次按 Win+Alt+Q 重选/取消本次选择；ESC 取消选区（不退出程序）。

3) 选区预设（快捷键 Ctrl+Shift+1~9 定义 / Alt+Shift+1~9 触发）★新增
   - 用 Ctrl+Shift+N 框选并把屏幕某块区域“存”为命名选区（落盘到 region_presets.json）。
   - 之后按 Alt+Shift+N 一键自动截该区域 → OCR → 静默复制到剪贴板，无需每次重画。
   - 适合反复取同一处固定文字（字幕条、计时器、比分牌、表单框等）。

依赖：mss / rapidocr-onnxruntime / pynput / pyperclip / numpy / pywin32

运行（在隔离 venv 中）：
    python main.py
"""

__version__ = "2.0.0"

import os
import sys
import time
import threading
import json
import ctypes
from ctypes import wintypes

import numpy as np
import mss
import pyperclip
from pynput import keyboard
from rapidocr_onnxruntime import RapidOCR

try:
    import win32gui
    import win32con
    import win32api
    import pywintypes
    HAS_WIN32 = True
except Exception as _e:  # 无 pywin32 时退回控制台输出
    HAS_WIN32 = False
    print(f"[提示] 未检测到 pywin32（{_e}），区域选择等 GUI 功能将不可用。")

try:
    import win32file
    HAS_WIN32FILE = True
except Exception:
    HAS_WIN32FILE = False

# 系统托盘（桌面应用形态）：包装成常驻后台、右下角图标的“正式”程序
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    HAS_TRAY = True
except Exception as _te:
    HAS_TRAY = False
    print(f"[提示] 未检测到 pystray/PIL（{_te}），将不显示系统托盘图标。")

# ===================== 配置区 =====================
# 热键采用 OS 独占注册（Win32 RegisterHotKey），冲突会被精确检测并提示。
# 默认值经实测调校，避开本机已被占用的「Win+数字」系列（某窗口/启动类工具占用了整套
# Win+digit 组合）：固定键用 Win+字母（空闲），槽位键用 Ctrl/Alt+Shift+数字（空闲且冲突面小）。
HOTKEY = "<cmd>+<alt>+o"   # 全屏识别快捷键：Win+Alt+O
REGION_HOTKEY = "<cmd>+<alt>+q"  # 区域选择识别快捷键（可多选区域）：Win+Alt+Q（R 已被占用）
MONITOR = 1                 # 1 = 主显示器；0 = 全部显示器（拼接大图，较慢）
AUTO_COPY_ALL = True        # OCR 后自动复制全部到剪贴板（一键复制全部）
SHOW_WINDOW = True          # 是否弹出结果窗口（支持框选复制）
REGION_ALPHA = 160          # 区域选择遮罩的暗化不透明度（0-255，越大越暗）
CLOSE_KEY = "<esc>"          # 关闭/取消“当前弹窗”（结果窗口或区域遮罩），绝不退出程序
MONITOR_HOTKEY = "<ctrl>+<alt>+m"  # 锁定区域轮询监控：Ctrl+Alt+M（再次按下停止监控）
MONITOR_INTERVAL = 1.0            # 监控轮询间隔（秒）；画面未变化时跳过 OCR 以省 CPU

# ----------------- 选区预设（数字槽位） -----------------
# 把屏幕上某块区域“存”成预设，绑定快捷键；之后一键自动截该区域→OCR→静默复制。
PRESET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "region_presets.json")
PRESET_SLOTS = 9            # 支持 1~9 号槽位
# 定义槽位始终注册（用来创建预设）；触发槽位仅在已存预设时注册（见 build_hotkey_map）。
# 注意：槽位键不用 Win+数字（本机该系列已被占用），改用 Ctrl+Shift / Alt+Shift + 数字。
DEFINE_HOTKEY_TMPL = "<ctrl>+<shift>+%d"    # 定义选区：Ctrl+Shift+1..9
TRIGGER_HOTKEY_TMPL = "<alt>+<shift>+%d"     # 触发选区：Alt+Shift+1..9
# =================================================

# 给界面显示用的人类可读快捷键
def _pretty(hk):
    return (hk.replace("<cmd>", "Win")
             .replace("<ctrl>", "Ctrl")
             .replace("<alt>", "Alt")
             .replace("<shift>", "Shift")
             .replace("<esc>", "Esc")
             .replace("+", "+"))

HOTKEY_PRETTY = _pretty(HOTKEY)
REGION_HOTKEY_PRETTY = _pretty(REGION_HOTKEY)
CLOSE_KEY_PRETTY = _pretty(CLOSE_KEY)
TRIGGER_HOTKEY_PRETTY_TMPL = "Alt+Shift+%d"
DEFINE_HOTKEY_PRETTY_TMPL = "Ctrl+Shift+%d"
MONITOR_HOTKEY_PRETTY = _pretty(MONITOR_HOTKEY)

# =================================================

# ----------------- 快捷键配置（可运行时修改，落盘 hotkeys.json） -----------------
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOTKEYS_CONFIG_FILE = os.path.join(_BASE_DIR, "hotkeys.json")

DEFAULT_HOTKEYS = {
    "full": HOTKEY,
    "region": REGION_HOTKEY,
    "close": CLOSE_KEY,
    "trigger_tmpl": TRIGGER_HOTKEY_TMPL,
    "define_tmpl": DEFINE_HOTKEY_TMPL,
}
CFG = dict(DEFAULT_HOTKEYS)   # 当前生效的快捷键配置（运行时可改）


# ----------------- OCR 后处理（layout.py：竖排重排 / 繁体 / 标点） -----------------
# layout 为可选增强模块：导入失败时退化为“横排 + 原样”，不影响主流程。
try:
    from layout import (
        reorder_vertical,
        to_traditional,
        add_punctuation,
        _HAS_OPENCC as LAYOUT_HAS_OPENCC,
    )
except Exception as _layout_err:  # pragma: no cover - 环境相关
    def reorder_vertical(items):  # 退化：当 layout 不可用时按横排处理
        return _merge_horizontal(items)
    def to_traditional(t):
        return t
    def add_punctuation(t):
        return t
    LAYOUT_HAS_OPENCC = False
    print(f"[layout] 模块加载失败，竖排/繁体/标点功能不可用: {_layout_err}")


# ----------------- OCR 选项（排版 / 输出 / 标点，落盘 ocr_settings.json） -----------------
OCR_SETTINGS_FILE = os.path.join(_BASE_DIR, "ocr_settings.json")
DEFAULT_OCR_SETTINGS = {
    "vertical": False,      # 竖排重排（上→下、右→左）
    "traditional": False,   # 简体→繁体（OpenCC s2t，离线）
    "punctuate": "off",     # 自动标点：off / rule（离线规则）
}
OCR_CFG = dict(DEFAULT_OCR_SETTINGS)
VERTICAL = False
TRADITIONAL = False
PUNCTUATE = "off"


def load_ocr_config():
    """从 ocr_settings.json 读取 OCR 选项；缺失/损坏则回退默认。"""
    cfg = dict(DEFAULT_OCR_SETTINGS)
    try:
        if os.path.exists(OCR_SETTINGS_FILE):
            with open(OCR_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULT_OCR_SETTINGS:
                    if k in data:
                        cfg[k] = data[k]
    except Exception as e:
        print(f"[OCR设置] 读取 {OCR_SETTINGS_FILE} 失败，使用默认: {e}")
    cfg["vertical"] = bool(cfg.get("vertical"))
    cfg["traditional"] = bool(cfg.get("traditional"))
    if cfg.get("punctuate") not in ("off", "rule"):
        cfg["punctuate"] = "off"
    return cfg


def save_ocr_config(cfg):
    """把 OCR 选项写回 ocr_settings.json。"""
    try:
        os.makedirs(os.path.dirname(OCR_SETTINGS_FILE), exist_ok=True)
        with open(OCR_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[OCR设置] 保存 {OCR_SETTINGS_FILE} 失败: {e}")


def apply_ocr_config(cfg):
    """把 OCR 选项写回全局变量，供 ocr_image 使用。"""
    global OCR_CFG, VERTICAL, TRADITIONAL, PUNCTUATE
    OCR_CFG = dict(cfg)
    VERTICAL = bool(OCR_CFG.get("vertical"))
    TRADITIONAL = bool(OCR_CFG.get("traditional"))
    PUNCTUATE = OCR_CFG.get("punctuate", "off")
    if TRADITIONAL and not LAYOUT_HAS_OPENCC:
        print("[OCR设置] 已开启“转繁体”，但 opencc-python 未安装，繁体转换将无效（输出原样）。")


def load_hotkey_config():
    """从 hotkeys.json 读取已保存的快捷键；缺失/损坏则回退默认。"""
    cfg = dict(DEFAULT_HOTKEYS)
    try:
        if os.path.exists(HOTKEYS_CONFIG_FILE):
            with open(HOTKEYS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULT_HOTKEYS:
                    if k in data and isinstance(data[k], str) and data[k]:
                        cfg[k] = data[k]
    except Exception as e:
        print(f"[快捷键] 读取 {HOTKEYS_CONFIG_FILE} 失败，使用默认: {e}")
    for k in ("trigger_tmpl", "define_tmpl"):
        if "%d" not in cfg[k]:
            cfg[k] = DEFAULT_HOTKEYS[k]
    return cfg


def save_hotkey_config(cfg):
    """把快捷键配置写回 hotkeys.json。"""
    try:
        os.makedirs(os.path.dirname(HOTKEYS_CONFIG_FILE), exist_ok=True)
        with open(HOTKEYS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[快捷键] 保存 {HOTKEYS_CONFIG_FILE} 失败: {e}")


def apply_config(cfg):
    """把配置写回全局变量与派生变量，供热键监听与界面显示使用。"""
    global CFG, HOTKEY, REGION_HOTKEY, CLOSE_KEY
    global TRIGGER_HOTKEY_TMPL, DEFINE_HOTKEY_TMPL
    global HOTKEY_PRETTY, REGION_HOTKEY_PRETTY, CLOSE_KEY_PRETTY
    global TRIGGER_HOTKEY_PRETTY_TMPL, DEFINE_HOTKEY_PRETTY_TMPL
    CFG = dict(cfg)
    HOTKEY = CFG["full"]
    REGION_HOTKEY = CFG["region"]
    CLOSE_KEY = CFG["close"]
    TRIGGER_HOTKEY_TMPL = CFG["trigger_tmpl"]
    DEFINE_HOTKEY_TMPL = CFG["define_tmpl"]
    HOTKEY_PRETTY = _pretty(HOTKEY)
    REGION_HOTKEY_PRETTY = _pretty(REGION_HOTKEY)
    CLOSE_KEY_PRETTY = _pretty(CLOSE_KEY)
    TRIGGER_HOTKEY_PRETTY_TMPL = _pretty(TRIGGER_HOTKEY_TMPL)
    DEFINE_HOTKEY_PRETTY_TMPL = _pretty(DEFINE_HOTKEY_TMPL)


def build_hotkey_map():
    """根据当前 CFG 生成“可注册热键映射表”（用于 Win32 RegisterHotKey）。

    为减少与其它软件的全局热键冲突，触发槽位仅在「已存预设」时注册：
    未定义过的槽位不会占用全局热键，定义后才即时启用（见 do_define_preset）。
    定义槽位始终注册（用于创建预设）。

    注意：关闭/取消键（如 <esc>）是无修饰键的“裸键”，RegisterHotKey 不允许注册，
    由独立的 Esc 钩子（见 start_esc_listener）处理；若关闭键含修饰键则一并注册。
    """
    m = {
        HOTKEY: on_activate_ocr,
        REGION_HOTKEY: on_activate_region,
        MONITOR_HOTKEY: on_activate_monitor,
    }
    # 关闭键：含修饰键才能注册；裸键（Esc 等）由 Esc 钩子负责
    try:
        _parse_hotkey(CLOSE_KEY)
        m[CLOSE_KEY] = on_activate_esc_close
    except Exception:
        pass
    for n in range(1, PRESET_SLOTS + 1):
        m[DEFINE_HOTKEY_TMPL % n] = (lambda s=n: on_activate_define(s))
        if str(n) in presets:   # 仅对已存预设的槽位注册触发热键
            m[TRIGGER_HOTKEY_TMPL % n] = (lambda s=n: on_activate_trigger(s))
    return m


# ----------------- Esc 关闭/取消键：独立键盘钩子 -----------------
# RegisterHotKey 无法注册“裸键”（无修饰键），而用户常用的“按 Esc 关闭/取消当前弹窗”
# 正是裸键。这里用一个轻量键盘钩子只监听 Esc，复用 pynput；钩子非独占，但回调仅在
# 本程序有活动窗口时才动作（on_activate_esc_close 内部已判断），与其它软件共存无碍。
_esc_listener = None


def _on_esc_press(key):
    try:
        if key == keyboard.Key.esc:
            on_activate_esc_close()
    except Exception as e:
        print(f"[Esc] 回调异常: {e}")


def start_esc_listener():
    """启动 Esc 钩子（仅当关闭键为裸键时才有意义；始终启动以覆盖默认 <esc>）。"""
    global _esc_listener
    if _esc_listener is not None:
        return
    try:
        _esc_listener = keyboard.Listener(on_press=_on_esc_press)
        _esc_listener.start()
    except Exception as e:
        print(f"[Esc] 监听器启动失败（Esc 关闭功能将不可用）: {e}")


def stop_esc_listener():
    global _esc_listener
    if _esc_listener is not None:
        try:
            _esc_listener.stop()
        except Exception:
            pass
        _esc_listener = None


def _parse_hotkey(hk):
    """把 pynput 风格热键串（如 '<cmd>+<alt>+o'）解析为 (mods, vk)。

    返回 win32 MOD_* 修饰符与虚拟键码；解析失败抛 ValueError。
    """
    mods = 0
    vk = None
    for p in hk.split("+"):
        pl = p.strip().lower().strip("<>")
        if pl == "ctrl":
            mods |= win32con.MOD_CONTROL
        elif pl == "alt":
            mods |= win32con.MOD_ALT
        elif pl == "shift":
            mods |= win32con.MOD_SHIFT
        elif pl in ("cmd", "win"):
            mods |= win32con.MOD_WIN
        elif pl == "esc":
            vk = win32con.VK_ESCAPE
        elif pl == "space":
            vk = win32con.VK_SPACE
        elif pl == "tab":
            vk = win32con.VK_TAB
        elif pl == "enter":
            vk = win32con.VK_RETURN
        elif pl.startswith("f") and pl[1:].isdigit():
            n = int(pl[1:])
            if 1 <= n <= 24:
                vk = getattr(win32con, "VK_F%d" % n)
        elif len(pl) == 1:
            code = win32api.VkKeyScan(pl)
            if code & 0xFFFF == 0xFFFF:
                raise ValueError("无法识别按键: " + p)
            vk = code & 0xFF
        else:
            raise ValueError("不支持的按键: " + p)
    if vk is None:
        raise ValueError("缺少主键（组合键需含一个非修饰键）: " + hk)
    if mods == 0:
        raise ValueError("缺少修饰键（系统不允许注册无修饰键的组合）: " + hk)
    return mods, vk


def _hk_name_map():
    """返回 {hk_str: 动作名} 便于冲突提示。"""
    items = [("全屏识别", CFG["full"]),
             ("区域选择", CFG["region"]),
             ("区域监控", MONITOR_HOTKEY),
             ("关闭/取消", CFG["close"])]
    for n in range(1, PRESET_SLOTS + 1):
        items.append((f"选区定义{n}", CFG["define_tmpl"] % n))
        if str(n) in presets:
            items.append((f"选区触发{n}", CFG["trigger_tmpl"] % n))
    m = {}
    for name, hk in items:
        if hk:
            m.setdefault(hk, name)
    return m


def _register_hotkeys(hotkey_map):
    """在 result_win 上（重新）注册全部热键，返回失败项 [(hk, reason)]。

    先卸载旧注册；冲突/占用会被 RegisterHotKey 抛 pywintypes.error(1409) 捕获。
    """
    global _hotkey_ids, _hotkey_callbacks
    if result_win is not None and result_win.hwnd:
        for hid in _hotkey_ids:
            try:
                win32gui.UnregisterHotKey(result_win.hwnd, hid)
            except Exception:
                pass
    _hotkey_ids = []
    _hotkey_callbacks = {}
    failures = []
    for hk, cb in hotkey_map.items():
        try:
            mods, vk = _parse_hotkey(hk)
        except Exception as e:
            failures.append((hk, "解析失败: %s" % e))
            continue
        hid = len(_hotkey_ids) + 1
        try:
            win32gui.RegisterHotKey(result_win.hwnd, hid,
                                    mods | win32con.MOD_NOREPEAT, vk)
        except pywintypes.error as e:
            failures.append((hk, "被其它程序或系统占用（WinError %d）" % e.winerror))
        else:
            _hotkey_ids.append(hid)
            _hotkey_callbacks[hid] = cb
    return failures


def start_hotkey_listener():
    """（在 UI 线程）注册全部热键。返回 (ok, failures)。

    failures 为 [(hk_pretty, 动作名, 原因)]，空列表表示全部成功。
    需在 result_win 已 build 之后调用（应在 UI 线程）。
    """
    if not HAS_WIN32 or result_win is None or not result_win.hwnd:
        return False, [("（窗口未就绪）", "热键", "UI 窗口尚未创建")]
    hmap = build_hotkey_map()
    failures = _register_hotkeys(hmap)
    namemap = _hk_name_map()
    detailed = [(_pretty(hk), namemap.get(hk, "（未知）"), reason)
                for (hk, reason) in failures]
    return (len(failures) == 0, detailed)


def stop_hotkey_listener():
    """卸载全部已注册热键（退出时调用）。"""
    global _hotkey_ids, _hotkey_callbacks
    if result_win is not None and result_win.hwnd:
        for hid in _hotkey_ids:
            try:
                win32gui.UnregisterHotKey(result_win.hwnd, hid)
            except Exception:
                pass
    _hotkey_ids = []
    _hotkey_callbacks = {}


# 启动时加载已保存配置（覆盖默认）
_loaded = load_hotkey_config()
apply_config(_loaded)
_ocr_loaded = load_ocr_config()
apply_ocr_config(_ocr_loaded)


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

_lock = threading.Lock()

# 全局热键（基于 Win32 RegisterHotKey 的 OS 独占注册）：
# - _hotkey_ids        : 本次已注册的 id 列表（用于卸载）
# - _hotkey_callbacks  : id -> 回调函数
# 注册必须在“拥有 result_win 的 UI 线程”进行；WM_HOTKEY 由 UI 线程的消息泵派发到
# ResultWindow._wndproc，再在此处查表回调。这样系统保证同一组合键只归本程序，
# 被其它程序/系统占用时 RegisterHotKey 会抛 1409，可精确报冲突。
_hotkey_ids = []
_hotkey_callbacks = {}
_pending_conflict_msg = ""   # 启动时的冲突提示文本，由 UI 线程弹窗读取

# 当前活动的区域选择器（供全局热键“取消”使用）
region_sel = None

# 每次区域选择用唯一窗口类名，避免“类已存在”(1410)——类一旦注册会常驻进程，
# 第二次 RegisterClass 使用相同名字即报错。用自增计数器保证名称唯一。
_region_class_seq = 0


def _next_region_class_name():
    global _region_class_seq
    _region_class_seq += 1
    return "OCRRegionSel_%d" % _region_class_seq


# Toast 窗口类名自增（每次一个唯一名，避免“类已存在”1410）
_toast_class_seq = 0


def _next_toast_class_name():
    global _toast_class_seq
    _toast_class_seq += 1
    return "OCRToast_%d" % _toast_class_seq


# ----------------- 选区预设存储 -----------------
# presets: { "1": {"name": "选区1", "monitor": 1, "rects": [[x, y, w, h], ...]}, ... }
presets = {}
_active_mode = None   # "region" | "define"：当前是否在进行框选及其类型
_active_slot = None   # define 模式下框选对应的槽位


def load_presets():
    """启动时从 JSON 加载已保存的选区预设（重启后保留）。"""
    global presets
    presets = {}
    if os.path.exists(PRESET_FILE):
        try:
            with open(PRESET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                presets = data
        except Exception as e:
            print(f"[预设] 读取 {PRESET_FILE} 失败，已忽略: {e}")


def save_presets():
    """把当前选区预设写回 JSON 文件。"""
    try:
        with open(PRESET_FILE, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[预设] 保存 {PRESET_FILE} 失败: {e}")


_engine = None  # RapidOCR 引擎单例（懒加载，见 get_engine）


def get_engine():
    """懒加载 RapidOCR 引擎（模型随包内置，离线）。"""
    global _engine
    if _engine is None:
        print("[初始化] 加载 OCR 模型…")
        _engine = RapidOCR()
        print("[初始化] 模型就绪。")
    return _engine


def get_monitor(index):
    """返回 mss 的显示器字典 {left, top, width, height}（绝对坐标），越界自动回退。"""
    with mss.MSS() as sct:
        max_idx = len(sct.monitors) - 1
        if index < 1 or index > max_idx:
            index = 1 if max_idx >= 1 else 0
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
WM_RESULT_SHOW = win32con.WM_APP + 2   # 由窗口所属线程执行“显示”（线程安全）
WM_RESULT_HIDE = win32con.WM_APP + 3   # 由窗口所属线程执行“隐藏/关闭”
WM_ABOUT_SHOW = win32con.WM_APP + 4    # 由窗口所属线程弹出“关于”模态框（线程安全）
WM_HOTKEY_RELOAD = win32con.WM_APP + 6  # 请求 UI 线程重新注册全局热键（跨线程安全）
WM_HOTKEY_CONFLICT_SHOW = win32con.WM_APP + 7  # 启动后弹“热键冲突”提示
WM_LOG_VIEW_SHOW = win32con.WM_APP + 8  # 由 UI 线程弹出“运行日志”查看窗口
WM_MONITOR_UPDATE = win32con.WM_APP + 9  # 监控线程 -> UI 线程：刷新结果文本（线程安全）
WM_MONITOR_START = win32con.WM_APP + 10  # 托盘菜单 -> UI 线程：弹出框选并启动监控


def _about_text():
    """「关于」弹窗内容（托盘菜单与 UI 线程共用）。"""
    return (
        f"拾字（PickText）· 屏幕离线取字工具 v{__version__}\n\n"
        f"全屏识别 : {HOTKEY_PRETTY}\n"
        f"区域选择 : {REGION_HOTKEY_PRETTY}\n\n"
        "选区预设 : 定义 Ctrl+Shift+1~9 → 触发 Alt+Shift+1~9\n\n"
        "关闭弹窗 : 按 Esc（或点结果窗口的“关闭”/X；选区中按 Esc 取消选区）\n"
        "退出程序 : 右键托盘图标 → 退出（仅此一种方式）\n\n"
        f"区域监控 : {MONITOR_HOTKEY_PRETTY}（框选区域后可锁定轮询，字幕/歌词自动刷新；再次按下或 Esc 停止）"
    )


# 用 ctypes 直接调 Win32 抢前台焦点：pywin32 在某些版本缺失 AllowSetForegroundWindow，
# 而跨线程（OCR 工作线程 -> UI 线程）的窗口必须显式允许前台切换，否则弹窗拿不到焦点、
# 点“关闭”需点两次甚至“关不上”。ASFW_ANY = 0xFFFFFFFF 允许任意进程设置前台窗口。
_user32 = ctypes.windll.user32
_user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]


def _bring_to_front(hwnd):
    """可靠地把窗口带到前台并抢焦点（绕过 pywin32 缺失的 API）。"""
    try:
        _user32.AllowSetForegroundWindow(0xFFFFFFFF)
    except Exception:
        pass
    try:
        _user32.SetForegroundWindow(int(hwnd))
    except Exception:
        pass


# ----------------- 单实例与首启判定 -----------------
_kernel32 = ctypes.windll.kernel32
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetLastError.restype = wintypes.DWORD
_kernel32.SetLastError.argtypes = [wintypes.DWORD]

_SINGLE_INSTANCE_MUTEX_NAME = "ScreenOCR_SingleInstance_Mutex_v1"
_single_instance_handle = None


def _another_instance_running():
    """尝试创建全局命名互斥体。已存在→说明已有实例在运行（返回 True）。

    本实例成功创建后持有句柄直到进程退出，从而互斥其它实例。
    """
    global _single_instance_handle
    _kernel32.SetLastError(0)
    h = _kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
    if not h:
        return False
    if _kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        _kernel32.CloseHandle(h)
        return True
    _single_instance_handle = h  # 持有到进程结束，维持单实例
    return False


def _first_run_marker_path():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "ScreenOCR", "firstrun.done")


def _is_first_run():
    return not os.path.exists(_first_run_marker_path())


def _mark_first_run_done():
    try:
        p = _first_run_marker_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w"):
            pass
    except Exception:
        pass


def _text_to_markdown(text):
    """把 OCR 逐行文本转为 Markdown：每行作为一个段落，空行自动跳过。"""
    lines = [ln.rstrip() for ln in text.split("\n")]
    paras = [ln for ln in lines if ln.strip()]
    return "\n\n".join(paras)


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
            "OCR 结果 - 框选后 Ctrl+C 复制 / 点'复制全部' / 可导出 TXT·MD",
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
            10, 340, 120, 34, self.hwnd, 2, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "导出TXT",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            140, 340, 120, 34, self.hwnd, 4, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "导出MD",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            270, 340, 120, 34, self.hwnd, 5, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "关闭",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            400, 340, 160, 34, self.hwnd, 3, self._inst, None,
        )
        win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        self.ready = True

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_HOTKEY:
            # 全局快捷键由系统派发到本窗口：查表调用对应回调
            cb = _hotkey_callbacks.get(wparam)
            if cb:
                try:
                    cb()
                except Exception as e:
                    print(f"[热键] 回调异常: {e}")
            return 0
        if msg == WM_HOTKEY_RELOAD:
            # 跨线程（如定义预设后）请求在 UI 线程重新注册热键
            try:
                ok, failures = start_hotkey_listener()
                if not ok:
                    for hk, name, reason in failures:
                        print(f"[热键] 重新注册失败 {hk}（{name}）: {reason}")
            except Exception as e:
                print(f"[热键] 重新注册异常: {e}")
            return 0
        if msg == WM_HOTKEY_CONFLICT_SHOW:
            txt = _pending_conflict_msg
            if txt:
                try:
                    win32gui.MessageBox(
                        self.hwnd, txt, "快捷键冲突（启动）",
                        win32con.MB_OK | win32con.MB_ICONWARNING
                        | win32con.MB_SETFOREGROUND | win32con.MB_TOPMOST,
                    )
                except Exception as e:
                    print(f"[UI] 冲突提示异常: {e}")
            return 0
        if msg == WM_RESULT_SHOW:
            # 在窗口所属线程中执行“显示”，避免跨线程操作 Win32 窗口导致无法交互/无法关闭
            try:
                win32gui.SendMessage(self.edit, win32con.WM_SETTEXT, 0, self.full_text)
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
                win32gui.SetWindowPos(
                    self.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
                )
                # 允许本进程抢前台，确保弹窗能拿到焦点、点击“关闭”即时生效
                _bring_to_front(self.hwnd)
            except Exception as e:
                print(f"[UI] 显示窗口异常: {e}")
            return 0
        if msg == WM_RESULT_HIDE:
            self._real_hide()
            return 0
        if msg == WM_ABOUT_SHOW:
            # 在窗口所属线程（ui_loop）中以本窗口为 owner 弹出原生模态消息框：
            # 确定按钮 / Esc 的关闭完全由 OS 模态循环接管，不再在托盘线程里
            # 直接调 MessageBox（那是在 pystray 回调栈内阻塞，导致弹窗关不掉）。
            _show_about_modal(self.hwnd)
            return 0
        if msg == WM_HOTKEY_SETTINGS_SHOW:
            # 在 UI 线程弹出「快捷键设置」弹层（嵌套消息循环），托盘回调立即返回。
            open_hotkey_settings(self.hwnd)
            return 0
        if msg == WM_OCR_SETTINGS_SHOW:
            # 在 UI 线程弹出「OCR 选项」弹层（嵌套消息循环），托盘回调立即返回。
            open_ocr_settings(self.hwnd)
            return 0
        if msg == WM_LOG_VIEW_SHOW:
            # 在 UI 线程弹出「运行日志」查看窗口（嵌套消息循环），托盘回调立即返回。
            open_log_viewer(self.hwnd)
            return 0
        if msg == WM_MONITOR_UPDATE:
            # 监控线程请求刷新结果文本（运行在 UI 线程，SendMessage 到同线程 edit 安全）
            self.update_text()
            return 0
        if msg == WM_MONITOR_START:
            # 托盘菜单“开始监控区域”请求：在 UI 线程弹框选并启动（与其他弹层一致）
            try:
                on_activate_monitor()
            except Exception as e:
                print(f"[监控] 启动异常: {e}")
            return 0
        if msg == win32con.WM_COMMAND:
            ctrl_id = wparam & 0xFFFF
            if ctrl_id == 2:          # “复制全部”按钮（复制当前编辑框内容，含用户修改）
                cur = win32gui.GetWindowText(self.edit) if (HAS_WIN32 and self.edit) else self.full_text
                if cur:
                    pyperclip.copy(cur)
                    print("[OCR] 已复制全部到剪贴板。")
            elif ctrl_id == 4:        # “导出 TXT”
                self.export_result("txt")
            elif ctrl_id == 5:        # “导出 MD”
                self.export_result("md")
            elif ctrl_id == 3:        # “关闭”按钮
                self._do_hide()
            return 0
        if msg == win32con.WM_CLOSE:  # 点标题栏 X：隐藏（可重复弹出）
            self._do_hide()
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _do_hide(self):
        """请求隐藏：投递到窗口自己的消息循环下一轮处理。

        关键：绝不能在 WndProc 处理 WM_COMMAND/WM_CLOSE（即窗口过程自身）里
        直接 ShowWindow(SW_HIDE) 隐藏当前窗口——这属于“在消息回调内同步隐藏自身”，
        会触发 Win32 消息循环重入，表现为“点了关闭却关不掉”。改为 PostMessage 一个
        自定义消息，由 PumpMessages 在下一轮迭代里执行真正的隐藏（见 _real_hide）。
        """
        if HAS_WIN32 and self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, WM_RESULT_HIDE, 0, 0)
            except Exception:
                pass

    def _real_hide(self):
        """真正执行隐藏（运行在窗口所属线程的消息循环内，安全、无重入）。"""
        try:
            win32gui.SetWindowPos(
                self.hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )
        except Exception:
            pass
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        except Exception:
            pass
        print("[UI] 结果窗口已隐藏。")

    def show(self, text):
        self.full_text = _crlf(text)
        if not (HAS_WIN32 and self.ready):
            print("---- OCR 结果（可框选复制）----")
            print(text)
            print("--------------------------------")
            return
        # 通过 PostMessage 让窗口所属线程执行显示，跨线程安全
        try:
            win32gui.PostMessage(self.hwnd, WM_RESULT_SHOW, 0, 0)
        except Exception as e:
            print(f"[UI] 显示窗口失败，退回控制台: {e}")
            print(text)

    def hide(self):
        if HAS_WIN32 and self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, WM_RESULT_HIDE, 0, 0)
            except Exception:
                pass

    def update_text(self):
        """监控模式：把 full_text 推到编辑框（由 UI 线程在 WM_MONITOR_UPDATE 中调用）。

        若窗口被隐藏则显示（不抢焦点、不强制置顶，避免打断用户其它操作）；
        已显示则只更新文本。配合 set_readonly(True) 实现“监控态只读”。
        """
        if not (HAS_WIN32 and self.edit):
            return
        try:
            win32gui.SendMessage(self.edit, win32con.WM_SETTEXT, 0, self.full_text)
            if not win32gui.IsWindowVisible(self.hwnd):
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
                win32gui.SetWindowPos(
                    self.hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
                )
        except Exception as e:
            print(f"[UI] 监控刷新异常: {e}")

    def set_readonly(self, flag):
        """切换编辑框只读（监控态下置为只读，避免被下一轮结果覆盖用户编辑）。"""
        if HAS_WIN32 and self.edit:
            try:
                win32gui.SendMessage(self.edit, win32con.EM_SETREADONLY,
                                     1 if flag else 0, 0)
            except Exception:
                pass

    def export_result(self, fmt):
        """把当前编辑框内容导出为 .txt 或 .md（原生“另存为”对话框）。"""
        if not (HAS_WIN32 and self.edit):
            return
        text = win32gui.GetWindowText(self.edit)
        if not text.strip():
            print("[OCR] 结果为空，未导出。")
            return
        export_dir = os.path.join(_app_dir(), "exports")
        try:
            os.makedirs(export_dir, exist_ok=True)
        except Exception:
            pass
        defext = ".md" if fmt == "md" else ".txt"
        filt = ("Markdown Files\0*.md\0All Files\0*.*\0" if fmt == "md"
                else "Text Files\0*.txt\0All Files\0*.*\0")
        try:
            res = win32gui.GetSaveFileName(
                InitialDir=export_dir, File="", DefExt=defext,
                Title="导出 OCR 结果", Filter=filt,
            )
        except Exception as e:
            print(f"[OCR] 导出对话框出错: {e}")
            return
        if not res:
            return
        path = res[0] if isinstance(res, (tuple, list)) else res
        if not path:
            return
        if not path.lower().endswith(defext):
            path += defext
        try:
            content = text if fmt == "txt" else _text_to_markdown(text)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[OCR] 已导出到 {path}")
            show_toast(f"已导出: {os.path.basename(path)}")
        except Exception as e:
            print(f"[OCR] 导出失败: {e}")


result_win = ResultWindow()
_FIRST_RUN = False  # 由 main() 在启动前设置：本次是否为首次运行（需自动弹“关于”）


def ui_loop():
    """在独立线程中构建并泵消息，保证窗口可交互。"""
    if not HAS_WIN32:
        return
    try:
        result_win.build()
        # 启动 Esc 关闭/取消键的轻量钩子（裸键，RegisterHotKey 无法注册）
        start_esc_listener()
        # 在 UI 线程注册全局热键（依赖 result_win.hwnd），并检测启动冲突
        try:
            ok, failures = start_hotkey_listener()
            if not ok:
                global _pending_conflict_msg
                lines = "\n".join(f"• {hk}（{name}）：{reason}"
                                  for (hk, name, reason) in failures)
                _pending_conflict_msg = ("部分快捷键被其它程序或系统占用，可能无法使用：\n\n"
                                         + lines + "\n\n可右键托盘 → 快捷键设置 重新指定。")
                win32gui.PostMessage(result_win.hwnd, WM_HOTKEY_CONFLICT_SHOW, 0, 0)
        except Exception as e:
            print(f"[UI] 热键注册失败: {e}")
        if _FIRST_RUN:
            # 首次运行：在 UI 线程同步弹出“关于”。此时窗口已 build 完成、hwnd 有效，
            # 直接调用（而非 PostMessage）最可靠——不依赖消息队列/消息泵时序，必弹。
            try:
                print("[UI] 首次运行：即将弹出“关于”窗口...")
                _show_about_modal(result_win.hwnd)
                _mark_first_run_done()
                print("[UI] 首次运行：已弹出“关于”窗口。")
            except Exception as e:
                print(f"[UI] 首启弹窗失败: {e}")
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
      - ESC：取消本次选区（仅取消选区，不退出程序）
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
        self.cancel_hint = REGION_HOTKEY_PRETTY  # 顶部提示栏显示的“再次按此键取消”

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
        # 不直接在 WndProc 内 ShowWindow(SW_HIDE) 隐藏自身（会引发消息循环重入），
        # 仅设置结果并退出消息循环，由 select() 末尾的 DestroyWindow 移除窗口。
        self.confirmed = True
        win32gui.PostQuitMessage(0)

    def _cancel(self):
        # 同上：仅设标志 + 退出循环，避免“在消息回调内隐藏自身”。
        self.confirmed = False
        self.rects = []
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
            elif vk == 27:          # Esc 取消选区
                self._cancel()
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
                f"再次按 {self.cancel_hint} 重选")
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


# ----------------- 轻量 Toast 提示（原生窗口，不抢焦点） -----------------
class ToastWindow:
    """一个短暂出现的原生浮层，显示一行提示后自动消失。

    使用 WS_EX_NOACTIVATE + SW_SHOWNOACTIVATE，绝不抢走当前窗口焦点，
    适合在“静默复制”等场景给出轻提示。每条 toast 独立线程 + 独立窗口类，
    互不干扰；显示 duration 毫秒后自动隐藏并退出消息循环。
    """

    def __init__(self, text, x, y, w, h, duration_ms):
        self.text = text
        self.x, self.y, self.w, self.h = x, y, w, h
        self.duration = duration_ms
        self.hwnd = None
        self._inst = None
        self._atom = None
        self._class_name = None

    def _build(self):
        self._inst = win32api.GetModuleHandle(None)
        wc = win32gui.WNDCLASS()
        wc.hInstance = self._inst
        wc.lpszClassName = _next_toast_class_name()
        self._class_name = wc.lpszClassName
        wc.lpfnWndProc = self._wndproc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW + 1
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        self._atom = win32gui.RegisterClass(wc)
        ex_style = (win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST
                    | win32con.WS_EX_NOACTIVATE)
        self.hwnd = win32gui.CreateWindowEx(
            ex_style, self._atom, "", win32con.WS_POPUP,
            self.x, self.y, self.w, self.h, 0, 0, self._inst, None,
        )
        # 半透明暗底，弱化存在感
        win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 230, win32con.LWA_ALPHA)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_PAINT:
            self._paint(hwnd)
            return 0
        if msg == win32con.WM_TIMER:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            except Exception:
                pass
            win32gui.PostQuitMessage(0)
            return 0
        if msg == win32con.WM_DESTROY:
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _paint(self, hwnd):
        hdc, ps = win32gui.BeginPaint(hwnd)
        brush = win32gui.CreateSolidBrush(win32api.RGB(30, 30, 30))
        win32gui.FillRect(hdc, (0, 0, self.w, self.h), brush)
        win32gui.DeleteObject(brush)
        pen = win32gui.CreatePen(win32con.PS_SOLID, 1, win32api.RGB(0, 191, 255))
        old = win32gui.SelectObject(hdc, pen)
        win32gui.Rectangle(hdc, 0, 0, self.w - 1, self.h - 1)
        win32gui.SelectObject(hdc, old)
        win32gui.DeleteObject(pen)
        lf = win32gui.LOGFONT()
        lf.lfHeight = -16
        lf.lfFaceName = "Microsoft YaHei"
        hf = win32gui.CreateFontIndirect(lf)
        oldf = win32gui.SelectObject(hdc, hf)
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
        win32gui.SetTextColor(hdc, win32api.RGB(255, 255, 255))
        win32gui.DrawText(
            hdc, self.text, -1, (12, 0, self.w - 12, self.h),
            win32con.DT_VCENTER | win32con.DT_SINGLELINE | win32con.DT_LEFT,
        )
        win32gui.SelectObject(hdc, oldf)
        win32gui.DeleteObject(hf)
        win32gui.EndPaint(hwnd, ps)

    def run(self):
        try:
            self._build()
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
            win32gui.SetWindowPos(
                self.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )
            win32gui.SetTimer(self.hwnd, 1, self.duration, None)
            win32gui.PumpMessages()
        except Exception as e:
            print(f"[Toast] 显示失败: {e}")
        finally:
            try:
                if self.hwnd:
                    win32gui.DestroyWindow(self.hwnd)
            except Exception:
                pass
            try:
                if self._class_name and self._inst:
                    win32gui.UnregisterClass(self._class_name, self._inst)
            except Exception:
                pass


def show_toast(text, duration_ms=1600):
    """弹出一行轻量提示（不抢焦点，duration 毫秒后自动消失）。

    无 pywin32 时退回控制台打印。
    """
    if not HAS_WIN32:
        print(f"[Toast] {text}")
        return
    # 先按字体量出文字尺寸，决定浮层宽高
    try:
        hdc = win32gui.GetDC(0)
        lf = win32gui.LOGFONT()
        lf.lfHeight = -16
        lf.lfFaceName = "Microsoft YaHei"
        hf = win32gui.CreateFontIndirect(lf)
        old = win32gui.SelectObject(hdc, hf)
        tw, th = win32gui.GetTextExtentPoint32(hdc, text)
        win32gui.SelectObject(hdc, old)
        win32gui.DeleteObject(hf)
        win32gui.ReleaseDC(0, hdc)
    except Exception:
        tw, th = len(text) * 9, 20
    pad_x, pad_y = 24, 16
    w = tw + pad_x * 2
    h = th + pad_y
    maxw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN) - 40
    if w > maxw:
        w = maxw
    cx = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    cy = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    x = max(20, (cx - w) // 2)
    y = max(20, cy - h - 80)
    toast = ToastWindow(text, x, y, w, h, duration_ms)
    threading.Thread(target=toast.run, daemon=True).start()


# ----------------- 核心逻辑 -----------------
def _merge_horizontal(items):
    """把检测框按“同一行”归并（纵向重叠即同行的相邻片段），每行内按 x 从左到右拼接。

    用于横排场景；竖排由 layout.reorder_vertical 处理。items: [(x0,x1,y0,y1,text), ...]
    """
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


def ocr_image(img):
    """对单张 BGR 图像做 OCR，返回换行拼接的文本。

    OCR 检测器有时会把**同一行**文本拆成多个框（如中英文混排处的断点），
    若直接按框逐行输出，会导致一个区域识别出多行。这里先把纵向重叠的框
    归并为“同一行”再拼接，从而保证“一行文字 → 一行输出”，同时不影响
    区域内本来就存在的多行（不同行纵向不重叠，仍各自成行）。

    随后按当前 OCR 选项串联后处理：
      - 竖排模式：用 layout.reorder_vertical 按“上→下、右→左”重排；
      - 繁体输出：用 OpenCC 简→繁转换；
      - 自动标点：用 layout.add_punctuation 离线规则补句读。
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

    text = reorder_vertical(items) if VERTICAL else _merge_horizontal(items)
    if TRADITIONAL:
        text = to_traditional(text)
    if PUNCTUATE == "rule":
        text = add_punctuation(text)
    return text


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
    global region_sel, _active_mode
    if not _lock.acquire(blocking=False):
        return  # 上一轮还在跑，忽略重复触发
    try:
        mon = get_monitor(MONITOR)
        sel = RegionSelector()
        sel.cancel_hint = REGION_HOTKEY_PRETTY   # 顶部提示栏跟随当前配置
        region_sel = sel
        _active_mode = "region"
        confirmed, rects = sel.select(mon)
        region_sel = None
        _active_mode = None
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
        _active_mode = None
        _lock.release()


def do_define_preset(slot):
    """定义模式：框选区域（可多选）后保存到槽位 slot，不立即识别。"""
    global region_sel, _active_mode, _active_slot
    if not _lock.acquire(blocking=False):
        return  # 上一轮还在跑，忽略重复触发
    try:
        mon = get_monitor(MONITOR)
        sel = RegionSelector()
        region_sel = sel
        _active_mode = "define"
        _active_slot = slot
        # 顶部提示栏显示对应的“再次按此键取消”
        sel.cancel_hint = DEFINE_HOTKEY_PRETTY_TMPL % slot
        confirmed, rects = sel.select(mon)
        region_sel = None
        _active_mode = None
        _active_slot = None
        if not confirmed or not rects:
            print(f"[定义] 已取消选区 {slot} 的定义。")
            return
        name = "选区%d" % slot
        presets[str(slot)] = {
            "name": name,
            "monitor": MONITOR,
            "rects": [[int(x), int(y), int(w), int(h)] for (x, y, w, h) in rects],
        }
        save_presets()
        print(f"[定义] 已将 {name} 保存到槽位 {slot}（{len(rects)} 个区域），"
              f"重启后仍保留（见 region_presets.json）。")
        # 定义后即时让“触发”快捷键生效：跨线程安全地请 UI 线程重新注册热键。
        try:
            if result_win is not None and result_win.hwnd:
                win32gui.PostMessage(result_win.hwnd, WM_HOTKEY_RELOAD, 0, 0)
        except Exception as e:
            print(f"[定义] 请求热键重载失败（不影响预设保存）: {e}")
    except Exception as e:
        print(f"[定义] 出错: {e}")
    finally:
        region_sel = None
        _active_mode = None
        _active_slot = None
        _lock.release()


def trigger_preset(slot):
    """触发模式：自动截已存槽位的区域 → OCR → 静默复制到剪贴板（不弹窗）。"""
    if not _lock.acquire(blocking=False):
        return  # 上一轮还在跑，忽略重复触发
    try:
        key = str(slot)
        p = presets.get(key)
        if not p or not p.get("rects"):
            msg = f"选区 {slot} 未定义，请先 {DEFINE_HOTKEY_PRETTY_TMPL % slot} 定义"
            print(f"[触发] {msg}。")
            show_toast(msg)
            return
        name = p.get("name", "选区%d" % slot)
        mon_index = p.get("monitor", MONITOR)

        # 隐藏结果窗口，避免被截进屏幕
        result_win.hide()

        t0 = time.time()
        mon = get_monitor(mon_index)
        img = grab_monitor(mon)
        ih, iw = img.shape[:2]
        parts = []
        for (x, y, w, h) in p["rects"]:
            x0 = max(0, int(x)); y0 = max(0, int(y))
            x1 = min(iw, int(x) + int(w)); y1 = min(ih, int(y) + int(h))
            if x1 <= x0 or y1 <= y0:
                continue
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            t = ocr_image(crop)
            if t.strip():
                parts.append(t)
        text = "\n".join(parts)
        if text.strip():
            pyperclip.copy(_crlf(text))
            dt = (time.time() - t0) * 1000
            n_lines = len(text.splitlines())
            print(f"[触发] {name}(槽位{slot})：识别 {n_lines} 行，用时 {dt:.0f}ms，"
                  f"已静默复制到剪贴板。")
            show_toast(f"{name}(槽位{slot})：已复制 {n_lines} 行")
        else:
            print(f"[触发] {name}(槽位{slot})：未识别到文字。")
            show_toast(f"{name}(槽位{slot})：未识别到文字")
    except Exception as e:
        print(f"[触发] 出错: {e}")
    finally:
        _lock.release()


# ===================== 锁定区域轮询抓取（监控模式） =====================
# monitor_state 保存后台轮询线程的运行状态与锁定区域；running 为唯一开关。
monitor_state = {
    "running": False,
    "rects": [],
    "monitor": 1,
    "interval": MONITOR_INTERVAL,
    "_last_hash": None,
    "_thread": None,
}


def _image_hash(img):
    """对 BGR 图像计算低成本感知哈希（用于判断监控区域是否变化，省去无谓 OCR）。

    纯 numpy 实现，不依赖 opencv：降采样到 32x32 灰度后按均值二值化为整数位串。
    """
    h, w = img.shape[:2]
    step = max(1, min(h, w) // 32)
    small = img[::step, ::step]
    if small.ndim == 3:
        gray = small.mean(axis=2).astype(np.uint8)
    else:
        gray = small.astype(np.uint8) if small.dtype != np.uint8 else small
    mean = gray.mean()
    bits = (gray > mean)
    hv = 0
    for b in bits.flatten():
        hv = (hv << 1) | (1 if b else 0)
    return hv


def ocr_rects(rects, mon_index):
    """抓取指定显示器并对 rects（显示器相对坐标）做 OCR，返回合并文本。

    供「触发选区」与「监控模式」共用，保证两者识别逻辑一致。
    """
    try:
        mon = get_monitor(mon_index)
        img = grab_monitor(mon)
    except Exception as e:
        print(f"[OCR] 抓取显示器失败: {e}")
        return ""
    ih, iw = img.shape[:2]
    parts = []
    for (x, y, w, h) in rects:
        x0 = max(0, int(x)); y0 = max(0, int(y))
        x1 = min(iw, int(x) + int(w)); y1 = min(ih, int(y) + int(h))
        if x1 <= x0 or y1 <= y0:
            continue
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        t = ocr_image(crop)
        if t.strip():
            parts.append(t)
    return "\n".join(parts)


def _region_bbox(rects, iw, ih):
    """返回 rects 合并后的 (x0, y0, x1, y1)，越界已裁剪；无有效区域返回 None。"""
    if not rects:
        return None
    xs0 = [max(0, int(x)) for (x, y, w, h) in rects]
    ys0 = [max(0, int(y)) for (x, y, w, h) in rects]
    xs1 = [min(iw, int(x) + int(w)) for (x, y, w, h) in rects]
    ys1 = [min(ih, int(y) + int(h)) for (x, y, w, h) in rects]
    bx0, by0 = min(xs0), min(ys0)
    bx1, by1 = max(xs1), max(ys1)
    if bx1 <= bx0 or by1 <= by0:
        return None
    return bx0, by0, bx1, by1


def monitor_loop(rects, mon_index, interval):
    """后台轮询线程：定时抓取锁定区域，画面变化时刷新结果窗口。"""
    st = monitor_state
    while st["running"]:
        try:
            mon = get_monitor(mon_index)
            img = grab_monitor(mon)
            ih, iw = img.shape[:2]
            changed = True
            bbox = _region_bbox(rects, iw, ih)
            if bbox is not None:
                bx0, by0, bx1, by1 = bbox
                hv = _image_hash(img[by0:by1, bx0:bx1])
                if hv == st["_last_hash"]:
                    changed = False
                else:
                    st["_last_hash"] = hv
            if changed:
                text = ocr_rects(rects, mon_index)
                if text.strip():
                    if result_win is not None and result_win.hwnd:
                        result_win.full_text = _crlf(text)
                        win32gui.PostMessage(result_win.hwnd, WM_MONITOR_UPDATE, 0, 0)
                    else:
                        print("---- 监控结果 ----")
                        print(text)
                        print("------------------")
                else:
                    # 区域无文字（如黑屏/空白）：清空，避免残留旧结果
                    if result_win is not None and result_win.hwnd:
                        result_win.full_text = ""
                        win32gui.PostMessage(result_win.hwnd, WM_MONITOR_UPDATE, 0, 0)
        except Exception as e:
            print(f"[监控] 出错: {e}")
        # 等待下一轮（细粒度 sleep，便于 stop 后尽快退出）
        t0 = time.time()
        while st["running"] and (time.time() - t0) < interval:
            time.sleep(0.1)
    print("[监控] 线程已退出。")


def start_monitor(rects, mon_index, interval=MONITOR_INTERVAL):
    """启动锁定区域轮询。rects 为显示器相对坐标的矩形列表。"""
    if monitor_state["running"]:
        print("[监控] 拾字 已在运行中。")
        return False
    if not rects:
        print("[监控] 未指定区域，已取消。")
        return False
    monitor_state["rects"] = [tuple(map(int, (x, y, w, h))) for (x, y, w, h) in rects]
    monitor_state["monitor"] = mon_index
    monitor_state["interval"] = max(0.3, float(interval))
    monitor_state["_last_hash"] = None
    monitor_state["running"] = True
    t = threading.Thread(
        target=monitor_loop,
        args=(monitor_state["rects"], mon_index, monitor_state["interval"]),
        daemon=True,
    )
    monitor_state["_thread"] = t
    t.start()
    # 监控态：结果窗口内容只读，避免被下一轮结果覆盖用户编辑
    if result_win is not None:
        result_win.set_readonly(True)
    print(f"[监控] 已启动：锁定 {len(rects)} 个区域，每 "
          f"{monitor_state['interval']:.1f}s 轮询（画面不变则跳过 OCR）。")
    return True


def stop_monitor():
    """停止锁定区域轮询（保留结果窗口当前内容供查看/复制/导出）。"""
    if not monitor_state["running"]:
        return
    monitor_state["running"] = False
    if result_win is not None:
        result_win.set_readonly(False)
    print("[监控] 已停止。")


def is_monitoring():
    return monitor_state["running"]


def on_activate_ocr():
    threading.Thread(target=do_ocr, daemon=True).start()


def on_activate_region():
    global region_sel
    if not HAS_WIN32:
        print("[区域] 区域选择模式需要 pywin32（Windows）。已跳过。")
        return
    # 若已有“区域模式”框选在进行，再次按快捷键 = 取消
    if region_sel is not None and getattr(region_sel, "hwnd", None):
        if _active_mode == "region":
            win32gui.PostMessage(region_sel.hwnd, WM_REGION_CANCEL, 0, 0)
        return
    threading.Thread(target=do_region_ocr, daemon=True).start()


def on_activate_esc_close():
    """ESC：关闭/取消“当前弹窗”，绝不退出整个程序。

    之前 ESC 是“退出程序”，已按需求删除。但用户仍希望用 ESC 关掉弹窗，
    故重设计为：有区域/定义选区在进行 → 取消选区；否则 → 隐藏 OCR 结果窗口。
    走全局热键，不依赖弹窗是否拥有焦点，因此一定可用（区别于按钮的 WM_COMMAND）。
    """
    global region_sel
    # 0) 监控中 → 停止监控并隐藏结果窗口（Esc 作为“停止监控/关弹窗”统一键）
    if is_monitoring():
        stop_monitor()
        result_win.hide()
        return
    # 1) 区域/定义选区进行中 → 取消选区（与“再次按快捷键取消”同一条取消消息）
    if region_sel is not None and getattr(region_sel, "hwnd", None):
        try:
            win32gui.PostMessage(region_sel.hwnd, WM_REGION_CANCEL, 0, 0)
        except Exception:
            pass
        return
    # 2) 否则隐藏 OCR 结果窗口（若未显示则无副作用）；走 WM_RESULT_HIDE，最干净路径
    result_win.hide()


def on_activate_trigger(slot):
    """触发选区：一键自动截已存区域 → OCR → 静默复制。"""
    threading.Thread(target=trigger_preset, args=(slot,), daemon=True).start()


def on_activate_monitor():
    """锁定区域轮询监控：框选区域后持续 OCR 刷新结果窗口。再次按下 → 停止。

    框选在 UI 线程进行（热键由 UI 线程派发，RegionSelector 用嵌套消息循环）。
    """
    global region_sel, _active_mode
    if not HAS_WIN32:
        print("[监控] 需要 pywin32（Windows）。已跳过。")
        return
    # 运行中再次触发 → 停止监控
    if monitor_state["running"]:
        stop_monitor()
        show_toast("已停止区域监控")
        return
    if not _lock.acquire(blocking=False):
        return  # 上一轮（区域/定义/框选）还在跑，忽略
    try:
        mon = get_monitor(MONITOR)
        sel = RegionSelector()
        sel.cancel_hint = MONITOR_HOTKEY_PRETTY
        region_sel = sel
        _active_mode = "monitor"
        confirmed, rects = sel.select(mon)
        region_sel = None
        _active_mode = None
        if not confirmed or not rects:
            return
        # 隐藏结果窗口，避免被截进屏幕
        result_win.hide()
        start_monitor(rects, MONITOR, MONITOR_INTERVAL)
        show_toast("已开始区域监控")
    except Exception as e:
        print(f"[监控] 出错: {e}")
    finally:
        region_sel = None
        _active_mode = None
        _lock.release()


def on_activate_define(slot):
    """定义选区：进入框选并把区域存为槽位 slot 的预设。"""
    global region_sel, _active_mode, _active_slot
    if not HAS_WIN32:
        print("[定义] 区域选择模式需要 pywin32（Windows）。已跳过。")
        return
    # 若已有“同槽位定义”框选在进行，再次按定义键 = 取消
    if region_sel is not None and getattr(region_sel, "hwnd", None):
        if _active_mode == "define" and _active_slot == slot:
            win32gui.PostMessage(region_sel.hwnd, WM_REGION_CANCEL, 0, 0)
        return
    threading.Thread(target=do_define_preset, args=(slot,), daemon=True).start()




# ----------------- 系统托盘（桌面应用形态） -----------------
def _app_dir():
    """返回程序所在目录：打包后为 exe 目录，开发时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_log_path():
    """返回日志文件路径（与 setup_logging 写入的位置一致）。"""
    return os.path.join(_app_dir(), "ocrclient.log")


def _rotate_log_if_needed(log_path, max_bytes=2 * 1024 * 1024, backups=3):
    """启动时按大小轮转日志：ocrclient.log 超过 max_bytes 则 .1/.2/.3 整体后移，最旧丢弃。

    注：轮转在每次启动 setup_logging 时进行（托盘常驻程序通常随系统/手动重启），
    单次超长运行期内不轮转，足以避免日志无限增长。
    """
    try:
        if not os.path.exists(log_path) or os.path.getsize(log_path) <= max_bytes:
            return
        oldest = f"{log_path}.{backups}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(backups - 1, 0, -1):
            src = f"{log_path}.{i}"
            if os.path.exists(src):
                os.rename(src, f"{log_path}.{i + 1}")
        os.rename(log_path, f"{log_path}.1")
    except Exception as e:
        print(f"[日志] 轮转失败（忽略）: {e}")


def setup_logging():
    """无控制台（frozen）时把 stdout/stderr 重定向到日志文件，便于排障。

    优先用 win32file 以 FILE_SHARE_READ 打开：日志查看器可在程序运行期间并发读取
    该文件而不被“独占锁”挡住（默认 open() 的共享模式为 0，会阻止其它句柄读取）。
    不支持 win32file 时退回普通追加打开（此时查看器可能无法实时读取被占用的文件）。
    """
    log_path = get_log_path()
    _rotate_log_if_needed(log_path)

    if not HAS_WIN32FILE:
        try:
            fh = open(log_path, "a", encoding="utf-8", buffering=1)
        except Exception as e:
            print(f"[日志] 无法写入日志文件 {log_path}: {e}")
            return

        class _Tee:
            def write(self, s):
                try:
                    fh.write(s)
                except Exception:
                    pass
                return len(s) if isinstance(s, str) else 1

            def flush(self):
                try:
                    fh.flush()
                except Exception:
                    pass

            def isatty(self):
                return False

        sys.stdout = _Tee()
        sys.stderr = _Tee()
        print(f"[日志] 输出已重定向到 {log_path}")
        return

    try:
        h = win32file.CreateFile(
            log_path,
            win32file.GENERIC_WRITE,
            win32file.FILE_SHARE_READ,   # 允许日志查看器并发读取
            None,
            win32file.OPEN_ALWAYS,
            win32con.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        win32file.SetFilePointer(h, 0, win32file.FILE_END)  # 追加到末尾，不覆盖历史
    except Exception as e:
        print(f"[日志] 无法写入日志文件 {log_path}: {e}")
        return

    class _FileTee:
        def __init__(self, handle):
            self._h = handle

        def write(self, s):
            data = s.encode("utf-8", "replace") if isinstance(s, str) else bytes(s)
            try:
                win32file.WriteFile(self._h, data)
            except Exception:
                pass
            return len(s) if isinstance(s, str) else 1

        def flush(self):
            try:
                win32file.FlushFileBuffers(self._h)
            except Exception:
                pass

        def isatty(self):
            return False

    sys.stdout = _FileTee(h)
    sys.stderr = _FileTee(h)
    print(f"[日志] 输出已重定向到 {log_path}")


def build_tray_icon_image():
    """用 PIL 绘制「拾字」图标（渐变磁贴 + 白字「字」，无需外部素材）。

    与 assets/icon.ico 同源设计，但按托盘小尺寸（约 16px 展示）做简化：
    省去取景框、放大主字，保证缩小后仍清晰可辨。
    """
    size = 64
    top, bot = (37, 99, 235), (6, 182, 212)     # 品牌渐变：蓝 -> 青
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = base.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b, 255)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=14, fill=255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(base, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, size - 2, size - 2], radius=13,
                        outline=(255, 255, 255, 50), width=1)
    fnt = None
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
        try:
            fnt = ImageFont.truetype(name, int(size * 0.60))
            break
        except Exception:
            continue
    if fnt is None:
        fnt = ImageFont.load_default()
    d.text((size // 2, size // 2), "字", font=fnt,
           fill=(255, 255, 255, 255), anchor="mm")
    return img


def _show_about_modal(hwnd):
    """在窗口所属线程中以本窗口为 owner 弹出原生模态“关于”框（线程安全）。

    必须在本窗口消息循环所在线程调用（ui_loop 线程）；若在托盘线程直接调用，
    会表现为“确定”点不动、关不掉。首启自动弹窗与生产托盘菜单的“关于”共用本函数。
    """
    if not HAS_WIN32 or not hwnd:
        print(_about_text())
        return
    try:
        _bring_to_front(hwnd)
        win32gui.MessageBox(
            hwnd, _about_text(), "关于 · 拾字 PickText",
            win32con.MB_OK | win32con.MB_ICONINFORMATION
            | win32con.MB_SETFOREGROUND | win32con.MB_TOPMOST,
        )
        print("[UI] 关于弹窗已关闭。")
    except Exception as e:
        print(f"[UI] 关于弹窗异常: {e}")


def show_about():
    """托盘菜单“关于”：把弹窗转交 UI 线程执行（PostMessage），托盘回调立即返回。

    关键：绝不能在 pystray 的菜单回调线程里直接调 win32gui.MessageBox——
    它会阻塞托盘线程的消息循环且弹窗交互异常（表现为“确定”点不动、关不掉）。
    """
    if not HAS_WIN32:
        print(_about_text())
        return
    if result_win is not None and result_win.ready and result_win.hwnd:
        win32gui.PostMessage(result_win.hwnd, WM_ABOUT_SHOW, 0, 0)
        return
    # 结果窗口尚未就绪（罕见）：退回控制台输出，避免在托盘线程弹框
    print(_about_text())


def show_log_viewer():
    """托盘菜单“运行日志”：把查看窗口转交 UI 线程执行（PostMessage），托盘回调立即返回。

    与 show_about 同理，绝不在托盘线程直接创建/操作 Win32 窗口。
    """
    if not HAS_WIN32:
        print("[日志] 运行日志路径：%s" % get_log_path())
        return
    if result_win is not None and result_win.ready and result_win.hwnd:
        win32gui.PostMessage(result_win.hwnd, WM_LOG_VIEW_SHOW, 0, 0)
        return
    print("[日志] 结果窗口尚未就绪，无法打开日志查看器；日志文件位于：%s" % get_log_path())


def on_tray_exit(icon, item):
    """托盘"退出"：停止热键监听与托盘图标，干净退出。"""
    try:
        stop_hotkey_listener()
        stop_esc_listener()
    except Exception:
        pass
    try:
        icon.stop()
    except Exception:
        pass
    os._exit(0)


def run_tray():
    """在独立线程中运行系统托盘图标（不阻塞热键主线程）。"""
    if not HAS_TRAY:
        return
    try:
        icon = pystray.Icon(
            "ScreenOCR",
            build_tray_icon_image(),
            "拾字（离线）",
            menu=pystray.Menu(
                pystray.MenuItem("开始监控区域...", start_monitor_from_tray,
                                 visible=lambda item: not is_monitoring()),
                pystray.MenuItem("停止监控", stop_monitor_from_tray,
                                 visible=lambda item: is_monitoring()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("快捷键设置...", open_hotkey_settings_from_tray),
                pystray.MenuItem("OCR 选项...", open_ocr_settings_from_tray),
                pystray.MenuItem("运行日志", show_log_viewer),
                pystray.MenuItem("关于 / 快捷键", show_about),
                pystray.MenuItem("退出", on_tray_exit),
            ),
        )
        icon.run()
    except Exception as e:
        print(f"[托盘] 启动失败，退回无托盘模式: {e}")


def start_monitor_from_tray(icon, item):
    """托盘“开始监控区域”：在 UI 线程弹框选并启动（与其他弹层一致的请求方式）。"""
    if HAS_WIN32 and result_win is not None and result_win.hwnd:
        win32gui.PostMessage(result_win.hwnd, WM_MONITOR_START, 0, 0)


def stop_monitor_from_tray(icon, item):
    """托盘“停止监控”：停止后台轮询，保留结果窗口内容。"""
    stop_monitor()
    show_toast("已停止区域监控")


# ----------------- 快捷键设置弹层（系统托盘 → 原生对话框） -----------------
# 弹层由 UI 线程（result_win 所属线程）以嵌套消息循环弹出，避免阻塞托盘回调。
if HAS_WIN32:
    WM_HOTKEY_SETTINGS_SHOW = win32con.WM_APP + 5  # 由 UI 线程弹出设置弹层
    WM_OCR_SETTINGS_SHOW = win32con.WM_APP + 6     # 由 UI 线程弹出 OCR 选项弹层
else:
    WM_HOTKEY_SETTINGS_SHOW = 0
    WM_OCR_SETTINGS_SHOW = 0


def vk_to_pynput(vk):
    """把当前按下的按键（含修饰键状态）转成 pynput 热键字符串。

    返回 (combo_str, main_key)；main_key 为 None 表示不支持的按键。
    """
    ctrl = (win32api.GetKeyState(win32con.VK_CONTROL) & 0x8000) != 0
    alt = (win32api.GetKeyState(win32con.VK_MENU) & 0x8000) != 0
    shift = (win32api.GetKeyState(win32con.VK_SHIFT) & 0x8000) != 0
    win = ((win32api.GetKeyState(win32con.VK_LWIN) & 0x8000) != 0
           or (win32api.GetKeyState(win32con.VK_RWIN) & 0x8000) != 0)
    parts = []
    if ctrl:
        parts.append("<ctrl>")
    if alt:
        parts.append("<alt>")
    if shift:
        parts.append("<shift>")
    if win:
        parts.append("<cmd>")
    main = None
    if 0x30 <= vk <= 0x39:
        main = chr(vk)                # 0-9
    elif 0x41 <= vk <= 0x5A:
        main = chr(vk).lower()        # A-Z
    elif vk == win32con.VK_ESCAPE:
        main = "<esc>"
    elif vk == win32con.VK_SPACE:
        main = "<space>"
    elif vk == win32con.VK_TAB:
        main = "<tab>"
    elif vk == win32con.VK_RETURN:
        main = "<enter>"
    elif win32con.VK_F1 <= vk <= win32con.VK_F12:
        main = "f" + str(vk - win32con.VK_F1 + 1)
    combo = "+".join(parts + [main]) if main else None
    return combo, main


def _find_hotkey_conflicts(cfg):
    """返回冲突项 {热键字符串: [动作名, ...]}（同一组合被多个动作占用）。"""
    items = [("全屏识别", cfg["full"]),
             ("区域选择", cfg["region"]),
             ("关闭/取消", cfg["close"])]
    for n in range(1, PRESET_SLOTS + 1):
        items.append((f"选区触发{n}", cfg["trigger_tmpl"] % n))
        items.append((f"选区定义{n}", cfg["define_tmpl"] % n))
    by = {}
    for name, hk in items:
        if not hk:
            continue
        by.setdefault(hk, []).append(name)
    return {hk: ns for hk, ns in by.items() if len(ns) > 1}


_settings_open = False


def open_hotkey_settings(owner_hwnd):
    """在 UI 线程弹出「快捷键设置」弹层（嵌套消息循环）。"""
    global _settings_open
    if _settings_open:
        return  # 防止重复打开
    if not HAS_WIN32:
        print("[设置] 需要 pywin32（Windows）才能打开设置窗口。")
        return
    _settings_open = True
    try:
        dlg = HotkeySettingsDialog(owner_hwnd)
        dlg.run()
    except Exception as e:
        print(f"[设置] 打开失败: {e}")
    finally:
        _settings_open = False


def open_hotkey_settings_from_tray(icon, item):
    """托盘菜单回调：把打开请求转交 UI 线程（PostMessage），立即返回。"""
    if result_win is not None and result_win.ready and result_win.hwnd:
        win32gui.PostMessage(result_win.hwnd, WM_HOTKEY_SETTINGS_SHOW, 0, 0)
    else:
        print("[设置] 结果窗口尚未就绪，无法打开快捷键设置。")


class HotkeySettingsDialog:
    """系统托盘「快捷键设置」弹层：可录制并修改各项快捷键，
    实时检测冲突并提示；保存时再次校验，冲突则阻止。"""

    # (配置键, 显示名, 是否模板(以 1-9 结尾))
    ITEMS = [
        ("full", "全屏识别", False),
        ("region", "区域选择", False),
        ("close", "关闭/取消", False),
        ("trigger_tmpl", "选区触发 (1-9)", True),
        ("define_tmpl", "选区定义 (1-9)", True),
    ]

    def __init__(self, owner):
        self.owner = owner
        self.hwnd = None
        self.edits = {}
        self.record_btns = {}
        self.status = None
        self.values = dict(CFG)
        self.recording = None
        self._inst = None
        self._atom = None

    def _display(self, key):
        v = self.values[key]
        if key in ("trigger_tmpl", "define_tmpl"):
            return _pretty(v % 1) + "  (1-9)"
        return _pretty(v)

    def _set_status(self, text):
        try:
            win32gui.SendMessage(self.status, win32con.WM_SETTEXT, 0, text)
        except Exception:
            pass

    def _refresh_conflict(self):
        c = _find_hotkey_conflicts(self.values)
        if not c:
            self._set_status("未检测到冲突。修改后点「确定」即可即时生效。")
        else:
            parts = [f"{_pretty(hk)}  →  {'、'.join(ns)}" for hk, ns in c.items()]
            self._set_status("⚠ 快捷键冲突：\n" + "\n".join(parts)
                             + "\n（保存时会被阻止，请先修改）")

    def _refresh_edit(self, key):
        try:
            win32gui.SendMessage(self.edits[key], win32con.WM_SETTEXT, 0,
                                 self._display(key))
        except Exception:
            pass

    def build(self):
        self._inst = win32api.GetModuleHandle(None)
        wc = win32gui.WNDCLASS()
        wc.hInstance = self._inst
        wc.lpszClassName = "OCRHotkeySettingsDlg"
        wc.lpfnWndProc = self._wndproc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_BTNFACE + 1
        self._atom = win32gui.RegisterClass(wc)

        w, h = 520, 530
        cx = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        x = max(0, (cx - w) // 2)
        y = 110
        style = win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_SYSMENU
        self.hwnd = win32gui.CreateWindow(
            self._atom, "快捷键设置", style,
            x, y, w, h, self.owner or 0, 0, self._inst, None,
        )
        self.header = win32gui.CreateWindow(
            "STATIC",
            "点击「录制」后按下新快捷键；再点一次「录制」可取消。冲突会立即提示。",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_LEFT,
            16, 12, w - 32, 40, self.hwnd, 10, self._inst, None,
        )

        row_h = 54
        top = 60
        self.labels = []
        for i, (key, name, _t) in enumerate(self.ITEMS):
            ry = top + i * row_h
            lbl = win32gui.CreateWindow(
                "STATIC", name,
                win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_LEFT,
                16, ry + 6, 150, 24, self.hwnd, 100 + i, self._inst, None,
            )
            self.labels.append(lbl)
            e = win32gui.CreateWindow(
                "EDIT", self._display(key),
                win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_BORDER
                | win32con.ES_READONLY,
                172, ry + 4, 208, 26, self.hwnd, 200 + i, self._inst, None,
            )
            self.edits[key] = e
            b = win32gui.CreateWindow(
                "BUTTON", "录制",
                win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
                392, ry + 4, 112, 26, self.hwnd, 300 + i, self._inst, None,
            )
            self.record_btns[key] = b

        status_y = top + len(self.ITEMS) * row_h + 4
        self.status = win32gui.CreateWindow(
            "EDIT", "",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_BORDER
            | win32con.WS_VSCROLL | win32con.ES_MULTILINE
            | win32con.ES_AUTOVSCROLL | win32con.ES_READONLY,
            16, status_y, w - 32, 96, self.hwnd, 900, self._inst, None,
        )
        btn_y = status_y + 106
        win32gui.CreateWindow(
            "BUTTON", "恢复默认",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            16, btn_y, 110, 32, self.hwnd, 903, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "取消",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            w - 220, btn_y, 100, 32, self.hwnd, 902, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "确定",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON
            | win32con.BS_DEFPUSHBUTTON,
            w - 110, btn_y, 94, 32, self.hwnd, 901, self._inst, None,
        )

        # 中文字体
        try:
            lf = win32gui.LOGFONT()
            lf.lfHeight = -15
            lf.lfFaceName = "Microsoft YaHei"
            hf = win32gui.CreateFontIndirect(lf)
            ctrls = (list(self.edits.values()) + list(self.record_btns.values())
                     + list(getattr(self, "labels", [])))
            ctrls.append(self.status)
            if getattr(self, "header", None):
                ctrls.append(self.header)
            for hw in ctrls:
                win32gui.SendMessage(hw, win32con.WM_SETFONT, hf, 1)
        except Exception:
            pass

        self._refresh_conflict()

    def _begin_record(self, key):
        self.recording = key
        try:
            win32gui.SetWindowText(self.record_btns[key], "停止")
        except Exception:
            pass
        try:
            _bring_to_front(self.hwnd)
        except Exception:
            pass
        try:
            win32gui.SetFocus(self.hwnd)  # 关键：焦点给对话框本身才能收到 WM_KEYDOWN
        except Exception:
            pass
        self._set_status("请按下新的快捷键组合…（再点「停止」可取消）")

    def _end_record(self, cancelled=False):
        if self.recording is None:
            return
        key = self.recording
        self.recording = None
        try:
            win32gui.SetWindowText(self.record_btns[key], "录制")
        except Exception:
            pass
        if not cancelled:
            self._refresh_edit(key)
            self._refresh_conflict()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_COMMAND:
            cid = wparam & 0xFFFF
            if 300 <= cid < 300 + len(self.ITEMS):
                key = self.ITEMS[cid - 300][0]
                if self.recording == key:
                    self._end_record(cancelled=True)
                else:
                    if self.recording is not None:
                        self._end_record(cancelled=True)
                    self._begin_record(key)
                return 0
            if cid == 901:
                self._on_ok()
                return 0
            if cid == 902:
                self._close()
                return 0
            if cid == 903:
                self.values = dict(DEFAULT_HOTKEYS)
                for k in self.edits:
                    self._refresh_edit(k)
                self._refresh_conflict()
                self._set_status("已恢复默认快捷键，点「确定」保存生效。")
                return 0
            return 0
        if msg == win32con.WM_KEYDOWN:
            if self.recording is not None:
                vk = wparam
                # 忽略单独的修饰键，等待主键
                if vk in (win32con.VK_CONTROL, win32con.VK_MENU,
                          win32con.VK_SHIFT):
                    return 0
                combo, main = vk_to_pynput(vk)
                key = self.recording
                is_tmpl = dict((k, t) for k, _, t in self.ITEMS)[key]
                if combo is None:
                    self._end_record(cancelled=True)
                    self._set_status("⚠ 该按键暂不支持，请换一个组合"
                                     "（如 Ctrl+Alt+字母/数字）。")
                    return 0
                if is_tmpl:
                    if main not in "123456789":
                        self._end_record(cancelled=True)
                        self._set_status("⚠ 选区快捷键需以数字 1-9 结尾"
                                         "（用于区分槽位），请重录。")
                        return 0
                    combo = combo.rsplit("+", 1)[0] + "+%d"
                self.values[key] = combo
                self._end_record()
                return 0
        if msg == win32con.WM_CLOSE:
            self._close()
            return 0
        if msg == win32con.WM_DESTROY:
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_ok(self):
        # 保存前最终冲突校验
        conflicts = _find_hotkey_conflicts(self.values)
        if conflicts:
            parts = [f"• {_pretty(hk)} ：{'、'.join(ns)}"
                     for hk, ns in conflicts.items()]
            msg = ("检测到以下快捷键冲突，请修改后再保存：\n\n"
                   + "\n".join(parts))
            win32gui.MessageBox(
                self.hwnd, msg, "快捷键冲突",
                win32con.MB_OK | win32con.MB_ICONWARNING | win32con.MB_TOPMOST,
            )
            return
        # 应用并即时生效
        old = dict(CFG)
        apply_config(self.values)
        ok, failures = start_hotkey_listener()
        if not ok:
            # 注册失败（被其它程序/系统占用）→ 回退到原设置并明确提示冲突
            apply_config(old)
            start_hotkey_listener()   # 恢复旧热键
            lines = "\n".join(f"• {hk}（{name}）：{reason}"
                              for (hk, name, reason) in failures)
            win32gui.MessageBox(
                self.hwnd,
                "以下快捷键与其他程序/系统冲突，已恢复原有设置：\n\n" + lines,
                "快捷键冲突",
                win32con.MB_OK | win32con.MB_ICONERROR | win32con.MB_TOPMOST,
            )
            return
        save_hotkey_config(self.values)
        show_toast("快捷键已更新并生效")
        self._close()

    def _close(self):
        try:
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
        except Exception:
            pass
        try:
            win32gui.PostQuitMessage(0)
        except Exception:
            pass

    def run(self):
        self.build()
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        try:
            _bring_to_front(self.hwnd)
        except Exception:
            pass
        win32gui.PumpMessages()  # 嵌套消息循环，直到 DestroyWindow + PostQuitMessage
        try:
            if self._atom is not None and self._inst is not None:
                win32gui.UnregisterClass("OCRHotkeySettingsDlg", self._inst)
        except Exception:
            pass


# ----------------- OCR 选项弹层（系统托盘 → 原生对话框） -----------------
_ocr_settings_open = False


class OcrSettingsDialog:
    """系统托盘「OCR 选项」弹层：排版（横/竖）、输出（简/繁）、自动标点（关/规则）。"""

    def __init__(self, owner):
        self.owner = owner
        self.hwnd = None
        self.chk_vertical = None
        self.chk_traditional = None
        self.chk_punct = None
        self._inst = None
        self._atom = None
        self.values = dict(OCR_CFG)

    def build(self):
        self._inst = win32api.GetModuleHandle(None)
        wc = win32gui.WNDCLASS()
        wc.hInstance = self._inst
        wc.lpszClassName = "OCROptionsDlg"
        wc.lpfnWndProc = self._wndproc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_BTNFACE + 1
        self._atom = win32gui.RegisterClass(wc)

        w, h = 460, 340
        cx = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        x = max(0, (cx - w) // 2)
        y = 150
        style = win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_SYSMENU
        self.hwnd = win32gui.CreateWindow(
            self._atom, "OCR 选项", style,
            x, y, w, h, self.owner or 0, 0, self._inst, None,
        )
        win32gui.CreateWindow(
            "STATIC",
            "竖排：按“上→下、右→左”重排（古籍/字幕）\n"
            "繁体：简体→繁体（OpenCC 离线）\n"
            "标点：离线规则补句读（保守，供初稿）",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_LEFT,
            20, 14, w - 40, 64, self.hwnd, 10, self._inst, None,
        )
        self.chk_vertical = win32gui.CreateWindow(
            "BUTTON", "竖排模式（上→下、右→左）",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_AUTOCHECKBOX,
            24, 90, 400, 28, self.hwnd, 1, self._inst, None,
        )
        self.chk_traditional = win32gui.CreateWindow(
            "BUTTON", "输出繁体（简→繁，OpenCC 离线）",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_AUTOCHECKBOX,
            24, 124, 400, 28, self.hwnd, 2, self._inst, None,
        )
        self.chk_punct = win32gui.CreateWindow(
            "BUTTON", "自动标点（离线规则，补句读）",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_AUTOCHECKBOX,
            24, 158, 400, 28, self.hwnd, 3, self._inst, None,
        )
        win32gui.SendMessage(self.chk_vertical, win32con.BM_SETCHECK,
                             1 if self.values.get("vertical") else 0, 0)
        win32gui.SendMessage(self.chk_traditional, win32con.BM_SETCHECK,
                             1 if self.values.get("traditional") else 0, 0)
        win32gui.SendMessage(self.chk_punct, win32con.BM_SETCHECK,
                             1 if self.values.get("punctuate") == "rule" else 0, 0)
        try:
            lf = win32gui.LOGFONT()
            lf.lfHeight = -15
            lf.lfFaceName = "Microsoft YaHei"
            hf = win32gui.CreateFontIndirect(lf)
            for hw in (self.chk_vertical, self.chk_traditional, self.chk_punct):
                win32gui.SendMessage(hw, win32con.WM_SETFONT, hf, 1)
        except Exception:
            pass
        win32gui.CreateWindow(
            "BUTTON", "取消",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            w - 220, h - 48, 100, 32, self.hwnd, 902, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "确定",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON
            | win32con.BS_DEFPUSHBUTTON,
            w - 110, h - 48, 94, 32, self.hwnd, 901, self._inst, None,
        )

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_COMMAND:
            cid = wparam & 0xFFFF
            if cid == 901:
                self._on_ok()
                return 0
            if cid == 902:
                self._close()
                return 0
            return 0
        if msg == win32con.WM_CLOSE:
            self._close()
            return 0
        if msg == win32con.WM_DESTROY:
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_ok(self):
        vertical = win32gui.SendMessage(
            self.chk_vertical, win32con.BM_GETCHECK, 0, 0) == 1
        traditional = win32gui.SendMessage(
            self.chk_traditional, win32con.BM_GETCHECK, 0, 0) == 1
        punct = win32gui.SendMessage(
            self.chk_punct, win32con.BM_GETCHECK, 0, 0) == 1
        cfg = {
            "vertical": vertical,
            "traditional": traditional,
            "punctuate": "rule" if punct else "off",
        }
        apply_ocr_config(cfg)
        save_ocr_config(cfg)
        show_toast("OCR 选项已更新")
        self._close()

    def _close(self):
        try:
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
        except Exception:
            pass
        try:
            win32gui.PostQuitMessage(0)
        except Exception:
            pass

    def run(self):
        self.build()
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        try:
            _bring_to_front(self.hwnd)
        except Exception:
            pass
        win32gui.PumpMessages()
        try:
            if self._atom is not None and self._inst is not None:
                win32gui.UnregisterClass("OCROptionsDlg", self._inst)
        except Exception:
            pass


def open_ocr_settings(owner_hwnd):
    """在 UI 线程弹出「OCR 选项」弹层（嵌套消息循环）。"""
    global _ocr_settings_open
    if _ocr_settings_open:
        return  # 防止重复打开
    if not HAS_WIN32:
        print("[OCR设置] 需要 pywin32（Windows）才能打开设置窗口。")
        return
    _ocr_settings_open = True
    try:
        dlg = OcrSettingsDialog(owner_hwnd)
        dlg.run()
    except Exception as e:
        print(f"[OCR设置] 打开失败: {e}")
    finally:
        _ocr_settings_open = False


def open_ocr_settings_from_tray(icon, item):
    """托盘菜单回调：把打开请求转交 UI 线程（PostMessage），立即返回。"""
    if result_win is not None and result_win.ready and result_win.hwnd:
        win32gui.PostMessage(result_win.hwnd, WM_OCR_SETTINGS_SHOW, 0, 0)
    else:
        print("[OCR设置] 结果窗口尚未就绪，无法打开 OCR 选项。")


# ----------------- 运行日志查看窗口（系统托盘 → 原生对话框） -----------------
def read_log_content(path, max_chars=200000):
    """读取日志文件内容；过大时只返回末尾 max_chars 并提示。"""
    if not os.path.exists(path):
        return "(日志文件尚不存在，程序运行一会儿后这里会记录输出。)"
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            if size > max_chars:
                f.seek(max(0, size - max_chars))
                data = f.read()
                # 跳过被截断的半行，从下一个完整行开始
                if data and not data.startswith("\n"):
                    nl = data.find("\n")
                    if nl != -1:
                        data = data[nl + 1:]
                return ("（仅显示最近约 %dKB，完整日志请点“打开日志文件”）\n\n"
                        % (max_chars // 1000)) + data
            return f.read()
    except Exception as e:
        return f"（读取日志失败：{e}）"


_log_viewer_open = False


def open_log_viewer(owner_hwnd):
    """在 UI 线程弹出「运行日志」查看窗口（嵌套消息循环）。"""
    global _log_viewer_open
    if _log_viewer_open:
        return  # 防止重复打开
    if not HAS_WIN32:
        print("[日志] 需要 pywin32（Windows）才能打开日志窗口。")
        return
    _log_viewer_open = True
    try:
        dlg = LogViewerDialog(owner_hwnd)
        dlg.run()
    except Exception as e:
        print(f"[日志] 打开失败: {e}")
    finally:
        _log_viewer_open = False


class LogViewerDialog:
    """系统托盘「运行日志」查看窗口：只读展示 ocrclient.log 的实时内容。

    提供「刷新」重新读取文件、「复制全部」复制到剪贴板、「打开日志文件」用系统
    默认程序打开日志，「关闭」退出。窗口由 UI 线程以嵌套消息循环驱动，避免阻塞
    托盘回调。日志文件已被 setup_logging 以 FILE_SHARE_READ 打开，可并发读取。
    """

    def __init__(self, owner):
        self.owner = owner
        self.hwnd = None
        self.edit = None
        self._inst = None
        self._atom = None
        self.log_path = get_log_path()

    def _load(self):
        content = read_log_content(self.log_path)
        try:
            win32gui.SendMessage(self.edit, win32con.WM_SETTEXT, 0, content)
            # 滚动到底部
            win32gui.SendMessage(self.edit, win32con.WM_VSCROLL,
                                 win32con.SB_BOTTOM, 0)
        except Exception:
            pass

    def _copy(self):
        try:
            text = win32gui.GetWindowText(self.edit)
            if text:
                pyperclip.copy(text)
                show_toast("日志已复制到剪贴板")
        except Exception as e:
            print(f"[日志] 复制失败: {e}")

    def _open_file(self):
        try:
            os.startfile(self.log_path)
        except Exception as e:
            print(f"[日志] 打开文件失败: {e}")

    def build(self):
        self._inst = win32api.GetModuleHandle(None)
        wc = win32gui.WNDCLASS()
        wc.hInstance = self._inst
        wc.lpszClassName = "OCRLogViewerDlg"
        wc.lpfnWndProc = self._wndproc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_BTNFACE + 1
        self._atom = win32gui.RegisterClass(wc)

        w, h = 640, 480
        cx = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        x = max(0, (cx - w) // 2)
        y = 90
        style = (win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_SYSMENU
                 | win32con.WS_THICKFRAME | win32con.WS_VSCROLL)
        self.hwnd = win32gui.CreateWindow(
            self._atom, "运行日志 - ocrclient.log", style,
            x, y, w, h, self.owner or 0, 0, self._inst, None,
        )
        self.edit = win32gui.CreateWindow(
            "EDIT", "",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_BORDER
            | win32con.WS_VSCROLL | win32con.WS_HSCROLL
            | win32con.ES_MULTILINE | win32con.ES_AUTOVSCROLL
            | win32con.ES_AUTOHSCROLL | win32con.ES_READONLY,
            12, 12, w - 24, h - 70, self.hwnd, 1, self._inst, None,
        )
        try:
            lf = win32gui.LOGFONT()
            lf.lfHeight = -15
            lf.lfFaceName = "Microsoft YaHei"
            hf = win32gui.CreateFontIndirect(lf)
            win32gui.SendMessage(self.edit, win32con.WM_SETFONT, hf, 1)
        except Exception:
            pass

        # 底部按钮区
        btn_w, btn_h, gap = 150, 32, 12
        total = btn_w * 3 + gap * 2
        bx = max(12, (w - total) // 2)
        by = h - 48
        win32gui.CreateWindow(
            "BUTTON", "刷新",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            bx, by, btn_w, btn_h, self.hwnd, 2, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "复制全部",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            bx + btn_w + gap, by, btn_w, btn_h, self.hwnd, 3, self._inst, None,
        )
        win32gui.CreateWindow(
            "BUTTON", "打开日志文件",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            bx + (btn_w + gap) * 2, by, btn_w, btn_h,
            self.hwnd, 4, self._inst, None,
        )
        # 右上角关闭按钮（标题栏也有关闭，这里再给一个显式入口）
        win32gui.CreateWindow(
            "BUTTON", "关闭",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON,
            w - 92, 10, 80, 28, self.hwnd, 5, self._inst, None,
        )
        self._load()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_COMMAND:
            cid = wparam & 0xFFFF
            if cid == 2:
                self._load()
            elif cid == 3:
                self._copy()
            elif cid == 4:
                self._open_file()
            elif cid == 5:
                self._close()
            return 0
        if msg == win32con.WM_CLOSE:
            self._close()
            return 0
        if msg == win32con.WM_DESTROY:
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _close(self):
        try:
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
        except Exception:
            pass
        try:
            win32gui.PostQuitMessage(0)
        except Exception:
            pass

    def run(self):
        self.build()
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        try:
            _bring_to_front(self.hwnd)
        except Exception:
            pass
        win32gui.PumpMessages()  # 嵌套消息循环，直到 DestroyWindow + PostQuitMessage
        try:
            if self._atom is not None and self._inst is not None:
                win32gui.UnregisterClass("OCRLogViewerDlg", self._inst)
        except Exception:
            pass


def main():
    if "--version" in sys.argv:
        print(f"PickText {__version__}")
        return
    # 桌面应用形态：打包后（frozen）默认启用系统托盘；可用 --tray 强制、--no-tray 禁用
    force_tray = "--tray" in sys.argv
    disable_tray = "--no-tray" in sys.argv
    tray_mode = (getattr(sys, "frozen", False) or force_tray) and not disable_tray
    if tray_mode:
        # 单实例：检测到已有实例在运行，提示后退出（仅桌面形态启用，避免影响开发/控制台调试）
        if _another_instance_running():
            try:
                win32gui.MessageBox(
                    0, "拾字 已在运行。", "提示",
                    win32con.MB_OK | win32con.MB_ICONINFORMATION | win32con.MB_TOPMOST,
                )
            except Exception:
                pass
            os._exit(0)
        setup_logging()

    global _FIRST_RUN
    _FIRST_RUN = _is_first_run()  # 首次运行（按机器记录）则自动弹“关于”

    print("=" * 46)
    print("  拾字（PickText）· 屏幕离线取字工具（全屏 + 区域多选 + 选区预设 · 离线）")
    print("=" * 46)
    load_presets()
    print(f"  全屏识别   : {HOTKEY_PRETTY}")
    print(f"  区域选择   : {REGION_HOTKEY_PRETTY}（可框选多个区域）")
    print(f"  识别范围   : {'全部显示器' if MONITOR == 0 else '主显示器'}")
    print(f"  自动复制全部 : {'开' if AUTO_COPY_ALL else '关'}")
    print(f"  结果窗口   : {'开' if SHOW_WINDOW and HAS_WIN32 else '关(控制台)'}")
    print(f"  选区预设   : 定义 {DEFINE_HOTKEY_PRETTY_TMPL % 1}~{DEFINE_HOTKEY_PRETTY_TMPL % PRESET_SLOTS}"
          f" → 触发 {TRIGGER_HOTKEY_PRETTY_TMPL % 1}~{TRIGGER_HOTKEY_PRETTY_TMPL % PRESET_SLOTS}")
    print(f"  已存选区   : {len(presets)} 个（见 region_presets.json）")
    print("  全屏模式：按快捷键识别整屏；区域模式：拖拽框选多区域后右键确认。")
    print("  选区预设：Ctrl+Shift+N 框选存为选区N；之后 Alt+Shift+N 一键识别并静默复制。")
    print("  按 Esc 关闭/取消当前弹窗（结果窗口或选区）；退出程序请右键托盘图标。")
    print("=" * 46)

    threading.Thread(target=ui_loop, daemon=True).start()

    if tray_mode and HAS_TRAY:
        threading.Thread(target=run_tray, daemon=True).start()

    # 全局热键监听已随 UI 线程（result_win）在 ui_loop() 中注册并由其消息泵驱动；
    # 托盘“退出”会停止热键并退出进程。
    # 主线程保持运行，等待托盘退出（Ctrl+C 亦可直接结束）
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
