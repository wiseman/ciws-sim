# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Trigger each explosion kind in front of a fixed camera and capture a timed sequence.

Usage: uv run tools/explosion_shot.py <out_prefix> [scenario]
Scenarios: airburst (default), water, deck, flak
"""
import http.server, socketserver, sys, threading, time
from functools import partial
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
out = sys.argv[1]
scenario = sys.argv[2] if len(sys.argv) > 2 else "airburst"

SCENARIOS = {
    "airburst": ("c.camera.position.set(-9, 9, 16); c.controls.target.set(0, 14, -25);",
                 "c.createExplosion(new V(0, 16, -32), 2.0);"),
    "water": ("c.camera.position.set(-20, 8, 20); c.controls.target.set(-25, 3, -25);",
              "c.createExplosion(new V(-25, 0.75, -30), 1);"),
    "deck": ("c.camera.position.set(-22, 12, 22); c.controls.target.set(0, 3, 0);",
             "c.createExplosion(new V(0, 2, 0), 1);"),
    "flak": ("c.camera.position.set(-9, 9, 16); c.controls.target.set(0, 14, -25);",
             "for (let i = 0; i < 12; i++) c.createExplosion(new V(-8 + i * 1.6, 12 + Math.sin(i) * 3, -30 - i), 0.35, {playSound: false, kind: 'flak'});"
             " for (let i = 0; i < 3; i++) c.createExplosion(new V(6 + i * 3, 16, -28), 0.5);"),
}
cam_js, boom_js = SCENARIOS[scenario]

handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
handler.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1280, "height": 760}, device_scale_factor=2)
    logs = []
    pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
    pg.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    pg.goto(f"http://127.0.0.1:{port}/index.html")
    time.sleep(4)
    # Hide the HUD so the frames show only the scene
    pg.evaluate("() => { document.getElementById('hud').style.display = 'none'; }")
    pg.evaluate(f"() => {{ const c = window.__ciws; const V = c.camera.position.constructor; {cam_js} c.controls.update(); }}")
    time.sleep(0.3)
    start = time.time()
    pg.evaluate(f"() => {{ const c = window.__ciws; const V = c.camera.position.constructor; {boom_js} }}")
    for t in (0.05, 0.15, 0.35, 0.7, 1.3, 2.5):
        time.sleep(max(0, t - (time.time() - start)))
        pg.screenshot(path=f"{out}-{scenario}-{t:.2f}.png")
        print("wrote", f"{out}-{scenario}-{t:.2f}.png")
    for l in logs:
        if "error" in l.lower() or "warn" in l.lower():
            print(l)
    b.close()
srv.shutdown()
