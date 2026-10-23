# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Enter VR on an emulated headset (Meta's IWER WebXR runtime, as a Quest 3) and check the session:
the camera stands at the deck station facing the mount, the game runs on the headset's frames, a
crew line and a net line come from their places (VOICE_POSITIONS), a blast close by muffles the mix
and shakes the view, and leaving puts the orbit view back. No headset needed; it can't judge
comfort, the look or the sound.

Usage: uv run tools/xr_check.py [page.html]
"""
import json
import sys
import urllib.request

from _harness import enable_audio, game_page, page_arg, report_errors

IWER_URL = "https://unpkg.com/iwer@2.5.0/build/iwer.min.js"

# Headless Chromium has a navigator.xr of its own, with no devices. IWER 2.5 takes an offset space's
# transform as a matrix, so it gets the transform's.
INSTALL_JS = """
new IWER.XRDevice(IWER.metaQuest3).installRuntime({ forceInstall: true });
const offset = XRReferenceSpace.prototype.getOffsetReferenceSpace;
XRReferenceSpace.prototype.getOffsetReferenceSpace = function (t) { return offset.call(this, t.matrix); };
"""

STATE_JS = """
() => {
    const { renderer, camera, debug } = window.__ciws;
    const fwd = camera.getWorldDirection(new camera.position.constructor());
    return {
        presenting: renderer.xr.isPresenting,
        position: camera.position.toArray().map(v => +v.toFixed(2)),
        forward: fwd.toArray().map(v => +v.toFixed(2)),
        fov: +camera.fov.toFixed(1),
        simTime: +debug.simTime.toFixed(2),
        zen: document.body.classList.contains('zen'),
        button: document.getElementById('vr-toggle').style.display !== 'none',
    };
}
"""

# Says a crew line (chat-ears: CREW[2]) and a net line, then sets off an impact 25 units off the
# starboard side of the station; reports where the voices went, the muffle and the view's jitter
BLAST_JS = """
async () => {
    const A = window.__ciwsAudio, { camera, createExplosion } = window.__ciws;
    const crew = await A.getCallout('chat-ears'), net = await A.getCallout('splash');
    A.speak('chat-ears', crew, A.ctx.currentTime + 0.05, 'crew');
    A.speak('splash', net, A.ctx.currentTime + 0.05, 'net');
    const frame = () => new Promise(r => setTimeout(r, 30));
    const eye = camera.position.clone();
    createExplosion(eye.clone().add(new eye.constructor(25, -3, 0)), 'impact');
    let minHz = 20000, jitter = 0;
    for (let i = 0; i < 40; i++) {
        await frame();
        minHz = Math.min(minHz, A.earFilter.frequency.value);
        jitter = Math.max(jitter, camera.position.distanceTo(eye));
    }
    return { speakers: Object.keys(A.speakers), minHz: Math.round(minHz), jitter: +jitter.toFixed(3) };
}
"""

iwer = urllib.request.urlopen(IWER_URL).read().decode()
with game_page(page_path=page_arg(sys.argv), audio=True) as (page, errors):
    page.add_init_script(iwer + "\n" + INSTALL_JS)
    page.reload()
    page.wait_for_function("window.__ciws && document.getElementById('vr-toggle').style.display !== 'none'", timeout=15000)
    enable_audio(page)
    before = page.evaluate(STATE_JS)
    page.click("#vr-toggle")
    page.wait_for_function("window.__ciws.renderer.xr.isPresenting", timeout=10000)
    page.wait_for_timeout(1500)
    inside = [page.evaluate(STATE_JS)]
    page.wait_for_timeout(1500)
    inside.append(page.evaluate(STATE_JS))
    blast = page.evaluate(BLAST_JS)
    page.evaluate("window.__ciws.renderer.xr.getSession().end()")
    page.wait_for_function("!window.__ciws.renderer.xr.isPresenting", timeout=10000)
    page.wait_for_timeout(500)
    after = page.evaluate(STATE_JS)
    print(json.dumps({"before": before, "inside": inside, "blast": blast, "after": after}, indent=1))
    report_errors(errors)
