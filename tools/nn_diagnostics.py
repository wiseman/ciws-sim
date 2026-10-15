# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Let the net learn live, probe its accuracy, and optionally let it fly the gun.

Usage: uv run tools/nn_diagnostics.py [learn_seconds] [drive_seconds]
Reports input ranges, fire-label balance, aim accuracy (degrees and miss distance at the
target versus a no-lead baseline), fire-call accuracy, and per-controller rounds/hits/kills.
With drive_seconds > 0 the net then aims the gun (learning stays on) for that long.
"""
import http.server, json, socketserver, sys, threading, time
from functools import partial
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
learn_seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 45
drive_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 0
handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
handler.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

PROBE = r"""() => {
  const M = window.__ciwsML, nn = M.NeuralController, C = M.consts;
  const all = nn.liveReplay.concat(nn.liveValidation);
  const val = nn.liveValidation;
  const names = ['range', 'closing', 'sideways', 'vertical', 'sinEl', 'cosEl', 'mortar'];
  const r3 = x => +x.toFixed(3);
  const inputs = names.map((name, i) => {
    const xs = all.map(s => s.inputs[i]);
    return { name, min: r3(Math.min(...xs)), max: r3(Math.max(...xs)), absMean: r3(xs.reduce((a, x) => a + Math.abs(x), 0) / xs.length) };
  });
  const pct = (arr, q) => { const a = arr.slice().sort((x, y) => x - y); return a[Math.floor(q * (a.length - 1))]; };
  const rangeOf = s => (s.inputs[0] + 1) * C.NN_REACH;
  // Outputs are sideways and vertical lead angles, so their difference is (to first order) the miss angle
  const aimErr = (out, s) => Math.hypot((out[0] - s.targets[0]) * C.NN_YAW_SCALE, (out[1] - s.targets[1]) * C.NN_PITCH_SCALE);
  const summarize = (set, f) => {
    if (!set.length) return null;
    const deg = set.map(s => f(s) * 180 / Math.PI);
    const miss = set.map(s => f(s) * rangeOf(s));
    return {
      n: set.length,
      medianDeg: r3(pct(deg, 0.5)), p90Deg: r3(pct(deg, 0.9)),
      medianMissUnits: +pct(miss, 0.5).toFixed(2),
      within1UnitPct: +(miss.filter(m => m < 1).length / miss.length * 100).toFixed(1)
    };
  };
  const inReach = val.filter(s => s.targets[2] > 0.5);
  const fireRight = val.filter(s => (M.sigmoid(nn.predict(s.inputs)[2]) > 0.5) === (s.targets[2] > 0.5)).length;
  return {
    examples: all.length, adamSteps: nn.trainedSamples, lossEma: nn.lossEma && r3(nn.lossEma),
    inputs,
    fireLabelInReachPct: +(all.filter(s => s.targets[2] > 0.5).length / all.length * 100).toFixed(1),
    aim: {
      netAll: summarize(val, s => aimErr(nn.predict(s.inputs), s)),
      zeroLeadAll: summarize(val, s => aimErr([0, 0], s)),
      netInReach: summarize(inReach, s => aimErr(nn.predict(s.inputs), s)),
      zeroLeadInReach: summarize(inReach, s => aimErr([0, 0], s))
    },
    fireCallAccuracyPct: +(fireRight / val.length * 100).toFixed(1),
    byType: {
      drone: summarize(inReach.filter(s => s.inputs[6] < 0), s => aimErr(nn.predict(s.inputs), s)),
      mortar: summarize(inReach.filter(s => s.inputs[6] > 0), s => aimErr(nn.predict(s.inputs), s)),
      under150: summarize(inReach.filter(s => rangeOf(s) < 150), s => aimErr(nn.predict(s.inputs), s)),
      from150to480: summarize(inReach.filter(s => rangeOf(s) >= 150), s => aimErr(nn.predict(s.inputs), s))
    },
    session: JSON.parse(JSON.stringify(M.engagementStats))
  };
}"""

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1280, "height": 760})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: m.type in ("error", "warning") and errors.append(m.text))
    pg.goto(f"http://127.0.0.1:{port}/index.html")
    time.sleep(2)
    pg.evaluate("() => { localStorage.clear(); window.__ciwsML.NeuralController.reset(); window.trainNeuralImitation(); }")
    time.sleep(learn_seconds)
    print("== after learning", learn_seconds, "s ==")
    print(json.dumps(pg.evaluate(PROBE), indent=1))
    print("game over:", pg.evaluate("() => document.getElementById('game-over').style.display === 'block'"),
          "| wave:", pg.inner_text("#wave-count"), "| time:", pg.inner_text("#time-elapsed"))
    if drive_seconds > 0:
        pg.evaluate("() => window.setControllerMode('neural')")
        time.sleep(drive_seconds)
        print("== after the net aimed for", drive_seconds, "s ==")
        out = pg.evaluate(PROBE)
        print(json.dumps({"aim": out["aim"], "byType": out["byType"], "fireCallAccuracyPct": out["fireCallAccuracyPct"], "session": out["session"]}, indent=1))
        print("game over:", pg.evaluate("() => document.getElementById('game-over').style.display === 'block'"),
              "| wave:", pg.inner_text("#wave-count"), "| time:", pg.inner_text("#time-elapsed"))
    if errors:
        print("errors:", errors)
    b.close()
srv.shutdown()
