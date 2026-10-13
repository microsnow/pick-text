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

