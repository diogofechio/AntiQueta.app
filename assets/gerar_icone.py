"""Gera icone.ico (Windows), icone.icns (macOS) e icone.png a partir do desenho de icone.svg.

Uso: pip install pillow && python assets/gerar_icone.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
S = 1024  # desenha grande e reduz, para bordas suaves
K = S / 256
BG, WHITE, BLUE = "#16181d", "#ffffff", "#6f8fff"


def pt(x, y):
    # mesmo transform do SVG: escala .94 em torno do centro
    return ((128 + 0.94 * (x - 128)) * K, (128 + 0.94 * (y - 128)) * K)


def arc(cx, cy, r, start, end, steps=16):
    return [pt(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in (start + (end - start) * i / steps for i in range(steps + 1))]


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((0, 0, S - 1, S - 1), radius=56 * K, fill=BG)
d.polygon([pt(16, 122), pt(80, 58), pt(152, 58), pt(117.70, 186), pt(80, 186)], fill=WHITE)
cx, cy = pt(72, 122)
r = 14 * 0.94 * K
d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BG)
d.polygon([pt(174, 68), *arc(224, 84, 16, -90, 0), *arc(224, 180, 16, 0, 90), pt(139.70, 196)], fill=BLUE)

img.save(HERE / "icone.png")
img.save(HERE / "icone.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(HERE / "icone.icns")
print("icone.png, icone.ico e icone.icns gerados em", HERE)
