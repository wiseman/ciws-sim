# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy"]
# ///
"""Generate and process the combat-information-center voice callouts in sounds/.

Usage:
  ELEVENLABS_API_KEY=... uv run tools/make_cic_audio.py generate [line ...]   # TTS -> sounds/src/*.mp3
  uv run tools/make_cic_audio.py process                                    # sounds/src -> sounds/*.mp3

`generate` calls ElevenLabs text-to-speech for each line (all lines, or only the named ones) and
keeps the raw takes in sounds/src/ so the radio processing can be re-tuned without regenerating.
The API key is read from the environment only; never put it in a file.

`process` gives each take its radio character and writes the game's assets:
  net  (CIC tactical net): band-limited 350-3200 Hz, driven and compressed, hiss bed, key-up click
       and a squelch tail
  1mc  (shipboard announcing system): horn-speaker band, a metallic resonance and a slap echo
       down the passageways
Needs ffmpeg on PATH (decode and mp3 encode).
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sounds" / "src"
OUT = ROOT / "sounds"
SR = 44100

# ElevenLabs premade voices
VOICE_NET = "pNInz6obpgDQGcFmaJgB"   # "Adam": deep, firm American male
VOICE_1MC = "pqHfZKP75CvOlQylNhV4"   # "Bill": older American male, measured
MODEL = "eleven_multilingual_v2"

DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "niner"]


def bearing_words(deg):
    return " ".join(DIGITS[int(c)] for c in f"{deg:03d}")


# name -> (text, chain); CHAINS (below the processing) gives each chain's voice and processing
LINES = {
    **{f"vampire-{deg:03d}": (f"Vampire, vampire, vampire! Bearing {bearing_words(deg)}, inbound!", "net")
       for deg in range(0, 360, 30)},
    "splash": ("Splash one vampire.", "net"),
    "birds-away": ("Birds away.", "net"),
    "general-quarters": ("General quarters, general quarters. All hands man your battle stations.", "1mc"),
}


def generate(names):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("set ELEVENLABS_API_KEY in the environment")
    SRC.mkdir(parents=True, exist_ok=True)
    for name in names:
        text, chain = LINES[name]
        voice, settings = CHAINS[chain]["voice"], CHAINS[chain]["settings"]
        body = json.dumps({"text": text, "model_id": MODEL, "voice_settings": settings}).encode()
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
            data=body, headers={"xi-api-key": key, "Content-Type": "application/json"})
        try:
            data = urllib.request.urlopen(req).read()
        except urllib.error.HTTPError as e:
            sys.exit(f"{name}: HTTP {e.code} {e.read()[:300]!r}")
        (SRC / f"{name}.mp3").write_bytes(data)
        print("generated", name, len(data), "bytes")


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def encode(x, path):
    pcm = np.clip(x, -1, 1).astype(np.float32).tobytes()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-codec:a", "libmp3lame", "-b:a", "96k", str(path)], input=pcm, check=True)


def trim(x, floor_db=-42, pad=0.03):
    env = np.abs(signal.hilbert(x)) if len(x) < 400000 else np.abs(x)
    thresh = np.max(env) * 10 ** (floor_db / 20)
    idx = np.where(env > thresh)[0]
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(x), idx[-1] + int(pad * SR))
    return x[a:b]


def sos(kind, freq, order=2):
    return signal.butter(order, freq, btype=kind, fs=SR, output="sos")


def peaking(f0, gain_db, q):
    # RBJ peaking EQ as a single biquad section
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / SR
    alpha = np.sin(w) / (2 * q)
    b = [1 + alpha * a, -2 * np.cos(w), 1 - alpha * a]
    den = [1 + alpha / a, -2 * np.cos(w), 1 - alpha / a]
    return np.array([[*(np.array(b) / den[0]), 1, den[1] / den[0], den[2] / den[0]]])


def compress(x, threshold_db=-24, ratio=4, attack=0.004, release=0.08):
    # Feed-forward peak compressor with make-up to keep the output peak where the input was
    ga, gr = np.exp(-1 / (attack * SR)), np.exp(-1 / (release * SR))
    env = 0.0
    out = np.empty_like(x)
    t = 10 ** (threshold_db / 20)
    for i, s in enumerate(x):
        a = abs(s)
        env = ga * env + (1 - ga) * a if a > env else gr * env + (1 - gr) * a
        g = 1.0 if env <= t else (t * (env / t) ** (1 / ratio)) / env
        out[i] = s * g
    return out


def peak_norm(x, gain=1):
    # Scale to a peak of `gain`
    return gain * x / (np.max(np.abs(x)) + 1e-9)


def rng_noise(n, seed):
    return np.random.default_rng(seed).standard_normal(n)


def net_chain(x, seed):
    x = peak_norm(x)
    x = signal.sosfilt(sos("highpass", 350, 4), x)
    x = signal.sosfilt(sos("lowpass", 3200, 4), x)
    x = signal.sosfilt(peaking(1800, 5, 1.2), x)
    x = compress(peak_norm(x), -22, 5)
    x = np.tanh(peak_norm(x, 2.6)) / np.tanh(2.6)
    lead, tail = int(0.07 * SR), int(0.22 * SR)
    y = np.concatenate([np.zeros(lead), x, np.zeros(tail)])
    n = len(y)
    t = np.arange(n) / SR
    # Carrier hiss for the length of the transmission, band-limited like the voice
    hiss = signal.sosfilt(sos("bandpass", [500, 4500], 2), rng_noise(n, seed))
    hiss /= np.max(np.abs(hiss))
    keyed = np.clip(t / 0.01, 0, 1) * np.clip((n / SR - t) / 0.005, 0, 1)
    y += hiss * 0.035 * keyed
    # Key-up click at the start
    click = np.zeros(n)
    click[int(0.01 * SR)] = 0.6
    click[int(0.01 * SR) + 1] = -0.45
    y += signal.sosfilt(sos("bandpass", [600, 5000], 1), click) * 3
    # Squelch tail: a short burst of open-channel noise as the key is released
    burst_at = lead + len(x) + int(0.03 * SR)
    burst = np.zeros(n)
    m = n - burst_at
    burst[burst_at:] = rng_noise(m, seed + 1) * np.exp(-np.arange(m) / (0.05 * SR)) * np.clip(np.arange(m) / (0.004 * SR), 0, 1)
    y += signal.sosfilt(sos("bandpass", [1200, 6500], 2), burst) * 0.55
    return y


def onemc_chain(x, seed):
    x = peak_norm(x)
    x = signal.sosfilt(sos("highpass", 420, 4), x)
    x = signal.sosfilt(sos("lowpass", 4200, 4), x)
    x = signal.sosfilt(peaking(1250, 7, 3.5), x)  # horn-speaker honk
    x = signal.sosfilt(peaking(2900, 4, 4), x)
    x = compress(peak_norm(x), -20, 4)
    x = np.tanh(peak_norm(x, 1.8))
    # Slap echoes off steel passageways and a short metallic tail
    tail = int(1.0 * SR)
    y = np.concatenate([np.zeros(int(0.05 * SR)), x, np.zeros(tail)])
    out = y.copy()
    for delay, gain in [(0.085, 0.42), (0.17, 0.24), (0.26, 0.12), (0.37, 0.06)]:
        d = int(delay * SR)
        out[d:] += y[:-d] * gain
    ir_len = int(0.6 * SR)
    ir = rng_noise(ir_len, seed) * np.exp(-np.arange(ir_len) / (0.12 * SR))
    ir = signal.sosfilt(sos("bandpass", [600, 3500], 2), ir)
    wet = signal.fftconvolve(out, ir)[: len(out)]
    out += peak_norm(wet) * 0.18 * np.max(np.abs(out))
    return out


# chain -> ElevenLabs voice and settings, radio processing, and the target loudness (RMS, dBFS)
CHAINS = {
    "net": {"voice": VOICE_NET, "settings": {"stability": 0.38, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True, "speed": 1.08},
            "process": net_chain, "rms_db": -15},
    "1mc": {"voice": VOICE_1MC, "settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True},
            "process": onemc_chain, "rms_db": -17},
}


def finish(y, peak_db=-1.0, rms_db=-15.0):
    rms = np.sqrt(np.mean(y[np.abs(y) > 1e-4] ** 2))
    y = y * (10 ** (rms_db / 20) / rms)
    peak = np.max(np.abs(y))
    limit = 10 ** (peak_db / 20)
    if peak > limit:
        # soft knee: compress the excess so loud syllables round off instead of clipping
        knee = limit * 0.8
        a = np.abs(y)
        over = a > knee
        y[over] = np.sign(y[over]) * (knee + (limit - knee) * np.tanh((a[over] - knee) / (limit - knee)))
    fade = int(0.01 * SR)
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    return y


def process():
    for i, (name, (_, chain)) in enumerate(LINES.items()):
        src = SRC / f"{name}.mp3"
        if not src.exists():
            print("missing", src)
            continue
        c = CHAINS[chain]
        y = finish(c["process"](trim(decode(src)), i), rms_db=c["rms_db"])
        encode(y, OUT / f"{name}.mp3")
        print(f"wrote sounds/{name}.mp3  {len(y) / SR:.2f} s  peak {20 * np.log10(np.max(np.abs(y))):.1f} dBFS")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "process"
    if cmd == "generate":
        generate(sys.argv[2:] or list(LINES))
    elif cmd == "process":
        process()
    elif cmd == "list":
        for name, (text, _) in LINES.items():
            print(f"{name:20s} {text}")
    else:
        sys.exit(__doc__)
