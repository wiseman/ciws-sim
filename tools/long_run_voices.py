# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Console-only check of the long-run voice lines (run on Christmas Eve, for the sleigh): the 1MC routine,
a cost milestone, the chatter and the Captain two hours in, the chirp, each sighting, and the totals
surviving a reload. Prints what was said after each trigger, by bucket.

Usage: uv run tools/long_run_voices.py"""
import sys, time, json
from _harness import game_page, report_errors, enable_audio, QUIET_SCENE_JS
HOOK = """() => {
    const A = window.__ciwsAudio, log = window.__said = [];
    const { say } = A;
    A.say = function (bucket, clip, ...rest) {
        const end = say.call(this, bucket, clip, ...rest);
        if (end !== null) log.push([+A.ctx.currentTime.toFixed(1), bucket, clip]);
        return end;
    };
}"""
def said(page):
    return page.evaluate("() => window.__said.splice(0)")
def run(page, label, js, wait):
    page.evaluate(js)
    time.sleep(wait)
    print(f"{label:10s}", said(page))
with game_page(width=640, height=360, audio=True, page_path="index.html?date=12-24") as (page, errors):
    enable_audio(page, settle=2)
    page.evaluate(QUIET_SCENE_JS, True)
    page.evaluate("() => window.__ciws.debug.holdFire()")
    page.evaluate(HOOK)
    time.sleep(3); said(page)
    d = "window.__ciws.debug"
    run(page, "routine", f"() => {d}.setLongRun({{ played: 3700, routineAt: 3700, routineHeard: {{}} }})", 16)
    run(page, "routine2", f"() => {d}.setLongRun({{ routineAt: 0, routineHeard: {{ 'pa-watch': 1, 'pa-sweepers': 2, 'pa-chow': 3, 'pa-mail': 4, 'pa-taps': 3600 }} }})", 16)
    run(page, "cost", f"() => {d}.setLongRun({{ cost: 4.1e7, milestone: 0 }})", 8)
    # Chatter, nudged every 5 s, at 2 h in (every lot unlocked)
    page.evaluate(f"() => {d}.setLongRun({{ played: 7300, routineAt: 1e9 }})")
    for _ in range(10):
        page.evaluate("() => { const A = window.__ciwsAudio; A.nextChatter = A.ctx.currentTime; }")
        time.sleep(5)
    print("chatter   ", said(page))
    for _ in range(3):
        page.evaluate("() => { const A = window.__ciwsAudio; A.captainKills = 30; A.captainAt = -Infinity; }")
        time.sleep(11)
    print("captain   ", said(page))
    run(page, "chirp", "() => window.__ciwsAudio.playChirp()", 1)
    for name, setup, wait in [("dolphins", "s.z = -75", 3), ("whale", "s.age = 2.6", 3), ("sailboat", "s.mesh.position.set(200, -1.5, 30)", 3),
                              ("flyby", "s.mesh.position.z = -s.dir * 430", 6), ("bird", "s.travelled = s.length / 2 - 75", 6),
                              ("duck", "s.mesh.position.z = -13", 4), ("sleigh", "s.mesh.position.z = -s.dir * 660", 10)]:
        run(page, name, f"() => {{ const d = {d}; d.sight('{name}'); const s = d.sightings[d.sightings.length - 1]; {setup}; }}", wait)
        page.evaluate(f"() => {{ for (const s of {d}.sightings) s.step = () => false; }}")
    print(page.evaluate(f"() => {d}.longRun"))
    page.reload()
    time.sleep(3)
    print("after reload:", page.evaluate(f"() => {{ const L = {d}.longRun; return [L.played, L.kills, L.cost, L.milestone]; }}"))
report_errors(errors)
