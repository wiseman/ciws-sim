# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Compare gunsight poses side by side in one frame (3 columns), during an ASCM engagement.
Columns: demo_video's sight (eye on the gun block, fov 45) | a raised sight (eye 1.9 above, behind
the block, fov 32) | the in-game PHALANX over-the-shoulder pose (fov 60). Also records draw calls
for a 3-pane frame."""
import sys, time, json
from pathlib import Path
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)

JS = r"""() => {
  const { scene, camera, renderer, layout } = window.__ciws;
  const d = window.__ciws.debug;
  const T = camera.position.constructor;
  const gunBlock = scene.getObjectByName('barrels').parent;
  const sky = scene.children.find(o => o.isMesh && o.renderOrder === -1);
  const mk = fov => new camera.constructor(fov, 1, 0.25, 4000);
  const cams = [mk(45), mk(32), mk(60)];
  const pose = () => {
    gunBlock.updateWorldMatrix(true, false);
    const M = gunBlock.matrixWorld;
    cams[0].position.set(0, 0.95, 0.6).applyMatrix4(M); cams[0].lookAt(new T(0, 0.95, 200).applyMatrix4(M));
    cams[1].position.set(0, 1.9, -1.2).applyMatrix4(M); cams[1].lookAt(new T(0, 1.9, 200).applyMatrix4(M));
    // in-game mode 1: turretPitch world pose + offset (4, 2.5, -6), rotated 180 about Y
    const pitch = gunBlock.parent;  // assume the gun block hangs off the pitch node
    const q = pitch.getWorldQuaternion(new THREE_Q());
    const p = pitch.getWorldPosition(new T());
    cams[2].position.copy(p).add(new T(4.0, 2.5, -6.0).applyQuaternion(q));
    cams[2].quaternion.copy(q); cams[2].rotateY(Math.PI);
  };
  const THREE_Q = camera.quaternion.constructor;
  const render = renderer.render.bind(renderer);
  renderer.info.autoReset = false;
  window.__three = { calls: [] };
  renderer.render = (sc, cam) => {
    pose();
    renderer.info.reset();
    const s = renderer.getSize(new T()); const W = s.x, H = s.y, gap = 3, w = Math.floor((W - 2 * gap) / 3);
    renderer.setScissorTest(true);
    renderer.setScissor(0, 0, W, H); const cc = renderer.getClearColor(new scene.background.constructor());
    renderer.setClearColor(0x101418); renderer.clear(); renderer.setClearColor(cc);
    cams.forEach((c, i) => {
      const x = i * (w + gap);
      c.aspect = w / H; c.updateProjectionMatrix();
      if (sky) sky.position.copy(c.position);
      renderer.setViewport(x, 0, w, H); renderer.setScissor(x, 0, w, H);
      render(sc, c);
    });
    if (sky) sky.position.copy(cam.position);
    renderer.setViewport(0, 0, W, H); renderer.setScissorTest(false);
    window.__three.calls.push(renderer.info.render.calls);
  };
  return gunBlock.parent.name || gunBlock.parent.type;
}"""
SPAWN = """(angle) => { const d = window.__ciws.debug; const r = Math.random; Math.random = () => angle / (Math.PI*2);
  try { window.__v = d.spawnAntiShipMissile(null); } finally { Math.random = r; } }"""
with game_page(width=1800, height=700, dpr=2) as (page, errors):
    page.add_style_tag(content="#hud, #radar, #center-reticle { display: none !important; }")
    time.sleep(6)
    page.evaluate("() => { const d = window.__ciws.debug; d.holdSpawns(); d.clearThreats(); }")
    print("pitch node:", page.evaluate(JS))
    time.sleep(1)
    page.evaluate(SPAWN, 0.35)
    t0 = time.time(); n = 0
    while time.time() - t0 < 12:
        r = page.evaluate("() => window.__ciws.debug.missiles.includes(window.__v) ? window.__v.mesh.position.length() : -1")
        if r < 0: break
        if r < 900 and n == 0 or r < 650 and n == 1 or r < 540 and n == 2:
            page.screenshot(path=str(out / f"sights-{n}-r{int(r)}.png")); n += 1
        time.sleep(0.03)
    calls = page.evaluate("() => window.__three.calls.slice(-60)")
    print("3-pane calls/frame (avg of last 60):", sum(calls) / len(calls))
report_errors(errors)
