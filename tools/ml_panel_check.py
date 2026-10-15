# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Walk through the fire-control/learning workflow and screenshot the dock.

Usage: uv run tools/ml_panel_check.py <out_prefix>
"""
import http.server, socketserver, sys, threading, time
from functools import partial
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
out = sys.argv[1]
handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
handler.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

STATE = """() => ({
    mode: document.getElementById('ml-chip-mode').textContent,
    chip: document.getElementById('ml-chip-learn').textContent,
    status: document.getElementById('status-text').textContent,
    learn: document.getElementById('ml-learn-state').textContent,
    trainBtn: document.getElementById('ml-train-btn').textContent,
    neuralDisabled: document.getElementById('ml-neural-btn').disabled,
    steps: document.getElementById('ml-steps').textContent,
    loss: document.getElementById('ml-loss').textContent,
    aim: document.getElementById('ml-aim-error').textContent,
    agree: document.getElementById('ml-fire-agree').textContent,
    classic: document.getElementById('ml-perf-classic').innerText.replace(/\\s+/g, ' '),
    neural: document.getElementById('ml-perf-neural').innerText.replace(/\\s+/g, ' '),
    saved: document.getElementById('ml-saved').textContent,
    open: document.getElementById('ml-panel').classList.contains('open')
})"""

def human_click(pg, sel):
    pg.locator(sel).scroll_into_view_if_needed()
    box = pg.locator(sel).bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down(); time.sleep(0.1); pg.mouse.up(); time.sleep(0.3)

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"])
    ctx = b.new_context(viewport={"width": 1280, "height": 760}, device_scale_factor=2)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    url = f"http://127.0.0.1:{port}/index.html"
    pg.goto(url); time.sleep(2.5)
    print("1 fresh:", pg.evaluate(STATE))
    pg.screenshot(path=f"{out}-collapsed.png")
    human_click(pg, "#ml-toggle")
    print("2 expanded:", pg.evaluate(STATE))
    human_click(pg, "#ml-neural-btn")
    print("3 neural while untrained (should stay classic):", pg.evaluate(STATE)["mode"])
    human_click(pg, "#ml-train-btn")
    time.sleep(8)
    print("4 learning 8s:", pg.evaluate(STATE))
    pg.screenshot(path=f"{out}-learning.png")
    human_click(pg, "#ml-train-btn")
    print("5 paused:", pg.evaluate(STATE))
    human_click(pg, "#ml-neural-btn")
    time.sleep(6)
    print("6 neural 6s:", pg.evaluate(STATE))
    pg.screenshot(path=f"{out}-neural.png")
    pg.keyboard.press("m"); time.sleep(0.3)
    print("7 after M key open =", pg.evaluate(STATE)["open"])
    pg.keyboard.press("m"); time.sleep(0.3)
    pg.reload(); time.sleep(2.5)
    print("8 after reload:", {k: v for k, v in pg.evaluate(STATE).items() if k in ("mode", "status", "steps", "open", "saved", "trainBtn")})
    human_click(pg, "#ml-reset-btn")
    print("9 reset armed:", pg.inner_text("#ml-reset-btn"))
    human_click(pg, "#ml-reset-btn")
    print("10 after reset:", {k: v for k, v in pg.evaluate(STATE).items() if k in ("mode", "steps", "neuralDisabled", "trainBtn", "saved")})
    print("errors:", errors)
    b.close()
srv.shutdown()
