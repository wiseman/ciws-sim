"""Shared setup for the Playwright tools: serve the repo and open the game in headless Chromium.

Usage from a tool script (run with `uv run tools/<script>.py`, which puts tools/ on sys.path):

    from _harness import game_page, report_errors
    with game_page(dpr=2) as (page, errors):
        ...
    report_errors(errors)

With audio=True, game_page lets the page play sound unprompted, and enable_audio(page) starts and
unmutes it. Also timed screenshots, contact sheets, in-page frame capture (FRAME_CAPTURE_JS, save_strip), a
quiet scene for staged shots (QUIET_SCENE_JS) and the --page option (page_arg). Playwright and
Pillow are imported where they're used, so a script needs only the dependencies of the helpers it
calls.
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
AUTOPLAY_ARGS = ["--autoplay-policy=no-user-gesture-required"]

# Page-side helper: base64-encode an ArrayBuffer in chunks (one huge btoa string overflows)
B64_ENCODE_JS = """
const toBase64 = buf => {
    const bytes = new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
};
"""


# Page-side, page.evaluate(QUIET_SCENE_JS, hide_hud): nothing else in the scene for a staged shot (no
# spawns, no unprompted VLS launches, no threats), and with hide_hud the HUD hidden
QUIET_SCENE_JS = """(hideHud) => {
    const d = window.__ciws.debug;
    if (hideHud) document.getElementById('hud').style.display = 'none';
    d.holdSpawns(); d.holdVLS(); d.clearThreats();
}"""

# Page-side, installed by page.evaluate(FRAME_CAPTURE_JS): window.__captureFrames(o) wraps
# renderer.render and copies the game's canvas (o.width wide, default 960) at sim times. Around each
# render it calls o.before() and then o.frameTime(), which returns the sim seconds since the moment
# of interest (null: not yet). Each time that reaches the next of o.samples the frame is copied,
# drawn over by o.decorate(ctx, t) and stamped with t. Once t reaches o.until (default the last
# sample) with every sample taken, or after o.timeoutMs (default 120 s), it puts the renderer back
# and resolves with the frames as base64 PNGs (for save_strip).
FRAME_CAPTURE_JS = """() => {
    window.__captureFrames = ({ samples, width = 960, until = samples[samples.length - 1], before = () => {},
                               frameTime, decorate = () => {}, timeoutMs = 120000 }) => new Promise(resolve => {
        const { renderer } = window.__ciws, canvas = renderer.domElement;
        const shot = document.createElement('canvas');
        shot.width = width;
        shot.height = Math.round(width * canvas.height / canvas.width);
        const ctx = shot.getContext('2d');
        const frames = [], original = renderer.render.bind(renderer), deadline = performance.now() + timeoutMs;
        let next = 0;
        const finish = () => { renderer.render = original; resolve(frames); };
        renderer.render = (scene, cam) => {
            before();
            original(scene, cam);
            const t = frameTime();
            if (performance.now() > deadline) return finish();
            if (t === null) return;
            if (next < samples.length && t >= samples[next]) {
                while (next < samples.length && t >= samples[next]) next++;
                ctx.drawImage(canvas, 0, 0, shot.width, shot.height);
                decorate(ctx, t);
                ctx.fillStyle = '#000'; ctx.font = '16px sans-serif'; ctx.fillText(`t=${t.toFixed(2)}s`, 8, 20);
                frames.push(shot.toDataURL('image/png').split(',')[1]);
            }
            if (next >= samples.length && t >= until) finish();
        };
    });
}"""


def page_arg(argv):
    """Takes `--page FILE` out of the argument list argv, if it's there: the page to play, a path
    relative to the repo (say a saved copy of an older build). Returns it, or index.html."""
    if "--page" not in argv:
        return "index.html"
    i = argv.index("--page")
    page = argv[i + 1]
    del argv[i:i + 2]
    return page


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def game_page(width=1280, height=760, dpr=1, extra_args=(), console_levels=("error",), page_path="index.html",
              audio=False):
    """Yields (page, errors) with the game loaded (page_path: the page, relative to the repo, say a
    saved copy of an older build); errors collects page errors and console messages. audio: let the
    page play sound without a user gesture (then call enable_audio)."""
    from playwright.sync_api import sync_playwright

    server = socketserver.TCPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=GPU_ARGS + (AUTOPLAY_ARGS if audio else []) + list(extra_args))
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=dpr)
            errors = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: m.type in console_levels and errors.append(f"{m.type}: {m.text}"))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/{page_path}")
            try:
                yield page, errors
            finally:
                browser.close()
    finally:
        server.shutdown()


def enable_audio(page, load=1.5, settle=1.5):
    """Starts the game's audio on a game_page(audio=True): waits `load` s for the page, clicks low
    on it (the first gesture initializes audio), unmutes and waits `settle` s (the urgent callouts
    load)."""
    time.sleep(load)
    size = page.viewport_size
    page.mouse.click(size["width"] // 2, int(size["height"] * 0.8))
    page.evaluate("() => window.toggleMute()")
    time.sleep(settle)


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


def save_strip(frames, path, cols=3, width=480):
    """Decode base64 PNG frames (from __captureFrames), scale each to `width` wide and save them as a
    contact sheet at `path`. Returns the path, or None if there were no frames."""
    import base64
    import io

    from PIL import Image

    if not frames:
        return None
    images = [Image.open(io.BytesIO(base64.b64decode(f))).convert("RGB") for f in frames]
    contact_sheet([im.resize((width, int(width * im.height / im.width))) for im in images], cols).save(path)
    return path
