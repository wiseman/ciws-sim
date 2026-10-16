# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Check the gun's line of fire against our own ship: sweep the turret around the compass at a few
elevations, cast a ray from the muzzle along the bore, and list the bearings where the ship's
geometry blocks it within 80 units.

Usage: uv run tools/arc_clearance.py
Bearings are degrees clockwise from the bow (-z), as the VLS and callouts use them, in 2-degree
steps. Each blocked sector is listed with the names of the meshes it hits ('hull', 'structure' for
the merged fixed parts, 'radar', 'vls' lids) and the box the hit points fall in (z along the ship,
y up), which says what's in the way.
"""
import json
import time

from _harness import game_page, report_errors

ELEVATIONS = [15, 0, -5, -10]  # degrees; negative is depression

JS = """async (elevations) => {
  const THREE = await import('three');
  const { scene } = window.__ciws;
  const d = window.__ciws.debug; d.holdSpawns(); d.clearThreats();
  const barrels = scene.getObjectByName('barrels');
  const pitchGroup = barrels.parent.parent, yawGroup = pitchGroup.parent, mount = yawGroup.parent;
  const targets = [];
  scene.getObjectByName('ship').traverse(o => { if (o.isMesh && !o.userData.isOutline && o.visible) targets.push(o); });
  const ray = new THREE.Raycaster(); ray.far = 80;
  const saved = [yawGroup.rotation.y, pitchGroup.rotation.x];
  const muzzle = new THREE.Vector3(), dir = new THREE.Vector3();
  const out = {};
  for (const elevation of elevations) {
    const sectors = [];
    for (let b = 0; b < 360; b += 2) {
      const rad = b * Math.PI / 180;
      yawGroup.rotation.y = Math.atan2(Math.sin(rad), -Math.cos(rad));
      pitchGroup.rotation.x = -elevation * Math.PI / 180;
      mount.updateMatrixWorld(true);
      muzzle.set(0, 0, 3.5).applyMatrix4(barrels.matrixWorld);
      dir.set(0, 0, 1).transformDirection(barrels.matrixWorld);
      ray.set(muzzle, dir);
      const hit = ray.intersectObjects(targets, false)[0];
      if (!hit) continue;
      const name = hit.object.name || hit.object.parent.name || '?';
      const { y, z } = hit.point;
      let last = sectors[sectors.length - 1];
      if (!last || last.to !== b - 2) sectors.push(last = { from: b, to: b, hits: new Set(), z: [z, z], y: [y, y] });
      last.to = b;
      last.hits.add(name);
      last.z = [Math.min(last.z[0], z), Math.max(last.z[1], z)];
      last.y = [Math.min(last.y[0], y), Math.max(last.y[1], y)];
    }
    // Join a sector running through north onto the one it continues
    if (sectors.length > 1 && sectors[0].from === 0 && sectors[sectors.length - 1].to === 358) {
      const tail = sectors.pop(), head = sectors[0];
      head.from = tail.from - 360;
      tail.hits.forEach(h => head.hits.add(h));
      head.z = [Math.min(head.z[0], tail.z[0]), Math.max(head.z[1], tail.z[1])];
      head.y = [Math.min(head.y[0], tail.y[0]), Math.max(head.y[1], tail.y[1])];
    }
    const span = ([a, b]) => `${a.toFixed(1)}..${b.toFixed(1)}`;
    out[elevation] = sectors.map(s => `${(s.from + 360) % 360}-${s.to}: ${[...s.hits].join(',')} (z ${span(s.z)}, y ${span(s.y)})`);
  }
  yawGroup.rotation.y = saved[0]; pitchGroup.rotation.x = saved[1];
  return { targets: targets.length, blocked: out };
}"""

with game_page() as (page, errors):
    time.sleep(4)
    result = page.evaluate(JS, ELEVATIONS)
    print("ship meshes tested:", result["targets"])
    for elevation in ELEVATIONS:
        sectors = result["blocked"][str(elevation)]
        print(f"elevation {elevation:+3d} deg:", "; ".join(sectors) if sectors else "clear")
report_errors(errors)
