# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Capture consecutive rendered frames of the spinning gun barrels for judging motion.

Usage: uv run tools/frame_strip.py OUT_PREFIX [side|front] [frames]
Poses the camera close to the barrels, waits until they are fully spun up, then copies a crop of
every rendered frame (hooked straight after renderer.render, so no frames are skipped). Writes
OUT_PREFIX-strip.png (frames in reading order) and OUT_PREFIX.gif (played at 50 fps, the GIF limit).
"""
import base64
import io
import sys
import time

from PIL import Image

from _harness import game_page, report_errors

prefix = sys.argv[1]
view = sys.argv[2] if len(sys.argv) > 2 else "front"
count = int(sys.argv[3]) if len(sys.argv) > 3 else 24

POSE_JS = """(view) => {
    const { scene, camera, controls } = window.__ciws;
    const T = camera.position.constructor;
    const b = scene.getObjectByName('barrels');
    b.updateWorldMatrix(true, false);
    const mid = new T(0, 0, 2.6).applyMatrix4(b.matrixWorld);
    const tip = new T(0, 0, 3.5).applyMatrix4(b.matrixWorld);
    const axis = tip.clone().sub(mid).normalize();
    const side = new T(0, 1, 0).cross(axis).normalize();
    const look = view === 'side' ? mid : tip;
    const pos = view === 'side'
        ? mid.clone().addScaledVector(side, 3.2).add(new T(0, 0.8, 0))
        : tip.clone().addScaledVector(axis, 2.6).addScaledVector(side, 0.9).add(new T(0, 0.4, 0));
    camera.position.copy(pos);
    controls.target.copy(look);
    controls.update();
    const blur = b.children.find(c => c.material && c.material.uniforms && c.material.uniforms.uSpin);
    return blur.material.uniforms.uSpin.value;
}"""

CAPTURE_JS = """async ([view, count]) => {
    const { renderer, camera, scene } = window.__ciws;
    const T = camera.position.constructor;
    const canvas = renderer.domElement;
    const crop = document.createElement('canvas');
    const size = Math.round(canvas.height * 0.45);
    crop.width = crop.height = size;
    const ctx = crop.getContext('2d');
    const frames = [];
    const original = renderer.render.bind(renderer);
    renderer.render = (s, c) => {
        original(s, c);
        if (frames.length >= count) return;
        // Track the muzzle (front) or barrel middle (side) on screen as the turret moves
        const b = scene.getObjectByName('barrels');
        const p = new T(0, 0, view === 'side' ? 2.6 : 3.5).applyMatrix4(b.matrixWorld).project(camera);
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
    deadline = time.time() + 60
    while time.time() < deadline:
        spin = page.evaluate(POSE_JS, view)
        if spin > 0.99:
            break
        time.sleep(0.05)
    # Keep re-posing the camera so it stays on the barrels during the capture
    page.evaluate("""(pose) => { window.__poseLoop = setInterval(() => (0, eval)(pose)(%r), 16); }""" % view, POSE_JS)
    frames = [Image.open(io.BytesIO(base64.b64decode(f))).convert("RGB") for f in page.evaluate(CAPTURE_JS, [view, count])]
report_errors(errors)

w, h = frames[0].size
thumb = 220
cols = 8
rows = (len(frames) + cols - 1) // cols
strip = Image.new("RGB", (cols * thumb, rows * thumb), "white")
for i, f in enumerate(frames):
    strip.paste(f.resize((thumb, thumb)), ((i % cols) * thumb, (i // cols) * thumb))
strip.save(f"{prefix}-strip.png")
frames[0].save(f"{prefix}.gif", save_all=True, append_images=frames[1:], duration=20, loop=0)
print("wrote", f"{prefix}-strip.png", f"{prefix}.gif", f"({len(frames)} frames, {w}x{h})")
