# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
import sys, time
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors
OUT = "/private/tmp/claude-501/-Users-wiseman-src-ciws-sim/3198b73f-d85d-4071-9cf0-328b4d244fe2/scratchpad/zen"
E = lambda page, js: page.evaluate(f"() => {{ const c = window.__ciws, d = c.debug; {js} }}")
with game_page() as (page, errors):
    time.sleep(2)
    page.keyboard.press("z")
    E(page, "d.wreckFriendly(0); d.setTimeScale(20);")
    while not E(page, "return !!d.friendlies[0].arriving;"):
        time.sleep(0.1)
    E(page, "d.setTimeScale(1);")
    while E(page, "return c.cameraMode;") != "off":
        time.sleep(0.2)
    page.mouse.click(640, 700)  # the user takes the camera: the director pauses
    for i in range(3):
        r = E(page, """const f = d.friendlies[0], p = f.position;
            c.camera.position.set(p.x - 70, 30, p.z + 60); c.controls.target.set(p.x, 0, p.z - 30); c.controls.update();
            return { name: f.name, left: f.position.distanceTo(f.arriving), shot: d.zenShot, chip: document.getElementById('zen-exit').className };""")
        print(r)
        time.sleep(1)
    page.screenshot(path=f"{OUT}/probe-arriving.png")
report_errors(errors)
