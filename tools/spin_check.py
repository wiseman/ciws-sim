# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Sample the gun-barrel and drone-prop rotations across frames to confirm they visibly spin.

Usage: uv run tools/spin_check.py [seconds]
Prints the per-frame rotation step of each part. A visible spin needs a nonzero step below
~1/3 of the part's symmetry angle (20 deg for the 6 barrels, 30 deg for the 4-arm prop).
"""
import json
import sys
import time

from _harness import game_page, report_errors

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 20

SAMPLE_JS = """
async () => {
    const { scene } = window.__ciws;
    const parts = () => {
        const out = {};
        scene.traverse(o => {
            if (o.name === 'prop') out['prop:' + o.parent.uuid.slice(0, 6)] = o.rotation.z;
        });
        const barrels = scene.getObjectByName('barrels');
        if (barrels) out.barrels = barrels.rotation.z;
        return out;
    };
    const frames = [];
    for (let i = 0; i < 90; i++) {
        frames.push(parts());
        await new Promise(r => requestAnimationFrame(r));
    }
    return frames;
}
"""

with game_page(console_levels=("error",)) as (page, errors):
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(2)
        frames = page.evaluate(SAMPLE_JS)
        steps = {}
        for a, b in zip(frames, frames[1:]):
            for k in a.keys() & b.keys():
                d = (b[k] - a[k]) % (2 * 3.141592653589793)
                steps.setdefault(k, []).append(d * 57.29578)
        summary = {k: f"{sum(v) / len(v):.1f} deg/frame (max {max(v):.1f})" for k, v in sorted(steps.items())}
        print(json.dumps(summary))
report_errors(errors)
