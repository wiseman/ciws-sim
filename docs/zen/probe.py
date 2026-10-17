# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Scratch probe for zen mode."""
import sys
import time

sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors

OUT = "/private/tmp/claude-501/-Users-wiseman-src-ciws-sim/3198b73f-d85d-4071-9cf0-328b4d244fe2/scratchpad/zen"
E = lambda page, js: page.evaluate(f"() => {{ const c = window.__ciws, d = c.debug; {js} }}")

with game_page() as (page, errors):
    time.sleep(3)
    before = E(page, "return { pos: c.camera.position.toArray(), wave: d.stats.wave };")
    page.keyboard.press("z")
    time.sleep(0.3)
    print("enter:", E(page, """return { zen: document.body.classList.contains('zen'),
        hud: getComputedStyle(document.getElementById('hud')).display, wave: d.stats.wave, shot: d.zenShot, mode: c.cameraMode };"""))

    # Director log, ~90 s, with two vampires spawned
    log, last, t0 = [], None, time.time()
    while time.time() - t0 < 90:
        t = time.time() - t0
        if 5 <= t < 5.15 or 50 <= t < 50.15:
            E(page, "d.spawnAntiShipMissile({ angle: Math.random() * 6.28 });")
            log.append((round(t, 1), "spawned vampire"))
            time.sleep(0.15)
        s = E(page, "return d.zenShot + '/' + c.cameraMode + (c.cameraMode === 'split' ? ' pin=' + !!d.splitState : '');")
        if s != last:
            log.append((round(t, 1), s))
            last = s
        time.sleep(0.1)
    print("director log:")
    for e in log:
        print("  ", e)
    page.screenshot(path=f"{OUT}/probe-director.png")

    # Wreck -> replacement
    E(page, "window.__w = { name: d.friendlies[0].name }; d.wreckFriendly(0); d.setTimeScale(10);")
    t0, seen_arriving, targeted_while_arriving, arrive_shot = time.time(), None, 0, False
    while time.time() - t0 < 40:
        r = E(page, """const f = d.friendlies[0];
            return { alive: f.alive, arriving: !!f.arriving, name: f.name, x: f.position.x, z: f.position.z,
                     targeted: d.missiles.filter(m => m.targetInfo.friendlyId === 0 && m.targetInfo.type === 'friendly').length,
                     wrecks: d.wrecks.length, health: d.stats.health };""")
        if r["alive"] and r["arriving"]:
            if not seen_arriving:
                seen_arriving = r
                print("replacement sent:", r)
            targeted_while_arriving = max(targeted_while_arriving, r["targeted"])
            if not arrive_shot and abs(r["z"] - 0) < 400:
                E(page, "d.setTimeScale(1); c.camera.position.set(-150, 90, 260); c.controls.target.set(0, 0, 60); c.controls.update();")
                time.sleep(0.3)
                page.screenshot(path=f"{OUT}/probe-arriving.png")
                E(page, "d.setTimeScale(10);")
                arrive_shot = True
        if seen_arriving and r["alive"] and not r["arriving"]:
            print("on station:", r, "| old name:", E(page, "return window.__w.name;"), "| max targeted while arriving:", targeted_while_arriving)
            break
        time.sleep(0.1)
    else:
        print("TIMEOUT waiting for replacement", r)
    E(page, "d.setTimeScale(1);")

    # Health: own-ship hits and real impacts with the gun held
    E(page, "d.hitOwnShip(); d.hitOwnShip('port'); d.holdFire(); for (let i = 0; i < 4; i++) d.spawnAntiShipMissile({ angle: i * 1.5 }); d.setTimeScale(4);")
    time.sleep(8)
    print("health after hits:", E(page, "d.setTimeScale(1); return { health: d.stats.health, hud: document.getElementById('health-bar').textContent, alive: d.friendlies.filter(f => f.alive).length };"))

    # Exit chip, then Esc exit
    page.mouse.click(640, 380)
    time.sleep(0.5)
    print("chip shown:", E(page, "return document.getElementById('zen-exit').className;"))
    page.keyboard.press("Escape")
    time.sleep(0.3)
    after = E(page, """return { zen: document.body.classList.contains('zen'), hud: getComputedStyle(document.getElementById('hud')).display,
        mode: c.cameraMode, pos: c.camera.position.toArray(), wave: d.stats.wave, status: document.getElementById('zen-status').textContent };""")
    print("before:", before)
    print("after exit:", after)
    E(page, "d.setTimeScale(8);")
    time.sleep(3)
    print("wave ramp after ~24 sim s:", E(page, "d.setTimeScale(1); return d.stats.wave;"))
    page.screenshot(path=f"{OUT}/probe-exit.png")

    # Z again then Z (toggle), then game over -> Z reloads into zen
    page.keyboard.press("z"); time.sleep(0.3); page.keyboard.press("z"); time.sleep(0.3)
    print("toggle twice, zen:", E(page, "return document.body.classList.contains('zen');"))
    E(page, "for (let i = 0; i < d.friendlies.length; i++) d.wreckFriendly(i);")
    time.sleep(0.5)
    print("game over shown:", E(page, "return getComputedStyle(document.getElementById('game-over')).display;"))
    with page.expect_navigation():
        page.keyboard.press("z")
    time.sleep(3)
    print("after reload:", E(page, "return { zen: document.body.classList.contains('zen'), shot: d.zenShot, mode: c.cameraMode, wave: d.stats.wave, alive: d.friendlies.filter(f => f.alive).length };"))
report_errors(errors)
