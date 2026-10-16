# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Render counts for the friendlies: per friendly (meshes incl. outlines, triangles) and for a
fixed overhead view of the whole field (draw calls, triangles), spawns held and threats cleared.

Usage: uv run docs/model-plan/scratch/friendly_counts.py [N]   (from the build's root; copy it
into tools/ to use the harness). Averages N page loads (friendly placement is random).
"""
import json
import sys
import time

from _harness import game_page, report_errors

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
COUNT_JS = """() => {
    const { renderer, scene, camera, controls } = window.__ciws, d = window.__ciws.debug;
    d.holdSpawns(); d.clearThreats();
    document.getElementById('hud').style.display = 'none';
    const tris = g => (g.index ? g.index.count : g.getAttribute('position').count) / 3;
    const per = d.friendlies.map(f => {
        let meshes = 0, outlines = 0, triangles = 0;
        f.mesh.traverse(o => { if (o.isMesh) { meshes++; if (o.userData.isOutline) outlines++; triangles += tris(o.geometry); } });
        return { meshes, outlines, triangles };
    });
    const views = { overhead: [[0, 330, 40], [0, 0, 0]], overview: [[-120, 78, 95], [45, 0, -5]] };
    const out = { perFriendly: per[0], positions: d.friendlies.map(f => [Math.round(f.position.x), Math.round(f.position.z)]) };
    return new Promise(resolve => {
        const names = Object.keys(views);
        const next = i => {
            if (i === names.length) return resolve(out);
            const [p, t] = views[names[i]];
            controls.maxDistance = Infinity;
            camera.position.set(...p); controls.target.set(...t); controls.update();
            requestAnimationFrame(() => requestAnimationFrame(() => {
                const r = renderer.info.render;
                out[names[i]] = { calls: r.calls, triangles: r.triangles };
                next(i + 1);
            }));
        };
        setTimeout(() => next(0), 300);
    });
}"""

for i in range(N):
    with game_page() as (page, errors):
        time.sleep(3)
        print(json.dumps(page.evaluate(COUNT_JS)))
    report_errors(errors)
