import Foundation
import simd

public struct Friendly: Identifiable, Sendable {
  public var id: Int
  public var key: String
  public var name: String { key == "cape-sable" ? "Cape Sable" : key.capitalized }
  public var fit: Int
  public var number: String
  public var position: Vector3
  public var heading: Double
  public var radarAngle: Double
  public var cells: [VLSCell]
  public var alive = true
  public var arriving: Vector3?
  public var wakeStrength = 0.0, wakeScroll = 0.0
  public var onStation: Bool { alive && arriving == nil }
  public static let keys = [
    "halvorsen", "whitcomb", "cordell", "pellam", "marsden", "talbert", "vanover", "cape-sable",
  ]
  static let hulls = [
    (0, "64"), (1, "38"), (0, "67"), (1, "41"), (0, "69"), (1, "47"), (0, "72"), (1, "52"),
  ]
  static func deckHeight(_ z: Double) -> Double {
    -1.5 + (GameRules.deckHeight(z / 0.41 + 14) + 1.5) * 0.55
  }
  public var launcherOrigin: Vector3 {
    let z = fit == 0 ? -9.2 : -9.8
    return Vector3(fit == 0 ? 1.24 : 0, Self.deckHeight(z) - 0.75, z).rotatedY(heading) + position
  }
}
public struct Wreck: Identifiable, Sendable {
  public var id: Int { slot }
  public var slot: Int, key: String
  public var position: Vector3, heading: Double, baseY: Double
  public var listSign: Double, bowLift: Double
  public var age = 0.0, nextSmoke = 0.0, nextFoam = 0.5
  public var bowPitch = 0.0, sternPitch = 0.0, roll = 0.0
}
struct FleetStation {
  var position: Vector3
  var heading: Double
  var footprint: [Vector3]
}
extension Simulation {
  func footprint(at p: Vector3, heading: Double) -> [Vector3] {
    [-1.0, -0.5, 0, 0.5, 1].map { p + Vector3(-sin(heading), 0, -cos(heading)) * ($0 * 22.96) }
  }
  func pickStation(others: [[Vector3]], lane: Double = 0) -> FleetStation {
    func tooClose(_ a: [Vector3], _ b: [Vector3]) -> Bool {
      a.contains { p in b.contains { q in hypot(p.x - q.x, p.z - q.z) < 18 } }
    }
    while true {
      let p = Vector3(random.signed(100), 0.75, random.signed(100))
      let heading = random.range(-0.45, 0.45)
      let fp = footprint(at: p, heading: heading)
      let path = (0..<Int(ceil(lane / 9))).map {
        p + Vector3(sin(heading), 0, cos(heading)) * (Double($0 + 1) * 9)
      }
      if GameRules.nearShip(p, margin: 15)
        || fp.contains(where: { GameRules.nearShip($0, margin: 8) })
        || others.contains(where: { tooClose(fp, $0) })
        || path.contains(where: { GameRules.nearShip($0, margin: 8) })
        || others.contains(where: { tooClose(path, $0) })
      {
        continue
      }
      return FleetStation(position: p, heading: heading, footprint: fp)
    }
  }
  func buildFriendly(id: Int, key: String, station: FleetStation) -> Friendly {
    let hull = Friendly.hulls[Friendly.keys.firstIndex(of: key)!]
    let cells = VLSCell.module(origin: .zero)
    return Friendly(
      id: id, key: key, fit: hull.0, number: hull.1, position: station.position,
      heading: station.heading, radarAngle: random.range(0, 2 * .pi), cells: [cells[1], cells[6]])
  }
  func createFleet() {
    let names = random.shuffle(Friendly.keys)
    var footprints: [[Vector3]] = []
    for i in 0..<5 {
      let station = pickStation(others: footprints)
      footprints.append(station.footprint)
      friendlies.append(buildFriendly(id: i, key: names[i], station: station))
    }
  }
  public func sendReplacement(_ slot: Int) {
    let taken = Set(friendlies.map(\.key))
    let key = random.pick(Friendly.keys.filter { !taken.contains($0) })
    let others = friendlies.filter { $0.id != slot }.map {
      footprint(at: $0.arriving ?? $0.position, heading: $0.heading)
    }
    let station = pickStation(others: others, lane: 300)
    var f = buildFriendly(id: slot, key: key, station: station)
    f.arriving = f.position
    f.position += Vector3(sin(station.heading), 0, cos(station.heading)) * 600
    f.wakeStrength = 1
    friendlies[slot] = f
  }
  func updateArrivals(steps: Double) {
    for i in friendlies.indices {
      guard let station = friendlies[i].arriving else {
        friendlies[i].wakeStrength = max(0, friendlies[i].wakeStrength - 0.4 * steps / 60 / 10)
        if !friendlies[i].alive { friendlies[i].wakeStrength = 0 }
        continue
      }
      let left = (station - friendlies[i].position).length
      let step = min(left, 0.35 * sqrt(min(1, left / 60)) * steps)
      if left > 500 && left - step <= 500 {
        voices.play("arrive", params: .init(ship: friendlies[i].key))
      }
      if left - step < 0.01 {
        friendlies[i].position = station
        friendlies[i].arriving = nil
        voices.play(
          "joined",
          params: .init(ship: friendlies[i].key, side: station.x >= 0 ? "starboard" : "port"))
      } else {
        friendlies[i].position += (station - friendlies[i].position) * (step / left)
      }
      friendlies[i].wakeScroll += step
      if friendlies[i].arriving == nil {
        friendlies[i].wakeStrength = 0.4
      } else if steps > 0 {
        friendlies[i].wakeStrength = min(1, step / (0.35 * steps))
      }
    }
  }
  public func destroyFriendly(_ slot: Int) {
    guard friendlies.indices.contains(slot), friendlies[slot].alive else { return }
    friendlies[slot].alive = false
    let f = friendlies[slot]
    wrecks.append(
      Wreck(
        slot: slot, key: f.key, position: f.position, heading: f.heading, baseY: f.position.y,
        listSign: random.unit() < 0.5 ? -1 : 1, bowLift: random.range(0.75, 1.25)))
    voices.announceFriendlyHit(key: f.key, side: f.position.x >= 0 ? 1 : -1)
    events.append(.friendlyLost(slot))
    if !zen && !friendlies.contains(where: \.alive) { triggerGameOver(.friendlies) }
  }
  func updateWrecks(dt: Double) {
    for i in friendlies.indices {
      friendlies[i].radarAngle = modulo(friendlies[i].radarAngle + dt * 2.5, 2 * .pi)
    }
    for i in wrecks.indices.reversed() {
      var w = wrecks[i]
      w.age += dt
      let b = smoothstep(w.age, 0, 2.5)
      let s = 1 - pow(1 - min(1, w.age / 95), 1.6)
      let p = smoothstep(w.age, 95, 115)
      if p >= 1 {
        wrecks.remove(at: i)
        voices.play("gone", params: .init(ship: w.key))
        if zen { sendReplacement(w.slot) }
        continue
      }
      w.bowPitch = (0.07 * b + 0.12 * s + 0.45 * p) * w.bowLift
      w.sternPitch = -(0.045 * b + 0.08 * s + 0.35 * p)
      w.position.y =
        w.baseY - 0.6 * b - 1.9 * s - 24 * pow(p, 2.5) + sin(w.age * 0.9) * 0.05 * (1 - p)
      w.roll = w.listSign * (0.06 * b + 0.3 * s + 0.2 * p)
      w.nextSmoke -= dt
      w.nextFoam -= dt
      if w.age < 95 * 0.92 && w.nextSmoke <= 0 {
        let fierce = w.age < 4
        let fade = min(1, w.age / 95)
        w.nextSmoke += fierce ? 0.1 : 0.2 + 0.25 * fade
        effects.wreckSmoke(at: w.position, fierce: fierce, fade: fade)
      }
      if w.nextFoam <= 0 {
        w.nextFoam = random.range(1.6, 3) * (p > 0 ? 0.4 : 1)
        effects.foam(
          at: w.position + [random.range(-3, 3), 0, random.range(-3, 3)],
          size: random.range(12, 18), life: random.range(1.6, 2.4))
      }
      wrecks[i] = w
    }
  }
}
