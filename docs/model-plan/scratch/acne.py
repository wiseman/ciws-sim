# /// script
# dependencies = ["playwright", "pillow"]
# ///
import sys, time
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors
from PIL import Image
out = sys.argv[1]
with game_page(width=1280, height=760) as (page, errors):
    time.sleep(4)
    page.evaluate("""() => { document.getElementById('hud').style.display='none'; const c = window.__ciws; c.debug.holdSpawns(); c.debug.clearThreats();
      c.camera.position.set(-6, 11, -4); c.controls.target.set(0, 6.5, 12); c.controls.update(); }""")
    time.sleep(1)
    shots = []
    for name, js in [("base", ""), ("noshadow", "c.scene.traverse(o => { if (o.isMesh) o.receiveShadow = false; }); c.scene.traverse(o => { if (o.material && !Array.isArray(o.material)) o.material.needsUpdate = true; });"),
                     ("nooutline", "c.scene.traverse(o => { if (o.userData.isOutline) o.visible = false; });")]:
        page.evaluate("() => { const c = window.__ciws; " + js + " }")
        time.sleep(0.5)
        p = f"{out}-{name}.png"; page.screenshot(path=p); shots.append(p)
report_errors(errors)
ims = [Image.open(p).crop((300, 150, 1000, 600)) for p in shots]
W = Image.new("RGB", (700 * 3, 450))
for i, im in enumerate(ims): W.paste(im, (i * 700, 0))
W.save(out + "-sheet.png")
