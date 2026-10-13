"""OCRClient 纯函数单测（pytest）。

仅覆盖不依赖 GUI/模型的纯逻辑，便于回归：换行规整、CJK 判断、热键解析、导出文本转换。
运行：在 ocrclient venv 中 `python -m pytest tests/`。
"""
import os
import sys
import numpy as np

# 把项目根目录加入 import 路径，使 `import main` 可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


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
