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
import json
import sys
import time

from _harness import game_page, report_errors

learn_seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 45
drive_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 0

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
    examples: all.length, trainSteps: nn.trainSteps, lossEma: nn.lossEma && r3(nn.lossEma),
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


with game_page(console_levels=("error", "warning")) as (page, errors):
    time.sleep(2)
    page.evaluate("() => { localStorage.clear(); window.__ciwsML.NeuralController.reset(); window.trainNeuralImitation(); }")
    time.sleep(learn_seconds)
    print("== after learning", learn_seconds, "s ==")
    print(json.dumps(page.evaluate(PROBE), indent=1))
    print("game over:", page.evaluate("() => document.getElementById('game-over').style.display === 'block'"),
          "| wave:", page.inner_text("#wave-count"), "| time:", page.inner_text("#time-elapsed"))
    if drive_seconds > 0:
        page.evaluate("() => window.setControllerMode('neural')")
        time.sleep(drive_seconds)
        print("== after the net aimed for", drive_seconds, "s ==")
        out = page.evaluate(PROBE)
        print(json.dumps({"aim": out["aim"], "byType": out["byType"], "fireCallAccuracyPct": out["fireCallAccuracyPct"], "session": out["session"]}, indent=1))
        print("game over:", page.evaluate("() => document.getElementById('game-over').style.display === 'block'"),
              "| wave:", page.inner_text("#wave-count"), "| time:", page.inner_text("#time-elapsed"))
report_errors(errors)
