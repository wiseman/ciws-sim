# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Tile a set of screenshots (center-cropped) into one contact sheet.

Usage: uv run tools/contact_sheet.py <out.png> <crop_w> <crop_h> <img>...
"""
import sys
from PIL import Image

from _harness import contact_sheet

out, cw, ch, *paths = sys.argv[1:]
cw, ch = int(cw), int(ch)
tiles = []
for path in paths:
    im = Image.open(path)
    x0, y0 = (im.width - cw) // 2, (im.height - ch) // 2
    tiles.append(im.crop((x0, y0, x0 + cw, y0 + ch)))
sheet = contact_sheet(tiles, 3, "black")
sheet.thumbnail((2400, 2400))
sheet.save(out)
