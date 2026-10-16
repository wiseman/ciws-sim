# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Close-up of a friendly's VLS hatch opening for a launch (copy into tools/ to run).
Usage: uv run tools/hatch.py OUT_PREFIX [friendly index]"""
import sys
import time

from _harness import game_page, report_errors

out = sys.argv[1]
index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
with game_page(dpr=2) as (page, errors):
    time.sleep(3)
    page.evaluate("""(i) => {
        document.getElementById('hud').style.display = 'none';
        const c = window.__ciws, d = c.debug, V = c.camera.position.constructor;
        d.holdSpawns(); d.clearThreats();
        const f = d.friendlies[i].mesh;
        c.controls.maxDistance = Infinity;
        c.camera.position.copy(f.localToWorld(new V(-7, 5.5, -4)));
        c.controls.target.copy(f.localToWorld(new V(0, 0.5, -9.5)));
        c.controls.update();
    }""", index)
    time.sleep(0.5)
    page.screenshot(path=f"{out}-shut.png")
    page.evaluate("(i) => window.__ciws.debug.launchVLS(i, 90)", index)
    for t in (0.35, 1.4, 4.0):
        time.sleep(t - (0 if t == 0.35 else {1.4: 0.35, 4.0: 1.4}[t]))
        page.screenshot(path=f"{out}-{t:.2f}.png")
    print("wrote", out)
report_errors(errors)
