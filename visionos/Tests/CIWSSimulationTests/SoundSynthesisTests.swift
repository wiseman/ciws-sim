import XCTest

@testable import CIWSSimulation
@testable import CIWSSound

final class SoundSynthesisTests: XCTestCase {
  let rate = 48000.0

  func render(_ synth: SoundSynth, seconds: Double, block: Int = 512) -> [Float] {
    var out = [Float](repeating: 0, count: Int(seconds * rate))
    out.withUnsafeMutableBufferPointer { b in
      var i = 0
      while i < b.count {
        let n = min(block, b.count - i)
        synth.render(b.baseAddress! + i, frames: n)
        i += n
      }
    }
    return out
  }
  func playingBus() -> SoundBus {
    let bus = SoundBus()
    bus.paused.value = false
    return bus
  }
  /// Goertzel power at `hz`
  func power(_ x: ArraySlice<Float>, at hz: Double) -> Double {
    let k = 2 * cos(2 * .pi * hz / rate)
    var s1 = 0.0, s2 = 0.0
    for v in x {
      let s = Double(v) + k * s1 - s2
      s2 = s1
      s1 = s
    }
    return (s1 * s1 + s2 * s2 - k * s1 * s2) / Double(x.count * x.count)
  }
  func impulse(length: Int = 100) -> SampleBuffer {
    let b = SampleBuffer(count: length, sampleRate: rate)
    b.samples[0] = 1
    b.samples[1] = 1
    return b
  }

  func testRulesMatchTheWebFormulas() {
    XCTAssertEqual(SoundRules.distanceGain(30, reference: 40), 1)
    XCTAssertEqual(SoundRules.distanceGain(100, reference: 40), 40 / 130, accuracy: 1e-12)
    XCTAssertEqual(SoundRules.airCutoff(0), 18000)
    XCTAssertEqual(SoundRules.airCutoff(5000), 350)
    XCTAssertEqual(SoundRules.slowPitch(0.1), 0.505, accuracy: 1e-12)
    XCTAssertEqual(SoundRules.doppler(closingSpeed: 0), 1)
    XCTAssertEqual(SoundRules.doppler(closingSpeed: -100), 343.0 / 603, accuracy: 1e-12)
    XCTAssertEqual(SoundRules.doppler(closingSpeed: 100), 2.4)  // clamped
    XCTAssertEqual(SoundRules.gunFatigue(5), 1)
    XCTAssertEqual(SoundRules.gunFatigue(65), 0.65, accuracy: 1e-12)
    XCTAssertEqual(SoundRules.gunFatigue(500), 0.3, accuracy: 1e-12)
    XCTAssertEqual(SoundRules.gunFatigue(65, floor: 0.5), 0.75, accuracy: 1e-12)
    XCTAssertEqual(GunSynth.shotSpacing(sinceTrigger: 0, interval: 0.1, jitter: 0), 0.16, accuracy: 1e-12)
    XCTAssertEqual(GunSynth.shotSpacing(sinceTrigger: 1, interval: 0.1, jitter: 0.5), 0.1004, accuracy: 1e-12)
    // playAt: a centred send of 0.35 at 100 m, reference 40
    let g = SoundRules.distanceGain(100, reference: 40)
    XCTAssertEqual(
      SoundRules.reverbRatio(wet: 0.35, distance: 100, distanceGain: g),
      0.35 * 2.squareRoot() * 1.4 * pow(g, 0.6) * 0.55 / g, accuracy: 1e-12)
  }

  func testOpenWaterMatchesTheWebFootprints() {
    let s = Simulation(seed: 3, holiday: nil, createFleet: true)
    XCTAssertFalse(s.isOverOpenWater([0, 0, 10]))  // our hull
    XCTAssertFalse(s.isOverOpenWater([9.5, 0, 10]))  // within the 1.5 margin
    XCTAssertTrue(s.isOverOpenWater([300, 0, 0]) || s.friendlies.contains { ($0.position - [300, 0, 0]).length < 30 })
    XCTAssertFalse(s.isOverOpenWater([300, 5, 0]))  // too high to splash
    let f = s.friendlies[0]
    XCTAssertFalse(s.isOverOpenWater(f.position + Vector3(0, 0, 20).rotatedY(f.heading)))
    XCTAssertTrue(s.isOverOpenWater(f.position + Vector3(0, 0, 26).rotatedY(f.heading)))
  }

  func testPausedBusIsSilent() {
    let bus = SoundBus()
    let synth = EngineSynth(level: 1, sampleRate: rate, bus: bus)
    XCTAssertEqual(render(synth, seconds: 0.1).map(abs).max(), 0)
  }

  func testOneShotPlaysOnceAtItsRate() {
    let buffer = SampleBuffer(count: 4800, sampleRate: rate)
    for i in 0..<4800 { buffer.samples[i] = 0.5 }
    let shot = OneShotSynth(buffer: buffer, rate: 2, gain: 1, sampleRate: rate, bus: playingBus())
    XCTAssertEqual(shot.duration, 0.05, accuracy: 1e-9)
    let out = render(shot, seconds: 0.1)
    XCTAssertEqual(out[1000], 0.5, accuracy: 1e-3)
    XCTAssertEqual(out[2399], 0.5, accuracy: 1e-3)
    XCTAssertEqual(out[2500], 0, accuracy: 1e-6)
  }

  func testGunSpinsUpToItsRateAndStops() {
    let gun = GunSynth(shots: [impulse()], seed: 7, sampleRate: rate, bus: playingBus())
    gun.level.value = 1
    gun.held.value = true
    let firing = render(gun, seconds: 1)
    gun.held.value = false
    let after = render(gun, seconds: 0.5)
    // Rounds start where the slapback-free signal jumps from silence
    let raw = firing.indices.dropFirst().filter { abs(firing[$0]) > 0.3 && abs(firing[$0 - 1]) < 0.05 }
    var expected = 0, t = 0.02
    while t < 1 {
      expected += 1
      t += GunSynth.shotSpacing(sinceTrigger: t - 0.0, interval: 1.0 / 60, jitter: 0)
    }
    XCTAssertEqual(raw.count, expected, accuracy: 2)
    let first = Double(raw[0]) / rate, second = Double(raw[1]) / rate
    XCTAssertEqual(first, 0.02, accuracy: 0.001)
    XCTAssertEqual(second - first, 1.6 / 60, accuracy: 0.001)  // still spinning up
    XCTAssertEqual(after.suffix(12000).map(abs).max() ?? 1, 0, accuracy: 1e-4)
  }

  func testThreatPitchFollowsDoppler() {
    for shift in [1.0, 1.5] {
      let shell = ThreatSynth(kind: .mortar, seed: 9, sampleRate: rate, bus: playingBus())
      shell.level.value = 0.35
      shell.distanceGain.value = 1
      shell.air.value = 20000
      shell.frequency.value = Float(shift)
      let out = render(shell, seconds: 1)[24000...]
      let hz = Double(shell.base) * shift
      XCTAssertGreaterThan(power(out, at: hz), 50 * power(out, at: hz * 1.12), "shift \(shift)")
    }
  }

  func testReleasedThreatFadesOut() {
    let drone = ThreatSynth(kind: .drone, seed: 4, sampleRate: rate, bus: playingBus())
    drone.level.value = 0.45
    drone.distanceGain.value = 1
    XCTAssertGreaterThan(render(drone, seconds: 0.5).map(abs).max()!, 0.05)
    drone.released.value = true
    XCTAssertLessThan(render(drone, seconds: 0.4).suffix(4800).map(abs).max()!, 1e-3)
  }

  func testEverySynthStaysFiniteAndBounded() {
    let bus = playingBus()
    let noise = makeNoiseLoop(seconds: 3, color: .white, seed: 1, sampleRate: rate)
    let mount = MountSynth(noise: noise, seed: 1, sampleRate: rate, bus: bus)
    mount.barrelSpeed.value = 1
    mount.slew.value = 0.1
    let wind = NoiseBedSynth(
      sea: false, loop: makeNoiseLoop(seconds: 7, color: .pink, seed: 2, sampleRate: rate), seed: 2,
      sampleRate: rate, bus: bus)
    wind.level.value = 0.075
    wind.center.value = 950
    let sea = NoiseBedSynth(
      sea: true, loop: makeNoiseLoop(seconds: 9, color: .brown, seed: 3, sampleRate: rate), seed: 3,
      sampleRate: rate, bus: bus)
    sea.level.value = 0.075
    var synths: [SoundSynth] = [mount, wind, sea, RingSynth(hz: 3900, level: 0.03, sampleRate: rate, bus: bus)]
    for kind in [ThreatSynth.Kind.ascm, .mortar, .drone] {
      let t = ThreatSynth(kind: kind, seed: 5, sampleRate: rate, bus: bus)
      t.level.value = 1
      t.distanceGain.value = 1
      t.frequency.value = 2.4
      t.band.value = 2.4
      t.rush.value = 0.3
      synths.append(t)
    }
    bus.earCutoff.value = 450
    bus.earGain.value = 0.5
    for synth in synths {
      let out = render(synth, seconds: 1, block: 333)
      XCTAssertTrue(out.allSatisfy { $0.isFinite && abs($0) <= 1 }, "\(type(of: synth))")
      XCTAssertGreaterThan(out.map(abs).max()!, 1e-4, "\(type(of: synth)) is silent")
    }
  }

  func testNoiseLoopsAreNormalized() {
    for color in [NoiseColor.white, .brown, .pink] {
      let loop = makeNoiseLoop(seconds: 2, color: color, seed: 8, sampleRate: rate)
      XCTAssertEqual(loop.samples.count, Int(1.95 * rate))
      XCTAssertEqual(Double(loop.samples.map(abs).max()!), 0.9, accuracy: 1e-6)
    }
  }

  func testSlotPlaysWhatItIsHanded() {
    let bus = playingBus()
    let slot = SourceSlot(sampleRate: rate, bus: bus)
    XCTAssertEqual(render(slot, seconds: 0.05).map(abs).max(), 0)
    let buffer = SampleBuffer(count: 4800, sampleRate: rate)
    for i in 0..<4800 { buffer.samples[i] = 1 }
    // The sound's own knee applies once: 1.6 bends to 0.8 + 0.2·tanh(4)
    slot.play(OneShotSynth(buffer: buffer, rate: 1, gain: 1.6, sampleRate: rate, bus: bus))
    let out = render(slot, seconds: 0.05)
    XCTAssertEqual(out[1000], Float(0.8 + 0.2 * tanh(4.0)), accuracy: 1e-3)
    slot.play(nil)
    XCTAssertEqual(render(slot, seconds: 0.05).map(abs).max(), 0)
  }

  func testBlastBodyLiftsTheBoomIntoTheSpeakersRange() throws {
    let folder = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
      .appendingPathComponent("../../Resources/Sounds/")
    let bank = try SoundBank(
      index: Data(contentsOf: folder.appendingPathComponent("web-sounds.json")),
      pcm: Data(contentsOf: folder.appendingPathComponent("web-sounds.bin")))
    // Energy from 150 Hz to 2 kHz in the boom after the crack, where the headset's speakers play
    func body(_ b: SampleBuffer) -> Double {
      let x = Array(b.samples[2400..<28800])
      return [200.0, 300, 450, 700, 1000].reduce(0) { $0 + power(x[...], at: $1) }
    }
    for (name, style, mix) in [("big", BlastBody.big, Float(1)), ("thump", .thump, 0.8)] {
      let web = bank.sounds[name]![0]
      let voiced = style.added(to: web, mix: mix, seed: 1)
      XCTAssertEqual(voiced.samples.count, web.samples.count)
      XCTAssertGreaterThan(body(voiced), 5 * body(web), name)  // 7 dB or more
      XCTAssertEqual(voiced.samples[100], style.added(to: web, mix: mix, seed: 1).samples[100])
      for seed in UInt64(1)...8 {
        let varied = style.varied(seed: seed)
        XCTAssertGreaterThan(body(varied.added(to: web, mix: mix, seed: seed)), 3 * body(web), name)
      }
    }
  }

  func testBlastBodiesVaryALittle() {
    let bodies = (UInt64(21)..<41).map { BlastBody.big.varied(seed: $0) }
    for b in bodies {
      for (part, spread) in [(b.whump, 1.4), (b.roar, 1.6), (b.rumble, 1.6), (b.length, 1.25), (b.tone, 1.2)] {
        XCTAssertLessThanOrEqual(abs(log(Double(part))), log(spread) + 1e-6)
      }
    }
    // Spread over the range, not stuck near the preset
    XCTAssertGreaterThan(bodies.map(\.roar).max()! / bodies.map(\.roar).min()!, 1.6)
    XCTAssertEqual(Set(bodies.map(\.length)).count, bodies.count)
    XCTAssertEqual(BlastBody.big.varied(seed: 5).tone, BlastBody.big.varied(seed: 5).tone)
  }

  /// The bundled export: every sound the native app plays, with the web's variant counts
  func testExportedWebSounds() throws {
    let folder = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
      .appendingPathComponent("../../Resources/Sounds/")
    let bank = try SoundBank(
      index: Data(contentsOf: folder.appendingPathComponent("web-sounds.json")),
      pcm: Data(contentsOf: folder.appendingPathComponent("web-sounds.bin")))
    let counts = [
      "shot": 6, "big": 3, "thump": 2, "hit": 4, "pop": 4, "splash": 3, "slap": 3, "vlsRoar": 2,
      "chirp": 6, "rotor": 1, "bells": 1,
    ]
    XCTAssertEqual(bank.sounds.mapValues(\.count), counts)
    XCTAssertEqual(bank.sounds["big"]![0].duration, 4.5, accuracy: 1e-3)
    for (name, variants) in bank.sounds {
      for v in variants {
        let peak = v.samples.map(abs).max()!
        XCTAssertGreaterThan(peak, 0.3, name)
        XCTAssertLessThanOrEqual(peak, 1, name)
      }
    }
  }
}
