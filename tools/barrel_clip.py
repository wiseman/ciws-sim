# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Record a short close-up clip of the gun spinning up and firing, with its audio, as an mp4.

Usage: uv run tools/barrel_clip.py OUT.mp4 [width] [height] [--keep-webm]
Idles the gun, then sends in a wave and records the canvas plus the game's master audio output
(MediaRecorder, as in demo_video.py). The cuts are timed from the moment the barrels start to
spin, and the take is trimmed to start just before it:
   0-3 s  close side view of the barrels: spin-up and the first bursts
   3-6 s  close three-quarter front view of the muzzles
   6-8 s  Phalanx gun camera (over the shoulder)
Needs ffmpeg on PATH. --keep-webm also saves the raw (untrimmed) recording as OUT.webm.
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
PRE_ROLL = 0.6           # seconds kept before the barrels start to spin
SHOTS = [3.0, 3.0, 2.0]  # side, front, gun camera
LENGTH = sum(SHOTS)

# Resolves with [recording size, seconds into the recording that the trimmed clip starts]
DIRECTOR_JS = """([preRoll, shots]) => new Promise(resolve => {
    const { scene, camera, renderer } = window.__ciws;
    const d = window.__ciws.debug;
    const T = camera.position.constructor;
    const b = scene.getObjectByName('barrels');
    const blur = b.children.find(c => c.material && c.material.uniforms && c.material.uniforms.uSweep);

    // Close views that ride along with the turret, posed just before every render
    const pose = shot => {
        b.updateWorldMatrix(true, false);
        const mid = new T(0, 0, 2.5).applyMatrix4(b.matrixWorld);
        const tip = new T(0, 0, 3.5).applyMatrix4(b.matrixWorld);
        const axis = tip.clone().sub(mid).normalize();
        const side = new T(0, 1, 0).cross(axis).normalize();
        if (shot === 0) {
            camera.position.copy(mid).addScaledVector(side, 3.4).add(new T(0, 0.9, 0));
            camera.lookAt(mid.clone().addScaledVector(axis, 0.5));
        } else {
            camera.position.copy(tip).addScaledVector(axis, 2.6).addScaledVector(side, 1.3).add(new T(0, 0.5, 0));
            camera.lookAt(tip.clone().addScaledVector(axis, -0.5));
        }
    };

    let spinAt = null, shot = 0;
    const render = renderer.render.bind(renderer);
    renderer.render = (s, c) => {
        if (spinAt === null && blur.material.uniforms.uSweep.value > 0) spinAt = performance.now();
        if (shot < 2) pose(shot);
        render(s, c);
    };

    const A = window.__ciwsAudio;
    const audioDest = A.ctx.createMediaStreamDestination();
    A.output.connect(audioDest);
    const stream = new MediaStream([
        ...renderer.domElement.captureStream(60).getVideoTracks(),
        ...audioDest.stream.getAudioTracks(),
    ]);
    const rec = new MediaRecorder(stream, {
        mimeType: 'video/webm;codecs=vp8,opus',
        videoBitsPerSecond: 16_000_000,
        audioBitsPerSecond: 256_000,
    });
    const chunks = [];
    rec.ondataavailable = e => chunks.push(e.data);
    let t0;
    rec.onstop = () => {
        window.__clipBlob = new Blob(chunks);
        resolve([window.__clipBlob.size, (spinAt - t0) / 1000 - preRoll]);
    };

    const wait = seconds => new Promise(r => setTimeout(r, seconds * 1000));
    (async () => {
        rec.start(1000);
        t0 = performance.now();
        await wait(preRoll + 0.4);  // the first threat can draw fire almost at once
        d.setWave(6);
        d.resumeSpawns();
        while (spinAt === null) {
            if (performance.now() - t0 > 40000) { rec.stop(); return; }
            await wait(0.01);
        }
        const at = seconds => wait(Math.max(0, (spinAt + seconds * 1000 - performance.now()) / 1000));
        await at(shots[0] - preRoll);
        shot = 1;
        await at(shots[0] + shots[1] - preRoll);
        shot = 2;
        window.toggleCameraFollow();  // gun camera
        await at(shots[0] + shots[1] + shots[2] - preRoll + 0.3);
        rec.stop();
    })();
})"""

SLICE_JS = """async ([start, end]) => {
    %s
    return toBase64(await window.__clipBlob.slice(start, end).arrayBuffer());
}""" % B64_ENCODE_JS

IDLE_JS = """() => {
    const b = window.__ciws.scene.getObjectByName('barrels');
    const blur = b.children.find(c => c.material && c.material.uniforms && c.material.uniforms.uSweep);
    return blur.material.uniforms.uSweep.value === 0;
}"""

with game_page(width=width, height=height,
               extra_args=["--autoplay-policy=no-user-gesture-required"]) as (page, errors):
    page.add_style_tag(content="#hud, #radar, #ml-panel { display: none !important; }")
    time.sleep(1.0)
    page.mouse.click(width // 2, int(height * 0.8))  # first gesture initializes audio
    page.evaluate("() => { window.toggleMute(); }")
    # Quiet the gun down so the take catches a spin-up from rest
    page.evaluate("() => { const d = window.__ciws.debug; d.holdSpawns(); d.clearThreats(); }")
    deadline = time.time() + 20
    while time.time() < deadline and not page.evaluate(IDLE_JS):
        time.sleep(0.05)
    time.sleep(0.5)
    size, start = page.evaluate(DIRECTOR_JS, [PRE_ROLL, SHOTS])
    data = bytearray()
    step = 8 * 1024 * 1024
    for i in range(0, size, step):
        data += base64.b64decode(page.evaluate(SLICE_JS, [i, min(size, i + step)]))
report_errors(errors)
if start != start:  # NaN: the gun never fired
    sys.exit("the barrels never spun up")

with tempfile.TemporaryDirectory() as tmp:
    webm = out.with_suffix(".webm") if keep_webm else Path(tmp) / "clip.webm"
    webm.write_bytes(data)
    trim = ["-ss", f"{max(0.0, start):.3f}", "-t", f"{LENGTH:.3f}"]
    # Two-pass loudness normalization of the trimmed take: measure, then one fixed gain
    LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=20"
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(webm), *trim, "-vn",
                            "-af", LOUDNORM + ":print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, check=True).stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    measured = (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(webm), *trim, "-r", "60", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-af", LOUDNORM + measured, "-ar", "48000", "-c:a", "aac", "-b:a", "256k",
                    "-movflags", "+faststart", str(out)], check=True)
print("wrote", out, f"(trimmed from {start:.2f} s into the recording)")
