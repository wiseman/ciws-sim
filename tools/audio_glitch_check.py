# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "numpy"]
# ///
"""Look for crackle sources in the game's audio output.

Usage: uv run tools/audio_glitch_check.py [seconds] [camera] [out.f32]
camera: orbit (default) | gun | missile

Captures the exact float samples leaving the limiter with an AudioWorklet (no codec), then
reports: peak level and samples at/over full scale (clipping at the output), and abrupt
sample-to-sample jumps (clicks from discontinuities). Also reports audio-thread load and
dropped frames when the browser exposes them (renderCapacity / playoutStats).
"""
import base64
import sys
import time

import numpy as np

from _harness import B64_ENCODE_JS, game_page, report_errors

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 20
camera = sys.argv[2] if len(sys.argv) > 2 else "orbit"
raw_out = sys.argv[3] if len(sys.argv) > 3 else None

RECORDER = """
registerProcessor('tap', class extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input.length) this.port.postMessage([input[0].slice(), (input[1] || input[0]).slice()]);
    return true;
  }
});
"""

CAPTURE = """async ([seconds, recorderSrc]) => {
  %s
  const A = window.__ciwsAudio, ctx = A.ctx;
  const url = URL.createObjectURL(new Blob([recorderSrc], { type: 'application/javascript' }));
  await ctx.audioWorklet.addModule(url);
  const tap = new AudioWorkletNode(ctx, 'tap', { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 2, channelCountMode: 'explicit' });
  A.output.connect(tap);
  const L = [], R = [];
  tap.port.onmessage = e => { L.push(e.data[0]); R.push(e.data[1]); };
  const stats = { hasRenderCapacity: 'renderCapacity' in ctx, hasPlayoutStats: 'playoutStats' in ctx, load: [] };
  if (stats.hasRenderCapacity) {
    ctx.renderCapacity.addEventListener('update', e => stats.load.push({ avg: e.averageLoad, peak: e.peakLoad, underrun: e.underrunRatio }));
    ctx.renderCapacity.start({ updateInterval: 1 });
  }
  const before = stats.hasPlayoutStats ? { ...ctx.playoutStats.toJSON() } : null;
  await new Promise(r => setTimeout(r, seconds * 1000));
  A.output.disconnect(tap);
  if (stats.hasRenderCapacity) ctx.renderCapacity.stop();
  if (stats.hasPlayoutStats) stats.playout = { before, after: ctx.playoutStats.toJSON() };
  const n = L.reduce((a, b) => a + b.length, 0);
  const inter = new Float32Array(n * 2);
  let o = 0;
  for (let i = 0; i < L.length; i++) for (let j = 0; j < L[i].length; j++) { inter[o++] = L[i][j]; inter[o++] = R[i][j]; }
  return { pcm: toBase64(inter.buffer), sampleRate: ctx.sampleRate, stats };
}""" % B64_ENCODE_JS

with game_page(extra_args=["--autoplay-policy=no-user-gesture-required"]) as (page, errors):
    time.sleep(1.5)
    page.mouse.click(640, 600)
    page.click("#audio-toggle")
    for _ in range({"orbit": 0, "gun": 1, "missile": 2}[camera]):
        page.click("#camera-toggle")
    time.sleep(1)
    result = page.evaluate(CAPTURE, [seconds, RECORDER])
report_errors(errors)

pcm = np.frombuffer(base64.b64decode(result["pcm"]), dtype=np.float32).reshape(-1, 2)
sr = result["sampleRate"]
if raw_out:
    pcm.tofile(raw_out)
peak = float(np.abs(pcm).max())
print(f"captured {len(pcm) / sr:.1f} s at {sr} Hz")
print(f"peak {20 * np.log10(peak + 1e-12):+.2f} dBFS | samples >= 0.999: {int((np.abs(pcm) >= 0.999).sum())} | over 1.0: {int((np.abs(pcm) > 1.0).sum())}")

# Clicks: a jump far larger than the signal's recent slope. Compare each sample-to-sample
# step with the median step size over the surrounding 5 ms.
win = int(sr * 0.005)
for ch, name in ((0, "L"), (1, "R")):
    x = pcm[:, ch].astype(np.float64)
    step = np.abs(np.diff(x))
    pad = np.pad(step, (win, win), mode="edge")
    local = np.lib.stride_tricks.sliding_window_view(pad, 2 * win + 1)[:len(step)]
    med = np.median(local, axis=1) + 1e-6
    ratio = step / med
    clicks = np.where((ratio > 40) & (step > 0.02))[0]
    # merge clicks within 2 ms into one event
    events = []
    for idx in clicks:
        if not events or idx - events[-1] > sr * 0.002:
            events.append(idx)
    print(f"{name}: {len(events)} click-like jumps" + (f" (first at {', '.join(f'{e / sr:.3f}s' for e in events[:8])})" if events else ""))

st = result["stats"]
print("renderCapacity available:", st["hasRenderCapacity"], "| playoutStats available:", st["hasPlayoutStats"])
if st["load"]:
    loads = st["load"]
    print(f"audio thread load avg {np.mean([l['avg'] for l in loads]):.2f}, peak {max(l['peak'] for l in loads):.2f}, underrun ratio max {max(l['underrun'] for l in loads):.3f}")
if st.get("playout"):
    print("playoutStats:", st["playout"])
