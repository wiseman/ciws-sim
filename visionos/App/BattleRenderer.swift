import CIWSSimulation
import RealityKit
import SwiftUI
import UIKit
import simd

@MainActor final class BattleRenderer {
  let root = Entity()
  private let model: BattleModel, presentation: BattlePresentation
  private let mountYaw: Entity, mountPitch: Entity, barrels: Entity, flash: Entity
  private let marker = Entity()
  private var subscription: EventSubscription?
  private var shownMarks = -1
  private var entities: [String: Entity] = [:], fleetNames: [Int: String] = [:]
  private let assets: WebVisualAssets
  private let ship: Entity
  private let ocean: ModelEntity
  private let audio: BattleAudio
  private var generation: Int, stopped = false, audioReady = false
  init(model: BattleModel, presentation: BattlePresentation) async throws {
    self.model = model
    self.presentation = presentation
    generation = model.generation
    assets = try await WebVisualAssets(immersive: presentation == .deck)
    ocean = SceneGeometry.environment(
      parent: root, immersive: presentation == .deck, assets: assets)
    ship = assets.model("ship")
    root.addChild(ship)
    let mount = assets.model("mount")
    root.addChild(mount)
    mountYaw = mount.findEntity(named: "mount-yaw")!
    mountPitch = mount.findEntity(named: "mount-pitch")!
    barrels = mount.findEntity(named: "barrels")!
    flash = assets.muzzle()
    flash.position = [0, 0, 5]
    mountPitch.addChild(flash)
    for x: Float in [-5, 5] {
      _ = SceneGeometry.box([0.35, 3, 0.35], [x, 0, 0], .systemMint, parent: marker, unlit: true)
    }
    _ = SceneGeometry.box([10, 0.35, 0.35], [0, 1.5, 0], .systemMint, parent: marker, unlit: true)
    root.addChild(marker)
    marker.isEnabled = false
    audio = BattleAudio(root: root, immersive: presentation == .deck)
    if presentation == .deck {
      // Same station and facing as XR_STATION; only the system moves the tracked head.
      let q = simd_quatf(angle: -atan2(4.5, 5.5), axis: [0, 1, 0])
      root.orientation = q
      root.position = -q.act([4.5, 4, 3.5])
    } else {
      assets.inkScale = 0.4  // the web's outlines are heavy on a miniature
    }
  }
  func fit(in bounds: BoundingBox) {
    guard presentation == .tabletop else { return }
    root.scale = .init(
      repeating: min(bounds.extents.x / 2400, bounds.extents.z / 2400, bounds.extents.y / 650))
    // A volume's RealityView origin is its centre. The converted frame's centre isn't reliable
    // (it put the ship at the front edge), so only its size is used.
    root.position = [0, -bounds.extents.y / 2 + 0.08, 0]
    let inverseScale = 1 / root.scale.x
    if abs(assets.distanceScale - inverseScale) > 0.01 {
      assets.distanceScale = inverseScale
      assets.updateDistanceScale(root, to: inverseScale)
      try? assets.oceanMaterial.setParameter(name: "distanceScale", value: .float(inverseScale))
    }
  }
  func subscribe(_ content: RealityViewContent) {
    subscription = content.subscribe(to: SceneEvents.Update.self) { [weak self] in
      self?.update($0.deltaTime)
    }
  }
  func loadAudio() async {
    await audio.load(scheduler: model.simulation.voices)
    guard !stopped else {
      audio.stop()
      return
    }
    audioReady = true
    if !audio.failures.isEmpty {
      model.audioMessage = "Some audio could not load (\(audio.failures.count) clips)."
    }
    refreshAudio()
  }
  private var audible: Bool {
    !stopped && !model.muted && !model.paused && model.sceneActive
      && model.activePresentation == presentation && !model.simulation.isGameOver
  }
  func refreshAudio() { audio.update(enabled: audible) }
  private func entity(_ key: String, make: () -> Entity) -> Entity {
    if let e = entities[key] { return e }
    let e = make()
    entities[key] = e
    root.addChild(e)
    return e
  }
  private func color(_ rgb: UInt32) -> UIColor {
    UIColor(
      red: CGFloat((rgb >> 16) & 255) / 255, green: CGFloat((rgb >> 8) & 255) / 255,
      blue: CGFloat(rgb & 255) / 255, alpha: 1)
  }
  private func update(_ delta: Double) {
    guard !stopped, model.activePresentation == presentation else {
      audio.update(enabled: false)
      return
    }
    if generation != model.generation {
      generation = model.generation
      for e in entities.values { e.removeFromParent() }
      entities = [:]
      fleetNames = [:]
      audio.reset()
      audio.bind(model.simulation.voices)
    }
    let events = audioReady ? model.advance(delta, from: presentation) : []
    let s = model.simulation
    try? assets.oceanMaterial.setParameter(name: "time", value: .float(Float(s.elapsed)))
    ocean.model?.materials = [assets.oceanMaterial]
    ship.findEntity(named: "ship-radar")?.orientation = simd_quatf(
      angle: Float(s.elapsed * 2.5), axis: [0, 1, 0])
    mountYaw.orientation = simd_quatf(angle: Float(s.yaw), axis: [0, 1, 0])
    mountPitch.orientation = simd_quatf(angle: Float(s.pitch), axis: [1, 0, 0])
    barrels.orientation = simd_quatf(angle: Float(s.barrelAngle), axis: [0, 0, 1])
    flash.isEnabled = s.isFiring && !model.paused
    if flash.isEnabled { assets.updateMuzzle(flash, barrelAngle: s.barrelAngle, time: s.elapsed) }
    let marks = s.longRun.kills / 100
    if shownMarks != marks, let radome = mountPitch.findEntity(named: "radome") {
      shownMarks = marks
      for e in radome.children where e.name == "kill-mark" { e.removeFromParent() }
      for (name, count, y) in [
        ("killMark", s.longRun.killMarks, Float(2)), ("killStar", s.longRun.killStars, Float(2.48)),
      ] {
        for i in 0..<count {
          let a = Float.pi + (Float(i) - Float(count - 1) / 2) * 0.19
          let mark = assets.model(name)
          mark.name = "kill-mark"
          mark.position = [sin(a) * 0.972, y, cos(a) * 0.972]
          mark.orientation = simd_quatf(angle: a, axis: [0, 1, 0])
          radome.addChild(mark)
        }
      }
    }
    var live = Set<String>()
    func track(_ key: String, make: () -> Entity) -> Entity {
      live.insert(key)
      return entity(key, make: make)
    }
    for t in s.threats {
      let e = track("threat-\(t.id)") {
        assets.model(
          t.kind == .drone
            ? (s.holiday == .halloween ? "witch" : "drone")
            : t.kind == .mortar ? (s.holiday == .halloween ? "pumpkin" : "mortar") : "ascm")
      }
      e.position = t.position.float
      e.orientation = simd_quatf(real: Float(t.orientation.real), imag: t.orientation.imag.float)
      e.findEntity(named: "prop")?.orientation = simd_quatf(
        angle: Float(t.propAngle), axis: [0, 0, 1])
    }
    for r in s.rounds {
      let e = track("round-\(r.id)") { assets.model("tracer") }
      e.position = r.position.float
      e.orientation = simd_quatf(from: [0, 0, 1], to: r.velocity.normalized.float)
    }
    for f in s.friendlies where f.alive {
      let key = "friendly-\(f.id)-\(f.key)"
      let e = track(key) { assets.model("friendly-\(f.key)") }
      e.position = f.position.float
      e.orientation = simd_quatf(angle: Float(f.heading), axis: [0, 1, 0])
      if f.wakeStrength > 0 {
        let wake = track("wake-\(f.id)-\(f.key)") { assets.model("wake") } as! ModelEntity
        wake.position = (f.position + Vector3(0, -2.2, -22.96).rotatedY(f.heading)).float
        wake.orientation = e.orientation
        var paint = assets.effects["Wake"]!
        try? paint.setParameter(name: "scroll", value: .float(Float(f.wakeScroll)))
        try? paint.setParameter(name: "strength", value: .float(Float(f.wakeStrength)))
        wake.model?.materials = [paint]
      }
      e.findEntity(named: "friendly-radar")?.orientation = simd_quatf(
        angle: Float(f.radarAngle), axis: [0, 1, 0])
      for (j, c) in f.cells.enumerated() {
        e.findEntity(named: "hatch-\(j)")?.orientation = simd_quatf(
          angle: Float(c.lidAngle), axis: [0, 0, 1])
      }
    }
    for w in s.wrecks {
      let e = track("wreck-\(w.slot)-\(w.key)") { assets.model("wreck-\(w.key)") }
      e.position = w.position.float
      e.orientation =
        simd_quatf(angle: Float(w.heading), axis: [0, 1, 0])
        * simd_quatf(angle: Float(w.roll), axis: [0, 0, 1])
      e.findEntity(named: "wreck-bow")?.orientation = simd_quatf(
        angle: Float(w.bowPitch), axis: [1, 0, 0])
      e.findEntity(named: "wreck-stern")?.orientation = simd_quatf(
        angle: Float(w.sternPitch), axis: [1, 0, 0])
    }
    for (i, c) in s.shipCells.enumerated() {
      ship.findEntity(named: "hatch-\(i)")?.orientation = simd_quatf(
        angle: Float(c.lidAngle), axis: [0, 0, 1])
    }
    for l in s.launches {
      let e = track("launch-\(l.id)") { assets.model("vlsMissile") }
      e.position = l.position.float
      e.scale = .init(repeating: Float(l.scale))
      e.orientation = simd_quatf(from: [0, 0, 1], to: l.direction.float)
    }
    for p in s.effects.puffs {
      let e = track("puff-\(p.id)") { assets.puff() } as! ModelEntity
      e.isEnabled = p.delay <= 0
      assets.updatePuff(e, state: p)
    }
    for p in s.effects.sparks {
      let e = track("spark-\(p.id)") { assets.model("spark") }
      e.position = p.position.float
      e.scale = [Float(p.width), Float(p.width), Float(p.length)]
      e.orientation = simd_quatf(from: [0, 0, 1], to: p.velocity.normalized.float)
      e.components.set(OpacityComponent(opacity: Float(max(0, 1 - p.age / p.life))))
    }
    for d in s.effects.debris {
      let e = track("debris-\(d.id)") { assets.model(d.pumpkin ? "pumpkinDebris" : "debris") }
      e.position = d.position.float
      e.scale = .init(repeating: Float(d.size * min(1, (d.life - d.age) / 0.15)))
      e.orientation =
        simd_quatf(angle: Float(d.rotation.x), axis: [1, 0, 0])
        * simd_quatf(angle: Float(d.rotation.z), axis: [0, 0, 1])
    }
    for r in s.effects.rings {
      let e =
        track("ring-\(r.id)") { assets.billboard("Ring", facingCamera: !r.foam) } as! ModelEntity
      assets.ring(e, state: r)
    }
    for (owner, points) in Dictionary(grouping: s.effects.trails, by: \.owner)
    where points.count > 1 {
      let e = track("trail-\(owner)") { ModelEntity() } as! ModelEntity
      assets.updateTrail(e, points: points)
    }
    for p in s.effects.plumes {
      let e = track("plume-\(p.id)") { assets.billboard("Plume") } as! ModelEntity
      assets.updatePlume(e, state: p)
    }
    for sight in s.sightings {
      if sight.kind == .dolphins {
        for (i, d) in sight.pod.enumerated() {
          let e = track("pod-\(sight.id)-\(i)") { assets.model("dolphins") }
          e.position = d.position.float
          e.isEnabled = d.visible
          e.orientation = simd_quatf(angle: Float(d.pitch), axis: [1, 0, 0])
        }
      } else {
        let e = track("sight-\(sight.id)") { assets.model(sight.kind.rawValue) }
        e.position = sight.position.float
        if sight.kind == .whale { e.position.y += Float(9 * cos(sight.pitch)) }
        e.orientation =
          simd_quatf(angle: Float(sight.yaw), axis: [0, 1, 0])
          * simd_quatf(angle: Float(sight.pitch), axis: [1, 0, 0])
          * simd_quatf(angle: Float(sight.roll), axis: [0, 0, 1])
        e.findEntity(named: "rotor")?.orientation = simd_quatf(
          angle: Float(sight.rotor), axis: [0, 1, 0])
        e.findEntity(named: "tailRotor")?.orientation = simd_quatf(
          angle: Float(sight.tailRotor), axis: [1, 0, 0])
        for i in 0..<2 {
          e.findEntity(named: "wing-\(i)")?.orientation = simd_quatf(
            angle: Float(sight.wing) * (i == 0 ? 1 : -1), axis: [0, 0, 1])
        }
      }
    }
    for key in Array(entities.keys) where !live.contains(key) {
      entities.removeValue(forKey: key)?.removeFromParent()
    }
    if let target = s.threats.first(where: { $0.id == s.targetID }) {
      marker.position = target.position.float + [0, 9, 0]
      marker.isEnabled = true
    } else {
      marker.isEnabled = false
    }
    refreshAudio()
    audio.advance(simulation: s, events: events)
  }
  func stop() {
    stopped = true
    subscription?.cancel()
    subscription = nil
    audio.stop()
  }
}
