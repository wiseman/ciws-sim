# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Record a short close-up clip of the gun spinning up and firing, with its audio, as an mp4.

Usage: uv run tools/barrel_clip.py OUT.mp4 [width] [height] [--keep-webm]
Waits for the gun to come to rest, lets the threats in, and cuts on the moment the barrels start
to turn: about 3 s from the side of the barrels, then 3 s from in front of the muzzle and off to
one side, then 2 s on the Phalanx gun camera, cut in on the next burst (the gun often pauses
between targets, so that shot is spliced on from wherever the burst lands). The close cameras
ride with the gun, so they stay on it as it slews. Records the WebGL canvas plus the master audio
output in the page (MediaRecorder), keeps the two spans, and converts to 60 fps h264/aac with
two-pass loudness normalization. Needs ffmpeg on PATH. --keep-webm also saves the raw recording
as OUT.webm. 1080p recordings dropped most frames here, hence the 720p default.
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
width = int(argv[2]) if len(argv) > 2 else 1280
height = int(argv[3]) if len(argv) > 3 else 720
PRE_ROLL = 0.5                   # seconds kept before the barrels start to turn
SHOTS = [("side", 2.6), ("front", 3.0)]  # close cameras, seconds from the spin-up on
GUN_SHOT = 2.0                   # seconds on the gun camera, from the next burst

DIRECTOR_JS = """async ([shots, gunShot]) => {
    const { scene, camera, controls, renderer } = window.__ciws;
    const d = window.__ciws.debug;
    const T = camera.position.constructor;
    const wait = seconds => new Promise(r => setTimeout(r, seconds * 1000));

    // Let the close cameras sit nearer the gun and look up at it
    controls.minDistance = 0;
    controls.maxPolarAngle = Math.PI;

    // Quiet start: no threats, barrels at rest
    d.holdSpawns();
    d.clearThreats();
    while (d.barrelSpeed > 0) await wait(0.05);

    // Close cameras fixed to the gun (they ride its traverse and elevation), posed just before each
    // render. 'gun' is the game's own Phalanx camera.
    let view = 'side';
    const b = scene.getObjectByName('barrels');
    const render = renderer.render.bind(renderer);
    renderer.render = (sc, cam) => {
        if (view !== 'gun') {
            b.updateWorldMatrix(true, false);
            const mid = new T(0, 0, 2.4).applyMatrix4(b.matrixWorld);
            const tip = new T(0, 0, 3.5).applyMatrix4(b.matrixWorld);
            const axis = tip.clone().sub(mid).normalize();
            const side = new T(0, 1, 0).cross(axis).normalize();
            const up = axis.clone().cross(side).normalize();
            const [pos, look] = view === 'side'
                ? [mid.clone().addScaledVector(side, 2.7).addScaledVector(up, 0.7), mid.clone().addScaledVector(axis, 0.4)]
                : [tip.clone().addScaledVector(axis, 2.8).addScaledVector(side, 1.7).addScaledVector(up, 0.5),
                   tip.clone().addScaledVector(axis, 0.6)];
            cam.position.copy(pos);
            controls.target.copy(look);
            cam.lookAt(look);
        }
        render(sc, cam);
    };

    // Record the canvas and the game's master output together
    const A = window.__ciwsAudio;
    const audioDest = A.ctx.createMediaStreamDestination();
    A.output.connect(audioDest);
    const stream = new MediaStream([
        ...renderer.domElement.captureStream(60).getVideoTracks(),
        ...audioDest.stream.getAudioTracks(),
    ]);
    const rec = new MediaRecorder(stream, {
        mimeType: 'video/webm;codecs=vp8,opus',
        videoBitsPerSecond: 20_000_000,
        audioBitsPerSecond: 256_000,
    });
    const chunks = [];
    rec.ondataavailable = e => chunks.push(e.data);
    const stopped = new Promise(r => { rec.onstop = r; });

    const t0 = performance.now();
    rec.start(1000);
    await wait(0.4);
    // A heavy wave, so the gun keeps finding targets for the whole take, plus anti-ship missiles
    // (~4.5 s from spawn to the gun's reach) to keep it firing through the later shots
    d.setWave(16);
    d.resumeSpawns();
    [0, 1.5, 3].forEach(at => setTimeout(() => d.spawnAntiShipMissile(), at * 1000));
    while (d.barrelSpeed === 0) await new Promise(r => requestAnimationFrame(r));
    const spinUp = (performance.now() - t0) / 1000;
    for (const [name, seconds] of shots) {
        view = name;
        await wait(seconds);
    }
    // Cut to the gun camera on a burst: the first frame a round leaves (or a 6 s timeout)
    const rounds = () => d.stats.engagementStats.classic.rounds + d.stats.engagementStats.neural.rounds;
    const before = rounds(), deadline = performance.now() + 6000;
    while (rounds() === before && performance.now() < deadline) await new Promise(r => requestAnimationFrame(r));
    window.toggleCameraFollow(); // OFF -> PHALANX
    view = 'gun';
    const gunStart = (performance.now() - t0) / 1000;
    await wait(gunShot);
    rec.stop();
    await stopped;
    renderer.render = render;
    window.__clipBlob = new Blob(chunks);
    return { size: window.__clipBlob.size, spinUp, gunStart };
}"""

# Pull the recording out in slices (one huge evaluate result is slow and memory-hungry)
SLICE_JS = """async ([start, end]) => {
    %s
    return toBase64(await window.__clipBlob.slice(start, end).arrayBuffer());
}""" % B64_ENCODE_JS

with game_page(width=width, height=height,
               extra_args=["--autoplay-policy=no-user-gesture-required"]) as (page, errors):
    page.add_style_tag(content="#hud, #radar { display: none !important; }")
    time.sleep(1.0)
    page.mouse.click(width // 2, int(height * 0.8))  # first gesture initializes audio
    page.evaluate("() => { window.toggleMute(); }")
    time.sleep(2.0)
    result = page.evaluate(DIRECTOR_JS, [SHOTS, GUN_SHOT])
    size = result["size"]
    data = bytearray()
    step = 8 * 1024 * 1024
    for start in range(0, size, step):
        data += base64.b64decode(page.evaluate(SLICE_JS, [start, min(size, start + step)]))
report_errors(errors)

# The close-up span from just before the spin-up, then the gun camera span
start = max(0.0, result["spinUp"] - PRE_ROLL)
spans = [(start, result["spinUp"] + sum(sec for _, sec in SHOTS)),
         (result["gunStart"], result["gunStart"] + GUN_SHOT)]
print(f"spin-up at {result['spinUp']:.2f} s, gun camera at {result['gunStart']:.2f} s; keeping "
      + ", ".join(f"{a:.2f}-{b:.2f}" for a, b in spans))
n = len(spans)
graph = f"[0:v]split={n}" + "".join(f"[sv{i}]" for i in range(n)) + f";[0:a]asplit={n}" + "".join(f"[sa{i}]" for i in range(n)) + ";"
graph += "".join(f"[sv{i}]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}];"
                 f"[sa{i}]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[a{i}];" for i, (a, b) in enumerate(spans))
graph += "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][joined]"

with tempfile.TemporaryDirectory() as tmp:
    webm = out.with_suffix(".webm") if keep_webm else Path(tmp) / "clip.webm"
    webm.write_bytes(data)
    # Two-pass loudness normalization: measure the kept spans, then apply one fixed gain (linear)
    LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=20"
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(webm), "-filter_complex",
                            graph + ";[joined]" + LOUDNORM + ":print_format=json[a]",
                            "-map", "[v]", "-map", "[a]", "-f", "null", "-"],
                           capture_output=True, text=True, check=True).stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    measured = (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(webm),
                    "-filter_complex", graph + ";[joined]" + LOUDNORM + measured + "[a]",
                    "-map", "[v]", "-map", "[a]", "-r", "60", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
                    "-ar", "48000", "-c:a", "aac", "-b:a", "256k",
                    "-movflags", "+faststart", str(out)], check=True)
print("wrote", out)
