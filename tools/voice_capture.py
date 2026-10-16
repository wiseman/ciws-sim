# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Record the game's voice traffic live while triggering it through the debug hooks.

Usage: uv run tools/voice_capture.py <out.webm> [scenario]
Spawns and unprompted VLS launches are held so only the scripted events happen. Scenarios
(seconds from the start of the recording):
  full (default, ~100 s):
     1  a friendly is hit (crew reaction, 1MC rescue call, maybe a follow-up)
    25  anti-ship missile hit on our starboard side      47  ... on our port side
    68  routine VLS launch from our ship ("Stand by for missile launch", alarm, launch, "Birds away")
    82  drone hit on our port side (a fire call), then an anti-ship missile that the radar picks
        up ~1 s later, during the fire call: its vampire call is skipped and the fire call plays
        through; 89  a launch answering it (alarm only)
  short (~35 s): a friendly hit, then a missile hit on our starboard side; a vampire during its
     damage-control call (skipped), then another once the net is quiet (called)
Prints the event log (times on the recording's clock; indented lines are voices and alarms, at
the time they're scheduled to start) and the voice state, and any page errors.
Convert with ffmpeg and transcribe (e.g. mlx_whisper) to check what was said when.
"""
import base64
import json
import sys
import time
from pathlib import Path

from _harness import B64_ENCODE_JS, game_page, report_errors

out = sys.argv[1]
scenario = sys.argv[2] if len(sys.argv) > 2 else "full"

# [seconds, label, page-side expression (d: debug hooks)]
SCENARIOS = {
    "full": [
        [1, "friendly hit", "(() => { const f = d.friendlies.find(f => f.alive); d.wreckFriendly(f.id); return `${f.name} ${f.position.x >= 0 ? 'starboard' : 'port'}`; })()"],
        [25, "missile hit, starboard", "d.hitOwnShip('starboard', 'ascm').toArray().map(Math.round)"],
        [47, "missile hit, port", "d.hitOwnShip('port', 'ascm').toArray().map(Math.round)"],
        [68, "routine launch", "d.launchVLS('ship', 90, 'routine')"],
        [82, "drone hit, port", "d.hitOwnShip('port', 'drone').toArray().map(Math.round)"],
        [85, "anti-ship missile spawned", "(window.__vc.ascm = d.spawnAntiShipMissile(), 'ok')"],
        [89, "vampire-response launch", "d.launchVLS('ship', 200, 'response')"],
    ],
    "short": [
        [1, "friendly hit", "(() => { const f = d.friendlies.find(f => f.alive); d.wreckFriendly(f.id); return `${f.name} ${f.position.x >= 0 ? 'starboard' : 'port'}`; })()"],
        [14, "missile hit, starboard", "d.hitOwnShip('starboard', 'ascm').toArray().map(Math.round)"],
        [19, "anti-ship missile spawned", "(window.__vc.ascm = d.spawnAntiShipMissile(), 'ok')"],
        [29, "anti-ship missile spawned", "(window.__vc.ascm = d.spawnAntiShipMissile(), 'ok')"],
    ],
}
events = SCENARIOS[scenario]
seconds = events[-1][0] + 16

RUN_JS = """async ({ events, seconds }) => {
    %s
    const d = window.__ciws.debug, A = window.__ciwsAudio;
    d.holdSpawns(); d.clearThreats(); d.holdVLS();
    window.__vc = { ascm: null };
    const dest = A.ctx.createMediaStreamDestination();
    A.output.connect(dest);
    const rec = new MediaRecorder(dest.stream, { mimeType: 'audio/webm;codecs=opus', audioBitsPerSecond: 192000 });
    const chunks = [], log = [];
    rec.ondataavailable = e => chunks.push(e.data);
    const t0 = A.ctx.currentTime;
    const now = () => +(A.ctx.currentTime - t0).toFixed(2);
    // Log every voice and alarm as it's scheduled (at its start time) and every launch
    const speak = A.speak, play = A.playBuffer;
    A.speak = function (name, buffer, when, ...rest) {
        log.push({ t: +(when - t0).toFixed(2), label: `  voice ${name} (${buffer.duration.toFixed(1)} s)` });
        return speak.call(this, name, buffer, when, ...rest);
    };
    A.playBuffer = function (buffer, when, ...rest) {
        const alarm = buffer === this.buffers.alarm ? 'GQ alarm' : buffer === this.buffers.launchAlarm ? 'launch alarm' : null;
        if (alarm) log.push({ t: +(when - t0).toFixed(2), label: `  ${alarm}` });
        return play.call(this, buffer, when, ...rest);
    };
    let launches = d.vlsLaunches.length;
    rec.start();
    for (const [at, label, expr] of events) {
        setTimeout(() => {
            let result;
            try { result = eval(expr); } catch (err) { result = 'ERROR ' + err.message; }
            log.push({ t: now(), label, result });
        }, at * 1000);
    }
    // Note when the radar picks the missile up, and every voice that starts
    const poll = setInterval(() => {
        const m = window.__vc.ascm;
        if (m && m.detected && !m.logged) { m.logged = true; log.push({ t: now(), label: 'vampire detected' }); }
    }, 20);
    let skipped = A.debugState.cic.skipped;
    const watch = setInterval(() => {
        const c = A.debugState.cic;
        if (c.skipped !== skipped) { log.push({ t: now(), label: '  vampire call skipped (net busy)' }); skipped = c.skipped; }
        if (d.vlsLaunches.length > launches) log.push({ t: now(), label: 'VLS launch' });
        launches = d.vlsLaunches.length;
    }, 50);
    await new Promise(r => setTimeout(r, seconds * 1000));
    clearInterval(poll); clearInterval(watch);
    A.speak = speak; A.playBuffer = play;
    const done = new Promise(r => { rec.onstop = r; });
    rec.stop();
    await done;
    return { audio: toBase64(await new Blob(chunks).arrayBuffer()), log, voice: d.voice,
             names: d.friendlies.map(f => `${f.name}${f.alive ? '' : ' (lost)'}`) };
}""" % B64_ENCODE_JS

with game_page(extra_args=["--autoplay-policy=no-user-gesture-required"]) as (page, errors):
    time.sleep(1.5)
    page.mouse.click(640, 600)   # first gesture initializes audio
    page.click("#audio-toggle")  # unmute
    time.sleep(1.5)              # let the urgent callouts decode
    r = page.evaluate(RUN_JS, {"events": events, "seconds": seconds})
    Path(out).write_bytes(base64.b64decode(r.pop("audio")))
    print("wrote", out)
    print("friendlies:", ", ".join(r["names"]))
    for e in sorted(r["log"], key=lambda e: e["t"]):
        print(f"{e['t']:7.2f}  {e['label']}" + (f"  -> {e['result']}" if e.get("result") is not None else ""))
    print("voice state:", json.dumps(r["voice"]))
report_errors(errors)
