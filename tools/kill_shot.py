# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "pillow"]
# ///
"""Watch the gun kill an anti-ship missile a given distance short of its target, and capture the
explosion (a frame every 0.1 sim s) from one of the game's cameras or from beside the path.

Usage: uv run tools/kill_shot.py OUT_PREFIX [gun|missile|orbit|side|hull] [range] [--slow K] [--friendly N]
  gun, missile: the Phalanx and missile-follow cameras; orbit: the default view; side: a camera
  beside the last stretch of the path, looking across it; hull: out over the water off where it
  would strike, to one side of its path, looking at the hull (for debris clanging off the hull)
  range: how far short of its target (metres) it dies; it can't be killed before then (default 120).
  0 lets it through, to capture its impact on the target
  --slow: run at timeScale K (0.1 is the game's slow motion); the frames stay 0.1 sim s apart
  --friendly: aim it at friendly N instead of our ship
Writes OUT_PREFIX-strip.png and prints the kill point, its range from the gun, and how many debris
pieces clanged off a hull or skipped on the water.
"""
import sys
import time

from _harness import FRAME_CAPTURE_JS, QUIET_SCENE_JS, game_page, report_errors, save_strip

args = sys.argv[1:]
opts = {}
for flag in ("--slow", "--friendly"):
    if flag in args:
        i = args.index(flag)
        opts[flag] = args[i + 1]
        del args[i:i + 2]
prefix = args[0]
view = args[1] if len(args) > 1 else "gun"
kill_range = float(args[2]) if len(args) > 2 else 120
slow = float(opts.get("--slow", 1))
friendly = int(opts["--friendly"]) if "--friendly" in opts else None
SAMPLES = [round(0.1 * i, 2) for i in range(18)]

SETUP_JS = """([view, friendly]) => {
    const c = window.__ciws, d = c.debug;
    if (view === 'gun') c.setCameraMode('phalanx');
    if (view === 'missile') c.setCameraMode('missile');
    const m = d.spawnAntiShipMissile({ targetIndex: friendly });
    m.health = 1e9; // until it's within range
    window.__m = m;
    return true;
}"""

CAPTURE_JS = """async ([view, range, slow, samples]) => {
    const c = window.__ciws, d = c.debug, { camera } = c;
    const T = camera.position.constructor;
    const m = window.__m, aim = m.targetInfo.position.clone();
    // Beside the last stretch: abreast of the middle of it, a little more than its length off the path
    const back = m.mesh.position.clone().sub(aim).setY(0).normalize();
    const across = new T(0, 1, 0).cross(back);
    const look = aim.clone().addScaledVector(back, range * 0.5).setY(3);
    const eye = look.clone().addScaledVector(across, 20 + range * 0.6).setY(9);
    // hull: out over the water off where it would strike, to one side of its path, looking at the hull
    if (view === 'hull') { look.copy(aim).addScaledVector(back, 6).setY(2); eye.copy(aim).addScaledVector(back, 24).addScaledVector(across, 26).setY(8); }
    const fixed = view === 'side' || view === 'hull';
    const pose = () => { if (fixed) { camera.position.copy(eye); camera.lookAt(look); } };
    if (fixed) c.controls.enabled = false;
    const counts0 = d.fx;
    let killedAt = null, killPos = null;
    const frames = await window.__captureFrames({
        samples,
        before: () => {
            pose();
            if (m.health > 1 && m.mesh.position.distanceTo(aim) < range) { m.health = 1; d.setTimeScale(slow); }
        },
        frameTime: () => {
            if (killedAt === null) {
                if (d.missiles.includes(m)) return null; // killed, or (range 0) reached its target
                killedAt = d.simTime;
                killPos = m.mesh.position.clone();
            }
            return d.simTime - killedAt;
        }
    });
    d.setTimeScale(1);
    const fx = d.fx;
    return { frames, killPos: killPos && killPos.toArray().map(x => +x.toFixed(1)),
             toTarget: killPos && +killPos.distanceTo(aim).toFixed(1),
             fromGun: killPos && +killPos.distanceTo(new T(0, c.layout.mountY, 0)).toFixed(1),
             leaked: m.health > 0, clangs: fx.clangs - counts0.clangs, skips: fx.skips - counts0.skips };
}"""

with game_page(dpr=1, console_levels=("error", "warning")) as (page, errors):
    time.sleep(4)
    page.evaluate(QUIET_SCENE_JS, True)
    page.evaluate(FRAME_CAPTURE_JS)
    page.evaluate(SETUP_JS, [view, friendly])
    res = page.evaluate(CAPTURE_JS, [view, kill_range, slow, SAMPLES])
report_errors(errors)

save_strip(res.pop("frames"), f"{prefix}-strip.png")
print(f"{view}: {res}")
