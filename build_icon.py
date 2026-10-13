#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为「拾字 / PickText」生成应用图标：渐变圆角磁贴 + 白色「字」+ 拾取光标。
输出 assets/icon.ico（多尺寸 ICO）与 assets/icon_preview.png（512 预览）。
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"

# 品牌渐变：蓝(#2563EB) -> 青(#06B6D4)，科技 + 拾取感
TOP = (37, 99, 235)
BOT = (6, 182, 212)
EDGE = (255, 255, 255, 45)        # 磁贴内描边
INK = (15, 23, 42, 210)           # 光标描边/阴影用深色


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_icon(size):
    s = size
    # 1) 渐变背景
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bp = base.load()
    for y in range(s):
        col = lerp(TOP, BOT, y / (s - 1))
        for x in range(s):
            bp[x, y] = (col[0], col[1], col[2], 255)
    # 2) 圆角磁贴遮罩
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=max(2, int(s * 0.22)), fill=255)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask)
    d = ImageDraw.Draw(out)
    # 3) 磁贴高光描边
    d.rounded_rectangle([1, 1, s - 2, s - 2], radius=max(1, int(s * 0.22) - 1),
                        outline=EDGE, width=max(1, int(s * 0.012)))
    # 4) 四角取景框（scan bracket）——「取/框」语义；小尺寸下省去以免糊成噪点
    if s >= 48:
        inset = 0.20 * s
        arm = 0.11 * s
        bw = max(1, int(round(s * 0.030)))
        bc = (255, 255, 255, 235)
        lines = [
            [(inset, inset), (inset + arm, inset)],
            [(inset, inset), (inset, inset + arm)],
            [(s - inset, inset), (s - inset - arm, inset)],
            [(s - inset, inset), (s - inset, inset + arm)],
            [(inset, s - inset), (inset + arm, s - inset)],
            [(inset, s - inset), (inset, s - inset - arm)],
            [(s - inset, s - inset), (s - inset - arm, s - inset)],
            [(s - inset, s - inset), (s - inset, s - inset - arm)],
        ]
        for a, b in lines:
            d.line([a, b], fill=bc, width=bw)
        fs = int(s * 0.50)
    else:
        fs = int(s * 0.62)   # 无取景框时放大主字，保证小尺寸可读
    try:
        font = ImageFont.truetype(FONT_BOLD, fs)
    except Exception:
        font = ImageFont.truetype(FONT_REG, fs)
    cx, cy = s / 2, s / 2
    d.text((cx, cy + max(1, int(s * 0.012))), "字", font=font,
           fill=(0, 0, 0, 70), anchor="mm")           # 柔和投影
    d.text((cx, cy), "字", font=font,
           fill=(255, 255, 255, 255), anchor="mm")    # 主体
    return out


def main():
    os.makedirs(ASSETS, exist_ok=True)
    sizes = [256, 128, 96, 64, 48, 40, 32, 24, 20, 16]
    frames = [make_icon(sz) for sz in sizes]
    ico = os.path.join(ASSETS, "icon.ico")
    frames[0].save(ico, format="ICO", append_images=frames[1:])
    png = os.path.join(ASSETS, "icon_preview.png")
    make_icon(512).save(png)
    print("saved:", ico, os.path.getsize(ico), "bytes")
    print("saved:", png, os.path.getsize(png), "bytes")


if __name__ == "__main__":
    main()
