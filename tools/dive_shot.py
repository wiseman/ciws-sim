# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Frame strips of a drone's pushover and dive, from the side or through the game's cameras.

Usage: uv run tools/dive_shot.py OUT_PREFIX [--view side|missile|split] [--target ship|N]
           [--height H] [--gamma DEG] [--angle DEG] [--wave N] [--scale K] [--step S] [--killable]
Holds the spawns and sends in one drone from bearing angle
(degrees; x = cos, z = sin) at cruise height H with dive angle DEG, at our ship or friendly N. The gun
tracks it but holds its fire, unless --killable: then it engages as usual.
side: the orbit camera abeam of the dive line, about 120 off it on a long lens; missile: the
missile-follow camera; split: the split screen with the chase camera pinned on the drone. From
about 0.75 s before the pushover the game runs at K x speed (default 0.1, so the frame times are
exact) and a frame is taken every S sim seconds (default 0.25) until 0.75 s after it's gone.
Writes OUT_PREFIX-NN.png, a contact sheet OUT_PREFIX-sheet.png and, for side, OUT_PREFIX-zoom.png:
a 3x crop round the drone in each frame (and round where it went off, after).
"""
import sys
import time

from PIL import Image

from _harness import QUIET_SCENE_JS, contact_sheet, game_page, report_errors

argv = sys.argv[1:]
prefix = argv[0]


def opt(name, default, kind=str):
    return kind(argv[argv.index(name) + 1]) if name in argv else default


view = opt("--view", "side")
target = opt("--target", "ship")
height = opt("--height", 90.0, float)
gamma = opt("--gamma", 45.0, float)
angle = opt("--angle", 200.0, float)
wave = opt("--wave", 3, int)
scale = opt("--scale", 0.1, float)
step = opt("--step", 0.25, float)
killable = "--killable" in argv

SETUP_JS = """async (o) => {
    const THREE = await import('three');
    const c = window.__ciws, d = c.debug;
    d.setWave(o.wave);
    if (!o.killable) d.holdFire();
    const m = d.spawnDrone({ angle: o.angle * Math.PI / 180, height: o.height, gamma: o.gamma,
                             targetIndex: o.target === 'ship' ? null : +o.target });
    window.__dive = m;
    const aim = m.targetInfo.position, p = m.mesh.position;
    if (o.view === 'side') {
        // Abeam of the dive line, 120 off it and low, looking at its middle
        const along = new THREE.Vector3(p.x - aim.x, 0, p.z - aim.z).normalize();
        const mid = aim.clone().addScaledVector(along, m.dive.pushoverRange * 0.6);
        mid.y = (aim.y + o.height) / 2;
        const across = new THREE.Vector3(-along.z, 0, along.x);
        c.camera.position.copy(mid).addScaledVector(across, 120).setY(12);
        c.camera.fov = 50; c.camera.updateProjectionMatrix();
        c.controls.maxPolarAngle = Math.PI; // the orbit camera may look up from below the target
        c.controls.target.copy(mid); c.controls.update();
    } else {
        c.setCameraMode(o.view);
        if (o.view === 'split') d.setChaseTrack(m);
    }
    return { gamma: m.dive.gamma * 180 / Math.PI, pushoverRange: m.dive.pushoverRange, aim: aim.toArray() };
}"""

STATE_JS = """() => {
    const m = window.__dive, d = window.__ciws.debug, p = m.mesh.position, t = m.targetInfo.position;
    const s = p.clone().project(window.__ciws.camera);
    return { t: d.simTime, alive: !!m.mesh.parent, sx: (s.x + 1) / 2 * innerWidth, sy: (1 - s.y) / 2 * innerHeight, range: Math.hypot(p.x - t.x, p.z - t.z), lead: m.dive.pushoverRange + 0.75 * 60 * m.dive.cruise,
             phase: m.dive.phase, y: p.y, pitch: -Math.asin(m.velocity.y / m.velocity.length()) * 180 / Math.PI };
}"""

with game_page(width=1280, height=760, console_levels=("error",)) as (page, errors):
    time.sleep(2)
    page.evaluate(QUIET_SCENE_JS, False)
    info = page.evaluate(SETUP_JS, {"view": view, "target": target, "height": height, "gamma": gamma, "angle": angle,
                                    "wave": wave, "killable": killable})
    print("drone:", info)
    while True:
        s = page.evaluate(STATE_JS)
        if s["range"] <= s["lead"] or not s["alive"]:
            break
        time.sleep(0.02)
    page.evaluate(f"() => window.__ciws.debug.setTimeScale({scale})")
    paths, spots, start = [], [], page.evaluate(STATE_JS)["t"]
    gone_at = None
    while True:
        s = page.evaluate(STATE_JS)
        if not s["alive"] and gone_at is None:
            gone_at = s["t"]
        if gone_at is not None and s["t"] > gone_at + 0.75:
            break
        if s["t"] >= start + len(paths) * step:
            path = f"{prefix}-{len(paths):02d}.png"
            page.screenshot(path=path)
            print(f"{path}: +{s['t'] - start:.2f} s {s['phase']:8s} y {s['y']:5.1f} pitch {s['pitch']:5.1f} range {s['range']:6.1f}")
            paths.append(path)
            spots.append((s["sx"], s["sy"]))
        time.sleep(0.01)
report_errors(errors)
images = [Image.open(p).resize((640, 380)) for p in paths]
contact_sheet(images, 4).save(f"{prefix}-sheet.png")
print("wrote", f"{prefix}-sheet.png")
if view == "side":
    crops = []
    for path, (x, y) in zip(paths, spots):
        x, y = min(max(x, 100), 1180), min(max(y, 60), 700)
        crops.append(Image.open(path).crop((int(x) - 100, int(y) - 60, int(x) + 100, int(y) + 60)).resize((600, 360)))
    contact_sheet(crops, 4).save(f"{prefix}-zoom.png")
    print("wrote", f"{prefix}-zoom.png")
