# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Probe the drones' flight: cruise height, pushover, dive angle and speed, against the plan's model.

Usage: uv run tools/dive_probe.py OUT.json [--wave N] [--seconds S] [--grid]
Default: plays at wave N (default 3) for S seconds (default 120) and records every threat's spawn,
target and fate, and for drones a sample every frame of (range to the aim point in plan, height,
speed, pitch, flight phase). --grid instead holds the spawns and sends in a set of invulnerable
drones (cruise heights 30-90 by dive angles 30-45, alternately at our ship and a friendly, from
spread bearings); their targets are marked so reaching them does no damage, so each dive runs to
the end. Prints, per drone that reached its target, the measured pushover range, impact angle and
speed, dive time and flight time beside the plan's model of the same drone (docs/dronedive/PLAN.md:
level cruise, the geometric pushover trigger, a 45°/s turn toward the line of sight, speed toward
cruise x (1 + 0.6 sin pitch) with a 42-step time constant), and the plan's acceptance checks: spawn
heights, impact angle within 3° of the dive angle (cruise height >= 45), turn rate, speed rise,
NaNs and loop-backs.
"""
import json
import math
import sys
import time

from _harness import QUIET_SCENE_JS, game_page, report_errors

argv = sys.argv[1:]
out = argv[0]
wave = int(argv[argv.index("--wave") + 1]) if "--wave" in argv else 3
seconds = float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else 120
grid = "--grid" in argv

WATCH_JS = """({ wave, grid }) => {
    const d = window.__ciws.debug;
    d.setWave(wave);
    const live = new Map(), done = [];
    window.__probe = { done, live };
    if (grid) {
        let i = 0;
        for (const height of [30, 45, 60, 75, 90]) {
            for (const gamma of [30, 37.5, 45]) {
                for (const friendly of [false, true]) {
                    const m = d.spawnDrone({ angle: i * 2.39996, height, gamma, invulnerable: true, targetIndex: friendly ? i % 5 : null });
                    m.probeTarget = m.targetInfo.type;
                    m.targetInfo.type = 'probe'; // reaching it does nothing
                    i++;
                }
            }
        }
    }
    const tick = () => {
        const now = new Set(d.missiles);
        for (const m of d.missiles) {
            let r = live.get(m);
            const p = m.mesh.position, t = m.targetInfo.position, v = m.velocity;
            if (!r) {
                r = { type: m.type, target: m.probeTarget ?? m.targetInfo.type, spawn: [p.x, p.y, p.z], aim: [t.x, t.y, t.z],
                      spawnSimT: d.simTime, samples: [] };
                if (m.dive) Object.assign(r, { gamma: m.dive.gamma * 180 / Math.PI, cruise: m.dive.cruise, pushoverRange: m.dive.pushoverRange });
                live.set(m, r);
            }
            const speed = v.length();
            r.last = [p.x, p.y, p.z, Math.hypot(p.x, p.y - 6, p.z), speed, -Math.asin(v.y / speed) * 180 / Math.PI];
            if (m.dive) r.samples.push([+d.simTime.toFixed(4), +Math.hypot(p.x - t.x, p.z - t.z).toFixed(2), +p.y.toFixed(2),
                +speed.toFixed(4), +(-Math.asin(v.y / speed) * 180 / Math.PI).toFixed(2), m.dive.phase[0], +v.x.toFixed(5), +v.y.toFixed(5), +v.z.toFixed(5)]);
        }
        for (const [m, r] of live) {
            if (!now.has(m)) {
                live.delete(m);
                r.fate = m.health <= 0 ? 'killed' : 'arrived';
                r.endSimT = d.simTime;
                if (m.dive) r.endPhase = m.dive.phase;
                done.push(r);
            }
        }
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}"""

SPS = 60
TURN = math.radians(45) / SPS
SPEEDUP, TAU, FIT, RADIUS = 0.6, 42, 0.6, 5


def model(dist, height, aim_y, gamma_deg, cruise):
    """The plan's flight model in the vertical plane through the aim point, a step at a time.
    profile: (range in plan, height, speed m/s, pitch degrees) at each step."""
    drop = height - aim_y
    r_turn = cruise / TURN
    gamma = min(math.radians(gamma_deg), math.acos(max(-1, min(1, 1 - FIT * drop / r_turn))))
    x_p = drop / math.tan(gamma) + r_turn * math.tan(gamma / 2)
    x, y, pitch, speed, t, phase = dist, height, 0.0, cruise, 0, "c"
    pushover, profile = None, []
    while t < 4000:
        profile.append((x, y, speed * SPS, math.degrees(pitch)))
        nx, ny = x - math.cos(pitch) * speed, y - math.sin(pitch) * speed
        # Swept hit test against the aim point at (0, aim_y)
        ax, ay, bx, by = x, y - aim_y, nx, ny - aim_y
        sx, sy = bx - ax, by - ay
        a2, b2, c2 = sx * sx + sy * sy, ax * sx + ay * sy, ax * ax + ay * ay - RADIUS * RADIUS
        disc = b2 * b2 - a2 * c2
        if b2 < 0 and disc >= 0 and (-b2 - math.sqrt(disc)) / a2 <= 1:
            break
        x, y, t = nx, ny, t + 1
        if phase == "c" and x <= x_p:
            phase, pushover = "p", (x, t)
        if phase != "c":
            los = math.atan2(y - aim_y, x)
            off = los - pitch
            pitch += max(-TURN, min(TURN, off))
            speed += (cruise * (1 + SPEEDUP * max(0, math.sin(pitch))) - speed) * (1 - math.exp(-1 / TAU))
    return {"gamma": math.degrees(gamma), "pushover": pushover[0] if pushover else None,
            "impactDeg": math.degrees(pitch), "impactSpeed": speed * SPS,
            "diveS": (t - pushover[1]) / SPS if pushover else None, "flightS": t / SPS, "profile": profile}


def turn_rates(samples):
    rates = []
    for a, b in zip(samples, samples[1:]):
        dt = (b[0] - a[0]) * SPS
        if dt <= 0:
            continue
        u, v = a[6:9], b[6:9]
        nu, nv = math.sqrt(sum(c * c for c in u)), math.sqrt(sum(c * c for c in v))
        cos = max(-1, min(1, sum(p * q for p, q in zip(u, v)) / (nu * nv)))
        rates.append(math.degrees(math.acos(cos)) / dt * SPS)
    return rates


def summarize(done):
    drones = [r for r in done if r["type"] == "drone"]
    print(f"{len(done)} threats ended, {len(drones)} drones")
    if not drones:
        return
    hs = sorted(r["spawn"][1] for r in drones)
    print(f"spawn height: min {hs[0]:.1f} median {hs[len(hs) // 2]:.1f} mean {sum(hs) / len(hs):.1f} max {hs[-1]:.1f}")
    nan = sum(any(isinstance(x, float) and math.isnan(x) for s in r["samples"] for x in s[1:5]) for r in drones)
    loops = sum(any(b[1] > a[1] + 0.05 for a, b in zip(r["samples"], r["samples"][1:])) for r in drones)
    rates = [x for r in drones for x in turn_rates(r["samples"])]
    print(f"NaN drones {nan}; loop-backs (range to aim growing) {loops}; max turn rate {max(rates):.1f} deg/s")
    arrived = [r for r in drones if r["fate"] == "arrived"]
    print(f"\n{'target':8s} {'h':>4s} {'aimY':>5s} {'gamma':>5s} | {'pushover':>15s} | {'impact deg':>11s} | {'impact m/s':>11s} | {'speed x':>7s} | {'dive s':>9s} | {'flight s':>11s}")
    print(f"{'':8s} {'':4s} {'':5s} {'':5s} | {'game':>7s} {'model':>7s} | {'game':>5s} {'model':>5s} | {'game':>5s} {'model':>5s} | {'game':>7s} | {'game':>4s} {'mdl':>4s} | {'game':>5s} {'model':>5s}")
    errs = []
    for r in sorted(arrived, key=lambda r: (r["target"], r["spawn"][1], r["gamma"])):
        s = r["samples"]
        dist = math.hypot(r["spawn"][0] - r["aim"][0], r["spawn"][2] - r["aim"][2])
        m = model(dist, r["spawn"][1], r["aim"][1], r["gamma"], r["cruise"])
        po = next((a for a in s if a[5] != "c"), None)
        impact = r["last"][5]
        dive = r["endSimT"] - po[0] if po else float("nan")
        flight = r["endSimT"] - r["spawnSimT"]
        if r["spawn"][1] >= 45:
            errs.append(impact - r["gamma"])
        print(f"{r['target']:8s} {r['spawn'][1]:4.0f} {r['aim'][1]:5.1f} {r['gamma']:5.1f} | {po[1] if po else float('nan'):7.1f} {m['pushover']:7.1f} | "
              f"{impact:5.1f} {m['impactDeg']:5.1f} | {r['last'][4] * SPS:5.1f} {m['impactSpeed']:5.1f} | {r['last'][4] / r['cruise']:7.2f} | "
              f"{dive:4.2f} {m['diveS']:4.2f} | {flight:5.2f} {m['flightS']:5.2f}")
    if errs:
        print(f"\nimpact angle - dive angle, cruise height >= 45: mean {sum(errs) / len(errs):+.2f}, worst {max(errs, key=abs):+.2f} deg (n={len(errs)})")
    for fate in ("killed", "arrived"):
        rs = [r for r in drones if r["fate"] == fate]
        if rs:
            phases = {p: sum(r["endPhase"] == p for r in rs) for p in ("cruise", "pushover", "terminal")}
            print(f"{fate}: {len(rs)}, phase at the end {phases}")


with game_page(console_levels=("error",)) as (page, errors):
    time.sleep(2)
    if grid:
        page.evaluate(QUIET_SCENE_JS, False)
    page.evaluate(WATCH_JS, {"wave": wave, "grid": grid})
    start = time.time()
    while time.time() - start < seconds:
        time.sleep(5)
        n, alive = page.evaluate("() => [window.__probe.done.length, window.__probe.live.size]")
        print(f"t={time.time() - start:4.0f}s done={n}", flush=True)
        if grid and alive == 0:
            break
    data = page.evaluate("() => ({ done: window.__probe.done, stats: window.__ciws.debug.stats, simTime: window.__ciws.debug.simTime })")
report_errors(errors)
with open(out, "w") as f:
    json.dump(data, f)
print("wrote", out)
summarize(data["done"])
