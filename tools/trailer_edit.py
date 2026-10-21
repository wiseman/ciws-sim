# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow", "opencv-python-headless"]
# ///
"""Cut the trailer: the takes (tools/trailer_shots.py), the score (tools/score.py) and the voice
clips, to the edit list in trailer/edit.txt, with titles, captions and the mix, as an mp4.

Usage: uv run tools/trailer_edit.py [EDIT.txt] [OUT.mp4] [--from S --to S] [--frames DIR]
--from/--to render only part of it (seconds), --frames also saves a PNG every 0.25 s for review.

The edit list, line by line (# starts a comment). Times are in bars of the score: `8` (bar 8),
`8.3` (its 3rd beat), `8.3.2` (that beat's 2nd 16th), or seconds as `@20.4`.

    tempo 128 / size 1920x1080 / fps 60 / length 30       the frame and the piece
    music FILE gain=G                                       the score, from 0 s
    shot AT TAKE IN [k=v ...]    cut to TAKE from IN (take seconds, or a mark: kill, kill#2,
                                 fire-0.12, lock+0.3); it runs to the next shot. zoom=A>B eases
                                 the frame's scale over the shot, punch=T:S:D snaps it to S at
                                 take second T over D s, dim=K darkens it, game=G its sound
    voice AT FILE [range=A-B] [gain=G] [caption="..."]    a line, or the part of it from A to B s
    caption AT DUR "TEXT"        a subtitle, low in the picture
    text AT DUR STYLE "TEXT"     STYLE: card (a slam, centre), slug (small, spaced, top left),
                                 title (the big one), endcard (the lock-up: title / tagline / url
                                 split on |)
    box TAKE DUR "LABEL"         brackets on the take's tracked object with LABEL, for DUR s
                                 from the start of that take's shot
    flash AT DUR                 the frame washes to white and back
"""
import json
import re
import shlex
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
TAKES = ROOT / "trailer" / "takes"
SR = 48000
FONT_BOLD = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
FONT_ALT = "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"
LETTERBOX = 2.2  # picture aspect inside the bars


# ---------------------------------------------------------------- the edit list

def parse_time(spec, tempo):
    if spec.startswith("@"):
        return float(spec[1:])
    parts = [int(p) for p in spec.split(".")] + [1, 1]
    bar, beat, sub = parts[:3]
    beat_s = 60 / tempo
    return (bar - 1) * 4 * beat_s + (beat - 1) * beat_s + (sub - 1) * beat_s / 4


def take_meta(name):
    return json.loads((TAKES / f"{name}.json").read_text())


def take_time(spec, meta):
    """`1.5`, `kill`, `kill#2-0.3`, `lock+0.2` -> take seconds"""
    m = re.match(r"^([a-z]+)(?:#(\d+))?([+-][\d.]+)?$", spec)
    if not m:
        return float(spec)
    name, nth, off = m.groups()
    return meta["marks"][name][int(nth or 1) - 1] + float(off or 0)


def parse_edit(path):
    edit = {"tempo": 128, "size": (1920, 1080), "fps": 60, "length": 30.0, "music": None,
            "shots": [], "voices": [], "captions": [], "texts": [], "boxes": [], "flashes": []}
    for raw in Path(path).read_text().splitlines():
        line = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()
        if not line:
            continue
        word, *rest = shlex.split(line)
        kv = dict(r.split("=", 1) for r in rest if "=" in r)
        pos = [r for r in rest if "=" not in r]
        T = lambda s: parse_time(s, edit["tempo"])
        if word == "tempo":
            edit["tempo"] = float(pos[0])
        elif word == "size":
            edit["size"] = tuple(int(v) for v in pos[0].split("x"))
        elif word in ("fps", "length"):
            edit[word] = float(pos[0])
        elif word == "music":
            edit["music"] = (ROOT / pos[0], float(kv.get("gain", 1)))
        elif word == "shot":
            meta = take_meta(pos[1])
            edit["shots"].append({"at": T(pos[0]), "take": pos[1], "in": take_time(pos[2], meta), "meta": meta, **kv})
        elif word == "voice":
            a, b = (float(v) for v in kv["range"].split("-")) if "range" in kv else (0, None)
            edit["voices"].append({"at": T(pos[0]), "file": ROOT / pos[1], "from": a, "to": b,
                                   "gain": float(kv.get("gain", 1))})
            if "caption" in kv:
                edit["captions"].append({"at": T(pos[0]), "dur": float(kv.get("hold", 0)) or None, "text": kv["caption"]})
        elif word == "caption":
            edit["captions"].append({"at": T(pos[0]), "dur": float(pos[1]), "text": pos[2]})
        elif word == "text":
            edit["texts"].append({"at": T(pos[0]), "dur": float(pos[1]), "style": pos[2], "text": pos[3]})
        elif word == "box":
            edit["boxes"].append({"take": pos[0], "dur": float(pos[1]), "label": pos[2]})
        elif word == "flash":
            edit["flashes"].append((T(pos[0]), float(pos[1])))
        else:
            raise ValueError(f"don't know {word!r}: {raw}")
    shots = sorted(edit["shots"], key=lambda s: s["at"])
    for s, nxt in zip(shots, shots[1:] + [None]):
        s["end"] = nxt["at"] if nxt else edit["length"]
    edit["shots"] = shots
    # Captions without a length stay up while their line plays
    for c in edit["captions"]:
        if c["dur"] is None:
            v = next(v for v in edit["voices"] if abs(v["at"] - c["at"]) < 1e-6)
            c["dur"] = (v["to"] or clip_seconds(v["file"])) - v["from"] + 0.25
    return edit


def clip_seconds(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


# ---------------------------------------------------------------- audio

def decode_audio(path, start=0.0, dur=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0, start):.4f}", "-i", str(path)]
    if dur is not None:
        cmd += ["-t", f"{dur:.4f}"]
    cmd += ["-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).T.astype(np.float64)


def place(bus, x, at, fade=0.008):
    i = int(round(at * SR))
    if i >= bus.shape[1] or x.shape[1] == 0:
        return
    x = x[:, : bus.shape[1] - i].copy()
    n = min(int(fade * SR), x.shape[1] // 2)
    if n:
        ramp = np.linspace(0, 1, n)
        x[:, :n] *= ramp
        x[:, -n:] *= ramp[::-1]
    bus[:, i:i + x.shape[1]] += x


def mix_audio(edit, out_wav):
    n = int(edit["length"] * SR)
    music = np.zeros((2, n))
    game = np.zeros((2, n))
    voice = np.zeros((2, n))
    if edit["music"]:
        path, gain = edit["music"]
        m = decode_audio(path)[:, :n]
        music[:, : m.shape[1]] = m * gain
    for s in edit["shots"]:
        g = float(s.get("game", 0.7))
        if g > 0:
            place(game, decode_audio(TAKES / f"{s['take']}.webm", s["in"], s["end"] - s["at"]) * g, s["at"])
    for v in edit["voices"]:
        dur = None if v["to"] is None else v["to"] - v["from"]
        place(voice, decode_audio(v["file"], v["from"], dur) * v["gain"], v["at"], fade=0.004)
    # Duck the music and the game under the voices: follow the voice bus's level, smoothed
    level = np.abs(voice).max(axis=0)
    win = int(0.25 * SR)
    k = np.ones(win) / win
    env = np.convolve(level > 0.01, k, mode="same")
    env = np.clip(env * 3, 0, 1)
    duck = 1 - 0.5 * env  # about -6 dB
    music *= duck
    game *= 1 - 0.35 * env
    out = music + game + voice
    # The last half second fades out
    tail = int(0.5 * SR)
    out[:, -tail:] *= np.linspace(1, 0, tail) ** 2
    peak = np.abs(out).max()
    out = np.tanh(out / peak * 1.3) / np.tanh(1.3) * 0.89
    data = (out.T * 32767).astype("<i2")
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def loudnorm(src, dst, target="I=-14:TP=-1.0:LRA=20"):
    """Two-pass loudness normalization: measure, then one fixed gain (linear), as demo_video.py"""
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm={target}:print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    measured = (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", f"loudnorm={target}{measured}",
                    "-ar", str(SR), str(dst)], check=True)


# ---------------------------------------------------------------- pictures

def font(size, alt=False):
    return ImageFont.truetype(FONT_ALT if alt else FONT_BOLD, size)


def text_rgba(text, size, tracking=0.0, fill=(255, 255, 255), stroke=0, stroke_fill=(0, 0, 0), alt=False, shadow=True):
    """Text as an RGBA array, letters spaced by `tracking` em, with a soft shadow"""
    f = font(size, alt)
    widths = [f.getlength(ch) for ch in text]
    track = tracking * size
    w = int(sum(widths) + track * (len(text) - 1) + 2 * stroke + size * 0.3)
    asc, desc = f.getmetrics()
    h = asc + desc + 2 * stroke + int(size * 0.2)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = stroke + size * 0.15
    for ch, cw in zip(text, widths):
        d.text((x, stroke + size * 0.1), ch, font=f, fill=fill + (255,), stroke_width=stroke, stroke_fill=stroke_fill + (255,))
        x += cw + track
    arr = np.array(img).astype(np.float32) / 255
    if shadow:
        a = arr[..., 3]
        sh = cv2.GaussianBlur(a, (0, 0), size * 0.08) * 0.65
        out = np.zeros_like(arr)
        out[..., 3] = np.maximum(a, sh)
        out[..., :3] = arr[..., :3] * (a / np.maximum(out[..., 3], 1e-6))[..., None]
        arr = out
    return arr


def blend(frame, rgba, cx, cy, alpha=1.0, scale=1.0):
    """Composite rgba (float 0..1) onto frame (float 0..1) centred at (cx, cy)"""
    if alpha <= 0:
        return
    if abs(scale - 1) > 1e-3:
        rgba = cv2.resize(rgba, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    h, w = rgba.shape[:2]
    x0, y0 = int(cx - w / 2), int(cy - h / 2)
    fx0, fy0 = max(0, x0), max(0, y0)
    fx1, fy1 = min(frame.shape[1], x0 + w), min(frame.shape[0], y0 + h)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    sub = rgba[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    a = sub[..., 3:4] * alpha
    region = frame[fy0:fy1, fx0:fx1]
    region *= 1 - a
    region += sub[..., :3] * a


def ease_out(k):
    k = min(max(k, 0), 1)
    return 1 - (1 - k) ** 3


class Titles:
    """The text overlays, rendered once and animated per frame"""

    def __init__(self, edit, W, H):
        self.W, self.H = W, H
        self.items = []
        for t in edit["texts"]:
            style, text = t["style"], t["text"]
            if style == "card":
                layers = [(text_rgba(text, int(H * 0.14), 0.06), 0)]
            elif style == "slug":
                layers = [(text_rgba(text, int(H * 0.038), 0.35, alt=True), 0)]
            elif style == "title":
                main, *sub = text.split("|")
                layers = [(text_rgba(main, int(H * 0.26), 0.04), 0)]
                if sub:
                    layers.append((text_rgba(sub[0], int(H * 0.04), 0.28, alt=True), int(H * 0.165)))
            elif style == "endcard":
                title, tag, url = text.split("|")
                layers = [(text_rgba(title, int(H * 0.15), 0.04), -int(H * 0.1)),
                          (text_rgba(tag, int(H * 0.042), 0.45, alt=True), int(H * 0.035)),
                          (text_rgba(url, int(H * 0.06), 0.08, fill=(255, 196, 64)), int(H * 0.13))]
            else:
                raise ValueError(f"no text style {style}")
            self.items.append({**t, "layers": layers})
        self.captions = [{**c, "img": text_rgba(c["text"], int(H * 0.052), 0.02, stroke=4, alt=True, shadow=False)}
                         for c in edit["captions"]]

    def draw(self, frame, t):
        W, H = self.W, self.H
        for it in self.items:
            age = t - it["at"]
            if not 0 <= age < it["dur"]:
                continue
            left = it["dur"] - age
            out = min(1, left / 0.12)
            if it["style"] == "card":
                k = ease_out(age / 0.14)
                for img, dy in it["layers"]:
                    blend(frame, img, W / 2, H / 2 + dy, alpha=min(1, age / 0.05) * out, scale=1.5 - 0.5 * k + 0.03 * age)
            elif it["style"] == "slug":
                a = min(1, age / 0.4) * min(1, left / 0.4)
                img = it["layers"][0][0]
                blend(frame, img, W * 0.07 + img.shape[1] / 2, H * 0.2, alpha=a)
            elif it["style"] == "title":
                k = ease_out(age / 0.18)
                for i, (img, dy) in enumerate(it["layers"]):
                    if i == 0:
                        blend(frame, img, W / 2, H / 2 - H * 0.03 + dy, alpha=min(1, age / 0.04) * out, scale=1.8 - 0.8 * k + 0.025 * age)
                    else:
                        a = min(1, max(0, age - 0.35) / 0.3) * out
                        blend(frame, img, W / 2, H / 2 - H * 0.03 + dy, alpha=a)
            elif it["style"] == "endcard":
                for i, (img, dy) in enumerate(it["layers"]):
                    a = min(1, max(0, age - 0.25 * i) / 0.35)
                    blend(frame, img, W / 2, H / 2 + dy + (1 - ease_out(max(0, age - 0.25 * i) / 0.5)) * 18, alpha=a)
        for c in self.captions:
            age = t - c["at"]
            if 0 <= age < c["dur"]:
                a = min(1, age / 0.08) * min(1, (c["dur"] - age) / 0.12)
                blend(frame, c["img"], W / 2, H * 0.79, alpha=a)


def draw_box(frame, cx, cy, size, label, color, alpha, W):
    """Corner brackets round (cx, cy), `size` px across, with a label tab above"""
    if alpha <= 0:
        return
    over = frame.copy()
    s = max(size, 60) / 2
    L = s * 0.35
    th = 4
    col = tuple(float(c) / 255 for c in color)
    pts = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    for sx, sy in pts:
        x, y = int(cx + sx * s), int(cy + sy * s)
        cv2.line(over, (x, y), (int(x - sx * L), y), col, th, cv2.LINE_AA)
        cv2.line(over, (x, y), (x, int(y - sy * L)), col, th, cv2.LINE_AA)
    lbl = text_rgba(label, 34, 0.25, fill=color, alt=True, shadow=False)
    cv2.addWeighted(over, alpha, frame, 1 - alpha, 0, dst=frame)
    blend(frame, lbl, cx - s + lbl.shape[1] / 2 - 4, cy - s - 24, alpha=alpha)


def vignette(W, H):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2)
    return (1 - 0.32 * np.clip(r - 0.45, 0, 1) ** 1.6)[..., None]


def grade(frame):
    """A touch more contrast and colour, the trailer look on the game's cel shading"""
    lum = frame.mean(axis=2, keepdims=True)
    frame += (frame - lum) * 0.18          # saturation
    frame -= 0.5
    frame *= 1.1                           # contrast
    frame += 0.5
    np.clip(frame, 0, 1, out=frame)


class ShotReader:
    """Frames of a take from an in-point, at the trailer's rate, as float32 RGB"""

    def __init__(self, take, start, dur, W, H, fps):
        self.W, self.H = W, H
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0, start):.4f}", "-i", str(TAKES / f"{take}.webm"),
             "-t", f"{dur + 0.5:.4f}", "-vf", f"fps={fps},scale={W}:{H}:flags=lanczos", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE)
        self.last = np.zeros((H, W, 3), np.uint8)

    def read(self):
        buf = self.proc.stdout.read(self.W * self.H * 3)
        if len(buf) == self.W * self.H * 3:
            self.last = np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3)
        return self.last  # past the take's end: hold its last frame

    def close(self):
        self.proc.kill()
        self.proc.wait()


def zoomed(img, scale, cx=0.5, cy=0.5):
    if scale <= 1.0001:
        return img
    H, W = img.shape[:2]
    w, h = W / scale, H / scale
    x0 = min(max(cx * W - w / 2, 0), W - w)
    y0 = min(max(cy * H - h / 2, 0), H - h)
    M = np.float32([[scale, 0, -x0 * scale], [0, scale, -y0 * scale]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR)


def shot_scale(s, t):
    """The frame's scale for shot s at trailer time t"""
    k = (t - s["at"]) / max(s["end"] - s["at"], 1e-6)
    scale = 1.0
    if "zoom" in s:
        a, b = (float(v) for v in s["zoom"].split(">"))
        scale = a + (b - a) * (k * k * (3 - 2 * k))
    if "punch" in s:
        at, size, d = (float(v) for v in s["punch"].split(":"))
        tt = s["in"] + (t - s["at"])
        scale *= 1 + (size - 1) * ease_out((tt - at) / d) if tt >= at else 1
    return scale


def render(edit, out, t_from=0.0, t_to=None, frames_dir=None):
    W, H = edit["size"]
    fps = edit["fps"]
    t_to = edit["length"] if t_to is None else t_to
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.wav"
        mix_audio(edit, raw)
        wav = Path(tmp) / "mix.wav"
        loudnorm(raw, wav)
        enc = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps:g}", "-i", "-",
             "-ss", f"{t_from:.4f}", "-t", f"{t_to - t_from:.4f}", "-i", str(wav),
             "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-shortest", str(out)],
            stdin=subprocess.PIPE)
        titles = Titles(edit, W, H)
        vig = vignette(W, H)
        bar_h = int((H - W / LETTERBOX) / 2)
        boxes = {b["take"]: b for b in edit["boxes"]}
        reader, current = None, None
        n0, n1 = int(round(t_from * fps)), int(round(t_to * fps))
        for n in range(n0, n1):
            t = n / fps
            s = next(s for s in edit["shots"] if s["at"] <= t + 1e-9 < s["end"]) if t >= edit["shots"][0]["at"] else None
            if s is not current:
                if reader:
                    reader.close()
                current = s
                reader = ShotReader(s["take"], s["in"] + (t - s["at"]), s["end"] - t, W, H, fps) if s else None
            img = reader.read() if reader else np.zeros((H, W, 3), np.uint8)
            scale = shot_scale(s, t) if s else 1
            frame = zoomed(img, scale).astype(np.float32) / 255
            grade(frame)
            if s and "dim" in s:
                frame *= 1 - float(s["dim"]) * min(1, (t - s["at"]) / 0.6)
            frame *= vig
            if s and s["take"] in boxes and t - s["at"] < boxes[s["take"]]["dur"]:
                b = boxes[s["take"]]
                tt = s["in"] + (t - s["at"])
                tr = s["meta"]["track"]
                row = min(tr, key=lambda r: abs(r[0] - tt))
                x, y = (row[1] + 1) / 2, (1 - row[2]) / 2
                # Through the shot's zoom (about the centre)
                px = W / 2 + (x * W - W / 2) * scale
                py = H / 2 + (y * H - H / 2) * scale
                size = row[3] * W / 2 * scale * 2.2
                age = t - s["at"]
                blink = 1 if age > 0.3 or int(age * 16) % 2 == 0 else 0
                draw_box(frame, px, py, size, b["label"], (90, 255, 140), blink * 0.95, W)
            titles.draw(frame, t)
            for at, d in edit["flashes"]:
                if at <= t < at + d:
                    k = (t - at) / d
                    a = (1 - k) ** 2
                    frame += (1 - frame) * a
            frame[:bar_h] = 0
            frame[H - bar_h:] = 0
            out8 = (np.clip(frame, 0, 1) * 255).astype(np.uint8)
            enc.stdin.write(out8.tobytes())
            if frames_dir and n % int(fps / 4) == 0:
                Image.fromarray(out8).resize((W // 4, H // 4)).save(Path(frames_dir) / f"f{t:06.2f}.png")
        if reader:
            reader.close()
        enc.stdin.close()
        enc.wait()
    print("wrote", out)


if __name__ == "__main__":
    argv = sys.argv[1:]
    opts = {}
    for flag in ("--from", "--to", "--frames"):
        if flag in argv:
            i = argv.index(flag)
            opts[flag] = argv[i + 1]
            del argv[i:i + 2]
    edit_path = Path(argv[0]) if argv else ROOT / "trailer" / "edit.txt"
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "demo" / "ciws-trailer.mp4"
    frames = opts.get("--frames")
    if frames:
        Path(frames).mkdir(parents=True, exist_ok=True)
    render(parse_edit(edit_path), out, float(opts.get("--from", 0)),
           float(opts["--to"]) if "--to" in opts else None, frames)
