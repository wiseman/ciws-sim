# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Record the trailer's takes: short scripted shots of the game, each with its own camera move,
as raw webm recordings (canvas + the game's master audio) for tools/trailer_edit.py to cut.

Usage: uv run tools/trailer_shots.py [TAKE ...] [--size WxH]
With no takes named, records them all. Each take writes trailer/takes/TAKE.webm and TAKE.json:
the recording's length, its marks (seconds into the recording of the moments the edit cuts on,
such as the first shot fired or a kill) and the voice lines the game asked for.

A take is a JS function body run in the page with `K` in scope (see KIT_JS): K.cam(fn) flies the
orbit camera along fn(t) -> {pos, look, fov} (t in real seconds since the take began; the view
shake still applies), K.at(t, fn) schedules, K.mark(name) notes a moment, K.end(t) stops, and
K.watchKills(threats, name) marks each one's end, and with K.trackObj set the take's track
holds that object's screen position and size each frame. The voice lines are muted unless the take sets
K.voices = true.
"""
import base64
import json
import sys
import time
from pathlib import Path

from _harness import B64_ENCODE_JS, ROOT, enable_audio, game_page, report_errors

OUT = ROOT / "trailer" / "takes"
LEAD_IN = 6.0  # game time before a take starts: the scene settles, and a line from the load finishes

KIT_JS = """(takeBody) => new Promise(resolve => {
    const { scene, camera, controls, renderer, layout, setCameraMode } = window.__ciws;
    const d = window.__ciws.debug, A = window.__ciwsAudio;
    const V = camera.position.constructor;
    const t0 = performance.now();
    const now = () => (performance.now() - t0) / 1000;
    const K = {
        d, A, V, scene, camera, controls, layout, setCameraMode, voices: false,
        marks: {}, said: [], camFn: null, track: [], trackObj: null,
        now,
        mark(name) { (K.marks[name] ??= []).push(+now().toFixed(3)); },
        at(t, fn) { setTimeout(fn, Math.max(0, t - now()) * 1000); },
        end(t) { K.at(t, () => rec.stop()); },
        cam(fn) { setCameraMode('off'); K.camFn = fn; },
        // The mount's barrels: where they are and the way they point (flat, unless full)
        mount() { return scene.getObjectByName('barrels').getWorldPosition(new V()); },
        aim(full = false) {
            const b = scene.getObjectByName('barrels');
            const a = new V(0, 0, 1).transformDirection(b.matrixWorld);
            return full ? a : a.setY(0).normalize();
        },
        // A threat moved in along its line of approach to `range` units out (saves waiting)
        closeIn(m, range) {
            const p = m.mesh.position, k = range / Math.hypot(p.x, p.z);
            p.x *= k; p.z *= k;
            m.trackedPosition.copy(p);
            return m;
        },
        drone(angle, range = null, opts = {}) {
            const m = d.spawnDrone({ angle, ...opts });
            return range ? K.closeIn(m, range) : m;
        },
        ascm(angle, range = null, targetIndex = null) {
            const m = d.spawnAntiShipMissile({ angle, targetIndex });
            return range ? K.closeIn(m, range) : m;
        },
        // Marks `name` when each of threats leaves play (shot down, or got through)
        watchKills(threats, name = 'kill') {
            const live = new Set(threats);
            const timer = setInterval(() => {
                for (const m of live) if (!d.missiles.includes(m)) { live.delete(m); K.mark(name); }
                if (!live.size) clearInterval(timer);
            }, 10);
        },
        // Marks 'fire' the first time the gun's rounds are in the air after `after` s
        watchFire(after = 0) {
            const timer = setInterval(() => {
                if (now() >= after && d.rounds > 0) { K.mark('fire'); clearInterval(timer); }
            }, 10);
        },
        lerp: (a, b, k) => a.map((v, i) => v + (b[i] - v) * k),
        ease: k => k < 0 ? 0 : k > 1 ? 1 : k * k * (3 - 2 * k),
    };

    // The take's camera rides in for controls.update (it runs before the view shake is added)
    controls.maxPolarAngle = Math.PI - 0.01;
    const update = controls.update.bind(controls);
    controls.update = () => {
        if (!K.camFn) return update();
        const { pos, look, fov = 60 } = K.camFn(now());
        camera.position.set(...pos);
        controls.target.set(...look);
        camera.lookAt(controls.target);
        if (camera.fov !== fov) { camera.fov = fov; camera.updateProjectionMatrix(); }
        if (K.trackObj) {
            camera.updateMatrixWorld();
            // Where it is on screen (NDC) and how big: the NDC width of 8 units across it
            const p = K.trackObj.position.clone().project(camera);
            const right = new V(1, 0, 0).applyQuaternion(camera.quaternion);
            const q = K.trackObj.position.clone().addScaledVector(right, 8).project(camera);
            K.track.push([+now().toFixed(3), +p.x.toFixed(4), +p.y.toFixed(4), +Math.abs(q.x - p.x).toFixed(4)]);
        }
        return true;
    };

    const play = window.__voicePlay ?? A.play;
    A.play = function (bucket, ...rest) {
        K.said.push([+now().toFixed(2), bucket, K.voices]);
        return K.voices ? play.call(this, bucket, ...rest) : null;
    };

    const audioDest = A.ctx.createMediaStreamDestination();
    A.output.connect(audioDest);
    const stream = new MediaStream([...renderer.domElement.captureStream(60).getVideoTracks(), ...audioDest.stream.getAudioTracks()]);
    const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8,opus', videoBitsPerSecond: 20_000_000, audioBitsPerSecond: 256_000 });
    const chunks = [];
    rec.ondataavailable = e => chunks.push(e.data);
    rec.onstop = () => {
        window.__takeBlob = new Blob(chunks);
        resolve({ size: window.__takeBlob.size, length: now(), marks: K.marks, said: K.said, track: K.track });
    };
    rec.start(1000);
    new Function('K', takeBody)(K);
})"""

SLICE_JS = """async ([start, end]) => {
    %s
    return toBase64(await window.__takeBlob.slice(start, end).arrayBuffer());
}""" % B64_ENCODE_JS

# Setup run before each take (before recording): clear the decks, and the voices muted from here
# (KIT_JS logs them, and lets them through for a take that wants them)
QUIET_JS = """(spawns) => {
    const d = window.__ciws.debug, A = window.__ciwsAudio;
    d.holdVLS(); d.clearThreats();
    if (!spawns) d.holdSpawns();
    const play = A.play;
    window.__voicePlay = play;
    A.play = () => null;
}"""

# The Seahawk's pass for the gag takes: starboard side, bow to stern, from 300 units out
FLYBY_JS = """
    K.d.sight('flyby');
    const s = K.d.sightings.find(s => s.name === 'flyby');
    s.side = 1; s.dir = 1;
    s.mesh.position.set(30, s.mesh.position.y, -300);
    s.mesh.rotation.y = 0;
    K.trackObj = s.mesh;
    const timer = setInterval(() => {
        if (s.scolded && !K.marks.lock) K.mark('lock');
        if (s.mesh.position.z > 160 || !s.alive) { clearInterval(timer); K.end(K.now() + 0.2); }
    }, 10);
"""

# name -> (spawns allowed, JS body). Angles: radians, x = cos, z = sin; our bow is -z.
TAKES = {
    # Cold open: a slow push in, low over the water, onto the mount at rest
    "open": (False, """
        K.cam(t => {
            const k = K.ease(t / 6.5);
            return { pos: K.lerp([46, 5.5, -34], [17, 7.5, -11], k), look: K.lerp([0, 7, 0], [0, 8, 1], k), fov: 38 };
        });
        K.end(6.5);
    """),
    # The mount from low beside it, looking up past the gun at a stream of drones coming in off
    # the starboard bow: it slews, spins up and lets rip
    "mount": (False, """
        const a = -1.1;  // off the starboard bow
        const ds = [K.drone(a, 330, { height: 45 }), K.drone(a + 0.12, 420, { height: 60 }), K.drone(a - 0.1, 520, { height: 50 })];
        K.watchKills(ds); K.watchFire();
        // In profile, the barrels across the frame and the drones beyond
        const dir = [Math.cos(a), Math.sin(a)], side = [-Math.sin(a), Math.cos(a)];
        K.cam(t => {
            const k = K.ease(t / 7), r = 8.5 - 2 * k, back = 2.5 + 1.5 * k;
            return { pos: [0.9 + side[0] * r - dir[0] * back, 8.4, 1.75 + side[1] * r - dir[1] * back],
                     look: [0.9 + dir[0] * 9, 11, 1.75 + dir[1] * 9], fov: 50 };
        });
        K.end(7);
    """),
    # The gun camera, rounds pouring into drones
    "guncam": (False, """
        const a = 2.2;
        const ds = [K.drone(a, 300, { height: 40 }), K.drone(a + 0.2, 380, { height: 55 }), K.drone(a - 0.15, 460, { height: 35 })];
        K.watchKills(ds); K.watchFire();
        K.setCameraMode('phalanx');
        K.end(7);
    """),
    # Our ship's VLS from low on the forecastle: the hatch, the launch, the bird climbing away
    "vls": (False, """
        K.cam(t => ({ pos: [-7, 7.5, 6], look: K.lerp([0, 6, -10.5], [0, 26, -16], K.ease((t - 1.2) / 1.6)), fov: 55 }));
        K.at(0.3, () => { K.d.launchVLS('ship', 300); K.mark('launch'); });
        K.end(5.5);
    """),
    # The missile chase camera on a vampire, slowing to a crawl for the kill
    "chase": (False, """
        const v = K.ascm(0.35, 700);
        K.watchKills([v]);
        K.setCameraMode('missile');
        const slow = setInterval(() => {
            if (!K.d.missiles.includes(v)) return;
            if (v.mesh.position.length() < 330) { K.d.setTimeScale(0.2); K.mark('slow'); clearInterval(slow); }
        }, 5);
        K.at(0.1, () => {});
        const done = setInterval(() => {
            if (!K.marks.kill) return;
            clearInterval(done);
            K.end(K.now() + 3.5);
        }, 20);
    """),
    # The vampire from low behind our ship, down its line of approach, then the split screen
    "split": (False, """
        const a = 0.35, dir = [Math.cos(a), 0, Math.sin(a)];
        const v = K.ascm(a, 950);
        K.watchKills([v]);
        K.cam(t => ({ pos: [-8 - 36 * dir[0], K.layout.mountY + 12, 5 - 36 * dir[2]],
                      look: [70 * dir[0], K.layout.mountY + 6, 70 * dir[2]], fov: 45 }));
        const go = setInterval(() => {
            if (!K.d.missiles.includes(v) || v.mesh.position.length() > 560) return;
            clearInterval(go);
            K.mark('split');
            K.d.setChaseTrack(v); K.d.setSplitLayout('side'); K.camFn = null; K.setCameraMode('split');
        }, 5);
        const done = setInterval(() => {
            if (!K.marks.kill) return;
            clearInterval(done);
            K.end(K.now() + 2.5);
        }, 20);
    """),
    # Saturation: the whole group from a low, slowly turning view; a friendly hit and burning,
    # vampires on several bearings, launches from everyone
    "overview": (False, """
        K.d.setWave(11);
        const vs = [K.ascm(2.4, 800, 2), K.ascm(5.2, 900), K.ascm(1.2, 750, 4), K.ascm(0.6, 1000), K.ascm(3.7, 1100)];
        K.watchKills(vs);
        K.at(0.2, () => { K.d.wreckFriendly(1); K.mark('wreck'); });
        K.at(0.8, () => K.d.launchVLS(0, null));
        K.at(1.6, () => K.d.launchVLS('ship', null));
        K.at(2.4, () => K.d.launchVLS(3, null));
        K.at(3.0, () => K.d.launchVLS(2, null));
        K.cam(t => {
            const ang = 2.3 + 0.03 * t;
            return { pos: [Math.cos(ang) * 150, 34, Math.sin(ang) * 150 + 10], look: [0, 4, 10], fov: 50 };
        });
        K.end(9);
    """),
    # The gag, in two takes of the same pass: the Seahawk close aboard on our starboard side, bow to
    # stern, and the mount swinging round to track her. FLYBY_JS sets her up; "lock" marks the
    # mount taking an interest (the crew's "No! Bad!" goes 0.4 s after); her screen position is
    # in the take's track
    "helo-wide": (False, FLYBY_JS + """
        // Off our starboard bow beside her line, panning with her as she comes past and on down our side
        K.cam(t => {
            const h = s.mesh.position;
            return { pos: [50, 15, -150], look: K.lerp([h.x, h.y, h.z], [0, 8, 0], 0.15), fov: 40 };
        });
    """),
    "helo-pov": (False, FLYBY_JS + """
        // From her cabin door, as it were (just beside and below her), on a long lens held on the
        // mount with a little hand wobble, so the barrels come round to stare down it
        const P = new K.V(0, 8.6, 0.8), up = new K.V(0, 1, 0);
        K.cam(t => {
            const h = s.mesh.position, out = h.clone().sub(P).normalize();
            const lat = out.clone().cross(up).normalize();
            const cam = h.clone().addScaledVector(lat, -4).addScaledVector(up, -2.5);
            const wob = [Math.sin(t * 2.3) * 0.25, Math.sin(t * 3.1 + 1) * 0.2, Math.sin(t * 1.7 + 2) * 0.25];
            return { pos: cam.toArray(), look: P.toArray().map((v, i) => v + wob[i]), fov: 13 };
        });
    """),
    # The title's backdrop: the mount from low and in front, firing up past us at a swarm overhead
    "hero": (False, """
        const a = -1.6;
        const ds = [];
        for (let i = 0; i < 7; i++) ds.push(K.drone(a + (i % 3 - 1) * 0.18, 320 + i * 70, { height: 45 + (i * 13) % 40 }));
        K.watchKills(ds); K.watchFire();
        K.cam(t => {
            const k = t / 8;
            const ang = a - 0.75 + 0.1 * k;
            const r = 17 - 1 * k;
            return { pos: [Math.cos(ang) * r, 2.6, Math.sin(ang) * r], look: [0, 9.5, 0], fov: 42 };
        });
        K.end(8);
    """),
}


def record(name, size):
    spawns, body = TAKES[name]
    w, h = size
    with game_page(width=w, height=h, audio=True) as (page, errors):
        page.add_style_tag(content="#hud, #radar, #zen-exit { display: none !important; }")
        enable_audio(page, load=1.0, settle=0.5)
        page.evaluate(QUIET_JS, spawns)
        time.sleep(LEAD_IN)
        info = page.evaluate(KIT_JS, body)
        data = bytearray()
        step = 8 * 1024 * 1024
        for start in range(0, info["size"], step):
            data += base64.b64decode(page.evaluate(SLICE_JS, [start, min(info["size"], start + step)]))
    report_errors(errors)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.webm").write_bytes(data)
    meta = {k: info[k] for k in ("length", "marks", "said", "track")}
    (OUT / f"{name}.json").write_text(json.dumps(meta, indent=1))
    print(f"{name}: {meta['length']:.2f} s, marks {meta['marks']}, said {[s[1] for s in meta['said']]}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    size = (1920, 1080)
    if "--size" in argv:
        i = argv.index("--size")
        size = tuple(int(v) for v in argv[i + 1].split("x"))
        del argv[i:i + 2]
    for name in argv or TAKES:
        record(name, size)
