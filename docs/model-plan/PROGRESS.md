# Model plan: progress log

Screenshots and strips are in `shots/models/` (untracked). `before-*` is the untouched build (HEAD
55c35bf), taken with the same tools as the later phases. Baseline runs that needed the old build
after the edits had started were served from a `git archive` copy of HEAD.

## P0: plumbing and tools

**Changed**
- `MOUNT_Y` (0 for now) in the configuration block. Routed through it: `MOUNT_AUDIO_POSITION`, the
  initial camera and orbit target, `targetInfoFor(null)`, and the missile camera's `phalanxPos`,
  fallback pose and look point.
- `createPhalanxCIWS` creates `ciwsGroup` first, at `y = MOUNT_Y`, and the pedestal and base now hang
  under it instead of the scene root.
- `createShipVLS(ship, origin)` takes the module centre (`VLS_ORIGIN`) instead of a hard-coded
  `z0 = 19` and deck at y 0. `vlsLaunchPoint`'s vent now comes from `VLS_ORIGIN.x` and the cell height.
- `deckHeightAt(z)` (flat for now), the ship group is named `'ship'`, and
  `window.__ciws.layout = { mountY, deckHeightAt, shipBounds }` for the tools.
- `mergeGeometries` imported (the plan said it already was; it wasn't).
- New tools: `tools/arc_clearance.py` (from the scratch prototype; tests only the `'ship'` group,
  so friendlies can't block a ray, adds -5 deg and names the meshes hit) and `tools/model_shots.py`
  (from `closeups.py`: gun and ship close-ups, gun camera at four bearings, render counts at the
  default view). `tools/nn_diagnostics.py` gained `--save FILE` and `--frozen FILE`, so one saved net
  can be scored, untrained, on two geometries.

**Not changed, on purpose**: `isOverOpenWater` keeps `y < 4`. That bound is height above the sea
(impacts on friendlies, which sit at y 0.75), not the gun's height, and our ship is excluded by
`nearShip` anyway.

**Checks**
- `screenshot.py`: same layout as before in every view (only the live game state differs).
- `arc_clearance.py`: +15 clear; 0 deg blocked at 180; -5 at 168-192; -10 at 158-202. Matches the
  plan's baseline.
- Baseline render counts (`model_shots.py`, default view, spawns held): **265 draw calls, 32.7k
  triangles**, 619 meshes (81 outlines), 41 meshes in the turret (+4 for the pedestal and base).
  The plan's 253 / 22k was measured from a different view.
- `soak.py 60 5` (baseline): 34 kills, ASCM 4 killed / 1 leaked, 60.0 fps, worst frame 23 ms.

## P1: CIWS Block 1B

**Changed**: `createPhalanxCIWS` rebuilt. New helpers in a "Ship and mount models" section:
`mergeByMaterial` (one mesh per material and outline flag, transforms baked in), `convexSolid` /
`loftLoops` (flat-faceted capped solids between two loops), `chamferRect` / `levelLoop`, `at()` (a
part transform) and `strut()` (a thin box between two points). Materials `CIWS_GRAY`, `CIWS_DARK`,
`RADOME_WHITE`, `RADOME_PANEL`, `BARREL_MAT`, `INK_MAT`. Parts:
- barbette (chamfered, tapered, on a deck flange, with panel lines for doors) and train bearing;
- train platform and two enclosures (extruded side profile: cut-back lower front, top rounded about
  the trunnion), trunnion caps, grab handles and door panel lines;
- ammunition drum with rim bands, feed chute (tube) into the gun's right side, radome collar, FLIR
  on the mount's left (head, lens, lower sensor, bracket);
- lathed radome (cylinder plus domed top) with seam rings, a vertical seam and the track-antenna panel;
- gun housing (tapered, chamfered) and the triangulated barrel frame (two hex ring plates and 12 struts);
- in the existing `cluster` inside `barrels`: six barrels (merged), the mid brace, the lipped muzzle
  restraint, the six ink bores on its face and vent slots in its side. `createGunFX(gunBlock,
  cluster)` is unchanged; the flash uses a new `BARREL_RING` constant instead of a literal 0.2.

Interfaces kept: `ciwsGroup`, `turretYaw` (y 3), `turretPitch` (0, 2, 0.5), gun block at z 1.5 (now a
Group), `barrels` named and parented to it, muzzle at (0, 0, 3.5).

**Deviations from the plan**
- The plan's drum position doesn't clear the platform: at -25 deg its front drops to yaw-local
  y -0.1. The train platform is lowered instead (yaw-local -0.55 to -0.25, on a barbette 2.2 tall);
  this also gives the trunnion the real height above the platform. The drum is a little smaller
  (r 0.75, 2.2 long, axis at pitch-local y -1.25, z -0.4) so it clears the gun housing above it.
  Checked by posing at -30, -25, 0 and +85 deg (`p1-clip-sheet.png`).
- Enclosures end at z -1.6 and the FLIR sits higher (pitch-local y 2.55): at +85 deg the plan's
  FLIR position swings into the enclosure's rear.
- The radome is 0.95 radius, 3.2 tall above its collar (top at mount height 9.1).
- No blur-specific barrel contract any more (the blur was replaced by the high-shutter look before
  this work); new barrel parts are in `cluster`, so they shudder and spin with it.
- The gun now rests trained over the bow (`turretYaw.rotation.y = Math.PI`, plan 4.1, optional).

**Checks**
- `frame_strip.py` front/side/sight/gun: cluster lands at irregular angles, bores read head-on,
  flash at the barrel ends, the sight view is clear of the housing.
- `spin_check.py`: ~29 deg/frame, max ~49 (the expected 10-50 deg jumps).
- `model_shots.py`: 34 meshes in the mount including outlines and the 6 muzzle-flash meshes
  (was 45 incl. pedestal and base); 28 without the flash. Default view 196-220 calls,
  23-30k triangles (varies with which friendlies are in view; was 265 / 32.7k).
- `soak.py 120 5`: 68 kills, 17 of 19 ASCMs killed, 60.0 fps, worst frame 23 ms.

## P2: hull loft, MOUNT_Y = 4, VLS move, lifelines, hazard ring

**Changed**
- `HULL_STATIONS` (16 stations, z -42 to +70: sheer, deck and waterline half-breadths, keel) and
  `hullSection` (10 points per half-section: keel, deadrise, bilge, waterline, boot-top edge, knuckle,
  deck edge, bow bulwark; raked stem, lifted stern and raked transom) feed `buildHull`, which stitches
  them into flat-faceted sides (with stem and transom caps), the black boot-top and bottom, and the
  deck. `SHIP_OUTLINE` is now derived from the stations, so `SHIP_BOUNDS`, `hullHalfWidthAt`,
  `nearShip` and friendly spawning follow the new 112-long hull. `deckHeightAt(z)` interpolates the sheer.
- `MOUNT_Y = 4`: the CIWS stands on an 01-level deck (`slopedBlock`, front sloped back like a
  breakwater) that runs aft as the 01 deckhouse; side walkways on the main deck (y 2.0).
- Painted yellow/black safety ring round the CIWS (`hazardRing`, a striped `makeHazardTexture`
  strip with polygon offset). The hazard-striped bulwarks are gone; `lifelineParts` puts stanchions
  and two rails along the main-deck edge aft of the bow bulwark and round the 01 deck.
- The live VLS module moved to the forecastle: `VLS_ORIGIN = (0, deckHeightAt(-10.5), -10.5)`.
- Shadow frustum: target (0, 0, 14), +-62.
- Palette: `NAVY_HAZE`, `NAVY_HAZE_LT`, `NAVY_DECK` (0x5f666b; the plan's 0x555c61 went near-black
  in the shadow band), `BOOT_TOP`.
- Tools re-posed relative to `window.__ciws.layout.mountY`: `screenshot.py` (behind, low; high
  reframed for the longer ship), `explosion_shot.py`, `scene_shot.py` (engage, vls), `audio_lab.py`
  and `audio_stress.py` (camera, gun and mount spatializers, deck impact, the VLS position).

**Deviations**
- The deck is flat at y 2.0 from z -14 aft (the plan had 2.3 at the VLS) so the live module sits
  level; the sheer rises forward of it.
- The hull doesn't cast shadows (the sea doesn't receive them; on itself it only made acne).
- No antifouling red: the water is opaque, so the underwater body would never show. Everything below
  the boot-top's upper edge is boot-top black.
- `isOverOpenWater` unchanged (see P0).

**Checks**
- `scene_shot.py vls`: the launch leaves the forward module, the exhaust vents beside it, the
  missile climbs clear of the CIWS.
- `explosion_shot.py deck` (impact at the mount on the 01 deck: fire, debris, no water splash) and
  `water` (splash ring and spray): correct.
- `arc_clearance.py` (hull and 01 level only): +15 and 0 clear; -5 blocked 174-186 by the 01 level's
  aft lifeline; -10 blocked 352-8 by the raised bow and 168-192 aft.
- `soak.py 180 5`: 106 kills (the baseline rate), 18 of 18 ASCMs killed, 60.0 fps, worst frame 23 ms.
- Neural net, `nn_diagnostics.py 60 30`. The saved-weights spec and inputs are unchanged. A net
  trained on the old geometry and saved (`shots/models/nn-baseline-net.json`) was scored frozen
  (`--frozen`) on both builds:

  | | old geometry | new geometry (two runs) |
  |---|---|---|
  | in-reach aim error, median / p90 (deg) | 0.096 / 0.39 | 0.089 / 0.34, 0.075 / 0.29 |
  | in-reach within 1 unit | 69% | 72%, 80% |
  | fire-call accuracy | 99.2% | 99.9%, 98.9% |
  | driving 30 s: rounds / hits / kills | 729 / 45 / 20 | 648 / 40 / 20, 664 / 42 / 19 |

  No change beyond run-to-run noise, so the storage key stays `ciwsNeuralControllerV8`. (Learning
  from scratch varies a lot between runs on either build: 0.07 to 0.25 deg median.)

## P3: superstructure, SPY faces, mast, funnels

**Changed** (all in `createShip`)
- Bridge block on the 01 level (z 9 to 24, roof at 8.5), lofted between two chamfered loops so its
  four cut corners carry the SPY-1D faces (`faceOctagon`: octagon, flat edge up, on a darker rim; the
  aft pair 0.6 higher). Windows across the front and forward corners (`loftFace` / `facePanel`),
  bridge wings at 7.0 to 7.9.
- A lower 02 deckhouse (to 6.6) from the bridge aft to the second funnel; two raked funnels (top
  10.6) with dark caps and exhaust stubs; the hangar (to 7.0) with two doors.
- Raked tripod mast from the bridge roof: legs, pole to 25.5, platform with the SPS-67 radome, two
  yards, a TACAN pod, ink whip aerials, and the surface-search antenna (`shipRadar`) turning in
  `updateWorldFX` (sim time, so it slows in slow motion).
- New helpers: `slopedLoops` (with `slopedBlock` on it), `loftFace`, `facePanel`, `faceOctagon`;
  `strut` can make round rods; `WINDOW_MAT`, `SPY_FACE`, `SPY_RIM`.
- Shadows: the inclined walls are nearly edge-on to the sun and faces turned from it showed heavy
  acne (also with the plan's frustum alone). `shadow.normalBias` 0.03 -> 0.12, `bias` -0.0005 -> -0.0002.
  Checked with shadows on and off (`acne-sheet.png` / `acne2-sheet.png`).

**Deviations**: no SPG-62 on the bridge roof (it would rise into the line of fire); the two
illuminators are on the 02 deckhouse aft. The bridge sits flush with the 01 deckhouse walls
(continuing the inclined wall) rather than overhanging to +-6.5.

**Checks**
- `arc_clearance.py`: +15 deg: mast pole and platform only (178-182). 0 deg: thin slivers from the
  mast legs and pole and the first funnel (174, 178-182, 186), as agreed. -5 deg: 144-216, the bridge
  front (was 168-192, the old deckhouse); -10 deg: 154-206 aft (was 158-202) and 352-8 over the bow.
  A bridge right behind the gun blocks depressed fire astern on any layout; the real mount has the
  same arc.
- Gun camera at 0/90/180/270: clear; at 180 the bridge, SPY face and mast fill the background.

## P4: Mk 45, VLS banks, boats, hangar and flight deck, markings, detail

**Changed**
- Mk 45 Mod 4 at z -26: faceted gunhouse loft on a short barbette, 6.2-long barrel at 5 deg with a
  muzzle swell, dark slot, and a low V breakwater ahead of it.
- VLS: `vlsCells` / `vlsModuleParts` build a module's fixed parts; the live module keeps its hinged
  lids (`createShipVLS` now returns its fixed parts for merging). Two fixed modules flank it (24
  cells forward) and four sit across the deck aft of the second funnel (32 cells). Lid and well
  materials are module-level (`VLS_LID_MAT`, `VLS_DARK_MAT`).
- Fittings: anchor windlass, cable links to the hawse pipes, three pairs of bollards a side, a RHIB
  a side on davits by the 01 deckhouse (grey hull, dark collar, console, ink falls), life-raft
  canisters, decoy launchers ahead of the bridge, two SPG-62-style illuminators.
- Decals (`decalMat`, `canvasTexture`): flight-deck markings (edge lines, dashed centreline, yellow
  landing circle and lineup line) and a made-up hull number "166" on the upper strake of each bow,
  set on the loft's knuckle-to-deck facet and reading left to right from outboard.
- All the fixed ship parts are merged in one pass (`structure`), one mesh per material: the ship
  is 45 meshes including outlines, 16 of them the live module's eight lids and their outlines (64
  before merging per group). The arc tool now reports where hits land (z, y), since the names are
  coarse ('hull', 'structure', 'radar', 'vls').
- Anti-ship missiles aimed at our ship strike where their run first crosses the hull
  (`shipStrikePoint`, set in `spawnAntiShipMissile`) instead of all flying on to the mount: with the
  longer hull, one from ahead or astern flew through the bow, or through the hangar, funnels and
  bridge, first (`ascm-astern-before-sheet.png`, `ascm-strike-sheet.png`). Damage, integrity and
  engagement are unchanged; from abeam they still hit beside the mount.

**Deviations**: the 01 deckhouse ends at z 48 (not 57) so a 4-module aft VLS bank fits on the main
deck before the hangar; no aft CIWS dummy on the hangar; no draft marks or ensign.

**Checks**
- `model_shots.py`: forecastle, amidships and stern close-ups, profile, bow, quarter, far
  silhouette (`p4b-sheet.png`, `p4-ship-far.png`). Default view 187 draw calls, 37.5k triangles.
- `soak.py 90 5`: 53 kills, 9 of 10 ASCMs killed, 60.0 fps, worst frame 24 ms.

## P5: cameras, demo poses, final checks

**Changed**
- Default orbit view starts off the port bow, looking aft at the gun with the bridge and mast behind
  it (`camera (-15, MOUNT_Y + 8.5, -15)`, target `(0, MOUNT_Y + 4.5, 2)`); from the old pose the
  bridge filled half the frame. The gun already rests trained over the bow (P1).
- `demo_video.py`: the opening 3/4 shot pulls back to frame the whole mount and its ring (it still
  derives from where the gun is aiming); the vampire shot and the chase camera's look point are
  relative to `layout.mountY`. Gun camera, missile cam, split-screen gunsight (eye on the gun block)
  and overview unchanged and checked.
- `explosion_shot.py`: also `airburst` and `flak` re-posed. `scene_shot.py vls` re-posed for the
  forward module.

**Demo**: recorded once (`demo/ciws-demo-newmodels.mp4`, 32.6 s) before the user asked for no video;
its frame sheet is `shots/models/demo-newmodels-sheet.png`. No further video work and no
unique-frame check, as asked.

**Final checks**
- `scene_shot.py` vls / vls-boat / wreck / ascm / engage, `explosion_shot.py` airburst / flak / deck /
  water: all behave (`p5-checks.png`); the ASCMs in `ascm` and `engage` are engaged and killed.
- `soak.py 120 5`: 69 kills, 17 of 18 ASCMs killed, 60.0 fps, worst frame 21 ms.
- `spin_check.py`: ~29 deg/frame, max ~49.
- Time to first frame (median of 5 loads, `scratch/startup.py`): ~350 ms before, ~390 ms after.
- Render counts, default view, spawns held (`model_shots.py`, several runs each; the spread is
  which friendlies, clouds and smoke are in frame): **before 237-265 draw calls, 26-33k triangles;
  after 168-249 calls, 33-51k triangles**. Like for like, the ship went from 63 to 45 meshes
  (including outlines, and the 16 for the live VLS lids) and the mount from 45 to 34 (6 of them the
  muzzle flash). Triangles are up from the lofted hull, the lathed radome and the lifelines.
- Before/after: `before-after-game.png`, `before-after-models.png`.

The scratch scripts used for these checks are in `docs/model-plan/scratch/` (pose clipping,
unopposed ASCM runs, candidate camera poses, the shadow-acne A/B, startup timing, a sheet maker).

## F: friendly ships (frigates instead of 9 m boats)

Shots in `shots/friendlies/` (untracked): `before-*` from a copy of the build as it stood before this
work (`shots/friendlies/before-build/`), `work/` for the iterations, and the final set at the top level.

**Reference and scale.** Two fits of small modern warships that carry Mk 41: after the
**Constellation class (FFG-62)** (57 mm Mk 110, a Mk 41 bank behind it, an integrated mast with three
fixed radar faces, one big funnel, NSM, SeaRAM on the hangar) and a **light frigate in the MEKO 200 /
Anzac mould** (76 mm in a faceted cupola, one 8-cell module, a traditional bridge with a director,
a lattice tripod mast carrying a big turning air-search radar, a raked funnel with a RHIB each side,
Harpoon canisters, an after director, a Phalanx on the hangar). Real frigates are as long as our
destroyer (FFG-62 151 m); at our ship's 0.72 they'd be ~110 long and five wouldn't fit round her. The
hull is **our own hull's loft scaled 0.41 long, 0.44 wide, 0.55 high about the waterline: 46 x 7.5**,
freeboard 1.9 amidships, 3.4 at the bow. Topside equipment is at about 0.65 of ours (`FRIENDLY_VLS_SCALE`,
the scale the friendly VLS missiles already used). They read as frigates in company, about 0.4 the
length of our ship.

**Built** (all in the "Friendlies" section): `FRIENDLY_HULL_MATRIX` / `friendlyHull` (the loft through
any list of `hullSection`s, carried over), `friendlyDeckY`, `friendlyHalfBeam`; the two topside
builders `frigateTopside` and `lightFrigateTopside` (fixed parts, the topmast's parts, the radar's,
the two deckhouse blocks either side of the break) and shared parts (`friendlyFittings`: breakwater,
windlass, bollards, scaled lifelines in two runs that stop at the break; `friendlyBoatParts`,
`friendlyCIWSParts`, `friendlyFunnelParts`, `friendlyVLSParts`); `FRIENDLY_FITS` (each fit's
template and wreck, built once and cloned); `buildFriendlyShip`; `buildFriendlyWreck`. Markings:
`makeFriendlyMarkings(number, name)`, one 512 x 256 canvas per ship holding the hull number, the name
and the flight deck markings, on one mesh (`friendlyMarkingQuads` / `friendlyMarkingsMesh`): the
number wraps over the knuckle on both bows and reads from outboard, the name is across the transom,
the deck has edge lines, centreline, landing circle and lineup line. `FRIENDLY_HULLS` gives each name
a fit and a made-up two-digit hull number (FFG fit 64/67/69/72, light frigates 38/41/47/52), so any
draw of five has both fits.

Shared helpers changed, our ship's output unchanged (45 meshes): `stationAt` (with `deckHeightAt` on
it) and `hullSectionAt`; `buildHull(sections)` takes the sections; `lifelineParts(path, scale)`;
`vlsModuleParts(origin, live)` leaves the live cells' lids off (was a boolean); `vlsHatches` builds
hinged lids for any module (our live module and the friendlies'); `RHIB_PLAN` shared.

**VLS.** Each friendly has two live cells in her first module (`FRIENDLY_LIVE_CELLS`) with hinged
hatches built per ship on her `'vls'` anchor (a group at the module centre, in our module's units).
`vlsLaunchPoint` picks a ready cell for her as for our ship; the exhaust vents from the uptake beside
it; `swingHatch` opens and closes both. A salvo's second round uses the other cell.

**Wreck.** Per fit, from the same parts: the hull lofted in two halves to a jagged, torn section at
`FRIENDLY_BREAK_Z` (between the bridge and the funnel), with a scorched band either side; parts go to
the half their centre is on; smoke-stained hull, superstructure and charred deck (`WRECK_PAINT`), the
deckhouse ends burnt out, the topmast and radar down over the starboard side; the markings take the
ship's own paint. `'wreck-fire'` is at the break. `updateWrecks` retuned for the 46-long hull: the
break settles until awash while the ends lift and she lists about 20 deg; in the plunge both ends rear up
first and she sinks 24 (was 6), enough to take the bow under before the wreck is removed. Smoke
leaves from a wider patch at the break; foam rings boil up round the break, bigger.

**Gameplay.** Unchanged: each friendly's targeting point (group origin at `FRIENDLY_Y` = 0.75, the
hit test is still within 5 of it), damage, threat logic, the solver, the net, the CIC wiring
(`destroyFriendly` -> `announceFriendlyHit(key, side)`). Changed:
- Placement keeps the old rule (uniform in +-100, centre 15 clear of our hull box) and adds: her
  whole length 8 clear of our hull box, 18 between any two friendlies' centrelines, heading within
  +-26 deg of our course (in company). Sampled 10,000 times (`scratch/placement.mjs`): range from
  the gun mean 84.0 -> 85.2 (median 86.4 -> 87.9; share within 60: 17.5% -> 17.0%); nearest other
  friendly mean 57.6 -> 69.7 (pairs closer than 25: 18% -> 1%).
- `isOverOpenWater` is also false over a friendly's hull (`overFriendly`), so a hit on her is a deck
  explosion (fireball, shock ring, the non-water sound), not a water column out of her deck.
- Known look: the hit sphere is her middle, so an anti-ship missile from ahead or astern passes into
  her hull for about 0.1 s before it goes off. Moving her aim point to the hull edge (as
  `shipStrikePoint` does for us) would shorten the engagement, so it's left.

**Checks**
- No console errors (`screenshot.py`, every `scene_shot.py` run, the soaks).
- Shots: `after-models-sheet.png` (both fits close up, `model_shots.py` gained `ffg-*` / `lf-*` views
  in a friendly's own frame), `before-after-default.png`, `before-after-high.png`,
  `after-vls-boat-sheet.png` and `after-hatch-sheet.png` (the hatch opening, `scratch/hatch.py`),
  `after-wreck-sheet.png`, `after-wreck-late-sheet.png` (V-break, list, ends rearing, gone under),
  `after-engage-sheet.png` (the second missile is aimed at friendly 0; both are shot down).
  `scene_shot.py` `wreck`, `wreck-late` and `vls-boat` are now posed in the friendly's own frame.
- Render counts (`scratch/friendly_counts.py`, three loads each, spawns held):

  | | before | after |
  |---|---|---|
  | one friendly: meshes (outlines), triangles | 11 (5), 196 | 16-17 (3), 5.3-5.8k |
  | overhead view of the whole field: calls, triangles | 157-164, 24-28k | 162-178, 50k |
  | demo overview pose: calls, triangles | 244-287, 42-48k | 237-303, 61-72k |

  Most of a friendly's triangles are the lifelines, spheres and cylinders; the draw calls barely
  move because everything static is merged per material and only the hull sides, the superstructure
  and the radar carry outlines.
- `soak.py 120 5`, three runs each (the spread is mostly which friendlies the random threats pick):

  | | kills | ASCMs killed | friendlies lost | worst frame | fps |
  |---|---|---|---|---|---|
  | before | 69, 73, 69 | 17/17, 13/13, 19/22 | 4, 0, 2 | 25, 23, 30 ms | 60.0 |
  | after | 71, 72, 71 | 16/16, 17/17, 14/14 | 1, 2, 2 | 28, 31, 28 ms | 60.0 |

  No change beyond run-to-run noise.
