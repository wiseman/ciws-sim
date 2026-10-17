# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy"]
# ///
"""Summarize drone_probe.py output: spawn heights, height entering reach, fate by type/target,
kill range and height. Usage: uv run analyze.py FILE.json [...]"""
import json, sys
import numpy as np
for fn in sys.argv[1:]:
    d = json.load(open(fn))
    done = d['done']
    print(f"== {fn}: {len(done)} threats ended in {d['simTime']} sim s; stats {d['stats']['engagementStats']} score {d['stats']['score']} health {d['stats']['health']}")
    for typ in ('drone', 'mortar', 'ascm'):
        rs = [r for r in done if r['type'] == typ]
        if not rs: continue
        k = [r for r in rs if r['fate'] == 'killed']; l = [r for r in rs if r['fate'] == 'leaked']
        line = f"  {typ:6s} n={len(rs):3d} killed {len(k)} leaked {len(l)} ({100*len(l)/len(rs):.1f}% leak)"
        if typ == 'drone':
            sy = np.array([r['spawn'][1] for r in rs])
            line += f"\n    spawn y: min {sy.min():.1f} p10 {np.percentile(sy,10):.1f} median {np.median(sy):.1f} mean {sy.mean():.1f} p90 {np.percentile(sy,90):.1f} max {sy.max():.1f}"
            ry = np.array([r['reachY'] for r in rs if r['reachY'] is not None])
            if len(ry): line += f"\n    height entering reach (472 from mount): median {np.median(ry):.1f}, range {ry.min():.1f}-{ry.max():.1f}"
            sp = np.array([r['speed'] for r in rs]) * 60
            line += f"\n    speed m/s: {sp.min():.0f}-{sp.max():.0f}"
            if k:
                kr = np.array([r['last'][4] for r in k]); ky = np.array([r['last'][1] for r in k])
                dt = np.array([r['endSimT'] - r['reachSimT'] for r in k if r['reachSimT'] is not None])
                line += f"\n    kill range from mount: median {np.median(kr):.0f} p10 {np.percentile(kr,10):.0f} p90 {np.percentile(kr,90):.0f}; kill height median {np.median(ky):.1f}; time in reach before kill median {np.median(dt):.2f}s"
            for tgt in ('ciws', 'friendly'):
                t = [r for r in rs if r['target'] == tgt]
                if t: line += f"\n    target {tgt}: n={len(t)} leaked {sum(r['fate']=='leaked' for r in t)}"
            fl = [r for r in rs if r['spawn'] and r['samples']]
        print(line)
