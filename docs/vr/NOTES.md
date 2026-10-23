# VR notes

## Audio on Vision Pro (visionOS 26, Safari 26.3), 2026-10-22

visionOS plays everything Safari outputs from a fixed place in the room, about where the Safari
window was, and tracks the head itself. That includes Web Audio inside a WebXR session, plain mono
and plain stereo. A page can't put sounds around the listener: its left/right panning only shifts
the sound a little around that spot. Cues that turn with the head (the game's spatializer, or a
`PannerNode` with the listener following the head) get turned a second time by visionOS, which sounds
wrong (a source behind "sounded very weird" when turning).

There was no Spatial Audio setting (Off / Fixed / Head Tracked) for Safari in Control Center, even
with an `<audio>` element and Media Session metadata playing so Safari was Now Playing.

So in VR the game keeps the listener at the station's facing (`refreshListener`) and lets visionOS
do the head tracking. Real positional audio around the listener needs a native app (RealityKit).

The test: `tools/xr-audio-test.html`, served by `tools/serve_xr.py` (it saves the answers to
`xr-audio-results.jsonl` here). The first run's answers, sounds in this order, all "stayed put in
the room": stereo hard left: left. PannerNode 90° left: ahead. PannerNode behind: right (and odd when
turning). Mono: ahead. Stereo hard right: left of the marker ahead. PannerNode 90° right: right.

### Why: WebKit's source (main, checked 2026-10-22)

It's by design. On visionOS WebKit gives every audio output a head-tracked spatial experience
anchored to the page: `AudioSessionIOS::updateSpatialExperience` sets
`AVAudioSessionSpatialExperienceHeadTracked` anchored to the window's scene, and Web Audio's output
unit gets a `CAHeadTrackedSpatialAudio` from `createSpatialAudioExperienceWithOptions`
(`SpatialAudioExperienceHelper.mm`), anchored to the page's layer or scene. No path asks for
non-spatial (head-locked) output, and nothing changes it for a WebXR session. The one related
preference, `PreferSpatialAudioExperience`, is `internal` (not in Safari's Feature Flags) and only
chooses between two anchored variants. WebKit bug 261367 ("[visionOS] Audio does not spatialize
correctly with multiple windows") is about the same anchoring.
