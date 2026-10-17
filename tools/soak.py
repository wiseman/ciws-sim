# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Play the game unattended for a while and report what happened, frame rate and console errors.

Usage: uv run tools/soak.py [seconds] [wave] [--neural] [--camera MODE] [--page FILE]
Forces the difficulty to `wave` (default 5, so anti-ship missiles are in the mix), tallies how
every threat ended by type and by target (shot down, or reached our ship or a friendly), where
drones were shot down (range from the mount, height, and their flight phase), and samples the
frame rate. With --neural the net learns from the solver for the first third and then takes over
the gun. --camera plays it in a camera mode (off, phalanx, missile or split); the cameras only read
the game, so the outcome should match a run without it, to within run-to-run noise. --page plays
another copy of the game (a path relative to the repo, say a saved older build) for before/after
comparisons. Prints a summary line at the end, prefixed SUMMARY, as JSON.
"""
import json
import sys
import time
from collections import Counter
from statistics import median

from _harness import game_page, page_arg, report_errors

argv = sys.argv[1:]
camera = argv.pop(argv.index("--camera") + 1) if "--camera" in argv else None
page_path = page_arg(argv)
args = [a for a in argv if not a.startswith("--")]
seconds = float(args[0]) if args else 90
wave = int(args[1]) if len(args) > 1 else 5
neural = "--neural" in sys.argv

WATCH_JS = """(wave) => {
    const d = window.__ciws.debug;
    d.setWave(wave);
    // tally[type][target]: [killed, leaked]; drones: kill range, height and phase
    window.__soak = { seen: new Map(), tally: {}, droneKills: [], frames: 0, worstFrame: 0, last: performance.now() };
    const s = window.__soak;
    const tick = () => {
        const now = performance.now();
        s.worstFrame = Math.max(s.worstFrame, now - s.last);
        s.last = now;
        s.frames++;
        const live = new Set(d.missiles);
        for (const [m, target] of s.seen) {
            if (live.has(m)) continue;
            s.seen.delete(m);
            const byTarget = (s.tally[m.type] ??= {});
            const counts = (byTarget[target] ??= [0, 0]);
            if (m.health <= 0) {
                counts[0]++;
                if (m.type === 'drone') {
                    const p = m.mesh.position;
                    s.droneKills.push([Math.hypot(p.x, p.y - 6, p.z), p.y, m.dive ? m.dive.phase : 'level']);
                }
            } else counts[1]++;
        }
        live.forEach(m => { if (!s.seen.has(m)) s.seen.set(m, m.targetInfo.type); });
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}"""

REPORT_JS = """() => {
    const d = window.__ciws.debug, s = window.__soak;
    const st = d.stats;
    return { tally: s.tally, frames: s.frames, worstFrameMs: Math.round(s.worstFrame),
             score: st.score, health: st.health, wave: st.wave, wrecks: d.wrecks.length,
             friendliesLost: d.friendlies.filter(f => !f.alive).length, smokePuffs: d.smokePuffs,
             vlsInFlight: d.vlsLaunches.length, threats: d.missiles.length, stats: st.engagementStats,
             gameOver: document.getElementById('game-over').style.display === 'block' };
}"""


with game_page(console_levels=("error", "warning"), page_path=page_path) as (page, errors):
    time.sleep(2)
    page.evaluate(WATCH_JS, wave)
    if camera:
        page.evaluate("(mode) => window.__ciws.setCameraMode(mode)", camera)
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
    r = page.evaluate(REPORT_JS)
    fps = r["frames"] / (time.time() - start)
    kills = page.evaluate("() => window.__soak.droneKills")
    print(f"average {fps:.1f} fps")
report_errors(errors)
phases = Counter(phase for _, _, phase in kills)
print("SUMMARY", json.dumps({
    "page": page_path, "wave": wave, "seconds": seconds, "fps": round(fps, 1), "worstFrameMs": r["worstFrameMs"],
    "tally": r["tally"], "friendliesLost": r["friendliesLost"], "health": r["health"], "gameOver": r["gameOver"],
    "droneKillRangeMedian": median(k[0] for k in kills) if kills else None,
    "droneKillHeightMedian": median(k[1] for k in kills) if kills else None,
    "droneKillPhases": phases, "classic": r["stats"]["classic"]}))
