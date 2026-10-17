# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Count draw calls of one render with and without the shadow pass, and time the shadow pass."""
import json, sys, time
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors

JS = """() => {
  const { scene, camera, renderer } = window.__ciws;
  const gl = renderer.getContext();
  const sm = renderer.shadowMap;
  const out = {};
  const one = (label, needs) => {
    sm.autoUpdate = false; sm.needsUpdate = needs;
    gl.finish();
    const t0 = performance.now();
    renderer.info.reset();
    renderer.render(scene, camera);
    gl.finish();
    out[label] = { calls: renderer.info.render.calls, tris: renderer.info.render.triangles, ms: +(performance.now() - t0).toFixed(2) };
  };
  renderer.info.autoReset = false;
  for (let i = 0; i < 3; i++) { one('withShadow', true); one('noShadow', false); }
  let casters = 0, receivers = 0, meshes = 0;
  scene.traverse(o => { if (o.isMesh) { meshes++; if (o.castShadow) casters++; if (o.receiveShadow) receivers++; } });
  out.meshes = meshes; out.casters = casters; out.receivers = receivers;
  out.programs = renderer.info.programs.length;
  out.geometries = renderer.info.memory.geometries;
  sm.autoUpdate = true; renderer.info.autoReset = true;
  return out;
}"""
with game_page(width=1600, height=900, dpr=2) as (page, errors):
    time.sleep(8)
    print(json.dumps(page.evaluate(JS), indent=1))
report_errors(errors)
