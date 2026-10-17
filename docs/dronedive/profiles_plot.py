# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "matplotlib"]
# ///
"""Altitude vs range to target: measured current drones (drone_probe.py output) beside the
proposed cruise-pushover-dive profiles (dive_sim.py's model). Usage: uv run profiles_plot.py OUT.png base-w3.json"""
import json, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

src = open("dive_sim.py").read().split("# ---------------- 1.")[0]
ns = {"__name__": "dive_sim"}
exec(src, ns)
Drone, fly = ns["Drone"], ns["fly"]

out, probe = sys.argv[1], sys.argv[2]
d = json.load(open(probe))
fig, axes = plt.subplots(1, 2, figsize=(13, 4.2), sharey=True)
ax = axes[0]
for r in d["done"]:
    if r["type"] != "drone" or not r["samples"]:
        continue
    s = np.array(r["samples"])
    ax.plot(s[:, 0], s[:, 1], color="#c0392b" if r["fate"] == "leaked" else "#7f8c8d", lw=0.8, alpha=0.7)
ax.set_title("Current drones (measured, wave 3): straight line from 20-60 m")
ax.set_xlabel("horizontal range to target (m)"); ax.set_ylabel("height (m)")
ax.set_xlim(620, 0); ax.grid(alpha=0.3)
ax = axes[1]
cols = {30: "#2e86c1", 40: "#28b463", 50: "#d68910", 60: "#8e44ad"}
for h in (30, 60, 90):
    for dive in (30, 40, 50, 60):
        dr = Drone("dive", h, 0.9, trigger_deg=dive, turn_dps=45)
        p = fly(dr)
        P = np.array([q[0] for q in p])
        hr = np.hypot(P[:, 0] - dr.target[0], P[:, 2] - dr.target[2])
        ax.plot(hr, P[:, 1], color=cols[dive], lw=1.2, label=f"dive {dive} deg" if h == 90 else None)
ax.axhline(6, color="k", lw=0.5, ls=":")
ax.set_title("Proposed: level cruise at 30-90 m, pushover, dive (45 deg/s turn)")
ax.set_xlabel("horizontal range to target (m)"); ax.set_xlim(620, 0); ax.grid(alpha=0.3); ax.legend(loc="upper left")
fig.tight_layout(); fig.savefig(out, dpi=110)
print("wrote", out)
