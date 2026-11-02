import Foundation
import simd

// JavaScript numbers and THREE.Vector3 use doubles. Convert only at the rendering boundary.
public typealias Vector3 = SIMD3<Double>
extension SIMD3 where Scalar == Double {
  public var float: SIMD3<Float> { SIMD3<Float>(Float(x), Float(y), Float(z)) }
  public var length: Double { simd_length(self) }
  public var normalized: Self { self / (length == 0 ? 1 : length) }
  public func settingY(_ y: Double) -> Self { [x, y, z] }
  public func rotatedY(_ angle: Double) -> Self {
    [x * cos(angle) + z * sin(angle), y, z * cos(angle) - x * sin(angle)]
  }
}
func clamp(_ x: Double, _ lo: Double, _ hi: Double) -> Double { min(max(x, lo), hi) }
func modulo(_ x: Double, _ n: Double) -> Double {
  (x.truncatingRemainder(dividingBy: n) + n).truncatingRemainder(dividingBy: n)
}
public func wrapAngle(_ a: Double) -> Double { modulo(a + .pi, 2 * .pi) - .pi }
func smoothstep(_ x: Double, _ lo: Double, _ hi: Double) -> Double {
  if x <= lo { return 0 }
  if x >= hi { return 1 }
  let t = (x - lo) / (hi - lo)
  return t * t * (3 - 2 * t)
}
func lerp(_ a: Double, _ b: Double, _ t: Double) -> Double { a + (b - a) * t }
func ema(_ previous: Double, _ value: Double, _ k: Double) -> Double {
  previous.isFinite ? previous + (value - previous) * k : value
}
func sign(_ x: Double) -> Double { x == 0 ? 0 : x < 0 ? -1 : 1 }
func sigmoid(_ x: Double) -> Double { 1 / (1 + exp(-x)) }

/// All stochastic rules take a source so reference tests can supply the same random tape as JS.
public final class GameRandom {
  private var state: UInt64
  private var tape: [Double]
  private var cursor = 0
  public init(seed: UInt64 = UInt64.random(in: 1...UInt64.max), tape: [Double] = []) {
    state = seed
    self.tape = tape
  }
  public func unit() -> Double {
    if !tape.isEmpty {
      precondition(cursor < tape.count, "Reference random tape exhausted")
      defer { cursor += 1 }
      return tape[cursor]
    }
    state = state &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
    return Double(state >> 11) / 9_007_199_254_740_992
  }
  func range(_ a: Double, _ b: Double) -> Double { a + unit() * (b - a) }
  func signed(_ range: Double) -> Double { (unit() * 2 - 1) * range }
  func pick<T>(_ items: [T]) -> T { items[Int(unit() * Double(items.count))] }
  func shuffle<T>(_ items: [T]) -> [T] {
    var result = items
    guard result.count > 1 else { return result }
    for i in stride(from: result.count - 1, through: 1, by: -1) {
      result.swapAt(i, Int(unit() * Double(i + 1)))
    }
    return result
  }
}

public enum GameRules {
  public static let stepsPerSecond = 60.0
  public static let bulletSpeed = 8.0
  public static let gravity = 0.02
  public static let roundLife = 60.0
  public static let roundTravel = 59.0
  public static let maximumIntercept = 240.0
  public static let impactRadius = 5.0
  public static let mountY = 4.0
  public static let waterY = -1.5
  public static let radarPositionError = 0.3
  public static let radarRangeError = 0.00375
  public static let radarVerticalScale = 0.45
  public static let radarVelocityError = 0.04
  public static let radarReseed = 6.0...18.0
  public static let radarResponse = 0.08
  public static let maxTraverseRate = 0.08
  public static let maxTraverseAcceleration = 0.005
  public static let yawFireThreshold = 0.10
  public static let pitchFireThreshold = 0.10
  public static let droneTurnRate = Double.pi / 240
  public static let droneBankG = 9.8 / (60 * 60)
  public static let hullStations: [[Double]] = [
    [-42, 4.6, 0.25, 0, -1.2], [-39, 4.15, 1.7, 0.15, -2.8], [-36, 3.75, 3, 0.8, -4],
    [-33, 3.35, 4.1, 1.7, -4.8], [-30, 3, 5.1, 2.6, -5.3], [-26, 2.65, 6.2, 3.7, -5.7],
    [-22, 2.35, 7, 4.7, -5.9], [-18, 2.12, 7.6, 5.5, -6], [-14, 2, 8, 6.2, -6],
    [-10, 2, 8.3, 6.8, -6], [-5, 2, 8.45, 7.3, -6], [2, 2, 8.5, 7.6, -6], [50, 2, 8.5, 7.6, -6],
    [58, 1.95, 8.4, 7.2, -4.5], [64, 1.9, 8.1, 6.6, -2.6], [70, 1.85, 7.8, 6, -0.9],
  ]
  public static func stationValue(_ z: Double, _ column: Int) -> Double {
    if z <= hullStations[0][0] { return hullStations[0][column] }
    for i in 1..<hullStations.count where z <= hullStations[i][0] {
      let a = hullStations[i - 1]
      let b = hullStations[i]
      return lerp(a[column], b[column], (z - a[0]) / (b[0] - a[0]))
    }
    return hullStations.last![column]
  }
  public static func deckHeight(_ z: Double) -> Double { stationValue(z, 1) }
  public static func hullHalfWidth(_ z: Double) -> Double { stationValue(z, 2) }
  static func nearShip(_ p: Vector3, margin: Double) -> Bool {
    abs(p.x) < 8.5 + margin && p.z > -42 - margin && p.z < 70 + margin
  }
  static func overHull(_ p: Vector3, margin: Double = 0) -> Bool {
    p.z > -42 && p.z < 70 && abs(p.x) < hullHalfWidth(p.z) + margin
  }
}

public struct AimSolution: Codable, Sendable {
  public var targetYaw: Double
  public var targetPitch: Double
  public var interceptSteps: Double?
  public var canFire: Bool
  public var inReach: Bool { interceptSteps.map { $0 <= GameRules.roundTravel } ?? false }
}

public func solveInterceptSteps(_ d: Vector3, _ v: Vector3, _ speed: Double = GameRules.bulletSpeed)
  -> Double?
{
  let a = simd_dot(v, v) - speed * speed
  let b = 2 * simd_dot(d, v)
  let c = simd_dot(d, d)
  if abs(a) < 1e-6 {
    guard abs(b) > 1e-6 else { return nil }
    let t = -c / b
    return t > 0 && t <= GameRules.maximumIntercept ? t : nil
  }
  let discriminant = b * b - 4 * a * c
  guard discriminant >= 0 else { return nil }
  let candidates = [(-b - sqrt(discriminant)) / (2 * a), (-b + sqrt(discriminant)) / (2 * a)].filter
  { $0 > 0 }
  guard let t = candidates.min(), t <= GameRules.maximumIntercept else { return nil }
  return t
}

public func sightAngles(target: Vector3, muzzle: Vector3) -> AimSolution {
  let d = target - muzzle
  return AimSolution(
    targetYaw: atan2(d.x, d.z), targetPitch: -atan2(d.y, hypot(d.x, d.z)),
    interceptSteps: nil, canFire: false)
}

public func computeAimSolution(target: Vector3, velocity: Vector3, isMortar: Bool, muzzle: Vector3)
  -> AimSolution
{
  let time = solveInterceptSteps(target - muzzle, velocity)
  var aim = target
  if let time {
    aim += velocity * time
    if !isMortar { aim.y += 0.5 * GameRules.gravity * time * time }
  }
  var solution = sightAngles(target: aim, muzzle: muzzle)
  solution.interceptSteps = time
  solution.canFire = time != nil  // Deliberately NOT limited to round travel; matches the classic solver.
  return solution
}

public struct Traverse: Codable, Sendable {
  public var angle: Double
  public var rate: Double
  public var error: Double
}
public func stepTraverseAxis(
  current: Double, target: Double, rate: Double, steps: Double, wrap: Bool = false
) -> Traverse {
  var diff = target - current
  if wrap {
    while diff > .pi { diff -= 2 * .pi }
    while diff < -.pi { diff += 2 * .pi }
  }
  let accelStep = GameRules.maxTraverseAcceleration * steps
  let absDiff = abs(diff)
  if absDiff < 1e-5 && abs(rate) < accelStep { return Traverse(angle: current, rate: 0, error: 0) }
  let desired =
    sign(diff)
    * min(GameRules.maxTraverseRate, sqrt(2 * GameRules.maxTraverseAcceleration * absDiff))
  var nextRate = rate + clamp(desired - rate, -accelStep, accelStep)
  var step = nextRate * steps
  if abs(step) > absDiff {
    step = diff
    nextRate = 0
  }
  let angle = wrap ? wrapAngle(current + step) : current + step
  return Traverse(angle: angle, rate: nextRate, error: abs(diff - step))
}

public func segmentSphereEntry(_ a: Vector3, _ b: Vector3, _ c: Vector3, _ radius: Double) -> Double
{
  let seg = b - a
  let off = a - c
  let outside = simd_length_squared(off) - radius * radius
  if outside <= 0 { return 0 }
  let lengthSq = simd_length_squared(seg)
  let closing = simd_dot(off, seg)
  let disc = closing * closing - lengthSq * outside
  if closing >= 0 || disc < 0 { return -1 }
  let k = (-closing - sqrt(disc)) / lengthSq
  return k <= 1 ? k : -1
}

extension GameRandom {
  /// Original random-comparator lottery, using V8's small-array binary insertion order.
  /// All chatter/routine lists have at most six entries.
  func randomizedLots<T>(_ items: [T]) -> [T] {
    guard items.count > 1 else { return items }
    var a = items
    for start in 1..<a.count {
      let pivot = a[start]
      var left = 0
      var right = start
      while left < right {
        let mid = (left + right) / 2
        if unit() < 0.5 { right = mid } else { left = mid + 1 }
      }
      if left < start {
        for p in stride(from: start, through: left + 1, by: -1) { a[p] = a[p - 1] }
      }
      a[left] = pivot
    }
    return a
  }
}
