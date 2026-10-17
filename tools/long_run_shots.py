# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Staged stills of the long-run sightings, the kill marks and (with a date) a holiday shoot-down, as a
contact sheet.

Usage: uv run tools/long_run_shots.py out.png [MM-DD] [shot,shot...]
Shots: dolphins whale-blow whale-flukes sailboat flyby bird duck sleigh marks."""
import sys, time, io
from _harness import game_page, report_errors, contact_sheet, QUIET_SCENE_JS
from PIL import Image
OUT = sys.argv[1]
date = sys.argv[2] if len(sys.argv) > 2 else None
only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
POSE = """async ([name, setup]) => {
    const g = window.__ciws, d = g.debug;
    d.setTimeScale(1);
    d.sight(name);
    const s = d.sightings[d.sightings.length - 1];
    new Function('s', setup)(s);
    await new Promise(r => setTimeout(r, 700));
    d.setTimeScale(0);
    const cam = new g.camera.position.constructor(), look = cam.clone();
    s.frame(s, cam, look);
    g.camera.position.copy(cam); g.controls.target.copy(look); g.controls.update();
    await new Promise(r => setTimeout(r, 200));
}"""
SHOTS = {
    "dolphins": "s.z = -25; s.age = 0;",
    "whale-blow": "s.age = 3.0; s.blows = [3.2];",
    "whale-flukes": "s.age = 11.3; s.blows = [];",
    "sailboat": "s.travelled = 0; s.mesh.position.set(70, s.mesh.position.y, -50);",
    "flyby": "s.mesh.position.z = 30 * -s.dir;",
    "bird": "s.travelled = s.length / 2 - 4;",
    "duck": "s.mesh.position.z = 0;",
    "sleigh": "s.mesh.position.z = 20 * -s.dir;",
}
with game_page(width=640, height=360, page_path="index.html" + (f"?date={date}" if date else "")) as (page, errors):
    time.sleep(2.5)
    page.evaluate(QUIET_SCENE_JS, True)
    page.evaluate("() => window.__ciws.debug.holdFire()")
    images = []
    for label, setup in SHOTS.items():
        if only and label not in only: continue
        name = label.split("-")[0]
        page.evaluate(POSE, [name, setup])
        images.append(Image.open(io.BytesIO(page.screenshot())))
        page.evaluate("() => { const d = window.__ciws.debug; for (const s of d.sightings) s.step = () => false; d.setTimeScale(1); }")
        time.sleep(0.3)
    if not only or "marks" in only:
        # Kill marks: 2345 kills is two stars and three missiles; close behind the radome
        page.evaluate("""async () => {
            const g = window.__ciws, d = g.debug;
            d.setLongRun({ kills: 2345 });
            await new Promise(r => setTimeout(r, 300));
            let radome = null;
            g.scene.traverse(o => { if (o.isInstancedMesh && o.count > 0 && o.parent?.geometry?.type === 'LatheGeometry') radome = o.parent; });
            radome.updateWorldMatrix(true, false);
            const c = radome.localToWorld(new g.camera.position.constructor(0, 2.05, 0));
            const back = new g.camera.position.constructor(0, 0, -1).transformDirection(radome.matrixWorld);
            g.camera.position.copy(c).addScaledVector(back, 4).setY(c.y + 0.6);
            g.controls.target.copy(c); g.controls.update();
            await new Promise(r => setTimeout(r, 300));
        }""")
        images.append(Image.open(io.BytesIO(page.screenshot())))
    if date:
        # A shoot-down in front of the camera, a moment after
        page.evaluate("""async () => {
            const g = window.__ciws;
            g.camera.position.set(-28, 33, 28); g.controls.target.set(0, 30, 0); g.controls.update();
            g.createExplosion(new g.camera.position.constructor(0, 32, 0), 'airburst');
            await new Promise(r => setTimeout(r, 450));
        }""")
        images.append(Image.open(io.BytesIO(page.screenshot())))
    contact_sheet(images, 3).save(OUT)
    print("wrote", OUT)
report_errors(errors)
