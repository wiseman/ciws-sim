# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Play the game headlessly with audio on and record the master output.

Usage: uv run tools/audio_capture.py <out.webm> [seconds] [camera] [slowmo] [--vampire]
camera: orbit (default) | gun | missile; pass "slowmo" as the 4th argument for slow motion
--vampire: spawns an anti-ship missile at the start (general alarm + "vampire" callout once it's
detected) and a VLS launch from our ship 6 s in; recording starts when the radar picks it up
Also prints any page errors. Convert/inspect with ffmpeg afterwards.
"""
import base64
import sys
from pathlib import Path

from _harness import B64_ENCODE_JS, enable_audio, game_page, report_errors

vampire = "--vampire" in sys.argv
argv = [a for a in sys.argv if a != "--vampire"]
out = argv[1]
seconds = float(argv[2]) if len(argv) > 2 else 20
camera = argv[3] if len(argv) > 3 else "orbit"
slowmo = len(argv) > 4 and argv[4] == "slowmo"

with game_page(audio=True) as (page, errors):
    enable_audio(page, settle=0)
    for _ in range({"orbit": 0, "gun": 1, "missile": 2}[camera]):
        page.click("#camera-toggle")
    if slowmo:
        page.click("#slowmo-toggle")
    if vampire:
        # Start recording as the radar picks the missile up (the alarm and callout go out then)
        page.evaluate("""() => new Promise(resolve => {
            const d = window.__ciws.debug;
            const m = d.spawnAntiShipMissile();
            setTimeout(() => d.launchVLS('ship', 90), 6000);
            const poll = setInterval(() => { if (m.detected) { clearInterval(poll); resolve(); } }, 20);
        })""")
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
    print("audio state:", page.evaluate("() => ({ mode: window.__ciwsAudio.spatialMode, nearMisses: window.__ciwsAudio.debugState.threats.nearMisses, oneShots: window.__ciwsAudio.activeOneShots, cic: window.__ciwsAudio.debugState.cic })"))
report_errors(errors)
