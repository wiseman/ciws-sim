# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Close-ups of the Seahawk flyby's model, frozen in mid-pass, as a contact sheet.

Usage: uv run tools/helo_shots.py out.png [width]
Views (relative to the helicopter, nose +z): side, front three-quarter, rear three-quarter, below,
above, and the zen director's framing of the flyby."""
import io
import sys
import time

from _harness import game_page, report_errors, contact_sheet, QUIET_SCENE_JS
from PIL import Image

OUT = sys.argv[1]
WIDTH = int(sys.argv[2]) if len(sys.argv) > 2 else 720
VIEWS = {  # camera offset from the helicopter in its own frame (nose +z, left +x), look offset
    "side": ([-17, 0.8, -2.2], [0, 0.6, -2.2]),
    "front-34": ([-7, 1.5, 9], [0, 0.3, 1.5]),
    "rear-34": ([9, 3.5, -16], [0, 1, -5]),
    "below": ([-7, -7, 5], [0, 0, -1.5]),
    "above": ([-8, 11, 1], [0, 0.5, -2]),
}
POSE = """async ([offset, look]) => {
    const g = window.__ciws, d = g.debug, V = g.camera.position.constructor;
    const s = d.sightings[d.sightings.length - 1];
    s.mesh.updateMatrixWorld(true);
    const cam = s.mesh.localToWorld(new V(...offset)), at = s.mesh.localToWorld(new V(...look));
    g.camera.position.copy(cam); g.controls.target.copy(at); g.controls.update();
    await new Promise(r => setTimeout(r, 250));
}"""
with game_page(width=WIDTH, height=WIDTH * 11 // 18) as (page, errors):
    time.sleep(2.5)
    page.evaluate(QUIET_SCENE_JS, True)
    page.evaluate("""async () => {
        const g = window.__ciws, d = g.debug;
        d.holdFire(); d.setTimeScale(1);
        g.controls.maxPolarAngle = Math.PI; // let the camera look up from below
        d.sight('flyby');
        const s = d.sightings[d.sightings.length - 1];
        s.mesh.position.z = 30 * -s.dir;
        await new Promise(r => setTimeout(r, 400));
        d.setTimeScale(0);
    }""")
    images = []
    for name, (offset, look) in VIEWS.items():
        page.evaluate(POSE, [offset, look])
        images.append(Image.open(io.BytesIO(page.screenshot())))
    page.evaluate("""async () => {
        const g = window.__ciws, d = g.debug, s = d.sightings[d.sightings.length - 1];
        g.controls.maxPolarAngle = Math.PI / 2 - 0.1;
        const cam = new g.camera.position.constructor(), look = cam.clone();
        s.frame(s, cam, look);
        g.camera.position.copy(cam); g.controls.target.copy(look); g.controls.update();
        await new Promise(r => setTimeout(r, 250));
    }""")
    images.append(Image.open(io.BytesIO(page.screenshot())))
    contact_sheet(images, 3 if WIDTH <= 720 else 2).save(OUT)
    print("wrote", OUT)
report_errors(errors)
