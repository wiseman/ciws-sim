import Foundation
import Synchronization

// The web game's audio graph (AudioController in index.html) as per-sample synths that render on
// RealityKit's audio thread. This target is compiled optimized even in Debug builds (Package.swift):
// unoptimized, a raid's worth of synths overruns the audio deadline.

// MARK: - Shared state

/// A value the main thread sets and the audio thread reads
public final class SharedFloat: Sendable {
  private let bits: Atomic<UInt32>
  public init(_ value: Float) { bits = Atomic(value.bitPattern) }
  public var value: Float {
    get { Float(bitPattern: bits.load(ordering: .relaxed)) }
    set { bits.store(newValue.bitPattern, ordering: .relaxed) }
  }
}

public final class SharedFlag: Sendable {
  private let bits: Atomic<Bool>
  public init(_ value: Bool) { bits = Atomic(value) }
  public var value: Bool {
    get { bits.load(ordering: .relaxed) }
    set { bits.store(newValue, ordering: .relaxed) }
  }
}

/// What the web's mix bus and ear stage do to every battle sound: the duck under voices, and a
/// close blast's muffle (earFilter, earGain). paused holds every synth where it is.
public final class SoundBus: Sendable {
  public let duck = SharedFloat(1), earGain = SharedFloat(1), earCutoff = SharedFloat(20000)
  public let paused = SharedFlag(true)
  public init() {}
}

/// Mono PCM owned for the app's lifetime, so the audio thread reads it without retaining anything
public final class SampleBuffer: @unchecked Sendable {
  public let samples: UnsafeMutableBufferPointer<Float>
  public let sampleRate: Double
  public var duration: Double { Double(samples.count) / sampleRate }
  public init(count: Int, sampleRate: Double) {
    samples = .allocate(capacity: count)
    samples.initialize(repeating: 0)
    self.sampleRate = sampleRate
  }
  deinit { samples.deallocate() }
}

/// The web's synthesized buffers, rendered by tools/export_audio.mjs
public final class SoundBank: Sendable {
  struct Index: Decodable {
    let format: Int
    let sampleRate: Double
    let sounds: [String: [[Int]]]
  }
  public let sounds: [String: [SampleBuffer]]
  public init(index: Data, pcm: Data) throws {
    let document = try JSONDecoder().decode(Index.self, from: index)
    sounds = document.sounds.mapValues { ranges in
      ranges.map { range in
        let buffer = SampleBuffer(count: range[1], sampleRate: document.sampleRate)
        pcm.withUnsafeBytes { bytes in
          for i in 0..<range[1] {
            let value = bytes.loadUnaligned(fromByteOffset: (range[0] + i) * 2, as: Int16.self)
            buffer.samples[i] = Float(Int16(littleEndian: value)) / 32767
          }
        }
        return buffer
      }
    }
  }
  public init(sounds: [String: [SampleBuffer]]) { self.sounds = sounds }
}

// MARK: - DSP

struct SoundRandom {
  var state: UInt64
  init(seed: UInt64) { state = seed | 1 }
  /// 0..<1
  mutating func next() -> Float {
    state ^= state << 13
    state ^= state >> 7
    state ^= state << 17
    return Float(state >> 40) / Float(1 << 24)
  }
  mutating func signed() -> Float { next() * 2 - 1 }
  mutating func range(_ a: Float, _ b: Float) -> Float { a + (b - a) * next() }
}

/// RBJ biquad as Web Audio's BiquadFilterNode computes it
struct Biquad {
  enum Kind { case lowpass, highpass, bandpass }
  /// Web Audio's lowpass/highpass Q is in dB; its default of 1 is this linear Q
  static let webQ: Float = 1.1220185
  let kind: Kind, q: Float
  private var b0: Float = 1, b1: Float = 0, b2: Float = 0, a1: Float = 0, a2: Float = 0
  private var x1: Float = 0, x2: Float = 0, y1: Float = 0, y2: Float = 0
  private var frequency: Float = -1
  init(_ kind: Kind, q: Float = webQ) {
    self.kind = kind
    self.q = q
  }
  mutating func set(_ hz: Float, sampleRate: Float) {
    let f = min(hz, sampleRate * 0.49)
    guard f != frequency else { return }
    frequency = f
    let w = 2 * Float.pi * f / sampleRate
    let cosine = cos(w), alpha = sin(w) / (2 * q)
    let a0 = 1 + alpha
    switch kind {
    case .lowpass:
      b0 = (1 - cosine) / 2
      b1 = 1 - cosine
      b2 = b0
    case .highpass:
      b0 = (1 + cosine) / 2
      b1 = -(1 + cosine)
      b2 = b0
    case .bandpass:  // constant 0 dB peak gain
      b0 = alpha
      b1 = 0
      b2 = -alpha
    }
    b0 /= a0
    b1 /= a0
    b2 /= a0
    a1 = -2 * cosine / a0
    a2 = (1 - alpha) / a0
  }
  @inline(__always) mutating func process(_ x: Float) -> Float {
    let y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
    x2 = x1
    x1 = x
    y2 = y1
    y1 = y
    return y
  }
}

/// Band-limited (PolyBLEP) oscillator standing in for Web Audio's OscillatorNode
struct Oscillator {
  enum Shape { case sine, sawtooth, triangle, square }
  let shape: Shape
  var phase: Float = 0
  init(_ shape: Shape) { self.shape = shape }
  @inline(__always) private static func blep(_ t: Float, _ dt: Float) -> Float {
    if t < dt {
      let x = t / dt
      return x + x - x * x - 1
    }
    if t > 1 - dt {
      let x = (t - 1) / dt
      return x * x + x + x + 1
    }
    return 0
  }
  /// dt: frequency / sample rate
  @inline(__always) mutating func next(_ dt: Float) -> Float {
    let t = phase
    phase += dt
    phase -= phase.rounded(.down)
    switch shape {
    case .sine: return sin(2 * .pi * t)
    case .sawtooth: return 2 * t - 1 - Self.blep(t, dt)
    case .triangle: return 1 - 4 * abs(t - 0.5)
    case .square:
      let u = t + 0.5
      return (t < 0.5 ? 1 : -1) + Self.blep(t, dt) - Self.blep(u - u.rounded(.down), dt)
    }
  }
}

/// AudioParam.setTargetAtTime, applied once per render block and ramped across it
struct Smooth {
  var value: Float
  init(_ value: Float) { self.value = value }
  /// The block's start value and per-sample step toward `target` with time constant `tc` s
  mutating func ramp(_ target: Float, _ tc: Float, frames: Int, sampleRate: Float) -> (Float, Float) {
    let start = value
    let k = tc > 0 ? 1 - exp(-Float(frames) / (tc * sampleRate)) : 1
    value += (target - value) * k
    return (start, (value - start) / Float(max(frames, 1)))
  }
}

/// makeLoopBuffer: a seamlessly looping noise buffer, its first 50 ms crossfaded with the end
public enum NoiseColor { case white, brown, pink }
public func makeNoiseLoop(seconds: Double, color: NoiseColor, seed: UInt64, sampleRate: Double)
  -> SampleBuffer
{
  var random = SoundRandom(seed: seed)
  let count = Int(seconds * sampleRate), fade = Int(sampleRate * 0.05)
  let raw = SampleBuffer(count: count, sampleRate: sampleRate)
  let d = raw.samples
  var y: Float = 0
  var b: [Float] = Array(repeating: 0, count: 7)
  for i in 0..<count {
    let w = random.signed()
    switch color {
    case .white: d[i] = w
    case .brown:
      y = (y + w * 0.02) * 0.998
      d[i] = y
    case .pink:
      b[0] = 0.99886 * b[0] + w * 0.0555179
      b[1] = 0.99332 * b[1] + w * 0.0750759
      b[2] = 0.969 * b[2] + w * 0.153852
      b[3] = 0.8665 * b[3] + w * 0.3104856
      b[4] = 0.55 * b[4] + w * 0.5329522
      b[5] = -0.7616 * b[5] - w * 0.016898
      d[i] = (b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + w * 0.5362) * 0.11
      b[6] = w * 0.115926
    }
  }
  for i in 0..<fade {
    let k = Float(i) / Float(fade)
    d[i] = d[i] * k + d[count - fade + i] * (1 - k)
  }
  // loopEnd stops 50 ms early, where the crossfaded start takes over
  let loop = SampleBuffer(count: count - fade, sampleRate: sampleRate)
  let peak = d.prefix(count - fade).reduce(Float(0)) { max($0, abs($1)) }
  for i in 0..<loop.samples.count { loop.samples[i] = d[i] * (peak > 0 ? 0.9 / peak : 0) }
  return loop
}

/// A blast's body for small speakers (BLAST_BODY, addBlastBody). The web's big explosion has 85% of
/// its energy under 120 Hz and the thump nearly all of it: a boom for headphones and subwoofers
/// that the headset's speakers barely play. The body sits an octave or two up: a falling whump
/// (noise under a closing filter, not a tone: the boom's sweep moved up into hearing would sound
/// pitched), a fireball roar and a rolling debris rumble.
public struct BlastBody: Sendable {
  public var whump: Float, roar: Float, rumble: Float
  /// Scales how long each part lasts, and the body's filter frequencies
  public var length: Float = 1, tone: Float = 1
  public static let big = BlastBody(whump: 1, roar: 1, rumble: 1)
  public static let thump = BlastBody(whump: 1, roar: 0.4, rumble: 0.2)

  /// This body with each part's level, its length and its tone moved a little, so no two blasts
  /// in the bank sound alike
  public func varied(seed: UInt64) -> BlastBody {
    var random = SoundRandom(seed: seed &* 0x9E37_79B9_7F4A_7C15)
    func by(_ spread: Float) -> Float { pow(spread, random.signed()) }
    return BlastBody(
      whump: whump * by(1.4), roar: roar * by(1.6), rumble: rumble * by(1.6),
      length: length * by(1.25), tone: tone * by(1.2))
  }

  /// `buffer` with the body mixed in at `mix`; peaks may pass 1, for the playback gain and knee
  public func added(to buffer: SampleBuffer, mix: Float, seed: UInt64) -> SampleBuffer {
    let rate = Float(buffer.sampleRate), x = buffer.samples
    let out = SampleBuffer(count: x.count, sampleRate: buffer.sampleRate)
    var random = SoundRandom(seed: seed)
    let butterworth: Float = 0.70710677
    var roarLow = Biquad(.highpass, q: butterworth), roarHigh = Biquad(.lowpass, q: butterworth)
    var rumbleLow = Biquad(.highpass, q: butterworth), rumbleHigh = Biquad(.lowpass, q: butterworth)
    var whumpLow = Biquad(.highpass, q: butterworth), whumpHigh = Biquad(.lowpass, q: 0.9)
    whumpLow.set(90 * tone, sampleRate: rate)
    roarLow.set(300 * tone, sampleRate: rate)
    roarHigh.set(1100 * tone, sampleRate: rate)
    rumbleLow.set(120 * tone, sampleRate: rate)
    rumbleHigh.set(320 * tone, sampleRate: rate)
    // Slow random swells (DSP.wander): straight lines between random points `rate` times a second
    var flicker = (from: random.next(), to: random.next(), at: Float(0))
    var roll = (from: random.next(), to: random.next(), at: Float(0))
    let fade = Float(rate * 0.1)  // the rumble can outlast a short buffer
    for i in 0..<x.count {
      let t = Float(i) / rate
      flicker.at += 9 / rate
      if flicker.at >= 1 { flicker = (flicker.to, random.next(), flicker.at - 1) }
      roll.at += 4 / rate
      if roll.at >= 1 { roll = (roll.to, random.next(), roll.at - 1) }
      whumpHigh.set((150 + 550 * exp(-t / (0.1 * length))) * tone, sampleRate: rate)
      let w =
        whumpLow.process(whumpHigh.process(random.signed())) * 9.7 * min(1, t / 0.006)
        * exp(-t / (0.28 * length))
      let r =
        roarHigh.process(roarLow.process(random.signed())) * 3 * min(1, t / 0.015)
        * exp(-t / (0.45 * length))
        * (0.6 + 0.4 * (flicker.from + (flicker.to - flicker.from) * flicker.at))
      let b =
        rumbleHigh.process(rumbleLow.process(random.signed())) * 3.5 * min(1, t / 0.06)
        * exp(-t / (1.2 * length)) * (0.35 + 0.65 * (roll.from + (roll.to - roll.from) * roll.at))
      let end = min(1, Float(x.count - i) / fade)
      out.samples[i] = x[i] + mix * (whump * w + roar * r + rumble * b) * end
    }
    return out
  }
}

/// Plays a noise loop from a random point
struct LoopPlayer {
  let buffer: SampleBuffer
  var index: Int
  init(_ buffer: SampleBuffer, random: inout SoundRandom) {
    self.buffer = buffer
    index = Int(random.next() * Float(buffer.samples.count - 1))
  }
  @inline(__always) mutating func next() -> Float {
    let x = buffer.samples[index]
    index += 1
    if index == buffer.samples.count { index = 0 }
    return x
  }
}

// MARK: - Synths

/// One sound source's audio-thread rendering. Subclasses fill a block; the base applies the
/// battle duck and the ear stage, then the web master's soft knee.
public class SoundSynth: @unchecked Sendable {
  public let sampleRate: Float
  let bus: SoundBus
  /// false for the ringing in the ears, which skips the duck and the muffle it comes with
  let throughEar: Bool
  /// false for a SourceSlot, whose sound has already been through the knee
  let limited: Bool
  private var earFilter = Biquad(.lowpass)
  private var earLevel = Smooth(1), earHz = Smooth(20000)
  init(sampleRate: Double, bus: SoundBus, throughEar: Bool = true, limited: Bool = true) {
    self.sampleRate = Float(sampleRate)
    self.bus = bus
    self.throughEar = throughEar
    self.limited = limited
  }
  public final func render(_ out: UnsafeMutablePointer<Float>, frames: Int) {
    guard !bus.paused.value else {
      out.update(repeating: 0, count: frames)
      return
    }
    synthesize(out, frames)
    if throughEar {
      var (level, step) = earLevel.ramp(
        bus.earGain.value * bus.duck.value, 0.01, frames: frames, sampleRate: sampleRate)
      _ = earHz.ramp(bus.earCutoff.value, 0.01, frames: frames, sampleRate: sampleRate)
      earFilter.set(earHz.value, sampleRate: sampleRate)
      for i in 0..<frames {
        out[i] = earFilter.process(out[i]) * level
        level += step
      }
    }
    guard limited else { return }
    // DSP.safetyCurve(0.8): unity to the knee, then a smooth bend that never passes ±1
    for i in 0..<frames {
      let x = out[i], a = abs(x)
      if a > 0.8 { out[i] = (x < 0 ? -1 : 1) * (0.8 + 0.2 * tanh((a - 0.8) / 0.2)) }
    }
  }
  func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    out.update(repeating: 0, count: frames)
  }
}

/// playAt / playBuffer: one buffer once, at a playback rate, through the air-absorption filter
public final class OneShotSynth: SoundSynth, @unchecked Sendable {
  private let buffer: SampleBuffer
  private let step: Double, gain: Float, cutoff: Float
  private var air = Biquad(.lowpass)
  private var position = 0.0
  /// Seconds it plays for at its rate
  public var duration: Double { buffer.duration / (step * Double(sampleRate) / buffer.sampleRate) }
  public init(
    buffer: SampleBuffer, rate: Double, gain: Double, cutoff: Double = 20000,
    sampleRate: Double, bus: SoundBus
  ) {
    self.buffer = buffer
    step = rate * buffer.sampleRate / sampleRate
    self.gain = Float(gain)
    self.cutoff = Float(cutoff)
    super.init(sampleRate: sampleRate, bus: bus)
    air.set(self.cutoff, sampleRate: self.sampleRate)
  }
  override func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    let s = buffer.samples, last = s.count - 1
    for i in 0..<frames {
      var x: Float = 0
      if position < Double(last) {
        let j = Int(position), k = Float(position - Double(j))
        x = s[j] + (s[j + 1] - s[j]) * k
        position += step
      }
      out[i] = (cutoff < 19000 ? air.process(x) : x) * gain
    }
  }
}

/// A long-lived source that plays whichever synth it was last handed. The headset stops starting
/// new RealityKit audio generators after some hundreds, so short sounds take turns on a pool of
/// these rather than each getting a generator of its own.
public final class SourceSlot: SoundSynth, @unchecked Sendable {
  private let current = Mutex<SoundSynth?>(nil)
  public init(sampleRate: Double, bus: SoundBus) {
    super.init(sampleRate: sampleRate, bus: bus, throughEar: false, limited: false)
  }
  public func play(_ synth: SoundSynth?) { current.withLock { $0 = synth } }
  override func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    // Never wait on the main thread; a handover in progress costs a silent block
    if let synth = current.withLockIfAvailable({ $0 }) ?? nil {
      synth.render(out, frames: frames)
    } else {
      out.update(repeating: 0, count: frames)
    }
  }
}

/// The ringing in the ears after a close blast (BLAST_FEEL.ring): a sine that rises over 50 ms,
/// holds 0.3 s, and fades over ringFade
public final class RingSynth: SoundSynth, @unchecked Sendable {
  private var tone = Oscillator(.sine)
  private let hz: Float, level: Float
  private var t: Float = 0
  public static let fade = 2.5
  public init(hz: Double, level: Double, sampleRate: Double, bus: SoundBus) {
    self.hz = Float(hz)
    self.level = Float(level)
    super.init(sampleRate: sampleRate, bus: bus, throughEar: false)
  }
  override func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    let dt = 1 / sampleRate, tail = Float(Self.fade) / 3
    let peak = level * (1 - exp(-0.3 / 0.05))
    for i in 0..<frames {
      let env = t < 0.3 ? level * (1 - exp(-t / 0.05)) : peak * exp(-(t - 0.3) / tail)
      out[i] = tone.next(hz * dt) * env
      t += dt
    }
  }
}

/// The 20 mm gun: each round's sound, timed to the sample with the barrels' spin-up, fused by a
/// soft clip into the roar, with slapback off the deck and superstructure (buildGun, scheduleGun)
public final class GunSynth: SoundSynth, @unchecked Sendable {
  /// A round went out within the last couple of intervals (noteShot)
  public let held = SharedFlag(false)
  public let interval = SharedFloat(1.0 / 60)  // seconds between rounds at full rate
  public let pitch = SharedFloat(1)
  public let level = SharedFloat(0.32)  // gunBus, under GUN_FATIGUE
  private struct Shot {
    var buffer: Int
    var position: Double
    var step: Double
    var gain: Float
  }
  private let shots: [SampleBuffer]
  private var active: [Shot] = []
  private var random: SoundRandom
  private var clock = 0.0, nextShot = 0.0, heldSince = -1.0
  private var delay: [Float] = Array(repeating: 0, count: 4096)
  private var write = 0
  private var slapA = Biquad(.lowpass), slapB = Biquad(.lowpass)
  private var gain = Smooth(0.32)
  private static let norm = tanh(Float(2.2))
  /// Gap to the next round: the gun takes a moment to reach full rate as the barrels spin up.
  /// jitter is uniform in -0.5..0.5.
  public static func shotSpacing(sinceTrigger: Double, interval: Double, jitter: Double) -> Double {
    interval * (1.6 - 0.6 * min(1, sinceTrigger / 0.25)) + jitter * 0.0008
  }
  public init(shots: [SampleBuffer], seed: UInt64, sampleRate: Double, bus: SoundBus) {
    self.shots = shots
    random = SoundRandom(seed: seed)
    active.reserveCapacity(64)
    super.init(sampleRate: sampleRate, bus: bus)
    slapA.set(3500, sampleRate: self.sampleRate)
    slapB.set(3500, sampleRate: self.sampleRate)
  }
  override func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    let sr = Double(sampleRate), isHeld = held.value, gap = Double(interval.value)
    let rate = Double(pitch.value)
    if !isHeld {
      heldSince = -1
    } else if heldSince < 0 {
      heldSince = clock
      nextShot = max(nextShot, clock + 0.02)
    }
    var (g, gStep) = gain.ramp(level.value, 0.05, frames: frames, sampleRate: sampleRate)
    let tapA = Int(0.013 * sr), tapB = Int(0.021 * sr), mask = delay.count - 1
    for i in 0..<frames {
      let t = clock + Double(i) / sr
      while isHeld && nextShot <= t && active.count < 64 {
        let b = Int(random.next() * Float(shots.count)) % shots.count
        let r = Double(random.range(0.97, 1.03)) * rate
        active.append(
          Shot(
            buffer: b, position: 0, step: r * shots[b].sampleRate / sr,
            gain: random.range(0.75, 1)))
        nextShot += Self.shotSpacing(
          sinceTrigger: nextShot - heldSince, interval: gap, jitter: Double(random.signed() / 2))
      }
      var sum: Float = 0
      var n = 0
      while n < active.count {
        let s = shots[active[n].buffer].samples
        let p = active[n].position
        let j = Int(p)
        if j >= s.count - 1 {
          active.swapAt(n, active.count - 1)
          active.removeLast()
          continue
        }
        let k = Float(p - Double(j))
        sum += (s[j] + (s[j + 1] - s[j]) * k) * active[n].gain
        active[n].position += active[n].step
        n += 1
      }
      let x = max(-1, min(1, sum * g))
      let shaped = tanh(x * 2.2) / Self.norm
      delay[write & mask] = shaped
      let slap =
        slapA.process(delay[(write - tapA) & mask]) * 0.22
        + slapB.process(delay[(write - tapB) & mask]) * 0.2
      write &+= 1
      out[i] = shaped + slap
      g += gStep
    }
    clock += Double(frames) / sr
  }
}

/// The mount's machinery (buildMount): the barrel drive's whine following the spin, the traverse
/// servos' whine sliding with the slew rate over a gearbox grind, and the idle hum
public final class MountSynth: SoundSynth, @unchecked Sendable {
  public let barrelSpeed = SharedFloat(0), slew = SharedFloat(0), pitch = SharedFloat(1)
  private var drive = [Oscillator(.sawtooth), Oscillator(.triangle), Oscillator(.sine)]
  private let driveMix: [Float] = [0.5, 0.35, 0.2], driveMults: [Float] = [1, 2.01, 3.98]
  private var driveFilter = Biquad(.bandpass, q: 0.6)
  private var servo = Oscillator(.sawtooth)
  private var servoFilter = Biquad(.bandpass, q: 3), grindFilter = Biquad(.bandpass, q: 1.2)
  private var hum = [Oscillator(.sine), Oscillator(.sine), Oscillator(.triangle)]
  private var grind: LoopPlayer
  private var driveHz = Smooth(160), driveGain = Smooth(0), servoHz = Smooth(240),
    servoGain = Smooth(0), grindGain = Smooth(0)
  public init(noise: SampleBuffer, seed: UInt64, sampleRate: Double, bus: SoundBus) {
    var random = SoundRandom(seed: seed)
    grind = LoopPlayer(noise, random: &random)
    super.init(sampleRate: sampleRate, bus: bus)
    driveFilter.set(1400, sampleRate: self.sampleRate)
    grindFilter.set(190, sampleRate: self.sampleRate)
  }
  override func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    let sr = sampleRate, spin = barrelSpeed.value, p = pitch.value
    let s = min(1, slew.value * 20)
    var (dHz, dHzStep) = driveHz.ramp((160 + spin * 620) * p, 0.08, frames: frames, sampleRate: sr)
    var (dG, dGStep) = driveGain.ramp(spin * 0.16, 0.08, frames: frames, sampleRate: sr)
    var (sHz, sHzStep) = servoHz.ramp((240 + s * 900) * p, 0.06, frames: frames, sampleRate: sr)
    var (sG, sGStep) = servoGain.ramp(s * 0.12, 0.05, frames: frames, sampleRate: sr)
    var (gG, gGStep) = grindGain.ramp(s * 0.22, 0.05, frames: frames, sampleRate: sr)
    servoFilter.set(servoHz.value * 1.6, sampleRate: sr)
    for i in 0..<frames {
      var d: Float = 0
      for k in 0..<3 { d += drive[k].next(dHz * driveMults[k] / sr) * driveMix[k] }
      let whine = servoFilter.process(servo.next(sHz / sr))
      let gears = grindFilter.process(grind.next())
      let idle =
        hum[0].next(400 / sr) + 0.35 * hum[1].next(800 / sr) + 0.6 * hum[2].next(118 / sr)
      out[i] = driveFilter.process(d) * dG + whine * sG + gears * gG + idle * 0.004
      dHz += dHzStep
      dG += dGStep
      sHz += sHzStep
      sG += sGStep
      gG += gGStep
    }
  }
}

/// A threat's own sound while it flies (createThreatVoice): the anti-ship missile's turbine
/// scream over its exhaust roar, the mortar shell's falling whistle, the drone's two-stroke buzz
/// with the air rushing in its dive. The main thread sets the Doppler-shifted pitch, level, air
/// absorption and distance gain each frame (updateThreats).
public final class ThreatSynth: SoundSynth, @unchecked Sendable {
  public enum Kind { case ascm, mortar, drone }
  /// The base pitch's multiplier (Doppler, slow motion, dive or fall); band: the noise band's
  public let frequency = SharedFloat(1), band = SharedFloat(1)
  public let level = SharedFloat(0), air = SharedFloat(2000), distanceGain = SharedFloat(0)
  public let rush = SharedFloat(0)
  public let released = SharedFlag(false)
  public let kind: Kind
  public let base: Float
  private var oscs: [Oscillator] = []
  private var mults: [Float] = [], mix: [Float] = []
  private var noise: SoundRandom
  private var noiseBand: Biquad
  private let bandBase: Float, bandLevel: Float
  private var tone = Biquad(.lowpass), airFilter = Biquad(.lowpass)
  private var lfo = Oscillator(.square)
  private var hz = Smooth(1), bandHz = Smooth(1), gain = Smooth(0), airHz = Smooth(2000),
    distance = Smooth(0), rushGain = Smooth(0)
  public init(kind: Kind, seed: UInt64, sampleRate: Double, bus: SoundBus) {
    self.kind = kind
    noise = SoundRandom(seed: seed)
    switch kind {
    case .ascm:
      base = noise.range(1700, 2000)
      oscs = [.init(.sine), .init(.sine), .init(.sine), .init(.triangle), .init(.sawtooth)]
      mults = [1, 1.007, 2.01, 0.5, 0.065]
      mix = [0.3, 0.18, 0.07, 0.08, 0.35]
      noiseBand = Biquad(.bandpass, q: 0.55)
      (bandBase, bandLevel) = (1100, 0.75)
    case .mortar:
      base = noise.range(1250, 1500)
      oscs = [.init(.sine), .init(.triangle)]
      mults = [1, 1.004]
      mix = [1, 0.25]
      noiseBand = Biquad(.bandpass, q: 1.5)
      (bandBase, bandLevel) = (1800, 0.5)
    case .drone:
      base = noise.range(95, 120)
      oscs = [.init(.sawtooth), .init(.square), .init(.sawtooth)]
      mults = [1, 2.003, 0.5]
      mix = [0.6, 0.25, 0.3]
      noiseBand = Biquad(.bandpass, q: 1.2)
      (bandBase, bandLevel) = (1400, 0)
    }
    super.init(sampleRate: sampleRate, bus: bus)
    tone.set(kind == .ascm ? 380 : 1800, sampleRate: self.sampleRate)
  }
  override func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    let sr = sampleRate
    let target: Float = released.value ? 0 : level.value
    var (f, fStep) = hz.ramp(base * frequency.value, 0.05, frames: frames, sampleRate: sr)
    _ = bandHz.ramp(bandBase * band.value, 0.05, frames: frames, sampleRate: sr)
    noiseBand.set(kind == .mortar ? bandBase : bandHz.value, sampleRate: sr)
    var (g, gStep) = gain.ramp(target, released.value ? 0.03 : 0.1, frames: frames, sampleRate: sr)
    _ = airHz.ramp(air.value, 0.1, frames: frames, sampleRate: sr)
    airFilter.set(airHz.value, sampleRate: sr)
    var (d, dStep) = distance.ramp(distanceGain.value, 0.02, frames: frames, sampleRate: sr)
    var (r, rStep) = rushGain.ramp(
      kind == .drone ? rush.value : bandLevel, 0.1, frames: frames, sampleRate: sr)
    for i in 0..<frames {
      var x: Float = 0
      switch kind {
      case .ascm:
        for k in 0..<4 { x += oscs[k].next(f * mults[k] / sr) * mix[k] }
        x += tone.process(oscs[4].next(f * mults[4] / sr) * mix[4])
      case .mortar:
        for k in 0..<2 { x += oscs[k].next(f * mults[k] / sr) * mix[k] }
      case .drone:
        var engine: Float = 0
        for k in 0..<3 { engine += oscs[k].next(f * mults[k] / sr) * mix[k] }
        // Soft clip, then the firing-stroke flutter at half the engine's rate
        let flutter = 0.75 + 0.25 * lfo.next(f * 0.5 / sr)
        x = tone.process(tanh(3 * max(-1, min(1, engine)))) * flutter
      }
      x += noiseBand.process(noise.signed() * 0.9) * r
      out[i] = airFilter.process(x * g) * d
      f += fStep
      g += gStep
      d += dStep
      r += rStep
    }
  }
}

/// A steady noise bed (buildAmbient): the sea's brown-noise wash or the wind's pink-noise gusts,
/// filtered and swelled by the main thread
public final class NoiseBedSynth: SoundSynth, @unchecked Sendable {
  public let level = SharedFloat(0), center = SharedFloat(500)
  public let levelTime: Float
  private var loop: LoopPlayer
  private var low: Biquad, high: Biquad?
  private var gain = Smooth(0), hz: Smooth
  private let moving: Bool
  /// sea: highpass 90 into lowpass 1100; wind: a band (0.5 Q) whose centre moves with the gusts
  public init(sea: Bool, loop buffer: SampleBuffer, seed: UInt64, sampleRate: Double, bus: SoundBus) {
    var random = SoundRandom(seed: seed)
    loop = LoopPlayer(buffer, random: &random)
    moving = !sea
    levelTime = sea ? 0.9 : 1.2
    low = sea ? Biquad(.lowpass) : Biquad(.bandpass, q: 0.5)
    high = sea ? Biquad(.highpass) : nil
    hz = Smooth(sea ? 1100 : 500)
    super.init(sampleRate: sampleRate, bus: bus)
    low.set(hz.value, sampleRate: self.sampleRate)
    high?.set(90, sampleRate: self.sampleRate)
  }
  override func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    var (g, step) = gain.ramp(level.value, levelTime, frames: frames, sampleRate: sampleRate)
    if moving {
      _ = hz.ramp(center.value, 1.2, frames: frames, sampleRate: sampleRate)
      low.set(hz.value, sampleRate: sampleRate)
    }
    for i in 0..<frames {
      var x = loop.next()
      if high != nil { x = high!.process(x) }
      out[i] = low.process(x) * g
      g += step
    }
  }
}

/// The ship's machinery: a low engine/generator drone felt more than heard
public final class EngineSynth: SoundSynth, @unchecked Sendable {
  private var oscs = [Oscillator(.sine), Oscillator(.sine), Oscillator(.sine)]
  public let level: Float
  public init(level: Double, sampleRate: Double, bus: SoundBus) {
    self.level = Float(level)
    super.init(sampleRate: sampleRate, bus: bus)
  }
  override func synthesize(_ out: UnsafeMutablePointer<Float>, _ frames: Int) {
    let sr = sampleRate
    for i in 0..<frames {
      out[i] =
        (oscs[0].next(31 / sr) + 0.5 * oscs[1].next(62 / sr) + 0.25 * oscs[2].next(93.5 / sr))
        * level
    }
  }
}
