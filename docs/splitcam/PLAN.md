# Plan: an in-game split-screen camera mode

This is a plan only. No repo files were changed. Everything named `splitcam/…` below is in
`/private/tmp/claude-501/-Users-wiseman-src-ciws-sim/3198b73f-d85d-4071-9cf0-328b4d244fe2/scratchpad/splitcam/`.
Another workstream is editing `index.html` at the same time. Line numbers drift (they moved by about 17 lines while
this plan was being written), so the plan names functions and symbols instead of line numbers.

## 0. Summary and recommendations

- **What it shows.** On a landscape screen the **gunsight is on the left and a chase camera on the threat is on the
  right**, split by a 3 px dark divider. This is the `demo_video.py` look. On a portrait screen (window aspect below
  about 1.0) the panes **stack**: the chase camera on top and the gunsight below. Picture-in-picture is an optional
  later layout. A 3-up layout is not recommended (section 1).
- **Which threat the chase camera follows.** It locks onto a threat and stays on it. It starts on the gun's
  current `target`, with a hysteresis rule so it doesn't flicker when two ETAs are close. A vampire always takes the
  chase camera. After a kill (or an impact) the camera **holds for a beat and pulls back**. The demo's hold, 9 m
  behind the missile, leaves the camera inside the fireball (`splitcam/shots/side-afterkill-0.60.png`). After the
  hold it **cuts** to the next track instead of swooping across the sky. With nothing inbound it shows a slow, wide
  "NO TRACK" view of the formation.
- **How you get in.** The camera button gets a fourth step: OFF → PHALANX → MISSILE → **SPLIT** → OFF. Hotkeys: **C**
  cycles the modes and **V** toggles split straight on and off. Each pane gets a small label next to the divider at
  the top: `GUNSIGHT` and `TRACK · VAMPIRE 090 → CORDELL · 1.2 km`.
- **Rendering.**
  - **The main `camera` becomes the gunsight** in split mode. The listener, smoke-ribbon orientation and shake
    falloff all read `camera`, so they keep working unchanged.
  - A second `PerspectiveCamera` is the chase camera.
  - Each pane is drawn with scissor and viewport in CSS pixels. Three.js applies the pixel ratio itself.
  - Per pane: the sky dome and the outline thickness are set, and the shadow map is rendered once per frame.
- **Cost (measured, section 4.7).** A side-by-side split has the same pixel count as one full view, so fill cost
  barely changes. The cost is CPU and draw calls: **609 against 298 calls per frame**, and **1.85 against 1.16 ms**
  of CPU in `renderer.render`. Everything held 60 fps at 3200×1800 on this Mac. Rendering the shadow pass only once
  saves about 10% of the second pane's calls.
- **Code.** About 250 lines in a new `// --- SPLIT VIEW ---` section next to `updateCameraFollow`. It only reads game
  state (`target`, `missiles`, `friendlies`). Outside that section, the changes are:
  - one branch in `animate`
  - one in `toggleCameraFollow` and one in `updateCameraFollow`
  - a hotkey in `handleGlobalHotkeys`
  - `shoot()`'s shake condition
  - `addShake`, for a second shake receiver
  - a `__ciws` hook

  The fire control is untouched. The PHALANX mode's habit of shaking the turret itself is not copied (section 4.5).
- **`demo_video.py`** can drop its monkey-patched `renderer.render` (about 45 lines). It would call
  `__ciws.setCameraMode('split')` and pin the vampire with `__ciws.debug.setChaseTrack(m)`. **This needs a fix
  either way:** the demo's `% 3` camera-mode shim goes out of step as soon as there are four modes (section 6.5).

---

## 1. Design: what the split screen shows

### Reference captures (current game, demo split logic re-run by `splitcam/probe.py`)

| File | What it shows |
|---|---|
| `splitcam/shots/side-01.79-r853.png` | Side-by-side at 1600×900 @2x. The gunsight (left) is firing, and the chase camera (right) is 9 m behind a vampire at 850 m, looking at the ship. |
| `splitcam/shots/side-03.56-r555.png` | The same at 555 m. The muzzle flash and shock ring cover the bore line in the gunsight. The HUD stats and controls sit in the outer top corners, so the inner corners next to the divider are free. |
| `splitcam/shots/side-afterkill-0.15/0.60/1.20.png` | The demo's "hold the last pose": **the camera is engulfed by the kill fireball** and the pane is solid orange. |
| `splitcam/shots/pip.png` | A picture-in-picture mock-up: the full gunsight with a 34%-width chase inset. The inset overlaps the radar, so it needs placing with care. |
| `splitcam/shots/portrait-pair.png` | 430×932: stacked on the left (works), side-by-side on the right (each pane 0.23 aspect, unusable). |
| `splitcam/shots/sights-*.png` | A 3-up comparing gunsight poses: the demo's sight on the gun block (fov 45), a raised sight (fov 32), and an over-the-shoulder pose (fov 60). |

The `#center-reticle` dashed circle lands on the divider in the side layout (visible in every side capture), so it
has to move or hide.

### Layouts

| Layout | When | Panes | Verdict |
|---|---|---|---|
| **side** | window aspect ≥ 1.0 | gunsight on the left, chase on the right, 3 px divider | **Default.** Proven in the demo. Each pane is about 0.89 aspect at 16:9. |
| **stack** | window aspect < 1.0 (phones, portrait tablets) | chase on top, gunsight below | **Default on portrait.** The threat "comes down" to the gun. The gun sits in the thumb zone. |
| pip | opt-in (V cycles side → pip → off?) | full gunsight, chase inset at about 34% width | Optional, phase 3. Costs about 12% extra pixels. Place it above or left of the radar, below the controls column. |
| 3-up (overview + two) | — | — | **Not recommended.** 859 calls per frame, and the panes are 0.59 aspect on 16:9 (`sights-*.png` shows how narrow). If it's ever wanted, do it as one wide overview on top with two small panes below, as a "director" layout. |

Auto layout uses hysteresis: switch to stack below 0.95 and back to side above 1.05, so dragging a window edge
doesn't make it flip back and forth.

**Gunsight pose.** Keep the demo's sight: `SIGHT_EYE (0, 0.95, 0.6)` and `SIGHT_AHEAD (0, 0.95, 200)` in the gun
block's frame (the block doesn't spin), with fov 45. The 3-up comparison shows that the raised sight loses the gun
entirely and reads as an empty seascape, and the over-the-shoulder pose shows mostly the mount's side. The demo sight
has one problem: during long bursts the star and ring billboards cover the bore line (section 4.6 has the options).
Do **not** reuse mode 1's over-the-shoulder pose. Mode 1 stays a separate mode.

**Chase pose.** Each threat type gets its own offset. It is computed from the threat's position, and it **looks at
what the threat is aimed at** (`m.targetInfo.position`), not always at our ship. A vampire aimed at Cordell then
shows Cordell growing in the frame.

| Type | Behind | Up | fov | Note |
|---|---|---|---|---|
| ascm | 9 | 2.6 | 60 | The demo's values, which look good (`side-01.79`) |
| drone | 6 | 1.5 | 60 | Smaller and slower |
| mortar | 10 along −velocity | +3 | 55 | Ballistic, so "behind" means along its own path, not horizontal from the ship. That avoids the demo's `setY(0).normalize()` breaking down when a shell is nearly overhead. |

---

## 2. Targets: how the chase pane picks and switches

The state lives in `splitView.track`, one of:
- `{ m, since }` while following a threat
- `{ hold: pose, until, kind }` after a kill or impact
- `null` when idle

1. **Lock.** Once the camera locks onto a threat it stays on it while that threat lives. Only these break the lock:
   - **A vampire.** A newly detected ASCM (`onVampireDetected`, or any `m.type === 'ascm'`) takes the chase camera
     unless one is already being followed. It cuts straight away: vampires are the show.
   - **A long disagreement.** The gun's `target` has been a different threat for **1.0 s of real time** without a
     break, and the locked threat isn't an ASCM. Then the camera switches to the gun's target. The gun's `target`
     is re-picked every step by ETA, with ties broken toward friendlies, so it can flip between near-equal ETAs. The
     1 s debounce stops the pane from flickering.
2. **Death.** When the locked threat leaves `missiles`:
   - Killed by the gun: it was in `missiles` last frame and there is a kill explosion near its last position. In
     practice, if it isn't removed by the impact branch, treat it as a kill. A small read-only hook is cleaner: have
     the split section keep `lastSeen = {pos, vel}` every frame and decide kill or impact by whether it reached
     within 6 m of `targetInfo.position`.
   - Either way: **hold.** Freeze the look-at point at the last position. Ease the camera **backwards along its
     line to about 28 m in 0.35 s**, so the fireball fills about a third of the frame instead of all of it. Hold for
     `max(1.2 s, soundDelay + 0.3 s)` of real time. `soundDelay` is the distance from the listener to the kill
     divided by `SPEED_OF_SOUND`, so the hold ends just after the boom reaches the gun. A kill at 500 m is about
     1.5 s. That ties picture and sound together.
   - Label: `SPLASH · VAMPIRE 090`, or `IMPACT · CORDELL` for one that gets through.
3. **After the hold.** **Cut** to the next track, using the gun's current `target` and then the nearest threat, and
   flash the label. No lerp: the current mode 2's `camera.position.lerp(camPos, 0.2)` turns a target change into a
   kilometre-long swoop, and its smoothing depends on the frame rate.
4. **Nothing inbound.** Show a slow, wide **"NO TRACK"** shot. Use a low three-quarter view of our ship and the
   formation from about 60 m out. Turn it about 2°/s in real time, centred on the bearing of the last threat. Cut
   back as soon as a threat is detected. This takes the place of mode 2's snap to `(20, MOUNT_Y+20, 20)`.
5. **Smoothing.** While following, the camera's position is rigid to the threat (no lag). It reads well and is
   stable in slow motion. Only the look-at point is smoothed, exponentially by real dt
   (`1 - exp(-dt / 0.12)`), so the view doesn't jerk when a sea-skimmer jinks.

Debug hook: `__ciws.debug.setChaseTrack(m | null)` pins a track (for the demo and tests). `null` returns to the
automatic choice.

---

## 3. UI

- **Entering.**
  - `toggleCameraFollow` cycles `(cameraMode + 1) % 4`. Add a `CAMERA_MODES = ['OFF', 'PHALANX', 'MISSILE', 'SPLIT']`
    table so the label, the button's `active` class and `controls.enabled` come from one place.
  - `handleGlobalHotkeys`: **C** cycles and **V** toggles split, returning to the previous mode. Only `a` and `m`
    are taken today.
  - `enterSplitView()` and `exitSplitView()` run on the transitions in and out of mode 3.
- **Button text.** `#follow-status` reads `SPLIT`. Consider renaming the button "CAMERA" now that it has four
  states.
- **Pane labels.** Add an HTML overlay `#split-labels`, inside `#hud` with `pointer-events: none`, holding two chips
  styled like `.toggle-btn` but smaller. They are positioned from the pane rectangles every frame (only when they
  change):
  - side: at the top, against the divider (left pane: top-right corner; right pane: top-left corner). Those
    corners are free in every capture. The stats panel and the controls column take the outer corners.
  - stack: left edge, just above and below the horizontal divider.
  - pip: along the inset's top edge.
  - Text: `GUNSIGHT` with `· FIRING` while `isFiring` is set. `TRACK · VAMPIRE 090 → CORDELL · 1.2 km`. The type
    names are VAMPIRE, DRONE and SHELL. The bearing comes from `bearingFromShip`, with three digits as the callouts
    use. The range is to our ship. The target's name comes from `friendlies.find(f => f.id === …).name`, or `OWN
    SHIP`. The chip also shows `SPLASH …`, `IMPACT …` and `NO TRACK`.
  - Update the text at about 10 Hz, not every frame.
- **`#center-reticle`.** Move it to the gunsight pane's centre, which is the bore line, because the sight looks down
  the barrels. Hide it in the PiP inset.
- **Optional (phase 3).** A projected bracket around the tracked threat in the gunsight pane. At 600 m a vampire is a
  few pixels across (`sights-1-r647.png`), and the bracket links the two panes visually. Draw it as an HTML element
  positioned from `track.position.project(camera)`.
- **Phone.** In stack mode the existing HUD already covers much of the top pane (`portrait-pair.png`). That is an
  existing small-screen problem and out of scope, but worth noting.

---

## 4. Rendering

### 4.1 Cameras and aspect

- In split mode the **main `camera` is the gunsight**. `enterSplitView` saves `camera.fov` and sets it to 45, and
  `exitSplitView` restores 60. Both call `updateProjectionMatrix` and restore `aspect` from the window, so
  `onWindowResize` stays valid.
- `splitView.chase = new THREE.PerspectiveCamera(60, 1, 0.25, 4000)` is made once.
- Before each pane is drawn, set its `aspect = rect.w / rect.h`. If a pane is narrow, widen the vertical fov so the
  horizontal fov stays at least about 40°: `vfov = max(base, 2·atan(tan(hfovMin/2) / aspect))`. Clamp it to 75°.

### 4.2 Scissor, viewport and pixel ratio

- `renderer.setViewport` and `setScissor` take **CSS pixels** and three multiplies them by the renderer's pixel
  ratio (capped at 2 by `setPixelRatio(min(dpr, 2))`). Work out the rectangles from `renderer.getSize()` in whole
  CSS pixels (`Math.floor`), so fractional DPRs like 1.5 don't leave one-device-pixel seams.
- WebGL's y axis points up: the stack layout's top pane has `y = half + gap`.
- Per frame:
  1. `setScissorTest(true)`, then a full-canvas `clear()` with the divider colour, which draws the 3 px divider.
     **Restore the clear colour** with `getClearColor`. The demo leaves it at `0x101418` for good.
  2. For each pane: viewport and scissor set to its rectangle, then `render`.
  3. Reset the viewport to the full canvas and `setScissorTest(false)`.
- `scene.background` clears each pane, so the clear colour only shows in the gap.
- The canvas includes the divider, so `captureStream` recordings (the demo) get the full composite. The labels are
  HTML and are not recorded, as with the rest of the HUD.

### 4.3 Sky dome per pane

`skyDome.position.copy(paneCamera.position)` before each pane, and back to `camera.position` at the end. Use the
`skyDome` variable directly. The demo finds the dome with `o.position.equals(cam.position)`, which fails on any
frame with explosion shake, because the dome is placed before the shake offset is added. It then quietly leaves the
dome at the main camera. That is harmless because the 3000-unit dome still encloses a chase camera about 1 km away,
but it is fragile.

### 4.4 Outlines and post effects

- There is no post-processing: there is no composer, and the outlines are inverted-hull geometry. Nothing to split.
- **Outline width is a uniform worked out for one camera:**
  `thickness = OUTLINE_PX · 2·tan(fov/2) / window.innerHeight` (`updateOutlineThickness`). The puff outlines
  share the same uniform object (`uOutlineWidth: outlineMaterial.uniforms.thickness`).
  - The side layout uses full-height panes, but the sight's fov is 45. With the uniform worked out for fov 60, its
    ink would be about 1.4× too thick.
  - The stack layout uses half-height panes, so the ink would be half as thick.
  - Fix: generalise to `setOutlineScale(fov, paneHeightCss)` and call it before each pane. Restore it with
    `updateOutlineThickness()` on exit. One assignment covers the hulls and the puffs.
- Fog is per camera (by distance), so it is correct in each pane automatically.

### 4.5 Camera shake per pane

- **Gun-fire shake (`cameraShake`).** Today mode 1 adds random rotation to **`turretPitch` itself**, records it in
  `lastShake`, and takes it back off at the top of the next `animate`. In split mode the chase pane would see the
  gun jitter, and it is a game-state mutation that should not spread further.
  - Split mode instead applies the rotation to the **sight camera** after it is posed: `camera.rotateX(rx)` and
    `rotateY(ry)` with the same 0.0125 rad scale and the same decay.
  - `shoot()`'s `if (cameraMode === 1)` becomes `if (cameraMode === 1 || cameraMode === CAMERA_SPLIT)`.
  - Leave mode 1 as it is. Moving it to camera-space shake is a separate, optional cleanup.
- **Explosion shake (`fxShake`).** `getExplosionShakeOffset()` stays on the gunsight. `addShake` scales falloff by
  distance to `camera`, so kills 500 m out barely shake the gunsight, which is right. The chase camera is the one
  near the fireball:
  - Give it its own accumulator, `splitView.shake`. In split mode `addShake` also adds the falloff measured from the
    chase camera.
  - It decays with the same `exp(-6·realDt)` in `updateExplosionFX`.
  - Apply it as a position offset (×0.6 of the gunsight's scale) only around the chase pane's render.
  - This is a three-line change to `addShake`, which is the one FX function the plan touches.

### 4.6 Billboards and FX that use the camera

| Effect | Camera dependence | Per pane? |
|---|---|---|
| Explosion billboards (`BILLBOARD_VERTEX`: flash, rings) | Faces the camera in the vertex shader through `modelViewMatrix` | **Correct automatically.** Three sets view matrices per render. |
| Gun FX (`GUN_FX_VERTEX`: muzzle star, jet, ring) with the `uViewRange` min/max clamp | Clamp by view depth in the shader | Automatic. In the chase pane at about 500 m the 0.01 × depth minimum makes the flash a visible about 5 m star on the ship, which is what the clamp is for. |
| Puffs, ink, water (`cameraPosition`) | Shader | Automatic |
| **Smoke ribbons (`updateTrail`)** | **CPU:** the side vector is `cross(tangent, camera.position - p)`, once per frame | **Wrong in the chase pane:** ribbons face the gunsight and can look edge-on (thin) from the chase camera. Fix in phase 3: move the side vector into `TRAIL_VERTEX` (pass the tangent as an attribute, use `cameraPosition`). That fixes every pane and takes CPU work off the main thread. Until then, accept it. |
| `addShake`, audio, whizz-by | CPU, reads `camera` | Stay on the gunsight (sections 4.5 and 5) |
| Barrel high-shutter spin, muzzle-flash visibility | Per frame, not per camera | Both panes show the same strobe frame, which is right |

**Muzzle flash in the gunsight.** During sustained fire the star and ring cover the bore line
(`side-03.56-r555.png`, `pip.png`). Options:
1. Accept it. It is dramatic, and the shutter skips 15% of flashes.
2. Lower `uViewRange.y` (the maximum size as a fraction of depth) for the star and ring only while the gunsight pane
   renders, so the flash keeps to a fraction of the frame. Set it per pane and restore it, like the outline uniform.
3. Raise the eye 0.2–0.3 so the flash sits lower in the frame.

The recommendation is (2), or (3) if (2) looks fake. This is a user decision.

### 4.7 Cost and how to keep 60 fps

All figures are measured at 1600×900 CSS × DPR 2 (3200×1800 device pixels) in headless Chromium with ANGLE/Metal on
this Mac, with 3–5 threats in flight. Sources: `splitcam/probe.py`, `splitcam/shots/perf.json` and
`splitcam/shadowcount.py`.

| View | Draw calls | Triangles | CPU in `render` (mean / p95) | CPU+GPU with `gl.finish` |
|---|---|---|---|---|
| Orbit (single) | 298 | 74k | 1.16 / 1.5 ms | 1.43 ms |
| PHALANX (single) | 322 | 74k | 1.09 / 1.6 ms | 1.16 ms |
| **Split, side** | **609** | 143k | **1.85 / 2.6 ms** | 2.12 ms |
| Split, shadow once | 607* | 147k | 2.09 / 3.1 ms | 2.06 ms |
| 3-up | 859 | — | — | — |

\* The threat count moved between samples, so this is within noise.

In one controlled single-frame comparison, the shadow pass was **28 of 277 calls and 7.4k of 68k triangles**, from 43
casters. Every variant held 60 fps; the browser caps it there.

Conclusions:
- **Fill cost is about flat.** Two half panes are the same number of pixels as one full view. "Lower resolution for
  one pane" saves little, and it needs a render target plus a blit (and MSAA on the target), so **don't do it**.
- **The real cost is about 2× draw calls and scene traversal.** Each `renderer.render` repeats
  `scene.updateMatrixWorld`, frustum culling, sorting and uniform uploads. Cheap wins:
  - **Shadow map once per frame.** Set `renderer.shadowMap.autoUpdate = false` while in split, and
    `needsUpdate = true` before the first pane. The directional light's shadow camera is fixed (±62 around
    (0, 0, 14)) and doesn't depend on the view camera, so this is safe. It saves about 28 calls per frame.
  - **Matrix update once.** Call `scene.updateMatrixWorld()` once, then set `scene.matrixWorldAutoUpdate = false`
    around the second pane and restore it. Scenes with about 800 meshes notice this on weak CPUs.
  - Smaller chase-pane culling: `chase.far = 2000`. Fog is opaque past 1600, but the sky dome is 3000 and
    `frustumCulled = false`, so it still draws.
- **If a device still can't hold 60 fps** (phase 3, only if measured): drop the pixel ratio to 1.5 while split is
  on, or hide small far-only detail in the chase pane with a camera layer (for example the outline meshes of
  friendlies over 300 m away, by `chase.layers`). Don't toggle `receiveShadow` per pane, because that recompiles
  materials. Measure with CPU throttling first (section 8).

---

## 5. Audio

- **The listener follows the gunsight.** It is the main `camera`, so `refreshListener`, `spatialCues`,
  `updateThreats`, `updateNearMisses`, the delayed explosion sounds and `addShake` all keep working with no change.
  The gun's pan cap `GUN_SPATIAL_LIMITS { maxPan: 0.2, cueScale: 0.25 }` still applies. From the sight, which sits on
  the gun block, the gun is nearly dead ahead, so it stays centred, as it should.
- **Why not the chase pane?** Its listener would put the gun 500–1000 m away (quiet and late) and make the vampire
  roar. The EXTREME spatial profile would then swing wildly on every cut between targets. One stable listener on
  "us" is clearer. Mode 2 does move the listener today, but in split mode the gunsight is the "self" pane.
- **Spatial oddities to accept, or to use:**
  - The kill boom arrives `distance / 343` s after the chase pane shows the fireball: about 1.5 s at 500 m. The hold
    rule in section 2 ends the hold just after the boom, which makes it a feature.
  - The vampire's voice gets louder as it closes on the gun, not as it fills the chase pane. That is consistent with
    the gunsight listener.
  - Whizz-bys from our own rounds are already excluded by `p.origin.distanceTo(cam) <= radius`. With the listener on
    the gun block, every round starts inside the radius, so there are no false whizzes.
- **No changes to `AudioController`.**

---

## 6. Interaction with the rest of the game

1. **Slow motion (`timeScale` 0.1).**
   - Chase position is rigid to the threat, and look-at smoothing, label updates and the label rate all use real dt,
     so slow motion just works.
   - The hold uses `max(1.2 s real, soundDelay)`. `soundDelay` is real time stretched by `timeScale`, because sound
     arrivals are scheduled `/ timeScale`. So in slow motion the hold lengthens with the slowed boom.
   - **Cap it at 6 s of real time.** Decide whether the slow-motion hold should stretch at all.
2. **Game over.** `updateLogic` returns early, threats freeze in place, and FX keep playing. Keep split on:
   - the chase camera holds its current pose
   - the labels read `SYSTEM OFFLINE` / `FRIENDLIES LOST` (from `triggerGameOver`'s reason)

   No code path runs in split mode that game over has to stop. Reboot reloads the page, so nothing needs
   persisting.
3. **Window resize.** Pane rectangles are worked out from `renderer.getSize()` every frame, so no resize handler is
   needed in split mode. The auto side/stack choice re-evaluates with hysteresis. `onWindowResize` still sets the
   main camera's full-window aspect. That is overwritten per pane while split is on, and correct again on exit
   because `exitSplitView` re-applies it.
4. **OrbitControls.** `controls.enabled = false` in split mode, as in modes 1 and 2. Returning to mode 0 from any
   follow mode currently jumps the orbit from wherever the follow camera was. Small fix for every mode:
   `saveOrbitPose()` when leaving mode 0 and `restoreOrbitPose()` on return (position and `controls.target`).
5. **Tools.**
   - **`demo_video.py`** wraps `toggleCameraFollow` with its own `mode = (mode + 1) % 3` counter. As soon as the game
     has four modes, that counter and the real mode go out of step and the director picks wrong cameras. Fix:
     expose `__ciws.cameraMode` (getter) and `__ciws.setCameraMode(n | name)`, and delete the shim.
   - Then the demo's split becomes:
     ```js
     __ciws.debug.setChaseTrack(window.__vampire); __ciws.setCameraMode('split');
     … await kill …
     await wait(1.4); __ciws.setCameraMode('off');
     ```
     The demo keeps its own director timing. It can force `__ciws.debug.setSplitLayout('side')` so a portrait
     recording doesn't auto-stack.
   - **What changes on screen.** The listener moves from the over-the-shoulder PHALANX pose to the sight, which pans
     the gun a little more to the centre. The kill hold pulls back instead of engulfing the camera.
   - Re-record and compare with `demo/ciws-demo.mp4`.
   - `screenshot.py` (toggles to gun-cam, then missile-cam) and `frame_strip.py gun` (one toggle) still work,
     because SPLIT is added at the end of the cycle.

---

## 7. Code structure

New section `// --- SPLIT VIEW ---`, placed between `toggleCameraFollow` and `animate` in `index.html`:

```text
const CAMERA_SPLIT = 3;
const CAMERA_MODES = ['OFF', 'PHALANX', 'MISSILE', 'SPLIT'];
const SPLIT_GAP_PX = 3, SPLIT_DIVIDER = 0x101418;
const SIGHT_EYE = new THREE.Vector3(0, 0.95, 0.6), SIGHT_AHEAD = new THREE.Vector3(0, 0.95, 200);
const CHASE_POSE = { ascm: {back: 9, up: 2.6, fov: 60}, drone: {...}, mortar: {...} };
const TRACK_HOLD = { min: 1.2, maxReal: 6, pullBack: 28, pullTime: 0.35 };
const splitView = { layout: 'auto', resolved: 'side', chase: null, track: null, pinned: null,
                    disagreeSince: 0, shake: 0, labels: {...}, savedFov: 60, labelText: ['', ''] };

function setCameraMode(mode)            // the one place that sets cameraMode, label and controls.enabled
function enterSplitView() / exitSplitView()
function updateSightCamera(cam, realDt) // pose on the gun block, plus camera-space gun-fire shake
function pickChaseTrack(realDt)         // the rules in section 2, read-only on target/missiles
function updateChaseCamera(realDt)      // follow, hold/pull back, idle orbit
function splitPaneRects(w, h)           // -> [{cam, x, y, w, h, label}] for side/stack/pip
function renderPane(pane, shakeOffset)  // sky dome, outline scale, aspect, viewport/scissor, render
function renderSplitView(shake)         // clear+divider, shadow once, panes, restore state
function updateSplitLabels()            // HTML chips at about 10 Hz, positioned from the rects
```

Changes outside the section, all small:
- `toggleCameraFollow` → `setCameraMode((cameraMode + 1) % CAMERA_MODES.length)`.
- `updateCameraFollow` → `else if (cameraMode === CAMERA_SPLIT) { updateSightCamera(camera, dt); updateChaseCamera(dt); }`.
- `animate`: keep `skyDome.position.copy(camera.position)` and the shake add and subtract, but wrap the single
  `renderer.render(scene, camera)` call:
  ```js
  if (cameraMode === CAMERA_SPLIT) renderSplitView(); else renderer.render(scene, camera);
  ```
  `renderSplitView` restores the viewport, scissor, sky, outline width, clear colour, shadow autoUpdate and
  `matrixWorldAutoUpdate` before returning, so the single-view path never sees split state.
- `shoot()`: the shake condition (section 4.5).
- `addShake`: the second receiver (section 4.5). `updateExplosionFX` decays `splitView.shake`.
- `handleGlobalHotkeys`: C and V.
- `onWindowResize`: no change. Split reads the size every frame.
- HTML and CSS: `#split-labels` with two chips. The rename of `#camera-toggle`'s text is optional.
- `window.__ciws`: `get cameraMode`, `setCameraMode`, and `debug.setChaseTrack`, `debug.setSplitLayout`,
  `debug.splitState` (track, pose, layout) for the tools.

**Keeping it out of the gameplay paths.** Split code never writes to:
- `target`, `missiles`, any threat's mesh or velocity
- `turretYaw`/`turretPitch`, `lastShake`
- `timeScale`, or the spawn and VLS cooldowns

It reads `target` and the threat list after `updateLogic` has run. Review check: `grep` the section for `=` on those
names. The fire control (`computeAimSolution`, the neural controller, `isFiring`, `getMuzzlePosition`) is upstream
of the cameras and unchanged. The one shared mutable object, the turret, is no longer touched by shake in split mode.

---

## 8. Verification

1. **Screenshots of the poses** (extend `tools/screenshot.py` with a `split` view, appended after `missile-cam`):
   `__ciws.setCameraMode('split')`, a pinned vampire, wait 3 s, then capture. Check:
   - a 3 px divider with no 1 px seams at DPR 1, 1.5 and 2
   - the sky gradient is the same in both panes, with no seam at the horizon
   - the labels sit in the inner top corners, clear of the stats and controls
   - the reticle is at the gunsight's centre
2. **New tool `tools/split_shot.py`** (productised from `splitcam/probe.py`):
   - Spawn a vampire at a fixed angle, as the demo does. Capture at ranges of 900, 650 and 540 m, then at kill
     +0.15, +0.6 and +1.2 s. Add a `--portrait` run at 430×932 (stack) and `--pip`. Contact sheet with
     `_harness.contact_sheet`.
   - Pass criteria:
     - after the kill, the fireball fills less than about 50% of the chase pane (compare with today's 100%)
     - the label goes `TRACK` → `SPLASH` → next track or `NO TRACK`
   - Also run a drone and a mortar to check the per-type poses, including a mortar nearly overhead.
3. **Outline width consistency.** Grab one frame and measure the ink width in device pixels on a straight hull edge
   in each pane: it should be `OUTLINE_PX × DPR` ±1 in both panes, in both side and stack.
4. **`frame_strip.py`.**
   - Add a `split` view that crops the gunsight pane around the muzzle. Use it to confirm the high-shutter strobe and
     the muzzle-flash clamp choice (section 4.6) frame by frame.
   - Add a `chase` crop to check the chase pane doesn't jitter. Shake applies only after a kill, and it should look
     like shake rather than noise.
5. **Frame cost.** Hook `renderer.render` as `probe.py` does: `renderer.info.autoReset = false`, reset once per
   frame, sum over panes. Take `performance.now()` around the whole `animate` body through a wrapped
   `requestAnimationFrame` callback.
   - Report calls, triangles, mean and p95 ms, and the median frame interval for orbit, PHALANX, split-side,
     split-stack and PiP.
   - Targets:
     - split calls ≤ 2 × single − about 25 (shadow once)
     - render CPU ≤ 2 × single
     - 60 fps held
   - Repeat with CDP CPU throttling (`Emulation.setCPUThrottlingRate` 4× via `page.context.new_cdp_session`) to
     stand in for a weak laptop or phone. That is where the matrix-update and shadow savings show.
6. **Gameplay unchanged.** Add `--camera split` to `tools/soak.py` and run 90 s at wave 5 in mode 0 and in split.
   - The ASCM kill and leak ratio and the error count should match within run-to-run noise.
   - There should be no console errors.
   - Because the split code is read-only on game state, any difference beyond noise is a bug.
7. **Interaction checks (manual or scripted):**
   - slow motion on and off mid-hold
   - game over while split, then reboot
   - resize across the 1.0 aspect boundary several times (no flip-flop)
   - C/V hotkeys and the button cycle
   - return to orbit restores the saved orbit pose
   - audio: with the AUDIO DEBUG overlay (`A`), the gun pan stays ≤ 0.2 and the listener position equals the sight
     camera
8. **`demo_video.py`.** After switching it to the in-game mode, re-record. Compare the shot timings (about 32 s) and
   the split segment against `demo/ciws-demo.mp4`.

---

## 9. Phases

| Phase | Scope | Check |
|---|---|---|
| **P0 plumbing** | `setCameraMode`, `CAMERA_MODES`, `__ciws.cameraMode`/`setCameraMode`; fix the `demo_video.py` shim (works with three modes too, so it can land first) | `screenshot.py`, `frame_strip.py gun` and the demo still behave the same |
| **P1 basic split** | Mode 3 in the cycle and the V/C keys. Side and stack auto layout. Sight = main camera, chase camera following the gun's `target` with the demo's pose. Divider, sky per pane, outline scale per pane, shadow once, restoring state. Reticle moved. | `split_shot.py` captures, perf numbers, soak in split |
| **P2 targeting and labels** | The lock, hysteresis and vampire rules; hold and pull-back; cut; NO TRACK idle; per-type poses; labels; camera-space gun shake; chase explosion shake | Capture series through kill and impact; label sequence; slow-motion and game-over checks |
| **P3 polish (optional)** | PiP layout; target bracket in the gunsight; muzzle-flash clamp per pane; trail ribbons oriented on the GPU; `matrixWorldAutoUpdate` saving; orbit pose save and restore; `demo_video.py` switched to the in-game mode | Throttled perf run; re-recorded demo |

Effort: P0 and P1 about half a day of agent time; P2 about half a day; P3 a few hours per item.

## 10. Risks

- **Clashing with the other workstream.** `animate`, `updateCameraFollow`, `shoot` and `addShake` are hot spots.
  Keep the edits to one-line hooks into the new section, and rebase by symbol, not by line.
- **State leaks from `renderSplitView`.** A forgotten restore leaves the next single-view frame wrong: scissor test
  on, a quarter viewport, the dome at the chase camera, thin outlines, or shadow autoUpdate off. That shows up when
  leaving split mode. Mitigation: one `try/finally` restore block, and a screenshot check right after leaving split
  mode.
- **The four-mode cycle breaks tools** that count toggles (the demo's shim). That's why P0 lands first.
- **Track flicker.** If the hysteresis is too short, the chase camera cuts back and forth between two drones with
  nearly equal ETAs. Tune with soak captures at wave 8+ (saturation).
- **Chase camera clipping.** It can pass through smoke columns or wreck plumes (seen in `portrait-pair.png`, top
  pane) and through friendlies as a threat makes its terminal dive. Acceptable. If it looks bad, push the camera to
  the side away from `targetInfo` at close range.
- **Weak devices.** Doubling the draw calls (about 600 per frame) is fine on this Mac but could drop phones below
  60 fps. Mitigations in section 4.7. Measure throttled before building any of them.
- **Explosion shake on the chase camera** can be nauseating at about 28 m from a 10 m fireball. Start at 0.6× and
  tune it down if needed.

## 11. Decisions for the user

1. **Gunsight pose.** The demo's down-the-barrels sight (recommended), or mode 1's over-the-shoulder pose?
2. **Muzzle flash in the gunsight.** Accept it, clamp it for that pane, or raise the eye (section 4.6)?
3. **Layouts.** Side and stack auto-switching only (recommended), or also PiP from the start? Skip 3-up?
4. **Entering.** A fourth step on the camera cycle plus C/V keys (recommended), or a separate SPLIT button?
5. **Vampire priority.** Should a new vampire always take the chase camera (recommended), or should it strictly
   follow the gun's target?
6. **Kill hold length.** Tie it to the boom's arrival (about 1.2–2 s, recommended) or a fixed beat? Should it
   stretch in slow motion (capped at 6 s)?
7. **Audio listener.** Gunsight (recommended) or chase pane?
8. **Demo.** Switch `demo_video.py` to the in-game mode (P3), or keep its monkey-patch and fix only the mode shim
   (P0)?
