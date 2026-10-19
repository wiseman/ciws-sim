# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Console check of the mount tracking the Seahawk's close pass (FLYBY.lock): stages a flyby on a quiet
scene and prints, every 0.5 s, the helicopter's distance from abeam, the mount's yaw error to her,
rounds in flight and the voice buckets asked for. With out.png, also a strip of zen mode's framing
through the pass.

Usage: uv run tools/flyby_lock_probe.py [out.png]"""
import io
import sys
import time

from _harness import game_page, report_errors, contact_sheet, QUIET_SCENE_JS
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else None
STATE = """() => {
    const g = window.__ciws, d = g.debug, s = d.sightings.find(s => s.name === 'flyby');
    if (!s) return null;
    const p = s.mesh.position, m = d.mount;
    // The mount's yaw is atan2(x, z) from the muzzle; near enough from the mount's axis here
    const want = Math.atan2(p.x, p.z);
    let err = m.yaw - want;
    while (err > Math.PI) err -= 2 * Math.PI;
    while (err < -Math.PI) err += 2 * Math.PI;
    const asked = window.__asked.splice(0);
    return { z: +(-s.dir * p.z).toFixed(0), near: !!s.near, yawErr: +(err * 180 / Math.PI).toFixed(1), rounds: d.rounds, asked, shot: d.zenShot };
}"""
with game_page(width=960, height=540) as (page, errors):
    time.sleep(2.5)
    if OUT:
        page.evaluate("() => toggleZenMode()")
        time.sleep(1)
    page.evaluate(QUIET_SCENE_JS, True)
    page.evaluate("""() => {
        const A = window.__ciwsAudio, play = A.play, asked = window.__asked = [];
        A.play = function (bucket, ...rest) { asked.push(bucket); return play.call(this, bucket, ...rest); };
        const d = window.__ciws.debug;
        d.setTimeScale(1);
        d.sight('flyby');
        const s = d.sightings.find(s => s.name === 'flyby');
        s.mesh.position.z = -s.dir * 430;
    }""")
    images = []
    for i in range(30):
        st = page.evaluate(STATE)
        print(st)
        if OUT and st and -120 < st["z"] < 140 and len(images) < 8:
            images.append(Image.open(io.BytesIO(page.screenshot())))
        if st is None:
            break
        time.sleep(0.5)
    if OUT and images:
        contact_sheet(images, 4).save(OUT)
    report_errors(errors)
