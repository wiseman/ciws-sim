import Foundation
import simd

public enum Holiday: String, Codable, Sendable {
  case july4, halloween, xmas
  public static var today: Holiday? {
    let c = Calendar.current.dateComponents([.month, .day], from: Date())
    return forDate(month: c.month!, day: c.day!)
  }
  public static func forDate(month: Int, day: Int) -> Holiday? {
    switch (month, day) {
    case (7, 4): .july4
    case (10, 31): .halloween
    case (12, 24), (12, 25): .xmas
    default: nil
    }
  }
}
public struct LongRunState: Codable, Sendable {
  public var played = 0.0, cost = 0.0
  public var kills = 0, milestone = 0
  public var routineAt = 300.0, chirpAt = 7200.0, savedAt = 0.0
  public var routineHeard: [String: Double] = [:], sightAt: [String: Double] = [:]
  public var killMarks: Int { (kills / 100) % 10 }
  public var killStars: Int { min(28, kills / 1000) }
  public init() {}
}
final class PendingVoiceAsk {
  var bucket: String, params: VoiceParameters, until: Double
  var next = 0.0, waiting = false, done = false
  init(_ bucket: String, params: VoiceParameters, until: Double) {
    self.bucket = bucket
    self.params = params
    self.until = until
  }
}
public enum SightingKind: String, CaseIterable, Sendable {
  case flyby, dolphins, bird, sailboat, whale, duck, sleigh
}
public struct Dolphin: Sendable {
  public var dx: Double, dz: Double, period: Double, phase: Double, high: Double
  public var wet = true, visible = false
  public var position = Vector3.zero, pitch = 0.0
}
public struct Sighting: Identifiable, Sendable {
  public var id: Int, kind: SightingKind, position: Vector3
  public var age = 0.0, side = 1.0, direction = 1.0, yaw = 0.0, pitch = 0.0, roll = 0.0
  public var seen = false, near = false, scolded = false, sounded = false
  public var from = Vector3.zero, velocity = Vector3.zero, length = 0.0, travelled = 0.0
  public var baseY = 0.0, wing = 0.0, rotor = 0.0, tailRotor = 0.0, sparkle = 0.0
  public var pod: [Dolphin] = []
  public var blows = 0
}
extension Simulation {
  func sayEventually(_ bucket: String, params: VoiceParameters = .init(), within: Double = 60) {
    asks.append(PendingVoiceAsk(bucket, params: params, until: longRun.played + within))
  }
  func updateLongRun(_ dt: Double) {
    longRun.played += dt
    if longRun.played >= longRun.routineAt {
      longRun.routineAt = longRun.played + random.range(360, 600)
      let routine = [
        ("pa-watch", 0.0), ("pa-sweepers", 0), ("pa-chow", 0), ("pa-mail", 0), ("pa-taps", 3600),
        ("pa-reveille", 5400),
      ]
      func heard(_ name: String) -> Double { longRun.routineHeard[name] ?? -1 }
      let due = routine.filter {
        longRun.played >= $0.1 && ($0.0 != "pa-reveille" || heard("pa-taps") > heard("pa-reveille"))
      }.map(\.0)
      let name = random.randomizedLots(due).enumerated().sorted { a, b in
        heard(a.element) == heard(b.element)
          ? a.offset < b.offset : heard(a.element) < heard(b.element)
      }.first!.element
      longRun.routineHeard[name] = longRun.played
      sayEventually(name, within: 90)
    }
    let milestones = [4e7, 1e8, 5e8, 2e9]
    if longRun.milestone < milestones.count && longRun.cost >= milestones[longRun.milestone] {
      longRun.milestone += 1
      sayEventually("cost-\(longRun.milestone)", within: 120)
    }
    if longRun.played >= longRun.chirpAt && !isFiring {
      longRun.chirpAt = longRun.played + random.range(240, 600)
      events.append(.chirp)
    }
    let sightings: [(SightingKind, Double, Double, Double)] = [
      (.flyby, 480, 720, 1200), (.dolphins, 600, 900, 1500), (.bird, 720, 900, 1500),
      (.sailboat, 900, 1200, 2100), (.whale, 1200, 1500, 2400), (.duck, 3600, 5400, 9000),
      (.sleigh, 150, 1200, 1800),
    ]
    for (kind, after, lo, hi) in sightings {
      if kind == .sleigh && holiday != .xmas { continue }
      if longRun.sightAt[kind.rawValue] == nil {
        longRun.sightAt[kind.rawValue] = after + random.range(0, lo / 2)
      }
      if longRun.played < longRun.sightAt[kind.rawValue]! { continue }
      if !self.sightings.isEmpty {
        longRun.sightAt[kind.rawValue] = longRun.played + random.range(60, 180)
      } else if startSighting(kind) {
        longRun.sightAt[kind.rawValue] = longRun.played + random.range(lo, hi)
      }
    }
    for a in asks {
      if a.waiting || longRun.played < a.next { continue }
      a.next = longRun.played + 4
      if let attempt = voices.play(a.bucket, params: a.params) {
        a.waiting = true
        attempt.then { [weak a] end in
          a?.waiting = false
          a?.done = end != nil
        }
      }
    }
    asks.removeAll { $0.done || (!$0.waiting && longRun.played >= $0.until) }
    if longRun.played - longRun.savedAt >= 15 {
      longRun.savedAt = longRun.played
      onSaveLongRun?(longRun)
    }
  }
  @discardableResult public func startSighting(_ kind: SightingKind) -> Bool {
    func side() -> Double { random.unit() < 0.5 ? 1 : -1 }
    var s = Sighting(id: allocateID(), kind: kind, position: .zero)
    switch kind {
    case .flyby:
      s.side = side()
      s.direction = side()
      s.position = [s.side * random.range(26, 40), 22, -s.direction * 700]
      s.yaw = s.direction > 0 ? 0 : .pi
      s.pitch = 0.08
    case .dolphins:
      s.side = side()
      s.position = [s.side * random.range(15, 24), 0, -170]
      for i in 0..<(4 + Int(random.unit() * 3)) {
        s.pod.append(
          Dolphin(
            dx: s.side * random.range(-3, 4), dz: -Double(i) * random.range(2.5, 4),
            period: random.range(2, 2.8), phase: random.range(0, 3), high: random.range(1.1, 1.8)))
      }
    case .whale:
      s.side = side()
      s.position = [s.side * random.range(75, 110), -10.5, random.range(-50, 70)]
      s.yaw = random.unit() < 0.5 ? 0 : .pi
    case .sailboat:
      var found = false
      for _ in 0..<12 {
        let bearing = random.range(0, 2 * .pi)
        let distance = random.range(150, 230)
        let normal = Vector3(cos(bearing), 0, sin(bearing))
        let direction = Vector3(-normal.z, 0, normal.x) * side()
        let start = normal * distance - direction * 300
        if friendlies.filter(\.alive).allSatisfy({ f in
          let t = clamp(simd_dot(f.position - start, direction), 0, 600)
          return (f.position - start - direction * t).settingY(0).length > 45
        }) {
          s.position = start.settingY(-1.5)
          s.velocity = direction
          s.yaw = atan2(direction.x, direction.z)
          found = true
          break
        }
      }
      if !found { return false }
    case .bird:
      s.side = side()
      s.from = [s.side * 130, random.range(11, 17), random.range(-60, 40)]
      let to = Vector3(-s.side * 130, random.range(11, 17), random.range(-50, 30))
      s.length = (to - s.from).length
      s.velocity = (to - s.from).normalized
      s.position = s.from
    case .duck:
      s.side = side()
      s.position = [s.side * random.range(11, 14), -1.5, -95]
    case .sleigh:
      s.side = side()
      s.direction = side()
      s.baseY = random.range(45, 60)
      s.position = [s.side * random.range(30, 80), s.baseY, -s.direction * 750]
      s.yaw = s.direction > 0 ? 0 : .pi
    }
    sightings.append(s)
    return true
  }
  func updateSightings(dt: Double) {
    for i in sightings.indices.reversed() {
      var s = sightings[i]
      s.age += dt
      var seen = false
      var finished = false
      switch s.kind {
      case .flyby:
        s.position.z += s.direction * 45 * dt
        s.near = abs(s.position.z) < 140
        s.rotor += 27 * dt
        s.tailRotor += 60 * dt
        seen = -s.direction * s.position.z < 420 && -s.direction * s.position.z > 0
        if !s.sounded && -s.direction * s.position.z < 180 {
          s.sounded = true
          events.append(.passBy("helicopter", s.position))
        }
        finished = s.direction * s.position.z >= 700
      case .dolphins:
        s.position.z += 8 * dt
        for j in s.pod.indices {
          var d = s.pod[j]
          let u = modulo(s.age + d.phase, d.period) / 0.9
          let out = u < 1
          if d.wet == out {
            effects.foam(at: [s.position.x + d.dx, -1.5, s.position.z + d.dz], size: 3, life: 1)
            d.wet = !out
          }
          d.visible = out
          d.position = [s.position.x + d.dx, -1.8 + d.high * 4 * u * (1 - u), s.position.z + d.dz]
          d.pitch = -atan2(d.high * 4 * (1 - 2 * u) / 0.9, 8)
          s.pod[j] = d
        }
        seen = s.position.z > -70 && s.position.z < -20
        finished = s.position.z >= 230
      case .whale:
        s.position += Vector3(0, 0, 1.2 * dt).rotatedY(s.yaw)
        let keys = [(0.0, -0.48), (3.0, -0.06), (8.0, 0.1), (16.0, 1.5)]
        for k in 1..<keys.count where s.age >= keys[k - 1].0 && s.age <= keys[k].0 {
          let t =
            k == 3
            ? smoothstep(s.age, keys[k - 1].0, keys[k].0)
            : (s.age - keys[k - 1].0) / (keys[k].0 - keys[k - 1].0)
          s.pitch = lerp(keys[k - 1].1, keys[k].1, t)
        }
        if s.blows < 2 && s.age >= [3.0, 6.5][s.blows] {
          s.blows += 1
          effects.foam(at: s.position, size: 5, life: 2)
        }
        seen = s.age >= 3
        finished = s.age >= 16
      case .sailboat:
        s.travelled += 2.6 * dt
        s.position += s.velocity * (2.6 * dt)
        s.position.y = -1.5 + 0.08 * sin(s.age * 1.3)
        s.roll = 0.12 + 0.03 * sin(s.age * 0.9)
        seen = s.position.length < 240
        finished = s.travelled >= 600
      case .bird:
        s.travelled += 10 * dt
        s.position = s.from + s.velocity * s.travelled
        s.position.y += sin(s.age * 0.8) * 1.2
        s.position.x += sin(s.age * 0.5) * 3
        s.yaw = atan2(s.velocity.x, s.velocity.z) + sin(s.age * 0.5) * 0.25
        s.wing = modulo(s.age, 4) < 2.6 ? sin(s.age * 9) * 0.55 : 0.1
        seen = s.position.length < 70
        finished = s.travelled >= s.length
      case .duck:
        s.position.z += 1.5 * dt
        s.position.y = -1.65 + 0.12 * sin(s.age * 1.7)
        s.pitch = 0.08 * sin(s.age * 1.3)
        s.yaw = 0.6 * sin(s.age * 0.13) + s.side * 0.3
        s.roll = 0.1 * sin(s.age * 1.1)
        seen = s.position.z > -12 && s.position.z < 12
        finished = s.position.z >= 135
      case .sleigh:
        s.position.z += s.direction * 30 * dt
        s.position.y = s.baseY + sin(s.age * 1.4) * 1.5
        s.pitch = -cos(s.age * 1.4) * 0.05
        s.sparkle += 40 * dt
        while s.sparkle >= 1 {
          s.sparkle -= 1
          effects.spark(
            at: s.position + [random.range(-1.5, 1.5), 0.3, -s.direction * random.range(1, 3)],
            velocity: effects.randomDirection() * random.range(1, 4), life: random.range(0.6, 1.4),
            width: 0.12, length: 0.3, color: 0xffd36b)
        }
        seen = abs(s.position.z) < 650 && -s.direction * s.position.z > 0
        if !s.sounded && -s.direction * s.position.z < 90 {
          s.sounded = true
          events.append(.passBy("sleigh", s.position))
        }
        finished = s.direction * s.position.z >= 750
      }
      if seen && !s.seen {
        s.seen = true
        voices.play(s.kind.rawValue, params: .init(side: s.side > 0 ? "starboard" : "port"))
        events.append(.sighting(s.kind.rawValue))
      }
      if finished { sightings.remove(at: i) } else { sightings[i] = s }
    }
  }
}
