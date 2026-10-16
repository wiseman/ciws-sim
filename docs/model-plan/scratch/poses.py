# /// script
# dependencies = ["playwright", "pillow"]
# ///
import sys, time, json
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors, contact_sheet
from PIL import Image
out = sys.argv[1]
poses = json.loads(sys.argv[2])  # [[cam], [target]] in mount-relative y
paths = []
with game_page(width=1280, height=760) as (page, errors):
    time.sleep(4)
    for i, (cam, tgt) in enumerate(poses):
        page.evaluate("""([cam, tgt]) => { const c = window.__ciws, m = c.layout.mountY;
            c.camera.position.set(cam[0], cam[1] + m, cam[2]); c.controls.target.set(tgt[0], tgt[1] + m, tgt[2]); c.controls.update(); }""", [cam, tgt])
        time.sleep(0.5)
        p = f"{out}-{i}.png"; page.screenshot(path=p); paths.append(p)
report_errors(errors)
contact_sheet([Image.open(p).convert("RGB").resize((640, 380)) for p in paths], 2).save(out + "-sheet.png")
