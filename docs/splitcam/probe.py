# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Scratch probe for the split-screen plan (does not touch the repo).

Usage: uv run probe.py OUTDIR
Loads the game with tools/_harness.py, installs a split-screen renderer modelled on
tools/demo_video.py (layouts: side, stack, pip), takes screenshots and measures per-frame cost:
renderer.info (draw calls, triangles) summed over panes, CPU time inside renderer.render, and
CPU+GPU time with gl.finish() around it. Variants: single view, split, split with the shadow map
rendered once per frame.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

INSTALL_JS = r"""() => {
    const { scene, camera, renderer, layout } = window.__ciws;
    const d = window.__ciws.debug;
    const T = camera.position.constructor;
    const S = window.__split = {
        on: false, layout: 'side', shadowOnce: false, measure: false, finish: false,
        stats: [], chaseTarget: null,
    };
    const chase = new camera.constructor(60, 1, 0.25, 4000);
    const sight = new camera.constructor(45, 1, 0.25, 4000);
    const gunBlock = scene.getObjectByName('barrels').parent;
    const SIGHT_EYE = new T(0, 0.95, 0.6), SIGHT_AHEAD = new T(0, 0.95, 200);
    const SHIP = new T(0, layout.mountY + 4, 0);
    const sky = scene.children.find(o => o.isMesh && o.renderOrder === -1 && o.geometry.parameters?.radius === 3000);
    const updateSight = () => {
        gunBlock.updateWorldMatrix(true, false);
        sight.position.copy(SIGHT_EYE).applyMatrix4(gunBlock.matrixWorld);
        sight.lookAt(SIGHT_AHEAD.clone().applyMatrix4(gunBlock.matrixWorld));
    };
    const pickTarget = () => {
        if (S.chaseTarget && d.missiles.includes(S.chaseTarget)) return S.chaseTarget;
        // nearest threat to the ship
        let best = null, bd = Infinity;
        for (const m of d.missiles) { const r = m.mesh.position.distanceTo(SHIP); if (r < bd) { bd = r; best = m; } }
        if (best) S.chaseTarget = best;
        return best;
    };
    const updateChase = () => {
        const m = pickTarget();
        if (!m) return;
        const pos = m.mesh.position;
        const back = pos.clone().sub(SHIP).setY(0).normalize();
        chase.position.copy(pos).addScaledVector(back, 9).add(new T(0, 2.6, 0));
        chase.lookAt(SHIP);
    };
    const gl = renderer.getContext();
    const render = renderer.render.bind(renderer);
    renderer.info.autoReset = false;
    let frame = null;
    const pane = (cam, x, y, w, h) => {
        cam.aspect = w / h; cam.updateProjectionMatrix();
        if (sky) sky.position.copy(cam.position);
        renderer.setViewport(x, y, w, h);
        renderer.setScissor(x, y, w, h);
        render(scene, cam);
    };
    renderer.render = (sc, cam) => {
        if (S.measure && S.finish) gl.finish();
        const t0 = performance.now();
        renderer.info.reset();
        if (!S.on) {
            render(sc, cam);
        } else {
            updateChase(); updateSight();
            const size = renderer.getSize(new T());
            const W = size.x, H = size.y, gap = 3;
            renderer.setScissorTest(true);
            renderer.setScissor(0, 0, W, H);
            const cc = renderer.getClearColor(new scene.background.constructor());
            renderer.setClearColor(0x101418);
            renderer.clear();
            renderer.setClearColor(cc);
            const shadowAuto = renderer.shadowMap.autoUpdate;
            if (S.shadowOnce) { renderer.shadowMap.autoUpdate = false; renderer.shadowMap.needsUpdate = true; }
            if (S.layout === 'side') {
                const half = Math.floor(W / 2);
                pane(sight, 0, 0, half - gap, H);
                pane(chase, half + gap, 0, W - half - gap, H);
            } else if (S.layout === 'stack') {
                const half = Math.floor(H / 2);
                pane(chase, 0, half + gap, W, H - half - gap);   // top (GL y is up)
                pane(sight, 0, 0, W, half - gap);                // bottom
            } else if (S.layout === 'pip') {
                pane(sight, 0, 0, W, H);
                const w = Math.round(W * 0.34), h = Math.round(w * 9 / 16), m = 16;
                const x = W - w - m, y = m + 60;
                renderer.setScissor(x - gap, y - gap, w + 2 * gap, h + 2 * gap);
                renderer.setClearColor(0x101418); renderer.clear(); renderer.setClearColor(cc);
                pane(chase, x, y, w, h);
            }
            renderer.shadowMap.autoUpdate = shadowAuto;
            if (sky) sky.position.copy(cam.position);
            renderer.setViewport(0, 0, W, H);
            renderer.setScissorTest(false);
        }
        if (S.measure) {
            if (S.finish) gl.finish();
            const r = renderer.info.render;
            S.stats.push({ ms: performance.now() - t0, calls: r.calls, tris: r.triangles, t: performance.now() });
        }
    };
    return { sky: !!sky };
}"""

MEASURE_JS = """async ([seconds, finish]) => {
    const S = window.__split;
    S.stats = []; S.finish = finish; S.measure = true;
    await new Promise(r => setTimeout(r, seconds * 1000));
    S.measure = false;
    const st = S.stats;
    const avg = k => st.reduce((a, s) => a + s[k], 0) / st.length;
    const sorted = st.map(s => s.ms).sort((a, b) => a - b);
    const intervals = st.slice(1).map((s, i) => s.t - st[i].t).sort((a, b) => a - b);
    return {
        frames: st.length, fps: st.length / seconds,
        renderMs: +avg('ms').toFixed(2), renderP95: +sorted[Math.floor(sorted.length * 0.95)].toFixed(2),
        frameIntervalMedian: +intervals[Math.floor(intervals.length / 2)].toFixed(2),
        calls: Math.round(avg('calls')), tris: Math.round(avg('tris')),
        threats: window.__ciws.debug.missiles.length,
    };
}"""

SET_MODE_JS = """(mode) => {
    // cycle the 3-mode toggle until the follow-status label matches
    const names = ['OFF', 'PHALANX', 'MISSILE'];
    for (let i = 0; i < 3 && document.getElementById('follow-status').innerText !== names[mode]; i++) window.toggleCameraFollow();
}"""

SPAWN_JS = """(angle) => {
    const d = window.__ciws.debug;
    const random = Math.random;
    Math.random = () => angle / (Math.PI * 2);
    try { window.__split.chaseTarget = d.spawnAntiShipMissile(null); } finally { Math.random = random; }
}"""

ALIVE_JS = "() => { const S = window.__split; return !!S.chaseTarget && window.__ciws.debug.missiles.includes(S.chaseTarget) ? S.chaseTarget.mesh.position.length() : -1; }"

results = {}
with game_page(width=1600, height=900, dpr=2) as (page, errors):
    time.sleep(6)
    print(page.evaluate(INSTALL_JS))
    page.evaluate("() => { window.__ciws.debug.setWave(6); }")
    time.sleep(2)
    # --- perf: single view vs split variants (CPU-only timing, then with gl.finish) ---
    for finish in (False, True):
        tag = "finish" if finish else "cpu"
        page.evaluate(SET_MODE_JS, 0)
        results[f"orbit-{tag}"] = page.evaluate(MEASURE_JS, [3, finish])
        page.evaluate(SET_MODE_JS, 1)
        results[f"gun-{tag}"] = page.evaluate(MEASURE_JS, [3, finish])
        page.evaluate("() => { window.__split.on = true; window.__split.layout = 'side'; window.__split.shadowOnce = false; }")
        results[f"split-{tag}"] = page.evaluate(MEASURE_JS, [3, finish])
        page.evaluate("() => { window.__split.shadowOnce = true; }")
        results[f"split-shadowonce-{tag}"] = page.evaluate(MEASURE_JS, [3, finish])
        page.evaluate("() => { window.__split.on = false; window.__split.shadowOnce = false; }")
    print(json.dumps(results, indent=1))

    # --- screenshots: side-by-side split following one vampire to its kill ---
    page.evaluate("() => { window.__ciws.debug.holdSpawns(); window.__ciws.debug.clearThreats(); }")
    time.sleep(1.0)
    page.evaluate(SPAWN_JS, 0.35)
    page.evaluate("() => { window.__split.on = true; window.__split.layout = 'side'; }")
    t0 = time.time()
    shots = []
    last = 0
    while time.time() - t0 < 14:
        r = page.evaluate(ALIVE_JS)
        if r < 0:
            break
        if time.time() - last > 1.6:
            p = out / f"side-{time.time() - t0:05.2f}-r{int(r)}.png"
            page.screenshot(path=str(p)); shots.append(p.name); last = time.time()
        time.sleep(0.05)
    # just after the kill (chase holds the last pose)
    for dt in (0.15, 0.6, 1.2):
        time.sleep(dt if dt == 0.15 else 0.45)
        p = out / f"side-afterkill-{dt:.2f}.png"
        page.screenshot(path=str(p)); shots.append(p.name)

    # --- PiP layout ---
    page.evaluate(SPAWN_JS, 1.9)
    page.evaluate("() => { window.__split.layout = 'pip'; }")
    time.sleep(4.5)
    page.screenshot(path=str(out / "pip.png")); shots.append("pip.png")

    # --- portrait: stacked ---
    page.set_viewport_size({"width": 430, "height": 932})
    time.sleep(0.5)
    page.evaluate("() => { window.__split.layout = 'stack'; }")
    page.evaluate(SPAWN_JS, 0.9)
    time.sleep(4.0)
    page.screenshot(path=str(out / "stack-portrait.png")); shots.append("stack-portrait.png")
    page.evaluate("() => { window.__split.layout = 'side'; }")
    time.sleep(0.3)
    page.screenshot(path=str(out / "side-portrait.png")); shots.append("side-portrait.png")
    print("shots:", shots)
report_errors(errors)
(out / "perf.json").write_text(json.dumps(results, indent=1))
