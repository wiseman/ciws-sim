# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Record a scripted ~30 s demo video of the game, with its audio, as an mp4.

Usage: uv run tools/demo_video.py OUT.mp4 [width] [height] [--keep-webm]
Records the WebGL canvas plus the master audio output in the page (MediaRecorder), so the sound
is the exact game mix and stays in sync. The HUD is HTML and isn't in the recording.

Shot list (seconds into the recording):
   0-5.5 third-person view of the whole gun mount from behind its line of fire: early drones
   5.5-10 Phalanx gun camera
  10-13.5 missile-follow camera (new spawns pause here so the gun is free for the vampire)
  13.5-  low view behind the ship, looking down the threat axis: an anti-ship missile inbound
         ("vampire" + general alarm), a VLS launch
  ~3 s   split screen as the vampire closes: a gunsight view down the barrels on the left, a
         chase camera behind the missile on the right, held a beat past the kill; spawns resume
  then   ~12 s static high overview of the whole group: late-wave saturation, a friendly hit
         and burning, more vampires, friendly VLS launches. Anti-ship missiles are staggered so
         the gun is still killing them at the end, and the take ends a beat after the last kill.
Total length is about 32 s; it varies by a second or so with when the kills land.
Needs ffmpeg on PATH for the mp4 conversion. --keep-webm also saves the raw recording as OUT.webm.
"""
import base64
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _harness import B64_ENCODE_JS, game_page, report_errors

keep_webm = "--keep-webm" in sys.argv
argv = [a for a in sys.argv if a != "--keep-webm"]
out = Path(argv[1])
width = int(argv[2]) if len(argv) > 2 else 1920
height = int(argv[3]) if len(argv) > 3 else 1080
OVERVIEW_MIN, OVERVIEW_MAX = 10.5, 14.0  # the overview ends a beat after its last kill
LEAD_IN = 5.0  # game time before recording starts, so the first drones are already inbound

DIRECTOR_JS = """([minSeconds, maxSeconds]) => new Promise(resolve => {
    const { scene, camera, controls, renderer } = window.__ciws;
    const d = window.__ciws.debug;
    const T = camera.position.constructor;

    // The orbit controls won't look up at their target (maxPolarAngle keeps the camera above the
    // water), so every pose keeps its target below the camera or the controls move the camera
    const pose = (pos, target) => {
        if (window.__ciwsCameraMode()) return;
        camera.position.set(...pos);
        controls.target.set(...target);
        controls.update();
    };
    const setCameraMode = mode => { while (window.__ciwsCameraMode() !== mode) window.toggleCameraFollow(); };

    // An anti-ship missile from a chosen direction (angle in radians, x = cos, z = sin)
    const spawnASCM = (angle, friendlyIndex = null) => {
        const random = Math.random;
        Math.random = () => angle / (Math.PI * 2);
        try { return d.spawnAntiShipMissile(friendlyIndex); } finally { Math.random = random; }
    };
    // Bearing clockwise from our bow (-z), as the VLS and callouts use it
    const bearingOf = angle => ((Math.atan2(Math.cos(angle), -Math.sin(angle)) * 180 / Math.PI) + 360) % 360;

    const VAMPIRE_ANGLE = 0.35;            // off the starboard bow, toward the camera's right
    const dir = new T(Math.cos(VAMPIRE_ANGLE), 0, Math.sin(VAMPIRE_ANGLE));

    const wait = seconds => new Promise(r => setTimeout(r, seconds * 1000));
    const timeline = (events, from = 0) => events.forEach(([at, action]) => setTimeout(action, (at - from) * 1000));

    const openingAndVampire = [
        [0, () => {
            // Behind and off to the side of the mount relative to where the gun is aiming, so the
            // whole turret is in frame with its line of fire running out into the sky
            setCameraMode(0);
            const barrels = scene.getObjectByName('barrels');
            const mount = barrels.getWorldPosition(new T());
            const aim = new T(0, 0, 1).transformDirection(barrels.matrixWorld).setY(0).normalize();
            const side = new T(-aim.z, 0, aim.x);
            const cam = mount.clone().addScaledVector(aim, -11).addScaledVector(side, 9).add(new T(0, 4, 0));
            const look = mount.clone().addScaledVector(aim, 5).add(new T(0, 1.5, 0));
            pose(cam.toArray(), look.toArray());
        }],
        [5.5, () => setCameraMode(1)],
        [10, () => setCameraMode(2)],
        [10.5, () => { d.setWave(5); d.holdSpawns(); }],
        [12.5, () => { window.__vampire = spawnASCM(VAMPIRE_ANGLE); }],
        [13.5, () => {
            setCameraMode(0);
            const cam = dir.clone().multiplyScalar(-36).add(new T(-8, 12, 5));
            const look = dir.clone().multiplyScalar(70).add(new T(0, 6, 0));
            pose(cam.toArray(), look.toArray());
        }],
        [15.3, () => d.launchVLS('ship', bearingOf(VAMPIRE_ANGLE))],
    ];

    // Split screen: a gunsight view down the barrels on the left half, a chase camera behind the
    // vampire on the right. The chase camera holds its last pose once the missile is gone, to watch
    // the kill. The gunsight rides the gun block (the barrels themselves spin).
    const chase = new camera.constructor(60, 1, 0.25, 4000);
    const sight = new camera.constructor(45, 1, 0.25, 4000);
    const gunBlock = scene.getObjectByName('barrels').parent;
    const SIGHT_EYE = new T(0, 0.95, 0.6), SIGHT_AHEAD = new T(0, 0.95, 200);
    const SHIP = new T(0, 4, 0);
    const updateSight = () => {
        gunBlock.updateWorldMatrix(true, false);
        sight.position.copy(SIGHT_EYE).applyMatrix4(gunBlock.matrixWorld);
        sight.lookAt(SIGHT_AHEAD.clone().applyMatrix4(gunBlock.matrixWorld));
    };
    const updateChase = () => {
        const m = window.__vampire;
        if (!d.missiles.includes(m)) return;
        const pos = m.mesh.position;
        const back = pos.clone().sub(SHIP).setY(0).normalize();
        chase.position.copy(pos).addScaledVector(back, 9).add(new T(0, 2.6, 0));
        chase.lookAt(SHIP);
    };
    let split = false;
    const render = renderer.render.bind(renderer);
    renderer.render = (sc, cam) => {
        if (!split) return render(sc, cam);
        updateChase();
        updateSight();
        const size = renderer.getSize(new T());
        const half = size.x / 2, gap = 3;
        // The sky dome is re-centered on the main camera each frame; move it with the chase view
        const sky = sc.children.find(o => o.isMesh && o.position.equals(cam.position));
        renderer.setScissorTest(true);
        renderer.setScissor(0, 0, size.x, size.y);
        renderer.setClearColor(0x101418);
        renderer.clear();
        sight.aspect = chase.aspect = (half - gap) / size.y;
        sight.updateProjectionMatrix();
        chase.updateProjectionMatrix();
        if (sky) sky.position.copy(sight.position);
        renderer.setViewport(0, 0, half - gap, size.y);
        renderer.setScissor(0, 0, half - gap, size.y);
        render(sc, sight);
        if (sky) sky.position.copy(chase.position);
        renderer.setViewport(half + gap, 0, half - gap, size.y);
        renderer.setScissor(half + gap, 0, half - gap, size.y);
        render(sc, chase);
        if (sky) sky.position.copy(cam.position);
        renderer.setViewport(0, 0, size.x, size.y);
        renderer.setScissorTest(false);
    };
    // Anti-ship missiles take ~7 s from spawn to the kill zone, so these keep the gun busy to the end
    const finale = [];
    const finaleASCM = (angle, friendlyIndex = null) => () => finale.push(spawnASCM(angle, friendlyIndex));
    const overview = [
        [0, () => pose([-120, 78, 95], [45, 0, -5])],
        [0.4, () => d.wreckFriendly(1)],
        [0.8, finaleASCM(2.4, 2)],
        [1.8, () => d.launchVLS(0, null)],
        [2.6, finaleASCM(5.2)],
        [3.6, finaleASCM(1.2, 4)],
        [4.6, () => d.launchVLS(3, null)],
        [5.0, finaleASCM(3.7)],
        [6.0, finaleASCM(0.6)],
        [7.0, () => d.launchVLS('ship', null)],
    ];

    // Record the canvas and the game's master output together
    const A = window.__ciwsAudio;
    const audioDest = A.ctx.createMediaStreamDestination();
    A.output.connect(audioDest);
    const stream = new MediaStream([
        ...renderer.domElement.captureStream(60).getVideoTracks(),
        ...audioDest.stream.getAudioTracks(),
    ]);
    const rec = new MediaRecorder(stream, {
        mimeType: 'video/webm;codecs=vp8,opus',  // vp8: cheaper to encode live than vp9
        videoBitsPerSecond: 16_000_000,
        audioBitsPerSecond: 256_000,
    });
    const chunks = [];
    rec.ondataavailable = e => chunks.push(e.data);
    rec.onstop = () => { window.__demoBlob = new Blob(chunks); resolve(window.__demoBlob.size); };

    (async () => {
        const t0 = performance.now();
        rec.start(1000);
        timeline(openingAndVampire);
        // Cut to the split screen as the vampire closes; hold it a beat past the kill
        await wait(14);
        const deadline = t0 + 23000;
        const alive = () => d.missiles.includes(window.__vampire);
        while (alive() && window.__vampire.mesh.position.length() > 520 && performance.now() < deadline) await wait(0.02);
        setCameraMode(1);   // the audio listener rides with the gun camera
        split = true;
        d.setWave(11);
        d.resumeSpawns();   // new threats are ~7 s out, so they don't distract the gun yet
        while (alive() && performance.now() < deadline) await wait(0.02);
        await wait(1.4);
        split = false;
        setCameraMode(0);
        const overviewStart = performance.now();
        timeline(overview);
        // End a beat after the last finale missile is shot down (or gets through)
        await wait(minSeconds);
        const end = overviewStart + maxSeconds * 1000;
        while (finale.some(m => d.missiles.includes(m)) && performance.now() < end - 1000) await wait(0.05);
        await wait(Math.min(1.0, Math.max(0, (end - performance.now()) / 1000)));
        rec.stop();
    })();
})"""

# Pull the recording out in slices (one huge evaluate result is slow and memory-hungry)
SLICE_JS = """async ([start, end]) => {
    %s
    return toBase64(await window.__demoBlob.slice(start, end).arrayBuffer());
}""" % B64_ENCODE_JS

with game_page(width=width, height=height,
               extra_args=["--autoplay-policy=no-user-gesture-required"]) as (page, errors):
    # Expose the camera mode for the director, hide the HTML overlays (they aren't recorded anyway)
    page.add_style_tag(content="#hud, #radar { display: none !important; }")
    time.sleep(1.0)
    page.mouse.click(width // 2, int(height * 0.8))  # first gesture initializes audio
    page.evaluate("() => { window.toggleMute(); }")
    page.evaluate("""() => {
        let mode = 0;
        const toggle = window.toggleCameraFollow;
        window.toggleCameraFollow = () => { mode = (mode + 1) % 3; toggle(); };
        window.__ciwsCameraMode = () => mode;
    }""")
    time.sleep(LEAD_IN)
    size = page.evaluate(DIRECTOR_JS, [OVERVIEW_MIN, OVERVIEW_MAX])
    data = bytearray()
    step = 8 * 1024 * 1024
    for start in range(0, size, step):
        data += base64.b64decode(page.evaluate(SLICE_JS, [start, min(size, start + step)]))
report_errors(errors)

with tempfile.TemporaryDirectory() as tmp:
    webm = out.with_suffix(".webm") if keep_webm else Path(tmp) / "demo.webm"
    webm.write_bytes(data)
    # Two-pass loudness normalization: measure, then apply one fixed gain (linear mode). Single-pass
    # loudnorm rides the gain dynamically and audibly pulled the last seconds down.
    LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=20"
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(webm), "-vn",
                            "-af", LOUDNORM + ":print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, check=True).stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    measured = (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    # Constant 60 fps for players that dislike variable-rate webm
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(webm), "-r", "60", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-af", LOUDNORM + measured, "-ar", "48000", "-c:a", "aac", "-b:a", "256k",
                    "-movflags", "+faststart", str(out)], check=True)
print("wrote", out)
