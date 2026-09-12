# -*- coding: utf-8 -*-
"""
Delfin 图标生成器
输入：assets/whale_mask.png（已固化的海豚形状遮罩）；缺该文件时回退到 assets/ds-favicon.ico
产出：
  - dsh_icons.py        base64 图标（被 dsh-tray.py 引用，保证 exe 自包含）
  - assets/dsh-tray.ico 多尺寸 exe 图标
  - preview.png         多尺寸预览（浅/深底）
"""
import base64
import io
import os

from PIL import Image, ImageDraw

BRAND = (77, 107, 254, 255)      # #4D6BFE DeepSeek 品牌蓝
WHALE = BRAND
GREEN = (46, 160, 67, 255)
RED = (222, 74, 66, 255)
WHITE = (255, 255, 255, 255)

HERE = os.path.dirname(os.path.abspath(__file__))
MASK = os.path.join(HERE, "assets", "whale_mask.png")
SRC = os.path.join(HERE, "assets", "ds-favicon.ico")
ICON_SIZE = 64          # 交给 pystray 的尺寸（Windows 托盘会按需缩放）
DOT = 0.29              # 状态点直径 / 画布


def whale_mask(size=256):
    """小海豚形状遮罩（保留眼部/水纹镂空）

    优先读取仓库内已固化的 assets/whale_mask.png —— 这样重新生成整套图标
    不依赖任何第三方素材；仅在该文件缺失时才回退到官方 favicon 的 alpha 通道。
    """
    if os.path.exists(MASK):
        return Image.open(MASK).convert("L").resize((size, size), Image.LANCZOS)
    if not os.path.exists(SRC):
        raise SystemExit("缺少 assets/whale_mask.png 或 assets/ds-favicon.ico，无法生成图标")
    im = Image.open(SRC).convert("RGBA")
    mask = im.split()[3]
    bbox = mask.getbbox()
    mask = mask.crop(bbox)
    w, h = mask.size
    side = max(w, h)
    margin = int(side * 0.04)
    canvas = Image.new("L", (side + margin * 2, side + margin * 2), 0)
    canvas.paste(mask, ((canvas.width - w) // 2, (canvas.height - h) // 2))
    return canvas.resize((size, size), Image.LANCZOS)


def build(mask_src, whale_color, dot_color, size=ICON_SIZE, gap=True):
    """组合：小海豚剪影 + 右下角状态点"""
    m = mask_src.resize((size, size), Image.LANCZOS)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (size, size), whale_color), (0, 0), m)
    d = ImageDraw.Draw(img)
    r = size * DOT / 2
    cx = cy = size * (1 - DOT / 2) - size * 0.045
    if gap:  # 在圆点周围留出一圈空隙，任何底色下都清晰
        d.ellipse([cx - r * 1.15, cy - r * 1.15, cx + r * 1.15, cy + r * 1.15], fill=(0, 0, 0, 0))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dot_color)
    return img


def png_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


if __name__ == "__main__":
    mask_src = whale_mask(256)
    mask_src.save(os.path.join(HERE, "assets", "whale_mask.png"))
    run = build(mask_src, WHALE, GREEN)
    stop = build(mask_src, WHALE, RED)

    # 生成 dsh_icons.py
    with open(os.path.join(HERE, "dsh_icons.py"), "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write('"""自动生成：DeepSeek 小海豚托盘图标（勿手改，改 make_icon.py 后重跑）"""\n')
        f.write("import base64\nimport io\n\nfrom PIL import Image\n\n")
        f.write('RUNNING = "%s"\n\n' % png_b64(run))
        f.write('STOPPED = "%s"\n\n' % png_b64(stop))
        f.write(
            "def load(running):\n"
            '    """返回托盘图标 Image（running=True 绿点 / False 红点）"""\n'
            '    raw = base64.b64decode(RUNNING if running else STOPPED)\n'
            "    return Image.open(io.BytesIO(raw)).convert(\"RGBA\")\n"
        )

    # exe / 快捷方式用多尺寸 ico
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    run.save(os.path.join(HERE, "assets", "dsh-tray.ico"),
             sizes=[(s, s) for s in sizes])

    # 预览
    preview_sizes = [16, 20, 24, 32, 48, 64, 128]
    pad, gap2 = 14, 18
    W = pad * 2 + sum(preview_sizes) + gap2 * (len(preview_sizes) - 1)
    H = pad * 2 + 128 * 2 + gap2
    pv = Image.new("RGB", (W, H), (245, 246, 248))
    ImageDraw.Draw(pv).rectangle([0, pad + 128 + gap2 // 2, W, H], fill=(32, 34, 38))
    x = pad
    for s in preview_sizes:
        for row, ic in enumerate((run, stop)):
            thumb = ic.resize((s, s), Image.LANCZOS)
            y = pad + row * (128 + gap2) + (128 - s) // 2
            pv.paste(thumb, (x, y), thumb)
        x += s + gap2
    pv.save(os.path.join(HERE, "preview.png"))
    print("icons ok: %d bytes b64 running" % len(png_b64(run)))
