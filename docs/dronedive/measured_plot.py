# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Measured drone profiles (tools/dive_probe.py --grid output) against the plan's model of the same
drones: height, pitch and speed against range to the aim point in plan.
Usage: uv run docs/dronedive/measured_plot.py OUT.png grid-w3.json [grid-w10.json ...]"""
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

src = (Path(__file__).resolve().parents[2] / "tools" / "dive_probe.py").read_text()
ns = {"math": math}
exec(src[src.index("SPS = 60"):src.index("def turn_rates")], ns)
model = ns["model"]

out, files = sys.argv[1], sys.argv[2:]
fig, axes = plt.subplots(len(files), 3, figsize=(15, 3.6 * len(files)), squeeze=False)
cols = {30: "#2e86c1", 45: "#28b463", 60: "#d68910", 75: "#c0392b", 90: "#8e44ad"}
for row, fn in zip(axes, files):
    d = json.load(open(fn))
    wave = Path(fn).stem.split("-")[-1]
    for r in d["done"]:
        if r["type"] != "drone" or r["target"] != "ciws":
            continue
        s = r["samples"]
        dist = math.hypot(r["spawn"][0] - r["aim"][0], r["spawn"][2] - r["aim"][2])
        prof = model(dist, r["spawn"][1], r["aim"][1], r["gamma"], r["cruise"])["profile"]
        c = cols[round(r["spawn"][1])]
        for ax, k, mk in ((row[0], 2, 1), (row[1], 4, 3), (row[2], 3, 2)):
            scale = 60 if k == 3 else 1
            ax.plot([q[1] for q in s], [q[k] * scale for q in s], color=c, lw=2.2, alpha=0.45)
            ax.plot([q[0] for q in prof], [q[mk] for q in prof], color="k", lw=0.7, ls="--")
    for ax, label in zip(row, ("height (m)", "pitch down (deg)", "speed (m/s)")):
        ax.set_xlim(200, 0); ax.grid(alpha=0.3); ax.set_ylabel(label)
        ax.set_xlabel("range to aim point in plan (m)")
        ax.set_title(f"{wave}: {label.split(' (')[0]} — game (thick) vs plan model (dashed)")
fig.tight_layout(); fig.savefig(out, dpi=100)
print("wrote", out)
