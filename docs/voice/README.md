# Voice buckets

Every spoken line in the game (the CIC net, the 1MC and the crew) comes from a **bucket**: a named
group of recorded clips in `BUCKETS` (`index.html`). A trigger asks for a line with
`AudioController.play(name, params, t, lead)`. The engine then decides whether a line goes out,
which clip it is, and when it starts.

The clips are made by `tools/make_cic_audio.py`. Its `process` command also writes
`sounds/callouts.json`, the list of clips that the game loads.

## Fields

| Field | Meaning |
|---|---|
| `clips` | Clip names. `{ship}`, `{side}` and `{bearing}` are filled from `play`'s params. |
| `channel` | `net`: the CIC net, at once (with the 1MC's urgent calls). `1mc`: the ship's loudspeakers, queued in order. `crew`: next to us, dry. |
| `aside` | Flavour. It waits until no one is talking and no launch is under way. |
| `onlyIfClear` | It never interrupts. It's skipped outright unless everything is clear. Used for vampire calls. |
| `hush` | A channel whose lines wait until this line is over, plus their gap (`hushUntil`). The vampire call hushes the crew. |
| `urgent` | It goes out on time or not at all. It only takes a clip that's already decoded, and starts loading the others for next time. Its first clip (on every bearing in `CALLED_BEARINGS`, 000 to 330, if it names one) is fetched and decoded at start-up and kept (`URGENT_CALLOUTS`). |
| `keep` | With `urgent`: all its clips are loaded at start-up and kept, not just the first, so the rotation always has every one to choose from (the kill calls, general quarters, "Stand by for missile launch" and "Birds away"). |
| `cooldown` | Seconds before the bucket can play again (`Infinity`: once a game). It's spent only if a line goes out. |
| `repeat` | Seconds before the same clip can play again. The default is `VOICE_REPEAT_WINDOW` (300). `0` is for procedural calls, which real crews repeat word for word. |
| `lead`, `jitter` | Seconds from the trigger to the line, plus up to `jitter` more. `play`'s `lead` argument overrides `lead`: the vampire call goes out `VOICE_TRIGGERS.alarm.lead` after the general alarm. |
| `chance` | How often the line is tried, from 0 to 1. |
| `stale` | Seconds late the line may go out before it's dropped. The default is the channel's. |
| `rank(clip, params)` | Lower is preferred among the fresh clips. Ties go round-robin. Damage control ranks by side, kind and frame; the crew's reaction prefers naming the ship (or not, by `params.named`). |
| `then` | The bucket that follows this one, from the end of its line, with the same params (vampire, then GQ, then Zebra; the crew's "We're hit!", then damage control's call, then a call for reports; `is-it-over`, then `is-it-over-reply`: "Is it over?", then "Don't jinx it"). |
| `thenAlways` | `then` follows even if this line doesn't go out, from the trigger's time. Damage control's call doesn't depend on the crew's shout. |

`BUCKETS` holds only how a line plays. When a trigger asks for one is up to the trigger, and its
settings are in `VOICE_TRIGGERS`: the general alarm's `cooldown` and `lead` before a vampire call,
the multi-splash `window`, the rescue call's `gap` after the crew's reaction, chatter's `delay` and
`retry`, and the captain's `kills`, `action` and `quiet`.

Every bucket has at least three lines for each situation it covers (each ship, side or bearing), so
none is heard over and over.

## Policies

- **Picking.** Each bucket keeps a cursor that starts at a random clip. A pick walks forward from the
  cursor, skips clips heard within `repeat` seconds and takes the first one left (or the best
  ranked). If none are fresh, the bucket stays quiet and its cooldown isn't spent. A line spends the
  cooldown as soon as it's picked (`reserve`), including while it waits in the 1MC's queue, and gives
  it back if it's dropped (`release`).
- **Channels.** The CIC net, the 1MC and the crew are separate lines (separate circuits on a real
  ship), so a long 1MC announcement doesn't keep "Birds away" off the net. A line starts at its due time, or as soon after as its line is free (`VOICE.gap`).
  It's dropped if it would start more than `stale` seconds late.
- **Priorities.** Vampire calls never interrupt anyone, and they're skipped when anything is on.
  Crew lines never overlap each other, and wait until a vampire call is over (`hush`). 1MC calls go
  out one at a time, in the order queued.
- **Launches.** `warnVLSLaunch` starts the alarm once the latest vampire call is over (the vampire
  bucket's last line, `bucketState.vampire.voice`), and holds the flavour lines from its warning until
  about 2 seconds after the round fires (`holdRadio`, which sets `launchUntil`). A net aside that
  comes up then is passed over rather than booked for after the hold, where it would take the net
  "Birds away" needs. "Birds away" waits up to 5 seconds for the net. An offline render
  (`makeOffline`) never holds anything.
- **Loading.** Only `URGENT_CALLOUTS` are fetched at start-up. Every other clip is fetched and
  decoded on first use (`getCallout`), or earlier when an urgent bucket warms it.
  Lazily decoded clips past `LAZY_CALLOUT_SECONDS` are dropped, least recently used first, and
  decoded again from their kept bytes. A clip that's missing from `sounds/callouts.json` or fails to
  load silences that line. `makeOffline({ decodeAll: true })` fetches and decodes the lot.

## In VR

On screen the voices aren't positioned. In VR each comes from a place on deck (`VOICE_POSITIONS`,
through `voiceOut`): the CIC net from a squawk box on the bridge front behind the station, the 1MC
and its alarms from a loudspeaker higher on the bridge front, and each crew member from where they
stand around the station. Which crew member says a line comes from `sounds/speakers.json` (an index
into `CREW` in `make_cic_audio.py`), which `process` writes, or `speakers` on its own.

## Long runs

`updateLongRun` (game code) drives the long-run lines from the real time played (`longRun.played`):
the 1MC's routine buckets (`pa-*`) on a timer, the cost buckets (`cost-1` to `cost-4`) as the total
passes each milestone, and each sighting's line as it comes into view (`SIGHTINGS`). Lines that must
eventually get a word in go through `sayEventually`, which tries again every few seconds. The crew's
tired buckets and `r2` join the chatter as `LONG_RUN.tired` unlocks them, each as likely as the
plain chatter; the Captain speaks from his latest lot (`LONG_RUN.captain`) two times in three, all
his lots on one cooldown (`VOICE_TRIGGERS.captain.cooldown`). `tools/long_run_voices.py` checks them.

## Probes

- `zen_voices.py [seconds] out.json [tree]` runs zen mode and logs every line (with its bucket),
  launch warning and launch from our ship, and the page's no-repeat window.
- `analyse.py out.json` reports repeats (and any within the no-repeat window), lines by bucket and
  what each of our ship's launches got.
- `tools/voice_capture.py out.webm birds` checks that "Birds away" goes out after both kinds of
  launch, with a 1MC call queued during each warning going out after it.
- `count_lines.py [index.html]` counts the voice code's lines.
