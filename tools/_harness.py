"""Shared setup for the Playwright tools: serve the repo and open the game in headless Chromium.

Usage from a tool script (run with `uv run tools/<script>.py`, which puts tools/ on sys.path):

    from _harness import game_page, report_errors
    with game_page(dpr=2) as (page, errors):
        ...
    report_errors(errors)
"""
import http.server
import socketserver
import threading
from contextlib import contextmanager
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

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
