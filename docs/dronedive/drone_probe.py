# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Baseline probe of drone flight and fate (read-only: no changes to the game).

Usage: uv run drone_probe.py OUT.json [seconds] [wave]
Plays the game at a forced wave and records, for every threat: type, spawn position, target type,
speed, a sample of (range to its target, height, speed) every few frames, the height where it
enters the gun's reach (472 units from the mount), and how it ended (killed / leaked) with where.
"""
import json
import sys
import time

sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors  # noqa: E402

out = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 90
wave = int(sys.argv[3]) if len(sys.argv) > 3 else 5

WATCH_JS = """(wave) => {
    const d = window.__ciws.debug;
    d.setWave(wave);
    const REACH = window.__ciwsML.consts.NN_REACH;
    const live = new Map();
    const done = [];
    window.__probe = { done, live };
    let frame = 0;
    const tick = () => {
        frame++;
        const now = new Set(d.missiles);
        for (const m of d.missiles) {
            let r = live.get(m);
            const p = m.mesh.position, t = m.targetInfo.position;
            const hr = Math.hypot(p.x - t.x, p.z - t.z);
            const mountR = Math.hypot(p.x, p.y - 6, p.z);
            if (!r) {
                r = { type: m.type, target: m.targetInfo.type, spawn: [p.x, p.y, p.z], targetPos: [t.x, t.y, t.z],
                      speed: m.velocity.length(), samples: [], reachY: null, reachSimT: null, spawnSimT: d.simTime };
                live.set(m, r);
            }
            if (r.reachY === null && mountR < REACH) { r.reachY = p.y; r.reachSimT = d.simTime; }
            if (frame % 6 === 0) r.samples.push([+hr.toFixed(1), +p.y.toFixed(2), +m.velocity.length().toFixed(3)]);
            r.last = [p.x, p.y, p.z, hr, mountR, m.health];
        }
        for (const [m, r] of live) {
            if (!now.has(m)) {
                live.delete(m);
                r.fate = m.health <= 0 ? 'killed' : 'leaked';
                r.endSimT = d.simTime;
                done.push(r);
            }
        }
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}"""

with game_page(console_levels=("error",)) as (page, errors):
    time.sleep(2)
    page.evaluate(WATCH_JS, wave)
    start = time.time()
    while time.time() - start < seconds:
        time.sleep(10)
        n = page.evaluate("() => window.__probe.done.length")
        print(f"t={time.time() - start:4.0f}s done={n}", flush=True)
    data = page.evaluate("() => ({ done: window.__probe.done, stats: window.__ciws.debug.stats, simTime: window.__ciws.debug.simTime })")
report_errors(errors)
with open(out, "w") as f:
    json.dump(data, f)
print("wrote", out)
