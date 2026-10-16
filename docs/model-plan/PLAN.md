# Plan: a realistic host ship and a Phalanx CIWS Block 1B model

This is a plan only. No repo files were changed. All paths below under `modelplan/` are in
`/private/tmp/claude-501/-Users-wiseman-src-ciws-sim/3198b73f-d85d-4071-9cf0-328b4d244fe2/scratchpad/modelplan/`.
The line numbers come from `index.html` as it stood on 2026-10-16. Other agents are editing the file, so the numbers will drift. Search by symbol name instead.

## 0. Summary and recommendations

- **Gun.** Rebuild `createPhalanxCIWS` as a Block 1B. It gets a barbette, a rotating train platform, two tall electronics enclosures that carry the trunnions, an ammunition drum under the gun, a gun housing, a barrel support frame, a mid barrel brace and the fat muzzle restraint. On top sit a lathed radome with seams and the FLIR on the mount's left side. Keep the scale the gun has today, about **1.9 units per real metre**. It is deliberately oversized, and the current proportions (pivot height, muzzle reach, radome height) already match the real mount at that scale. Keep every interface the game uses: `ciwsGroup`, `turretYaw`, `turretPitch`, `barrels` (named `'barrels'`, parent = gun block), the pivots, and the muzzle at barrels-local (0, 0, 3.5).
- **Ship.** Use a compressed **Arleigh Burke Flight IIA destroyer, DDG-81 to DDG-84 fit**: a Mk 45 Mod 4 5"/62 gun, a forward Phalanx on the 01 level in front of the bridge, an aft Phalanx, hangars and Mk 41 VLS. That fit puts a Phalanx exactly where our gun is: forward, ahead of the bridge, behind the forward VLS. Build it at about 112 × 17 units (L/B ≈ 6.6, against 3.6 today). The beam stays the same and the bow moves from z = −17 to about z = −42. The superstructure is compressed vertically so the hero gun still has clear arcs.
- **Freeboard needs one gameplay-visible change.** With the deck at y = 0 and the water at y = −1.5, every hull reads as a barge. The recommendation is a single constant `MOUNT_Y` (≈ 4) that raises the CIWS onto an 01-level deck, plus updates to the 7 hard-coded points listed in section 5.9. The fire control is unaffected because it reads the muzzle from `matrixWorld`.
- **Build approach.** Keep building procedurally in code. Do not use glTF (section 6). Add three small geometry helpers: a hull loft, a merge-by-material step, and a tapered/chamfered box.
- **Phases.** P0 plumbing and tools, P1 gun, P2 hull and raise, P3 superstructure, P4 weapons and details, P5 camera and demo reframing. The total is roughly 3–5 focused days of agent time. Every phase has a screenshot check and a gameplay check (section 7).

---

## 1. What exists now

### Scale (from the code)

The scale comes from code comments: `SPEED_OF_SOUND = 343 // units/s (1 unit ≈ 1 m)`, `ASCM_SPEED_BASE = 2.6 // units/step (~155 m/s)` and `ASCM_CRUISE_Y = 1.8 // ~3 m above the water`. The world is therefore about **1 unit = 1 m**.

| Thing | Size in units | Real equivalent | Note |
|---|---|---|---|
| CIWS overall height | ~9 (deck 0 → radome top 8.95) | 4.7 m | **Gun is ~1.9× oversize** |
| CIWS pitch pivot | y = 5 (yaw at 3, pitch +2, z +0.5) | ~2.6 m | Matches the real trunnion height × 1.9 |
| Muzzle | 5 units ahead of pivot | ~2.4–2.6 m | OK |
| Radome | Ø 2.4, 3.75 tall | Ø ~1.0 m, ~1.9 m | A bit fat (real Ø would be ~1.9 units) |
| Ship deck plan | 61 long (z −17 … +44) × 17 beam | — | L/B 3.6, barge-like |
| Freeboard | 1.5 (deck 0, `WATER_LEVEL = −1.5`) | — | Very low; reads as a lighter or barge |
| Hull draft | keel at −4.5 | — | — |
| Friendly boats | 8.6 × 3.0, origin at y 0.75 | ~9 m patrol boats | — |
| Bullets | `BULLET_SPEED` 8 u/step = 480 m/s | Real 1,100 m/s | Gamified |

Draw calls, measured with `modelplan/closeups.py`: **253 calls, 22k triangles, 497 meshes (86 of them outline meshes)**. The turret alone has **41 meshes**, including outlines.

### Reference screenshots of the current build (taken with the repo tools)

- `modelplan/cur-default.png`: the default orbit view.
- `modelplan/cur-behind.png`, `cur-low.png`, `cur-high.png`.
- `modelplan/cur-gun-cam.png`: the over-the-shoulder gun cam (mode 1).
- `modelplan/cur-missile-cam.png`.
- `modelplan/ref-gun-side.png`, `ref-gun-34.png`, `ref-gun-rear.png`: close-ups of the gun.
- `modelplan/ref-ship-side.png`, `ref-ship-bow.png`: ship profile and bow.

### Gun shortcomings

- The mount is a plain frustum base with a box "body" and two slab "cheek plates". The real mount has a tapered barbette, a wide train platform and two tall, handle-studded electronics enclosures that form the elevation yoke.
- There is no ammunition drum and no feed conveyor. On the real mount the drum is the large cylinder under the gun and one of its most recognisable features.
- The gun is a 1 × 1 × 3 box with a dark window. The real mount has a gun housing behind the barrels and a lattice barrel-support frame. The Block 1B also has a mid barrel brace and a thick muzzle restraint.
- The radome is a capped cylinder with no seams, no track/search split and no rivet rings. It is about 25% too wide.
- The Block 1B FLIR on the left of the radome is missing.
- The pedestal and base are added straight to the scene rather than under `ciwsGroup`, so the gun cannot be moved as a unit.
- At rest (yaw 0) the gun points **aft** (+z). That is harmless now. Once a bridge stands aft of the gun, it will look as though the gun is aiming at its own bridge.

### Ship shortcomings

- The hull is an extruded plan polygon: vertical sides, a flat deck, no flare, sheer or knuckle, and a blunt three-segment bow with no stem rake. The open stern has no transom shape.
- The yellow and black hazard-striped bulwarks around the whole deck look industrial, not naval.
- There is one white box deckhouse with a pole mast, and no superstructure, bridge, radar faces, funnels, boats or bow gun.
- The VLS is aft of the gun. On a Burke the forward VLS is ahead of the forward Phalanx.
- The boot-top is a red band. The US Navy uses a **black** boot-top over a red anti-fouling bottom.

---

## 2. References

### Phalanx CIWS (Mk 15) Block 1B

| Source | What it shows |
|---|---|
| [Wikipedia: Phalanx CIWS](https://en.wikipedia.org/wiki/Phalanx_CIWS) | Height 4.7 m, weight 5,700–6,200 kg. Block 1B elevation −25° to +85°, traverse ±150°. The search antenna sits at the top of the radome with the track antenna below it. Block 1B adds the FLIR, the optimized gun barrels (OGB) and a 1,550-round drum. |
| [NavWeaps: Phalanx](https://navweaps.com/Weapons/WNUS_Phalanx.php) | Barrels 1.52 m on Block 0/1 and 1.981 m on Block 1B. The OGB are "18 inches longer and substantially thicker" with "a barrel brace and a muzzle restraint". Block 1B train and elevation rate is ~115°/s. |
| [Seaforces: Mk 15 CIWS](https://www.seaforces.org/wpnsys/SURFACE/Mk-15-close-in-weapon-system.htm) | Photo gallery, including "Mk-15 Block 1B – with FLIR". Specs: 4.7 m high, 6,120 kg. |
| [Wikimedia Commons: Category Phalanx CIWS](https://commons.wikimedia.org/wiki/Category:Phalanx_CIWS) | Many photos. The two used here are below. |
| [File:DDH-183 Izumo Mk.15 Block1B Baseline2.jpg](https://commons.wikimedia.org/wiki/File:DDH-183_Izumo_Mk.15_Block1B_Baseline2.jpg) (local copy `modelplan/refimg/`) | **Near-orthographic front view.** Used for the proportions below. It shows the tapered barbette, the slab train platform, the two tall enclosures with grab handles forming the yoke, and the drum (round, covered) under the gun housing. The barrel-shaped radome has a domed top, rivet rings and a seam about 1/3 down. The FLIR turret is on the **mount's left** (viewer's right), on a bracket at mid radome height, with a round lens and a smaller cylinder below it. |
| [File:Feng jia (PFG-1115) frigate Phalanx CIWS Block 1B.jpg](https://commons.wikimedia.org/wiki/File:Feng_jia_(PFG-1115)_frigate_Phalanx_CIWS_Block_1B.jpg) (local copy) | **3/4 front-right view.** It shows the triangulated lattice barrel-support frame ahead of the housing, the six thick barrels, the mid brace and the long perforated muzzle restraint. The big drum, with its end cap, sits under the gun, and the linked feed conveyor curves from the drum to the gun on the right side. The right enclosure has a chamfered lower front. |
| [Wikipedia: M61 Vulcan](https://en.wikipedia.org/wiki/M61_Vulcan) | The gun itself: rotor and housing proportions. |

**Real proportions.** These are measured off the Izumo front view and scaled to the published 4.7 m height (1 m ≈ 281 px), so treat them as ±10%. Scene units use a scale of 1.9.

| Part | Real (m) | Scene (u) | Current model |
|---|---|---|---|
| Overall height (deck → radome top) | 4.7 | 8.9 | 8.95 ✓ |
| Barbette (static) height | ~1.25 | ~2.4 | 3.0 (base) |
| Barbette width (bottom / top) | ~2.3 / 1.9 | 4.4 / 3.6 | Ø 5 / 4 |
| Train platform width × depth × thickness | 2.4 × 2.2 × 0.15 | 4.6 × 4.2 × 0.3 | — |
| Enclosures (each): w × d × h | 0.55 × 1.6 × 1.5 | 1.0 × 3.0 × 2.9 | Cheeks 0.36 × 2.3 × 2.7 |
| Outer span across the enclosures | 2.0 | 3.9 | 2.7 |
| Trunnion / bore axis above deck | ~2.6 | ~5.0 | 5.0 ✓ |
| Drum Ø × length | ~0.9 × ~1.3 | 1.7 × 2.5 | — |
| Radome Ø | ~1.0 | 1.9 | 2.4 |
| Radome height (bottom → top) | ~1.9 | 3.6 | 3.75 |
| Radome seam (track/search split) | ~0.65 below the top of the cylinder | — | — |
| Barrel length (Block 1B OGB) | 1.98 | 3.76 | 3.5 (keep: muzzle fixed) |
| Barrel cluster Ø (outer) | ~0.33 | ~0.6 | 0.56 ✓ |
| Muzzle restraint length × Ø | ~0.3 × ~0.38 | 0.55 × 0.72 | Clamp 0.16 × 0.68 |
| FLIR head (lens Ø) | ~0.25 | ~0.5 | — |

### Host ship: Arleigh Burke, DDG-81–84 fit

| Source | What it shows |
|---|---|
| [Wikipedia: Arleigh Burke-class destroyer](https://en.wikipedia.org/wiki/Arleigh_Burke-class_destroyer) | 154–155.3 m × 20 m beam, draft 9.4 m. "Wide, flaring bow" on a large-waterplane hull. All-steel inclined (stealth) surfaces and a raked tripod mast. Mk 45 forward of the 32-cell VLS. **DDG-51 to 84 have two Phalanx (front and rear)**. Flight IIA (DDG-79+) has two hangars. DDG-81+ has the 5"/62 Mk 45 Mod 4. Two RHIBs. The aft SPY-1D faces on Flight IIA are one deck higher. |
| [Seaforces: Arleigh Burke class](https://www.seaforces.org/usnships/ddg/Arleigh-Burke-class.htm) | Per-ship photo galleries, including profiles and overhead views. Use these for the deck layout. |
| [Wikipedia: 5-inch/54 Mk 45](https://en.wikipedia.org/wiki/5-inch/54-caliber_Mark_45_gun) | Mod 4 faceted gunhouse and 62-calibre barrel (~7.9 m). |
| FineScale forum threads ([1](https://forum.finescale.com/t/need-help-with-arleigh-burke-colors/119079), [2](https://forum.finescale.com/t/current-color-of-usn-ships-help/130368)) | Modern haze gray is FS 36270 (26270), a neutral gray, not the bluish WWII 5-H. Deck gray is darker (FS 36118 or 36008 by source). |

**Why this class.** It is the iconic Phalanx, Mk 41 and Mk 45 platform, and the game already uses its vocabulary ("vampire", CIC callouts, Mk 41). DDG-81–84 carry a Phalanx **forward, on the 01 level directly ahead of the bridge and behind the forward VLS and 5-inch gun**. That is where our gun is: near the bow, with the ship extending aft. A corvette such as the Israeli Sa'ar 5 (85.6 × 11.9 m) is a plausible smaller alternative. Its beam is too narrow for the hero-scale mount, though, and I could not confirm its Phalanx position from the sources I checked.

---

## 3. Scale decisions

- **Gun.** Stays at hero scale, 1.9 u/m. It is the player's avatar. Its geometry already matches the real mount at that scale, and the fire control is tuned to it.
- **Ship.** Use a compressed, stylized Burke: **length ≈ 0.72 × real (112 u), beam ≈ 0.85 × real (17 u, as now), superstructure heights ≈ 0.6–0.7 × real**. The vertical compression is deliberate (section 5.2). L/B goes from 3.6 to 6.6. Real Burkes are ~7.8, but 6.6 still reads as a destroyer, and the slightly chubby look suits the anime style.
- **Deck equipment.** Mk 45, VLS, boats and life rafts sit at about **1.0 u/m**. The existing 8-cell VLS module, 3.8 × 6.8 u, is already 1:1 with a real Mk 41 module. Equipment then reads correctly next to the hull, and the CIWS stays the obvious hero.
- **Friendlies.** The 9 m boats are unchanged. Next to a 112 u ship they read as small craft, which is correct.

---

## 4. CIWS build plan

### 4.1 Hierarchy (same names, same pivots)

```
ciwsGroup                      (root; position (0, MOUNT_Y, 0); MOUNT_Y = 0 until phase P2)
├─ mountStatic                 NEW: barbette + train ring, moved here from scene root
└─ turretYaw                   position y = 3 (unchanged); rotation.y driven by fire control
   ├─ yawStatic (merged)       train platform, enclosures, trunnion caps, handles
   └─ turretPitch              position (0, 2, 0.5) (unchanged pivot); rotation.x driven
      ├─ pitchStatic (merged)  drum, feed conveyor, radome collar, FLIR bracket + head
      ├─ radome (lathe)        separate mesh (white material, own outline)
      └─ gunBlock              position (0, 0, 1.5) (unchanged); the gun housing mesh
         └─ barrels  name='barrels'  origin = bore axis, spins about z (spinVisual)
            ├─ 6 × barrel tube   (owned by the barrel-blur rework; do not merge)
            ├─ muzzles (crowns)  (owned by the blur rework)
            ├─ barrel brace @ z≈1.6, muzzle restraint z 2.95→3.5
            └─ blur mesh(es)     (owned by the blur rework)
```

**Invariants (P1 acceptance).** If these hold, `getMuzzlePosition`, `shoot()`, the gun cam, the gunsight in `tools/demo_video.py` (eye at gunBlock-local (0, 0.95, 0.6)), `tools/frame_strip.py`, `tools/spin_check.py` and the audio muzzle spatializer all keep working unchanged.

- `scene.getObjectByName('barrels')` returns the spinning group, and `barrels.parent` is the **non-spinning gun block**.
- The barrels' origin lies on the bore axis, which passes through the pitch pivot. In pitch-local terms the bore axis is y = 0, x = 0.
- The muzzle is at barrels-local (0, 0, 3.5), which is pitch-local z = 5.0.
- `turretYaw.position = (0, 3, 0)` and `turretPitch.position = (0, 2, 0.5)` relative to `ciwsGroup`.
- The blur meshes stay direct children of `barrels` (`frame_strip.py` finds them by `material.uniforms.uSpin`).
- The barrel tubes keep their own material instance (`tubeMat`), which the blur hides from the colour pass.

`BARREL.{ring, radius, muzzle, clamps, clampRadius, clampHalf}` feed the blur shader (`createBarrelBlur`). Change barrel-related sizes **only through `BARREL`, and only after the blur rework lands**, then re-run `frame_strip.py`.

**Optional.** Set `turretYaw.rotation.y = Math.PI` once at creation so the gun rests pointing forward rather than at the bridge. The fire control slews from whatever angle it finds, so this does not change any interface.

### 4.2 Part list

All parts use the toon style. Coordinates are in the parent's frame. +z is the gun's forward direction, and **+x is the gun's left**: facing +z with +y up, the right-hand side is −x.

| # | Part | Parent | Construction | Size / placement (u) | Material |
|---|---|---|---|---|---|
| 1 | Barbette | mountStatic | Chamfered tapered box (8 verts; see helper `taperedBox`), or an octagonal `CylinderGeometry(r1, r2, h, 8)` | Bottom 4.4 × 4.4, top 3.6 × 3.6, h 2.6, y 0 → 2.6, corners chamfered 0.5 | `CIWS_GRAY` (haze gray) |
| 2 | Train ring / bearing | mountStatic | `CylinderGeometry(1.9, 1.9, 0.4, 32)` | y 2.6 → 3.0 | `CIWS_DARK` |
| 3 | Deck foot flange | mountStatic | `CylinderGeometry(2.6, 2.8, 0.15, 8)` | y 0 → 0.15 | `CIWS_GRAY` |
| 4 | Train platform | yawStatic | Box 4.6 × 0.3 × 4.2 with chamfered front corners (`ExtrudeGeometry` of a plan polygon, depth 0.3) | Yaw-local y 0 → 0.3 | `CIWS_GRAY` |
| 5 | Enclosures L/R | yawStatic | `ExtrudeGeometry` of the **side profile**: a rectangle with the lower-front corner chamfered 45° and a rounded top-front where the trunnion is. Extrude 1.0 across x. | x = ±(1.0 … 2.0), y 0.3 → 3.2, z −1.7 → +1.4. The trunnion centre must be at yaw-local (±1.5, 2.0, 0.5). | `CIWS_GRAY` |
| 6 | Trunnion caps | yawStatic | `CylinderGeometry(0.45, 0.45, 0.12, 24)`, axis x | Outer faces of the enclosures at (±2.05, 2.0, 0.5) | `CIWS_DARK` |
| 7 | Grab handles | yawStatic | U-shapes from 3 thin boxes each, merged; 4 per enclosure front, 3 per side | 0.3 wide, 0.06 thick | `CIWS_DARK`, **noOutline** |
| 8 | Ammunition drum | pitchStatic | `CylinderGeometry(0.85, 0.85, 2.5, 32)`, axis z, plus two end-cap discs (`CylinderGeometry(0.88, 0.88, 0.1)`) | Axis at pitch-local (0, −1.05, −0.2), z −1.45 → +1.05 | `CIWS_GRAY`; caps `CIWS_DARK` |
| 9 | Feed conveyor | pitchStatic | `TubeGeometry` along a `CatmullRomCurve3`, 24 segments, radius 0.13, 8 radial | From the drum front-right (−0.6, −1.3, 1.0) curving out to (−0.75, −0.6, 1.4) and into the gun housing's right side (−0.5, 0, 1.0) | `CIWS_DARK` |
| 10 | Gun housing | gunBlock (its own geometry, replacing the 1 × 1 × 3 box) | Tapered box: rear 1.0 × 1.0, front 0.8 × 0.8 | gunBlock-local z −1.9 → +0.1, y −0.5 → +0.45. **Keep the top below y 0.75 for z > 0.3** so the gunsight eye at (0, 0.95, 0.6) stays clear. | `CIWS_DARK` |
| 11 | Barrel support frame | gunBlock | Merged thin boxes: a hexagonal ring at z 0.1 (Ø 0.9) and z 1.0 (Ø 0.75), plus 6 diagonal struts between them. That gives the triangulated lattice look. | Struts 0.06 × 0.06. Ring plates 0.1 thick. | `CIWS_GRAY`. Outline on the rings only; struts **noOutline**. |
| 12 | Barrel tubes ×6 | barrels | **Unchanged** (blur rework). Optionally `BARREL.radius` goes 0.08 → 0.09 (Block 1B "thicker"). | Ring 0.2, z 0 → 3.5 | `tubeMat` |
| 13 | Barrel brace (mid) | barrels | `CylinderGeometry(0.34, 0.34, 0.16)` (existing clamp at z 1.6) | z 1.6 | `CIWS_DARK` |
| 14 | Muzzle restraint | barrels | `LatheGeometry` profile: a sleeve r 0.36, z 2.95 → 3.5, with a 0.04 lip at each end. The front face is an `ExtrudeGeometry` disc with 6 bore holes (`Shape.holes`, depth 0.04). | Replaces the clamp at 3.35 | `CIWS_DARK`. The face is **noOutline** (holes break the inverted hull). |
| 15 | Radome collar | pitchStatic | Short `CylinderGeometry(1.0, 1.0, 0.35, 32)` under the radome | Pitch-local centre (0, 0.75, −0.5) | `CIWS_GRAY` |
| 16 | Radome | turretPitch | **`LatheGeometry`** from one profile (48 radial segments): cylinder r 0.95 from y 0.9 → 3.4, a 0.03 raised rivet lip at y 2.75 (the search/track seam), then a quarter-ellipse cap of height 0.85 to y 4.25. Make the profile points dense around the cap for smooth toon bands. | Centre axis at pitch-local (0, ·, −0.5), as now | `RADOME_WHITE` (0xeceae2) |
| 17 | Radome seams | radome | Two thin `TorusGeometry` rings (at y 0.95 and 2.75) and one vertical seam strip (box 0.03 × 2.4 × 0.02) | — | `CIWS_DARK`, **noOutline** |
| 18 | Track-antenna window | radome | Flat-ish arc panel: a `CylinderGeometry` segment (thetaLength 1.2 rad, r 0.955) at the front-lower part, y 1.1 → 2.6 | — | Slightly greyer white (0xdcdad2), noOutline |
| 19 | FLIR bracket + head | pitchStatic | Bracket: L-shaped arm from 2 boxes. Head: box 0.55 × 0.5 × 0.6 plus a lens (dark disc r 0.2 with a light `RingGeometry` rim) facing +z. Under it, a cylinder r 0.22, length 0.45, axis x. | On the **mount's left = +x** side of the radome. Head centre at pitch-local (1.3, 2.3, −0.3). | Head `CIWS_GRAY`, lens `INK`; lens **noOutline** |
| 20 | Stencils (optional) | yawStatic | CanvasTexture decal: yellow "CAUTION" plate and red danger chevrons on the enclosures | — | noOutline |

### 4.3 Materials (shared module-level constants, created once)

- `CIWS_GRAY = toonMat(0x9aa1a5)`: haze gray for the mount. On ships the mount is gray and only the radome is white or very light.
- `CIWS_DARK = toonMat(0x4a5155)`: drum caps, housing, frame, trunnions.
- `RADOME_WHITE = toonMat(0xeceae2)`: the current white.
- `INK = new THREE.MeshBasicMaterial({ color: PALETTE.ink })`: lenses, holes and tiny lines.
- The barrel `tubeMat` and `barrelMat` stay as they are (blur rework).

### 4.4 Merging, outlines and performance

- Add a helper `mergeByMaterial(parts) → Mesh[]`. It takes `[{ geo, mat, matrix, noOutline }]`, applies each matrix, groups the parts by material and `noOutline`, and calls `mergeGeometries` once per group. `mergeGeometries` is already imported. Normalise first: `geo.index ? geo.toNonIndexed() : geo`, keep only `position` and `normal`, and also `uv` where a texture is used. This avoids mixing indexed Box geometry with non-indexed Extrude geometry, which `mergeGeometries` rejects.
- Build one merged mesh per (rigid group × material): mountStatic ×2, yawStatic ×2 + handles ×1, pitchStatic ×2–3, radome ×1, seams ×1, gun housing ×1, frame ×2, and barrels (tubes ×6 + crowns + brace + restraint + face, as the blur needs). That comes to about **15 visible meshes plus about 10 outlines**, against 41 today. Keep `castShadow` on the static merged meshes and the radome. Shadows from the handles, seams and lens add nothing.
- **Outline rules.** `getOutlineGeometry` welds vertices (1e-3) and recomputes smooth normals. That is fine for closed convex-ish parts: the barbette, enclosures, drum, radome and housing. Mark these **`noOutline`**:
  - parts with holes (the muzzle face)
  - parts thinner than about 0.1 u (struts, handles, seams), where a 2 px ink shell swallows the part at any distance
  - decals and lens discs

  For the radome, outline the lathe mesh only. The seam rings provide the internal "ink lines" more cleanly than outlines would.
- **Flat versus smooth shading.** The enclosures and barbette should look faceted. Build them non-indexed and call `computeVertexNormals()` so the faces stay flat and the toon bands step per face. The radome and drum need smooth normals: lathe and cylinder geometry are indexed, so they are already smooth.

### 4.5 Camera and coupling checks for the gun

- **Gun cam (mode 1).** The offset is (4, 2.5, −6) in the pitch frame, so the camera sits behind the gun and on its left (+x). The new **FLIR on +x will appear in the right-hand part of the gun-cam frame** next to the radome. Check `cur-gun-cam.png` against a new capture. If it intrudes too much, nudge the FLIR head lower and further aft (pitch-local y 2.0, z −0.6). Do not mirror it to the wrong side.
- **Gunsight** (`demo_video.py`, gunBlock-local eye (0, 0.95, 0.6) looking along +z). Nothing in the gun block may rise above y 0.75 forward of z 0.3. The radome front edge is at gunBlock-local z ≈ −1.05, so it is behind the eye.
- **Swing clearance.** The enclosures stand ±2.0 off the axis at yaw-local y ≤ 3.2. The drum's lowest point at −25° depression is at pitch-local (0, −1.9, 0.9) rotated, so it stays above the train platform. Check it at `turretPitch.rotation.x = +0.44` (depression; the pitch sign follows `computeSightAngles`, where negative pitch is up) and at −1.48 (+85° elevation). The drum and radome must not pass through the platform or the enclosures. Verify by posing the mount in a scratch script and taking side screenshots.

---

## 5. Ship build plan

### 5.1 Layout in ship coordinates

The bow points to −z, the gun is at the origin, and +x is **starboard**: facing −z with +y up, the right-hand side is +x. Heights assume `MOUNT_Y = 4` (section 5.9).

```
 z: -42      -26        -10.5      0         +9 ...+24  +27..+33  +44..+50  +50..+57  +57..+64   +64..+70
    stem     Mk45 Mod4  fwd VLS    CIWS(01)  bridge/SPY  fwd stack aft stack  aft VLS   hangar    flight deck
    deck 4.6 deck ~3.0  deck 2.15  01 lvl 4  roof 8.5    top ~11   top ~11    deck 2.0  roof 7.5  deck 1.8
```

| Item | Real Burke (approx., from bow) | Here (z, u) |
|---|---|---|
| Stem at deck / forefoot at waterline | 0 | −42 / −37 (raked stem) |
| Mk 45 gunhouse centre | ~26 m | −26 |
| Forward VLS (32 cells) | ~36–46 m | −14 … −7 (the existing 8-cell module, live, plus 2 dummy modules alongside) |
| Forward Phalanx on the 01 level | ~50 m | **0 (our gun)** |
| Bridge front | ~54 m | +9 (≥ 8.5 so the gun cam at mode 1 clears it) |
| SPY-1D faces | On the forward superstructure | Four octagons on the inclined corners of the bridge block, z +11 … +22 |
| Tripod mast | ~62 m | +20 (raked aft ~8°) |
| Forward / aft funnels | ~72 / ~95 m | +27…+33 / +44…+50 |
| RHIBs | Amidships | +36, starboard (and port) |
| Aft VLS (64) | Aft of the 2nd funnel | +50 … +57 (dummy, static) |
| Hangar ×2, aft CIWS on top | Aft | +57 … +64 (aft CIWS: optional static dummy) |
| Flight deck / transom | Last ~20% | +64 … +70 |

### 5.2 Keep the hero gun's arcs clear

The game's single gun engages 360° of threats. On a real ship the bridge and mast block the forward Phalanx's arcs aft, and the mount has cut-out zones. Here, tracers flying through our own superstructure would look broken. The approach:

- **Line-of-fire ceiling.** Every bulky structure within 40 u of the gun stays at or below **y = MOUNT_Y + 4.5 (8.5)**. The pitch pivot and the level-fire muzzle are at MOUNT_Y + 5 (9). That is why the superstructure is compressed vertically: bridge roof 8.5, with the SPY faces on the bridge block's inclined sides. Only the thin tripod mast and the two funnels rise above it. Those occlude narrow sectors astern: a funnel about 3.5 wide at 30 u blocks about ±3.3°.
- **Clear gun circle.** Keep nothing above the 01 deck (MOUNT_Y) within **r = 6.5** of the yaw axis. At −25° the muzzle drops to about MOUNT_Y + 2.9 at a radius of about 4.7.
- **Measure it.** `modelplan/arc_clearance.py` is a working prototype. It poses the turret at bearings 0–358° and pitches 0°, −10° and +15°, raycasts from the muzzle along the bore against own-ship meshes, and lists blocked bearings. On the current build: pitch 0° → bearing 180° (the mast); −10° → 158–202° (the deckhouse); +15° → none. Promote it to `tools/arc_clearance.py` in P0 and use it as the acceptance check for P2–P4. Target: at 0° pitch, only a few-degree slivers from the mast and funnels; at −10°, nothing beyond the deck itself near the stern.
- **Decision for the user.** If any blocking remains objectionable, a separate gameplay change could end tracer flight at the first own-ship hit (a cheap AABB list) and spawn a spark. That changes hit statistics, so it is not part of this plan.

### 5.3 Hull: a lofted station table

Replace `extrudeOutline(SHIP_OUTLINE, …)` with `buildLoftedHull(STATIONS)`:

- **Station table.** Each station is `{ z, deckY, halfDeck, halfKnuckle, knuckleY, halfWL, halfBilge, keelY }`, with about 16–20 stations, denser at the bow and the transom. Example values:

  | z | deckY | halfDeck | halfKnuckle (y) | halfWL | keelY |
  |---|---|---|---|---|---|
  | −42 | 4.6 | 0.25 | 0.2 (3.6) | 0 | — (stem) |
  | −37 | 4.3 | 2.6 | 2.0 (3.2) | 0.4 | −2.5 |
  | −30 | 3.8 | 5.0 | 4.2 (2.6) | 2.4 | −4.5 |
  | −20 | 3.0 | 7.2 | 6.6 (1.8) | 5.2 | −5.5 |
  | −10 | 2.3 | 8.3 | — | 6.8 | −6 |
  | 0 … +50 | 2.0 | 8.5 | — | 7.6 | −6 |
  | +60 | 1.9 | 8.3 | — | 7.2 | −5 |
  | +70 (transom) | 1.8 | 7.8 | — | 6.4 | transom foot −0.9 |

  - **Sheer**: a smooth rise forward of z −10, from 2.0 to 4.6 at the stem.
  - **Flare**: the deck edge is wider than the waterline everywhere, and strongly so forward (about 30° at z −30, about 10° aft). That is the Burke's "wide flaring bow".
  - **Knuckle**: forward of z −12 the section breaks at knuckleY. The upper strake flares outward more than the lower one, which gives the classic Burke bow chine line and catches a toon light band.
  - **Stem**: raked about 25°, from the deck at z −42 down to the forefoot at the waterline, z −37.
  - **Transom**: flat, raked about 8°. Its foot sits 0.6 u above the water so the stern overhang reads.
- **Mesh.**
  - For each station, emit a half-section polyline (keel → bilge → waterline → knuckle → deck edge) and mirror it to x < 0.
  - Stitch consecutive stations with quads. Use the same vertex count per station so the stitch is trivial, and collapse the points to the stem line at the bow.
  - Add a **deck cap** (triangle strip between port and starboard deck edges per station, using a separate material group) and a **transom cap**.
  - Build it non-indexed with `computeVertexNormals()` for crisp toon facets. Use two meshes (sides, deck) rather than one multi-material mesh. Draw-call count is the same, and it is simpler to outline only the sides plus a deck-edge rim.
  - Outline the sides mesh. It is closed with the deck and transom caps, so `getOutlineGeometry` works. The deck needs no separate outline.
- **Derive `SHIP_OUTLINE` from the station table.** Use the plan polygon of `halfDeck`, and make it symmetric with x ≥ 0 points sorted by z as `hullHalfWidthAt()` expects. That keeps `SHIP_BOUNDS`, `nearShip()`, `hullHalfWidthAt()` (audio hull-slap positions), friendly spawn exclusion and `isOverOpenWater()` all correct automatically. Also add `deckHeightAt(z)`, which interpolates `deckY` (and 01 and superstructure tops), for the impact code (section 5.9).
- **Waterline treatment.** Generate the boot-top as a **separate thin band** from the same loft: sample each station's section between y = WL − 0.35 and WL + 0.45, offset 0.03 along the section normal, black `0x1c2023`, noOutline. The underwater body below it is anti-fouling red `0x8c3b33` (the existing colour), which only shows in the water's transparency or at grazing angles. Optionally add a narrow white foam strip mesh, or reuse the existing ring billboards along the waterline at the bow, for a little bow-wave life. The ship is stationary, so keep it subtle.

### 5.4 Superstructure: stealth-inclined blocks

Add a helper `slopedBlock({ x0, x1, z0, z1, y0, y1, inSide, inFront, inBack })`. It is an 8-vertex box whose top face is inset inward on the sides (about 8–10°, the Burke's inclined walls), front and back, built non-indexed for flat facets. It is the one building block for the forecastle step, 01 deckhouse, bridge, hangar and funnels.

- **CIWS 01-level deck.** z −6 … +9, half-width 6, y 2.0 → 4.0 (= MOUNT_Y). The front face slopes back about 30° (a breakwater-like wedge). The flat top is the gun's deck plane.
- **01 deckhouse.** It runs aft from +9 to +57 at half-width 6.2, y 2 → 4, leaving 2.3-u side walkways on the main deck.
- **Bridge block (02–03).** z +9 … +24, half-width 6.5 tapering to 5.5 at the roof, y 4 → 8.5. The front is inclined about 15°.
  - Bridge windows: a dark inset band (0x22303a, noOutline) on the front and front corners, y 7.3 → 8.1, slanted with the face.
  - Bridge wings: thin slabs to ±8.0 at y 7.4.
- **SPY-1D faces.** Four flat **octagons** (`CylinderGeometry(1.3, 1.3, 0.12, 8)` turned face-on, then rotated π/8 so a flat edge is up). Centres at y ≈ 6.4, on the bridge block's four corner facets. The forward pair faces ±45° off the bow, at z ≈ +11. The aft pair faces ±135°, at z ≈ +22, about 0.6 higher, per Flight IIA. Colour 0x7b8489 with a darker rim ring (0x5d656b); both noOutline because they sit flush.
- **Hangar block.** z +57 … +64, half-width 7.5, y 2 → 7.5, two hangar doors (dark inset rectangles, noOutline). Optionally a static dummy CIWS on top: reuse the merged gun geometry, without barrels spin or blur, at 0.8 scale.
- **Small detail** (one merged mesh per material):
  - Life-raft canister racks: white cylinders r 0.3 × 1.0, about 12 along the 01 deckhouse sides.
  - SRBOC/Nulka launchers: small dark boxes by the bridge wings.
  - Pelorus and lookout stands on the bridge wings.
  - Searchlights on the funnel platforms.

### 5.5 Mast and radar

- **Raked tripod.** Three cylinders (r 0.22) from the bridge roof (y 8.5) at z +18 … +22, converging at a platform at y 17. It continues as a single pole to y 25, raked aft 8°. Add two yardarms (boxes 6 × 0.15 × 0.15 at y 18.5 and 21), a small platform with the SPS-67 radome (sphere r 0.45), a TACAN/ESM pod near the top, and 2–3 whip antennas. Draw the whips as thin ink boxes (noOutline, `INK` material) so they read as drawn lines.
- **One cheap animated part.** A small rotating surface-search antenna bar on the mast platform, `rotation.y += dt * 2`. It gives the ship life at almost no cost.
- **SPG-62 illuminators.** Three dish-on-pedestal units: one on the bridge roof forward, two on the aft deckhouse. Each is a `LatheGeometry` shallow dish r 0.6 plus a cylinder pedestal. Point them at the current target (cosmetic, optional).

### 5.6 Funnels

Two funnel casings, each a `slopedBlock`: z +27…+33 and +44…+50, half-width 1.8, y 4 → 10.5, raked aft about 8° (shear the top vertices +0.6 z). The flat top has two or three short black exhaust stubs (cylinders r 0.35, height 0.5) and a dark cap plate. The funnels are slightly lighter than the hull so they separate in the cel bands.

### 5.7 Weapons and deck equipment

- **Mk 45 Mod 4 (bow gun) at z −26.**
  - Gunhouse: a faceted `slopedBlock`, 2.8 wide × 4.4 long × 1.9 tall, sitting on a short barbette ring. The front is sloped strongly and the sides inclined about 12°: the Mod 4's angular stealth shield.
  - Barrel: a cylinder r 0.13, length 6.0, tapering slightly, with a small muzzle swell. It sticks out of a vertical slot in the shield front and is elevated about 5° at rest.
  - Group it as `bowGun` with a yaw group and a pitch group so it can later be slewed cosmetically toward the threat bearing. Not required.
- **Forward VLS.** **Move** the existing functional 8-cell module from z0 = 19 to **z0 = −10.5**, set into the main deck at y = `deckHeightAt(−10.5)` (≈ 2.15). Flank it with two **dummy** 8-cell modules (x ±3.9): one merged static mesh with lids closed, the same `VLS_PLATE_MAT` and lid colour. Together they make a 24-cell bank; the real Flight IIA has 32. Code changes:
  - `createShipVLS(ship, { x0, z0, deckY })` takes its origin instead of the hard-coded `z0 = 19` and y 0.06 / 0.15.
  - `cell.pos` is set from that origin, so launches rise from the right place.
  - In `vlsLaunchPoint`, `vent: new THREE.Vector3(0, 0.4, cell.pos.z)` becomes `vent: new THREE.Vector3(VLS_ORIGIN.x, cell.pos.y + 0.25, cell.pos.z)`. It currently assumes x = 0 and the deck at y = 0.
  - The rising missile must clear the CIWS. At 10.5 u from the yaw axis that is outside the 6.5 gun circle, so it does.
- **Aft VLS.** Dummy 64-cell look: 8 merged module plates with closed lids, static, at z +50…+57.
- **Boats.** One RHIB per side at z +36, on davit arms (two bent boxes) over the walkway, y ≈ 4.6. Hull: gray with a dark collar (`ExtrudeGeometry` of a boat plan polygon, bevel on).
- **Forecastle fittings.**
  - Anchor windlass (two drums) at z −35, with anchor chains as a merged row of small dark boxes running to the hawse pipes at the deck edge.
  - Bow bullnose.
  - Bitts/bollards: reuse the existing bollard geometry, merged.
  - Breakwater: a low V-shaped wall at z −31, 0.6 tall, ahead of the Mk 45.
- **Lifelines in place of hazard bulwarks.**
  - One merged mesh of stanchions (boxes 0.06 × 1.0 × 0.06 every 2 u along the deck edge, following `deckY` and `halfDeck`) and two lifeline rails (thin boxes along each edge segment), in `INK` or dark gray, **noOutline**.
  - Keep a solid bulwark only at the bow (z −42 … −30, 0.8 tall, part of the hull loft: extend the side polyline above the deck there).
  - **Open question:** the hazard stripes may be a deliberate gamey touch. If so, keep them only as a painted yellow/black danger ring on the 01 deck around the CIWS (decal), which matches real ships' painted safety circles in spirit.
- **Flight deck.** A deck-gray plane with white edge lines, a centreline and the touchdown circle, plus yellow lineup lines. Use one CanvasTexture decal (noOutline, `polygonOffset`), and add a safety net (thin ink boxes) along the edges.
- **Markings.**
  - Hull number: white numerals with a black drop shadow, CanvasTexture on a quad on each bow side at z ≈ −31. Orient each quad to that station's flare angle (compute the section normal from the loft) and use `polygonOffset`. Use a **fictional** number (e.g. "166") so the model does not claim a real ship.
  - Draft marks at the bow and stern (optional).
  - A small ensign on the mast gaff (optional).

### 5.8 Colours

Define these as constants next to `PALETTE`. The toon gradient has 3 bands at 0.41 / 0.73 / 1.0, so the planes must differ in **value**, not just hue, to read.

| Token | Hex | Used for |
|---|---|---|
| `NAVY_HAZE` | 0x8e969a | Hull sides (FS 36270-ish neutral gray) |
| `NAVY_HAZE_LT` | 0x9ca3a7 | Superstructure, funnels, Mk 45. One step lighter so blocks separate from the hull. |
| `NAVY_DECK` | 0x555c61 | Weather decks (dark deck gray). Check it doesn't go near-black in the shadow band; raise to 0x5f666b if it does. |
| `FLIGHT_DECK` | 0x60666a | Plus white 0xf0efe9 and yellow 0xe2b53a markings |
| `BOOT_TOP` | 0x1c2023 | Waterline band |
| `ANTIFOUL` | 0x8c3b33 | Underwater hull |
| `WINDOW` | 0x22303a | Bridge windows, hangar door insets |
| `SPY_FACE` / `SPY_RIM` | 0x7b8489 / 0x5d656b | Radar faces |
| `CIWS_GRAY` / `CIWS_DARK` / `RADOME_WHITE` | see 4.3 | Gun |

The white radome becomes the brightest object on a gray ship. That is good: the hero reads first.

### 5.9 `MOUNT_Y`: raising the gun's ground plane (required for a realistic freeboard)

A real-looking hull needs freeboard of roughly 0.3–0.5 × beam (5–8 u), and today it is 1.5 u. Two ways to get it:

- **Raise the gun.** This is the recommended option. Add `const MOUNT_Y = 4`, set `ciwsGroup.position.y = MOUNT_Y`, and move the pedestal and base under `ciwsGroup`. Then update every hard-coded "gun is at y ≈ 0" point:

  | Where | Now | Change to |
  |---|---|---|
  | `MOUNT_AUDIO_POSITION` (~l.727) | (0, 4, 0) | (0, MOUNT_Y + 4, 0) |
  | `controls.target.set(0, 5, 0)` in `init` (~l.3183), initial `camera.position (-15, 10, 20)` | — | Target y + MOUNT_Y, camera y + MOUNT_Y |
  | `targetInfoFor(null)` (~l.3759) | (0, 2, 0) | (0, MOUNT_Y + 2, 0), so threats still strike the mount and the impact sits on the 01 deck |
  | Missile-cam `phalanxPos` (~l.6136) and the no-target fallback `camera.lookAt(0, 5, 0)` (~l.6127) | — | + MOUNT_Y |
  | `isOverOpenWater()` (~l.4803): `!nearShip(p, 1.5) && p.y < 4` | — | `!nearShip(p, 1.5) && p.y < deckHeightAt(p.z) + 2`, or simply `< MOUNT_Y + 4` |
  | `vlsLaunchPoint` vent y 0.4, x 0 | — | Module origin (5.7) |
  | `createShipVLS` hard-coded deck y | — | Module origin (5.7) |
  | Shadow camera `dirLight.shadow.camera` ±45 around target (0, 0, 12) | — | Target (0, 0, 14), ±62, so the 112-u ship is inside it. Keep the 2048 map (≈ 6 cm texels). Raise `far` if the mast top clips. |

  **Fire control impact.** `computeSightAngles`, `computeAimSolution`, `shoot()` and the NN inputs are all muzzle-relative and read `barrels.matrixWorld`, so aiming stays correct. The only change is geometric: targets are now 4 u further below the muzzle, so engagements use slightly more depression. The gun has no pitch clamp, and the steepest case (a sea-skimmer at 1.8 at 45 u) is about −11°.

  Re-check the neural controller with `tools/nn_diagnostics.py`. The saved net (`ciwsNeuralControllerV8`) was trained on the old geometry. If its accuracy drops, bump the storage key so it retrains rather than loading a stale net.

  ASCMs climb to `target.y` in the terminal phase, so they now hit the 01 deck rather than the main deck. Sea-skimming height (`ASCM_CRUISE_Y`) is unchanged.

- **Lower the sea** (`WATER_LEVEL` to −5.5). This is **not** recommended. Friendlies sit at a hard-coded y 0.75 (their targeting point would float 4 u above their hulls). `ASCM_CRUISE_Y`, the spawn altitudes, splashes and `isOverOpenWater` are all absolute, and every tool pose would need to change. More code would move, with more risk.

- **Fallback if no gameplay-visible change is wanted (`MOUNT_Y = 0`).** Everything in 5.3–5.8 still applies, but the deck at the gun stays at y 0. The best available is a solid 1.5-u bulwark (hull sides continuing above the deck), so the visible side is about 3 u. The ship will read as a low patrol ship rather than a destroyer, and the 01-level step must be dropped.

**Tools to re-pose for `MOUNT_Y`.** Best done by exposing `window.__ciws.layout = { mountY, deckHeightAt, shipBounds }` and posing relative to it:

- `tools/screenshot.py` views `behind`, `low` and `high` (absolute y).
- `tools/explosion_shot.py` `deck`/`airburst` targets.
- `tools/scene_shot.py` `vls`/`engage` poses (14, 9, 10).
- `tools/audio_lab.py` and `tools/audio_stress.py` (camera (−15, 10, 20) looking at (0, 5, 0)).
- `tools/demo_video.py`: `SHIP = (0, 4, 0)`, the 13.5 s low view `dir * −36 + (−8, 12, 5)` looking at `dir * 70 + (0, 6, 0)`, and the overview.

The opening pose and the gunsight in `demo_video.py` derive from `barrels`, so they follow automatically.

### 5.10 Readability at game distances

- **At 20–40 u** (default orbit, gun cam): the gun, the 01 deck, the forward VLS, the Mk 45 and the bridge front fill the frame. Put the fine detail here: handles, seams, FLIR, lids, windlass, life rafts.
- **At 150–300 u** (demo overview, friendlies' views): only the silhouette survives. That means the bow sheer and flare, the stepped superstructure, the raked mast, two funnels, the white radome dot, the Mk 45 barrel and the black boot-top line. Make these strong and keep the outline on the hull sides, superstructure blocks, funnels and mast legs. Everything else is noOutline or merged.
- Ink outline width is a constant 2 px, so tiny outlined parts become ink blobs at distance. That is the main reason for the noOutline list above.

---

## 6. Procedural code or glTF?

| | Procedural (as now) | Authored glTF (.glb) |
|---|---|---|
| Single-file, no build step | ✓ stays one file | ✗ needs a sidecar `.glb`, or a base64 blob of several hundred KB inlined |
| Interfaces (`turretYaw` / `turretPitch` / `barrels`, pivots, muzzle) | Exact, in code | Must match node names and pivot transforms authored in Blender; drift is easy |
| Startup | Synchronous: `createPhalanxCIWS()` sets globals that `init`, the audio spatializer and the tools use immediately | Async `GLTFLoader`, so `init` must await it or guard every early use of `barrels` |
| Cel look | `toonMat` and outline rules applied per part, by intent | Imported PBR materials must be remapped to toon. Imported meshes often have split normals, open shells and tiny parts that make inverted-hull outlines noisy. |
| Parametric (`MOUNT_Y`, ship length, station table) | ✓ | ✗ re-export for every change |
| Agent-editable and diffable | ✓ text diffs; other agents can edit in parallel | ✗ binary; nobody can review a diff |
| Detail ceiling | Lower, but cel style rewards simple, clean shapes | Higher (rivets, curved armour) |

**Recommendation: procedural.** It fits the no-build single file, keeps the gameplay interfaces exact and synchronous, and keeps the cel look under control. The extra code is about 600–900 lines, kept manageable with four helpers: `mergeByMaterial`, `taperedBox`/`slopedBlock`, `buildLoftedHull`, and `decalQuad` (a CanvasTexture plane with polygonOffset). Keep the model code in a clearly fenced section ("Ship and mount models") so it stays separate from gameplay code.

---

## 7. Phases, effort, risks and verification

Effort is rough agent working time. Every phase ends with the repo tools run against the working tree, and screenshots compared side by side with `modelplan/cur-*.png` and `ref-*.png`.

### P0: Plumbing and tools (S, ~2–3 h). No visual change.

- Add `MOUNT_Y = 0`, `deckHeightAt()` and `window.__ciws.layout`. Move the pedestal and base under `ciwsGroup` (`mountStatic`). Route the hard-coded points in 5.9 through `MOUNT_Y`.
- Add `tools/arc_clearance.py` (from `modelplan/arc_clearance.py`). Add `tools/model_shots.py` (from `modelplan/closeups.py`: gun side, 3/4 and rear, ship side and bow, draw-call and mesh counts, and the gun cam at yaw 0/90/180/270).
- **Verify:**
  - `uv run tools/screenshot.py <prefix>` should be pixel-identical in layout to today.
  - `uv run tools/soak.py 60` should show the same kill and leak counts and fps.
  - The arc report should match the baseline above (bearing 180 at 0°; 158–202 at −10°).

### P1: CIWS Block 1B (M, ~0.5–1 day). Independent of the ship work and can go first.

- Build section 4 and add the merge helpers. Start **after the barrel-blur rework lands**, or touch only parts 1–11 and 15–19 and leave `barrels` children alone until it does.
- **Risks:**
  - Breaking the blur's assumptions (`BARREL`, `tubeMat`, `barrels.children`).
  - The FLIR or housing intruding on the gun cam or the demo gunsight.
  - Outline noise on the lattice frame (mitigated by noOutline).
  - Drum or radome clipping the platform at the pitch extremes.
- **Verify:**
  - `uv run tools/frame_strip.py <p> side 24` and `front 24`: barrels spin and the blur is intact.
  - `uv run tools/spin_check.py`.
  - `uv run tools/screenshot.py <p>`: check the gun-cam frame especially.
  - `tools/model_shots.py`: turret meshes ≤ about 25 including outlines (from 41); total calls ≤ the baseline of 253.
  - A scratch pose script at pitch +0.44 / −1.48 rad and yaw 0/90° for clipping.
  - `uv run tools/demo_video.py out.mp4 1280 720`: check the split-screen gunsight is unobstructed.
  - `uv run tools/soak.py 120 5`: fps unchanged and kills unchanged (muzzle invariant).

### P2: Hull loft, MOUNT_Y = 4, VLS move, lifelines (M–L, ~1 day)

- Station table, `buildLoftedHull`, derived `SHIP_OUTLINE`, boot-top band, 01-level CIWS deck, forward VLS relocation (with the `vent` fix), shadow frustum, and tool re-posing from 5.9.
- **Risks:**
  - Fire-control behaviour change from the new geometry (NN shift).
  - Threat impact point and deck splash classification.
  - Friendlies spawning nearer the longer hull (the margin of 15 still applies).
  - The orbit camera dipping into the hull: `minDistance` 5, no collision.
  - Shadow acne on the new faceted hull: tune `normalBias`.
- **Verify:**
  - `tools/screenshot.py` (all 6 views).
  - `uv run tools/scene_shot.py <p> vls`: the launch leaves the relocated cell, the exhaust vents beside it, and nothing intersects the CIWS.
  - `uv run tools/explosion_shot.py <p> deck` and `water`: correct deck versus water effects.
  - `tools/arc_clearance.py`.
  - `uv run tools/nn_diagnostics.py 60 30`: accuracy within noise of the baseline taken in P0.
  - `uv run tools/soak.py 180 5`.
  - `uv run tools/audio_lab.py`, briefly: hull-slap positions follow `hullHalfWidthAt`.

### P3: Superstructure, SPY faces, mast, funnels (M, ~0.5–1 day)

- **Risks:**
  - Exceeding the line-of-fire ceiling.
  - The gun cam clipping the bridge front when the gun aims forward. The camera is about 6.5 u aft of the pivot, so keep the bridge front at z ≥ 9 and its roof below MOUNT_Y + 7.5.
  - Default orbit framing occluded by the bridge or mast.
- **Verify:**
  - `tools/arc_clearance.py`: only sliver sectors at 0°.
  - Gun-cam captures at yaw 0/90/180/270 (`model_shots.py`).
  - `tools/screenshot.py` default/behind/high.
  - Draw calls checked.

### P4: Mk 45, dummy VLS banks, boats, hangar and flight deck, markings, small detail (M, ~0.5–1 day)

- **Risks:**
  - Draw-call creep. Keep merged-per-material: the ship's total budget is about 50 calls including outlines and the live VLS lids.
  - Decal z-fighting: use `polygonOffset` and noOutline.
  - Detail noise at distance.
- **Verify:**
  - `model_shots.py` (counts plus ship side/bow).
  - `tools/screenshot.py high` and a far overview pose (300 u) for silhouette readability.
  - `soak.py` fps.

### P5: Camera and demo reframing, polish (S–M, ~0.5 day)

- Re-pose `demo_video.py` (the 13.5 s low view must now see the forward VLS launch past the bow and superstructure; the overview must fit the longer ship), `scene_shot.py`, `explosion_shot.py` and `screenshot.py` via `window.__ciws.layout`.
- Optionally make the gun rest pointing forward (4.1) and the cosmetic Mk 45 or illuminator slewing.
- **Verify:**
  - `uv run tools/demo_video.py demo.mp4` and review frames at 0, 6, 11, 14, 16 and 25 s (`ffmpeg -ss … -frames:v 1`).
  - `uv run tools/contact_sheet.py` to compare before and after.

### Cross-cutting risks

1. **Concurrent edits.** Other agents are changing `createPhalanxCIWS` (the blur) and possibly tools. Land P0 and P1 in small commits, re-read the current function before editing, and keep the `BARREL` contract.
2. **Hidden "y ≈ 0" assumptions** beyond those listed. Grep for `0, 2, 0`, `0, 4, 0`, `0, 5, 0`, `y < 4` and `position.y` literals in both `index.html` and `tools/*.py` during P0. The list in 5.9 is from a grep on 2026-10-16.
3. **Performance.** The current frame is 253 calls / 22k triangles. The new ship adds triangles (loft, lathe), but merging should keep calls flat or lower. Watch the shadow pass: shadow casters are drawn twice, so mark only big parts `castShadow`.
4. **Outline artefacts on complex merged geometry.** Inverted hulls need closed, reasonably convex shells. Merged boxes are fine (each shell is welded separately). Lofted and extruded parts must be closed (caps). Open or thin parts get noOutline.
5. **Scale perception.** The hero-scale gun on a 0.72× ship is a deliberate stylization. If it reads as too toy-like, the main dial is ship length, 112 → 130, without touching the gun.

## 8. Files in `modelplan/`

- `PLAN.md`: this file.
- `cur-default.png`, `cur-behind.png`, `cur-low.png`, `cur-high.png`, `cur-gun-cam.png`, `cur-missile-cam.png`: current build, from `tools/screenshot.py`.
- `ref-gun-side.png`, `ref-gun-34.png`, `ref-gun-rear.png`, `ref-ship-side.png`, `ref-ship-bow.png`: close-ups, from `closeups.py`.
- `closeups.py`: scratch pose and draw-call script, to be promoted to `tools/model_shots.py`.
- `arc_clearance.py`: scratch line-of-fire clearance check, to be promoted to `tools/arc_clearance.py`.
- `refimg/`: the two Commons reference photos plus one more Block 1B shot (Izumo front view, Feng Jia 3/4 view, JS Shimakaze).
