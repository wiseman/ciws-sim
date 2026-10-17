# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Which damage-control calls drone hits on our ship would choose, now and before the dive change.

Usage: uv run docs/dronedive/dc_tally.py [n]
Now: holds the spawns and the gun's fire and sends in n drones (default 60) at our ship from random
bearings, a few at a time, marked so reaching her does no damage, and records where each goes off
(what callDamageControl gets). Before: drones flew straight from 600 out at a height of 20-60 at
the mount (0, 6, 0) and went off 5 short of it, worked out here. Each burst point is turned into
the call announceDamage would choose (DC_CALLS in index.html: same side, a drone's call, not the
last one made, nearest frame), and the calls are tallied.
"""
import math
import random
import sys
import time
from collections import Counter

sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
BOW, STERN, FRAMES = -42, 70, 460
DC_CALLS = [
    ("dc-hit-stbd-fwd", 1, 80, True), ("dc-hit", 1, 210, True), ("dc-hit-port", -1, 160, True),
    ("dc-hit-port-aft", -1, 310, True), ("dc-fire-bravo", 1, 120, False), ("dc-fire-charlie-stbd", 1, 150, False),
    ("dc-fire-alpha-port", -1, 96, False), ("dc-flooding-port", -1, 180, False), ("dc-fire-bravo-port", -1, 220, False),
    ("dc-fire-charlie", -1, 240, False), ("dc-flooding", 0, 142, False),
]


def calls(points):
    last, out = None, []
    for x, _, z in points:
        side = 0 if abs(x) < 1.2 else (1 if x > 0 else -1)
        frame = (z - BOW) / (STERN - BOW) * FRAMES
        sided = [c for c in DC_CALLS if c[1] == side]
        fresh = [c for c in sided if c[0] != last]
        kind = [c for c in fresh if not c[3]]
        choices = kind or fresh or sided
        call = min(choices, key=lambda c: abs(c[2] - frame))
        last = call[0]
        out.append((call[0], side, round(frame)))
    return out


def before(count):
    rng = random.Random(1)
    pts = []
    for _ in range(count):
        a, h = rng.random() * 2 * math.pi, 20 + 40 * rng.random()
        p = (math.cos(a) * 600, h, math.sin(a) * 600)
        d = [0 - p[0], 6 - p[1], 0 - p[2]]
        L = math.sqrt(sum(c * c for c in d))
        pts.append(tuple(c * 5 / L * -1 + t for c, t in zip(d, (0, 6, 0))))
    return pts


JS = """async (n) => {
    const d = window.__ciws.debug;
    d.holdSpawns(); d.holdVLS(); d.holdFire(); d.clearThreats(); d.setWave(3);
    const bursts = [];
    for (let i = 0; i < n; i++) {
        const m = d.spawnDrone();
        m.targetInfo.type = 'probe'; // reaching her does nothing
        const watch = () => { if (m.mesh.parent) { requestAnimationFrame(watch); return; } bursts.push(m.mesh.position.toArray()); };
        requestAnimationFrame(watch);
        if (i % 6 === 5) await new Promise(r => setTimeout(r, 500));
    }
    while (bursts.length < n) await new Promise(r => setTimeout(r, 500));
    return bursts;
}"""

with game_page(console_levels=("error",)) as (page, errors):
    time.sleep(2)
    now = page.evaluate(JS, n)
report_errors(errors)
for label, pts in (("before (at the mount)", before(n)), ("now (strike points)", now)):
    cs = calls(pts)
    frames = sorted(f for _, _, f in cs)
    sides = Counter({-1: "port", 0: "centreline", 1: "starboard"}[s] for _, s, _ in cs)
    print(f"== {label}: {len(cs)} hits; sides {dict(sides)}; frames {frames[0]}-{frames[-1]} (median {frames[len(frames) // 2]})")
    for name, k in Counter(c for c, _, _ in cs).most_common():
        print(f"   {name:22s} {k}")
