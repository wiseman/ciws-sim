# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Record the Seahawk's close pass in zen mode, with its audio, as an mp4: her approach (the
director's cut to her and the pilot on the net), then the mount tracking her without firing while
the crew scold it ("No! Bad!", FLYBY.lock), and her going on her way.

Usage: uv run tools/flyby_video.py OUT.mp4 [width] [height]
A quiet scene (no threats), so the mount is free to take its interest. Records the canvas and the
game's master output (MediaRecorder), as demo_video.py does. Needs ffmpeg on PATH."""
import base64
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _harness import B64_ENCODE_JS, enable_audio, game_page, report_errors, QUIET_SCENE_JS

out = Path(sys.argv[1])
width = int(sys.argv[2]) if len(sys.argv) > 2 else 1280
height = int(sys.argv[3]) if len(sys.argv) > 3 else 720
START, PAST = 430, 170  # m: where she starts (toward abeam), and how far past it the take ends

RECORD_JS = """([start, past]) => new Promise(resolve => {
    const { renderer } = window.__ciws, d = window.__ciws.debug;
    const A = window.__ciwsAudio, said = window.__said = [];
    const play = A.play;
    A.play = function (bucket, ...rest) { said.push([+(performance.now() / 1000).toFixed(1), bucket]); return play.call(this, bucket, ...rest); };
    const audioDest = A.ctx.createMediaStreamDestination();
    A.output.connect(audioDest);
    const stream = new MediaStream([...renderer.domElement.captureStream(60).getVideoTracks(), ...audioDest.stream.getAudioTracks()]);
    const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8,opus', videoBitsPerSecond: 16_000_000, audioBitsPerSecond: 256_000 });
    const chunks = [];
    rec.ondataavailable = e => chunks.push(e.data);
    rec.onstop = () => { window.__clipBlob = new Blob(chunks); resolve(window.__clipBlob.size); };
    rec.start(1000);
    const t0 = performance.now() / 1000;
    d.sight('flyby');
    const s = d.sightings.find(s => s.name === 'flyby');
    s.mesh.position.z = -s.dir * start;
    const timer = setInterval(() => {
        if (s.alive && s.dir * s.mesh.position.z < past) return;
        clearInterval(timer);
        said.forEach(l => l[0] = +(l[0] - t0).toFixed(1));
        rec.stop();
    }, 50);
})"""

SLICE_JS = """async ([start, end]) => {
    %s
    return toBase64(await window.__clipBlob.slice(start, end).arrayBuffer());
}""" % B64_ENCODE_JS

with game_page(width=width, height=height, audio=True) as (page, errors):
    page.add_style_tag(content="#hud, #radar, #zen-exit { display: none !important; }")
    enable_audio(page, load=1.0, settle=2.0)
    page.evaluate("() => toggleZenMode()")
    time.sleep(1.0)
    page.evaluate(QUIET_SCENE_JS, True)
    time.sleep(6.5)  # past the director's minimum shot, so it can cut to her as she's seen
    size = page.evaluate(RECORD_JS, [START, PAST])
    print("lines (s into the take, bucket):", page.evaluate("() => window.__said"))
    data = bytearray()
    step = 8 * 1024 * 1024
    for start in range(0, size, step):
        data += base64.b64decode(page.evaluate(SLICE_JS, [start, min(size, start + step)]))
report_errors(errors)

with tempfile.TemporaryDirectory() as tmp:
    webm = Path(tmp) / "flyby.webm"
    webm.write_bytes(data)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(webm), "-r", "60", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=20", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(out)], check=True)
print("wrote", out)
