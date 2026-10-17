# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Screenshots and checks of the split-screen camera mode (CAMERA: SPLIT, or V in the game).

Usage: uv run tools/split_shot.py OUTDIR [--portrait] [--outline] [--perf]
Default (and --portrait, at 430x932): a scripted run in split mode with spawns held. NO TRACK
with nothing inbound; one drone or shell on the chase camera; a vampire taking it over once
radar has it; the vampire closing at about 900, 650 and 540 m; its kill at +0.15, +0.6 and
+1.2 s and after the hold; then a second vampire killed in slow motion, at +0.5, +3 and
+5.5 s. Prints the chase label's sequence and how long each kill hold lasted, and writes a
contact sheet of the lot.
--outline: measures the ink line width (device pixels) in the single view and in each pane of
  the side and stacked layouts; every one should be about OUTLINE_PX (2) x DPR.
--perf: draw calls, triangles, CPU time in the game's frame and the frame rate at wave 5, for
  the orbit view, PHALANX and both split layouts, then again with the CPU throttled 4x.
"""
import sys
import time
from pathlib import Path

from _harness import QUIET_SCENE_JS, contact_sheet, game_page, report_errors

flags = {a for a in sys.argv[1:] if a.startswith("--")}
out = Path(next(a for a in sys.argv[1:] if not a.startswith("--")))
out.mkdir(parents=True, exist_ok=True)
portrait = "--portrait" in flags
width, height = (430, 932) if portrait else (1600, 900)
DPR = 2

SETUP_JS = """() => {
    const d = window.__ciws.debug;
    d.setWave(4);
    // The chase label's sequence, and when the watched threat dies (performance.now())
    const w = window.__watch = { labels: [], watched: null, killedAt: 0, holds: [], killRanges: [] };
    let holdStart = 0;
    const tick = () => {
        const s = d.splitState;
        const word = s.label.split(' · ').slice(0, 2).join(' · ').split(' ').slice(0, 3).join(' ');
        if (word !== w.labels[w.labels.length - 1]) w.labels.push(word);
        if (w.watched && !w.watched.mesh.parent && !w.killedAt) {
            w.killedAt = performance.now();
            w.killRanges.push(Math.round(w.watched.mesh.position.length()));
        }
        const holding = s.holdLeft > 0;
        if (holding && !holdStart) holdStart = performance.now();
        if (!holding && holdStart) { w.holds.push(+((performance.now() - holdStart) / 1000).toFixed(2)); holdStart = 0; }
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}"""

STATE_JS = "() => { const s = window.__ciws.debug.splitState; return { label: s.label, sight: s.sightLabel, layout: s.layout, holding: s.holdLeft > 0 }; }"


def shot(page, name, shots):
    path = out / f"{name}.png"
    page.screenshot(path=str(path))
    print(f"{name:16s}", page.evaluate(STATE_JS))
    shots.append(path)


def wait_range(page, metres, timeout=20):
    """Until the watched threat is within `metres` of our ship (False if it died first)."""
    end = time.time() + timeout
    while time.time() < end:
        r = page.evaluate("() => { const m = window.__watch.watched; return m.mesh.parent ? m.mesh.position.length() : -1; }")
        if r < 0:
            return False
        if r <= metres:
            return True
        time.sleep(0.02)
    return False


def wait_kill(page, timeout=30):
    page.wait_for_function("() => window.__watch.killedAt > 0", timeout=timeout * 1000)
    return time.time()


def spawn_vampire(page, angle, friendly="null"):
    page.evaluate(f"() => {{ window.__watch.watched = window.__ciws.debug.spawnAntiShipMissile({{ angle: {angle}, targetIndex: {friendly} }}); window.__watch.killedAt = 0; }}")


def scripted_run(page):
    shots = []
    page.evaluate(QUIET_SCENE_JS, False)
    page.evaluate(SETUP_JS)
    page.evaluate("() => window.__ciws.setCameraMode('split')")
    time.sleep(2.0)
    shot(page, "1-notrack", shots)

    # One drone or shell (wave 4 spawns those and, one time in five, a vampire: retry until it's not)
    for _ in range(10):
        page.evaluate("() => { const d = window.__ciws.debug; d.clearThreats(); d.resumeSpawns(); }")
        time.sleep(0.1)
        page.evaluate("() => window.__ciws.debug.holdSpawns()")
        if page.evaluate("() => window.__ciws.debug.missiles.every(m => m.type !== 'ascm')"):
            break
    time.sleep(1.2)
    shot(page, "2-track-first", shots)

    # A vampire takes the chase camera once radar has it (~1.3 s after it appears)
    spawn_vampire(page, 0.35, "2")
    page.wait_for_function("() => window.__ciws.debug.splitState.label.includes('VAMPIRE')", timeout=10000)
    time.sleep(0.3)
    shot(page, "3-vampire-takes", shots)
    for r in (900, 650, 540):
        if wait_range(page, r):
            shot(page, f"4-vampire-{r}m", shots)

    t0 = wait_kill(page)
    for dt in (0.15, 0.6, 1.2):
        time.sleep(max(0, t0 + dt - time.time()))
        shot(page, f"5-kill+{dt:.2f}", shots)
    page.wait_for_function("() => window.__ciws.debug.splitState.holdLeft <= 0", timeout=10000)
    time.sleep(0.4)
    shot(page, "6-after-hold", shots)

    # Slow motion: the hold stretches with the boom, to at most 6 s
    page.evaluate("() => window.__ciws.debug.clearThreats()")
    spawn_vampire(page, 2.2)
    wait_range(page, 700)
    page.evaluate("() => window.toggleSlowMo()")
    t0 = wait_kill(page, timeout=60)
    for dt in (0.5, 3.0, 5.5):
        time.sleep(max(0, t0 + dt - time.time()))
        shot(page, f"7-slowmo-kill+{dt:.1f}", shots)
    page.wait_for_function("() => window.__ciws.debug.splitState.holdLeft <= 0", timeout=10000)
    page.evaluate("() => window.toggleSlowMo()")
    w = page.evaluate("() => { const w = window.__watch; return { labels: w.labels, holds: w.holds, killRanges: w.killRanges }; }")
    print("chase labels:", " -> ".join(w["labels"]))
    print("kill ranges (m):", w["killRanges"], " hold lengths (s):", w["holds"])

    # Back out to the orbit view: the renderer state must be single-view again
    page.keyboard.press("v")
    time.sleep(0.5)
    shot(page, "8-exit", shots)

    from PIL import Image
    images = [Image.open(p).convert("RGB") for p in shots]
    scale = 0.3 if not portrait else 0.4
    images = [im.resize((int(im.width * scale), int(im.height * scale))) for im in images]
    sheet = contact_sheet(images, cols=4 if not portrait else 6)
    sheet.save(out / "contact.png")
    print("wrote", out / "contact.png")


def ink_widths(path, rects):
    """Ink line widths (device px) in each rect: the median length of dark runs, down columns and
    along rows, that have light pixels on both sides (an ink line over a light hull, sea or sky)."""
    from statistics import median
    from PIL import Image

    im = Image.open(path).convert("L")
    px = im.load()

    def runs(line):
        found, start = [], None
        for i in range(1, len(line)):
            dark = line[i] < 50
            if dark and start is None and line[i - 1] > 100:
                start = i
            elif not dark and start is not None:
                if line[i] > 100 and i - start <= 12:
                    found.append(i - start)
                start = None
        return found

    result = []
    for (x0, y0, w, h) in rects:
        found = []
        for x in range(x0 + 4, x0 + w - 4, 2):
            found += runs([px[x, y] for y in range(y0, y0 + h)])
        for y in range(y0 + 4, y0 + h - 4, 2):
            found += runs([px[x, y] for x in range(x0, x0 + w)])
        result.append((median(found) if found else None, len(found)))
    return result


# For the measurement only: the sight pane shows the chase camera's NO TRACK view (ships against
# the sea), so both panes have long ink lines on light surfaces
SAME_VIEW_JS = """() => {
    const { renderer, camera } = window.__ciws, chase = window.__ciws.debug.splitState.chase;
    const render = renderer.render.bind(renderer);
    renderer.render = (scene, cam) => {
        if (cam === camera && window.__ciws.cameraMode === 'split') {
            camera.position.copy(chase.position);
            camera.quaternion.copy(chase.quaternion);
        }
        render(scene, cam);
    };
}"""


def outline_check(page):
    """Single view (fov 60, full height), side panes (fov 45, full height) and stacked panes (fov
    45, half height) need three different ink uniforms for the same width on screen."""
    page.evaluate(QUIET_SCENE_JS, False)
    page.evaluate(SETUP_JS)
    page.add_style_tag(content="#hud, #radar { display: none !important; }")
    page.evaluate("() => window.__ciws.setCameraMode('split')")
    time.sleep(1.5)
    page.evaluate(SAME_VIEW_JS)
    print(f"expected about {2 * DPR} device px (OUTLINE_PX x DPR); antialiasing can take one off")
    for layout in ("side", "stack"):
        page.evaluate(f"() => window.__ciws.debug.setSplitLayout('{layout}')")
        time.sleep(0.6)
        path = out / f"outline-{layout}.png"
        page.screenshot(path=str(path))
        panes = page.evaluate("() => window.__ciws.debug.splitState.panes")
        rects = [(p["x"] * DPR, p["top"] * DPR, p["w"] * DPR, p["h"] * DPR) for p in panes]
        (sight, n1), (chase, n2) = ink_widths(path, rects)
        print(f"{layout:6s} sight {sight} ({n1} runs)  chase {chase} ({n2} runs)")
    # The single view from the same place
    page.evaluate("""() => {
        const { camera, controls } = window.__ciws, chase = window.__ciws.debug.splitState.chase;
        const look = new camera.position.constructor(0, 0, -1).applyQuaternion(chase.quaternion).multiplyScalar(150).add(chase.position);
        window.__ciws.setCameraMode('off');
        camera.position.copy(chase.position);
        controls.target.copy(look);
        controls.update();
    }""")
    time.sleep(0.6)
    path = out / "outline-single.png"
    page.screenshot(path=str(path))
    (single, n), = ink_widths(path, [(0, 0, width * DPR, height * DPR)])
    print(f"single {single} ({n} runs)")


PERF_JS = """async (seconds) => {
    const { renderer } = window.__ciws;
    renderer.info.autoReset = false;
    // CPU time of each rAF callback (the game's whole frame), and the draw calls it made
    const frames = [];
    const raf = window.__raf ??= window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = cb => raf(t => {
        renderer.info.reset();
        const t0 = performance.now();
        cb(t);
        const r = renderer.info.render;
        if (r.calls) frames.push({ ms: performance.now() - t0, calls: r.calls, tris: r.triangles, t: t0 });
    });
    await new Promise(r => setTimeout(r, seconds * 1000));
    window.requestAnimationFrame = raf;
    renderer.info.autoReset = true;
    const avg = k => frames.reduce((a, f) => a + f[k], 0) / frames.length;
    const ms = frames.map(f => f.ms).sort((a, b) => a - b);
    const gaps = frames.slice(1).map((f, i) => f.t - frames[i].t).sort((a, b) => a - b);
    return { fps: +(frames.length / seconds).toFixed(1), frameMs: +avg('ms').toFixed(2),
             p95: +ms[Math.floor(ms.length * 0.95)].toFixed(2), gapMedian: +gaps[gaps.length >> 1].toFixed(1),
             calls: Math.round(avg('calls')), tris: Math.round(avg('tris')), threats: window.__ciws.debug.missiles.length };
}"""


def perf(page):
    page.evaluate("() => { const d = window.__ciws.debug; d.setWave(5); }")
    time.sleep(6)
    cdp = page.context.new_cdp_session(page)
    for throttle in (1, 4):
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
        for name, js in (("orbit", "setCameraMode('off')"), ("phalanx", "setCameraMode('phalanx')"),
                         ("split side", "debug.setSplitLayout('side'); window.__ciws.setCameraMode('split')"),
                         ("split stack", "debug.setSplitLayout('stack')")):
            page.evaluate(f"() => {{ window.__ciws.{js}; }}")
            time.sleep(1)
            print(f"cpu x{throttle} {name:12s}", page.evaluate(PERF_JS, 5))
        page.evaluate("() => { window.__ciws.debug.setSplitLayout('auto'); window.__ciws.setCameraMode('off'); }")


with game_page(width=width, height=height, dpr=DPR, console_levels=("error", "warning")) as (page, errors):
    time.sleep(2.5)
    if "--outline" in flags:
        outline_check(page)
    elif "--perf" in flags:
        perf(page)
    else:
        scripted_run(page)
report_errors(errors)
