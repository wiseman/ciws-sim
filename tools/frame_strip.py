# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Capture consecutive rendered frames of the spinning gun barrels for judging motion.

Usage: uv run tools/frame_strip.py OUT_PREFIX [side|front|gun|sight|far] [frames] [--spinup]
Poses the camera on the barrels (side and front: close up; gun: the Phalanx gun camera; sight: a
gunsight looking down the barrels; far: a distant three-quarter view), waits until they are fully
spun up (or, with --spinup, at rest and about to spin up), then copies a crop of every rendered
frame (hooked straight after renderer.render, so no frames are skipped). Writes
OUT_PREFIX-strip.png (frames in reading order) and OUT_PREFIX.gif (played at 50 fps, the GIF limit).
"""
import base64
import io
import sys
import time

from PIL import Image

from _harness import contact_sheet, game_page, report_errors

spinup = "--spinup" in sys.argv
argv = [a for a in sys.argv if a != "--spinup"]
prefix = argv[1]
view = argv[2] if len(argv) > 2 else "front"
count = int(argv[3]) if len(argv) > 3 else 24

POSE_JS = """(view) => {
    const { scene, camera, controls } = window.__ciws;
    if (view === 'gun' || view === 'sight') return window.__ciws.debug.barrelSpeed; // posed elsewhere
    const T = camera.position.constructor;
    const b = scene.getObjectByName('barrels');
    b.updateWorldMatrix(true, false);
    const mid = new T(0, 0, 2.6).applyMatrix4(b.matrixWorld);
    const tip = new T(0, 0, 3.5).applyMatrix4(b.matrixWorld);
    const axis = tip.clone().sub(mid).normalize();
    const side = new T(0, 1, 0).cross(axis).normalize();
    const look = view === 'side' ? mid : tip;
    const pos = view === 'side' ? mid.clone().addScaledVector(side, 3.2).add(new T(0, 0.8, 0))
        : view === 'far' ? tip.clone().addScaledVector(axis, 14).addScaledVector(side, 26).add(new T(0, 8, 0))
        : tip.clone().addScaledVector(axis, 2.6).addScaledVector(side, 0.9).add(new T(0, 0.4, 0));
    camera.position.copy(pos);
    controls.target.copy(look);
    controls.update();
    return window.__ciws.debug.barrelSpeed;
}"""

CAPTURE_JS = """async ([view, count, spinup]) => {
    const { renderer, camera, scene } = window.__ciws;
    const T = camera.position.constructor;
    const canvas = renderer.domElement;
    const crop = document.createElement('canvas');
    const size = Math.round(canvas.height * (view === 'side' || view === 'front' ? 0.45 : 0.7));
    crop.width = crop.height = size;
    const ctx = crop.getContext('2d');
    const frames = [];
    const original = renderer.render.bind(renderer);
    renderer.render = (s, c) => {
        const b = scene.getObjectByName('barrels');
        if (view === 'sight') {
            // Just above the barrels on the gun block, looking down them
            const gunBlock = b.parent;
            gunBlock.updateWorldMatrix(true, false);
            c.position.set(0, 0.95, 0.6).applyMatrix4(gunBlock.matrixWorld);
            c.lookAt(new T(0, 0.95, 200).applyMatrix4(gunBlock.matrixWorld));
        }
        original(s, c);
        if (frames.length >= count) return;
        if (spinup && !frames.length && window.__ciws.debug.barrelSpeed === 0) return; // start as it moves
        // Track the muzzle (or the barrel middle from the side) on screen as the turret moves
        const p = view === 'sight' ? new T(0, -0.25, 0)
            : new T(0, 0, view === 'side' ? 2.6 : 3.5).applyMatrix4(b.matrixWorld).project(camera);
        const x = (p.x + 1) / 2 * canvas.width - size / 2;
        const y = (1 - p.y) / 2 * canvas.height - size / 2;
        ctx.drawImage(canvas, x, y, size, size, 0, 0, size, size);
        frames.push(crop.toDataURL('image/png').split(',')[1]);
    };
    while (frames.length < count) await new Promise(r => requestAnimationFrame(r));
    renderer.render = original;
    return frames;
}"""

with game_page(dpr=2) as (page, errors):
    if view == "gun":
        page.evaluate("() => window.toggleCameraFollow()")  # OFF -> PHALANX
    deadline = time.time() + 60
    while time.time() < deadline:
        spin = page.evaluate(POSE_JS, view)
        if spin > 0.99:
            break
        time.sleep(0.05)
    # Spin-up: then wait for the barrels to come to rest after the burst
    while spinup and time.time() < deadline + 60:
        if page.evaluate(POSE_JS, view) == 0:
            break
        time.sleep(0.05)
    # Keep re-posing the camera so it stays on the barrels during the capture
    page.evaluate("""(pose) => { window.__poseLoop = setInterval(() => (0, eval)(pose)(%r), 16); }""" % view, POSE_JS)
    frames = [Image.open(io.BytesIO(base64.b64decode(f))).convert("RGB") for f in page.evaluate(CAPTURE_JS, [view, count, spinup])]
report_errors(errors)

w, h = frames[0].size
thumb = 220
contact_sheet([f.resize((thumb, thumb)) for f in frames], 8).save(f"{prefix}-strip.png")
frames[0].save(f"{prefix}.gif", save_all=True, append_images=frames[1:], duration=20, loop=0)
print("wrote", f"{prefix}-strip.png", f"{prefix}.gif", f"({len(frames)} frames, {w}x{h})")
