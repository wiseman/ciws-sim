import Foundation
import simd

public enum ThreatKind: String, Codable, Sendable, CaseIterable {
  case drone, mortar, ascm
  public var name: String {
    switch self {
    case .drone: "DRONE"
    case .mortar: "SHELL"
    case .ascm: "VAMPIRE"
    }
  }
  public var damage: Int { self == .ascm ? 35 : 25 }
  public var health: Int { self == .ascm ? 3 : 2 }
}
public struct TargetInfo: Sendable {
  public var position: Vector3
  public var friendlyID: Int?
  public init(position: Vector3 = [0, 6, 0], friendlyID: Int? = nil) {
    self.position = position
    self.friendlyID = friendlyID
  }
}
public struct RadarTrack: Sendable {
  var positionError = Vector3.zero, positionTarget = Vector3.zero
  var velocityError = Vector3.zero, velocityTarget = Vector3.zero
  var retuneIn = 0.0
}
public struct DroneDive: Sendable {
  public enum Phase: String, Sendable { case cruise, pushover, terminal }
  public var phase: Phase = .cruise
  public var cruise: Double
  public var gamma: Double
  public var pushoverRange: Double
  public var fullLoad: Double
  public var bank = 0.0
  var right = Vector3.zero
}
public struct Threat: Identifiable, Sendable {
  public var id: Int
  public var kind: ThreatKind
  public var position: Vector3
  public var velocity: Vector3
  public var health: Int
  public var targetInfo: TargetInfo
  public var trackedPosition: Vector3
  public var trackedVelocity: Vector3
  public var radar = RadarTrack()
  public var dive: DroneDive?
  public var speed = 0.0
  public var detected = false
  public var engineLoad = 0.0
  public var orientation = simd_quatd(real: 1, imag: .zero)
  public var propAngle = 0.0
  public var eta: Double { (position - targetInfo.position).length / max(velocity.length, 1e-4) }

  public init(id: Int, kind: ThreatKind, position: Vector3, velocity: Vector3, target: TargetInfo) {
    self.id = id
    self.kind = kind
    self.position = position
    self.velocity = velocity
    health = kind.health
    targetInfo = target
    trackedPosition = position
    trackedVelocity = velocity
  }

  public mutating func updateRadar(steps: Double, random: GameRandom) {
    radar.retuneIn -= steps
    if radar.retuneIn <= 0 {
      func error(_ magnitude: Double) -> Vector3 {
        let p = Vector3(
          random.signed(magnitude), random.signed(magnitude) * 0.45, random.signed(magnitude))
        return p.normalized * min(p.length, magnitude)
      }
      radar.positionTarget = error(0.3 + position.length * 0.00375)
      radar.velocityTarget = error(velocity.length * 0.04)
      radar.retuneIn = random.range(6, 18)
    }
    let blend = clamp(0.08 * steps, 0, 1)
    radar.positionError += (radar.positionTarget - radar.positionError) * blend
    radar.velocityError += (radar.velocityTarget - radar.velocityError) * blend
    trackedPosition = position + radar.positionError
    trackedVelocity = velocity + radar.velocityError
  }

  public mutating func steerSeaSkimmer() {
    let d = targetInfo.position - position
    let horizontal = max(1e-3, hypot(d.x, d.z))
    let k = min(1, horizontal / 45)
    let desiredY = targetInfo.position.y + (1.8 - targetInfo.position.y) * k
    let vy = clamp((desiredY - position.y) * 0.05, -0.3 * speed, 0.3 * speed)
    let h = sqrt(speed * speed - vy * vy)
    velocity = [d.x / horizontal * h, vy, d.z / horizontal * h]
    orientation = lookAlong(velocity)
  }

  public mutating func fly(steps: Double) -> Bool {
    switch kind {
    case .ascm:
      position += velocity * steps
      steerSeaSkimmer()
      return false
    case .mortar:
      position += velocity * steps
      velocity.y -= GameRules.gravity * steps
      orientation = lookAlong(velocity)
      let d = position - targetInfo.position
      return hypot(d.x, d.z) < 8 && position.y < targetInfo.position.y + 2
    case .drone:
      let from = velocity
      let count = max(1, Int(floor(steps + 0.5)))
      let dt = steps / Double(count)
      let speedup = 1 - exp(-dt / 42)
      var arrived = false
      for _ in 0..<count {
        if arrived { break }
        let old = position
        position += velocity * dt
        let k = segmentSphereEntry(old, position, targetInfo.position, 5)
        if k >= 0 { position = old + (position - old) * k }
        arrived = k >= 0 || (dive?.phase == .terminal && position.y < targetInfo.position.y - 1)
        if !arrived { steerDrone(steps: dt, speedup: speedup) }
      }
      orientDrone(from: from, steps: steps)
      propAngle = modulo(propAngle + min(0.45 * steps, 2 * .pi / 4 * 0.38), 2 * .pi)
      return arrived
    }
  }

  public mutating func steerDrone(steps: Double, speedup: Double) {
    guard var d = dive else { return }
    var to = targetInfo.position - position
    if d.phase == .cruise {
      if hypot(to.x, to.z) <= d.pushoverRange { d.phase = .pushover } else { to.y = 0 }
    }
    var speed = velocity.length
    var direction = velocity / speed
    let goal = to.normalized
    let off = acos(clamp(simd_dot(direction, goal), -1, 1))
    let maximum = GameRules.droneTurnRate * steps
    if off <= maximum {
      direction = goal
    } else {
      direction = simd_quatd(angle: maximum, axis: simd_cross(direction, goal).normalized).act(
        direction)
    }
    if d.phase != .cruise {
      let goalSpeed = d.cruise * (1 + 0.6 * max(0, -direction.y))
      speed += (goalSpeed - speed) * speedup
      if d.phase == .pushover && off < .pi / 180 { d.phase = .terminal }
    }
    velocity = direction * speed
    engineLoad = clamp((speed - d.cruise) / d.fullLoad, 0, 1)
    dive = d
  }

  public mutating func orientDrone(from: Vector3, steps: Double) {
    guard var d = dive else { return }
    let forward = velocity.normalized
    if abs(forward.y) < 0.98 {
      d.right = simd_cross(forward, [0, 1, 0]).normalized
    } else {
      d.right = (d.right - forward * simd_dot(d.right, forward)).normalized
    }
    if steps > 0 {
      let sideways = simd_dot(velocity - from, d.right) / steps
      let bank = clamp(atan(sideways / GameRules.droneBankG), -.pi / 3, .pi / 3)
      d.bank += (bank - d.bank) * (1 - exp(-steps / 8))
    }
    let up = simd_cross(d.right, forward) * cos(d.bank) + d.right * sin(d.bank)
    orientation = simd_quatd(simd_double3x3(columns: (simd_cross(up, forward), up, forward)))
    dive = d
  }
}

// THREE.Object3D.lookAt for a model (+z forward), rather than a camera (-z forward).
func lookAlong(_ velocity: Vector3) -> simd_quatd {
  var z = velocity.normalized
  if z.length == 0 { z.z = 1 }
  var x = simd_cross(Vector3(0, 1, 0), z)
  if x.length == 0 {
    z.z += 0.0001
    z = z.normalized
    x = simd_cross(Vector3(0, 1, 0), z)
  }
  x = x.normalized
  return simd_quatd(simd_double3x3(columns: (x, simd_cross(z, x), z)))
}
