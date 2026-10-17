# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Probe: kill a moving anti-ship missile the way the game does (createExplosion(pos, 'airburst')
then dispose) and record, every rendered frame, where the debris, sparks and new puffs are
relative to the burst point and to where the missile would have been (pos + v t).

Usage: uv run momentum_probe.py OUT_PREFIX
Writes OUT_PREFIX-data.json and OUT_PREFIX-strip.png (every 4th frame, abeam camera; the red
cross marks the missile's extrapolated position, the blue cross the burst point).
"""
import base64
import io
import json
import sys
import time

sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from PIL import Image, ImageDraw  # noqa: E402

from _harness import contact_sheet, game_page, report_errors  # noqa: E402

prefix = sys.argv[1]
FRAMES = 90

SETUP_JS = """() => {
    const c = window.__ciws, d = c.debug;
    document.getElementById('hud').style.display = 'none';
    d.holdSpawns(); d.holdVLS(); d.clearThreats();
    const m = d.spawnAntiShipMissile();
    m.mesh.position.set(-700, 10, 40);   // outside gun reach so nothing else is exploding
    window.__m = m;
    return true;
}"""

CAPTURE_JS = """async (count) => {
    const c = window.__ciws, d = c.debug, { renderer, camera, scene } = c;
    const T = camera.position.constructor;
    const m = window.__m;
    // Velocity per step -> per second
    const vStep = m.velocity.clone();
    const vSec = vStep.clone().multiplyScalar(60);
    const p0 = m.mesh.position.clone();
    // Abeam camera, 45 m to the side of the path, looking 25 m downrange of the burst
    const dir = vSec.clone().normalize();
    const side = new T(0, 1, 0).cross(dir).normalize();
    const look = p0.clone().addScaledVector(dir, 25);
    c.controls.enabled = false;
    camera.position.copy(look).addScaledVector(side, 55).add(new T(0, 6, 0));
    camera.lookAt(look);
    const before = new Set(scene.children);
    c.createExplosion(p0, 'airburst');
    d.clearThreats();
    const t0 = performance.now();
    const canvas = renderer.domElement;
    const shot = document.createElement('canvas');
    shot.width = 640; shot.height = Math.round(640 * canvas.height / canvas.width);
    const ctx = shot.getContext('2d');
    const frames = [], data = [];
    const original = renderer.render.bind(renderer);
    const proj = v => { const q = v.clone().project(camera); return [(q.x + 1) / 2 * shot.width, (1 - q.y) / 2 * shot.height]; };
    let simT = 0, last = performance.now();
    renderer.render = (s, cam) => {
        camera.position.copy(look).addScaledVector(side, 55).add(new T(0, 6, 0));
        camera.lookAt(look);
        original(s, cam);
        if (frames.length >= count) return;
        const now = performance.now(); simT += (now - last) / 1000; last = now;
        const fresh = scene.children.filter(o => !before.has(o) && o.visible && o.position.distanceTo(p0) < 80);
        const debris = fresh.filter(o => o.isMesh && o.geometry.type === 'DodecahedronGeometry');
        const puffs = fresh.filter(o => o.isMesh && o.material.uniforms && o.material.uniforms.uDissolve);
        const spark = scene.children.find(o => o.isInstancedMesh && o.geometry.type === 'BoxGeometry');
        const mean = arr => { if (!arr.length) return null; const s = new T(); arr.forEach(a => s.add(a)); return s.divideScalar(arr.length); };
        const rel = v => v ? [v.x - p0.x, v.y - p0.y, v.z - p0.z].map(x => +x.toFixed(2)) : null;
        const sp = [];
        if (spark) { const M = new c.camera.matrix.constructor(); for (let i = 0; i < spark.count; i++) { spark.getMatrixAt(i, M); const q = new T().setFromMatrixPosition(M); if (q.distanceTo(p0) < 80) sp.push(q); } }
        const dc = mean(debris.map(o => o.position)), pc = mean(puffs.map(o => o.position)), sc = mean(sp);
        const along = v => v ? +(v.clone().sub(p0).dot(dir)).toFixed(2) : null;
        data.push({ t: +((now - t0) / 1000).toFixed(3), nDebris: debris.length, nPuffs: puffs.length, nSparks: sp.length,
                    debris: rel(dc), puffs: rel(pc), sparks: rel(sc),
                    alongDebris: along(dc), alongPuffs: along(pc), alongSparks: along(sc),
                    alongMissile: +((now - t0) / 1000 * vSec.length()).toFixed(2) });
        ctx.drawImage(canvas, 0, 0, shot.width, shot.height);
        const ghost = p0.clone().addScaledVector(vSec, (now - t0) / 1000);
        const mark = (pt, col) => { const [x, y] = proj(pt); ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x - 7, y); ctx.lineTo(x + 7, y); ctx.moveTo(x, y - 7); ctx.lineTo(x, y + 7); ctx.stroke(); };
        mark(p0, '#06f'); mark(ghost, '#f00');
        ctx.fillStyle = '#000'; ctx.font = '14px sans-serif'; ctx.fillText(`t=${((now - t0) / 1000).toFixed(2)}s`, 8, 18);
        frames.push(shot.toDataURL('image/png').split(',')[1]);
    };
    while (frames.length < count) await new Promise(r => requestAnimationFrame(r));
    renderer.render = original;
    return { frames, data, vStep: vStep.toArray(), vSec: vSec.toArray(), speed: vSec.length() };
}"""

with game_page(dpr=1) as (page, errors):
    time.sleep(4)
    page.evaluate(SETUP_JS)
    time.sleep(0.4)  # let it steer, so its velocity is set
    res = page.evaluate(CAPTURE_JS, FRAMES)
report_errors(errors)

frames = [Image.open(io.BytesIO(base64.b64decode(f))).convert("RGB") for f in res.pop("frames")]
contact_sheet([f.resize((320, int(320 * f.height / f.width))) for f in frames[::6][:15]], 5).save(f"{prefix}-strip.png")
with open(f"{prefix}-data.json", "w") as fh:
    json.dump(res, fh, indent=1)
print("speed m/s", round(res["speed"], 1), "vStep", [round(x, 3) for x in res["vStep"]])
for row in res["data"][::6]:
    print(row["t"], "missile", row["alongMissile"], "debris", row["alongDebris"], row["nDebris"],
          "puffs", row["alongPuffs"], row["nPuffs"], "sparks", row["alongSparks"], row["nSparks"])
