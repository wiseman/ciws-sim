# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Walk through the fire-control/learning workflow and screenshot the dock.

Usage: uv run tools/ml_panel_check.py <out_prefix>
"""
import sys
import time

from _harness import game_page, report_errors

out = sys.argv[1]

STATE = """() => ({
    mode: document.getElementById('ml-chip-mode').textContent,
    chip: document.getElementById('ml-chip-learn').textContent,
    status: document.getElementById('status-text').textContent,
    learn: document.getElementById('ml-learn-state').textContent,
    trainBtn: document.getElementById('ml-train-btn').textContent,
    neuralDisabled: document.getElementById('ml-neural-btn').disabled,
    steps: document.getElementById('ml-steps').textContent,
    loss: document.getElementById('ml-loss').textContent,
    aim: document.getElementById('ml-aim-error').textContent,
    agree: document.getElementById('ml-fire-agree').textContent,
    classic: document.getElementById('ml-perf-classic').innerText.replace(/\\s+/g, ' '),
    neural: document.getElementById('ml-perf-neural').innerText.replace(/\\s+/g, ' '),
    saved: document.getElementById('ml-saved').textContent,
    open: document.getElementById('ml-panel').classList.contains('open')
})"""

def human_click(page, sel):
    page.locator(sel).scroll_into_view_if_needed()
    box = page.locator(sel).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down(); time.sleep(0.1); page.mouse.up(); time.sleep(0.3)

with game_page(dpr=2) as (page, errors):
    time.sleep(2.5)
    print("1 fresh:", page.evaluate(STATE))
    page.screenshot(path=f"{out}-collapsed.png")
    human_click(page, "#ml-toggle")
    print("2 expanded:", page.evaluate(STATE))
    human_click(page, "#ml-neural-btn")
    print("3 neural while untrained (should stay classic):", page.evaluate(STATE)["mode"])
    human_click(page, "#ml-train-btn")
    time.sleep(8)
    print("4 learning 8s:", page.evaluate(STATE))
    page.screenshot(path=f"{out}-learning.png")
    human_click(page, "#ml-train-btn")
    print("5 paused:", page.evaluate(STATE))
    human_click(page, "#ml-neural-btn")
    time.sleep(6)
    print("6 neural 6s:", page.evaluate(STATE))
    page.screenshot(path=f"{out}-neural.png")
    page.keyboard.press("m"); time.sleep(0.3)
    print("7 after M key open =", page.evaluate(STATE)["open"])
    page.keyboard.press("m"); time.sleep(0.3)
    page.reload(); time.sleep(2.5)
    print("8 after reload:", {k: v for k, v in page.evaluate(STATE).items() if k in ("mode", "status", "steps", "open", "saved", "trainBtn")})
    human_click(page, "#ml-reset-btn")
    print("9 reset armed:", page.inner_text("#ml-reset-btn"))
    human_click(page, "#ml-reset-btn")
    print("10 after reset:", {k: v for k, v in page.evaluate(STATE).items() if k in ("mode", "steps", "neuralDisabled", "trainBtn", "saved")})
report_errors(errors)
