"""Shared setup for the Playwright tools: serve the repo and open the game in headless Chromium.

Usage from a tool script (run with `uv run tools/<script>.py`, which puts tools/ on sys.path):

    from _harness import game_page, report_errors
    with game_page(dpr=2) as (page, errors):
        ...
    report_errors(errors)

Also timed screenshots and contact sheets. Playwright and Pillow are imported where they're
used, so a script needs only the dependencies of the helpers it calls.
"""
import http.server
import socketserver
import threading
import time
from contextlib import contextmanager
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPU_ARGS = ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"]

# Page-side helper: base64-encode an ArrayBuffer in chunks (one huge btoa string overflows)
B64_ENCODE_JS = """
const toBase64 = buf => {
    const bytes = new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
};
"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def game_page(width=1280, height=760, dpr=1, extra_args=(), console_levels=("error",)):
    """Yields (page, errors) with index.html loaded; errors collects page errors and console messages."""
    from playwright.sync_api import sync_playwright

    server = socketserver.TCPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=GPU_ARGS + list(extra_args))
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=dpr)
            errors = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: m.type in console_levels and errors.append(f"{m.type}: {m.text}"))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            try:
                yield page, errors
            finally:
                browser.close()
    finally:
        server.shutdown()


def report_errors(errors):
    for e in errors:
        print("ERROR:", e)


def timed_screenshots(page, times, path_for, start=None):
    """Screenshot the page at each of `times` (seconds after `start`, default now); path_for(t)
    names each file. Returns the paths."""
    start = time.time() if start is None else start
    paths = []
    for t in times:
        time.sleep(max(0, t - (time.time() - start)))
        path = path_for(t)
        page.screenshot(path=path)
        print("wrote", path)
        paths.append(path)
    return paths


def contact_sheet(images, cols, background="white"):
    """Tile equal-sized PIL images into a grid, left to right then top to bottom."""
    from PIL import Image

    w, h = images[0].size
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), background)
    for i, im in enumerate(images):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    return sheet
