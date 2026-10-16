# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Trigger each explosion kind in front of a fixed camera and capture a timed sequence.

Usage: uv run tools/explosion_shot.py <out_prefix> [scenario]
Scenarios: airburst (default), water, deck, flak
"""
import sys
import time

from _harness import game_page, report_errors, timed_screenshots

out = sys.argv[1]
scenario = sys.argv[2] if len(sys.argv) > 2 else "airburst"

SCENARIOS = {
    "airburst": ("c.camera.position.set(-9, 9, 16); c.controls.target.set(0, 14, -25);",
                 "c.createExplosion(new V(0, 16, -32), 'airburst');"),
    "water": ("c.camera.position.set(-20, 8, 20); c.controls.target.set(-25, 3, -25);",
              "c.createExplosion(new V(-25, 0.75, -30), 'impact');"),
    "deck": ("c.camera.position.set(-22, 12, 22); c.controls.target.set(0, 3, 0);",
             "c.createExplosion(new V(0, 2, 0), 'impact');"),
    "flak": ("c.camera.position.set(-9, 9, 16); c.controls.target.set(0, 14, -25);",
             "for (let i = 0; i < 12; i++) c.createExplosion(new V(-8 + i * 1.6, 12 + Math.sin(i) * 3, -30 - i), 'flak');"
             " for (let i = 0; i < 3; i++) c.createExplosion(new V(6 + i * 3, 16, -28), 'hit');"),
}
cam_js, boom_js = SCENARIOS[scenario]

with game_page(dpr=2, console_levels=("error", "warning")) as (page, errors):
    time.sleep(4)
    # Hide the HUD so the frames show only the scene
    page.evaluate("() => { document.getElementById('hud').style.display = 'none'; }")
    page.evaluate(f"() => {{ const c = window.__ciws; const V = c.camera.position.constructor; {cam_js} c.controls.update(); }}")
    time.sleep(0.3)
    start = time.time()
    page.evaluate(f"() => {{ const c = window.__ciws; const V = c.camera.position.constructor; {boom_js} }}")
    timed_screenshots(page, (0.05, 0.15, 0.35, 0.7, 1.3, 2.5), lambda t: f"{out}-{scenario}-{t:.2f}.png", start)
report_errors(errors)
