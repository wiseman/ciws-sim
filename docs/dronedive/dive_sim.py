# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy"]
# ///
"""Offline model of the proposed drone dive and of the classic solver's lead error against it.

Usage: uv run dive_sim.py
Re-implements, in game units (1 unit ~ 1 m, velocities per sim step, 60 steps/s):
  - the classic solver (solveInterceptSteps + computeAimSolution's non-mortar branch: constant
    velocity, plus 0.5 g t^2 of drop added to the aim point),
  - a round (8 u/step, gravity 0.02 u/step^2 applied before each move, 59 moves),
  - the hit test (within 1 unit of the round's ray and 3 of its position, approximated as the
    closest approach of the round's per-step segments),
  - the radar track noise (position error base 0.3 + 0.00375 * range, vertical x0.45; velocity
    error 4% of speed; reseeded every 6-18 steps, blended at 0.08/step) and the gun's spread
    (+-0.00625 rad in two axes),
and a candidate drone flight model: level cruise, a rate-limited pushover into pure pursuit of
the target point, and a speed-up toward a dive speed. Prints:
  1. the dive geometry for a grid of altitudes / dive angles (where the pushover starts, how long
     the dive lasts, the impact angle and speed),
  2. the noiseless miss distance of the classic solver vs time of flight for each flight phase,
  3. Monte Carlo hit probability per round vs range for current and new drones, with and without
     an acceleration-aware track velocity for drones.
"""
import math

import numpy as np

G = 0.02
S = 8.0
LIFE = 59
MAX_INTERCEPT = 240
SPS = 60
MUZZLE = np.array([0.0, 9.0, 0.0])
SHIP_TARGET = np.array([0.0, 6.0, 0.0])
rng = np.random.default_rng(1)


def solve_intercept(D, V):
    a = V @ V - S * S
    b = 2 * D @ V
    c = D @ D
    if abs(a) < 1e-6:
        if abs(b) > 1e-6:
            t = -c / b
            return t if 0 < t <= MAX_INTERCEPT else None
        return None
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    r = math.sqrt(disc)
    cands = [t for t in ((-b - r) / (2 * a), (-b + r) / (2 * a)) if t > 0]
    if not cands:
        return None
    t = min(cands)
    return t if t <= MAX_INTERCEPT else None


def classic_aim(tpos, tvel, muzzle):
    D = tpos - muzzle
    t = solve_intercept(D, tvel)
    if t is None:
        return None, None
    aim = tpos + tvel * t
    aim = aim + np.array([0, 0.5 * G * t * t, 0])
    d = aim - muzzle
    return d / np.linalg.norm(d), t


# ---------------- drone flight models ----------------

class Drone:
    """mode 'current': straight line at constant speed to the target.
    mode 'dive': level cruise, then rate-limited pursuit of the target point once its depression
    angle passes `trigger_deg`, speeding up toward speed*(1 + speedup*sin(dive)).
    weave: (amplitude_deg, period_s) heading oscillation in cruise (0 = none)."""

    def __init__(self, mode, height, speed, target=SHIP_TARGET, dist=600.0, angle=0.0,
                 trigger_deg=40.0, turn_dps=40.0, speedup=0.6, tau_s=0.7, weave=(0.0, 4.0), phase=0.0, geometric=True):
        self.geometric = geometric
        self.mode = mode
        self.target = target.copy()
        self.pos = np.array([math.cos(angle) * dist, height, math.sin(angle) * dist])
        self.cruise = speed
        self.speed = speed
        self.trigger = math.radians(trigger_deg)
        self.turn = math.radians(turn_dps) / SPS  # rad/step
        self.speedup = speedup
        self.tau = tau_s * SPS
        self.weave_amp = math.radians(weave[0])
        self.weave_w = 2 * math.pi / (weave[1] * SPS)
        self.phase = phase
        self.t = 0.0
        self.state = 'cruise'
        if mode == 'current':
            d = self.target - self.pos
            self.vel = d / np.linalg.norm(d) * speed
        else:
            d = self.target - self.pos
            d[1] = 0
            self.vel = d / np.linalg.norm(d) * speed
        self.pushover_at = None
        self.terminal_at = None

    def step(self, dt=1.0):
        self.pos = self.pos + self.vel * dt
        self.t += dt
        if self.mode == 'current':
            return
        to = self.target - self.pos
        horiz = math.hypot(to[0], to[2])
        dep = math.atan2(-to[1], horiz)  # depression of the target below the drone
        if self.state == 'cruise':
            # hold altitude, head for the target in plan, optional weave
            psi = math.atan2(to[2], to[0]) + self.weave_amp * math.sin(self.weave_w * self.t + self.phase)
            desired = np.array([math.cos(psi), 0.0, math.sin(psi)])
            # Pushover where a circular arc of radius R = v/turn-rate from level flight joins the
            # dive line through the target at the chosen angle: R*tan(dive/2) before the point
            # where that line crosses the cruise altitude
            R = self.speed / self.turn
            x_p = -to[1] / math.tan(self.trigger) + R * math.tan(self.trigger / 2)
            if (self.geometric and horiz <= x_p) or (not self.geometric and dep >= self.trigger):
                self.state = 'terminal'
                self.pushover_at = (horiz, self.pos[1], self.t)
        if self.state == 'terminal':
            desired = to / np.linalg.norm(to)
            dive = max(0.0, math.asin(min(1.0, -self.vel[1] / np.linalg.norm(self.vel))))
            vt = self.cruise * (1 + self.speedup * math.sin(max(dive, 0)))
            self.speed += (vt - self.speed) * (1 - math.exp(-dt / self.tau))
        # rate-limited rotation of the velocity direction toward `desired`
        u = self.vel / np.linalg.norm(self.vel)
        cosang = float(np.clip(u @ desired, -1, 1))
        ang = math.acos(cosang)
        maxang = self.turn * dt
        if ang <= maxang or ang < 1e-9:
            nu = desired
        else:
            axis = np.cross(u, desired)
            axis /= np.linalg.norm(axis)
            # Rodrigues rotation of u about axis by maxang
            nu = (u * math.cos(maxang) + np.cross(axis, u) * math.sin(maxang)
                  + axis * (axis @ u) * (1 - math.cos(maxang)))
        self.vel = nu / np.linalg.norm(nu) * self.speed
        if self.state == 'terminal' and self.terminal_at is None and ang < math.radians(1):
            self.terminal_at = (horiz, self.pos[1], self.t)

    def done(self):
        return np.linalg.norm(self.pos - self.target) < 5 or self.pos[1] < -1.5


def fly(drone, max_steps=4000):
    """Returns a list of (pos, vel, state) per step until impact."""
    path = []
    for _ in range(max_steps):
        path.append((drone.pos.copy(), drone.vel.copy(), drone.state))
        if drone.done():
            break
        drone.step()
    return path


def closest_approach(path, k, aim_dir, muzzle):
    """Fire a round at step k along aim_dir; return the closest approach to the drone (true path)."""
    bp = muzzle.copy()
    bv = aim_dir * S
    best = 1e9
    for j in range(1, LIFE + 1):
        if k + j >= len(path):
            break
        prev = bp.copy()
        bv = bv + np.array([0, -G, 0])
        bp = bp + bv
        target = path[k + j][0]
        seg = bp - prev
        tt = np.clip((target - prev) @ seg / (seg @ seg), 0, 1)
        d = np.linalg.norm(prev + seg * tt - target)
        best = min(best, d)
    return best


def accel_estimate(path, k, window=6):
    if k < window:
        return np.zeros(3)
    return (path[k][1] - path[k - window][1]) / window


# ---------------- 1. dive geometry ----------------
print("=== 1. Dive geometry (ship target at y=6, wave-2 speed 0.9 u/step = 54 m/s) ===")
print("h   dive  turn  | pushover range, alt | terminal (aligned) range, alt | dive s | impact angle, speed m/s | flight s")
for h in (30, 45, 60, 75, 90):
    for trig in (30, 40, 50, 60):
        for turn in (40, 60):
            d = Drone('dive', h, 0.9, trigger_deg=trig, turn_dps=turn)
            p = fly(d)
            pos, vel, _ = p[-1]
            ang = math.degrees(math.asin(-vel[1] / np.linalg.norm(vel)))
            po = d.pushover_at
            ta = d.terminal_at or (float('nan'), float('nan'), float('nan'))
            print(f"{h:3d} {trig:4d} {turn:5d}  | {po[0]:6.1f} {po[1]:5.1f}       | {ta[0]:6.1f} {ta[1]:5.1f}              "
                  f"| {(d.t - po[2]) / SPS:5.2f} | {ang:5.1f} {np.linalg.norm(vel) * SPS:6.1f}           | {d.t / SPS:5.2f}")

# ---------------- 2. noiseless miss vs TOF per phase ----------------
print()
print("=== 2. Classic solver, perfect track: miss distance (units) of a round fired at a given range ===")
print("(the hit radius is 1.0 unit; rounds live 59 steps = 472 units)")


def miss_table(label, make, comp=False):
    d = make()
    p = fly(d)
    rows = []
    for k in range(0, len(p) - 2, 3):
        pos, vel, state = p[k]
        mrange = np.linalg.norm(pos - MUZZLE)
        if mrange > 472:
            continue
        v = vel.copy()
        if comp:
            a = accel_estimate(p, k)
            t0 = mrange / S
            v = v + 0.5 * a * t0
        aim, t = classic_aim(pos, v, MUZZLE)
        if aim is None:
            continue
        miss = closest_approach(p, k, aim, MUZZLE)
        rows.append((mrange, t, state, miss))
    return rows


cases = [
    ("current, h=40, 54 m/s", lambda: Drone('current', 40, 0.9)),
    ("new, h=60, trig 40, turn 40", lambda: Drone('dive', 60, 0.9, trigger_deg=40, turn_dps=40)),
    ("new, h=90, trig 40, turn 40", lambda: Drone('dive', 90, 0.9, trigger_deg=40, turn_dps=40)),
    ("new, h=60, weave 8 deg / 4 s", lambda: Drone('dive', 60, 0.9, trigger_deg=40, turn_dps=40, weave=(8, 4))),
]
for label, make in cases:
    for comp in (False, True):
        rows = miss_table(label, make, comp)
        print(f"-- {label}{' + accel-aware track velocity' if comp else ''}")
        buckets = [(472, 350), (350, 250), (250, 150), (150, 80), (80, 0)]
        for hi, lo in buckets:
            sel = [r for r in rows if lo <= r[0] < hi]
            if not sel:
                continue
            for st in ('cruise', 'terminal'):
                s2 = [r for r in sel if r[2] == st]
                if not s2:
                    continue
                ms = np.array([r[3] for r in s2])
                tof = np.mean([r[1] for r in s2])
                print(f"   range {lo:3d}-{hi:3d} {st:8s} TOF {tof:5.1f} steps: miss mean {ms.mean():5.2f} max {ms.max():5.2f}  (n={len(s2)})")

# ---------------- 3. Monte Carlo hit probability ----------------
print()
print("=== 3. Monte Carlo P(hit) per round with radar noise + spread, by range from the muzzle ===")


class Track:
    def __init__(self):
        self.pe = np.zeros(3); self.pt = np.zeros(3); self.ve = np.zeros(3); self.vt = np.zeros(3); self.re = 0

    def rv(self, mag):
        v = np.array([rng.uniform(-1, 1) * mag, rng.uniform(-1, 1) * mag * 0.45, rng.uniform(-1, 1) * mag])
        n = np.linalg.norm(v)
        return v if n <= mag else v / n * mag

    def step(self, pos, vel):
        self.re -= 1
        if self.re <= 0:
            self.pt = self.rv(0.3 + np.linalg.norm(pos) * 0.00375)
            self.vt = self.rv(np.linalg.norm(vel) * 0.04)
            self.re = rng.uniform(6, 18)
        self.pe += (self.pt - self.pe) * 0.08
        self.ve += (self.vt - self.ve) * 0.08
        return pos + self.pe, vel + self.ve


def spread(aim):
    # small random rotation about two axes perpendicular to aim
    up = np.array([0, 1, 0])
    s = np.cross(aim, up); s /= np.linalg.norm(s)
    u = np.cross(s, aim)
    a1, a2 = rng.uniform(-0.00625, 0.00625, 2)
    d = aim + s * a1 + u * a2
    return d / np.linalg.norm(d)


def mc(label, make, comp=False, runs=12):
    buckets = [(472, 350), (350, 250), (250, 150), (150, 80), (80, 0)]
    hits = {b: [0, 0] for b in buckets}
    phase_hits = {'cruise': [0, 0], 'terminal': [0, 0]}
    for r in range(runs):
        d = make(r)
        p = fly(d)
        tr = Track()
        for k in range(len(p) - 2):
            pos, vel, st = p[k]
            tp, tv = tr.step(pos, vel)
            mrange = np.linalg.norm(pos - MUZZLE)
            if mrange > 472:
                continue
            if comp:
                a = accel_estimate(p, k)
                tv = tv + 0.5 * a * (mrange / S)
            aim, t = classic_aim(tp, tv, MUZZLE)
            if aim is None:
                continue
            hit = closest_approach(p, k, spread(aim), MUZZLE) < 1.0
            for b in buckets:
                if b[1] <= mrange < b[0]:
                    hits[b][0] += hit; hits[b][1] += 1
            phase_hits[st][0] += hit; phase_hits[st][1] += 1
    cells = "  ".join(f"{lo}-{hi}: {h / n:4.2f}" if n else f"{lo}-{hi}: --  " for (hi, lo), (h, n) in hits.items())
    ph = "  ".join(f"{k} {v[0] / v[1]:.2f} (n={v[1]})" for k, v in phase_hits.items() if v[1])
    print(f"-- {label}{' + accel comp' if comp else ''}\n   {cells}\n   by phase: {ph}")


hr = np.random.default_rng(7)
mc("current, h U(20,60), 54 m/s", lambda r: Drone('current', 20 + 40 * hr.random(), 0.9, angle=hr.random() * 6.28))
for comp in (False, True):
    mc("new, h U(30,90), trig 40, turn 40", lambda r: Drone('dive', 30 + 60 * hr.random(), 0.9, angle=hr.random() * 6.28, trigger_deg=40), comp)
    mc("new + weave 8 deg/4 s", lambda r: Drone('dive', 30 + 60 * hr.random(), 0.9, angle=hr.random() * 6.28, trigger_deg=40, weave=(8, 4), phase=hr.random() * 6.28), comp)
mc("current, wave 10 (78 m/s)", lambda r: Drone('current', 20 + 40 * hr.random(), 1.3, angle=hr.random() * 6.28))
mc("new, wave 10 (78 m/s)", lambda r: Drone('dive', 30 + 60 * hr.random(), 1.3, angle=hr.random() * 6.28, trigger_deg=40))
