# /// script
# dependencies = ["playwright"]
# ///
"""Time from navigation to the first rendered frame (window.__ciws present), median of 5 loads."""
import sys, time, statistics
sys.path.insert(0, sys.argv[1] + "/tools")
import _harness
from pathlib import Path
_harness.ROOT = Path(sys.argv[1])
from playwright.sync_api import sync_playwright
import http.server, socketserver, threading
from functools import partial
server = socketserver.TCPServer(("127.0.0.1", 0), partial(_harness._QuietHandler, directory=sys.argv[1]))
threading.Thread(target=server.serve_forever, daemon=True).start()
times = []
with sync_playwright() as p:
    b = p.chromium.launch(args=_harness.GPU_ARGS)
    for i in range(6):
        page = b.new_page(viewport={"width": 1280, "height": 760})
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
        page.wait_for_function("() => window.__ciws && window.__ciws.renderer.info.render.frame > 0", timeout=30000)
        t = page.evaluate("() => performance.now()")
        build = page.evaluate("() => { const t0 = performance.now(); return 0; }")
        if i: times.append(t)  # first load warms the CDN cache
        page.close()
    b.close()
server.shutdown()
print(sys.argv[1].split('/')[-1], "first frame ms:", [round(t) for t in times], "median", round(statistics.median(times)))
