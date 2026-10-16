# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Render index.html headlessly and save screenshots for visual checks.

Usage: uv run tools/screenshot.py [out_prefix] [wait_seconds]
Loads the page at 2x DPR and captures the default orbit view plus a few scripted camera angles
(posed relative to the gun's deck height, window.__ciws.layout.mountY).
"""
import sys
import time

from _harness import game_page, report_errors

prefix = sys.argv[1] if len(sys.argv) > 1 else "shot"
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 6

# name -> (js run before capture, seconds to wait after it)
views = {
    "default": (None, 0),
    "behind": ("camera.position.set(-9, m + 9, 16); controls.target.set(0, m + 5, -10);", 0.6),
    "low": ("camera.position.set(-30, m + 4, 30); controls.target.set(0, m + 4, 0);", 0.6),
    "high": ("camera.position.set(-75, 70, 95); controls.target.set(0, 0, 8);", 0.6),
    "gun-cam": ("window.toggleCameraFollow();", 1.5),
    "missile-cam": ("window.toggleCameraFollow();", 2.5),
}

with game_page(dpr=2, console_levels=("error", "warning")) as (page, errors):
    time.sleep(wait)
    for name, (js, delay) in views.items():
        if js:
            page.evaluate(f"() => {{ const {{camera, controls, layout}} = window.__ciws; const m = layout.mountY; {js} controls.update(); }}")
            time.sleep(delay)
        out = f"{prefix}-{name}.png"
        page.screenshot(path=out)
        print("wrote", out)
report_errors(errors)
