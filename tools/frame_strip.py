# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Capture consecutive rendered frames of the spinning gun barrels for judging motion.

Usage: uv run tools/frame_strip.py OUT_PREFIX [side|front|sight] [frames] [full|spinup]
Poses the camera close to the barrels (side, three-quarter front, or a gunsight view down them),
then copies a crop of every rendered frame (hooked straight after renderer.render, so no frames are
skipped). "full" (the default) waits until the barrels are fully spun up; "spinup" idles the gun,
then starts the capture a couple of frames before it spins up for the next threat. Writes
OUT_PREFIX-strip.png (frames in reading order) and OUT_PREFIX.gif (played at 50 fps, the GIF limit).
"""
import base64
import io
import sys
import time

from PIL import Image

from _harness import contact_sheet, game_page, report_errors

prefix = sys.argv[1]
view = sys.argv[2] if len(sys.argv) > 2 else "front"
count = int(sys.argv[3]) if len(sys.argv) > 3 else 24
mode = sys.argv[4] if len(sys.argv) > 4 else "full"

# Returns the barrel spin speed (0..1), read back from the motion blur's shutter sweep
POSE_JS = """(view) => {
    const { scene, camera, controls } = window.__ciws;
    const T = camera.position.constructor;
    const b = scene.getObjectByName('barrels');
    b.updateWorldMatrix(true, false);
    const mid = new T(0, 0, 2.6).applyMatrix4(b.matrixWorld);
    const tip = new T(0, 0, 3.5).applyMatrix4(b.matrixWorld);
    const axis = tip.clone().sub(mid).normalize();
    const side = new T(0, 1, 0).cross(axis).normalize();
    if (view !== 'sight') {
        const look = view === 'side' ? mid : tip;
        const pos = view === 'side'
            ? mid.clone().addScaledVector(side, 3.2).add(new T(0, 0.8, 0))
            : tip.clone().addScaledVector(axis, 2.6).addScaledVector(side, 0.9).add(new T(0, 0.4, 0));
        camera.position.copy(pos);
        controls.target.copy(look);
        controls.update();
    }
    const blur = b.children.find(c => c.material && c.material.uniforms && c.material.uniforms.uSweep);
    return Math.sqrt(blur.material.uniforms.uSweep.value / 3.9);
}"""

CAPTURE_JS = """async ([view, count, spinup]) => {
    const { renderer, camera, scene } = window.__ciws;
    const T = camera.position.constructor;
    const canvas = renderer.domElement;
    const crop = document.createElement('canvas');
    const size = Math.round(canvas.height * (view === 'sight' ? 0.7 : 0.45));
    crop.width = crop.height = size;
    const ctx = crop.getContext('2d');
    const b = scene.getObjectByName('barrels');
    const blur = b.children.find(c => c.material && c.material.uniforms && c.material.uniforms.uSweep);
    let frames = [], started = !spinup;
    // Gunsight view (as in demo_video): a camera riding the gun block, just above the barrels
    const sight = new camera.constructor(45, camera.aspect, 0.25, 4000);
    const aimSight = () => {
        b.parent.updateWorldMatrix(true, false);
        sight.position.set(0, 0.95, 0.6).applyMatrix4(b.parent.matrixWorld);
        sight.lookAt(new T(0, 0.95, 200).applyMatrix4(b.parent.matrixWorld));
    };
    const original = renderer.render.bind(renderer);
    renderer.render = (s, c) => {
        if (view === 'sight') aimSight();
        original(s, view === 'sight' ? sight : c);
        if (frames.length >= count && started) return;
        // Track the muzzle (front) or barrel middle (side) on screen as the turret moves
        const p = view === 'sight' ? new T(0, -0.3, 0)
            : new T(0, 0, view === 'side' ? 2.6 : 3.5).applyMatrix4(b.matrixWorld).project(camera);
        const x = (p.x + 1) / 2 * canvas.width - size / 2;
        const y = (1 - p.y) / 2 * canvas.height - size / 2;
        ctx.drawImage(canvas, x, y, size, size, 0, 0, size, size);
        frames.push(crop.toDataURL('image/png').split(',')[1]);
        // Spin-up: keep only the last two idle frames until the barrels start turning
        if (!started) {
            if (blur.material.uniforms.uSweep.value > 0 || b.rotation.z !== window.__idleAngle) started = true;
            else frames = frames.slice(-2);
        }
    };
    while (frames.length < count || !started) await new Promise(r => requestAnimationFrame(r));
    renderer.render = original;
    return frames;
}"""

with game_page(dpr=2) as (page, errors):
    deadline = time.time() + 60
    if mode == "spinup":
        # Let the gun go idle, then send in a fresh threat once the capture is armed
        page.evaluate("() => { const d = window.__ciws.debug; d.holdSpawns(); d.clearThreats(); }")
        while time.time() < deadline and page.evaluate(POSE_JS, view) > 0:
            time.sleep(0.05)
        time.sleep(0.5)
        page.evaluate("() => { window.__idleAngle = window.__ciws.scene.getObjectByName('barrels').rotation.z; }")
        page.evaluate("() => setTimeout(() => window.__ciws.debug.resumeSpawns(), 300)")
    else:
        while time.time() < deadline and page.evaluate(POSE_JS, view) < 0.99:
            time.sleep(0.05)
    # Keep re-posing the camera so it stays on the barrels during the capture
    page.evaluate("""(pose) => { window.__poseLoop = setInterval(() => (0, eval)(pose)(%r), 16); }""" % view, POSE_JS)
    frames = [Image.open(io.BytesIO(base64.b64decode(f))).convert("RGB")
              for f in page.evaluate(CAPTURE_JS, [view, count, mode == "spinup"])]
report_errors(errors)

w, h = frames[0].size
thumb = 220
contact_sheet([f.resize((thumb, thumb)) for f in frames], 8).save(f"{prefix}-strip.png")
frames[0].save(f"{prefix}.gif", save_all=True, append_images=frames[1:], duration=20, loop=0)
print("wrote", f"{prefix}-strip.png", f"{prefix}.gif", f"({len(frames)} frames, {w}x{h})")
