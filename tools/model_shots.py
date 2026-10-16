# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Close-ups of the gun and ship models, gun-camera frames around the compass, and render counts.

Usage: uv run tools/model_shots.py OUT_PREFIX [view...]
Holds spawning and clears threats, then poses the gun (trained aft, elevated 20 degrees) and
captures each view (default: all) as OUT_PREFIX-<view>.png with the HUD hidden:
  gun-side, gun-34, gun-rear, gun-front, gun-low   close-ups around the mount (relative to it)
  ship-side, ship-bow, ship-quarter, ship-far       the ship's profile, bow, stern quarter, silhouette
  ship-fore, ship-mid, ship-aft                     closer: forecastle, amidships, stern
  gun-cam-000 / -090 / -180 / -270                  the Phalanx gun camera (mode 1) with the gun
                                                    trained to that bearing (clockwise from the bow)
  ffg-34, ffg-side, ffg-stern, ffg-top              a friendly in the FFG-62 style fit (fit 0), and
  lf-34, lf-side, lf-stern, lf-top                  one in the light-frigate fit (fit 1), posed in
                                                    her own frame (bow -z); skipped if none has it
Prints draw calls and triangles for the default orbit view, and mesh / outline counts (in all, in
the mount and in the ship, each including outline meshes).
"""
import json
import math
import sys
import time

from _harness import game_page, report_errors

prefix = sys.argv[1]
GUN_VIEWS = {  # mount-relative camera position and target; the gun points along +z, its left is +x
    "gun-side": ([11, 5.5, 0.5], [0, 4.5, 0.5]),
    "gun-34": ([-7.5, 7, 9], [0, 4.6, 0.8]),
    "gun-rear": ([6, 8.5, -9], [0, 4.6, 0]),
    "gun-front": ([0.8, 5.6, 12], [0, 5, 0]),
    "gun-low": ([-5.5, 1.8, 7], [0, 5.5, 0.5]),
}
SHIP_VIEWS = {
    "ship-side": ([-118, 7, 14], [0, 5, 14]),
    "ship-bow": ([-40, 14, -66], [0, 5, -8]),
    "ship-quarter": ([48, 20, 104], [0, 4, 34]),
    "ship-far": ([-230, 120, 210], [0, 0, 14]),
    "ship-fore": ([-17, 12, -44], [0, 3.5, -20]),
    "ship-mid": ([-24, 13, 28], [0, 5, 37]),
    "ship-aft": ([-20, 15, 84], [0, 3, 57]),
}
FRIENDLY_VIEWS = {  # in the friendly's frame (origin at her targeting point, about deck height)
    "34": ([-17, 7, -24], [0, 1.5, -3]),
    "side": ([-42, 4, 2], [0, 1.5, 0]),
    "stern": ([14, 6, 30], [0, 0.5, 8]),
    "top": ([-16, 26, 6], [0, 0, 1]),
}
FITS = {"ffg": 0, "lf": 1}
CAM_BEARINGS = [0, 90, 180, 270]
names = sys.argv[2:] or [*GUN_VIEWS, *SHIP_VIEWS, *(f"gun-cam-{b:03d}" for b in CAM_BEARINGS),
                         *(f"{fit}-{view}" for fit in FITS for view in FRIENDLY_VIEWS)]

SETUP_JS = """() => {
    document.getElementById('hud').style.display = 'none';
    document.getElementById('radar').style.display = 'none';
    const c = window.__ciws, d = c.debug;
    d.holdSpawns(); d.clearThreats();
    c.controls.maxPolarAngle = Math.PI; // let the close-ups look up at the mount
    window.__home = [c.camera.position.toArray(), c.controls.target.toArray()];
}"""

# Turret pose: yaw (radians, 0 = gun pointing aft along +z) and pitch (negative is up)
POSE_GUN_JS = """([yaw, pitch]) => {
    const b = window.__ciws.scene.getObjectByName('barrels');
    const pitchGroup = b.parent.parent, yawGroup = pitchGroup.parent;
    yawGroup.rotation.y = yaw; pitchGroup.rotation.x = pitch;
}"""

CAMERA_JS = """([pos, target, relative]) => {
    const { scene, camera, controls } = window.__ciws;
    const T = camera.position.constructor;
    const mount = relative ? scene.getObjectByName('barrels').parent.parent.parent.parent.getWorldPosition(new T()) : new T();
    camera.position.copy(mount).add(new T(...pos));
    controls.target.copy(mount).add(new T(...target));
    controls.update();
}"""

# Camera in a friendly's frame: the first one in that fit; false if there's none
FRIENDLY_CAMERA_JS = """([pos, target, fit]) => {
    const { camera, controls, debug } = window.__ciws;
    const f = debug.friendlies.find(f => f.fit === fit && f.alive);
    if (!f) return false;
    const T = camera.position.constructor;
    controls.maxDistance = Infinity;
    camera.position.copy(f.mesh.localToWorld(new T(...pos)));
    controls.target.copy(f.mesh.localToWorld(new T(...target)));
    controls.update();
    return true;
}"""

COUNTS_JS = """() => {
    const { renderer, scene, camera, controls } = window.__ciws;
    camera.position.fromArray(window.__home[0]); controls.target.fromArray(window.__home[1]); controls.update();
    return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => {
        const r = renderer.info.render;
        let meshes = 0, outlines = 0, turret = 0, ship = 0;
        scene.traverse(o => { if (o.isMesh) { meshes++; if (o.userData.isOutline) outlines++; } });
        scene.getObjectByName('barrels').parent.parent.parent.parent.traverse(o => { if (o.isMesh) turret++; });
        scene.getObjectByName('ship').traverse(o => { if (o.isMesh) ship++; });
        resolve({ calls: r.calls, triangles: r.triangles, meshes, outlines, mountMeshes: turret, shipMeshes: ship,
                  geometries: renderer.info.memory.geometries });
    })));
}"""

with game_page(width=1280, height=760, dpr=1) as (page, errors):
    time.sleep(4)
    page.evaluate(SETUP_JS)
    time.sleep(1.5)  # let the turret settle; with no target it holds wherever it's put
    print(json.dumps(page.evaluate(COUNTS_JS)))
    page.evaluate(POSE_GUN_JS, [0, -0.35])
    in_gun_cam = False
    for name in names:
        if name.startswith("gun-cam-"):
            if not in_gun_cam:
                page.evaluate("() => window.toggleCameraFollow()")  # OFF -> PHALANX
                in_gun_cam = True
            b = math.radians(int(name[-3:]))
            page.evaluate(POSE_GUN_JS, [math.atan2(math.sin(b), -math.cos(b)), -0.12])
        elif name.split("-")[0] in FITS:
            fit, view = name.split("-", 1)
            if not page.evaluate(FRIENDLY_CAMERA_JS, [*FRIENDLY_VIEWS[view], FITS[fit]]):
                print("no friendly in fit", fit)
                continue
        else:
            pos, target = GUN_VIEWS.get(name) or SHIP_VIEWS[name]
            page.evaluate(CAMERA_JS, [pos, target, name in GUN_VIEWS])
        time.sleep(0.5)
        page.screenshot(path=f"{prefix}-{name}.png")
        print("wrote", f"{prefix}-{name}.png")
report_errors(errors)
