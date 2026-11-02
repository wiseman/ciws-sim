import CIWSSimulation
import RealityKit
import UIKit
import simd

@MainActor extension WebVisualAssets {
  func puff() -> ModelEntity {
    let e = model("puff") as! ModelEntity
    e.model?.materials = [effects["Puff"]!]
    let outline = ModelEntity(mesh: e.model!.mesh, materials: [effects["PuffInk"]!])
    outline.name = "puff-ink"
    e.addChild(outline)
    return e
  }
  func updatePuff(_ e: ModelEntity, state p: Puff) {
    e.position = p.position.float
    e.scale = .init(repeating: Float(p.scale))
    e.orientation =
      simd_quatf(angle: Float(p.rotation.x), axis: [1, 0, 0])
      * simd_quatf(angle: Float(p.rotation.y + p.age * p.spin), axis: [0, 1, 0])
      * simd_quatf(angle: Float(p.rotation.z), axis: [0, 0, 1])
    for (entity, name) in [
      (e, "Puff"), (e.findEntity(named: "puff-ink") as! ModelEntity, "PuffInk"),
    ] {
      var m = effects[name]!
      try? m.setParameter(name: "heat", value: .float(Float(p.heat)))
      try? m.setParameter(name: "dissolve", value: .float(Float(p.dissolve)))
      try? m.setParameter(name: "seed", value: .float(Float(p.seed)))
      try? m.setParameter(name: "boil", value: .float(Float(p.age * 0.35)))
      if name == "Puff" {
        try? m.setParameter(name: "smoke", value: .color(Self.sRGB(p.smoke)))
      } else {
        // Scales the outline only; the puff's haze stays in real metres
        try? m.setParameter(name: "distanceScale", value: .float(distanceScale))
        try? m.setParameter(name: "thickness", value: .float(0.003 * inkScale / max(0.001, Float(p.scale))))
      }
      entity.model?.materials = [m]
    }
  }
  static func sRGB(_ rgb: UInt32) -> CGColor {
    UIColor(
      red: CGFloat((rgb >> 16) & 255) / 255, green: CGFloat((rgb >> 8) & 255) / 255,
      blue: CGFloat(rgb & 255) / 255, alpha: 1
    ).cgColor
  }
  func billboard(_ material: String, facingCamera: Bool = true) -> ModelEntity {
    let e = model("billboard") as! ModelEntity
    e.model?.materials = [effects[material]!]
    if facingCamera { e.components.set(BillboardComponent()) }
    return e
  }
  func ring(_ e: ModelEntity, state r: EffectRing) {
    e.position = r.position.float
    e.scale = .init(repeating: Float(r.size))
    if r.foam { e.orientation = simd_quatf(angle: -.pi / 2, axis: [1, 0, 0]) }
    var m = effects["Ring"]!
    try? m.setParameter(name: "age", value: .float(Float(r.age / r.life)))
    try? m.setParameter(name: "seed", value: .float(Float(r.id % 63) / 10))
    try? m.setParameter(name: "color", value: .color(Self.sRGB(r.foam ? 0xd5e9f0 : 0xffe7ba)))
    e.model?.materials = [m]
  }
  func muzzle() -> Entity {
    let e = Entity()
    let star = billboard("Flash")
    star.name = "star"
    e.addChild(star)
    for i in 0..<3 {
      let jet = billboard("MuzzleJet", facingCamera: false)
      jet.name = "jet-\(i)"
      jet.position.z = 0.8
      jet.orientation =
        simd_quatf(angle: Float(i) * .pi / 3, axis: [0, 0, 1])
        * simd_quatf(angle: .pi / 2, axis: [1, 0, 0])
      jet.scale = [0.3, 0.8, 1]
      e.addChild(jet)
    }
    return e
  }
  func updateMuzzle(_ e: Entity, barrelAngle: Double, time: Double) {
    let a = barrelAngle + ((.pi / 2 - barrelAngle) / (.pi / 3)).rounded() * (.pi / 3)
    e.position = [Float(cos(a) * 0.2), Float(sin(a) * 0.2), 5]
    let seed = Float(time * 7919).truncatingRemainder(dividingBy: 6.3)
    let size = 0.5 + abs(sin(seed * 13.7)) * 0.7
    e.scale = .init(repeating: size)
    for child in e.children {
      guard let m = child as? ModelEntity else { continue }
      var material = effects[child.name == "star" ? "Flash" : "MuzzleJet"]!
      try? material.setParameter(name: "seed", value: .float(seed))
      m.model?.materials = [material]
    }
  }
}

@MainActor extension WebVisualAssets {
  func updateTrail(_ entity: ModelEntity, points: [TrailPoint]) {
    var positions: [SIMD3<Float>] = []
    var tangents: [SIMD3<Float>] = []
    var uvs: [SIMD2<Float>] = []
    var indices: [UInt32] = []
    for i in points.indices {
      let p = points[i]
      let age = Float(min(1, p.age / p.life))
      let direction =
        (points[min(i + 1, points.count - 1)].position - points[max(i - 1, 0)].position).normalized
        .float
      positions += [p.position.float, p.position.float]
      tangents += [direction, direction]
      uvs += [[-1, age], [1, age]]
      if i > 0 {
        let j = UInt32(i * 2)
        indices += [j - 2, j - 1, j, j, j - 1, j + 1]
      }
    }
    var desc = MeshDescriptor(name: "Web smoke ribbon")
    desc.positions = .init(positions)
    desc.normals = .init(Array(repeating: SIMD3<Float>(0, 1, 0), count: positions.count))
    desc.tangents = .init(tangents)
    desc.textureCoordinates = .init(uvs)
    desc.primitives = .triangles(indices)
    guard let mesh = try? MeshResource.generate(from: [desc]) else { return }
    var material = effects["Trail"]!
    try? material.setParameter(name: "width", value: .float(Float(points[0].width) / distanceScale))
    try? material.setParameter(name: "seed", value: .float(Float(points[0].owner % 100)))
    entity.model = ModelComponent(mesh: mesh, materials: [material])
  }
}

@MainActor extension WebVisualAssets {
  func updatePlume(_ e: ModelEntity, state p: WaterPlume) {
    let t = p.age / p.life
    let rise = 1 - pow(1 - min(t / 0.22, 1), 3)
    let k = max(0, min(1, (t - 0.45) / 0.55))
    let height = p.height * rise * (1 - 0.55 * k * k * (3 - 2 * k))
    e.position = p.position.float + [0, Float(height / 2), 0]
    e.scale = [Float(p.width * (0.6 + 0.7 * t) / 2), Float(height / 2), 1]
    var m = effects["Plume"]!
    try? m.setParameter(name: "seed", value: .float(Float(p.seed)))
    try? m.setParameter(name: "age", value: .float(Float(t)))
    e.model?.materials = [m]
  }
}
