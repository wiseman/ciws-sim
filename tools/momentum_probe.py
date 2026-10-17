# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Probe explosion momentum: kill a moving threat the way the game does (createExplosion(pos,
'hit', v) and createExplosion(pos, 'airburst', v), then dispose) and record, every rendered frame,
where the debris, sparks, puffs and the flash and shock ring are along the flight direction,
against sim time (debug.simTime), next to where the threat would have been (pos + v t).

Usage: uv run tools/momentum_probe.py OUT_PREFIX [ascm|drone|mortar|still] [abeam|down] [--slow K]
  ascm:   a real anti-ship missile, killed out of the gun's reach (about 160 m/s)
  drone:  a burst carrying a level 50 m/s; mortar: a capped, descending 250 m/s at 45 degrees
  still:  the ascm case passing no velocity (the look before explosions carried momentum)
  abeam:  a camera beside the path; down: behind the burst, looking along the path
  --slow: run the explosion at timeScale K (0.1 is the game's slow motion); sim time is unchanged
Writes OUT_PREFIX-data.json and OUT_PREFIX-strip.png (a frame every 0.1 sim s; the red cross marks
the threat's extrapolated position, the blue cross the burst point) and prints the centroids.
"""
import json
import sys
import time

from _harness import FRAME_CAPTURE_JS, QUIET_SCENE_JS, game_page, report_errors, save_strip

args = sys.argv[1:]
slow = 1.0
if "--slow" in args:
    i = args.index("--slow")
    slow = float(args[i + 1])
    del args[i:i + 2]
prefix = args[0]
case = args[1] if len(args) > 1 else "ascm"
view = args[2] if len(args) > 2 else "abeam"
DURATION = 1.45  # sim seconds
SAMPLES = [round(0.1 * i, 2) for i in range(15)]

SETUP_JS = """() => {
    const d = window.__ciws.debug;
    const m = d.spawnAntiShipMissile();
    m.mesh.position.set(-700, 10, 40);   // outside gun reach so nothing else is exploding
    window.__m = m;
    return true;
}"""

CAPTURE_JS = """async ([kase, view, slow, duration, samples]) => {
    const c = window.__ciws, d = c.debug, { camera, scene } = c;
    const T = camera.position.constructor;
    const m = window.__m;
    // Velocity per step (what createExplosion takes) and per second
    const vStep = kase === 'drone' ? new T(0.83, 0, 0.1)
        : kase === 'mortar' ? new T(2.95, -2.95, 0.3)
        : m.velocity.clone();
    const vSec = vStep.clone().multiplyScalar(60);
    const p0 = m.mesh.position.clone();
    if (kase === 'mortar') p0.y = 45;
    const dir = vSec.clone().normalize();
    const flat = new T(dir.x, 0, dir.z).normalize();
    const side = new T(0, 1, 0).cross(flat).normalize();
    // abeam: 55 m to the side, looking 30 m downrange; down: 30 m behind and 8 up, looking along the path
    const look = view === 'down' ? p0.clone().addScaledVector(dir, 40) : p0.clone().addScaledVector(dir, 30);
    const eye = view === 'down' ? p0.clone().addScaledVector(dir, -30).add(new T(0, 8, 0))
        : look.clone().addScaledVector(side, 55).add(new T(0, 6, 0));
    c.controls.enabled = false;
    const pose = () => { camera.position.copy(eye); camera.lookAt(look); };
    pose();
    d.setTimeScale(slow);
    const before = new Set(scene.children);
    const s0 = d.simTime;
    const vel = kase === 'still' ? null : vStep;
    c.createExplosion(p0, 'hit', vel);
    c.createExplosion(p0, 'airburst', vel);
    d.clearThreats();
    const data = [];
    const canvas = c.renderer.domElement, shotW = 960, shotH = Math.round(960 * canvas.height / canvas.width);
    const proj = v => { const q = v.clone().project(camera); return [(q.x + 1) / 2 * shotW, (1 - q.y) / 2 * shotH]; };
    const along = v => v ? +(v.clone().sub(p0).dot(dir)).toFixed(2) : null;
    const mean = arr => { if (!arr.length) return null; const s = new T(); arr.forEach(a => s.add(a)); return s.divideScalar(arr.length); };
    const M = new c.camera.matrix.constructor();
    // Every frame up to `duration`: where the debris, puffs, sparks and flash and ring are
    const record = t => {
        const fresh = scene.children.filter(o => !before.has(o) && o.visible && o.position.distanceTo(p0) < 300);
        const debris = fresh.filter(o => o.isMesh && o.geometry.type === 'DodecahedronGeometry');
        const puffs = fresh.filter(o => o.isMesh && o.material.uniforms && o.material.uniforms.uDissolve);
        const boards = fresh.filter(o => o.isMesh && o.material.uniforms && o.material.uniforms.uSize);
        const spark = scene.children.find(o => o.isInstancedMesh && o.geometry.type === 'BoxGeometry');
        const sp = [];
        if (spark) for (let i = 0; i < spark.count; i++) { spark.getMatrixAt(i, M); const q = new T().setFromMatrixPosition(M); if (q.distanceTo(p0) < 300) sp.push(q); }
        const dc = mean(debris.map(o => o.position)), pc = mean(puffs.map(o => o.position)), sc = mean(sp), bc = mean(boards.map(o => o.position));
        const maxDebris = debris.length ? Math.max(...debris.map(o => along(o.position))) : null;
        data.push({ t: +t.toFixed(3), nDebris: debris.length, nPuffs: puffs.length, nSparks: sp.length, nBoards: boards.length,
                    alongDebris: along(dc), maxDebris, alongPuffs: along(pc), alongSparks: along(sc), alongBoards: along(bc),
                    debrisY: dc ? +(dc.y - p0.y).toFixed(2) : null, alongThreat: +(t * vSec.length()).toFixed(2) });
    };
    const frames = await window.__captureFrames({
        samples, until: duration, before: pose,
        frameTime: () => {
            const t = d.simTime - s0;
            if (t <= duration) record(t);
            return t;
        },
        // The burst point (blue) and the threat's extrapolated position (red)
        decorate: (ctx, t) => {
            const mark = (pt, col) => { const [x, y] = proj(pt); ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x - 7, y); ctx.lineTo(x + 7, y); ctx.moveTo(x, y - 7); ctx.lineTo(x, y + 7); ctx.stroke(); };
            mark(p0, '#06f'); mark(p0.clone().addScaledVector(vSec, t), '#f00');
        }
    });
    d.setTimeScale(1);
    return { frames, data, vStep: vStep.toArray(), vSec: vSec.toArray(), speed: vSec.length(), fx: d.fx };
}"""

with game_page(dpr=1, console_levels=("error", "warning")) as (page, errors):
    time.sleep(4)
    page.evaluate(QUIET_SCENE_JS, True)
    page.evaluate(FRAME_CAPTURE_JS)
    page.evaluate(SETUP_JS)
    time.sleep(0.4)  # let it steer, so its velocity is set
    res = page.evaluate(CAPTURE_JS, [case, view, slow, DURATION, SAMPLES])
report_errors(errors)

save_strip(res.pop("frames"), f"{prefix}-strip.png")
with open(f"{prefix}-data.json", "w") as fh:
    json.dump(res, fh, indent=1)
print(f"{case} {view} timeScale {slow}: speed {res['speed']:.1f} m/s, vStep {[round(x, 3) for x in res['vStep']]}")
print("  t      threat  debris (max, n, dy)        puffs (n)     sparks (n)    flash/ring")
for want in (0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.25, 1.4):
    row = min(res["data"], key=lambda r: abs(r["t"] - want))
    print(f"  {row['t']:.2f}  {row['alongThreat']:7.1f}  {row['alongDebris']} ({row['maxDebris']}, {row['nDebris']}, {row['debrisY']})"
          f"  {row['alongPuffs']} ({row['nPuffs']})  {row['alongSparks']} ({row['nSparks']})  {row['alongBoards']} ({row['nBoards']})")
