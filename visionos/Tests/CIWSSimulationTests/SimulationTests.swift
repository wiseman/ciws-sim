import XCTest
import simd

@testable import CIWSSimulation

final class SimulationTests: XCTestCase {
  func reference() throws -> [String: Any] {
    try JSONSerialization.jsonObject(
      with: Data(contentsOf: Bundle.module.url(forResource: "reference", withExtension: "json")!))
      as! [String: Any]
  }
  func vector(_ object: Any) -> Vector3 {
    let a = object as! [Double]
    return [a[0], a[1], a[2]]
  }
  func equal(
    _ a: Vector3, _ b: Vector3, accuracy: Double = 1e-9, file: StaticString = #filePath,
    line: UInt = #line
  ) {
    for i in 0..<3 { XCTAssertEqual(a[i], b[i], accuracy: accuracy, file: file, line: line) }
  }
  func equal(
    _ a: [Double], _ b: [Double], accuracy: Double = 1e-10, file: StaticString = #filePath,
    line: UInt = #line
  ) {
    XCTAssertEqual(a.count, b.count, file: file, line: line)
    for (x, y) in zip(a, b) { XCTAssertEqual(x, y, accuracy: accuracy, file: file, line: line) }
  }
  func quietSimulation(fleet: Bool = false) -> Simulation {
    let s = Simulation(seed: 42, holiday: nil, createFleet: fleet)
    s.spawningEnabled = false
    s.automaticFire = false
    s.applyWave(3)
    s.vlsCooldown = .infinity
    return s
  }
  func testAimAndNeuralFeaturesMatchJavaScript() throws {
    for a in try reference()["aims"] as! [[String: Any]] {
      let target = vector(a["target"]!)
      let v = vector(a["velocity"]!)
      let m = vector(a["muzzle"]!)
      let mortar = a["mortar"] as! Bool
      let r = computeAimSolution(target: target, velocity: v, isMortar: mortar, muzzle: m)
      let expected = a["result"] as! [String: Any]
      XCTAssertEqual(r.targetYaw, expected["targetYaw"] as! Double, accuracy: 1e-12)
      XCTAssertEqual(r.targetPitch, expected["targetPitch"] as! Double, accuracy: 1e-12)
      XCTAssertEqual(r.canFire, expected["canFire"] as! Bool)
      if let t = expected["interceptSteps"] as? Double {
        XCTAssertEqual(r.interceptSteps!, t, accuracy: 1e-9)
      } else {
        XCTAssertNil(r.interceptSteps)
      }
      equal(
        makeControllerInputs(displacement: target - m, velocity: v, isMortar: mortar),
        a["inputs"] as! [Double])
      equal(
        makeControllerTargets(solution: r, sight: sightAngles(target: target, muzzle: m)),
        a["labels"] as! [Double])
    }
  }
  func testTraverseMatchesJavaScript() throws {
    for a in try reference()["traverse"] as! [[String: Any]] {
      let p = a["args"] as! [Any]
      let e = a["result"] as! [String: Double]
      let r = stepTraverseAxis(
        current: p[0] as! Double, target: p[1] as! Double, rate: p[2] as! Double,
        steps: p[3] as! Double, wrap: p[4] as! Bool)
      XCTAssertEqual(r.angle, e["angle"]!, accuracy: 1e-12)
      XCTAssertEqual(r.rate, e["rate"]!, accuracy: 1e-12)
      XCTAssertEqual(r.error, e["error"]!, accuracy: 1e-12)
    }
  }
  func testFlightTrajectoriesMatchJavaScript() throws {
    for f in try reference()["flights"] as! [[String: Any]] {
      let kind = ThreatKind(rawValue: f["kind"] as! String)!
      let steps = f["steps"] as! Double
      let initial = f["initial"] as! [String: Any]
      var t = Threat(
        id: 0, kind: kind, position: vector(initial["position"]!),
        velocity: vector(initial["velocity"]!), target: .init())
      t.speed = 2.81
      if kind == .drone {
        let g = 0.6
        t.dive = DroneDive(
          cruise: 1, gamma: g,
          pushoverRange: 54 / tan(g) + (1 / GameRules.droneTurnRate) * tan(g / 2),
          fullLoad: 0.6 * sin(g))
        t.orientDrone(from: t.velocity, steps: 0)
      }
      var frame = 0
      var arrived = false
      for e in f["frames"] as! [[String: Any]] {
        while frame < e["frame"] as! Int {
          arrived = t.fly(steps: steps) || (t.position - t.targetInfo.position).length < 5
          frame += 1
        }
        equal(t.position, vector(e["position"]!), accuracy: 1e-7)
        equal(t.velocity, vector(e["velocity"]!), accuracy: 1e-9)
        XCTAssertEqual(arrived, e["arrived"] as! Bool)
        if kind == .drone {
          XCTAssertEqual(t.dive!.phase.rawValue, e["phase"] as! String)
          XCTAssertEqual(t.dive!.bank, e["bank"] as! Double, accuracy: 1e-8)
          XCTAssertEqual(t.engineLoad, e["engineLoad"] as! Double, accuracy: 1e-9)
        }
      }
    }
  }
  func testRadarNoiseMatchesJavaScriptTape() throws {
    let r = try reference()
    let random = GameRandom(seed: 0, tape: r["tape"] as! [Double])
    var t = Threat(
      id: 0, kind: .drone, position: [400, 50, -200], velocity: [-1.3, 0.4, 0.8], target: .init())
    for e in r["radar"] as! [[String: Any]] {
      t.updateRadar(steps: 1.3, random: random)
      equal(t.trackedPosition, vector(e["position"]!))
      equal(t.trackedVelocity, vector(e["velocity"]!))
      XCTAssertEqual(t.radar.retuneIn, e["retune"] as! Double, accuracy: 1e-12)
    }
  }
  func testNeuralForwardAndTenAdamStepsMatchJavaScript() throws {
    let e = try reference()["neural"] as! [String: Any]
    let n = NeuralController(random: GameRandom(seed: 3))
    n.weights = e["initialWeights"] as! [[[Double]]]
    n.resetOptimizer()
    let batch = (e["batch"] as! [[String: [Double]]]).map {
      TrainingSample(inputs: $0["inputs"]!, targets: $0["targets"]!)
    }
    for (s, p) in zip(batch, e["predictions"] as! [[Double]]) { equal(n.predict(s.inputs), p) }
    for loss in e["losses"] as! [Double] {
      XCTAssertEqual(n.trainBatch(batch), loss, accuracy: 1e-10)
    }
    for (a, b) in zip(n.weights, e["finalWeights"] as! [[[Double]]]) {
      for (x, y) in zip(a, b) { equal(x, y) }
    }
  }
  func testClassicFireIsNotLimitedToRoundReach() {
    let r = computeAimSolution(
      target: [0, 9, 900], velocity: .zero, isMortar: false, muzzle: [0, 9, 0])
    XCTAssertTrue(r.canFire)
    XCTAssertFalse(r.inReach)
    XCTAssertEqual(r.interceptSteps, 112.5)
  }
  func testRoundExpiresBeforeSixtiethMoveAndUsesVelocityFirstGravity() {
    let s = quietSimulation()
    s.rounds = [
      Round(
        id: 1, position: [0, 100, 0], velocity: [0, 0, 8], firedBy: .classic, origin: [0, 100, 0],
        previousPosition: [0, 100, 0], orientation: simd_quatd())
    ]
    for _ in 0..<59 { s.updateRounds(steps: 1) }
    XCTAssertEqual(s.rounds[0].position.z, 472)
    XCTAssertEqual(s.rounds[0].position.y, 100 - 0.02 * 59 * 60 / 2, accuracy: 1e-10)
    s.updateRounds(steps: 1)
    XCTAssertTrue(s.rounds.isEmpty)
  }
  func testCollisionKeepsWebEndpointGate() {
    let s = quietSimulation()
    s.addThreat(kind: .mortar, position: [0, 20, 4], velocity: .zero)
    s.rounds = [
      Round(
        id: 1, position: [0, 20, 0], velocity: [0, 0, 8], firedBy: .classic, origin: [0, 20, 0],
        previousPosition: [0, 20, 0], orientation: simd_quatd())
    ]
    s.updateRounds(steps: 1)
    XCTAssertEqual(
      s.threats[0].health, 2, "A swept-only replacement would incorrectly hit this target")
    s.threats[0].position = [0, 19.98, 15]
    s.updateRounds(steps: 1)
    XCTAssertEqual(s.threats[0].health, 1)
    XCTAssertTrue(s.rounds.isEmpty)
  }
  func testFirstFrameRampAndOneSpawnPerFrame() {
    let s = Simulation(seed: 14, holiday: nil, createFleet: false)
    s.automaticFire = false
    s.advance(realDelta: 1 / 60)
    XCTAssertEqual(s.wave, 2)
    XCTAssertEqual(s.threats.count, 1)
    XCTAssertEqual(s.spawnCooldown, 120)
    s.advance(realDelta: 5)
    XCTAssertEqual(s.threats.count, 2)
  }
  func testFriendlyPriorityOnEqualETAAndGameOver() {
    let s = quietSimulation(fleet: true)
    let own = s.addThreat(
      kind: .mortar, position: [100, 100, 0], velocity: [-1, 0, 0],
      target: .init(position: [0, 100, 0]))
    let ally = s.addThreat(
      kind: .mortar, position: [100, 100, 0], velocity: [-1, 0, 0],
      target: .init(position: [0, 100, 0], friendlyID: 0))
    s.advance(realDelta: 1 / 60)
    XCTAssertEqual(s.targetID, ally)
    XCTAssertNotEqual(s.targetID, own)
    for i in 0..<5 { s.destroyFriendly(i) }
    XCTAssertEqual(s.gameOverReason, .friendlies)
  }
  func testZenHealthAndReplacementLifecycle() {
    let s = quietSimulation(fleet: true)
    s.setZen(true)
    s.addThreat(kind: .mortar, position: [0, 6, 0], velocity: .zero)
    s.advance(realDelta: 1 / 60)
    XCTAssertEqual(s.health, 100)
    let name = s.friendlies[0].key
    s.destroyFriendly(0)
    s.updateWrecks(dt: 115)
    XCTAssertTrue(s.friendlies[0].alive)
    XCTAssertNotNil(s.friendlies[0].arriving)
    XCTAssertNotEqual(s.friendlies[0].key, name)
    XCTAssertFalse(s.friendlies[0].onStation)
    for _ in 0..<2000 { s.updateArrivals(steps: 1) }
    XCTAssertTrue(s.friendlies[0].onStation)
    XCTAssertFalse(s.isGameOver)
    s.setZen(false)
    XCTAssertEqual(s.wave, 3)
  }
  func testVLSHatchLeadCostAndFlight() {
    let s = quietSimulation()
    XCTAssertTrue(s.launchVLS(.ship, bearing: 90))
    XCTAssertEqual(s.longRun.cost, 2.1e6)
    s.updateVLS(dt: 0.79)
    XCTAssertTrue(s.launches.isEmpty)
    s.updateVLS(dt: 0.02)
    XCTAssertEqual(s.launches.count, 1)
    s.updateVLS(dt: 2)
    XCTAssertGreaterThan(s.launches[0].direction.x, 0.5)
    s.updateVLS(dt: 7)
    XCTAssertTrue(s.launches.isEmpty)
  }
  func testLongRunUsesRealTimeAndSurvivesSlowMode() {
    let s = quietSimulation()
    s.timeScale = 0.1
    s.advance(realDelta: 10)
    XCTAssertEqual(s.longRun.played, 10)
    XCTAssertEqual(s.elapsed, 1)
    s.isPaused = true
    s.advance(realDelta: 4)
    XCTAssertEqual(s.longRun.played, 10)
    s.longRun.cost = 1e8
    s.updateLongRun(1)
    XCTAssertEqual(s.longRun.milestone, 1)
    s.updateLongRun(1)
    XCTAssertEqual(s.longRun.milestone, 2)
    s.longRun.kills = 21347
    XCTAssertEqual(s.longRun.killStars, 21)
    XCTAssertEqual(s.longRun.killMarks, 3)
  }
  func testHelicopterTrackingNeverFiresAndSightingsEnd() {
    let s = quietSimulation()
    s.automaticFire = true
    s.startSighting(.flyby)
    s.sightings[0].position = [30, 22, -50]
    s.sightings[0].near = true
    s.advance(realDelta: 1 / 60)
    XCTAssertFalse(s.isFiring)
    XCTAssertTrue(s.sightings[0].scolded)
    s.updateSightings(dt: 40)
    XCTAssertTrue(s.sightings.isEmpty)
    for kind in SightingKind.allCases { s.startSighting(kind) }
    XCTAssertEqual(s.sightings.count, 7)
    for _ in 0..<300 { s.updateSightings(dt: 1) }
    XCTAssertTrue(s.sightings.isEmpty)
  }
  func testVoiceKillCooldownAndAsyncLoadRetention() {
    let v = VoiceScheduler(random: GameRandom(seed: 4))
    v.advanceClock(1)
    for _ in 0..<30 { v.announceKill(kind: .drone, distance: 500) }
    XCTAssertFalse(v.takeOutput().contains { $0.bucket == "kill" })
    for _ in 0..<30 { v.announceKill(kind: .ascm, distance: 500) }
    XCTAssertLessThanOrEqual(v.takeOutput().filter { $0.bucket == "kill" }.count, 1)
    let lazy = VoiceScheduler(random: GameRandom(seed: 4), allClipsReady: false)
    lazy.advanceClock(1)
    lazy.play("pa-watch")
    XCTAssertFalse(lazy.loadRequests.isEmpty)
    for clip in lazy.loadRequests { lazy.supplyClip(clip, duration: 3) }
    XCTAssertEqual(lazy.takeOutput().filter { $0.bucket == "pa-watch" }.count, 1)
  }
  func testFleetNamesAndPlacementConstraints() {
    for seed in 1...15 {
      let s = Simulation(seed: UInt64(seed), holiday: nil)
      XCTAssertEqual(Set(s.friendlies.map(\.key)).count, 5)
      for f in s.friendlies {
        XCTAssertFalse(GameRules.nearShip(f.position, margin: 15))
        XCTAssertTrue(f.onStation)
      }
    }
  }
  func testReplayHoldoutAndPersistence() {
    let n = NeuralController(random: GameRandom(seed: 5))
    for _ in 0..<10 { n.rememberLiveSample(inputs: [1, 0, 0, 0, 0, 1, -1], targets: [0, 0, 1]) }
    XCTAssertEqual(n.liveReplay.count, 8)
    XCTAssertEqual(n.liveValidation.count, 2)
    n.trainFromLiveReplay(milliseconds: 1000)
    var saved: Data?
    n.onSave = { saved = $0 }
    n.save(milliseconds: 2000)
    let loaded = NeuralController(random: GameRandom(seed: 6))
    XCTAssertTrue(loaded.load(saved!))
    XCTAssertEqual(loaded.weights, n.weights)
    XCTAssertTrue(loaded.isTrained)
  }
}

extension SimulationTests {
  func testVoiceSchedulingMatchesJavaScript() throws {
    let url = Bundle.module.url(forResource: "voice-reference", withExtension: "json")!
    let r = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
    let v = VoiceScheduler(random: GameRandom(seed: 0, tape: r["tape"] as! [Double]))
    for a in r["actions"] as! [[String: Any]] {
      v.advanceClock((a["at"] as! Double) - v.now)
      let p = a["params"] as! [String: Any]
      v.play(
        a["bucket"] as! String,
        params: VoiceParameters(
          ship: p["ship"] as? String ?? "", side: p["side"] as? String ?? "",
          bearing: p["bearing"] as? String ?? "", named: p["named"] as? Bool ?? false,
          damageSide: p["side"] as? Double ?? 0, frame: p["frame"] as? Double ?? 0,
          missile: p["missile"] as? Bool ?? false))
    }
    let result = v.takeOutput()
    let expected = r["output"] as! [[String: Any]]
    XCTAssertEqual(result.count, expected.count)
    for (actual, e) in zip(result, expected) {
      XCTAssertEqual(actual.clip, e["clip"] as! String)
      XCTAssertEqual(actual.channel, e["channel"] as! String)
      XCTAssertEqual(actual.start, e["start"] as! Double, accuracy: 1e-10)
      XCTAssertEqual(actual.end, e["end"] as! Double, accuracy: 1e-10)
    }
  }
}

extension SimulationTests {
  func testChatterLotteriesMatchOriginalRandomComparator() throws {
    let r =
      try JSONSerialization.jsonObject(
        with: Data(
          contentsOf: Bundle.module.url(forResource: "lottery-reference", withExtension: "json")!))
      as! [String: Any]
    let random = GameRandom(seed: 0, tape: r["tape"] as! [Double])
    for expected in r["lotteries"] as! [[Int]] {
      XCTAssertEqual(random.randomizedLots(Array(0..<expected.count)), expected)
    }
  }
  func testMuzzleUsesLastRenderedPositionDuringFire() {
    let s = quietSimulation()
    s.yaw = 0
    s.pitch = 0
    let before = s.muzzlePosition
    s.frameMuzzle = before
    s.yaw = 0.1
    s.shoot()
    equal(s.rounds[0].position, before)
    XCTAssertGreaterThan(s.rounds[0].velocity.x, 0.7)
  }
  func testSustainedZenBattleAndTrainingRemainFinite() {
    let s = Simulation(seed: 194, holiday: nil)
    s.setZen(true)
    s.voices.isMuted = true
    for frame in 0..<7200 {
      if frame == 180 { s.neural.isTraining = true }
      if frame == 360 {
        s.neural.isTraining = false
        s.controllerMode = .neural
      }
      if frame == 600 { s.controllerMode = .classic }
      s.advance(realDelta: 1 / 60)
      _ = s.effects.takeSounds()
      _ = s.voices.takeOutput()
      XCTAssertTrue(s.muzzlePosition.x.isFinite && s.muzzlePosition.y.isFinite)
    }
    XCTAssertFalse(s.isGameOver)
    XCTAssertGreaterThan(s.roundsFired, 100)
    XCTAssertGreaterThan(s.kills, 0)
    XCTAssertGreaterThan(s.neural.trainSteps, 0)
    XCTAssertLessThan(s.rounds.count, 61)
    XCTAssertEqual(s.wave, 7)
    XCTAssertEqual(s.health, 100)
  }
}

extension SimulationTests {
  func testUntrainedNeuralSelectionFallsBackToClassic() {
    let s = Simulation(seed: 12)
    s.setController(.neural)
    XCTAssertEqual(s.controllerMode, .classic)
    s.neural.rememberLiveSample(inputs: [1, 0, 0, 0, 0, 1, -1], targets: [0, 0, 1])
    s.neural.trainFromLiveReplay(milliseconds: 100, wallMilliseconds: 1_000_000)
    s.setController(.neural)
    XCTAssertEqual(s.controllerMode, .neural)
  }

  func testNeuralAutosaveUsesWallClockAcrossSessionRestart() {
    let n = NeuralController(random: GameRandom(seed: 5))
    n.rememberLiveSample(inputs: [1, 0, 0, 0, 0, 1, -1], targets: [0, 0, 1])
    n.trainFromLiveReplay(milliseconds: 10_000, wallMilliseconds: 1_000_000)
    var data: Data?
    n.onSave = { data = $0 }
    n.save(milliseconds: 1_000_000)
    let restored = NeuralController(random: GameRandom(seed: 6))
    XCTAssertTrue(restored.load(data!))
    restored.rememberLiveSample(inputs: [1, 0, 0, 0, 0, 1, -1], targets: [0, 0, 1])
    var saves = 0
    restored.onSave = { _ in saves += 1 }
    restored.trainFromLiveReplay(milliseconds: 100, wallMilliseconds: 1_014_999)
    XCTAssertEqual(saves, 0)
    restored.trainFromLiveReplay(milliseconds: 200, wallMilliseconds: 1_015_001)
    XCTAssertEqual(saves, 1)
  }
}
