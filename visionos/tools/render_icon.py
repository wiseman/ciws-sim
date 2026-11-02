# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Renders the visionOS app icon's layers from the web app's own scene.

Usage: uv run visionos/tools/render_icon.py [OUT_DIR]
OUT_DIR defaults to App/Assets.xcassets/AppIcon.solidimagestack. Poses the Phalanx low on the
deck with its barrels raised, looks up at it from beside the mount and renders three 1024x1024
layers, each at twice the size and then reduced:
  Back    sky, sea and distant islands (opaque)
  Middle  the clouds (transparent)
  Front   the mount (transparent)
Also writes icon-preview.png beside this script's icon/ folder: the layers flattened and masked
to the circle the headset shows.
"""
import base64
import io
import json
import sys
import time
from pathlib import Path

VISIONOS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VISIONOS.parent / "tools"))
from _harness import QUIET_SCENE_JS, game_page, report_errors  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

SIZE = 1024
SCALE = 2
out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else VISIONOS / "App/Assets.xcassets/AppIcon.solidimagestack"

# Math.random is seeded so the islands and the clouds' puffs come out the same each time
SEED_JS = """{
    let seed = 7;
    Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
}"""

# Mount-relative camera: position, target and vertical field of view; gun yaw (0 = along +z) and
# pitch (negative is up)
SHOT = {
    "camera": [-11.5, 3.2, 13.5],
    "target": [0.2, 5.7, 0.1],
    "fov": 42,
    "yaw": 0.3,
    "pitch": -0.72,
    # Clouds kept, each at a point in the frame (x and y from -1 to 1, up is +y) and a distance
    "clouds": [[-0.42, 0.5, 420], [0.78, 0.02, 520], [-0.82, 0.08, 620]],
}

RENDER_JS = """(shot) => {
    const { scene, camera, controls, renderer } = window.__ciws;
    document.getElementById('radar').style.display = 'none';
    window.__ciws.debug.holdFire(true);
    const mount = scene.getObjectByName('barrels').parent.parent.parent.parent;
    const barrels = scene.getObjectByName('barrels');
    const pitchGroup = barrels.parent.parent, yawGroup = pitchGroup.parent;
    yawGroup.rotation.y = shot.yaw; pitchGroup.rotation.x = shot.pitch;

    const T = camera.position.constructor;
    const base = mount.getWorldPosition(new T());
    controls.maxPolarAngle = Math.PI;
    camera.position.copy(base).add(new T(...shot.camera));
    controls.target.copy(base).add(new T(...shot.target));
    camera.fov = shot.fov;
    camera.aspect = 1;
    camera.updateProjectionMatrix();
    controls.update();
    camera.updateMatrixWorld();

    // Clouds are groups of puffs sharing one geometry. The first few are moved to their places in
    // the frame, facing the camera; the rest are hidden.
    const isCloud = o => o.isGroup && o.children.length > 0
        && o.children.every(c => c.isMesh && c.geometry === o.children[0].geometry);
    const forward = camera.getWorldDirection(new T());
    const right = forward.clone().cross(camera.up).normalize(), up = right.clone().cross(forward);
    const reach = Math.tan(shot.fov * Math.PI / 360);
    const clouds = scene.children.filter(isCloud);
    clouds.forEach((cloud, i) => {
        const place = shot.clouds[i];
        if (!place) { cloud.visible = false; return; }
        const [x, y, distance] = place;
        cloud.position.copy(camera.position).addScaledVector(forward, distance)
            .addScaledVector(right, x * reach * distance).addScaledVector(up, y * reach * distance);
        cloud.lookAt(camera.position.x, cloud.position.y, camera.position.z);
    });
    const isLight = o => o.isLight || (o.isObject3D && !o.isMesh && !o.isGroup && o.children.length === 0);
    const layers = {
        Back: o => o !== mount && !isCloud(o) && o.name !== 'ship',
        Middle: o => isCloud(o),
        Front: o => o === mount,
    };
    const original = renderer.render.bind(renderer);
    renderer.render = () => {};  // hold the game's frames while the layers are drawn
    const saved = scene.children.map(o => o.visible), background = scene.background;
    const shots = {};
    for (const [name, keep] of Object.entries(layers)) {
        scene.children.forEach((o, i) => { o.visible = saved[i] && (isLight(o) || keep(o)); });
        const opaque = name === 'Back';
        scene.background = opaque ? background : null;
        renderer.setClearColor(0x000000, opaque ? 1 : 0);
        original(scene, camera);
        shots[name] = renderer.domElement.toDataURL('image/png').split(',')[1];
    }
    scene.children.forEach((o, i) => { o.visible = saved[i]; });
    scene.background = background;
    renderer.render = original;
    return shots;
}"""

with game_page(width=SIZE, height=SIZE, dpr=SCALE, init_script=SEED_JS) as (page, errors):
    time.sleep(4)
    page.evaluate(QUIET_SCENE_JS, True)
    time.sleep(1.5)
    shots = page.evaluate(RENDER_JS, SHOT)
report_errors(errors)

layers = {}
for name, data in shots.items():
    image = Image.open(io.BytesIO(base64.b64decode(data)))
    image = image.convert("RGB" if name == "Back" else "RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    layer_dir = out_dir / f"{name}.solidimagestacklayer"
    (layer_dir / "Content.imageset").mkdir(parents=True, exist_ok=True)
    image.save(layer_dir / "Content.imageset" / f"{name}.png")
    (layer_dir / "Content.imageset" / "Contents.json").write_text(json.dumps({
        "images": [{"filename": f"{name}.png", "idiom": "vision", "scale": "2x"}],
        "info": {"author": "xcode", "version": 1},
    }, indent=2) + "\n")
    (layer_dir / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
    layers[name] = image
(out_dir / "Contents.json").write_text(json.dumps({
    "info": {"author": "xcode", "version": 1},
    "layers": [{"filename": f"{name}.solidimagestacklayer"} for name in ("Front", "Middle", "Back")],
}, indent=2) + "\n")

preview = layers["Back"].convert("RGBA")
preview.alpha_composite(layers["Middle"])
preview.alpha_composite(layers["Front"])
mask = Image.new("L", (SIZE * 4, SIZE * 4), 0)
ImageDraw.Draw(mask).ellipse((0, 0, SIZE * 4, SIZE * 4), fill=255)
preview.putalpha(mask.resize((SIZE, SIZE), Image.LANCZOS))
preview_path = VISIONOS / "icon" / "icon-preview.png"
preview_path.parent.mkdir(exist_ok=True)
preview.save(preview_path)
print("wrote", out_dir, "and", preview_path)
