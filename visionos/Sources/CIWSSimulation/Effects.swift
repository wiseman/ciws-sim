import Foundation

public enum ExplosionKind: String, Sendable { case airburst, impact, hit, flak }
public struct Puff: Identifiable, Sendable {
  public var id: Int, position: Vector3, velocity: Vector3
  public var age = 0.0, life: Double, delay = 0.0
  public var s0: Double, s1: Double, growRate = 4.0, heat0 = 1.2, heatRate = 1.0,
    dissolveStart = 0.55
  public var drag = 2.5, buoyancy = 2.0, gravity = 0.0, wind = 0.0, smoke: UInt32 = 0x67615b
  public var scale = 0.0, heat = 0.0, dissolve = 0.0
  public var seed = 0.0, spin = 0.0, rotation = Vector3.zero
  public mutating func step(_ dt: Double) {
    velocity *= exp(-drag * dt)
    velocity.y += (buoyancy - gravity) * dt
    position += velocity * dt + Vector3(2.4, 0, -1.1) * (wind * dt)
    scale = s1 + (s0 - s1) * exp(-growRate * age)
    heat = heat0 - heatRate * age
    let k = age / life
    dissolve = k < dissolveStart ? 0 : 0.1 + 0.85 * (k - dissolveStart) / (1 - dissolveStart)
  }
}
public struct Spark: Identifiable, Sendable {
  public var id: Int, position: Vector3, velocity: Vector3, life: Double, width: Double,
    length: Double, color: UInt32?
  public var age = 0.0
}
public struct Debris: Identifiable, Sendable {
  public var id: Int, position: Vector3, velocity: Vector3, carry: Vector3, life: Double,
    size: Double, spin: Vector3
  public var age = 0.0, rotation = Vector3.zero, clear = false, pumpkin = false
}
public struct EffectRing: Identifiable, Sendable {
  public var id: Int, position: Vector3, size: Double, life: Double, foam: Bool
  public var age = 0.0
}
public struct TrailPoint: Identifiable, Sendable {
  public var id: Int, owner: Int, position: Vector3, width: Double, life: Double
  public var age = 0.0
}
public struct ExplosionSound: Sendable {
  public var position: Vector3
  public var kind: ExplosionKind
}
/// Visual state is independent of RealityKit; the original puff, drag, gravity and carried-motion rules use seconds.
public final class Effects {
  public private(set) var puffs: [Puff] = [], sparks: [Spark] = [], debris: [Debris] = [],
    rings: [EffectRing] = [], trails: [TrailPoint] = []
  public private(set) var sounds: [ExplosionSound] = []
  public internal(set) var plumes: [WaterPlume] = []
  var splinters: [Splinter] = []
  private var lastTrail: [Int: Vector3] = [:]
  private var serial = 0
  let random: GameRandom
  init(random: GameRandom) { self.random = random }
  func id() -> Int {
    defer { serial += 1 }
    return serial
  }
  func randomDirection() -> Vector3 {
    let z = random.range(-1, 1)
    let a = random.range(0, 2 * .pi)
    let r = sqrt(1 - z * z)
    return [r * cos(a), z, r * sin(a)]
  }
  func share(_ velocity: Vector3, _ fraction: Double, _ cap: Double) -> Vector3 {
    velocity * min(fraction, cap / max(velocity.length, 1e-9))
  }
  func puff(
    _ position: Vector3, velocity: Vector3 = .zero, s0: Double, s1: Double, grow: Double = 4,
    heat: Double = 1.2, cooling: Double = 1, life: Double, dissolve: Double = 0.55,
    drag: Double = 2.5,
    buoyancy: Double = 2, gravity: Double = 0, wind: Double = 0, smoke: UInt32 = 0x67615b,
    delay: Double = 0,
    carry: Vector3 = .zero, amount: Double = 1
  ) {
    let left = exp(-drag * delay)
    puffs.append(
      Puff(
        id: id(), position: position + carry * (amount * (1 - left) / drag),
        velocity: velocity + carry * (amount * left),
        life: life, delay: delay, s0: s0, s1: s1, growRate: grow, heat0: heat, heatRate: cooling,
        dissolveStart: dissolve,
        drag: drag, buoyancy: buoyancy, gravity: gravity, wind: wind, smoke: smoke, scale: s0,
        heat: heat))
    let i = puffs.count - 1
    puffs[i].seed = random.range(0, 10)
    puffs[i].rotation = [random.range(0, 6.3), random.range(0, 6.3), random.range(0, 6.3)]
    puffs[i].spin = random.range(-0.4, 0.4)
  }
  func spark(
    at p: Vector3, velocity: Vector3, life: Double, width: Double, length: Double,
    color: UInt32? = nil
  ) {
    guard sparks.count < 800 else { return }
    sparks.append(
      Spark(
        id: id(), position: p, velocity: velocity, life: life, width: width, length: length,
        color: color))
  }
  func foam(at p: Vector3, size: Double, life: Double) {
    rings.append(
      EffectRing(id: id(), position: p.settingY(-1.44), size: size, life: life, foam: true))
    _ = random.unit()
  }
  func trail(id owner: Int, at p: Vector3, width: Double, life: Double, spacing: Double) {
    if let last = lastTrail[owner], (p - last).length <= spacing { return }
    lastTrail[owner] = p
    trails.append(TrailPoint(id: id(), owner: owner, position: p, width: width, life: life))
  }
  public func takeSounds() -> [ExplosionSound] {
    let s = sounds
    sounds = []
    return s
  }
  func explosion(at p: Vector3, kind: ExplosionKind, carry perStep: Vector3, holiday: Holiday?) {
    sounds.append(ExplosionSound(position: p, kind: kind))
    let v = perStep * 60
    if p.y <= 51 && (kind == .airburst || kind == .impact) {
      spawnSplinters(at: p, carry: v, flat: kind == .impact)
    }
    let size: Double = kind == .airburst ? 20 : kind == .impact ? 26 : kind == .hit ? 2.4 : 1.5
    rings.append(
      EffectRing(
        id: id(), position: p, size: size, life: kind == .airburst || kind == .impact ? 0.45 : 0.09,
        foam: false))
    switch kind {
    case .hit:
      puff(
        p, velocity: randomDirection() * 2 + share(v, 0.3, 40), s0: 0.3, s1: 1, grow: 7, heat: 1.1,
        cooling: 2.2, life: 1.3, dissolve: 0.4, drag: 3, buoyancy: 0.5)
      for _ in 0..<12 {
        spark(
          at: p, velocity: randomDirection() * random.range(20, 45) + share(v, 0.6, 90),
          life: random.range(0.15, 0.4), width: 0.07, length: 1.2)
      }
    case .flak:
      puff(
        p, s0: 0.2, s1: random.range(0.9, 1.3), grow: 9, heat: 0.75, cooling: 2.6,
        life: random.range(2, 2.6), dissolve: 0.5, drag: 4, buoyancy: 0.3, smoke: 0x2c2a29)
      for _ in 0..<3 {
        spark(
          at: p, velocity: randomDirection() * random.range(15, 30) + share(v, 0.1, 50),
          life: random.range(0.1, 0.25), width: 0.06, length: 0.9)
      }
    case .airburst:
      puff(
        p, velocity: share(v, 0.25, 40), s0: 0.8, s1: 3.8, grow: 6, heat: 1.6, life: 4.5,
        dissolve: 0.5, drag: 3, buoyancy: 1.5)
      for i in 0..<10 {
        let d = randomDirection()
        let pos = p + d * random.range(0.3, 1.2)
        let vel = d * random.range(6, 15)
        let amount = random.range(0.4, 1.6)
        puff(
          pos, velocity: vel, s0: 0.5, s1: random.range(2, 3.4), grow: 5,
          heat: random.range(1.2, 1.45), cooling: random.range(0.75, 0.95),
          life: random.range(3.5, 5), dissolve: 0.5, drag: 3, buoyancy: 2.5,
          delay: Double(i) * 0.012, carry: share(v, 0.2, 40), amount: amount)
      }
      for _ in 0..<4 {
        let d = randomDirection()
        let delay = random.range(0.2, 0.4)
        let vel = d * random.range(2, 5)
        puff(
          p + d * 1.5, velocity: vel, s0: 1, s1: random.range(3, 4.2), grow: 2.5, heat: 0.5,
          cooling: 0.5, life: random.range(4.5, 6), dissolve: 0.45, drag: 1.5, buoyancy: 1.2,
          smoke: 0x4f4a46, delay: delay, carry: share(v, 0.08, 15))
      }
      for i in 0..<6 {
        var d = randomDirection()
        d.y = abs(d.y) * 0.8 + 0.2
        fragment(
          p, velocity: d.normalized * random.range(18, 32), carry: share(v, 0.7, 110),
          life: random.range(1.2, 2), pumpkin: holiday == .halloween && i < 3)
      }
      if holiday == .july4 {
        let colors: [UInt32] = [0xff4040, 0x55aaff, 0xffffff, 0xffd34d, 0x66ff88]
        let a = random.pick(colors)
        let b = random.pick(colors)
        for i in 0..<110 {
          spark(
            at: p, velocity: randomDirection() * random.range(38, 50), life: random.range(1.4, 2.2),
            width: 0.45, length: 3, color: i % 2 == 0 ? a : b)
        }
      }
      for _ in 0..<34 {
        spark(
          at: p, velocity: randomDirection() * random.range(25, 65) + share(v, 0.45, 70),
          life: random.range(0.25, 0.7), width: 0.12, length: 2.2)
      }
    case .impact:
      let flat = v.settingY(0)
      for i in 0..<12 {
        var d = randomDirection()
        d.y = abs(d.y) * 1.4 + 0.3
        d = d.normalized
        let pos = p + d * random.range(0.5, 1.5)
        let vel = d * random.range(7, 16)
        puff(
          pos, velocity: vel, s0: 0.8, s1: random.range(3, 4.6), grow: 4.5,
          heat: random.range(1.25, 1.5), cooling: random.range(0.6, 0.8),
          life: random.range(5, 6.5), dissolve: 0.5, buoyancy: 4, delay: Double(i) * 0.015,
          carry: share(flat, 0.12, 25))
      }
      for i in 0..<6 {
        puff(
          p + [random.range(-2, 2), random.range(1, 3), random.range(-2, 2)],
          velocity: [random.range(-1, 1), random.range(4, 8), random.range(-1, 1)], s0: 1.2,
          s1: random.range(4, 6), grow: 1.6, heat: 0.55, cooling: 0.45, life: random.range(6, 8),
          dissolve: 0.5, drag: 0.8, buoyancy: 2.5, smoke: 0x4a4541, delay: 0.2 + Double(i) * 0.12)
      }
      for _ in 0..<8 {
        var d = randomDirection()
        d.y = abs(d.y) + 0.4
        fragment(
          p, velocity: d.normalized * random.range(16, 30), carry: share(flat, 0.25, 40),
          life: random.range(1.4, 2.2))
      }
      for _ in 0..<40 {
        var d = randomDirection()
        d.y = abs(d.y)
        spark(
          at: p, velocity: d * random.range(25, 60) + share(flat, 0.25, 40),
          life: random.range(0.3, 0.8), width: 0.14, length: 2.6)
      }
    }
  }
  func fragment(
    _ p: Vector3, velocity: Vector3, carry: Vector3, life: Double, pumpkin: Bool = false
  ) {
    debris.append(
      Debris(
        id: id(), position: p, velocity: velocity, carry: carry, life: life,
        size: random.range(0.6, 1.3),
        spin: [random.range(-12, 12), random.range(-12, 12), random.range(-12, 12)],
        pumpkin: pumpkin))
  }
  func wreckSmoke(at p: Vector3, fierce: Bool, fade: Double) {
    puff(
      p + [random.range(-1.2, 1.2), 0, random.range(-1.2, 1.2)],
      velocity: [random.range(-0.7, 0.7), random.range(4.5, 7), random.range(-0.7, 0.7)],
      s0: random.range(0.7, 1.1), s1: random.range(3.4, 5) * (fierce ? 1.2 : 1 - 0.3 * fade),
      grow: 0.22, heat: random.range(1.15, 1.4) - 0.3 * fade, cooling: 2.4,
      life: random.range(12, 15), dissolve: 0.6, drag: 0.35, buoyancy: 1.6, wind: 1, smoke: 0x414141
    )
  }
  func launchCloud(at p: Vector3, scale: Double) {
    for i in 0..<7 {
      puff(
        p + Vector3(random.range(-0.6, 0.6), random.range(0, 1.5), random.range(-1.2, 1.2)) * scale,
        velocity: Vector3(random.range(-3, 3), random.range(9, 18), random.range(-3, 3)) * scale,
        s0: 0.6 * scale, s1: random.range(2.2, 3.6) * scale, grow: 2.2, heat: random.range(1, 1.3),
        cooling: random.range(1.2, 1.6), life: random.range(9, 13), drag: 1.6, buoyancy: 0.9,
        wind: 0.7, smoke: 0xebe7de, delay: Double(i) * 0.03)
    }
    for i in 0..<5 {
      let a = random.range(0, 2 * .pi)
      puff(
        p,
        velocity: Vector3(
          cos(a) * random.range(6, 11), random.range(0.5, 2.5), sin(a) * random.range(6, 11))
          * scale, s0: 0.7 * scale, s1: random.range(1.8, 2.8) * scale, grow: 1.8, heat: 0.7,
        cooling: 0.9, life: random.range(7, 10), drag: 1.4, buoyancy: 0.35, wind: 0.9,
        smoke: 0xebe7de, delay: 0.05 + Double(i) * 0.04)
    }
  }
  func update(dt: Double, simulation: Simulation) {
    updateWater(dt: dt, simulation: simulation)
    for i in puffs.indices {
      if puffs[i].delay > 0 {
        puffs[i].delay -= dt
        if puffs[i].delay > 0 { continue }
      }
      puffs[i].age += dt
      puffs[i].step(dt)
    }
    puffs.removeAll { $0.age >= $0.life }
    for i in sparks.indices {
      sparks[i].age += dt
      sparks[i].velocity *= exp(-1.5 * dt)
      sparks[i].velocity.y -= 22 * 0.6 * dt
      sparks[i].position += sparks[i].velocity * dt
    }
    sparks.removeAll { $0.age >= $0.life }
    for i in debris.indices {
      debris[i].age += dt
      debris[i].velocity.y -= 22 * dt
      debris[i].velocity *= exp(-0.4 * dt)
      debris[i].carry *= exp(-1.2 * dt)
      debris[i].position += (debris[i].velocity + debris[i].carry) * dt
      debris[i].rotation += debris[i].spin * dt
      let p = debris[i].position
      let inside = GameRules.overHull(p) && p.y < GameRules.deckHeight(p.z)
      if inside && debris[i].clear { debris[i].age = debris[i].life }
      if !inside { debris[i].clear = true }
      if p.y < -1.5 {
        spawnPlume(at: p)
        foam(at: p, size: 2, life: 0.8)
      }
    }
    debris.removeAll { $0.age >= $0.life || $0.position.y < -1.5 }
    for i in rings.indices { rings[i].age += dt }
    rings.removeAll { $0.age >= $0.life }
    for i in trails.indices {
      trails[i].age += dt
      trails[i].position += Vector3(2.4, 0, -1.1) * (0.45 * dt)
    }
    trails.removeAll { $0.age > $0.life }
    let owners = Set(trails.map(\.owner))
    lastTrail = lastTrail.filter { owners.contains($0.key) }
  }
}
