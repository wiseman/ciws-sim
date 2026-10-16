# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Record a scripted ~30 s demo video of the game, with its audio, as an mp4.

Usage: uv run tools/demo_video.py OUT.mp4 [width] [height]
Records the WebGL canvas plus the master audio output in the page (MediaRecorder), so the sound
is the exact game mix and stays in sync. The HUD is HTML and isn't in the recording.

Shot list (seconds into the recording):
   0-6   third-person view over the mount, looking where the gun is aiming: early drones
   6-11  Phalanx gun camera
  11-15  missile-follow camera
  15-21  low view behind the ship: an anti-ship missile inbound ("vampire" + general alarm),
         a VLS launch toward it, the gun engaging; the wave ramps up
  21-33  static high overview of the whole group: late-wave saturation, a friendly burning,
         more vampires, friendly VLS launches
Needs ffmpeg on PATH for the mp4 conversion.
"""
import base64
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _harness import B64_ENCODE_JS, game_page, report_errors

out = Path(sys.argv[1])
width = int(sys.argv[2]) if len(sys.argv) > 2 else 1920
height = int(sys.argv[3]) if len(sys.argv) > 3 else 1080
DURATION = 33.0
LEAD_IN = 5.0  # game time before recording starts, so the first drones are already inbound

DIRECTOR_JS = """(duration) => new Promise(resolve => {
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

    const shots = [
        [0, () => {
            // Behind and above the mount, looking along the gun toward its first targets
            setCameraMode(0);
            const barrels = scene.getObjectByName('barrels');
            const mount = barrels.getWorldPosition(new T());
            const aim = new T(0, 0, 1).transformDirection(barrels.matrixWorld).setY(0).normalize();
            const side = new T(-aim.z, 0, aim.x);
            const cam = mount.clone().addScaledVector(aim, -12).addScaledVector(side, 2.5).add(new T(0, 3.2, 0));
            const look = mount.clone().addScaledVector(aim, 80).add(new T(0, -1, 0));
            pose(cam.toArray(), look.toArray());
        }],
        [6, () => setCameraMode(1)],
        [11, () => setCameraMode(2)],
        [12.5, () => d.setWave(5)],
        [13.6, () => spawnASCM(VAMPIRE_ANGLE)],
        [15, () => {
            setCameraMode(0);
            const cam = dir.clone().multiplyScalar(-36).add(new T(-8, 12, 5));
            const look = dir.clone().multiplyScalar(70).add(new T(0, 6, 0));
            pose(cam.toArray(), look.toArray());
        }],
        [16.6, () => d.launchVLS('ship', bearingOf(VAMPIRE_ANGLE))],
        [18, () => d.setWave(11)],
        [19, () => d.wreckFriendly(1)],
        [21, () => pose([-120, 78, 95], [45, 0, -5])],
        [21.3, () => spawnASCM(2.4, 2)],
        [22.6, () => d.launchVLS(0, null)],
        [24.5, () => spawnASCM(5.2)],
        [26.2, () => d.launchVLS(3, null)],
        [27.5, () => spawnASCM(1.2, 4)],
        [28.4, () => d.launchVLS('ship', null)],
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

    rec.start(1000);
    for (const [at, action] of shots) setTimeout(action, at * 1000);
    setTimeout(() => rec.stop(), duration * 1000);
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
    size = page.evaluate(DIRECTOR_JS, DURATION)
    data = bytearray()
    step = 8 * 1024 * 1024
    for start in range(0, size, step):
        data += base64.b64decode(page.evaluate(SLICE_JS, [start, min(size, start + step)]))
report_errors(errors)

with tempfile.TemporaryDirectory() as tmp:
    webm = Path(tmp) / "demo.webm"
    webm.write_bytes(data)
    # Constant 60 fps for players that dislike variable-rate webm; loudness-normalized AAC audio
    # (the game mix runs hot, near -12 LUFS, and its peaks overshoot once encoded)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(webm), "-r", "60", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "256k",
                    "-movflags", "+faststart", str(out)], check=True)
print("wrote", out)
