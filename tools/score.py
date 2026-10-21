# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy"]
# ///
"""Render a text score to a stereo WAV: a small tracker-style composition format and the synth
voices to play it, for the trailer's music (trailer/score.txt).

Usage: uv run tools/score.py SCORE.txt OUT.wav [--stems DIR]

The format, line by line (# starts a comment, at the start of a line or after a space):

    tempo 128                      beats per minute (four 16th-note steps a beat, 16 a bar)
    bars 16                        the piece's length
    voice NAME KIND key=value...   an instrument: a KIND from VOICES with its settings (gain, pan,
                                   verb, duck, plus any the kind takes, such as cutoff)
    pattern NAME                   a block of lanes, one per line, up to the next line without one:
        VOICE: cells                 one cell per 16th step; `|` and spaces between groups are
                                     only for reading. Drum cells are single characters: X accent,
                                     x hit, o ghost, . rest. Pitched lanes are space-separated
                                     tokens instead: a note (D2, F#3, Bb1), a chord (D2+A2+D3),
                                     `-` to hold the note before, `.` for a rest; a trailing !
                                     accents a note and ? softens it; TOKEN*N repeats one, as
                                     in `D1+A1 -*31` for a chord held two bars.
    song                           then one line per entry, up to the end:
        BARS PATTERN[*GAIN] ...      bars as `3`, `3-5` or with a beat, `7.4` (bar 7, beat 4)
                                     or `7.4.3` (its 3rd 16th); a pattern shorter than the bars
                                     given loops, a longer one is cut off.
        BAR cut                      everything sounding stops dead there, reverb tails and all
                                     (the needle off the record); what starts there plays on.

Every voice sends `verb` of its level to one shared hall reverb, and a voice with `duck` is
pumped down by that much on each kick and taiko hit (sidechain). --stems also writes each
voice's dry track, for checking a part on its own.
"""
import re
import sys
import wave
from pathlib import Path

import numpy as np
from scipy import signal

SR = 48000
RNG = np.random.default_rng(7)

NOTE_RE = re.compile(r"^([A-G])([#b]?)(-?\d)$")
SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_freq(name):
    m = NOTE_RE.match(name)
    if not m:
        raise ValueError(f"bad note {name!r}")
    letter, acc, octave = m.groups()
    midi = 12 * (int(octave) + 1) + SEMITONES[letter] + {"#": 1, "b": -1, "": 0}[acc]
    return 440.0 * 2 ** ((midi - 69) / 12)


# ---------------------------------------------------------------- DSP helpers

def t_axis(seconds):
    return np.arange(int(seconds * SR)) / SR


def noise(seconds):
    return RNG.standard_normal(int(seconds * SR))


def saw(freq, seconds, phase=None):
    """Band-limited-ish sawtooth (additive up to Nyquist/2) at a fixed or per-sample frequency"""
    n = int(seconds * SR)
    f = np.broadcast_to(np.asarray(freq, float), (n,))
    ph = np.cumsum(f) / SR + (RNG.random() if phase is None else phase)
    top = max(1, int(SR / 2.5 / max(f.max(), 1)))
    out = np.zeros(n)
    for k in range(1, min(top, 60) + 1):
        out += np.sin(2 * np.pi * k * ph) / k
    return out * 0.6


def sine(freq, seconds, phase=0.0):
    n = int(seconds * SR)
    f = np.broadcast_to(np.asarray(freq, float), (n,))
    return np.sin(2 * np.pi * np.cumsum(f) / SR + phase)


def env_exp(seconds, decay, attack=0.002):
    t = t_axis(seconds)
    e = np.exp(-t / decay)
    if attack > 0:
        e *= np.clip(t / attack, 0, 1)
    return e


def env_adsr(seconds, a, d, s, r, hold):
    """Attack/decay/sustain for `hold` s, then the release, the whole thing `seconds` long"""
    t = t_axis(seconds)
    e = np.where(t < a, t / max(a, 1e-6), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-6)))
    rel = t >= hold
    level = e[np.argmax(rel)] if rel.any() else 0
    e[rel] = level * np.exp(-(t[rel] - hold) / max(r, 1e-6))
    return e


def lowpass(x, cutoff, q=0.707):
    b, a = signal.iirfilter(2, min(cutoff, SR * 0.45) / (SR / 2), btype="low", ftype="butter")
    return signal.lfilter(b, a, x)


def highpass(x, cutoff):
    b, a = signal.iirfilter(2, cutoff / (SR / 2), btype="high", ftype="butter")
    return signal.lfilter(b, a, x)


def bandpass(x, lo, hi):
    b, a = signal.iirfilter(2, [lo / (SR / 2), min(hi, SR * 0.45) / (SR / 2)], btype="band", ftype="butter")
    return signal.lfilter(b, a, x)


def svf_lowpass(x, cutoff, res=0.3):
    """State-variable lowpass with a per-sample cutoff (Hz array) and resonance 0..1"""
    cutoff = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    f = 2 * np.sin(np.pi * np.clip(cutoff, 20, SR / 6) / SR)
    q = 2 - 2 * res
    low = band = 0.0
    out = np.empty_like(x)
    for i in range(len(x)):
        low += f[i] * band
        high = x[i] - low - q * band
        band += f[i] * high
        out[i] = low
    return out


def svf_bandpass(x, cutoff, res=0.6):
    cutoff = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    f = 2 * np.sin(np.pi * np.clip(cutoff, 20, SR / 6) / SR)
    q = 2 - 2 * res
    low = band = 0.0
    out = np.empty_like(x)
    for i in range(len(x)):
        low += f[i] * band
        high = x[i] - low - q * band
        band += f[i] * high
        out[i] = band
    return out


def drive(x, amount):
    return np.tanh(x * amount) / np.tanh(amount)


# ---------------------------------------------------------------- voices
# Each takes (freqs: list of Hz or [None] for drums, length: s the note's held, vel 0..1, opts)
# and returns a mono array (it may ring past `length`).

def v_kick(_, length, vel, o):
    T = 0.6
    t = t_axis(T)
    f = 46 + 130 * np.exp(-t * 32)
    body = sine(f, T) * env_exp(T, 0.32, 0.001)
    click = highpass(noise(0.006), 2000) * 0.5
    body[: len(click)] += click
    return drive(body * 1.4, 1.8) * vel


def v_taiko(_, length, vel, o):
    T = 1.6
    t = t_axis(T)
    f = o.get("pitch", 62) * (1 + 0.6 * np.exp(-t * 20))
    body = sine(f, T) * env_exp(T, 0.42, 0.002) + 0.4 * sine(f * 1.6, T) * env_exp(T, 0.12)
    skin = lowpass(noise(T), 900) * env_exp(T, 0.07) * 1.2
    slap = bandpass(noise(0.03), 600, 3500) * env_exp(0.03, 0.008)
    out = body + skin
    out[: len(slap)] += slap * 0.8
    return drive(out, 1.5) * vel


def v_snare(_, length, vel, o):
    T = 0.45
    tone = sine(185, T) * env_exp(T, 0.06) + 0.5 * sine(330, T) * env_exp(T, 0.04)
    rattle = bandpass(noise(T), 1500, 9000) * env_exp(T, o.get("decay", 0.16))
    return drive((tone * 0.7 + rattle) * 1.2, 1.4) * vel


def v_hat(_, length, vel, o):
    T = 0.12
    return highpass(noise(T), 7500) * env_exp(T, o.get("decay", 0.03)) * vel


def v_crash(_, length, vel, o):
    T = 3.0
    n = highpass(noise(T), 3500) + 0.4 * bandpass(noise(T), 800, 3000)
    return n * env_exp(T, o.get("decay", 0.9), 0.003) * 0.6 * vel


def v_revcrash(_, length, vel, o):
    """A reversed crash, rising over `length` and stopping dead at its end"""
    n = highpass(noise(length), 2500) * (t_axis(length) / length) ** 3
    return n * vel


def v_boom(_, length, vel, o):
    """Sub drop and a thump: the hit under every big moment"""
    T = 3.0
    t = t_axis(T)
    f = 38 + 70 * np.exp(-t * 7)
    sub = sine(f, T) * env_exp(T, 0.9, 0.003)
    thump = lowpass(noise(T), 300) * env_exp(T, 0.15) * 1.5
    return drive((sub + thump) * 1.3, 2.0) * vel


def v_bass(freqs, length, vel, o):
    T = length + 0.15
    out = np.zeros(int(T * SR))
    for f in freqs:
        x = saw(f, T) + 0.8 * sine(f / 2, T) + 0.3 * saw(f * 1.005, T)
        e = env_adsr(T, 0.004, 0.08, 0.7, 0.05, length)
        cutoff = o.get("cutoff", 700) * (1 + 2.5 * env_exp(T, 0.06))
        out += svf_lowpass(x * e, cutoff, 0.35)
    return drive(out * 1.2, 1.6) * vel


def v_strings(freqs, length, vel, o):
    """Staccato string section: detuned saws, a quick bite and a short tail"""
    T = length + 0.3
    out = np.zeros(int(T * SR))
    for f in freqs:
        x = sum(saw(f * d, T) for d in (0.996, 1.0, 1.004, 2.002))
        out += x
    e = env_adsr(T, o.get("attack", 0.006), 0.09, o.get("sustain", 0.35), 0.12, length)
    return lowpass(out * e, o.get("cutoff", 3000)) * 0.35 * vel


def v_brass(freqs, length, vel, o):
    """Brass: stacked saws through a filter that opens on the attack, overdriven"""
    T = length + 0.8
    out = np.zeros(int(T * SR))
    for f in freqs:
        out += sum(saw(f * d, T) for d in (0.995, 1.0, 1.006))
    e = env_adsr(T, o.get("attack", 0.03), 0.4, 0.75, 0.35, length)
    cut = o.get("cutoff", 1800) * (0.35 + 0.65 * (1 - np.exp(-t_axis(T) / 0.06))) * (0.6 + 0.4 * e)
    return drive(svf_lowpass(out * e, cut, 0.25) * 0.5, 2.2) * vel


def v_braam(freqs, length, vel, o):
    """The trailer horn: low brass all at once, the filter tearing open, a long ring"""
    T = length + 2.5
    t = t_axis(T)
    out = np.zeros(int(T * SR))
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.5 * t)
    for f in freqs:
        out += sum(saw(f * d * vib, T) for d in (0.993, 1.0, 1.008)) + 0.6 * sine(f / 2, T)
    e = env_adsr(T, 0.02, 0.8, 0.6, 0.9, length)
    cut = 150 + 2600 * (1 - np.exp(-t / 0.12)) * np.exp(-t / 1.6)
    return drive(svf_lowpass(out * e, cut, 0.4) * 0.6, 3.0) * vel


def v_pad(freqs, length, vel, o):
    """A dark drone: saws through a low, slowly breathing filter, swelling in and out"""
    T = length + 1.5
    t = t_axis(T)
    out = np.zeros(int(T * SR))
    for f in freqs:
        out += sum(saw(f * d, T) for d in (0.997, 1.0, 1.003))
    e = env_adsr(T, o.get("attack", 1.0), 1.0, 1.0, 1.2, length)
    cut = o.get("cutoff", 220) * (1 + 0.5 * np.sin(2 * np.pi * 0.35 * t))
    wind = bandpass(noise(T), 300, 1400) * 0.05
    return (lowpass(out, 2000) * 0 + svf_lowpass(out, cut, 0.2) + wind) * e * 0.5 * vel


def v_ping(freqs, length, vel, o):
    """Sonar: a pure, slightly bending tone with a long ring"""
    T = 2.5
    f = (freqs[0] or 1150) * (1 - 0.01 * t_axis(T))
    x = sine(f, T) + 0.15 * sine(f * 2.01, T)
    return x * env_exp(T, 0.6, 0.004) * vel


def v_riser(_, length, vel, o):
    """Noise through a bandpass sweeping up, and a tone climbing two octaves, over `length`"""
    t = t_axis(length)
    k = t / length
    sweep = 250 * (40 ** k)
    n = svf_bandpass(noise(length), sweep, 0.7) * 1.6
    tone = sine(110 * 4 ** (k ** 1.5), length) * 0.25 + saw(55 * 4 ** (k ** 1.5), length) * 0.08
    return (n + tone) * (k ** 2.2) * vel


def v_scratch(_, length, vel, o):
    """A record scratch: two quick back-and-forth strokes of a pitch-bent saw and filtered noise"""
    T = 0.42
    t = t_axis(T)
    # Stroke shape: the record speed, forward then back, twice
    speed = np.interp(t, [0, 0.05, 0.11, 0.16, 0.22, 0.30, 0.42], [0.2, 1.8, -1.4, 0.3, 2.2, -0.6, 0])
    f = 180 * np.abs(speed) + 40
    tone = saw(f, T) * 0.5
    grit = svf_bandpass(noise(T), 400 + 2200 * np.abs(speed), 0.5) * 1.5
    e = np.clip(np.abs(speed) / 1.5, 0, 1) ** 0.7
    return drive((tone + grit) * e, 2.0) * vel


def v_whoosh(_, length, vel, o):
    T = max(length, 0.3)
    t = t_axis(T)
    k = t / T
    sweep = 5000 * (0.06 ** k)
    return svf_bandpass(noise(T), sweep, 0.5) * np.sin(np.pi * k) ** 2 * 1.5 * vel


VOICES = {
    "kick": v_kick, "taiko": v_taiko, "snare": v_snare, "hat": v_hat, "crash": v_crash,
    "revcrash": v_revcrash, "boom": v_boom, "bass": v_bass, "strings": v_strings, "brass": v_brass,
    "braam": v_braam, "pad": v_pad, "ping": v_ping, "riser": v_riser, "scratch": v_scratch,
    "whoosh": v_whoosh,
}
DRUMS = {"kick", "taiko", "snare", "hat", "crash", "boom", "scratch"}
SIDECHAIN_KEYS = {"kick", "taiko"}
VEL = {"X": 1.0, "x": 0.72, "o": 0.4}


# ---------------------------------------------------------------- parsing

def parse(text):
    score = {"tempo": 120, "bars": 8, "voices": {}, "patterns": {}, "song": [], "cuts": []}
    lines = [re.split(r"(?:^|\s)#", l, maxsplit=1)[0].rstrip() for l in text.splitlines()]  # not C#3
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        word, *rest = line.split()
        if word in ("tempo", "bars"):
            score[word] = float(rest[0]) if word == "tempo" else int(rest[0])
        elif word == "voice":
            name, kind, *opts = rest
            if kind not in VOICES:
                raise ValueError(f"voice {name}: no kind {kind!r}")
            score["voices"][name] = {"kind": kind, **{k: float(v) for k, v in (o.split("=") for o in opts)}}
        elif word == "pattern":
            lanes = []
            while i < len(lines) and ":" in lines[i]:
                voice, cells = lines[i].split(":", 1)
                lanes.append((voice.strip(), cells))
                i += 1
            score["patterns"][rest[0]] = lanes
        elif word == "song":
            while i < len(lines):
                entry = lines[i].strip()
                i += 1
                if entry:
                    where, *pats = entry.split()
                    if pats == ["cut"]:
                        score["cuts"].append(parse_where(where)[0])
                    else:
                        score["song"].append((where, pats))
        else:
            raise ValueError(f"line {i}: don't know {word!r}")
    return score


def lane_events(voice, cells, kind):
    """(step, steps held, freqs, vel) for each note in a lane, and the lane's length in steps"""
    events = []
    if kind in DRUMS or kind in ("revcrash", "riser", "whoosh"):
        steps = [c for c in cells if c not in " |\t"]
        for s, c in enumerate(steps):
            if c in VEL:
                hold = 1
                while s + hold < len(steps) and steps[s + hold] == "-":
                    hold += 1
                events.append((s, hold, [None], VEL[c]))
        return events, len(steps)
    tokens = []
    for tok in cells.replace("|", " ").split():
        m = re.match(r"^(.+)\*(\d+)$", tok)
        tokens += [m.group(1)] * int(m.group(2)) if m else [tok]
    for s, tok in enumerate(tokens):
        if tok in ("-", "."):
            continue
        vel = 0.75
        if tok.endswith("!"):
            vel, tok = 1.0, tok[:-1]
        elif tok.endswith("?"):
            vel, tok = 0.45, tok[:-1]
        hold = 1
        while s + hold < len(tokens) and tokens[s + hold] == "-":
            hold += 1
        events.append((s, hold, [note_freq(n) for n in tok.split("+")], vel))
    return events, len(tokens)


def parse_where(where):
    """`3`, `3-5`, `7.4`, `7.4.3` -> (start step, end step or None); steps from the piece's start"""
    def step(spec):
        parts = [int(p) for p in spec.split(".")] + [1, 1]
        bar, beat, sub = parts[:3]
        return (bar - 1) * 16 + (beat - 1) * 4 + (sub - 1)
    if "-" in where:
        a, b = where.split("-")
        return step(a), (int(b.split(".")[0])) * 16 if "." not in b else step(b)
    if "." in where:
        return step(where), None
    return step(where), step(where) + 16


# ---------------------------------------------------------------- rendering

def hall_ir(seconds=2.6):
    t = t_axis(seconds)
    ir = []
    for _ in range(2):
        n = noise(seconds) * np.exp(-t / 0.55)
        n = lowpass(n, 5000) * (1 - np.exp(-t / 0.01))
        ir.append(n)
    ir = np.array(ir)
    return ir / np.abs(ir).sum(axis=1, keepdims=True).max() * 18


def render(score):
    step_s = 60 / score["tempo"] / 4
    total = score["bars"] * 16 * step_s + 4.0
    n_total = int(total * SR)
    voices = score["voices"]
    # Notes are kept apart by which stretch between cuts they start in, so each can be silenced at
    # its cut
    cuts = sorted(score["cuts"])
    n_segs = len(cuts) + 1
    tracks = {name: np.zeros((n_segs, n_total)) for name in voices}
    keys = np.zeros(n_total)  # the sidechain's trigger: kick and taiko onsets, by velocity

    for where, pats in score["song"]:
        start, end = parse_where(where)
        for pat in pats:
            gain = 1.0
            if "*" in pat:
                pat, g = pat.split("*")
                gain = float(g)
            for voice, cells in score["patterns"][pat]:
                v = voices[voice]
                events, length = lane_events(voice, cells, v["kind"])
                span = (end - start) if end is not None else length
                for rep in range(max(1, -(-span // length))):
                    for s, hold, freqs, vel in events:
                        at = rep * length + s
                        if at >= span:
                            continue
                        hold = min(hold, span - at) if end is not None else hold
                        t0 = int((start + at) * step_s * SR)
                        sound = VOICES[v["kind"]](freqs, hold * step_s, vel * gain, v)
                        sound = sound[: n_total - t0]
                        seg = sum(c <= start + at for c in cuts)
                        tracks[voice][seg, t0:t0 + len(sound)] += sound * v.get("gain", 1.0)
                        if v["kind"] in SIDECHAIN_KEYS:
                            keys[t0] = max(keys[t0], vel * gain)

    # Sidechain envelope: a dip on each key hit, recovering over ~150 ms
    hits = np.nonzero(keys)[0]
    duck_env = np.zeros(n_total)
    shape = np.exp(-t_axis(0.4) / 0.13)
    for h in hits:
        seg = shape[: n_total - h] * keys[h]
        duck_env[h:h + len(seg)] = np.maximum(duck_env[h:h + len(seg)], seg)

    ir = hall_ir()
    out = np.zeros((2, n_total))
    for seg in range(n_segs):
        mix = np.zeros((2, n_total))
        send = np.zeros((2, n_total))
        for name, xs in tracks.items():
            v, x = voices[name], xs[seg]
            if not x.any():
                continue
            if v.get("duck"):
                x = x * (1 - v["duck"] * duck_env)
            pan = v.get("pan", 0.0)
            lr = np.array([np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)]) * np.sqrt(2)
            stereo = lr[:, None] * x[None, :]
            mix += stereo
            send += stereo * v.get("verb", 0.0)
        wet = np.array([signal.fftconvolve(send[c], ir[c])[:n_total] for c in range(2)])
        part = mix + wet
        if seg < len(cuts):
            at = int(cuts[seg] * step_s * SR)
            fade = int(0.004 * SR)
            part[:, at:at + fade] *= np.linspace(1, 0, fade)
            part[:, at + fade:] = 0
        out += part
    # Glue and limit: gentle saturation, then peak-normalize to -1 dBFS
    out = np.tanh(out / np.abs(out).max() * 1.6) / np.tanh(1.6)
    out *= 10 ** (-1 / 20) / np.abs(out).max()
    return out, {name: xs.sum(axis=0) for name, xs in tracks.items()}


def write_wav(path, stereo):
    data = (np.clip(stereo.T, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(stereo.shape[0] if stereo.ndim == 2 else 1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


if __name__ == "__main__":
    argv = sys.argv[1:]
    stems = None
    if "--stems" in argv:
        i = argv.index("--stems")
        stems = Path(argv[i + 1])
        del argv[i:i + 2]
    score = parse(Path(argv[0]).read_text())
    out, tracks = render(score)
    write_wav(argv[1], out)
    if stems:
        stems.mkdir(parents=True, exist_ok=True)
        for name, x in tracks.items():
            peak = np.abs(x).max()
            if peak > 0:
                write_wav(stems / f"{name}.wav", x[None, :] / peak * 0.9)
    print(f"wrote {argv[1]}: {out.shape[1] / SR:.2f} s, {score['bars']} bars at {score['tempo']:g} bpm")
