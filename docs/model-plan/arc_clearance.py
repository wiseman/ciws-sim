# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Scratch prototype of a 'line of fire clearance' check: sweep the gun in yaw at a few pitches,
cast a ray from the muzzle along the bore, and report bearings where own-ship geometry blocks it
within 80 units. Bearing is clockwise from the bow (-z), like the VLS/callouts use.
Usage: uv run arc_clearance.py   (run from the repo root so _harness serves index.html)"""
import sys, time, json
sys.path.insert(0, "/Users/wiseman/src/ciws-sim/tools")
from _harness import game_page, report_errors

JS = """async () => {
  const THREE = await import('three');
  const { scene } = window.__ciws;
  const d = window.__ciws.debug; d.holdSpawns(); d.clearThreats();
  const barrels = scene.getObjectByName('barrels');
  const pitchGrp = barrels.parent.parent, yawGrp = pitchGrp.parent;
  const turretRoot = yawGrp.parent;
  const isTurret = o => { for (; o; o = o.parent) if (o === turretRoot) return true; return false; };
  const targets = [];
  scene.traverse(o => { if (o.isMesh && !o.userData.isOutline && !isTurret(o) && o.visible && o.geometry) targets.push(o); });
  const ray = new THREE.Raycaster(); ray.far = 80;
  const saved = [yawGrp.rotation.y, pitchGrp.rotation.x];
  const out = {};
  for (const pitchDeg of [0, -10, 15]) {
    const blocked = [];
    for (let b = 0; b < 360; b += 2) {
      // bearing b clockwise from -z  ->  gun yaw angle atan2(x, z)
      const rad = b * Math.PI / 180;
      const x = Math.sin(rad), z = -Math.cos(rad);
      yawGrp.rotation.y = Math.atan2(x, z);
      pitchGrp.rotation.x = -pitchDeg * Math.PI / 180;
      turretRoot.updateMatrixWorld(true);
      const o = new THREE.Vector3(0, 0, 3.5).applyMatrix4(barrels.matrixWorld);
      const dir = new THREE.Vector3(0, 0, 1).transformDirection(barrels.matrixWorld);
      ray.set(o, dir);
      const hits = ray.intersectObjects(targets, false).filter(h => Math.abs(h.point.x) < 30 && h.point.y > -1.4);
      if (hits.length) blocked.push(b);
    }
    out[pitchDeg] = blocked;
  }
  yawGrp.rotation.y = saved[0]; pitchGrp.rotation.x = saved[1];
  return { targets: targets.length, blocked: out };
}"""
with game_page() as (page, errors):
    time.sleep(4)
    print(json.dumps(page.evaluate(JS)))
report_errors(errors)
