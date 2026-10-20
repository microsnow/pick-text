"""OCRClient 纯函数单测（pytest）。

仅覆盖不依赖 GUI/模型的纯逻辑，便于回归：换行规整、CJK 判断、热键解析、导出文本转换。
运行：在 ocrclient venv 中 `python -m pytest tests/`。
"""
import os
import sys
import cv2
import numpy as np

# 把项目根目录加入 import 路径，使 `import main` 可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
import layout  # noqa: E402


def test_crlf_idempotent():
    assert main._crlf("a\nb") == "a\r\nb"
    assert main._crlf("a\r\nb") == "a\r\nb"      # 幂等：不会双重换行
    assert main._crlf("") == ""


def test_is_cjk():
    assert main._is_cjk("中") is True
    assert main._is_cjk("A") is False
    assert main._is_cjk("！") is True   # 全角标点
    assert main._is_cjk("") is False


def test_parse_hotkey_mods():
    mods, vk = main._parse_hotkey("<cmd>+<alt>+o")
    assert mods & 0x0008                 # MOD_WIN
    assert mods & 0x0001                 # MOD_ALT
    mods2, _ = main._parse_hotkey("ctrl+shift+1")
    assert mods2 & 0x0002                # MOD_CONTROL
    assert mods2 & 0x0004                # MOD_SHIFT


def test_parse_hotkey_requires_mod_and_key():
    for bad in ("o", "ctrl"):            # 缺修饰键 / 缺主键都应抛错
        try:
            main._parse_hotkey(bad)
            raised = False
        except ValueError:
            raised = True
        assert raised


def test_text_to_markdown():
    out = main._text_to_markdown("第一行\n\n第二行\n")
    assert out == "第一行\n\n第二行"
    assert "空行" not in main._text_to_markdown("a\n\n\nb")


def test_image_hash_stable_for_identical():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    assert main._image_hash(img) == main._image_hash(img.copy())


def test_image_hash_changes_on_edit():
    a = np.zeros((64, 64, 3), dtype=np.uint8)
    b = np.zeros((64, 64, 3), dtype=np.uint8)
    b[:, 32:] = 255  # 右半变亮：监控区域画面变化应触发 OCR
    assert main._image_hash(a) != main._image_hash(b)


def test_region_bbox_merge_and_clip():
    rects = [(10, 20, 30, 40), (50, 60, 10, 10)]
    assert main._region_bbox(rects, 1000, 800) == (10, 20, 60, 70)
    # 越界裁剪：超出显示器范围的部分被截断
    assert main._region_bbox([(990, 790, 30, 30)], 1000, 800) == (990, 790, 1000, 800)
    # 空区域返回 None
    assert main._region_bbox([], 100, 100) is None


def test_monitor_state_default_off():
    assert main.is_monitoring() is False
    main.monitor_state["running"] = True
    assert main.is_monitoring() is True
    main.monitor_state["running"] = False


# ---------------- 功能2：竖排重排 / 繁体 / 标点 ----------------

def test_reorder_vertical_rtl():
    # 右列（x≈400）两框上下：甲(上) 乙(下)；左列（x≈100）一框：丙
    items = [
        (400, 440, 10, 30, "甲"),
        (400, 440, 40, 60, "乙"),
        (100, 140, 10, 30, "丙"),
    ]
    # 右→左读：先右列(上→下) 再左列 → "甲乙" / "丙"
    assert layout.reorder_vertical(items) == "甲乙\n丙"


def test_reorder_vertical_clusters_same_column():
    # x 重叠的两框聚为一列（上下），并与右侧单列按“右→左”排序：右列先读
    items = [
        (100, 140, 10, 30, "上"),
        (100, 140, 40, 60, "下"),
        (300, 340, 10, 30, "右"),
    ]
    assert layout.reorder_vertical(items) == "右\n上下"


def test_reorder_vertical_empty():
    assert layout.reorder_vertical([]) == ""


def test_merge_horizontal_basic():
    # 横排：CJK 相邻不补空格，拉丁相邻补空格；不同行各自成行
    items = [
        (10, 100, 10, 30, "你好"),
        (110, 200, 10, 30, "世界"),
        (10, 100, 100, 120, "Hello"),
        (110, 200, 100, 120, "World"),
    ]
    assert main._merge_horizontal(items) == "你好世界\nHello World"


def test_add_punctuation_terminal():
    # 短句无标点 → 补句号；已含终止标点则不重复补
    assert layout.add_punctuation("孔子曰学而时习之") == "孔子曰学而时习之。"
    assert layout.add_punctuation("学而时习之。") == "学而时习之。"


def test_add_punctuation_long_line_comma():
    # 长句无标点 → 中点补逗号 + 句末补句号
    out = layout.add_punctuation("吾日三省吾身为人谋而不忠乎与朋友交而不信乎")
    assert "，" in out and out.endswith("。")


def test_add_punctuation_preserves_blanks():
    # 空行保留结构（调试/古籍分段）
    assert layout.add_punctuation("甲\n\n乙") == "甲。\n\n乙。"


def test_to_traditional():
    if layout._HAS_OPENCC:
        assert layout.to_traditional("汉字") == "漢字"
    else:
        # 未安装 OpenCC 时退化为原样，但不报错
        assert layout.to_traditional("汉字") == "汉字"
    assert layout.to_traditional("") == ""


def test_filter_noise_boxes_keeps_cjk():
    # 正常：大号汉字框保留；极小的非汉字短串（引号框误识成 99）被丢弃
    items = [
        (13, 33, 18, 37, "吃"),                 # 正文汉字，保留
        (89, 164, 16, 39, "时间到→"),          # 正文，保留
        (70, 76, 20, 25, "99"),                # 极小非汉字噪声，丢弃
    ]
    out = main._filter_noise_boxes(items)
    texts = [t[4] for t in out]
    assert "吃" in texts and "时间到→" in texts
    assert "99" not in texts


def test_filter_noise_boxes_keeps_tiny_cjk_punct():
    # 极小的“汉字标点”不丢：只要含 CJK 字符就保留
    items = [
        (89, 164, 16, 39, "正文"),
        (70, 76, 20, 25, "，"),                 # 含 CJK 标点，保留
    ]
    out = main._filter_noise_boxes(items)
    assert "，" in [t[4] for t in out]


def test_filter_noise_boxes_single_box_passthrough():
    # 只有一个框时不过滤（避免误删唯一结果）
    items = [(70, 76, 20, 25, "99")]
    assert main._filter_noise_boxes(items) == items


def test_enhance_for_ocr_small_faint_image():
    # 淡灰小图 → 经增强后整体动态范围被拉满（min≈0, max≈255）
    img = np.full((40, 120, 3), 200, dtype=np.uint8)   # 浅灰底
    cv2.rectangle(img, (10, 10), (30, 30), (170, 170, 170), -1)  # 略深的“字”
    out = main._enhance_for_ocr(img)
    g = out[:, :, 0] if out.ndim == 3 else out
    assert int(g.min()) < 30 and int(g.max()) > 220



# ----------------- Win32 低级键盘钩子（Esc）回归测试 -----------------
# 历史背景：本项目原先用 pynput 监听 Esc，为摆脱 LGPL 依赖改为 ctypes 直调
# user32.dll 的 WH_KEYBOARD_LL。以下用例锁住三个极易踩坑的点：
#   1) LPARAM 必须是指针宽度（c_ssize_t），否则 vkCode 读出的是地址碎片；
#   2) CallNextHookEx 必须声明 argtypes，否则整数参数溢出；
#   3) 只认 Esc 按下，keyup / 其它键 / nCode<0 一律透传。
import ctypes
import pytest


def _synth_lparam(vk):
    """构造一个 KBDLLHOOKSTRUCT 并返回其裸地址（等价于 Windows 传来的 lParam）。"""
    return ctypes.cast(
        ctypes.pointer(main._KBDLLHOOKSTRUCT(
            vkCode=vk, scanCode=0, flags=0, time=0, dwExtraInfo=None)),
        ctypes.c_void_p).value


WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
VK_ESCAPE = 0x1B


def test_hook_struct_layout():
    # x64 下应为 24 字节：4 个 DWORD + 一个 8 字节指针
    assert ctypes.sizeof(main._KBDLLHOOKSTRUCT) == 24
    assert main._KBDLLHOOKSTRUCT.vkCode.offset == 0


def test_hook_lparam_is_pointer_sized():
    # 回归点：用 wintypes.LPARAM（有符号 32 位）会截断指针导致 vkCode 读错
    assert ctypes.sizeof(main._LRESULT) == ctypes.sizeof(ctypes.c_void_p)


def test_hook_callback_only_triggers_on_esc_down(monkeypatch):
    fired = []
    monkeypatch.setattr(main, "_post_esc_close", lambda: fired.append(1))
    proc = main._HOOKPROC(main._on_keyboard_ll)

    proc(0, WM_KEYDOWN, _synth_lparam(VK_ESCAPE))     # 应触发
    proc(0, WM_KEYUP, _synth_lparam(VK_ESCAPE))       # 抬起，不触发
    proc(0, WM_KEYDOWN, _synth_lparam(0x4F))           # 'O'，不触发
    proc(-1, WM_KEYDOWN, _synth_lparam(VK_ESCAPE))     # nCode<0，不触发

    assert len(fired) == 1


def test_hook_callback_handles_syskeydown(monkeypatch):
    fired = []
    monkeypatch.setattr(main, "_post_esc_close", lambda: fired.append(1))
    proc = main._HOOKPROC(main._on_keyboard_ll)
    proc(0, WM_SYSKEYDOWN, _synth_lparam(VK_ESCAPE))   # Alt+Esc 等系统键也应触发
    assert len(fired) == 1


def test_hook_callback_swallows_exceptions():
    # lParam 传 0（非法地址）不应抛到钩子外，否则会被系统静默摘钩
    proc = main._HOOKPROC(main._on_keyboard_ll)
    proc(0, WM_KEYDOWN, 0)      # 不抛异常即通过


@pytest.mark.skipif(not main.HAS_WIN32, reason="需要 Windows")
def test_hook_install_uninstall_and_idempotent():
    main.start_esc_listener()
    assert main._esc_hook_hhk is not None, "钩子安装失败"
    handle = main._esc_hook_hhk
    main.start_esc_listener()          # 重复调用不应重复挂钩
    assert main._esc_hook_hhk == handle
    main.stop_esc_listener()
    assert main._esc_hook_hhk is None
    assert main._esc_hook_proc is None

# ----------------- 触发模式：剪贴板一致性回归测试 -----------------
# 历史 bug：触发选区时若识别结果为空，程序不清理剪贴板，用户 Ctrl+V 会粘到
# 上一次的旧文本，误以为"第二次识别失败"。现约定：识别为空 => 清空剪贴板，
# 保证「剪贴板内容」与「本次识别结果」严格一致。
import inspect as _inspect


def _func_source(name):
    return _inspect.getsource(getattr(main, name))


def test_trigger_preset_clears_clipboard_when_empty():
    src = _func_source("trigger_preset")
    # else 分支（未识别到文字）必须清空剪贴板
    else_part = src.split("else:", 1)[1]
    assert '_copy_to_clipboard("", verify=False)' in else_part, "识别为空时未清空剪贴板"


def test_do_ocr_clears_clipboard_when_empty():
    assert '_copy_to_clipboard("", verify=False)' in _func_source("do_ocr")


def test_do_region_ocr_clears_clipboard_when_empty():
    assert '_copy_to_clipboard("", verify=False)' in _func_source("do_region_ocr")


# ----------------- 剪贴板写后读回校验 -----------------
# 背景（真实问题）：日志显示"已静默复制到剪贴板"，但用户 Ctrl+V 粘贴为空或
# 是上一次的旧内容。根因是 Windows 剪贴板为全局共享资源，pyperclip.copy() 在
# 剪贴板被短暂独占 / 被远程桌面或输入法劫持时会**静默失败**（不抛异常）。
# 因此改为：写入后立即读回比对，不一致重试，失败时把原因写进日志。
def test_copy_to_clipboard_verifies_and_returns_ok():
    assert main._copy_to_clipboard("hello test") == (True, "")


def test_copy_to_clipboard_verify_disabled():
    # verify=False 用于清空剪贴板：本就不该有内容，不校验
    ok, _ = main._copy_to_clipboard("", verify=False)
    assert ok is True


def test_copy_to_clipboard_reports_failure(monkeypatch):
    # 模拟"静默失败"：pyperclip.copy 不抛异常但什么都没写
    monkeypatch.setattr(main.pyperclip, "copy", lambda t: None)
    monkeypatch.setattr(main.pyperclip, "paste", lambda: "")
    ok, detail = main._copy_to_clipboard("期望这段内容")
    assert ok is False
    assert "读回不一致" in detail


def test_all_recognize_entries_use_verified_copy():
    import inspect
    for fn in (main.do_ocr, main.do_region_ocr, main.trigger_preset):
        assert "_copy_to_clipboard" in inspect.getsource(fn), \
            f"{fn.__name__} 未使用带校验的剪贴板写入"


def test_trigger_preset_waits_for_window_hidden():
    # 跨线程 hide() 是 PostMessage，截图前必须等窗口真的不可见，
    # 否则本程序的结果窗口会被一并截进去（识别出窗口里的旧文本）。
    src = _func_source("trigger_preset")
    assert "_wait_window_hidden" in src, "截图前未等待结果窗口隐藏"


def test_wait_window_hidden_handles_invalid_hwnd():
    # 无效句柄应立即返回 True（视为已隐藏），绝不能抛异常或长时间阻塞
    assert main._wait_window_hidden(999999, timeout=0.2) is True
    assert main._wait_window_hidden(0, timeout=0.2) is True

# ----------------- Toast 语义色回归测试 -----------------
# 背景：成功与失败的 Toast 原本长得一模一样（深色底+青色边框），用户分不清
# "识别成功" 与 "识别为空"。现按 kind 区分边框色：成功=青 / 失败=红 / 中性=蓝灰，
# 且失败提示停留更久（默认 1600ms -> 2600ms）。
def test_toast_accepts_kind_param():
    import inspect
    sig = inspect.signature(main.show_toast)
    assert "kind" in sig.parameters
    assert sig.parameters["kind"].default == "info"


def test_toastwindow_defaults_to_info():
    t = main.ToastWindow("x", 0, 0, 10, 10, 1600)
    assert t.kind == "info"
    t2 = main.ToastWindow("x", 0, 0, 10, 10, 1600, kind="error")
    assert t2.kind == "error"


def test_failure_toasts_use_error_kind():
    import inspect
    src = inspect.getsource(main.trigger_preset)
    # 触发失败的两处必须用 error 色：未定义选区、未识别到文字
    assert src.count('kind="error"') >= 2, "触发失败提示未使用 error 语义色"


def test_success_toasts_use_ok_kind():
    import inspect
    # do_ocr 不弹 toast（它用结果窗口），只检查真正弹 toast 的入口
    src = inspect.getsource(main.trigger_preset)
    assert 'kind="ok"' in src, "trigger_preset 成功提示未使用 ok 语义色"

# ----------------- 控制台编码加固回归测试 -----------------
# 真实事故：给--selftest 加了 ✓/✗ 标记后，打包版（console=False，输出重定向到
# 管道时编码退化为 GBK）抛 UnicodeEncodeError，PyInstaller 弹出
# "Unhandled exception in script" 对话框，自检与结果文件都没产出。
# 两道修复：(1) 标记只用纯ASCII [OK]/[FAIL]；(2) stdout/stderr 改用 errors='replace'。
def test_stdout_encoding_hardening_exists():
    assert callable(main._harden_stdout_encoding)


def test_harden_stdout_survives_gbk_strict_stdout():
    # 关键回归：GBK 严格编码的 stdout 下，遇到非 GBK 字符不得抛异常
    import io
    buf = io.BytesIO()
    old = sys.stdout
    try:
        sys.stdout = io.TextIOWrapper(buf, encoding="gbk", errors="strict")
        main._harden_stdout_encoding()
        print("测试 \u2713 \u2717 符号")     # ✓ ✗ 在 GBK 中无法编码
        sys.stdout.flush()
        buf.seek(0)
        out = buf.read().decode("gbk")          # 应能解码为含 '?' 的文本
        assert "\u2713" not in out
    finally:
        sys.stdout = old


def test_selftest_marks_are_ascii_only():
    # 自检文案里不得出现 GBK 无法编码的符号（✓/✗/✅ 等）
    import inspect
    src = inspect.getsource(main.main)
    for bad in ("\u2713", "\u2717", "\u2705", "\u274c"):
        assert bad not in src, f"main() 中含GBK 无法编码的符号: {bad!r}"
