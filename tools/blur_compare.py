# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Compare the real barrel meshes with the motion-blur proxy at chosen shutter sweeps, on one frame.

Usage: uv run tools/blur_compare.py OUT.png [side|front] [sweep ...]
Idles the gun, poses the camera close to the barrels and renders the same frame with the real
meshes, then with the blur proxy forced on at each sweep (radians; default 0, 0.5, 1.2, 3.9).
At sweep 0 the proxy should be indistinguishable from the meshes. Writes the crops side by side.
"""
import base64
import io
import sys
import time

from PIL import Image

from _harness import contact_sheet, game_page, report_errors

out = sys.argv[1]
view = sys.argv[2] if len(sys.argv) > 2 else "side"
sweeps = [float(s) for s in sys.argv[3:]] or [0, 0.5, 1.2, 3.9]

RENDER_JS = """([view, sweeps]) => {
    const { scene, camera, renderer } = window.__ciws;
    const T = camera.position.constructor;
    const b = scene.getObjectByName('barrels');
    b.updateWorldMatrix(true, false);
    const mid = new T(0, 0, 2.6).applyMatrix4(b.matrixWorld);
    const tip = new T(0, 0, 3.5).applyMatrix4(b.matrixWorld);
    const axis = tip.clone().sub(mid).normalize();
    const side = new T(0, 1, 0).cross(axis).normalize();
    const look = view === 'side' ? mid : tip;
    camera.position.copy(view === 'side'
        ? mid.clone().addScaledVector(side, 2.2).add(new T(0, 0.6, 0))
        : tip.clone().addScaledVector(axis, 1.8).addScaledVector(side, 0.6).add(new T(0, 0.3, 0)));
    camera.lookAt(look);
    camera.updateMatrixWorld();

    const proxy = b.children.find(c => c.material && c.material.uniforms && c.material.uniforms.uSweep);
    const tubes = b.children.filter(c => c.isMesh && c.geometry.type === 'CylinderGeometry' && c.geometry.parameters.radiusTop < 0.1);
    const bores = b.children.find(c => c.isMesh && c.material.vertexColors);
    const canvas = renderer.domElement;
    const size = Math.round(canvas.height * 0.6);
    const crop = document.createElement('canvas');
    crop.width = crop.height = size;
    const ctx = crop.getContext('2d');
    const p = look.clone().project(camera);
    const grab = () => {
        renderer.render(scene, camera);
        ctx.drawImage(canvas, (p.x + 1) / 2 * canvas.width - size / 2, (1 - p.y) / 2 * canvas.height - size / 2,
                      size, size, 0, 0, size, size);
        return crop.toDataURL('image/png').split(',')[1];
    };
    const setBlur = on => {
        proxy.visible = on;
        bores.visible = !on;
        tubes.forEach(t => {
            t.material.colorWrite = t.material.depthWrite = !on;
            t.children.forEach(o => { o.visible = !on; });
        });
    };
    setBlur(false);
    const shots = [grab()];
    setBlur(true);
    proxy.material.uniforms.uPhase.value = 0;
    for (const s of sweeps) {
        proxy.material.uniforms.uSweep.value = s;
        proxy.material.uniforms.uGlint.value = Math.min(1, Math.max(0, (s - 0.3) / 1.2));
        shots.push(grab());
    }
    return shots;
}"""

with game_page(dpr=2) as (page, errors):
    page.evaluate("() => { const d = window.__ciws.debug; d.holdSpawns(); d.clearThreats(); }")
    time.sleep(3)
    shots = page.evaluate(RENDER_JS, [view, sweeps])
report_errors(errors)

images = [Image.open(io.BytesIO(base64.b64decode(s))).convert("RGB") for s in shots]
contact_sheet([im.resize((400, 400)) for im in images], len(images)).save(out)
print("wrote", out, "(meshes, then sweeps", sweeps, ")")
