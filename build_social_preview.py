#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「拾字 / PickText」品牌横幅（1280x640）。

同一张图两处复用：
  1. README 首屏 Hero（GitHub 会自动缩放到容器宽度）
  2. GitHub 仓库 Settings -> Social preview（1280x640 是官方推荐尺寸）

输出：assets/social-preview.png
运行：<venv>\\Scripts\\python.exe build_social_preview.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
OUT = os.path.join(ASSETS, "social-preview.png")

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"

W, H = 1280, 640
TOP = (37, 99, 235)        # #2563EB 品牌蓝，与图标一致
BOT = (6, 182, 212)        # #06B6D4 品牌青
WHITE = (255, 255, 255)

EYEBROW = "WINDOWS 10 / 11  ·  完全离线"
TITLE = "拾字  PickText"
SUB1 = "把屏幕上任意一块区域，"
SUB2 = "变成一个可一键调用的快捷键。"
CHIPS = ["选区预设热键", "锁定区域监控", "竖排古籍重排", "不联网"]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def tw(draw, text, f):
    box = draw.textbbox((0, 0), text, font=f)
    return box[2] - box[0]


def build():
    # 1) 对角渐变背景（左上品牌蓝 -> 右下品牌青），带一点方向感
    base = Image.new("RGB", (W, H), TOP)
    px = base.load()
    for y in range(H):
        for x in range(0, W, 4):
            t = (x / W * 0.55 + y / H * 0.45)
            col = lerp(TOP, BOT, min(1.0, t))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = col

    img = base.convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")

    # 2) 右侧：白色圆角卡片承托应用图标（图标本身是蓝青渐变，直接放渐变底会糊）
    card = (886, 168, 886 + 300, 168 + 300)
    d.rounded_rectangle(card, radius=40, fill=(255, 255, 255, 255))

    icon_path = os.path.join(ASSETS, "icon_preview.png")
    if os.path.exists(icon_path):
        ic = Image.open(icon_path).convert("RGBA")
        ic.thumbnail((244, 244), Image.LANCZOS)
        ix = card[0] + (300 - ic.width) // 2
        iy = card[1] + (300 - ic.height) // 2
        img.paste(ic, (ix, iy), ic)

    # 3) 左侧文案
    f_eyebrow = font(FONT_BOLD, 22)
    f_title = font(FONT_BOLD, 60)
    f_sub = font(FONT_REG, 34)
    f_chip = font(FONT_REG, 22)

    d.text((80, 140), EYEBROW, font=f_eyebrow, fill=(255, 255, 255, 205))
    d.text((80, 182), TITLE, font=f_title, fill=WHITE)
    d.text((80, 292), SUB1, font=f_sub, fill=WHITE)
    d.text((80, 344), SUB2, font=f_sub, fill=WHITE)

    # 4) 分隔线
    d.line([(80, 428), (80 + 420, 428)], fill=(255, 255, 255, 90), width=2)

    # 5) 能力标签——画在独立透明层上再 alpha_composite，
    #    否则半透明填充会直接覆盖而不与渐变底混合（会变成纯白色块）
    chips = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chips)
    x = 80
    y = 462
    for text in CHIPS:
        w = tw(cd, text, f_chip) + 40
        cd.rounded_rectangle((x, y, x + w, y + 48), radius=24,
                             fill=(255, 255, 255, 46),
                             outline=(255, 255, 255, 120), width=1)
        cd.text((x + 20, y + 11), text, font=f_chip, fill=(255, 255, 255, 240))
        x += w + 14
    img = Image.alpha_composite(img, chips)

    # 6) 底部仓库地址（社交预览卡片被裁切时仍能知道出处）
    d = ImageDraw.Draw(img)
    d.text((80, 566), "github.com/microsnow/pick-text",
           font=font(FONT_REG, 20), fill=(255, 255, 255, 165))

    img.convert("RGB").save(OUT, "PNG", optimize=True)
    return OUT


if __name__ == "__main__":
    p = build()
    size_kb = os.path.getsize(p) / 1024
    print(f"[OK] {p}  {size_kb:.0f} KB  ({W}x{H})")
