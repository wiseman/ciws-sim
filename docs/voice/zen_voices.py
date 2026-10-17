# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Run zen mode for N seconds with audio on and log every voice line spoken (clip name, its bucket,
kind, time), our ship's launch warnings (event 'warn', routine or not) and her VLS launches (event
'launch'), and the page's no-repeat window (s).

Usage: uv run docs/voice/zen_voices.py [seconds] out.json [tree]
tree: the checkout to serve and play (default: the one this script is in)."""
import json, sys, time
from pathlib import Path
tree = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(tree.resolve() / "tools"))  # its _harness serves its own page
from _harness import enable_audio, game_page, report_errors
seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 300
out = sys.argv[2]
with game_page(width=960, height=540, audio=True) as (page, errors):
    enable_audio(page, settle=0)
    page.evaluate("""() => {
        const A = window.__ciwsAudio, log = window.__voiceLog = [];
        const now = () => +A.ctx.currentTime.toFixed(2);
        const { say, speak, warnVLSLaunch, playVLSLaunch } = A;
        A.speak = function (name, buffer, when, kind) {
            log.push({ t: now(), at: +when.toFixed(2), name, kind });
            return speak.call(this, name, buffer, when, kind);
        };
        // Every line goes out through say, which names its bucket
        A.say = function (bucket, ...rest) {
            const n = log.length, end = say.call(this, bucket, ...rest);
            if (log.length > n) log[n].bucket = bucket;
            return end;
        };
        A.warnVLSLaunch = function (routine) {
            window.__voiceLog.push({ t: now(), at: now(), event: 'warn', routine });
            return warnVLSLaunch.call(this, routine);
        };
        // Our ship's cells are within a few metres of the origin; the friendlies' far off
        A.playVLSLaunch = function (position, ...rest) {
            if (position.length() < 50) window.__voiceLog.push({ t: now(), at: now(), event: 'launch' });
            return playVLSLaunch.call(this, position, ...rest);
        };
    }""")
    page.keyboard.press("z")
    t0 = time.time()
    while time.time() - t0 < seconds:
        time.sleep(10)
    log = page.evaluate("() => window.__voiceLog")
    cic = page.evaluate("() => window.__ciwsAudio.debugState.cic")
    repeat = page.evaluate("() => window.__ciws.debug.voice.repeat")
    json.dump({"log": log, "cic": cic, "repeat": repeat}, open(out, "w"), indent=1)
    print(len([e for e in log if "name" in e]), "lines;", cic)
report_errors(errors)
