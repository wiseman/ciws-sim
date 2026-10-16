# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Stage the newer world effects in front of a fixed camera and capture timed screenshots.

Usage: uv run tools/scene_shot.py <out_prefix> <scenario>
Scenarios:
  wreck      a friendly is hit and starts sinking under a smoke column (early frames)
  wreck-late the same wreck run at 4x speed through its long settle and final plunge
             (frames at sim ages ~20, 50, 80, 96, 104, 110 s)
  ascm       an anti-ship missile running in at sea-skimming height
  engage     two anti-ship missiles from the west, engaged by the CIWS (tracked through a long lens from beside the gun)
  vls        a VLS launch from our ship
  vls-boat   a VLS launch from a friendly boat
Spawning is held so only the staged objects are in view (except in `engage`). Also writes
<out_prefix>-<scenario>-sheet.png, a contact sheet of the frames.
"""
import sys
import time

from PIL import Image

from _harness import contact_sheet, game_page, report_errors, timed_screenshots

out = sys.argv[1]
scenario = sys.argv[2]

# Scenario -> js that stages it; `d` is window.__ciws.debug, `c` window.__ciws
SETUP = {
    "wreck": """
        const f = d.friendlies[0];
        const p = f.position;
        c.camera.position.set(p.x - 13, 5, p.z + 15); c.controls.target.set(p.x, 4, p.z);
        d.wreckFriendly(0);""",
    "wreck-late": """
        const f = d.friendlies[0];
        const p = f.position;
        c.camera.position.set(p.x - 48, 14, p.z + 56); c.controls.target.set(p.x + 8, 24, p.z);
        d.wreckFriendly(0);
        d.setTimeScale(4);""",
    "ascm": """
        window.__m = d.spawnAntiShipMissile();
        window.__follow = setInterval(() => {
            const m = window.__m; if (!m || !m.mesh.parent) return;
            const p = m.mesh.position, v = m.velocity.clone().normalize();
            c.camera.position.set(p.x - v.x * 14 + v.z * 9, p.y + 3.5, p.z - v.z * 14 - v.x * 9);
            c.controls.target.copy(p).addScaledVector(v, 6);
            c.controls.update();
        }, 8);""",
    "engage": """
        // Two anti-ship missiles from the west, tracked through a long lens from beside the gun
        c.camera.fov = 7; c.camera.updateProjectionMatrix();
        window.dispatchEvent(new Event('resize')); // re-derives the ink line width for the new lens
        c.controls.maxDistance = Infinity;
        c.camera.position.set(14, 9, 10);
        window.__ms = [];
        [[-25, null], [30, 0]].forEach(([z, f], i) => setTimeout(() => {
            const m = d.spawnAntiShipMissile(f);
            m.mesh.position.set(-1150, 16, z * 4);
            window.__ms.push(m);
        }, i * 1800));
        window.__follow = setInterval(() => {
            const m = window.__ms.find(m => m.mesh.parent);
            if (m) c.controls.target.lerp(m.mesh.position, 0.2);
            c.camera.position.set(14, 9, 10);
            c.controls.update();
        }, 8);""",
    "vls": """
        c.camera.position.set(-48, 16, 66); c.controls.target.set(10, 30, 0);
        d.launchVLS('ship', 300);""",
    "vls-boat": """
        const p = d.friendlies[1].position;
        c.camera.position.set(p.x - 30, 10, p.z + 34); c.controls.target.set(p.x, 12, p.z);
        d.launchVLS(1, 45);""",
}
# Scenario -> screenshot times (s after the setup runs)
TIMES = {
    "wreck": [0.3, 1.5, 4, 8, 14, 24],
    "wreck-late": [5, 12.5, 20, 24, 26, 27.5],
    "ascm": [3.0, 3.6, 4.2, 4.8, 5.4, 6.0],
    "engage": [4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5],
    "vls": [0.08, 0.3, 0.7, 1.2, 2.0, 3.5, 6, 10],
    "vls-boat": [0.1, 0.5, 1.2, 2.5, 5, 9],
}

with game_page(dpr=2, console_levels=("error", "warning")) as (page, errors):
    time.sleep(3)
    # Hide the HUD, hold spawning and clear anything already in flight
    page.evaluate("() => { document.getElementById('hud').style.display = 'none'; const d = window.__ciws.debug; d.holdSpawns(); d.clearThreats(); }")
    time.sleep(0.5)
    page.evaluate(f"() => {{ const c = window.__ciws, d = c.debug; {SETUP[scenario]} c.controls.update(); }}")
    paths = timed_screenshots(page, TIMES[scenario], lambda t: f"{out}-{scenario}-{t:05.2f}.png")
    info = page.evaluate("() => { const d = window.__ciws.debug; return { smoke: d.smokePuffs, wrecks: d.wrecks.length, missiles: d.missiles.length, vls: d.vlsLaunches.length, stats: d.stats }; }")
    print(info)
report_errors(errors)

thumbs = [Image.open(p).convert("RGB") for p in paths]
w, h = thumbs[0].size
contact_sheet([im.resize((w // 3, h // 3)) for im in thumbs], 4 if len(thumbs) > 6 else 3).save(f"{out}-{scenario}-sheet.png")
print("wrote", f"{out}-{scenario}-sheet.png")
