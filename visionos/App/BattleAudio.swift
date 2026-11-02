import AVFoundation
import CIWSSimulation
import CIWSSound
import Foundation
import RealityKit

/// The Swift scheduler decides which lines go out and when. The battle's sounds are the web game's
/// own: its synthesized buffers (tools/export_audio.mjs) and its live voices, rendered by
/// SoundSynthesis into RealityKit audio generators, so the system places every source and
/// tracks the head. RealityKit supplies the tracked listener.
@MainActor final class BattleAudio {
  struct Playing {
    var entity: Entity
    var controller: AudioPlaybackController?
    /// The pooled source a sound plays on
    var slot: Int?
    var ends: Double
    var voice: Bool
  }
  enum Cue {
    case voice(String, gain: Double)
    /// reverb: the source's reverb level (dB); nil plays it head-locked, as the web's centred thump and ringing ears
    case sound(SoundSynth, duration: Double, reverb: Double?)
  }
  struct Pending {
    var cue: Cue
    var at: Double
    var position: SIMD3<Float>
    var duration: Double
  }
  /// Battle sounds against the voices: the web's mix puts the voices at 0.8 (cicBus) against
  /// the battle at 1, and the voices here play at their line level less 6 dB
  private static let trim: Audio.Decibel = -4
  private static let threatVoice: [ThreatKind: (reference: Double, airMax: Double, level: Double)] = [
    .drone: (28, 2400, 0.45), .mortar: (40, 2400, 0), .ascm: (36, 7000, 0.32),
  ]
  // BLAST_FEEL
  private static let thumpGain = 1.4, thumpRef = 60.0, blastRange = 140.0, onset = 0.12
  private static let minHz = 450.0, blastDuck = 0.5, hold = 0.25, recover = 0.6, ring = 0.1
  // BLAST_BODY: where explosions are at full level, and how far the gun dips as one arrives (dB)
  private static let blastReference = 80.0, gunDuck = 9.0
  /// BLAST_BODY.variations: voicings of each of the web's explosions
  nonisolated private static let blastBodies = 4
  private static let ringHz = 3900.0

  private let root: Entity, immersive: Bool
  private let bus = SoundBus()
  private let sampleRate: Double
  private var bank: SoundBank?
  private var resources: [String: AudioFileResource] = [:], durations: [String: Double] = [:]
  private var loading: Set<String> = []
  private var lazy: [String] = []
  private var urgent: Set<String> = []
  private var playing: [Playing] = [], pending: [Pending] = []
  private var enabled = false, stopped = false
  private(set) var failures: [String] = []
  private weak var scheduler: VoiceScheduler?

  // The steady sources and their entities
  private var gun: GunSynth?, mount: MountSynth?
  private var seaSynths: [NoiseBedSynth] = [], wind: NoiseBedSynth?
  private let gunEntity = Entity(), mountEntity = Entity(), windEntity = Entity()
  private var generators: [AudioGeneratorController] = []
  /// The pooled sources the one-shots and threats take turns on (SourceSlot). Head-locked ones
  /// carry the blast's thump and ringing ears.
  private struct Slot {
    let entity: Entity
    let source: SourceSlot
    let headLocked: Bool
    var busy: Bool
  }
  private var slots: [Slot] = []
  private var threats: [Int: (slot: Int, synth: ThreatSynth)] = [:]
  private var released: [(slot: Int, at: Double)] = []
  private var started = Date()
  private var lastShot = -Double.infinity, lastFlak = -Double.infinity, lastNow = 0.0
  private var nextSwell = 0.0, nextGust = 0.0, nextSlap = 2.0
  private var windPan = 0.0, windPanTarget = 0.0
  /// The latest close blast's muffle: when it closes down, and how hard
  private var muffle: (at: Double, strength: Double)?
  /// Blasts the gun dips under: when each arrives, and how far (dB)
  private var gunDucks: [(at: Double, depth: Double)] = []
  private var earGain = 1.0, earCutoff = 20000.0

  init(root: Entity, immersive: Bool) {
    self.root = root
    self.immersive = immersive
    let rate = AVAudioSession.sharedInstance().sampleRate
    sampleRate = rate > 0 ? rate : 48000
    // The web's outdoor "space" round the ship; on the tabletop the room's own reverb applies
    if immersive { root.components.set(ReverbComponent(reverb: .preset(.outside))) }
  }
  func load(scheduler: VoiceScheduler) async {
    bind(scheduler)
    let rate = sampleRate
    let loaded = await Task.detached { () -> (SoundBank, [SampleBuffer])? in
      guard let index = Bundle.main.url(forResource: "web-sounds", withExtension: "json"),
        let pcm = Bundle.main.url(forResource: "web-sounds", withExtension: "bin"),
        let bank = try? SoundBank(index: Data(contentsOf: index), pcm: Data(contentsOf: pcm))
      else { return nil }
      // The shared white noise, the sea's two brown channels and the wind's pink (buildAmbient)
      let loops = [
        makeNoiseLoop(seconds: 3, color: .white, seed: 11, sampleRate: rate),
        makeNoiseLoop(seconds: 9, color: .brown, seed: 12, sampleRate: rate),
        makeNoiseLoop(seconds: 9, color: .brown, seed: 13, sampleRate: rate),
        makeNoiseLoop(seconds: 7, color: .pink, seed: 14, sampleRate: rate),
      ]
      // The web's blasts with a body the headset's speakers can play (BlastBody), each in
      // several variations so that repeats are harder to hear (voiceBlasts)
      var sounds = bank.sounds
      func voiced(_ name: String, _ body: BlastBody, mix: Float, seed: Int) -> [SampleBuffer]? {
        sounds[name]?.enumerated().flatMap { i, web in
          (0..<Self.blastBodies).map { k in
            let n = UInt64(seed + i * Self.blastBodies + k)
            return body.varied(seed: n).added(to: web, mix: mix, seed: n)
          }
        }
      }
      sounds["big"] = voiced("big", .big, mix: 1, seed: 21)
      sounds["thump"] = voiced("thump", .thump, mix: 0.8, seed: 61)
      return (SoundBank(sounds: sounds), loops)
    }.value
    guard !stopped else { return }
    if let (bank, loops) = loaded {
      self.bank = bank
      startSteadySources(bank: bank, loops: loops)
    } else {
      failures.append("web-sounds")
    }
    for name in ["general-alarm", "launch-alarm"] { await loadClip(name, extension: "wav") }
    // Urgent lines must be decoded before their synchronous scheduling decisions.
    for name in scheduler.urgentClips.sorted() { await loadClip(name, extension: "mp3") }
  }
  private func startSteadySources(bank: SoundBank, loops: [SampleBuffer]) {
    started = Date()
    let gun = GunSynth(shots: bank.sounds["shot"] ?? [], seed: 1, sampleRate: sampleRate, bus: bus)
    let mount = MountSynth(noise: loops[0], seed: 2, sampleRate: sampleRate, bus: bus)
    mountEntity.position = SoundRules.mountPosition.float
    let seas = (0..<2).map { i in
      NoiseBedSynth(sea: true, loop: loops[1 + i], seed: UInt64(3 + i), sampleRate: sampleRate, bus: bus)
    }
    let wind = NoiseBedSynth(sea: false, loop: loops[3], seed: 5, sampleRate: sampleRate, bus: bus)
    let engine = EngineSynth(level: 0.012 * 0.9, sampleRate: sampleRate, bus: bus)
    var sources: [(Entity, SoundSynth, Double?)] = [
      (gunEntity, gun, 0.35), (mountEntity, mount, nil), (windEntity, wind, nil),
    ]
    // The sea washes along both sides abreast of the station; the machinery is under the deck
    let z = SoundRules.listener.z
    for (synth, side) in zip(seas, [1.0, -1.0]) {
      let e = Entity()
      e.position = Vector3(side * (GameRules.hullHalfWidth(z) + 2), -1.2, z).float
      sources.append((e, synth, nil))
    }
    let below = Entity()
    below.position = [0, 1, Float(z)]
    sources.append((below, engine, nil))
    for (entity, synth, wet) in sources {
      entity.spatialAudio = spatial(reverb: wet.map { reverbLevel(ratio: $0 * 0.55) })
      root.addChild(entity)
      if let g = try? entity.playAudio(configuration: .init(), renderer(synth)) { generators.append(g) }
    }
    self.gun = gun
    self.mount = mount
    seaSynths = seas
    self.wind = wind
    // The pool is made up front at a raid's size, so no source starts mid-battle: on the
    // headset a new generator can miss its first sound
    let pool =
      (0..<32).compactMap { _ in takeSlot(headLocked: false) }
      + (0..<6).compactMap { _ in takeSlot(headLocked: true) }
    for i in pool { freeSlot(i) }
  }
  /// A free pooled source, or a new one while the pool is short of one
  private func takeSlot(headLocked: Bool) -> Int? {
    if let i = slots.firstIndex(where: { !$0.busy && $0.headLocked == headLocked }) {
      slots[i].busy = true
      return i
    }
    let source = SourceSlot(sampleRate: sampleRate, bus: bus)
    let e = Entity()
    if headLocked {
      e.channelAudio = ChannelAudioComponent(gain: Self.trim)
    } else {
      e.spatialAudio = spatial(reverb: nil)
    }
    root.addChild(e)
    guard let g = try? e.playAudio(configuration: .init(), renderer(source)) else {
      e.removeFromParent()
      return nil
    }
    generators.append(g)
    slots.append(Slot(entity: e, source: source, headLocked: headLocked, busy: true))
    return slots.count - 1
  }
  private func freeSlot(_ i: Int) {
    slots[i].source.play(nil)
    slots[i].busy = false
  }
  private func spatial(reverb: Audio.Decibel?) -> SpatialAudioComponent {
    // Distance falloff is the web's, applied in the synths, so RealityKit only places the source
    SpatialAudioComponent(
      gain: Self.trim, reverbLevel: reverb ?? -.infinity, distanceAttenuation: .rolloff(factor: 0))
  }
  private func reverbLevel(ratio: Double) -> Audio.Decibel {
    // PHASE's sends top out at 0 dB
    min(0, max(-60, 20 * log10(max(ratio, 1e-6))))
  }
  func bind(_ newScheduler: VoiceScheduler) {
    scheduler = newScheduler
    urgent = newScheduler.urgentClips
    if let url = Bundle.main.url(forResource: "speakers", withExtension: "json"),
      let data = try? Data(contentsOf: url),
      let map = try? JSONDecoder().decode([String: Int].self, from: data)
    {
      newScheduler.speakerOf = map
    }
    for (name, duration) in durations where resources[name] != nil {
      newScheduler.supplyClip(name, duration: duration)
    }
  }
  private func loadClip(_ name: String, extension ext: String) async {
    guard !stopped, resources[name] == nil, !loading.contains(name) else { return }
    loading.insert(name)
    defer { loading.remove(name) }
    do {
      let r = try await AudioFileResource(named: "\(name).\(ext)", configuration: .init())
      guard !stopped else { return }
      resources[name] = r
      if ext == "mp3" && !urgent.contains(name) {
        lazy.removeAll { $0 == name }
        lazy.append(name)
      }
      if let url = Bundle.main.url(forResource: name, withExtension: ext),
        let file = try? AVAudioFile(forReading: url)
      {
        let duration = Double(file.length) / file.processingFormat.sampleRate
        durations[name] = duration
        scheduler?.supplyClip(name, duration: duration)
      } else {
        scheduler?.supplyClip(name, duration: VoiceScheduler.bundledDurations[name])
      }
    } catch {
      failures.append(name)
      scheduler?.supplyClip(name, duration: nil)
    }
  }
  func update(enabled: Bool) {
    self.enabled = enabled && !stopped
    bus.paused.value = !self.enabled
    for p in playing { if let c = p.controller { setPlaying(c, self.enabled) } }
    if !self.enabled && scheduler?.isMuted == true { reset() }
  }
  private func setPlaying(_ controller: AudioPlaybackController, _ active: Bool) {
    if active && !controller.isPlaying { controller.play() }
    if !active && controller.isPlaying { controller.pause() }
  }
  func advance(simulation: Simulation, events: [SimulationEvent]) {
    let v = simulation.voices
    if scheduler !== v { bind(v) }
    for name in v.loadRequests where !loading.contains(name) {
      Task { await self.loadClip(name, extension: "mp3") }
    }
    for line in v.takeOutput() {
      if lazy.contains(line.clip) {
        lazy.removeAll { $0 == line.clip }
        lazy.append(line.clip)
      }
      pending.append(
        Pending(
          cue: .voice(line.clip, gain: 20 * log10(max(0.001, line.level)) - 6), at: line.start,
          position: line.position.float, duration: line.duration))
    }
    // Same 60-second decoded lazy-callout budget as the browser. Active playback
    // retains its resource; future scheduled lines remain pinned until they start.
    let pinned = Set(pending.compactMap { p -> String? in
      if case .voice(let name, _) = p.cue { return name }
      return nil
    })
    var total = lazy.reduce(0.0) { $0 + (durations[$1] ?? 0) }
    for name in lazy where total > 60 && lazy.count > 1 && !pinned.contains(name) {
      total -= durations[name] ?? 0
      resources.removeValue(forKey: name)
      lazy.removeAll { $0 == name }
      v.evictClip(name)
    }
    let now = v.now
    let dt = max(0, now - lastNow)
    lastNow = now
    let pitch = SoundRules.slowPitch(simulation.timeScale)
    updateGun(simulation, now: now, pitch: pitch)
    updateThreats(simulation, now: now, pitch: pitch)
    if enabled { updateAmbient(now: now, dt: dt, pitch: pitch) }
    for sound in simulation.effects.takeSounds() {
      explosion(sound, simulation: simulation, now: now)
    }
    for event in events {
      switch event {
      case .launch(let p, let size):
        playAt(
          "vlsRoar", p, now: now, gain: 0.7 * size, reference: 40, rate: Double.random(in: 0.95...1.05),
          wet: 0.3, delay: travel(p, simulation), pitch: pitch)
      case .chirp:
        playAt(
          "chirp", SoundRules.mountPosition, now: now, gain: 0.45, reference: 20, wet: 0.15, pitch: pitch)
      case .passBy(let kind, let p):
        let rotor = kind == "helicopter"
        playAt(
          rotor ? "rotor" : "bells", p, now: now, gain: rotor ? 1.2 : 0.8,
          reference: rotor ? 60 : 90, wet: 0.25, pitch: pitch)
      default: break
      }
    }
    updateEar(now: now, dt: dt)
    playing.removeAll { p in
      if now >= p.ends {
        if let i = p.slot {
          freeSlot(i)
          return true
        }
        p.controller?.stop()
        p.entity.removeFromParent()
        return true
      }
      return false
    }
    released.removeAll { r in
      if now >= r.at {
        freeSlot(r.slot)
        return true
      }
      return false
    }
    guard enabled else { return }
    bus.duck.value = Float(v.ducks.filter { $0.from <= now && now < $0.to }.map(\.level).min() ?? 1)
    // The voices go through the ear stage too, but not under the duck
    let voiceGain = 20 * log10(earGain)
    for p in playing where p.voice { p.controller?.gain = voiceGain }
    let due = pending.filter { $0.at <= now }
    pending.removeAll { $0.at <= now }
    for p in due where now < p.at + p.duration { start(p, now: now) }
  }
  private func start(_ p: Pending, now: Double) {
    switch p.cue {
    case .voice(let name, let gain):
      guard let r = resources[name] else { return }
      let e = Entity()
      e.position = p.position
      e.spatialAudio = SpatialAudioComponent(
        gain: gain, reverbLevel: -.infinity, distanceAttenuation: .rolloff(factor: 0.15))
      root.addChild(e)
      let c = e.playAudio(r)
      playing.append(Playing(entity: e, controller: c, ends: now + p.duration, voice: true))
    case .sound(let synth, let duration, let reverb):
      guard playing.count(where: { !$0.voice }) < SoundRules.maxOneShots else { return }
      guard let i = takeSlot(headLocked: reverb == nil) else { return }
      let e = slots[i].entity
      if let reverb {
        e.position = p.position
        e.spatialAudio = spatial(reverb: reverb)
      }
      slots[i].source.play(synth)
      playing.append(Playing(entity: e, slot: i, ends: now + duration + 0.1, voice: false))
    }
  }

  // MARK: - The web's per-frame audio (AudioController.frame / update)

  /// Original sound-travel delay, measured from the ship-deck station
  private func travel(_ p: Vector3, _ simulation: Simulation) -> Double {
    (p - SoundRules.listener).length / SoundRules.speedOfSound / max(simulation.timeScale, 0.001)
  }
  private func updateGun(_ s: Simulation, now: Double, pitch: Double) {
    guard let gun, let mount else { return }
    if s.isFiring && !s.isPaused { lastShot = now }
    let interval = 1 / (60 * max(s.timeScale, 0.001))
    gun.held.value = enabled && now - lastShot < max(0.05, interval * 2.5)
    gun.interval.value = Float(interval)
    gun.pitch.value = Float(pitch)
    // A dip under each blast: down just before it arrives, held, then back over about a second
    gunDucks.removeAll { now - $0.at > 2 }
    let duck = gunDucks.map { b -> Double in
      let t = now - b.at + 0.03
      return t < 0 ? 0 : b.depth * (t < 0.15 ? 1 : exp(-(t - 0.15) / 0.35))
    }.max() ?? 0
    gun.level.value = Float(
      0.32 * SoundRules.gunFatigue(Date().timeIntervalSince(started)) * pow(10, -duck / 20))
    gunEntity.position = s.muzzlePosition.float
    mount.barrelSpeed.value = Float(s.barrelSpeed)
    mount.slew.value = Float(abs(s.yawRate) + abs(s.pitchRate))
    mount.pitch.value = Float(pitch)
  }
  private func updateThreats(_ s: Simulation, now: Double, pitch: Double) {
    let listener = SoundRules.listener
    var seen = Set<Int>()
    for t in s.threats {
      seen.insert(t.id)
      // Only while audible: muting resets the audio every frame
      if threats[t.id] == nil, bank != nil, enabled {
        let synth = ThreatSynth(
          kind: t.kind == .ascm ? .ascm : t.kind == .mortar ? .mortar : .drone,
          seed: UInt64(t.id &* 2_654_435_761 & 0xFFFF_FFFF) + 1, sampleRate: sampleRate, bus: bus)
        if let i = takeSlot(headLocked: false) {
          slots[i].entity.spatialAudio = spatial(reverb: nil)
          slots[i].source.play(synth)
          threats[t.id] = (i, synth)
        }
      }
      guard let (slot, synth) = threats[t.id], let spec = Self.threatVoice[t.kind] else { continue }
      slots[slot].entity.position = t.position.float
      let distance = (t.position - listener).length
      // Doppler from the closing speed (velocity is per sim step)
      let closing = simd_dot(t.velocity, (listener - t.position).normalized) * 60
      let doppler = SoundRules.doppler(closingSpeed: closing)
      var frequency = doppler * pitch, level = spec.level
      switch t.kind {
      case .mortar:
        // Whistle only on the way down, falling in pitch as it drops
        let falling = min(max(-t.velocity.y / 2.5, 0), 1)
        frequency *= 1 - 0.35 * falling
        level = 0.35 * falling
      case .drone:
        // Diving, the engine winds up, the prop over-speeds and the air rush comes in
        frequency *= 1 + 0.25 * t.engineLoad
        synth.rush.value = Float(0.3 * t.engineLoad)
      case .ascm: break
      }
      synth.frequency.value = Float(frequency)
      synth.band.value = Float(doppler * pitch)
      synth.level.value = Float(level)
      synth.air.value = Float(min(spec.airMax, SoundRules.airCutoff(distance)))
      synth.distanceGain.value = Float(
        SoundRules.distanceGain(distance, reference: spec.reference))
    }
    for (id, voice) in threats where !seen.contains(id) {
      voice.synth.released.value = true
      released.append((voice.slot, now + 0.4))
      threats.removeValue(forKey: id)
    }
  }
  private func updateAmbient(now: Double, dt: Double, pitch: Double) {
    if now >= nextSwell {
      // Two mono sources stand in for the web's stereo wash
      let level = Float(Double.random(in: 0.025...0.075) * 0.9 * 0.7)
      for sea in seaSynths { sea.level.value = level }
      nextSwell = now + Double.random(in: 1.5...4.5)
    }
    if let wind, now >= nextGust {
      let gust = Double.random(in: 0..<1)
      wind.level.value = Float((0.025 + gust * 0.05) * 0.9)
      wind.center.value = Float(350 + gust * 600)
      windPanTarget = Double.random(in: -1...1) * SoundRules.windSweep
      nextGust = now + Double.random(in: 1...4)
    }
    // The gusts sweep about the station, as the web pans its wind
    windPan += (windPanTarget - windPan) * (1 - exp(-dt / 1.5))
    let f = SoundRules.facing, right = Vector3(-f.z, 0, f.x)
    let a = windPan * .pi / 2
    windEntity.position = (SoundRules.listener + (f * cos(a) + right * sin(a)) * 15 + [0, 3, 0]).float
    if now >= nextSlap {
      // Waves slap the hull just outside its waterline
      let side = Bool.random() ? -1.0 : 1.0
      let z = Double.random(in: -38...70)
      let p = Vector3(side * (GameRules.hullHalfWidth(z) + 0.2), -1.5, z)
      playAt(
        "slap", p, now: now, gain: Double.random(in: 0.25...0.45), reference: 6,
        rate: Double.random(in: 0.8...1.2), wet: 0.05, pitch: pitch)
      nextSlap = now + Double.random(in: 1.5...5.5)
    }
  }
  /// playExplosion
  private func explosion(_ sound: ExplosionSound, simulation s: Simulation, now: Double) {
    guard enabled else { return }
    let p = sound.position, delay = travel(p, s), pitch = SoundRules.slowPitch(s.timeScale)
    let vary = { Double.random(in: 0.92...1.08) }
    switch sound.kind {
    case .flak:
      // Rounds burst at up to 60/s; thin them out so it crackles instead of roaring
      guard now - lastFlak >= 0.07 else { return }
      lastFlak = now
      playAt("pop", p, now: now, gain: 0.5, reference: 25, rate: vary(), wet: 0.25, delay: delay, pitch: pitch)
    case .hit:
      playAt("hit", p, now: now, gain: 0.6, reference: 18, rate: vary(), wet: 0.15, delay: delay, pitch: pitch)
    case .airburst, .impact:
      let big = sound.kind == .airburst, gain = (big ? 1.5 : 2.0) * Double.random(in: 0.8...1.12)
      playAt(
        "big", p, now: now, gain: gain, reference: Self.blastReference,
        rate: big ? vary() : vary() * 0.85, wet: 0.35, delay: delay, pitch: pitch)
      let heard = gain * SoundRules.distanceGain((p - SoundRules.listener).length, reference: Self.blastReference)
      gunDucks.append((now + delay, Self.gunDuck * min(1, heard / 0.5)))
      if !big && s.isOverOpenWater(p) {
        playAt(
          "splash", p, now: now, gain: 1, reference: 30, rate: vary(), wet: 0.2, delay: delay + 0.05,
          pitch: pitch)
      }
      if immersive { blast(distance: (p - SoundRules.listener).length, at: now + delay) }
    }
  }
  /// A one-shot at a world position `delay` seconds from now (playAt)
  private func playAt(
    _ name: String, _ position: Vector3, now: Double, gain: Double, reference: Double,
    rate: Double = 1, wet: Double, delay: Double = 0, pitch: Double
  ) {
    guard enabled, let buffer = bank?.sounds[name]?.randomElement() else { return }
    let distance = (position - SoundRules.listener).length
    let distanceGain = SoundRules.distanceGain(distance, reference: reference)
    let ratio = SoundRules.reverbRatio(wet: wet, distance: distance, distanceGain: distanceGain)
    let direct = gain * distanceGain
    guard direct >= SoundRules.audibleFloor || direct * ratio >= SoundRules.audibleFloor else { return }
    let synth = OneShotSynth(
      buffer: buffer, rate: rate * pitch, gain: direct, cutoff: SoundRules.airCutoff(distance),
      sampleRate: sampleRate, bus: bus)
    pending.append(
      Pending(
        cue: .sound(synth, duration: synth.duration, reverb: reverbLevel(ratio: ratio)),
        at: now + delay, position: position.float, duration: synth.duration))
  }
  /// VR: a big blast `distance` away whose sound arrives at `at`: its thump, and if it's close,
  /// for a moment everything muffled and quieter under ringing ears. The web's shake of the
  /// world isn't carried over: moving the world under a headset is uncomfortable.
  private func blast(distance: Double, at: Double) {
    if let buffer = bank?.sounds["thump"]?.randomElement() {
      let thump = OneShotSynth(
        buffer: buffer, rate: Double.random(in: 0.9...1.1),
        gain: Self.thumpGain * Double.random(in: 0.85...1.1)
          * pow(Self.thumpRef / max(Self.thumpRef, distance), 1.5),
        sampleRate: sampleRate, bus: bus)
      pending.append(
        Pending(
          cue: .sound(thump, duration: thump.duration, reverb: nil), at: at, position: .zero,
          duration: thump.duration))
    }
    let strength = pow(max(0, 1 - distance / Self.blastRange), 1.5)
    guard strength > 0 else { return }
    muffle = (at + Self.onset, strength)
    let ring = RingSynth(
      hz: Self.ringHz * Double.random(in: 0.95...1.05), level: Self.ring * strength,
      sampleRate: sampleRate, bus: bus)
    let length = 0.3 + RingSynth.fade * 1.5
    pending.append(
      Pending(
        cue: .sound(ring, duration: length, reverb: nil), at: at + Self.onset, position: .zero,
        duration: length))
  }
  /// The ear stage's setTargetAtTime curves: down to the blast's muffle, held, then recovering
  private func updateEar(now: Double, dt: Double) {
    var gainTarget = 1.0, cutoffTarget = 20000.0, tc = 0.1
    if let m = muffle, now >= m.at {
      if now < m.at + Self.hold {
        gainTarget = 1 - Self.blastDuck * m.strength
        cutoffTarget = 20000 * pow(Self.minHz / 20000, m.strength)
        tc = 0.015
      } else {
        tc = Self.recover * (1 + m.strength)
        if now > m.at + Self.hold + tc * 8 { muffle = nil }
      }
    }
    let k = 1 - exp(-dt / tc)
    earGain += (gainTarget - earGain) * k
    earCutoff += (cutoffTarget - earCutoff) * k
    bus.earGain.value = Float(earGain)
    bus.earCutoff.value = Float(earCutoff)
  }
  func reset() {
    for p in playing {
      if let i = p.slot {
        freeSlot(i)
      } else {
        p.controller?.stop()
        p.entity.removeFromParent()
      }
    }
    playing = []
    pending = []
    for voice in threats.values { freeSlot(voice.slot) }
    threats = [:]
    for r in released { freeSlot(r.slot) }
    released = []
    muffle = nil
    gunDucks = []
    // A restart brings a new scheduler, whose clock starts again from zero
    lastShot = -.infinity
    lastFlak = -.infinity
    lastNow = 0
    (nextSwell, nextGust, nextSlap) = (0, 0, 2)
  }
  func stop() {
    stopped = true
    bus.paused.value = true
    for g in generators { g.stop() }
    generators = []
    reset()
    for slot in slots { slot.entity.removeFromParent() }
    slots = []
  }
}

/// The generator's render block, made outside the main actor: RealityKit calls it on its audio
/// thread. Mono; any further channels get copies.
private func renderer(_ synth: SoundSynth) -> Audio.GeneratorRenderHandler {
  { _, _, frameCount, data in
    let buffers = UnsafeMutableAudioBufferListPointer(data)
    let frames = Int(frameCount)
    guard let first = buffers.first?.mData?.assumingMemoryBound(to: Float.self) else { return noErr }
    synth.render(first, frames: frames)
    for buffer in buffers.dropFirst() {
      buffer.mData?.copyMemory(from: first, byteCount: frames * MemoryLayout<Float>.size)
    }
    return noErr
  }
}
