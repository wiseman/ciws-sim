# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Scratch: close-up reference shots of the current gun and ship, plus draw-call counts."""
import sys, time, json
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors
prefix = sys.argv[1]
views = {
    "gun-side": ([11, 5.5, 0.5], [0, 4.5, 0.5]),
    "gun-34": ([7, 7, -8], [0, 4.5, 0]),
    "gun-rear": ([-4, 7.5, 9], [0, 4.5, 0]),
    "ship-side": ([-95, 4, 14], [0, 1, 14]),
    "ship-bow": ([-35, 9, -50], [0, 2, 5]),
}
with game_page(width=1280, height=760, dpr=1) as (page, errors):
    time.sleep(5)
    page.evaluate("() => { const d = window.__ciws.debug; d.holdSpawns(); d.clearThreats(); }")
    time.sleep(2)
    for name, (pos, tgt) in views.items():
        page.evaluate(f"() => {{ const {{camera, controls}} = window.__ciws; camera.position.set(...{pos}); controls.target.set(...{tgt}); controls.update(); }}")
        time.sleep(0.6)
        page.screenshot(path=f"{prefix}-{name}.png")
        print("wrote", name)
    info = page.evaluate("""() => {
        const { renderer, scene } = window.__ciws;
        const r = renderer.info.render;
        let meshes = 0, outlines = 0, tris = 0;
        scene.traverse(o => { if (o.isMesh) { meshes++; if (o.userData.isOutline) outlines++; } });
        const b = scene.getObjectByName('barrels');
        let gun = 0; b.parent.parent.parent.traverse(o => { if (o.isMesh) gun++; });
        return { calls: r.calls, triangles: r.triangles, meshes, outlines, turretMeshes: gun };
    }""")
    print(json.dumps(info))
report_errors(errors)
