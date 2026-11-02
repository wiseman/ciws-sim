import Foundation

public struct VLSCell: Sendable {
  public var position: Vector3, side: Double
  public var open = 0.0, amount = 0.0
  public var lidAngle: Double { -side * 1.9 * amount }
  static func module(origin: Vector3) -> [VLSCell] {
    (0..<4).flatMap { row in
      [-1.0, 1].map {
        VLSCell(position: origin + [$0 * 1.05, 0.15, -2.4 + Double(row) * 1.6], side: $0)
      }
    }
  }
  mutating func swing(_ dt: Double) {
    open -= dt
    let target = open > 0 ? 1.0 : 0
    amount += (target - amount) * min(1, dt * (target > 0 ? 14 : 2.5))
  }
}
public enum Launcher: Equatable, Sendable {
  case ship
  case friendly(Int)
}
struct VLSResponse {
  var delay: Double, bearing: Double
  var follow: Launcher?
}
struct VLSHeld {
  var delay: Double
  var bearing: Double?
}
struct VLSPending {
  var launcher: Launcher
  var position: Vector3
  var vent: Vector3
  var scale: Double
  var bearing: Double?
  var delay = 0.8
}
public struct VLSFlight: Identifiable, Sendable {
  public var id: Int, position: Vector3, scale: Double, heading: Vector3
  public var direction = Vector3(0, 1, 0), speed = 6.0, age = 0.0
  public var pitchStart: Double, climb: Double, burn: Double
  public var burning: Bool { age < burn }
  public var tail: Vector3 { position - direction * (2.4 * scale) }
}
extension Simulation {
  func validLauncher(_ launcher: Launcher) -> Bool {
    switch launcher {
    case .ship: true
    case .friendly(let id): friendlies[id].onStation
    }
  }
  @discardableResult public func launchVLS(_ launcher: Launcher, bearing: Double? = nil) -> Bool {
    let cells: [VLSCell]
    switch launcher {
    case .ship: cells = shipCells
    case .friendly(let id): cells = friendlies[id].cells
    }
    let ready = cells.indices.filter { cells[$0].open <= 0 }
    guard !ready.isEmpty else { return false }
    let index = random.pick(ready)
    let cell = cells[index]
    let pos: Vector3
    let vent: Vector3
    let scale: Double
    switch launcher {
    case .ship:
      shipCells[index].open = 6.8
      pos = cell.position
      scale = 1
      vent = [0, pos.y + 0.25, pos.z]
      longRun.cost += 2.1e6
    case .friendly(let id):
      friendlies[id].cells[index].open = 6.8
      let f = friendlies[id]
      scale = 0.65
      pos = f.launcherOrigin + (cell.position * scale).rotatedY(f.heading)
      vent =
        f.launcherOrigin
        + (Vector3(0, cell.position.y + 0.25, cell.position.z) * scale).rotatedY(f.heading)
    }
    vlsPending.append(
      VLSPending(launcher: launcher, position: pos, vent: vent, scale: scale, bearing: bearing))
    return true
  }
  func fireVLS(_ pending: VLSPending) {
    let b = (pending.bearing ?? random.range(0, 360)) * .pi / 180
    let flight = VLSFlight(
      id: allocateID(), position: pending.position - [0, 2.6 * pending.scale, 0],
      scale: pending.scale,
      heading: [sin(b), 0, -cos(b)], pitchStart: random.range(0.5, 0.8),
      climb: random.range(0.3, 0.6), burn: random.range(4, 5.5))
    launches.append(flight)
    effects.launchCloud(at: pending.vent, scale: pending.scale)
    events.append(.launch(pending.position, pending.scale))
    switch pending.launcher {
    case .ship: voices.play("birds-away")
    case .friendly(let id): voices.play("shooting", params: .init(ship: friendlies[id].key))
    }
  }
  func updateVLS(dt: Double) {
    for i in vlsPending.indices.reversed() {
      vlsPending[i].delay -= dt
      if vlsPending[i].delay > 0 { continue }
      let p = vlsPending.remove(at: i)
      if validLauncher(p.launcher) { fireVLS(p) }
    }
    for i in shipCells.indices { shipCells[i].swing(dt) }
    for i in friendlies.indices {
      for j in friendlies[i].cells.indices { friendlies[i].cells[j].swing(dt) }
    }
    for i in launches.indices.reversed() {
      launches[i].age += dt
      if launches[i].age >= 9 {
        launches.remove(at: i)
        continue
      }
      var l = launches[i]
      if l.burning { l.speed = min(420, l.speed + (l.age < 0.25 ? 25 : 120) * dt) }
      let pitch = smoothstep(l.age, l.pitchStart, l.pitchStart + 1) * (.pi / 2 - l.climb)
      l.direction = (Vector3(0, cos(pitch), 0) + l.heading * sin(pitch)).normalized
      l.position += l.direction * (l.speed * dt)
      if l.burning {
        effects.trail(
          id: l.id, at: l.tail, width: 1.4 * l.scale, life: 20,
          spacing: clamp(l.speed * 0.045, 0.5, 18))
      }
      launches[i] = l
    }
  }
  func updateVLSSchedule(dt: Double) {
    vlsCooldown -= dt
    if vlsResponse != nil { vlsResponse!.delay -= dt }
    if vlsHeld != nil {
      vlsHeld!.delay -= dt
      if vlsHeld!.delay <= 0 {
        launchVLS(.ship, bearing: vlsHeld!.bearing)
        vlsHeld = nil
      }
    }
    let due = vlsResponse.map { $0.delay <= 0 } ?? false
    guard due || vlsCooldown <= 0 else { return }
    let bearing = due ? vlsResponse!.bearing + random.range(-8, 8) : nil
    let follow = due ? vlsResponse!.follow : nil
    vlsResponse = nil
    if !due { vlsCooldown = random.range(35, 75) }
    let alive = friendlies.filter(\.onStation)
    let launcher: Launcher
    if let follow, validLauncher(follow) {
      launcher = follow
    } else {
      launcher = random.unit() < 0.35 || alive.isEmpty ? .ship : .friendly(random.pick(alive).id)
    }
    var wait = 0.0
    if launcher == .ship && follow == nil {
      wait =
        vlsHeld != nil ? 0 : voices.warnVLSLaunch(routine: !due, timeScale: timeScale) * timeScale
      if wait > 0 {
        vlsHeld = VLSHeld(delay: wait, bearing: bearing)
      } else if !launchVLS(.ship, bearing: bearing) {
        return
      }
    } else if !launchVLS(launcher, bearing: bearing) {
      return
    }
    lastVLSLaunchAt = elapsed + wait
    if follow == nil && random.unit() < 0.4 {
      vlsResponse = VLSResponse(
        delay: wait + random.range(1.2, 2.2), bearing: bearing ?? random.range(0, 360),
        follow: launcher)
    }
  }
  func requestVLSResponse(bearing: Double) {
    guard vlsResponse == nil, elapsed - lastVLSLaunchAt >= 10, random.unit() <= 0.55 else { return }
    vlsResponse = VLSResponse(delay: random.range(2.5, 4.5), bearing: bearing)
  }
}
