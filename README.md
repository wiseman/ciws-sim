# Phalanx CIWS Defense Simulator

<div align="center">
  <img src="screenshot.png" alt="CIWS Sim Screenshot" width="100%" />
</div>

<div align="center">
  <a href="https://ciws.obliscence.com">
    <img src="https://img.shields.io/badge/Play_Live-ciws.obliscence.com-blue?style=for-the-badge&logo=google-chrome" alt="Play Live" />
  </a>
</div>

<br />

A vibecoded web-based simulation of the Phalanx CIWS (Close-In Weapon System) defense system.

## Running locally

It's a single `index.html` plus the voice clips in `sounds/`; serve the directory and open it:

```sh
python3 -m http.server 8000
```

Then open http://localhost:8000. Click or press a key to start the audio, and use the AUDIO button to unmute.

## Controls

| Key | Action |
| --- | --- |
| `C` | Cycle cameras: orbit, Phalanx, missile follow, split screen |
| `V` | Toggle the split-screen view (gunsight + chase camera) |
| `Z` | Zen mode: no UI, an endless battle and cinematic camera cuts (`Z` or `Esc` to leave) |
| `M` | Fire-control panel (classic solver / neural net) |
| `A` | Audio debug overlay |

The buttons at the top right switch the camera, audio, slow motion, spatial-audio mode and zen mode.

## Voice lines

The crew, CIC net and 1MC callouts are recorded clips in `sounds/`, generated and processed by
`tools/make_cic_audio.py`. Its `process` step also writes `sounds/callouts.json`, the list of clips
the game loads. How each line plays is set in the game's `BUCKETS` table; see
[docs/voice/README.md](docs/voice/README.md).

## Long runs

The longer a session goes on (zen mode or a long game), the more turns up. It's counted in real
time played and kept for the browser tab's session, so the reboot after a game over carries on.

- The 1MC passes the ship's routine (relieve the watch, sweepers, chow, mail, and later taps and
  reveille), each after the bosun's pipe, as if it weren't general quarters.
- The crew wear down: more tired remarks join their chatter at 15 and 30 minutes and at 1 and 2
  hours, along with remarks about "R2" (the mount). After 2 hours the mount chirps now and then.
- The Captain's word grows, from "good work" to medals, to the cost, to the longest day of his life.
- The crew remark on what it's all cost (20 mm rounds and our ship's missiles) at $40 million, an
  F-35, half a billion and the price of the ship.
- A kill mark is stencilled on the back of the radome every 100 kills, and every ten become a gold
  star. Zen mode's camera visits them.
- Now and then something turns up: a Seahawk flying past (the mount tracks her as she comes close
  aboard, without firing, and the crew tell it off), dolphins, a seagull the radar sees, a
  sailboat that has wandered in, a whale, and (rarely) a rubber duck. Zen mode cuts to it.
- Holidays: fireworks on the Fourth of July, pumpkins on Halloween and a visitor on Christmas Eve.
  Add `?date=07-04` (or `10-31`, `12-24`) to the URL to see one on another day.

`LONG_RUN`, `SIGHTINGS` and `HOLIDAYS` in `index.html` hold the timings.

## Tools

The Python scripts in `tools/` (run with `uv run tools/<name>.py`) drive the game in headless
Chromium for screenshots, frame strips, audio captures, soak tests and the demo video.

## Deployment

To deploy to caprover:

```sh
tar cf deploy.tar captain-definition index.html sounds/*.mp3 sounds/callouts.json
```

Then upload the tar file to the caprover instance. The game needs `sounds/callouts.json` to find its
voice clips; without it, it runs silently.
