# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Play the game headlessly with audio on and record the master output.

Usage: uv run tools/audio_capture.py <out.webm> [seconds] [camera] [slowmo]
camera: orbit (default) | gun | missile; pass "slowmo" as the 4th argument for slow motion
Also prints any page errors. Convert/inspect with ffmpeg afterwards.
"""
import base64
import sys
import time
from pathlib import Path

from _harness import B64_ENCODE_JS, game_page, report_errors

out = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 20
camera = sys.argv[3] if len(sys.argv) > 3 else "orbit"
slowmo = len(sys.argv) > 4 and sys.argv[4] == "slowmo"

with game_page(extra_args=["--autoplay-policy=no-user-gesture-required"]) as (page, errors):
    time.sleep(1.5)
    page.mouse.click(640, 600)          # first gesture initializes audio
    page.click("#audio-toggle")          # unmute
    for _ in range({"orbit": 0, "gun": 1, "missile": 2}[camera]):
        page.click("#camera-toggle")
    if slowmo:
        page.click("#slowmo-toggle")
    encoded = page.evaluate(f"""() => new Promise(resolve => {{
        {B64_ENCODE_JS}
        const A = window.__ciwsAudio;
        const dest = A.ctx.createMediaStreamDestination();
        A.output.connect(dest);
        const rec = new MediaRecorder(dest.stream, {{ mimeType: 'audio/webm;codecs=opus', audioBitsPerSecond: 192000 }});
        const chunks = [];
        rec.ondataavailable = e => chunks.push(e.data);
        rec.onstop = async () => resolve(toBase64(await new Blob(chunks).arrayBuffer()));
        rec.start();
        setTimeout(() => rec.stop(), {seconds * 1000});
    }})""")
    Path(out).write_bytes(base64.b64decode(encoded))
    print("wrote", out)
    print("audio state:", page.evaluate("() => ({ mode: window.__ciwsAudio.spatialMode, nearMisses: window.__ciwsAudio.debugState.threats.nearMisses, oneShots: window.__ciwsAudio.activeOneShots })"))
report_errors(errors)
