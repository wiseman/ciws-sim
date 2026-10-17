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

`process` gives each take its character and writes the game's assets, and lists them in
sounds/callouts.json (the game loads what it lists):
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


# The Captain on the 1MC
VOICE_CAPTAIN = "TxGEqnHWrfWFTfGW9XjX"   # "Josh": deep, steady American male
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
# The boatswain's mate of the watch, for the 1MC's routine calls
VOICE_BMOW = "XrExE9yKIg1WjnnlVkGX"   # "Matilda"
# A helicopter pilot on the net
VOICE_PILOT = "N2lVS1w4EtoT3dr4eOWO"   # "Callum"
# Track numbers the kill calls name (kill-track-1 ...)
KILL_TRACKS = ["four zero seven", "four one two", "three niner five", "four two one", "three eight eight"]


def crew_set(prefix, texts, offset):
    """Crew lines `prefix`-key for each key -> text in `texts`, voiced by CREW in turn from `offset`"""
    return {f"{prefix}-{key}": (text, "dry", CREW[(i + offset) % len(CREW)]) for i, (key, text) in enumerate(texts.items())}


def each_ship(template):
    """key -> `template` naming each of SHIPS (as {name})"""
    return {key: template.format(name=name) for key, name in SHIPS.items()}


def variants(prefix, texts, chain="dry", voice=None, offset=0):
    """`prefix`-1, -2 ... for each of `texts`; dry lines are voiced by CREW in turn from `offset`"""
    return {f"{prefix}-{i + 1}": (text, chain, voice or CREW[(i + offset) % len(CREW)]) for i, text in enumerate(texts)}


def kill_tracks(first, last):
    """The net's kill calls on KILL_TRACKS[first:last]"""
    return {f"kill-track-{i + 1}": (f"Combat, Sea-whiz: kill on track {KILL_TRACKS[i]}.", "net") for i in range(first, last)}


# name -> (text, chain[, voice]); CHAINS (below the processing) gives each chain's default voice,
# model and processing. The order seeds each take's processing noise, so new lines go at the end.
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
    **crew_set("hit", GENERIC_REACTIONS, 0),
    # Rescue of a stricken friendly: the rescue and assistance (R and A) team and the boat crew
    **{f"rescue-{key}": (f"{name} has been hit. Away the rescue and assistance team. "
                         "R and A team, lay to the boat deck.", "1mc") for key, name in SHIPS.items()},
    "rescue-rhib-stbd": ("Away the starboard rib. Boat crew and Sar swimmer, lay to the starboard boat deck.", "1mc"),
    "rescue-rhib-port": ("Away the port rib. Boat crew and Sar swimmer, lay to the port boat deck.", "1mc"),
    "rescue-medical": ("Medical, stand by to receive casualties on the flight deck.", "1mc"),
    "rescue-lookouts": ("Lookouts, report all survivors in the water to the bridge.", "1mc"),
    # Flavor. Crew beside us in quiet stretches (two voices for the "is it over" exchange)...
    "chat-launchers": ("[tired] Where are they even coming from? Guess the Lincoln's strikes didn't get all the launchers.", "dry", CREW[0]),
    "chat-bearing": ("[muttering] That's the third one off that bearing. They've got a site out there somewhere.", "dry", CREW[3]),
    "chat-seawhiz": ("[impressed] Sea-whiz is earning its pay today.", "dry", CREW[1]),
    "chat-mikemike": ("[dry] Somebody tell supply we're gonna need a lot more twenty mike-mike.", "dry", CREW[6]),
    "chat-ears": ("[tired] My ears are still ringing from that mount.", "dry", CREW[2]),
    "chat-over": ("[quietly] ...Is it over?", "dry", CREW[5]),
    "chat-jinx": ("[tense] Don't jinx it.", "dry", CREW[4]),
    # ...and on events: a ship coming over the horizon, a friendly firing, a wreck going under
    **crew_set("arrive", each_ship("[relieved] Here comes the {name}. About damn time."), 1),
    **crew_set("shooting", each_ship("[excited] {name}'s shooting."), 3),
    **crew_set("gone", each_ship("[quietly] She's gone... {name}'s gone."), 5),
    "close-call": ("[shaken] Jesus, that one was close. I felt it.", "dry", CREW[7]),
    "multi-splash": ("[excited] Splash... and splash! Keep 'em coming!", "dry", CREW[1]),
    "we-hit": ("[shouting] We're hit! Hang on!", "dry", CREW[0]),
    "shells-incoming": ("[shouting] Incoming! Those are shells, get down!", "dry", CREW[3]),
    # The CIC net
    "weapons-free": ("All stations, Combat: weapons free, weapons free.", "net"),
    **kill_tracks(0, 3),
    "raid-size": ("Combat, all stations: multiple new contacts, raid size increasing.", "net"),
    # The 1MC: Zebra after general quarters, a new ship taking station, the Captain, damage control
    "set-zebra": (HURRIED + "Set material condition Zebra throughout the ship.", "1mc-hurried"),
    **{f"joined-{key}-{side}": (f"U S S {name} has joined the formation, taking station two thousand yards off our {side} quarter.", "1mc")
       for key, name in SHIPS.items() for side in ("port", "starboard")},
    "captain": ("All hands, this is the Captain. Good work. Stay sharp, this isn't over.", "1mc", VOICE_CAPTAIN),
    "dc-report": ("Damage control parties, report status to D C Central.", "1mc"),
    # More wordings for the lines that come round often, so none repeats verbatim for minutes
    **crew_set("close-call", dict(enumerate([
        "[shaken] Whoa... that was way too close.",
        "[breathless] Holy hell, that was right on top of us.",
        "[shaken] I felt that one in my teeth.",
        "[nervous laugh] Okay... okay. That one almost had our name on it.",
        "[shaken] Too close. Way too close."], 2)), 2),
    **crew_set("multi-splash", dict(enumerate([
        "[excited] Two down! Keep it up!",
        "[excited] Got 'em both!",
        "[excited] Splash two! Nice shooting!",
        "[excited] Look at that thing go! Back to back!",
        "[excited] Another one... and another one!"], 2)), 4),
    **crew_set("shells-incoming", dict(enumerate([
        "[shouting] Shells inbound! Heads down!",
        "[urgent] More shells coming in!",
        "[shouting] Incoming rounds, take cover!"], 2)), 5),
    "kill-splash-one": ("Splash one.", "net"),
    "kill-splashed": ("Vampire splashed.", "net"),
    "kill-destroyed": ("Combat, Sea-whiz: target destroyed.", "net"),
    "kill-good": ("Good kill, good kill.", "net"),
    **kill_tracks(3, 5),
    # Long runs. The 1MC's ship's routine, as if it weren't general quarters, each after the
    # boatswain's pipe (the "1mc-pipe" chain)...
    **variants("pa-watch", [
        "Now relieve the watch. Relieve the watch.",
        "On deck, the oncoming watch section. Now relieve the watch.",
        "Now relieve the watch. Oncoming watch standers, relieve your stations."], "1mc-pipe", VOICE_BMOW),
    **variants("pa-sweepers", [
        "Sweepers, sweepers, man your brooms. Give the ship a good clean sweep down, fore and aft. "
        "Sweep down all lower decks, ladder wells and passageways. Now sweepers.",
        "Now sweepers, sweepers, man your brooms. Clean sweep down fore and aft. Empty all trash receptacles.",
        "Sweepers, sweepers, man your brooms. Give the ship a clean sweep down fore and aft. "
        "Missile debris goes over the side, not in the trash."], "1mc-pipe", VOICE_BMOW),
    **variants("pa-chow", [
        "Chow is now being served on the mess decks.",
        "Now the oncoming watch section, chow is now being served on the mess decks.",
        "Now battle messing. Sandwiches and coffee are being brought to all general quarters stations."], "1mc-pipe", VOICE_BMOW),
    **variants("pa-mail", [
        "Mail call, mail call. Division mail petty officers, lay to the post office.",
        "Now mail call. Mail is ready for pickup at the post office.",
        "Mail call. Division mail petty officers, lay to the post office. Care packages are in."], "1mc-pipe", VOICE_BMOW),
    **variants("pa-taps", [
        "Taps, taps, lights out. All hands turn into your racks. Maintain silence about the decks. Now taps.",
        "Now taps, taps. Lights out. Maintain silence about the decks.",
        "Taps, taps, lights out. Maintain silence about the decks... except for the Sea-whiz."], "1mc-pipe", VOICE_BMOW),
    **variants("pa-reveille", [
        "Reveille, reveille. All hands heave out and trice up.",
        "Reveille, reveille. Heave out and trice up. The smoking lamp is lighted in all authorized spaces.",
        "Now reveille, reveille. All hands heave out. Not that anybody was asleep."], "1mc-pipe", VOICE_BMOW),
    # ...the crew wearing down as the hours go by...
    **variants("tired-1", [
        "[tired] How long have we been at GQ now?",
        "[sighs] Anybody know what time it is? I've lost track.",
        "[muttering] They said this would be a short one.",
        "[tired] My legs are asleep. Is that normal?"], offset=1),
    **variants("tired-2", [
        "[annoyed] Who drank the last of the coffee? Seriously, who?",
        "[tired] I'd kill for a slider right now.",
        "[groaning] I can't remember the last time I sat down.",
        "[tired] If anybody's making a coffee run, I'll take three."], offset=3),
    **variants("tired-3", [
        "[exhausted] I can't feel my ears anymore.",
        "[tired] I think I've forgotten what quiet sounds like.",
        "[dazed] I keep hearing that mount when it's not even firing.",
        "[exhausted] Pretty sure my coffee's gone cold three times now."], offset=5),
    **variants("tired-4", [
        "[delirious laugh] I see vampires when I close my eyes.",
        "[deadpan] I live here now. This is my life.",
        "[exhausted] Wake me up when it's over.",
        "[dazed] What day is it? Don't answer that."], offset=7),
    # ...the mount, which the crew call R2-D2...
    **variants("r2", [
        "[proud] R2's earned his pay today.",
        "[laughing] Somebody give R2-D2 a raise.",
        "[fondly] Remind me to buy R2 a beer when we get home.",
        "[impressed] Good old R2. Never gets tired."], offset=2),
    # ...the Captain, more so the longer it goes on (captain is the first of his first lot)...
    "captain-2": ("All hands, this is the Captain. Outstanding shooting. Keep it up.", "1mc", VOICE_CAPTAIN),
    "captain-3": ("All hands, this is the Captain. Well done, every one of you. Stay on your toes.", "1mc", VOICE_CAPTAIN),
    **variants("captain-medal", [
        "All hands, this is the Captain. I'm putting the whole mount crew in for a medal. Hell, I'm putting the mount in for one.",
        "This is the Captain. When this is over, there's a commendation for everyone in Combat. Stay sharp.",
        "All hands, this is the Captain. I've never seen shooting like this. I'm proud of every one of you."], "1mc", VOICE_CAPTAIN),
    **variants("captain-cost", [
        "All hands, this is the Captain. Somebody tell the Pentagon what this is costing. Then keep shooting.",
        "This is the Captain. Supply tells me we're running up quite a tab. I've told Supply to keep it coming.",
        "All hands, this is the Captain. I've just been asked to justify our ammunition budget. I pointed at the horizon."], "1mc", VOICE_CAPTAIN),
    **variants("captain-long", [
        "All hands, this is the Captain. Twenty-two years in the Navy, and this is the longest day of my life. Carry on.",
        "This is the Captain. I'm told it's been over two hours. It feels like two weeks. Outstanding work.",
        "All hands, this is the Captain. The galley's sending up sandwiches. Eat at your stations. That's an order."], "1mc", VOICE_CAPTAIN),
    # ...what it's all cost, at each milestone...
    **variants("cost-1", [
        "[whistles] Somebody's gonna have to explain this ammo bill.",
        "[muttering] That's gotta be forty million in missiles by now.",
        "[dry] And there goes my tax refund."], offset=4),
    **variants("cost-2", [
        "[stunned] We just shot a whole F-35.",
        "[dry] Congratulations, everybody. That's an F-35, gone, one round at a time.",
        "[laughing] Hundred million dollars. We could've bought a jet."], offset=6),
    **variants("cost-3", [
        "[stunned] Half a billion dollars. Half. A. Billion.",
        "[dry] I just did the math. You don't want to know the math.",
        "[muttering] Five hundred million dollars, and they still won't fix the ice machine."], offset=0),
    **variants("cost-4", [
        "[awed] Two billion. We've fired off the price of this whole ship.",
        "[deadpan] We could've built another destroyer with what we've shot today.",
        "[laughing] At this point it'd be cheaper to buy them a new launcher site."], offset=2),
    # ...and what turns up now and then
    **variants("dolphins", [
        "[delighted] Hey, dolphins! Off the bow!",
        "[amazed] Look at that, a whole pod of dolphins... in the middle of all this.",
        "[laughing] Dolphins! They don't care about any of it, do they?"], offset=3),
    **variants("whale-port", [
        "[excited] Whale! Port side!",
        "[amazed] Thar she blows! Port beam!",
        "[awed] Look, port side... a whale. Look at the size of her."], offset=5),
    **variants("whale-starboard", [
        "[excited] Whale! Starboard side!",
        "[amazed] Thar she blows! Starboard beam!",
        "[awed] Look, starboard side... a whale. Look at the size of her."], offset=1),
    **variants("sailboat", [
        "[incredulous] Who let him in here?",
        "[baffled] Is that a sailboat? What is he doing out here?",
        "[shouting] Somebody tell that sailboat this is a war zone!"], offset=7),
    **variants("flyby", [
        "Sea-whiz, Seahawk six-one, passing close aboard. Nice shooting down there.",
        "Combat, Seahawk six-one, overhead. That's some fine shooting, Sea-whiz.",
        "Seahawk six-one, low pass down your side. Keep it up down there, we'll stay out of your way."], "net", VOICE_PILOT),
    **variants("bird", [
        "Combat, Sea-whiz: new track, close aboard, low and slow... Negative, disregard. That's a bird.",
        "Sea-whiz has a small contact, close in... Disregard, disregard. It's a seagull.",
        "Combat, Sea-whiz, new track... Cancel track. Bird."], "net"),
    **variants("duck", [
        "[baffled] Is that... a rubber duck?",
        "[laughing] There's a rubber duck floating past us. A rubber duck.",
        "[deadpan] Rubber duck in the water. Nobody tell the Captain."], offset=4),
    # Holidays: the Fourth of July's fireworks, Halloween's pumpkins, and Christmas Eve's visitor
    **variants("july4", [
        "[laughing] Happy Fourth of July, everybody!",
        "[excited] Best fireworks I've ever seen!",
        "[cheering] Happy birthday, America!"], offset=6),
    **variants("halloween", [
        "[confused] Was that... a pumpkin?",
        "[laughing] Are they shooting pumpkins at us now?",
        "[dry] Happy Halloween, I guess."], offset=0),
    **variants("sleigh", [
        "Combat, Sea-whiz: new track, high and slow... Hold fire, hold fire! That's a friendly.",
        "Sea-whiz, check fire, check fire. Track is friendly. I say again, track is friendly.",
        "Combat, Sea-whiz: one large contact, eight small, high and slow... Hold fire. Hold fire. That's a friendly."], "net"),
    **variants("sleigh-crew", [
        "[whispering] Was that... what I think it was?",
        "[awed] I'm putting that in my letter home.",
        "[giddy] He's real. I told you he was real!"], offset=2),
    # Second and third wordings, so every bucket has at least three lines for each situation
    "general-quarters-2": (HURRIED + "General quarters, general quarters! All hands man your battle stations. "
                           "Up and forward to starboard, down and aft to port.", "1mc-hurried"),
    "general-quarters-3": (HURRIED + "General quarters, general quarters. This is not a drill. All hands man your battle stations.", "1mc-hurried"),
    "set-zebra-2": (HURRIED + "Set condition Zebra, set condition Zebra throughout the ship.", "1mc-hurried"),
    "set-zebra-3": (HURRIED + "All hands, set material condition Zebra. Close all Zebra fittings.", "1mc-hurried"),
    "weapons-free-2": ("Combat, all stations: you are weapons free. Weapons free.", "net"),
    "weapons-free-3": ("All stations, Combat: weapon status is free. I say again, weapons free.", "net", VOICE_NET_2),
    "raid-size-2": ("All stations, Combat: be advised, multiple new contacts on the horizon. Raid size increasing.", "net"),
    "raid-size-3": ("Combat, all stations: new raid inbound, raid count increasing.", "net", VOICE_NET_2),
    "missile-launch-2": ("Missile launch, missile launch. All hands stand clear of the forward launcher.", "1mc"),
    "missile-launch-3": ("Stand by for missile launch, forward launcher. All hands stay clear of the weather decks.", "1mc"),
    "birds-away-2": ("Missile away.", "net", VOICE_NET_2),
    "birds-away-3": ("Bird away, bird away.", "net"),
    "we-hit-2": ("[shouting] Brace, brace! We took one!", "dry", CREW[3]),
    "we-hit-3": ("[shouting] We're hit! Everybody okay?", "dry", CREW[6]),
    "dc-report-2": ("All repair lockers, report status to D C Central.", "1mc"),
    "dc-report-3": ("D C Central, all stations: report damage and casualties.", "1mc"),
    **{f"rescue-{key}-2": (f"Away the rescue and assistance team, away the R and A team. {name} is hit. "
                           "R and A team, lay to the boat deck.", "1mc") for key, name in SHIPS.items()},
    **{f"rescue-{key}-3": (f"Rescue and assistance team, lay to the boat deck for {name}. Away the R and A team.", "1mc")
       for key, name in SHIPS.items()},
    **{f"shooting-{key}-2": (text, "dry", CREW[(i + 5) % len(CREW)]) for i, (key, text) in enumerate(each_ship("[excited] There go {name}'s birds!").items())},
    **{f"shooting-{key}-3": (text, "dry", CREW[(i + 7) % len(CREW)]) for i, (key, text) in enumerate(each_ship("[excited] Look, {name}'s firing!").items())},
    **{f"gone-{key}-2": (text, "dry", CREW[(i + 1) % len(CREW)]) for i, (key, text) in enumerate(each_ship("[quietly] {name}'s going under...").items())},
    **{f"gone-{key}-3": (text, "dry", CREW[(i + 3) % len(CREW)]) for i, (key, text) in enumerate(each_ship("[somber] That's it. {name}'s gone.").items())},
    **{f"arrive-{key}-2": (text, "dry", CREW[(i + 4) % len(CREW)]) for i, (key, text) in enumerate(each_ship("[relieved] Ship on the horizon... that's the {name}.").items())},
    **{f"arrive-{key}-3": (text, "dry", CREW[(i + 6) % len(CREW)]) for i, (key, text) in enumerate(each_ship("[pleased] Look, the {name}'s coming up to join us.").items())},
    **{f"joined-{key}-{side}-2": (f"{name} is on station, two thousand yards off our {side} quarter.", "1mc", VOICE_BMOW)
       for key, name in SHIPS.items() for side in ("port", "starboard")},
    **{f"joined-{key}-{side}-3": (f"Be advised, U S S {name} has joined the formation, two thousand yards on our {side} quarter.", "1mc")
       for key, name in SHIPS.items() for side in ("port", "starboard")},
    # Someone wondering whether it's over (two voices), and the answers (three others)
    "chat-over-2": ("[hopeful] Is that... is that the last of them?", "dry", CREW[2]),
    "chat-over-3": ("[whispering] Did it stop? I think it stopped.", "dry", CREW[5]),
    "chat-jinx-2": ("[tense] Shh. You'll jinx it.", "dry", CREW[0]),
    "chat-jinx-3": ("[firmly] Don't even say it.", "dry", CREW[6]),
    "chat-jinx-4": ("[grim] Never ask that. Never.", "dry", CREW[4]),
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


def bosun_pipe(seed):
    """The boatswain's call's "Attention": a breathy whistle gliding up to its high note, held with
    a slight waver, then falling away"""
    n = int(1.9 * SR)
    t = np.arange(n) / SR
    lo, hi = 1950.0, 2750.0
    rise, fall = 0.18, 1.55
    f = np.where(t < rise, lo + (hi - lo) * (t / rise) ** 0.6,
                 np.where(t < fall, hi, hi - (hi - lo) * ((t - fall) / (t[-1] - fall)) ** 1.5))
    f = f * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t))
    phase = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(phase) + 0.08 * np.sin(2 * phase)
    breath = signal.sosfilt(sos("bandpass", [1800, 5000], 2), rng_noise(n, seed))
    env = np.clip(t / 0.05, 0, 1) * np.clip((t[-1] - t) / 0.12, 0, 1)
    return (tone + 0.12 * breath / np.max(np.abs(breath))) * env


def pipe_chain(x, seed):
    # The pipe, a breath, then the call, all through the 1MC
    pipe = bosun_pipe(seed) * 0.5 * np.max(np.abs(x))
    return onemc_chain(np.concatenate([pipe, np.zeros(int(0.45 * SR)), x]), seed)


# chain -> ElevenLabs voice, model and settings, processing, and the target loudness (RMS, dBFS)
CHAINS = {
    "net": {"voice": VOICE_NET, "settings": {"stability": 0.38, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True, "speed": 1.08},
            "process": net_chain, "rms_db": -15},
    "1mc": {"voice": VOICE_1MC, "settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True},
            "process": onemc_chain, "rms_db": -17},
    "1mc-hurried": {"voice": VOICE_1MC, "model": "eleven_v3", "settings": {"stability": 0.0, "similarity_boost": 0.8, "speed": 1.2},
                    "process": onemc_chain, "rms_db": -17},
    "1mc-pipe": {"voice": VOICE_BMOW, "settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True},
                 "process": pipe_chain, "rms_db": -17},
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
    names = []
    for i, (name, (_, chain, *_)) in enumerate(LINES.items()):
        src = SRC / f"{name}.mp3"
        if not src.exists():
            print("missing", src)
            continue
        c = CHAINS[chain]
        y = finish(c["process"](trim(decode(src)), i), rms_db=c["rms_db"])
        encode(y, OUT / f"{name}.mp3")
        print(f"wrote sounds/{name}.mp3  {len(y) / SR:.2f} s  peak {20 * np.log10(np.max(np.abs(y))):.1f} dBFS")
        names.append(name)
    # The game loads the clips this lists (index.html, loadCallouts)
    (OUT / "callouts.json").write_text(json.dumps(names, indent=1) + "\n")
    print(f"wrote sounds/callouts.json  {len(names)} clips")


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
