#!/usr/bin/env python3
"""Read the bundled callouts' real durations for identical voice-channel scheduling."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
NAMES = json.loads((ROOT / "sounds/callouts.json").read_text())


def duration(name):
    value = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        str(ROOT / "sounds" / (name + ".mp3"))
    ], text=True)
    return name, float(value)


with ThreadPoolExecutor(max_workers=8) as pool:
    durations = dict(pool.map(duration, NAMES))
destination = ROOT / "visionos/Sources/CIWSSimulation/Resources/voice-durations.json"
destination.write_text(json.dumps(durations, indent=2, sort_keys=True) + "\n")
