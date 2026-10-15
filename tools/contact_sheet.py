# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Tile a set of screenshots (center-cropped) into one contact sheet.

Usage: uv run tools/contact_sheet.py <out.png> <crop_w> <crop_h> <img>...
"""
import sys
from PIL import Image

out, cw, ch, *paths = sys.argv[1:]
cw, ch = int(cw), int(ch)
tiles = []
for path in paths:
    im = Image.open(path)
    x0, y0 = (im.width - cw) // 2, (im.height - ch) // 2
    tiles.append(im.crop((x0, y0, x0 + cw, y0 + ch)))
cols = 3
rows = (len(tiles) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cw, rows * ch), "black")
for i, t in enumerate(tiles):
    sheet.paste(t, ((i % cols) * cw, (i // cols) * ch))
sheet.thumbnail((2400, 2400))
sheet.save(out)
