# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy"]
# ///
"""How the exported web sounds sit on the headset: where each one's energy is by band, and how
loud (A-weighted) a big explosion is at a distance against the gun's continuous stream.

    uv run tools/sound_balance.py [reference-distance]

Explosions in BattleAudio play at gain 1.5 · reference / (reference + 1.5 · (d − reference)); the
gun is a round every 1/60 s at 0.32 through tanh(2.2). The headset body (BlastBody) and the gun's
dip under a blast are not modeled here.
"""
import json
import sys
from pathlib import Path

import numpy as np

folder = Path(__file__).parent.parent / "Resources" / "Sounds"
index = json.loads((folder / "web-sounds.json").read_text())
pcm = np.fromfile(folder / "web-sounds.bin", dtype="<i2").astype(np.float64) / 32767
rate = index["sampleRate"]
reference = float(sys.argv[1]) if len(sys.argv) > 1 else 80.0


def sound(name, variant=0):
    offset, length = index["sounds"][name][variant]
    return pcm[offset : offset + length]


def a_weighted(x):
    f = np.fft.rfftfreq(len(x), 1 / rate)
    f2 = f * f
    a = (12194**2 * f2**2) / ((f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194**2))
    return np.fft.irfft(np.fft.rfft(x) * a * 10**0.1, len(x))


def level(x, start, end):
    y = a_weighted(x)[int(start * rate) : int(end * rate)]
    return 10 * np.log10(np.mean(y**2))


edges = [0, 60, 120, 250, 500, 1000, 2000, 4000, 24000]
print("Share of energy by band (Hz):", "  ".join(f"{a}-{b}" for a, b in zip(edges, edges[1:])))
for name in ["big", "thump", "pop", "hit", "splash", "shot"]:
    x = sound(name)
    power = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / rate)
    shares = [power[(f >= a) & (f < b)].sum() / power.sum() for a, b in zip(edges, edges[1:])]
    print(f"  {name:7s}", "  ".join(f"{s * 100:5.1f}%" for s in shares))

gun = np.zeros(int(rate * 2))
shots = index["sounds"]["shot"]
for k in range(120):
    s = sound("shot", k % len(shots)) * 0.32
    i = int(k * rate / 60)
    gun[i : i + len(s)] += s[: len(gun) - i]
gun = np.tanh(2.2 * gun) / np.tanh(2.2)
print(f"\nGun stream: {level(gun, 0.5, 1.5):.1f} dB(A)")
big = sound("big")
print(f"Big explosion, reference {reference:.0f} m (crack 0-20 ms, boom 50-600 ms, tail 0.6-2 s):")
for d in [50, 100, 200, 300, 400]:
    g = 1.5 * reference / (reference + 1.5 * max(0, d - reference))
    x = big * g
    print(f"  {d:3d} m: crack {level(x, 0, 0.02):6.1f}  boom {level(x, 0.05, 0.6):6.1f}  tail {level(x, 0.6, 2):6.1f}")
