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

`process` gives each take its character and writes the game's assets:
  net  (CIC tactical net): band-limited 350-3200 Hz, driven and compressed, hiss bed, key-up click
       and a squelch tail
  1mc  (shipboard announcing system): horn-speaker band, a metallic resonance and a slap echo
       down the passageways; "1mc-hurried" is the same chain on eleven_v3 takes directed to sound
       rushed (general quarters, damage control and rescue calls)
  dry  (crew right next to us): no radio, just trimmed and evened out; eleven_v3 takes, whose
       [bracketed] audio tags direct the delivery and aren't spoken
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


# A second CIC watchstander for some of the vampire variations
VOICE_NET_2 = "iP95p4xoKVk53GoZ742B"   # "Chris"
# Delivery direction for the hurried 1MC calls: an eleven_v3 audio tag describing the voice (not
# spoken). With the speed setting at its maximum and stability at "creative", this was the take
# that sounded most hurried.
HURRIED = "[urgent, fast and clipped, out of breath] "

# Crew voices for the dry reactions (ElevenLabs premade), rotated so a ship's reactions come from
# different people
CREW = ["TX3LPaxmHKxFdv7VOQHJ", "CwhRBWXzGAHq8TQ4Fs17", "FGY2WhTYpPnrIDTdsKH5", "iP95p4xoKVk53GoZ742B",
        "cjVigY5qzO86Huf0OWal", "EXAVITQu4vr4xnSDxMaL", "bIHbv24MWmeRgasZH58o", "nPczCjzI2devNBz1zQrb"]
# Fictional but plausible names for the friendly ships (file names use the lower-case key)
SHIPS = {"halvorsen": "Halvorsen", "whitcomb": "Whitcomb", "cordell": "Cordell", "pellam": "Pellam",
         "marsden": "Marsden", "talbert": "Talbert", "vanover": "Vanover", "cape-sable": "Cape Sable"}
REACTIONS = [
    "[shocked] Oh no... {ship} just got hit!",
    "[angry] Damn it! They got {ship}!",
    "[urgent] {ship}'s hit! She's burning!",
    "[shouting] Holy... {ship} just took one!",
]
GENERIC_REACTIONS = {
    "oh-no": "[shocked] Oh no, they got hit!",
    "look-at-that": "[whispering] Jesus... look at that smoke.",
    "going-down": "[sad] She's going down...",
    "get-out": "[urgent] Come on, come on, get out of there...",
    "no-no-no": "[shocked] No, no, no...",
    "survivors": "[urgent] Somebody get eyes on survivors!",
    "god-help": "[quietly] God help them.",
    "direct-hit": "[shouting] Direct hit! They're hit!",
}

# name -> (text, chain[, voice]); CHAINS (below the processing) gives each chain's default voice,
# model and processing
LINES = {
    **{f"vampire-{deg:03d}": (f"Vampire, vampire, vampire! Bearing {bearing_words(deg)}, inbound!", "net")
       for deg in range(0, 360, 30)},
    "splash": ("Splash one vampire.", "net"),
    "birds-away": ("Birds away.", "net"),
    "general-quarters": ("General quarters, general quarters. All hands man your battle stations.", "1mc"),
    "missile-launch": ("Stand by for missile launch. All hands clear the weather decks.", "1mc"),
    # Damage control after a hit. Not an official script (the real wording is in each ship's damage
    # control bill): the commonly described pattern of casualty type, fire class, compartment as
    # deck-frame-position-use, then the repair locker that responds.
    "dc-fire-bravo": ("Fire, fire, fire. Class Bravo fire in compartment two, one-twenty, one, Lima. "
                      "Repair Two, respond.", "1mc"),
    "dc-fire-charlie": ("Fire, fire, fire. Class Charlie fire in compartment one, two-forty, two, Charlie. "
                        "Repair Three, respond.", "1mc"),
    "dc-flooding": ("Flooding, flooding, flooding in compartment three, one-forty-two, zero, Echo. "
                    "Repair Two, respond.", "1mc"),
    "dc-hit": ("Missile impact, starboard side, frame two-ten. "
               "All repair lockers investigate and report to D C Central.", "1mc"),
    # More damage control variations. The third part of a compartment number is the position: odd is
    # starboard, even is port, zero is the centerline.
    "dc-hit-port": ("Missile impact, port side, frame one-sixty. "
                    "All repair lockers investigate and report to D C Central.", "1mc"),
    "dc-hit-port-aft": ("Missile impact, port side aft, frame three-ten. "
                        "Repair Three, investigate and report.", "1mc"),
    "dc-hit-stbd-fwd": ("Missile impact, starboard side forward, frame eighty. "
                        "Repair Two, investigate and report.", "1mc"),
    "dc-fire-bravo-port": ("Fire, fire, fire. Class Bravo fire in compartment four, two-twenty, two, Echo. "
                           "Repair Five, respond.", "1mc"),
    "dc-fire-alpha-port": ("Fire, fire, fire. Class Alpha fire in compartment two, ninety-six, two, Lima. "
                           "Repair Two, respond.", "1mc"),
    "dc-fire-charlie-stbd": ("Fire, fire, fire. Class Charlie fire in compartment zero one, one-fifty, one, Charlie. "
                             "Repair Three, respond.", "1mc"),
    "dc-flooding-port": ("Flooding, flooding, flooding in compartment four, one-eighty, two, Echo. "
                         "Repair Five, respond.", "1mc"),
    # More ways to call a vampire, so the same words don't come round every time
    **{f"vampire-{deg:03d}-b": (f"Vampire, vampire! Bearing {bearing_words(deg)}, closing fast!", "net")
       for deg in range(0, 360, 30)},
    **{f"vampire-{deg:03d}-c": (f"Vampire inbound, bearing {bearing_words(deg)}! Sea-skimmer!", "net", VOICE_NET_2)
       for deg in range(0, 360, 30)},
    # Crew next to us when a friendly is hit: per-ship reactions, then generic ones
    **{f"hit-{key}-{i + 1}": (template.format(ship=name), "dry", CREW[(i + 2 * j) % len(CREW)])
       for j, (key, name) in enumerate(SHIPS.items()) for i, template in enumerate(REACTIONS)},
    **{f"hit-{key}": (text, "dry", CREW[i % len(CREW)]) for i, (key, text) in enumerate(GENERIC_REACTIONS.items())},
    # Rescue of a stricken friendly: the rescue and assistance (R and A) team and the boat crew
    **{f"rescue-{key}": (f"{name} has been hit. Away the rescue and assistance team. "
                         "R and A team, lay to the boat deck.", "1mc") for key, name in SHIPS.items()},
    "rescue-rhib-stbd": ("Away the starboard RHIB. Boat crew and Sar swimmer, lay to the starboard boat deck.", "1mc"),
    "rescue-rhib-port": ("Away the port RHIB. Boat crew and Sar swimmer, lay to the port boat deck.", "1mc"),
    "rescue-medical": ("Medical, stand by to receive casualties on the flight deck.", "1mc"),
    "rescue-lookouts": ("Lookouts, report all survivors in the water to the bridge.", "1mc"),
}
# General quarters, damage control and rescue calls go out hurried
for _name, (_text, _chain, *_voice) in LINES.items():
    if _name == "general-quarters" or _name.startswith(("dc-", "rescue-")):
        LINES[_name] = (HURRIED + _text, "1mc-hurried", *_voice)


def generate(names):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("set ELEVENLABS_API_KEY in the environment")
    SRC.mkdir(parents=True, exist_ok=True)
    for name in names:
        text, chain, *voice = LINES[name]
        c = CHAINS[chain]
        voice = voice[0] if voice else c["voice"]
        body = json.dumps({"text": text, "model_id": c.get("model", MODEL), "voice_settings": c["settings"]}).encode()
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


def dry_chain(x, seed):
    # Crew talking right beside us: no radio, just rumble removed and peaks evened out
    x = signal.sosfilt(sos("highpass", 90, 2), peak_norm(x))
    return compress(peak_norm(x), -18, 2.5)


# chain -> ElevenLabs voice, model and settings, processing, and the target loudness (RMS, dBFS)
CHAINS = {
    "net": {"voice": VOICE_NET, "settings": {"stability": 0.38, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True, "speed": 1.08},
            "process": net_chain, "rms_db": -15},
    "1mc": {"voice": VOICE_1MC, "settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True},
            "process": onemc_chain, "rms_db": -17},
    "1mc-hurried": {"voice": VOICE_1MC, "model": "eleven_v3", "settings": {"stability": 0.0, "similarity_boost": 0.8, "speed": 1.2},
                    "process": onemc_chain, "rms_db": -17},
    "dry": {"voice": CREW[0], "model": "eleven_v3", "settings": {"stability": 0.5, "similarity_boost": 0.8},
            "process": dry_chain, "rms_db": -17},
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
    for i, (name, (_, chain, *_)) in enumerate(LINES.items()):
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
        for name, (text, *_) in LINES.items():
            print(f"{name:20s} {text}")
    else:
        sys.exit(__doc__)
