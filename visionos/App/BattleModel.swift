import CIWSSimulation
import Foundation
import Observation

enum BattlePresentation { case deck, tabletop }
struct BattleStatus {
  var health = 100, kills = 0, wave = 1, rounds = 0, contacts = 0, afloat = 5, highScore = 0,
    trainingSteps = 0, samples = 0
  var elapsed = 0.0, cost = 0.0, loss = Double.nan, aimError = Double.nan, agreement = Double.nan
  var target = "Searching", firing = false, gameOver = false
  var radar: [Threat] = []
  var friendlies: [Friendly] = []
}
@MainActor @Observable final class BattleModel {
  @ObservationIgnored var simulation: Simulation
  @ObservationIgnored private var publicationTime = 0.0
  @ObservationIgnored private var savedZen = false
  var status = BattleStatus()
  var paused = false
  var slowMotion = false
  var holdFire = false
  var muted = ProcessInfo.processInfo.arguments.contains("--mute")
  var deckOpen = false
  var tabletopOpen = false
  /// Set by the station panel; a tabletop the system restores from a previous launch closes itself
  @ObservationIgnored var tabletopRequested = false
  var transitioning = false
  var sceneActive = true
  var message = "Ready to take the watch."
  var audioMessage: String?
  var generation = 0
  var controller: ControllerMode = .classic {
    didSet {
      simulation.setController(controller)
      if controller != simulation.controllerMode { controller = simulation.controllerMode }
      UserDefaults.standard.set(controller.rawValue, forKey: "ciwsControllerMode")
    }
  }
  var training = false {
    didSet {
      if oldValue && !training {
        simulation.neural.save(milliseconds: Date().timeIntervalSince1970 * 1000)
      }
    }
  }
  var resetArmed = false
  @ObservationIgnored private var resetDeadline = Date.distantPast
  var zen = false
  init() {
    simulation = Simulation(voiceClipsReady: false)
    restorePersistentState()
    publish()
  }
  private func restorePersistentState() {
    simulation.highScore = UserDefaults.standard.integer(forKey: "ciwsHighScore")
    if let data = UserDefaults.standard.data(forKey: "ciwsNeuralControllerV8") {
      simulation.neural.load(data)
    }
    controller =
      ControllerMode(
        rawValue: UserDefaults.standard.string(forKey: "ciwsControllerMode") ?? "classic")
      ?? .classic
    simulation.setController(controller)
    controller = simulation.controllerMode
    simulation.onHighScore = { UserDefaults.standard.set($0, forKey: "ciwsHighScore") }
    simulation.neural.onSave = { UserDefaults.standard.set($0, forKey: "ciwsNeuralControllerV8") }
  }
  var activePresentation: BattlePresentation? { deckOpen ? .deck : tabletopOpen ? .tabletop : nil }
  func enterDeck() {
    savedZen = zen
    zen = true
    simulation.setZen(true)
  }
  func leaveDeck() {
    zen = savedZen
    simulation.setZen(zen)
  }
  func advance(_ delta: Double, from presentation: BattlePresentation) -> [SimulationEvent] {
    guard presentation == activePresentation, sceneActive else { return [] }
    simulation.isPaused = paused
    simulation.timeScale = slowMotion ? 0.1 : 1
    simulation.automaticFire = !holdFire
    simulation.voices.isMuted = muted
    simulation.setController(controller)
    simulation.neural.isTraining = training
    simulation.setZen(zen)
    simulation.advance(realDelta: delta)
    for event in simulation.events {
      switch event {
      case .contact(let kind): message = "New contact · \(kind.name)"
      case .destroyed: message = "Threat neutralized."
      case .impact: message = "Impact! Damage control responding."
      case .wave(let n): message = "Wave \(n) · Incoming raid"
      case .friendlyLost(let id): message = "\(simulation.friendlies[id].name) hit."
      case .sighting(let kind): message = "\(kind.capitalized) sighted."
      case .launch: message = "Missile away."
      case .chirp, .passBy: break
      }
    }
    publicationTime += delta
    if publicationTime >= 0.1 || simulation.isGameOver {
      publicationTime = 0
      publish()
    }
    return simulation.events
  }
  func restart() {
    simulation.neural.save(milliseconds: Date().timeIntervalSince1970 * 1000)
    training = false
    let longRun = simulation.longRun
    simulation.voices.stop()
    simulation = Simulation(voiceClipsReady: false)
    simulation.longRun = longRun
    restorePersistentState()
    simulation.setZen(zen)
    paused = false
    publicationTime = 0
    generation += 1
    message = "New watch. All stations ready."
    publish()
  }
  func resetLearning() {
    if Date() > resetDeadline {
      resetDeadline = Date().addingTimeInterval(3)
      resetArmed = true
      Task { [weak self] in
        try? await Task.sleep(for: .seconds(3.05))
        if let self, Date() >= self.resetDeadline { self.resetArmed = false }
      }
      return
    }
    resetArmed = false
    resetDeadline = .distantPast
    simulation.resetNeuralController()
    UserDefaults.standard.removeObject(forKey: "ciwsNeuralControllerV8")
    controller = .classic
    training = false
    publish()
  }
  func sendRaid() {
    simulation.sendRaid()
    message = "Additional raid inbound."
    publish()
  }
  private func publish() {
    let n = simulation.neural
    status = BattleStatus(
      health: simulation.health, kills: simulation.kills, wave: simulation.wave,
      rounds: simulation.roundsFired,
      contacts: simulation.threats.count, afloat: simulation.friendlies.filter(\.alive).count,
      highScore: simulation.highScore,
      trainingSteps: n.trainSteps, samples: n.observedSamples, elapsed: simulation.elapsed,
      cost: simulation.longRun.cost,
      loss: n.lossEma, aimError: n.aimErrEma, agreement: n.fireAgreeEma,
      target: simulation.threats.first { $0.id == simulation.targetID }?.kind.name ?? "Searching",
      firing: simulation.isFiring, gameOver: simulation.isGameOver, radar: simulation.threats,
      friendlies: simulation.friendlies)
  }
}
