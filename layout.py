# -*- coding: utf-8 -*-
"""古籍 / 竖排 OCR 后处理：几何重排、繁体转换、离线标点。

所有函数均为“纯函数”，不依赖 Win32，便于在 pytest 中直接单测。
当 opencc-python 未安装时，to_traditional 退化为原样返回（不报错）。
"""
import re

# OpenCC 为可选依赖：未安装时繁体转换失效但不影响其它功能。
try:
    from opencc import OpenCC
    _cc_s2t = OpenCC("s2t")
    _HAS_OPENCC = True
except Exception:  # pragma: no cover - 依赖缺失为环境相关，不做强制
    _cc_s2t = None
    _HAS_OPENCC = False


# 句末终止标点（含全角/半角），用于判断是否需补句号
_TERMINAL = "。！？!?…”）]』」"


def reorder_vertical(items):
    """把竖排版式的检测框按传统阅读顺序重排。

    items: [(x0, x1, y0, y1, text), ...]，坐标来自 RapidOCR 的 4 点多边形
           （已归一为 x/y 的最小/最大值）。

    规则：
      1) 按 x 中心排序后，依据 x 重叠把框聚成“列”；
      2) 列间按 x 中心降序（最右列先读，符合右→左）；
      3) 列内按 y 升序（上→下）；
      4) 每列拼成一行，列与列之间换行。

    RapidOCR 对竖排框通常仍能检出，只是顺序被当成横排，故用纯几何聚类纠正，
    无需更换引擎。返回多行文本（每列一行）。
    """
    if not items:
        return ""
    # 1) 按 x 中心排序后，按 x 重叠聚成“列”
    items_sorted = sorted(items, key=lambda t: (t[0] + t[1]) / 2.0)
    cols = []
    for it in items_sorted:
        x0, x1, _y0, _y1, _text = it
        placed = False
        for col in cols:
            cx0 = min(c[0] for c in col)
            cx1 = max(c[1] for c in col)
            cw = max(1.0, cx1 - cx0)
            iw = max(1.0, x1 - x0)
            inter = min(cx1, x1) - max(cx0, x0)
            # 横向重叠超过较窄框宽度 30% → 视为同一列
            if inter > 0.3 * min(cw, iw):
                col.append(it)
                placed = True
                break
        if not placed:
            cols.append([it])
    # 2) 列按 x 中心降序（最右列先读）
    cols.sort(key=lambda col: -(min(c[0] for c in col) + max(c[1] for c in col)) / 2.0)
    lines = []
    for col in cols:
        col.sort(key=lambda t: t[2])  # 3) 列内按 y 升序（上→下）
        lines.append("".join(t[4] for t in col))
    return "\n".join(lines)


def to_traditional(text):
    """简体 → 繁体（OpenCC s2t，离线）。

    未安装 OpenCC 时原样返回；转换异常也回退原样，保证不崩溃。
    """
    if not text:
        return text
    if not _HAS_OPENCC:
        return text
    try:
        return _cc_s2t.convert(text)
    except Exception:
        return text


def add_punctuation(text):
    """离线规则标点（保守启发式）：补句末句号、长句中点补逗号、去除行内多余空格。

    仅用于古籍采集的“初稿”——最终以人工或可编辑结果为准（结果框可编辑与导出）。
    策略：
      - 去除行内所有空白（古籍 OCR 常夹带无关空格）；
      - 长句（>16 字且无任何标点）在中间补一个逗号，做粗略断句；
      - 行末若为句中停顿（，、；：）或已带终止标点则不补；
      - 否则补句号“。”。
    """
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            out.append("")
            continue
        line = re.sub(r"\s+", "", line)
        # 长句中点补逗号（启发式：无标点且较长）
        if "，" not in line and "、" not in line and "。" not in line and len(line) > 16:
            mid = len(line) // 2
            line = line[:mid] + "，" + line[mid:]
        last = line[-1]
        if last in "，、；：" or last in _TERMINAL:
            pass  # 已是句末或句中停顿，不补
        else:
            line += "。"
        out.append(line)
    return "\n".join(out)
