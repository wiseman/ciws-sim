# Phalanx for visionOS

Native SwiftUI + RealityKit app, with the simulation translated from `index.html` into Swift.
Open `CIWSSim.xcodeproj`, select the **CIWSSim** scheme and a Vision Pro destination, and run.
The deployment target is visionOS 2.0. A headset build needs your development team for signing.
The project and assets are included; XcodeGen and Node are only needed for development.

The app launches into a full immersive ship-deck view at the web app's `XR_STATION`, beside the mount
(`Info.plist` makes the immersive space the default scene). The headset supplies the viewpoint.
The station panel swaps the deck for a tabletop overview in a volume, and back; only one is open
at a time, and a tabletop the system restores from an earlier launch closes itself. Both share one
battle; only the open presentation advances it.
Use `--mute` in the scheme's launch arguments for silent inspection. Shut down the simulator after testing.

## Simulation

`Sources/CIWSSimulation` contains the Swift game rules, using Double precision and the web app's
variable display-frame update scaled to its 60-step reference rate. It preserves the tuned constants
and update order, including the previous rendered muzzle transform, one spawn/shot per frame,
round expiry before movement, the original bullet hit gate, noisy radar tracking, and ally ETA ties.

The port includes drone cruise/pushover/dive, ballistic mortar shells, sea-skimming cruise missiles,
classic intercept/traverse control, the 7–32–24–3 neural controller and Adam training, live replay,
fleet placement and replacement arrivals, damage and sinking, VLS timing and motion, waves and Zen,
voice scheduling/cooldowns/crew channels, long-run milestones, sightings, and holiday selection.
The bundled voice clips come from `../sounds`; there is no JavaScript runtime, WebView, network
requirement, or third-party runtime dependency.

Controls include pause, **1/10 speed**, hold fire, mute, send raid, restart, classic/neural control,
learning, and Zen. Neural mode is available after training. Resetting the net requires two presses
within three seconds, as on the web. High score, trained weights, and controller selection persist.
Entering the deck enables Zen, matching the web's XR entry behavior; leaving restores the prior mode.

## Original visual assets

The models are **the original web geometry**, exported by executing the model builders from
`index.html` during development. No replacement ship, mount, aircraft, or wildlife models are used.
`Resources/Visuals/web-models.json` records the source SHA-256, hierarchy, transforms, material colors,
UVs and geometry ranges; `web-meshes.bin` contains the original Float32 vertex and index buffers.
The canvas decals are exported as PNGs. Geometry and textures are shared between cloned entities.

This includes the detailed Phalanx, hull loft and deck fittings, hazard stripes and markings,
both frigate fits with each ship's identity, broken wreck halves, all three threat types,
VLS rounds, helicopter, dolphins, whale, gull, sailboat, duck, sleigh, witch, pumpkin and debris.
The native renderer animates the original turret, pitch, barrel, propeller, antenna, hatch, wreck,
rotor and wing pivots. Kill marks and stars use the original stencil geometry and placement rules.

`WebShaders.usda` contains native MaterialX shader graphs for the three-band toon ramp, ink hulls,
hemisphere/sun illumination, distance haze, gradient sky, moving ocean patches and whitecaps,
muzzle flashes, fire/smoke heat bands, crisp dissolve, ribbons, shock/foam rings, spray and wakes.
These retain the web palette and formulas where supported. They are loaded as RealityKit
`ShaderGraphMaterial`s; the GLSL strings and exporter JavaScript are not shipped in the app.

Rendering is not pixel-identical to Three.js: puff/ribbon noise currently uses MaterialX noise in
place of the Ashima simplex implementation, ink extrusion uses eye distance rather than view-space
z, and the Three.js PCF shadow-map pass is not reproduced. The headset view also does not use the
web's orbit-camera director, split-screen/chase cameras, or forced camera shake. These are remaining
parity work, not changes to the tuned aiming/flight constants.

## Original sound

The battle sounds are **the web game's own**. `tools/export_audio.mjs` runs `AudioController`'s
buffer builders from `index.html` with a fixed seed and writes the rounds, explosions, hits, flak
pops, splashes, hull slaps, VLS roar, blast thump, chirps, rotor and sleigh bells to
`Resources/Sounds/web-sounds.bin` (16-bit, 48 kHz, mid channel), plus the two alarms as WAVs.

The web's live audio graph is ported to per-sample Swift synths in `Sources/CIWSSound`, rendered
into RealityKit audio generators, so RealityKit places every source and tracks the head while the
sound itself matches the browser's:

- the gun, each round timed to the sample with the barrels' spin-up, fused by the soft clip, with
  deck slapback and the gun's fatigue over the first two minutes;
- the mount's barrel-drive whine, traverse servos, gearbox grind and idle hum;
- each threat's own voice (turbine scream, falling shell whistle, two-stroke drone with its dive
  rush), Doppler-shifted, muffled with distance;
- the sea's swells along both sides, gusting wind that sweeps about the station, the engine drone
  and random wave slaps on the hull;
- on deck, a close blast's centred thump, then everything muffled under ringing ears.

The explosions are voiced for small speakers like the headset's, which barely play the boom (85%
of a big blast's energy is under 120 Hz; the thump's is nearly all). As in the web's `BLAST_BODY`
and `addBlastBody`, `BlastBody` adds a whump, fireball roar and debris rumble an octave or two up
to each exported explosion, four ways with the parts' levels, length and pitch varied, and each
play varies in level and speed. The export is of the web's explosions before this voicing: the
voiced ones peak past full scale, which 16-bit can't hold. Explosions are at full level within
80 m, and the gun dips by up to 9 dB as one arrives; its fatigue settles at 0.3 of full level.
Before these, from the mount, the gun's continuous stream covered every blast but the closest.
`tools/sound_balance.py` measures the bands and the explosion's level against the gun.

The short sounds and threat voices take turns on a fixed pool of long-lived generators
(`SourceSlot`), made when the audio loads. On the headset, an app that makes a new generator per
sound gets silence after about 50 seconds (no error; the new generator is just never rendered).
The simulator doesn't show this, so check sound changes on a headset.

`Sources/CIWSSimulation/SoundRules.swift` holds the web's distance falloff, air absorption, Doppler,
slow-motion pitch and reverb sends. They're taken at the deck station under the web's default
EXTREME profile; the browser's own panning, head shadow and stereo width are left to RealityKit.
The deck uses RealityKit's outdoor reverb preset in place of the web's convolution reverb, and
there's no master limiter (each source has the web master's soft knee). The web's camera shake
on a blast isn't carried over: moving the world under a headset is uncomfortable. `CIWSSound` is
compiled optimized even in Debug builds: unoptimized, a raid's synths overrun the audio deadline.

## Development and validation

From the repository root:

```sh
swift test --package-path visionos
node visionos/Tests/Oracle/generate.mjs --check
node visionos/tools/export_web_reference.mjs --check
npm ci --prefix visionos/tools
npm run check --prefix visionos/tools
```

The JavaScript oracle executes extracted original functions to generate the Swift test fixtures.
Tests compare intercept solutions/features, flight trajectories, radar noise, traversal, neural
training weights, voice-channel schedules and randomized lotteries, plus gameplay regression and
long-run finite-state checks, and the sound synths' timing, pitch and levels. The asset check
regenerates the original builders with a fixed seed and requires byte-for-byte matches for the
geometry, hierarchy, textures, shader resources and sounds.

To refresh visuals and sounds after editing the web model builders, the web's sound builders or the
native shader translation:

```sh
npm run export --prefix visionos/tools
xcodegen generate --spec visionos/project.yml
```

The app icon is rendered from the web scene the same way: the Phalanx mount, the clouds, and the
sky and sea become the Front, Middle and Back layers of `App/Assets.xcassets/AppIcon.solidimagestack`.
The camera, gun pose and cloud placement are in the script. `icon/icon-preview.png` shows the layers
flattened in the headset's circle.

```sh
uv run visionos/tools/render_icon.py
```

To build without booting a simulator:

```sh
xcodebuild -project visionos/CIWSSim.xcodeproj -scheme CIWSSim \
  -destination 'generic/platform=visionOS Simulator' \
  -derivedDataPath /tmp/ciws-visionos-build CODE_SIGNING_ALLOWED=NO build
```

`App/WebVisualAssets.swift` loads/caches the exported meshes and materials; `WebEffects.swift`
updates the native effects; `BattleRenderer.swift` binds simulation state to the scene.
`BattleAudio.swift` owns the original voice queues, drives the synths from the simulation each
frame, and manages their generator entities.

Validated with Xcode 27 SDK builds, Swift tests, native shader loading, reproducible asset exports,
and a muted immersive simulator inspection. Physical-headset comfort, spatial audio and sustained
rendering performance still need headset testing. All simulator devices are shut down after checks.
