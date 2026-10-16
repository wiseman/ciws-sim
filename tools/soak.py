# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Play the game unattended for a while and report what happened, frame rate and console errors.

Usage: uv run tools/soak.py [seconds] [wave] [--neural]
Forces the difficulty to `wave` (default 5, so anti-ship missiles are in the mix), counts how
each anti-ship missile ended (shot down or reached its target), and samples the frame rate.
With --neural the net learns from the solver for the first third and then takes over the gun.
"""
import sys
import time

from _harness import game_page, report_errors

args = [a for a in sys.argv[1:] if not a.startswith("--")]
seconds = float(args[0]) if args else 90
wave = int(args[1]) if len(args) > 1 else 5
neural = "--neural" in sys.argv

WATCH_JS = """(wave) => {
    const d = window.__ciws.debug;
    d.setWave(wave);
    window.__soak = { ascmSeen: new Set(), ascmKilled: 0, ascmLeaked: 0, frames: 0, worstFrame: 0, last: performance.now() };
    const s = window.__soak;
    const tick = () => {
        const now = performance.now();
        s.worstFrame = Math.max(s.worstFrame, now - s.last);
        s.last = now;
        s.frames++;
        const live = new Set(d.missiles.filter(m => m.type === 'ascm'));
        for (const m of s.ascmSeen) {
            if (!live.has(m)) {
                s.ascmSeen.delete(m);
                if (m.health <= 0) s.ascmKilled++; else s.ascmLeaked++;
            }
        }
        live.forEach(m => s.ascmSeen.add(m));
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}"""

REPORT_JS = """() => {
    const d = window.__ciws.debug, s = window.__soak;
    const st = d.stats;
    return { ascmKilled: s.ascmKilled, ascmLeaked: s.ascmLeaked, frames: s.frames, worstFrameMs: Math.round(s.worstFrame),
             score: st.score, health: st.health, wave: st.wave, wrecks: d.wrecks.length,
             friendliesAlive: d.friendlies.filter(f => f.alive).length, smokePuffs: d.smokePuffs,
             vlsInFlight: d.vlsLaunches.length, threats: d.missiles.length, stats: st.engagementStats };
}"""

with game_page(console_levels=("error", "warning")) as (page, errors):
    time.sleep(2)
    page.evaluate(WATCH_JS, wave)
    if neural:
        page.evaluate("() => { window.__ciwsML.NeuralController.isTraining = true; }")
    start = time.time()
    switched = False
    while time.time() - start < seconds:
        time.sleep(5)
        if neural and not switched and time.time() - start > seconds / 3:
            page.evaluate("() => window.setControllerMode('neural')")
            switched = True
        r = page.evaluate(REPORT_JS)
        print(f"t={time.time() - start:5.0f}s", r)
    fps = page.evaluate(REPORT_JS)["frames"] / (time.time() - start)
    print(f"average {fps:.1f} fps")
report_errors(errors)
