# /// script
# dependencies = ["pillow"]
# ///
import sys
from PIL import Image
out, cols, w, *paths = sys.argv[1:]
cols, w = int(cols), int(w)
ims = [Image.open(p).convert("RGB") for p in paths]
h = int(w * ims[0].height / ims[0].width)
ims = [im.resize((w, h)) for im in ims]
rows = (len(ims) + cols - 1) // cols
S = Image.new("RGB", (cols * w, rows * h), "black")
for i, im in enumerate(ims): S.paste(im, ((i % cols) * w, (i // cols) * h))
S.save(out)
