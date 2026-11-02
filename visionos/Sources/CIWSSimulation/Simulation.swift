import Foundation
import simd

public struct Round: Identifiable, Sendable {
  public var id: Int
  public var position: Vector3
  public var velocity: Vector3
  public var life: Double = 60
  public var firedBy: ControllerMode
  public var origin: Vector3
  public var previousPosition: Vector3
  public var orientation: simd_quatd
}
public struct EngagementStats: Codable, Sendable {
  public var rounds = 0, hits = 0, kills = 0
}
public enum GameOverReason: String, Sendable { case ciws, friendlies }
public enum SimulationEvent: Sendable {
  case contact(ThreatKind)
  case destroyed(Vector3)
  case impact(Vector3)
  case wave(Int)
  case friendlyLost(Int)
  case sighting(String)
  case launch(Vector3, Double)
  case chirp
  case passBy(String, Vector3)
}

/// Swift port of the web game's updateLogic/animate rules. Velocities and accelerations
/// retain their original units per reference step; each display frame supplies simSteps.
public final class Simulation {
  public static let step = 1.0 / 60
  public internal(set) var threats: [Threat] = []
  public internal(set) var rounds: [Round] = []
  public internal(set) var events: [SimulationEvent] = []
  public internal(set) var elapsed = 0.0
  public internal(set) var realTime = 0.0
  public internal(set) var health = 100
  public internal(set) var kills = 0
  public var highScore = 0
  public internal(set) var wave = 1
  public internal(set) var yaw = Double.pi
  public internal(set) var pitch = 0.0
  public internal(set) var yawRate = 0.0, pitchRate = 0.0
  public internal(set) var barrelSpeed = 0.0
  public internal(set) var barrelAngle = 0.0
  public internal(set) var isFiring = false
  public internal(set) var targetID: Int?
  public internal(set) var gameOverReason: GameOverReason?
  public var isGameOver: Bool { gameOverReason != nil }
  public var automaticFire = true
  public var spawningEnabled = true
  public var isPaused = false
  public var timeScale = 1.0
  public var controllerMode: ControllerMode = .classic
  public let neural: NeuralController
  public let voices: VoiceScheduler
  public let random: GameRandom
  public internal(set) var stats: [ControllerMode: EngagementStats] = [
    .classic: .init(), .neural: .init(),
  ]
  public var roundsFired: Int { stats.values.reduce(0) { $0 + $1.rounds } }
  public internal(set) var friendlies: [Friendly] = []
  public internal(set) var wrecks: [Wreck] = []
  public internal(set) var launches: [VLSFlight] = []
  public internal(set) var shipCells: [VLSCell] = []
  public var longRun = LongRunState()
  public internal(set) var sightings: [Sighting] = []
  public var holiday: Holiday?
  public internal(set) var zen = false
  public var effects: Effects
  public var onSaveLongRun: ((LongRunState) -> Void)?
  public var onHighScore: ((Int) -> Void)?
  var frameMuzzle: Vector3?
  var nextID = 0
  var spawnCooldown = 0.0, difficultyCooldown = 0.0, missileSpawnRate = 120.0, fireCooldown = 0.0
  var barrelHold = 0.0, vampireDetections = 0
  var vlsCooldown = 30.0, lastVLSLaunchAt = -Double.infinity
  var vlsResponse: VLSResponse?, vlsHeld: VLSHeld?
  var vlsPending: [VLSPending] = []
  var zenSaved: (wave: Int, spawnRate: Double, difficulty: Double)?
  var zenRaidIn = 0.0
  var asks: [PendingVoiceAsk] = []

  public init(
    seed: UInt64 = UInt64.random(in: 1...UInt64.max), holiday: Holiday? = Holiday.today,
    voiceClipsReady: Bool = true, createFleet: Bool = true
  ) {
    random = GameRandom(seed: seed)
    neural = NeuralController(random: random)
    voices = VoiceScheduler(random: random, allClipsReady: voiceClipsReady)
    effects = Effects(random: random)
    self.holiday = holiday
    shipCells = VLSCell.module(origin: [0, GameRules.deckHeight(-10.5), -10.5])
    if createFleet { self.createFleet() }
  }

  public var muzzlePosition: Vector3 {
    let pitchQ = simd_quatd(angle: pitch, axis: [1, 0, 0])
    return Vector3(0, 7, 0) + (Vector3(0, 2, 0.5) + pitchQ.act([0, 0, 5])).rotatedY(yaw)
  }
  public func advance(realDelta: Double) {
    events.removeAll(keepingCapacity: true)
    guard !isPaused, realDelta.isFinite, realDelta > 0 else { return }
    realTime += realDelta
    voices.advanceClock(realDelta)
    let steps = realDelta * 60 * timeScale
    if !isGameOver { updateLogic(steps: steps, realDelta: realDelta) }
    effects.update(dt: steps / 60, simulation: self)
    updateWrecks(dt: steps / 60)
    updateVLS(dt: steps / 60)
    updateSightings(dt: steps / 60)
    voices.updateIdle(threats: threats, gameOver: isGameOver, played: longRun.played)
  }

  func updateLogic(steps: Double, realDelta: Double) {
    // THREE uses the last rendered barrels.matrixWorld throughout updateLogic.
    frameMuzzle = muzzlePosition
    defer { frameMuzzle = nil }
    elapsed += realDelta * timeScale
    updateLongRun(realDelta)
    if spawningEnabled {
      spawnCooldown -= steps
      if spawnCooldown <= 0 {
        spawnMissile()
        spawnCooldown = missileSpawnRate
      }
    }
    difficultyCooldown -= steps
    if difficultyCooldown <= 0 {
      wave += 1
      missileSpawnRate = max(20, 120 - Double(wave) * 5)
      difficultyCooldown = 1000
      events.append(.wave(wave))
      if random.unit() < 0.5 { voices.play("raid-size") }
    }
    if zen {
      zenRaidIn -= steps / 60
      if zenRaidIn <= 0 {
        zenRaidIn = random.range(180, 300)
        voices.play("raid-size")
      }
    }
    updateVLSSchedule(dt: steps / 60)
    updateArrivals(steps: steps)
    var bestID: Int?
    var bestETA = Double.infinity
    var bestPriority = 0
    for i in threats.indices.reversed() {
      let arrived = threats[i].fly(steps: steps)
      if threats[i].kind == .ascm && !threats[i].detected && threats[i].position.length < 950 {
        threats[i].detected = true
        onVampireDetected(threats[i])
      }
      threats[i].updateRadar(steps: steps, random: random)
      let threat = threats[i]
      if arrived || (threat.position - threat.targetInfo.position).length < 5 {
        effects.explosion(
          at: threat.position, kind: .impact, carry: threat.velocity, holiday: holiday)
        events.append(.impact(threat.position))
        threats.remove(at: i)
        if let friendly = threat.targetInfo.friendlyID {
          if friendlies.indices.contains(friendly), friendlies[friendly].alive {
            destroyFriendly(friendly)
          }
        } else {
          if !zen { health = max(0, health - threat.kind.damage) }
          if health <= 0 {
            triggerGameOver(.ciws)
          } else {
            voices.announceDamage(point: threat.position, kind: threat.kind)
          }
        }
        continue
      }
      let eta = threat.velocity.length < 1e-4 ? Double.infinity : threat.eta
      let priority = threat.targetInfo.friendlyID == nil ? 0 : 1
      if bestID == nil || eta < bestETA - 1e-3
        || (abs(eta - bestETA) <= 1e-3 && priority > bestPriority)
      {
        bestID = threat.id
        bestETA = eta
        bestPriority = priority
      }
    }
    targetID = bestID
    let helicopter =
      (bestID == nil || bestETA > 5) ? sightings.firstIndex { $0.kind == .flyby && $0.near } : nil
    isFiring = false
    if let helicopter {
      if !sightings[helicopter].scolded {
        sightings[helicopter].scolded = true
        voices.play("no-bad")
      }
      traverse(
        sightAngles(target: sightings[helicopter].position, muzzle: muzzlePosition), steps: steps)
    } else if let target = threats.first(where: { $0.id == targetID }) {
      let muzzle = muzzlePosition
      let teacher = computeAimSolution(
        target: target.trackedPosition, velocity: target.trackedVelocity,
        isMortar: target.kind == .mortar, muzzle: muzzle)
      let inputs = makeControllerInputs(
        displacement: target.trackedPosition - muzzle,
        velocity: target.trackedVelocity, isMortar: target.kind == .mortar)
      let sight = sightAngles(target: target.trackedPosition, muzzle: muzzle)
      if neural.isTraining {
        neural.rememberLiveSample(
          inputs: inputs, targets: makeControllerTargets(solution: teacher, sight: sight))
        neural.trainFromLiveReplay(milliseconds: realTime * 1000)
      }
      let net = neural.isTrained ? neural.decide(inputs: inputs, sight: sight) : nil
      if let net { neural.recordAgreement(net: net, teacher: teacher) }
      let decision = controllerMode == .neural ? net ?? teacher : teacher
      let errors = traverse(decision, steps: steps)
      if automaticFire { fireCooldown -= steps }
      if automaticFire, decision.canFire, errors.0 < 0.1, errors.1 < 0.1, fireCooldown <= 0 {
        shoot()
        isFiring = true
        fireCooldown = 1
      }
    } else {
      traverse(
        AimSolution(targetYaw: yaw, targetPitch: pitch, interceptSteps: nil, canFire: false),
        steps: steps)
    }
    barrelHold = isFiring ? 75 : max(0, barrelHold - steps)
    barrelSpeed =
      barrelHold > 0 ? min(1, barrelSpeed + 0.05 * steps) : max(0, barrelSpeed - 0.035 * steps)
    barrelAngle = modulo(barrelAngle + min(0.38 * barrelSpeed * steps, 2 * .pi / 6 * 0.38), 2 * .pi)
    updateRounds(steps: steps)
  }
  @discardableResult func traverse(_ solution: AimSolution, steps: Double) -> (Double, Double) {
    let y = stepTraverseAxis(
      current: yaw, target: solution.targetYaw, rate: yawRate, steps: steps, wrap: true)
    let p = stepTraverseAxis(
      current: pitch, target: solution.targetPitch, rate: pitchRate, steps: steps)
    yaw = y.angle
    yawRate = y.rate
    pitch = p.angle
    pitchRate = p.rate
    return (y.error, p.error)
  }
  func shoot() {
    let muzzle = frameMuzzle ?? muzzlePosition
    var q = simd_quatd(angle: yaw, axis: [0, 1, 0]) * simd_quatd(angle: pitch, axis: [1, 0, 0])
    q *= simd_quatd(angle: (random.unit() - 0.5) * 0.0125, axis: [1, 0, 0])
    q *= simd_quatd(angle: (random.unit() - 0.5) * 0.0125, axis: [0, 1, 0])
    rounds.append(
      Round(
        id: allocateID(), position: muzzle, velocity: q.act([0, 0, 8]), firedBy: controllerMode,
        origin: muzzle, previousPosition: muzzle, orientation: q))
    stats[controllerMode]!.rounds += 1
    longRun.cost += 35
  }
  func updateRounds(steps: Double) {
    for i in rounds.indices.reversed() {
      rounds[i].life -= steps
      if rounds[i].life <= 0 {
        effects.explosion(
          at: rounds[i].position, kind: .flak, carry: rounds[i].velocity, holiday: holiday)
        rounds.remove(at: i)
        continue
      }
      let previous = rounds[i].position
      rounds[i].previousPosition = previous
      rounds[i].velocity.y -= 0.02 * steps
      rounds[i].position += rounds[i].velocity * steps
      let direction = (rounds[i].position - previous).normalized
      for j in threats.indices.reversed() {
        let position = threats[j].position
        // Keep the web game's endpoint gate AND ray test, including its update ordering.
        guard (position - rounds[i].position).length < 3 else { continue }
        let along = simd_dot(position - previous, direction)
        let closest = along < 0 ? previous : previous + direction * along
        guard simd_length_squared(closest - position) < 1 else { continue }
        effects.explosion(at: position, kind: .hit, carry: threats[j].velocity, holiday: holiday)
        threats[j].health -= 1
        let firedBy = rounds[i].firedBy
        stats[firedBy]!.hits += 1
        rounds.remove(at: i)
        if threats[j].health <= 0 {
          let threat = threats.remove(at: j)
          effects.explosion(at: position, kind: .airburst, carry: threat.velocity, holiday: holiday)
          voices.announceKill(kind: threat.kind, distance: position.length)
          stats[firedBy]!.kills += 1
          kills += 1
          longRun.kills += 1
          if holiday == .july4 || holiday == .halloween { voices.play(holiday!.rawValue) }
          events.append(.destroyed(position))
          if kills > highScore && !zen {
            highScore = kills
            onHighScore?(highScore)
          }
        }
        break
      }
    }
  }
  func triggerGameOver(_ reason: GameOverReason) {
    guard !isGameOver else { return }
    gameOverReason = reason
    voices.stop()
  }
  public func applyWave(_ n: Int) {
    wave = n
    missileSpawnRate = max(20, 120 - Double(n) * 5)
    difficultyCooldown = .infinity
  }
  public func setZen(_ enabled: Bool) {
    guard zen != enabled else { return }
    zen = enabled
    if enabled {
      zenSaved = (wave, missileSpawnRate, difficultyCooldown)
      applyWave(7)
      zenRaidIn = random.range(180, 300)
      for f in friendlies where !f.alive && !wrecks.contains(where: { $0.slot == f.id }) {
        sendReplacement(f.id)
      }
    } else if let saved = zenSaved {
      wave = saved.wave
      missileSpawnRate = saved.spawnRate
      difficultyCooldown = saved.difficulty
    }
  }
  public func setController(_ mode: ControllerMode) {
    controllerMode = mode == .neural && !neural.isTrained ? .classic : mode
  }
  public func resetNeuralController() {
    neural.reset()
    controllerMode = .classic
  }
  public func sendRaid() {
    guard !isGameOver else { return }
    for _ in 0..<3 { spawnMissile() }
  }
  func allocateID() -> Int {
    defer { nextID += 1 }
    return nextID
  }
}

extension Simulation {
  public func targetInfo(friendlyID: Int? = nil) -> TargetInfo {
    friendlyID.map { TargetInfo(position: friendlies[$0].position, friendlyID: $0) } ?? TargetInfo()
  }
  func incomingTarget() -> TargetInfo {
    let alive = friendlies.filter(\.onStation)
    let own = random.unit() < 2 / 3 || alive.isEmpty
    return own ? TargetInfo() : targetInfo(friendlyID: random.pick(alive).id)
  }
  @discardableResult public func addThreat(
    kind: ThreatKind, position: Vector3, velocity: Vector3, target: TargetInfo = .init()
  ) -> Int {
    let id = allocateID()
    let threat = Threat(id: id, kind: kind, position: position, velocity: velocity, target: target)
    threats.append(threat)
    voices.noteThreat(threat)
    events.append(.contact(kind))
    return id
  }
  @discardableResult public func spawnDrone(
    target: TargetInfo = .init(), angle: Double? = nil,
    height: Double? = nil, gamma: Double? = nil
  ) -> Int {
    let angle = angle ?? random.range(0, 2 * .pi)
    let height = height ?? random.range(30, 90)
    let position = Vector3(cos(angle) * 600, height, sin(angle) * 600)
    var target = target
    target.position = target.friendlyID == nil ? droneStrikePoint() : target.position + [0, 2.5, 0]
    let cruise = 0.8 + Double(wave) * 0.05
    let velocity = (target.position - position).settingY(0).normalized * cruise
    let id = addThreat(kind: .drone, position: position, velocity: velocity, target: target)
    let drop = height - target.position.y
    let radius = cruise / GameRules.droneTurnRate
    let fit = acos(clamp(1 - 0.6 * drop / radius, -1, 1))
    let gamma = min((gamma ?? random.range(30, 45)) * .pi / 180, fit)
    let i = threats.count - 1
    threats[i].dive = DroneDive(
      cruise: cruise, gamma: gamma, pushoverRange: drop / tan(gamma) + radius * tan(gamma / 2),
      fullLoad: cruise * 0.6 * sin(gamma))
    threats[i].orientDrone(from: velocity, steps: 0)
    return id
  }
  @discardableResult public func spawnSeaSkimmer(target: TargetInfo = .init(), angle: Double? = nil)
    -> Int
  {
    let angle = angle ?? random.range(0, 2 * .pi)
    let position = Vector3(cos(angle) * 1150, random.range(12, 20), sin(angle) * 1150)
    var target = target
    if target.friendlyID == nil { target.position = shipStrikePoint(from: position) }
    let id = addThreat(kind: .ascm, position: position, velocity: .zero, target: target)
    let i = threats.count - 1
    threats[i].speed = 2.6 + Double(wave) * 0.03
    threats[i].steerSeaSkimmer()
    threats[i].trackedVelocity = threats[i].velocity
    return id
  }
  @discardableResult public func spawnMortar(
    target: TargetInfo = .init(), angle: Double? = nil, height: Double? = nil
  ) -> Int {
    let angle = angle ?? random.range(0, 2 * .pi)
    let position = Vector3(cos(angle) * 900, height ?? (2 + random.unit() * 5), sin(angle) * 900)
    let to = target.position - position
    let horizontal = hypot(to.x, to.z)
    let denominator = horizontal + position.y - target.position.y
    let speed =
      denominator > 10
      ? sqrt(0.02 * horizontal * horizontal / denominator) : sqrt(horizontal * 0.02 * 2)
    var velocity = to.settingY(0).normalized * (speed * sqrt(0.5))
    velocity.y = speed * sqrt(0.5)
    let id = addThreat(kind: .mortar, position: position, velocity: velocity, target: target)
    threats[threats.count - 1].orientation = lookAlong(velocity)
    return id
  }
  public func spawnMissile() {
    let target = incomingTarget()
    if wave >= 3 && random.unit() < 0.2 {
      spawnSeaSkimmer(target: target)
      return
    }
    if random.unit() < 0.5 {
      spawnDrone(target: target)
      return
    }
    spawnMortar(target: target)
  }
  public func droneStrikePoint() -> Vector3 {
    let zones: [(Double, Double, Double?, Double?)] = [
      (-30, -8, nil, nil), (-4, 8, 4, 5.7), (11, 22, 8.5, 5.1),
    ]
    var along = random.unit() * 45
    for (z0, z1, height, half) in zones {
      let z = z0 + along
      if z <= z1 {
        let w = (half ?? GameRules.hullHalfWidth(z)) - 2
        return [random.range(-w, w), height ?? GameRules.deckHeight(z), z]
      }
      along -= z1 - z0
    }
    preconditionFailure("Random value outside [0, 1)")
  }
  public func shipStrikePoint(from: Vector3) -> Vector3 {
    let to = Vector3(-from.x, 0, -from.z)
    let range = to.length
    let dir = to / range
    var point = Vector3.zero
    var distance = max(0, range - 150)
    while distance < range {
      point = from.settingY(0) + dir * distance
      if GameRules.overHull(point, margin: -1) { break }
      distance += 0.5
    }
    point += dir * 4
    point.y = GameRules.deckHeight(point.z) + 2
    return point
  }
  func onVampireDetected(_ threat: Threat) {
    let bearing = modulo(atan2(threat.position.x, -threat.position.z) * 180 / .pi + 360, 360)
    if vampireDetections % 4 == 0 { voices.announceVampire(bearing: bearing) }
    vampireDetections += 1
    requestVLSResponse(bearing: bearing)
  }
}
