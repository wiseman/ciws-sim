# /// script
# dependencies = ["playwright", "pillow"]
# ///
"""An unopposed anti-ship missile from a given direction (radians, x = cos, z = sin), watched from the side."""
import sys, time
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors, timed_screenshots, contact_sheet
from PIL import Image
out, angle = sys.argv[1], float(sys.argv[2])
with game_page(width=1100, height=620) as (page, errors):
    time.sleep(3)
    page.evaluate("""(angle) => {
        document.getElementById('hud').style.display='none';
        const c = window.__ciws, d = c.debug; d.holdSpawns(); d.clearThreats();
        const r = Math.random; Math.random = () => angle / (Math.PI * 2);
        const m = d.spawnAntiShipMissile(); Math.random = r;
        m.mesh.position.multiplyScalar(0.12); m.mesh.position.y = 1.8; // start close in
        m.health = 1e9;                                                   // the gun can't stop it
        window.__m = m;
        c.camera.position.set(-70, 22, 14); c.controls.target.set(0, 4, 14); c.controls.update();
        window.__target = m.targetInfo.position.toArray();
    }""", angle)
    print("target", page.evaluate("() => window.__target"))
    paths = timed_screenshots(page, [0.6, 0.9, 1.2, 1.5, 1.8, 2.1], lambda t: f"{out}-{t:.1f}.png")
report_errors(errors)
ims = [Image.open(p).convert("RGB").resize((550, 310)) for p in paths]
contact_sheet(ims, 3).save(out + "-sheet.png")
