import Foundation

public struct WaterPlume: Identifiable, Sendable {
  public var id: Int, position: Vector3, life: Double, height: Double, width: Double, seed: Double
  public var age = 0.0
}
struct Splinter {
  var position: Vector3, velocity: Vector3, age = 0.0
}
extension Effects {
  func spawnPlume(at p: Vector3, scale: Double = 1) {
    if plumes.count >= 1024 { plumes.removeFirst() }
    plumes.append(
      WaterPlume(
        id: id(), position: p.settingY(-1.5),
        life: random.range(1.1, 1.9), height: random.range(4, 10) * scale,
        width: random.range(1.8, 3.6) * (0.7 + 0.3 * scale), seed: random.unit()))
  }
  func spawnSplinters(at p: Vector3, carry: Vector3, flat: Bool) {
    var inherited = share(carry, 0.7, 110)
    if flat { inherited.y = 0 }
    for _ in 0..<min(60, 1200 - splinters.count) {
      var dir = randomDirection()
      dir.y = dir.y * 0.8 + 0.35
      dir = dir.normalized * random.range(12, 45) + inherited * random.range(0.6, 1)
      splinters.append(Splinter(position: p, velocity: dir))
    }
  }
  func insideHull(_ p: Vector3, simulation: Simulation) -> Bool {
    if p.y < GameRules.deckHeight(p.z) + 0.5 && GameRules.overHull(p) { return true }
    guard p.y < 3.25 else { return false }
    return simulation.friendlies.contains { f in
      let local = (p - f.position).rotatedY(-f.heading)
      return abs(local.z) < 22.96 && abs(local.x) < 3.652
    }
  }
  func updateWater(dt: Double, simulation: Simulation) {
    for i in splinters.indices.reversed() {
      splinters[i].velocity *= exp(-0.6 * dt)
      splinters[i].velocity.y -= 22 * dt
      splinters[i].position += splinters[i].velocity * dt
      splinters[i].age += dt
      let s = splinters[i]
      var done = s.age > 8 || insideHull(s.position, simulation: simulation)
      if !done && s.position.y <= -1.5 {
        spawnPlume(at: s.position, scale: 0.6 + 0.4 * min(1, s.velocity.length / 40))
        done = true
      }
      if done {
        splinters.swapAt(i, splinters.count - 1)
        splinters.removeLast()
      }
    }
    for i in plumes.indices { plumes[i].age += dt }
    plumes.removeAll { $0.age >= $0.life }
  }
}
