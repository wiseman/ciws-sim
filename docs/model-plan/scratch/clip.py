# /// script
# dependencies = ["playwright"]
# ///
import sys, time
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors
prefix = sys.argv[1]
poses = [("dep30", 0.52), ("dep25", 0.44), ("lvl", 0), ("el85", -1.48)]
views = {"side": ([11, 5, 0.5], [0, 4.2, 0.5]), "rear34": ([7, 7.5, -8], [0, 4.2, 0])}
with game_page(width=900, height=700) as (page, errors):
    time.sleep(4)
    page.evaluate("() => { document.getElementById('hud').style.display='none'; const c = window.__ciws; c.debug.holdSpawns(); c.debug.clearThreats(); c.controls.maxPolarAngle = Math.PI; }")
    time.sleep(1.5)
    for name, pitch in poses:
        for vname, (pos, tgt) in views.items():
            page.evaluate("""([pitch, pos, tgt]) => { const c = window.__ciws; const b = c.scene.getObjectByName('barrels');
              const P = b.parent.parent, Y = P.parent, M = Y.parent; Y.rotation.y = 0; P.rotation.x = pitch;
              const T = c.camera.position.constructor; const m = M.getWorldPosition(new T());
              c.camera.position.copy(m).add(new T(...pos)); c.controls.target.copy(m).add(new T(...tgt)); c.controls.update(); }""", [pitch, pos, tgt])
            time.sleep(0.3)
            page.screenshot(path=f"{prefix}-{name}-{vname}.png")
report_errors(errors)
