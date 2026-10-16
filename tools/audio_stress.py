# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Measure how hard a busy combat scene works the audio graph.

Usage: uv run tools/audio_stress.py [runs]
Renders 10 s of heavy combat (continuous gunfire, flak, hits, near-miss whizzes, airbursts,
12 drones, 4 mortars and 3 anti-ship missiles, two VLS launches, the general alarm and a
"vampire" callout, ambience) through the game's own graph in an OfflineAudioContext and
reports render time as a fraction of real time. Above ~0.5 the real-time audio thread has
little headroom and will start to glitch (crackle) on slower machines.
"""
import json
import sys
import time

from _harness import game_page, report_errors

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3

JS = """async ({ threats, oneShots, gun }) => {
  const { camera } = window.__ciws;
  const V = camera.position.constructor;
  const sr = 48000, seconds = 10;
  const ctx = new OfflineAudioContext(2, sr * seconds, sr);
  const A = await window.__ciwsAudio.makeOffline(ctx, 'extreme');
  // Sounds are all scheduled up front, so bypass the live-play voice cap (it counts sounds
  // that haven't ended yet, which here would be all of them)
  A.activeOneShots = -1e9;
  camera.position.set(-15, 10, 20); camera.lookAt(0, 5, 0); camera.updateMatrixWorld();
  A.refreshListener();
  A.updateSpatializer(A.gunSpatial, new V(0, 5, 3.5), 0);
  A.updateSpatializer(A.mountSpatial, new V(0, 4, 0), 0);

  // Incoming threats around the ship
  for (let i = 0; i < (threats ? 19 : 0); i++) {
    const type = i >= 16 ? 'ascm' : i >= 12 ? 'mortar' : 'drone';
    const mortar = type === 'mortar', a = i / 19 * Math.PI * 2, d = 150 + i * 30;
    const missile = { type, mesh: { position: new V(Math.cos(a) * d, mortar ? 120 : 40, Math.sin(a) * d) },
                      velocity: new V(-Math.cos(a), mortar ? -2 : -0.1, -Math.sin(a)) };
    A.updateThreats.call(A, [missile]); // builds and positions a voice
    A.threatVoices.clear();             // keep it alive (don't release it on the next call)
  }
  // Gunfire for the whole window, plus the flak, hits, whizzes and airbursts it causes
  if (gun) for (let t = 0.05; t < seconds; t += 1 / 60) A.queueShot(t);
  const rnd = (a, b) => a + Math.random() * (b - a);
  let shots = 0;
  for (let t = 0.1; oneShots && t < seconds - 1; t += 1 / 60) {
    const ang = rnd(0, Math.PI * 2);
    if (Math.random() < 1 / 4) { A.playExplosion(new V(Math.cos(ang) * 420, 80, Math.sin(ang) * 420), 'flak', { at: t }); shots++; }
    if (Math.random() < 1 / 12) A.playExplosion(new V(Math.cos(ang) * 150, 40, Math.sin(ang) * 150), 'hit', { at: t });
    if (Math.random() < 1 / 12) A.playAt(A.buffers.whizz[0], new V(-12, 10, 14), { delay: t, refDistance: 3, gain: 0.55, spread: 0.15, wet: 0.05 });
    if (Math.random() < 1 / 120) A.playExplosion(new V(Math.cos(ang) * 250, 60, Math.sin(ang) * 250), 'airburst', { at: t });
  }
  if (oneShots) {
    A.announceVampire(270);
    [2, 6].forEach(t => A.playVLSLaunch(new V(1, 0.2, 19), 1, { at: t }));
  }
  const scheduled = A.activeOneShots + 1e9;
  const t0 = performance.now();
  await ctx.startRendering();
  const ms = performance.now() - t0;
  return { renderSeconds: ms / 1000, realtimeFraction: ms / 1000 / seconds, oneShotsScheduled: scheduled };
}"""

with game_page(width=800, height=500) as (page, errors):
    time.sleep(1.5)
    scenes = {
        "full combat": {"threats": True, "oneShots": True, "gun": True},
        "gun + ambience only": {"threats": False, "oneShots": False, "gun": True},
        "threat voices only": {"threats": True, "oneShots": False, "gun": False},
        "explosions/flak/hits only": {"threats": False, "oneShots": True, "gun": False},
    }
    for name, opts in scenes.items():
        results = [page.evaluate(JS, opts) for _ in range(runs)]
        frac = sorted(r["realtimeFraction"] for r in results)[len(results) // 2]
        print(f"{name:28s} median {frac:.2f} of real time  (one-shots scheduled: {results[0]['oneShotsScheduled']})")
report_errors(errors)
