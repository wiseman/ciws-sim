# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Render a fixed sequence of game sounds offline (OfflineAudioContext) for listening/analysis.

Usage: uv run tools/audio_lab.py <out.wav>
Timeline (listener at the default orbit camera, ~25 m from the gun):
  0.0 s  2 s gun burst          3.0 s  three hits at 150 m     4.0 s  airburst at 250 m
  8.0 s  flak pops at 400 m     9.5 s  water impact at 60 m    13.0 s deck impact at 15 m
"""
import base64, http.server, socketserver, sys, threading, time
from functools import partial
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
out = sys.argv[1]

handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
handler.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

JS = """async () => {
  const A0 = window.__ciwsAudio;
  const { camera } = window.__ciws;
  const V = camera.position.constructor;
  const sr = 48000, seconds = 18;
  const A = Object.create(A0);
  A.ctx = new OfflineAudioContext(2, sr * seconds, sr);
  A.isMuted = false;
  A.slowPitch = 1;
  A.activeOneShots = 0;
  A.debugState = JSON.parse(JSON.stringify(A0.debugState));
  const ctx = A.ctx;
  A.masterGain = ctx.createGain();
  const limiter = ctx.createDynamicsCompressor();
  limiter.threshold.value = -8; limiter.knee.value = 6; limiter.ratio.value = 12;
  limiter.attack.value = 0.002; limiter.release.value = 0.25;
  A.masterGain.connect(limiter); limiter.connect(ctx.destination);
  A.mixBus = ctx.createGain(); A.mixBus.connect(A.masterGain);
  A.reverb = ctx.createConvolver(); A.reverb.buffer = A.buildReverbIR();
  const ret = ctx.createGain(); ret.gain.value = 0.55; A.reverb.connect(ret); ret.connect(A.mixBus);
  A.buildBuffers(); A.buildGun(); A.buildMount(); A.buildAmbient();
  A.isInit = true;
  camera.position.set(-15, 10, 20); camera.lookAt(0, 5, 0); camera.updateMatrixWorld();
  const l = ctx.listener, fwd = new V(0, 0, -1).applyQuaternion(camera.quaternion);
  l.positionX.value = -15; l.positionY.value = 10; l.positionZ.value = 20;
  l.forwardX.value = fwd.x; l.forwardY.value = fwd.y; l.forwardZ.value = fwd.z;
  A.setPannerPosition(A.gunPanner, new V(0, 5, 3.5));
  A.setPannerPosition(A.mountPanner, new V(0, 4, 0));
  // Gun burst with spin-up, driven through the same shot buffers and bus
  let t = 0.1, start = 0.1;
  while (t < 2.1) {
    const src = ctx.createBufferSource();
    src.buffer = A.pick(A.buffers.shot);
    src.playbackRate.value = 0.97 + Math.random() * 0.06;
    const g = ctx.createGain(); g.gain.value = 0.75 + Math.random() * 0.25;
    src.connect(g); g.connect(A.gunBus); src.start(t);
    const spin = Math.min(1, (t - start) / 0.25);
    t += (1 / 60) * (1.6 - 0.6 * spin) + (Math.random() - 0.5) * 0.0008;
  }
  A.driveGain.gain.setValueAtTime(0, 0); A.driveGain.gain.linearRampToValueAtTime(0.16, 0.4);
  A.driveGain.gain.setValueAtTime(0.16, 2.1); A.driveGain.gain.linearRampToValueAtTime(0, 3.0);
  const at = (time, fn) => { const saved = ctx.currentTime; fn(time); };
  // One-shots: use playAt with an explicit start offset (distance delay is added by playExplosion)
  const play = (time, pos, kind, opts) => {
    const orig = A.playAt.bind(A);
    A.playAt = (buf, p, o) => orig(buf, p, { ...o, delay: (o.delay || 0) + time });
    A.playExplosion(pos, kind, 1, opts || {});
    A.playAt = orig;
  };
  const dir = new V(0.3, 0.25, -1).normalize();
  [0, 0.12, 0.2].forEach(dt => play(3.0 + dt, dir.clone().multiplyScalar(150), 'hit'));
  play(4.0, dir.clone().multiplyScalar(250), 'airburst');
  for (let i = 0; i < 6; i++) { A.lastFlakTime = -1; play(8.0 + i * 0.13, new V(-200 + i * 20, 80, -340), 'flak'); }
  play(9.5, new V(-45, 0.75, -20), 'impact', { water: true });
  play(13.0, new V(0, 2, 0), 'impact');
  const buf = await ctx.startRendering();
  // Encode 16-bit WAV
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
  const u8 = new Uint8Array(ab); let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(bin);
}"""

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 800, "height": 500})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(f"http://127.0.0.1:{port}/index.html")
    time.sleep(1.5)
    Path(out).write_bytes(base64.b64decode(pg.evaluate(JS)))
    print("wrote", out)
    for e in errors:
        print("ERROR:", e)
    b.close()
srv.shutdown()
