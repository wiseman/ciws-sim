# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Play the game headlessly with audio on and record the master output.

Usage: uv run tools/audio_capture.py <out.webm> [seconds] [camera] [slowmo]
camera: orbit (default) | gun | missile; pass "slowmo" as the 4th argument for slow motion
Also prints any page errors. Convert/inspect with ffmpeg afterwards.
"""
import base64, http.server, socketserver, sys, threading, time
from functools import partial
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
out = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 20
camera = sys.argv[3] if len(sys.argv) > 3 else "orbit"
slowmo = len(sys.argv) > 4 and sys.argv[4] == "slowmo"

handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
handler.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist",
                                "--autoplay-policy=no-user-gesture-required"])
    pg = b.new_page(viewport={"width": 1280, "height": 760})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
    pg.goto(f"http://127.0.0.1:{port}/index.html")
    time.sleep(1.5)
    pg.mouse.click(640, 600)          # first gesture initializes audio
    pg.click("#audio-toggle")          # unmute
    if camera in ("gun", "missile"):
        pg.click("#camera-toggle")
    if camera == "missile":
        pg.click("#camera-toggle")
    if slowmo:
        pg.click("#slowmo-toggle")
    pg.evaluate(f"""() => new Promise(resolve => {{
        const A = window.__ciwsAudio;
        const dest = A.ctx.createMediaStreamDestination();
        A.output.connect(dest);
        const rec = new MediaRecorder(dest.stream, {{ mimeType: 'audio/webm;codecs=opus', audioBitsPerSecond: 192000 }});
        const chunks = [];
        rec.ondataavailable = e => chunks.push(e.data);
        rec.onstop = async () => {{
            const buf = await new Blob(chunks).arrayBuffer();
            let bin = ''; const bytes = new Uint8Array(buf);
            for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
            window.__rec = btoa(bin);
            resolve();
        }};
        rec.start();
        setTimeout(() => rec.stop(), {seconds * 1000});
    }})""")
    Path(out).write_bytes(base64.b64decode(pg.evaluate("() => window.__rec")))
    print("wrote", out)
    for e in errors:
        print("ERROR:", e)
    b.close()
srv.shutdown()
