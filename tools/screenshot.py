# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Render index.html headlessly and save screenshots for visual checks.

Usage: uv run tools/screenshot.py [out_prefix] [wait_seconds]
Serves the repo root on a local port, loads the page at 2x DPR, and captures
the default orbit view plus a few scripted camera angles.
"""
import http.server, socketserver, sys, threading, time
from functools import partial
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
prefix = sys.argv[1] if len(sys.argv) > 1 else "shot"
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 6

handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
handler.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# name -> (js run before capture, seconds to wait after it)
views = {
    "default": (None, 0),
    "behind": ("camera.position.set(-9, 9, 16); controls.target.set(0, 5, -10);", 0.6),
    "low": ("camera.position.set(-30, 4, 30); controls.target.set(0, 4, 0);", 0.6),
    "high": ("camera.position.set(-60, 60, 80); controls.target.set(0, 0, 0);", 0.6),
    "gun-cam": ("window.toggleCameraFollow();", 1.5),
    "missile-cam": ("window.toggleCameraFollow();", 2.5),
}

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"], headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 760}, device_scale_factor=2)
    logs = []
    pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
    pg.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    pg.goto(f"http://127.0.0.1:{port}/index.html")
    time.sleep(wait)
    for name, (js, delay) in views.items():
        if js:
            pg.evaluate(f"() => {{ const {{camera, controls}} = window.__ciws; {js} controls.update(); }}")
            time.sleep(delay)
        out = f"{prefix}-{name}.png"
        pg.screenshot(path=out)
        print("wrote", out)
    for l in logs:
        if "error" in l.lower() or "warn" in l.lower():
            print(l)
    b.close()
srv.shutdown()
