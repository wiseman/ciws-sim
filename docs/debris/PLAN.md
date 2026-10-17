# Explosion momentum: what the code does now, and a plan to add it

Line numbers are from `index.html` as of 2026-10-16. A snapshot is in this folder
(`index.snapshot.html`); it matched the live file when this was written, but another workstream
is editing the file.

## 1. What the code does now

**Short answer: nothing in an explosion inherits the threat's motion.** Every kill, hit, impact
and flak burst blooms symmetrically about a fixed point in the world.

### The API carries no velocity
- `createExplosion(position, kind)` (6325) takes only a position. It clones it, calls
  `AudioController.playExplosion(pos, kind, { water })` (1963) and dispatches to
  `spawnAirburst(pos)` (6196), `spawnImpact(pos, water)` (6241), `spawnFlak(pos)` (6311) or
  `spawnHit(pos)` (6298).
- `spawnAirburst`'s `scale` argument is always 1, because `createExplosion` never passes one.

### Call sites (all in `updateLogic`, 7170)
| line | event | kind | velocity available there (units/step) |
|---|---|---|---|
| 7233 | threat reaches its target (our ship or a friendly) | `impact` | `m.velocity` |
| 7375 | a round self-destructs at the end of its life | `flak` | `p.velocity` (about 8 u/step) |
| 7407 | a round hits a threat (every hit, including the killing one) | `hit` | `m.velocity` (and `p.velocity`) |
| 7417 | the threat's health reaches 0 | `airburst` | `m.velocity` |
| 4047 / 4062 | debug `wreckFriendly` / `hitOwnShip` | `impact` | none (stationary) |

A kill fires both `hit` and `airburst` at the same `mPos` in the same frame. All three threat
types (drone, mortar, ASCM) use the same `airburst`; there's no per-type kill effect.

### Each element starts with only its own radial velocity
- **Airburst (6196):** a flash, a shock ring and a light at `pos`; a core puff with no `vel`;
  10 fireball puffs at `randomDirection() * rand(6,15)`; 4 dark smoke puffs at 2–5 m/s (delayed
  0.2–0.4 s); 6 debris at 18–32 m/s with an upward bias (`dir.y = |y|*0.8+0.2`); and 34 sparks
  at 25–65 m/s in all directions.
- **Impact (6241):** fireball puffs biased upward, a rising smoke column, a water column on open
  water, 8 debris and 40 sparks in the upper hemisphere. All of it is centred on `pos`.
- **Hit (6298)** and **Flak (6311):** a small puff and a few sparks, also symmetric.

### How each element moves (`updateExplosionFX`, 6745, run on sim seconds)
- **Puffs** (`initPuff` 6051, `stepPuff` 6073, `spawnPuff` 6085): `vel *= exp(-drag·dt)`, plus
  buoyancy, gravity and wind. Drag is 3 for the airburst fireball, 1.5 for its dark smoke and 2.5
  for the impact. Delayed puffs appear where they were spawned.
- **Debris** (`makeDebris` 6001, `spawnDebris` 6139, loop 6782–6803): `vel.y -= FX_GRAVITY·dt`
  (22 u/s², 5574) and `vel *= exp(-0.4·dt)`, plus spin. A piece is removed when `age >= life`
  (it pops out of existence in mid-air) or when `y < WATER_LEVEL` (-1.5, 3046), which spawns one
  small white splash puff (6792–6798). Nothing checks for our ship or the friendlies, so debris
  passes through hulls.
- **Debris smoke ribbons** (`spawnTrail` 6156, trail loop 6806–6834): there are up to
  `TRAIL_MAX_POINTS` = 40 points, and a new one is dropped once the head moves `spacing` away
  (`max(0.35, trailWidth·1.2)`, about 0.42 m). A full ring drops its oldest point.
- **Sparks** (`spawnSpark` 6134, loop 6835–6857): `vel *= exp(-1.5·dt)` and gravity at 0.6×.
  Each streak is oriented along its own `vel` (`setFromUnitVectors(_zAxis, vel)`).
- **Flash, ring and light** are static billboards and a point light.
- **Shake:** `addShake(pos, …)` (6185) depends on the distance from the burst to the camera. It
  decays on real time (6867).
- **Audio:** one positioned one-shot at `pos`, delayed by the speed of sound. Nothing about it
  depends on motion.

### Units
- Threat and round velocities are in **units per sim step**. `SIM_STEPS_PER_SECOND` = 60 (619),
  and 1 unit is about 1 m.
- `animate` (7580) computes `simSteps = realDt·60·timeScale` (7592). FX run on
  `simSteps / SIM_STEPS_PER_SECOND` (7606), which is sim seconds, so slow motion
  (`timeScale` = 0.1, `toggleSlowMo` 7476) slows the explosions too. FX velocities are in u/s.
- **Per-step × 60 = per second.** Never divide by `timeScale` or use `realDt` for this.

### How fast the threats are (`THREAT_TYPES` 5347, `spawnMissile` 5486, `steerSeaSkimmer` 5436)
- **Drone:** a constant `(0.8 + 0.05·wave)` u/step, which is **48 m/s at wave 1, 78 m/s at wave
  10 and 108 m/s at wave 20**. It flies straight at its target. Drones are slower than 155 m/s.
- **Mortar:** a 45° ballistic arc. It launches at about `sqrt(0.02·900)` ≈ 4.2 u/step
  (**~250 m/s**), slows to ~3 u/step (~180 m/s, horizontal) at the apex, and comes back down at
  ~250 m/s and 45°. `GRAVITY` is 0.02 u/step² and is applied after the move (7212).
- **ASCM:** `2.6 + 0.03·wave` u/step (**~158–170 m/s**). It is re-steered every step, flat at
  y ≈ 1.8 and then levelling at the target's height.
- **Round:** 8 u/step (480 m/s).

### Measured (`momentum_probe.py`, outputs `ascm-data.json` and `ascm-strip.png`)
The probe killed an ASCM flying at 159.6 m/s exactly as the game does: `createExplosion(pos,
'airburst')`, then dispose. It then tracked the centroids of the new debris, puffs and sparks
along the flight direction:

| t (s) | missile would be at | debris centroid | puff centroid | spark centroid |
|---|---|---|---|---|
| 0.21 | +33.6 m | −1.2 m | −0.5 m | −0.7 m |
| 0.51 | +81.4 m | −2.6 m | −0.5 m | −0.6 m |
| 1.01 | +161 m | −4.5 m | −0.6 m | — |

Everything stays within a few metres of the burst point. In the strip, the red cross (where the
missile would have been) leaves the frame by 0.5 s, and the fireball stays on the blue cross (the
burst point).

### Effects on the other cases
- **Hit without a kill:** the threat flies on at 50–250 m/s, but the hit's puff and sparks stay
  where the round struck. A 3-hit ASCM leaves stationary hit puffs strung out behind it, which
  reads as "left behind" (plausible for smoke, wrong for sparks).
- **Impact on our ship or a friendly (7233):** the threat's momentum goes into the target. The
  stationary fireball is roughly right, but a steep mortar or a fast ASCM would also push the
  fireball and debris forward along the hull or across the water.
- **Missile-follow cam (7543–7575):** it sits 8 units behind the target on the far side from the
  Phalanx, looking at the Phalanx. `target` is picked before the projectile loop (7261), so the
  camera stays on the dead threat's last position for the kill frame. Next frame it lerps at
  0.2/frame to the next target, or to the default view. It barely sees the explosion today.

## 2. Plan

### 2.1 The physical case for this
Real mid-air intercepts don't burst symmetrically from a fixed point. Kinetic and fragmentation
intercepts (Phalanx and Goalkeeper footage, Iron Dome and Patriot intercepts, drone shoot-downs)
look like this:

- The **debris cloud keeps going along the trajectory** as a forward-raked spray. Dense fragments
  have a high ballistic coefficient and lose only a small fraction of 150+ m/s in the first
  second. That's why CIWS doctrine worries about "leakers": a missile killed close in can still
  throw its wreckage into the ship.
- The **fireball and smoke** are low-density gas. They're carried forward briefly, then stop
  within metres and hang. The cloud ends up elongated along the path.
- **Sparks and burning fragments** form a cone opening forward, not a sphere.
- **The blast shock** propagates in still air, so the shock ring and flash belong to the air
  frame and don't move with the threat.

The anime cel look already exaggerates. A forward-raked spray with smoke ribbons streaming ahead
of a hanging, cooling fireball is a stronger silhouette than a symmetric ball, and it's the
classic anime missile kill: a burst with streamers flung forward.

### 2.2 API change
```
createExplosion(position, kind, velocity = null)
```
- `velocity` is the destroyed object's velocity **in units per sim step**, the same units as
  `m.velocity` and `p.velocity`. Every call site has one in exactly those units, so the
  conversion happens once, inside: `_explosionCarry.copy(velocity).multiplyScalar(SIM_STEPS_PER_SECOND)`.
  That gives u/s, the FX units. Copy into a module-level temp; the threat's own vector is mutated
  and disposed.
- `null` (the debug hooks, `explosion_shot.py`, `wreckFriendly`, `hitOwnShip`) means zero, so
  the current look is unchanged.
- Pass the carry (u/s) down: `spawnAirburst(pos, scale, carry)`, `spawnImpact(pos, onWater,
  carry)`, `spawnHit(pos, carry)` and `spawnFlak(pos, carry)`.
- Leave `AudioController.playExplosion` alone. The sound is emitted at the burst instant, so a
  fixed source is correct.

### 2.3 Call sites
| line | change |
|---|---|
| 7417 `airburst` | `createExplosion(mPos, 'airburst', m.velocity)`: **the main one** |
| 7407 `hit` | `createExplosion(mPos, 'hit', m.velocity)` (the round's velocity stays out; see below) |
| 7233 `impact` | `createExplosion(m.mesh.position, 'impact', m.velocity)`, handled specially in 2.4 |
| 7375 `flak` | optional and low priority: `p.velocity`, sparks only (see 2.4) |
| 4047 / 4062 debug | unchanged (no velocity) |

### 2.4 How much each element inherits

`f` is the fraction of the carry added at spawn. `k` is the decay rate of the inherited part
(1/s). `cap` limits the inherited speed so that mortars (~250 m/s) and late-wave threats don't
go wild. The stopping distance is `D = min(f·V, cap) / k`, and the distance covered by time `t`
is `D·(1 − e^(−k·t))`.

**Airburst (kill):**
| element | f | cap (m/s) | decay | ASCM at 160 m/s: D / at 1 s | drone at 50 m/s: D |
|---|---|---|---|---|---|
| debris | 0.70 | 110 | separate `carry` vector, k = 1.2 | 92 m / 64 m | 29 m |
| sparks | 0.45 | 70 | added to `vel`, existing drag 1.5 | 47 m / ~25 m over their 0.25–0.7 s life | 15 m |
| core puff and 10 fireball puffs | 0.25 / 0.20 | 40 | added to `vel`, existing drag 3 | 13 m / 10 m | 4 m |
| 4 dark smoke puffs | 0.08 | 15 | added to `vel`, existing drag 1.5 | 8 m | 3 m |
| flash, shock ring, point light | 0 | — | — | 0 | 0 |

**Hit (no kill):**
| element | f | cap (m/s) | decay | notes |
|---|---|---|---|---|
| sparks | 0.6 | 90 | existing drag | fragments knocked off a moving target; they briefly ride with it |
| puff | 0.3 | 40 | existing drag 3 | drifts a few metres, then is left behind the threat |
| flash | 0 | — | — | a static flash for 0.09 s is fine |

**Impact (the threat reaches its target):** most of the momentum goes into the hull.
- Use **only the horizontal component** of the carry, and never push anything downward into the
  deck or water.
- Fireball puffs get f = 0.12, cap 25, which makes the fireball skid a few metres along the line
  of travel.
- Debris and sparks get f = 0.25 horizontal, cap 40, so some wreckage carries on across or over
  the hull.
- The smoke column, water column, foam ring and flash get 0.

**Flak (optional):**
- The puff gets 0, because real flak puffs hang.
- Sparks get f = 0.1, cap 50 (the round is at 480 m/s).
- This is the least important case, and up to 60 bursts/s happen far out. Do it last or not at
  all.

How to apply it, element by element:
- **Debris:** add `carry: new THREE.Vector3()` in `makeDebris`, and set it in `spawnDebris`
  (a new `carry` option). In the loop, keep `vel` exactly as now, so the radial spray looks
  identical in the threat's frame. Then add `carry *= exp(−k·dt)` and
  `pos += (vel + carry)·dt`.
  - Reason: putting it into `vel` would leave it under the existing 0.4 drag, giving D ≈ 270 m,
    which is off screen. Raising that drag would kill the radial pop.
- **Sparks:** add `f·carry` to the velocity passed to `spawnSpark`. Because the streak is drawn
  along `vel`, the spray rakes forward automatically into a cone. That's the look we want, with
  no new field and no loop change.
- **Puffs:** add `f·carry` to the `vel` option. `stepPuff`'s existing drag is already "a little,
  decaying quickly", so `initPuff` and `stepPuff` don't change.
  - **Delayed puffs:** the fireball puffs are staggered by `i·0.012` s and the dark smoke by
    0.2–0.4 s. Spawn them where the carried cloud will be when they appear: offset the spawn
    position by `c·(1 − e^(−k·delay))/k`, and give them velocity `c·e^(−k·delay)`, where
    `k = drag` and `c` is the capped carry. Otherwise the dark smoke pops in behind a fireball
    that has already moved 5–8 m.
- **Billboards and light:** unchanged.

### 2.5 Keeping it on screen (drag)
- The debris carry gets its own k = 1.2/s. A 160 m/s ASCM kill throws debris about 64 m
  downrange in 1 s, at most ~92 m, and within their 1.2–2.0 s life. The fireball moves about
  10–13 m. The CIWS kills at ~100–470 m, and the default camera is near the mount (-15, 12.5,
  -15), so the cloud stays in view.
- The `cap` values stop mortars and fast late waves from throwing debris 150 m.
- Leave the tunables as constants beside `FX_GRAVITY` (5574), for example
  `FX_CARRY = { debris: { f, cap, k }, spark: …, fireball: …, smoke: … }`, so they can be tuned
  from frame strips.
- **Trails** need one change. At 100 m/s, 40 points at a 0.42 m spacing cover only about 17 m,
  so the ribbon is short and the oldest points are recycled at once. Set
  `spacing = max(current, carrySpeed · trailLife / TRAIL_MAX_POINTS · 0.6)`, which is about
  2.5 m at 108 m/s, so a ribbon spans most of the throw. Point count and allocation are
  unchanged. The ribbons from the hanging fireball to the forward-flung pieces are what sell the
  momentum.

### 2.6 Cameras
- **Orbit (default) and Phalanx cam:** threats head for our ship or the friendlies, so the
  forward spray usually comes toward the camera. That's dramatic, and correct, as "debris still
  coming at us".
  - Check that a close kill (<80 m) doesn't fill the frame with near-camera debris.
  - The camera near plane is 0.25. Ribbons have `frustumCulled = false`, and so do puffs'
    outlines.
- **Shake:** `addShake(pos, …)` stays at the burst point, which is fine. A later option is a
  small extra shake when debris splashes within ~40 m of the camera.
- **Missile-follow cam:** it looks from behind the threat toward the Phalanx, so the carried
  cloud moves away from the camera and into the centre of the frame. That reads well, but the
  camera leaves after one frame (7261, 7573).
  - Optional follow-up, separate from this change: keep a `lastKill = { pos, carry, until }`.
    While `elapsedTime < until` (~0.6 sim s), aim the missile cam at the moving fireball centroid
    (`pos + carry·0.2·(1−e^(−3t))/3`) before lerping on to the next target.
  - The 0.2/frame lerp is per display frame, not per sim step, so in slow motion it would catch
    up too fast. If the linger is added, scale it by `timeScale`.

### 2.7 Slow motion
- Everything above runs on `dt = simSteps / SIM_STEPS_PER_SECOND` (sim seconds). Carry, decay
  and drag therefore scale with `timeScale` automatically, and the trajectories are identical in
  sim time at 1.0 and 0.1.
- The single conversion is per-step × `SIM_STEPS_PER_SECOND`. Using `timeScale` or `realDt`
  there would double-apply slow motion.
- At 0.1×, the trail gets about 10× more frames per metre, but spacing still controls the point
  count, so nothing changes.

### 2.8 Splashes and debris landing downrange
- Sea-skimmer kills happen at y ≈ 1.8–10, only 3–12 m above the water. About half the debris
  already lands within its life, so with carry the splashes now land **60–90 m downrange, toward
  the ship**: a line of white splashes running at the target. That's a strong, realistic read.
- Upgrade the landing splash (6792) when the piece's horizontal speed is above ~20 m/s:
  - one extra low puff a few metres further along the travel direction, for a skip;
  - optionally a small `spawnFoamRing(x, z, 3, 0.6)`.
  - It stays cheap: at most 8 debris per kill.
- **Hull contact (new):** with carry, debris from close kills can reach our ship and the
  friendlies, and today it passes through the hulls.
  - In the debris loop, when `nearShip(pos)` and `pos.y < deckHeightAt(pos.z) + 0.5`, or
    `overFriendly(pos)` and `pos.y < ~6`, end the piece. Spawn 4–6 sparks and a small lowDetail
    dark puff (a "clang"), and release its trail head.
  - Cosmetic only, with no damage. A "debris strike" callout could come later.
- **Pop-out:** debris that reaches `life` in mid-air vanishes, and with carry it vanishes
  further downrange, where it's easier to see.
  - Optional: shrink `scale` over the last 0.15 s of life.
  - Or extend life (up to +1 s) for pieces still within ~15 m of the water, so they reach the
    surface.
- **Impact on water:** the water column, foam ring and splash sound stay where they are.
  Horizontal carry applies only to the fireball, debris and sparks.

### 2.9 Performance
- No new draw calls, pools or per-frame allocations:
  - one `Vector3` per pooled debris piece (`carry`);
  - one module-level temp for the carry in `createExplosion`.
- Fix the existing allocations on the paths you touch (`pos.clone()`, `dir.clone()`, `new
  THREE.Vector3()` per puff and spark) only if it's convenient. They're per explosion, not per
  frame.
- The debris loop gains one `multiplyScalar` and one `addScaledVector` per piece.
- Trails keep 40 points, and a wider spacing means fewer updates per second.
- Hull checks use `nearShip` (an AABB). `overFriendly` loops over 5 friendlies with a rotate, and
  runs only for debris below ~6 m: negligible.
- Extra splashes add at most +8 lowDetail puffs per kill. Watch `fxPuffs` in a high-wave soak
  (`tools/soak.py`).

### 2.10 Verification with frame strips
1. **Quantitative probe:** `momentum_probe.py` in this folder. Rerun it after the change, with
   the probe passing `m.velocity` as the third argument. In the ASCM case (160 m/s), expect:
   - debris centroid along track ≈ **+60 m at 1 s** (now −4.5);
   - puff centroid ≈ **+10–13 m** and levelling off by ~1 s;
   - sparks ≈ +20–25 m;
   - flash and ring at 0.

   Add a drone case (built through `addThreat` or a new debug hook such as
   `debug.spawnThreat(type)`, at 50 m/s) and a descending mortar (~250 m/s, capped), and check
   that the caps hold.
2. **Abeam strip** (`ascm-strip.png` style; red cross for the extrapolated missile, blue for the
   burst point): the spray should rake toward the red cross, the ribbons should stream forward,
   and the fireball should elongate and hang a little ahead of blue.
3. **Down-the-path strip:** a camera behind the threat looking along `v`, or the actual
   missile-follow cam (`toggleCameraFollow` twice). The cloud should move away into the frame,
   and nothing should go off screen within 1 s.
4. **Phalanx cam strip** (`frame_strip.py gun`-style render hook): a kill at 100–150 m. Debris
   should come toward the gun, and the near-camera framing should be acceptable.
5. **Slow motion:** repeat 1 with `debug.setTimeScale(0.1)`. Centroid against *sim* time should
   match the 1.0 run.
6. **Splashes and hull:** kill a sea-skimmer at ~120 m (`scene_shot.py engage` setup). Splashes
   should form a line toward the ship, and any piece reaching the hull should end in a clang,
   not pass through.
7. **Regression:** `uv run tools/explosion_shot.py <out> airburst|water|deck|flak` passes no
   velocity, so the output must look the same as before.
   - Add an `airburst-moving` scenario that passes `new V(2.6, 0, 0)` (per step) to keep the new
     look under test.
   - Run with `console_levels=("error","warning")` and check there are no errors.

## 3. Order of work
1. The `velocity` parameter, conversion and plumbing, plus debris `carry` and spark/puff
   inheritance for **airburst**. That's the visible win.
2. Hit inheritance.
3. Trail spacing.
4. Debris hull contact and the upgraded splash.
5. Impact (horizontal-only).
6. Optional: flak sparks, the missile-cam linger and the debris fade-out.
