# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Render a fixed sequence of game sounds offline (OfflineAudioContext) for listening/analysis.

Usage: uv run tools/audio_lab.py <out.wav> [natural|wide|extreme]
Builds the game's own audio graph (AudioController.makeOffline) on an offline context, so the
render matches what the game plays. Timeline (listener at the default orbit camera, ~25 m from the gun):
  0.0 s  2 s gun burst (ahead)        3.0 s  three hits, left, ~140 m
  4.0 s  airburst, right, ~250 m      8.0 s  flak pops far ahead
  9.5 s  water impact, left, ~50 m    13.0 s deck impact at the gun
  15.5 s three hits behind the camera
  18.5 s VLS launch from our ship's module   25.5 s anti-ship missile (turbojet voice), ~200 m, 3 s
  29.0 s general alarm, then at 30.5 s the "vampire" callout on the CIC net, with the gun
         firing under it from 31.0 s (the battle ducks under the voice)
"""
import base64
import sys
import time
from pathlib import Path

from _harness import B64_ENCODE_JS, game_page, report_errors

out = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "extreme"

JS = """async (mode) => {
  %s
  const { camera } = window.__ciws;
  const V = camera.position.constructor;
  const sr = 48000, seconds = 36;
  const ctx = new OfflineAudioContext(2, sr * seconds, sr);
  const A = await window.__ciwsAudio.makeOffline(ctx, mode);

  camera.position.set(-15, 10, 20); camera.lookAt(0, 5, 0); camera.updateMatrixWorld();
  A.refreshListener();
  A.updateSpatializer(A.gunSpatial, new V(0, 5, 3.5), 0);
  A.updateSpatializer(A.mountSpatial, new V(0, 4, 0), 0);

  // 2 s gun burst with the game's own spin-up spacing
  const start = 0.1;
  for (let t = start; t < 2.1; t += A.shotSpacing(t - start, 1 / 60)) A.queueShot(t);
  A.driveGain.gain.setValueAtTime(0, 0); A.driveGain.gain.linearRampToValueAtTime(0.16, 0.4);
  A.driveGain.gain.setValueAtTime(0.16, 2.1); A.driveGain.gain.linearRampToValueAtTime(0, 3.0);

  // Explosions placed relative to the camera: ahead, right, height
  const fwd = new V(0, 0, -1).applyQuaternion(camera.quaternion).setY(0).normalize();
  const right = new V().crossVectors(fwd, new V(0, 1, 0)).normalize();
  const place = (ahead, side, height) => camera.position.clone().addScaledVector(fwd, ahead).addScaledVector(right, side).setY(height);
  const boom = (at, pos, kind, water = false) => A.playExplosion(pos, kind, { at, water });
  [0, 0.12, 0.2].forEach(dt => boom(3.0 + dt, place(60, -120, 30), 'hit'));
  boom(4.0, place(120, 220, 60), 'airburst');
  for (let i = 0; i < 6; i++) boom(8.0 + i * 0.13, place(380, -60 + i * 25, 80), 'flak');
  boom(9.5, place(25, -45, 0.75), 'impact', true);
  boom(13.0, new V(0, 2, 0), 'impact');
  [0, 0.12, 0.2].forEach(dt => boom(15.5 + dt, place(-60, 0, 12), 'hit'));

  // VLS launch from the cell module on our foredeck-aft
  A.playVLSLaunch(new V(1, 0.2, 19), 1, { at: 18.5 });

  // A held anti-ship missile voice: built by the game's own update, then gated on and off
  const ascm = { type: 'ascm', mesh: { position: place(150, 120, 4) }, velocity: new V(-1.5, 0, -1.4) };
  A.updateThreats.call(A, [ascm]);
  const voice = A.threatVoices.get(ascm);
  A.threatVoices.clear();
  voice.out.gain.cancelScheduledValues(0);
  voice.out.gain.setValueAtTime(0, 0);
  voice.out.gain.setValueAtTime(0, 25.5);
  voice.out.gain.linearRampToValueAtTime(0.32, 25.7);
  voice.out.gain.setValueAtTime(0.32, 28.3);
  voice.out.gain.linearRampToValueAtTime(0, 28.5);

  // General alarm, the callout ducking the battle, and a burst under it. (GQ is marked as
  // recently called so the 1MC's "General quarters" doesn't follow.)
  A.lastAt.gq = 0;
  A.announceVampire(270, 29.0);
  const g0 = 31.0;
  for (let t = g0; t < 34.0; t += A.shotSpacing(t - g0, 1 / 60)) A.queueShot(t);

  const buf = await ctx.startRendering();
  // Encode 16-bit stereo WAV
  const n = buf.length, ch = 2, bytes = 44 + n * ch * 2, ab = new ArrayBuffer(bytes), dv = new DataView(ab);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); dv.setUint32(4, bytes - 8, true); w(8, 'WAVE'); w(12, 'fmt '); dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true); dv.setUint16(22, ch, true); dv.setUint32(24, sr, true); dv.setUint32(28, sr * ch * 2, true);
  dv.setUint16(32, ch * 2, true); dv.setUint16(34, 16, true); w(36, 'data'); dv.setUint32(40, n * ch * 2, true);
  const L = buf.getChannelData(0), R = buf.getChannelData(1);
  for (let i = 0, o = 44; i < n; i++) {
    dv.setInt16(o, Math.max(-1, Math.min(1, L[i])) * 32767, true); o += 2;
    dv.setInt16(o, Math.max(-1, Math.min(1, R[i])) * 32767, true); o += 2;
  }
  return toBase64(ab);
}""" % B64_ENCODE_JS

with game_page(width=800, height=500) as (page, errors):
    time.sleep(1.5)
    Path(out).write_bytes(base64.b64decode(page.evaluate(JS, mode)))
    print("wrote", out)
report_errors(errors)
