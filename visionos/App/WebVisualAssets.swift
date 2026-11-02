import Foundation
import RealityKit
import UIKit
import simd

/// Geometry and decals are exported from the actual web model builders, without approximation.
/// All animation and gameplay are Swift; the bundle contains no JavaScript runtime.
@MainActor final class WebVisualAssets {
  struct Document: Decodable {
    let format: Int
    let sourceSHA256: String
    let assets: [String: Node]
    let geometries: [Geometry]
    let materials: [Paint]
    let textures: [String]
  }
  struct Node: Decodable {
    let name: String
    let position, rotation, scale: [Float]
    let visible: Bool
    let children: [Node]
    let geometry: Int?
    let materials: [Int]?
    let faceMaterials: [Int]?
    let outline: Bool?
  }
  struct Geometry: Decodable {
    let positions, indices: [Int]
    let normals, uv: [Int]?
  }
  struct Paint: Decodable {
    let color, emissive, repeatUV, offset: [Float]
    let toon: Bool
    let side: Int
    let opacity, alphaTest: Float
    let texture: Int?
    let depthWrite: Bool
    enum CodingKeys: String, CodingKey {
      case color, emissive, toon, side, opacity, alphaTest, texture, offset, depthWrite
      case repeatUV = "repeat"
    }
  }
  private let document: Document
  private let data: Data
  private var materials: [ShaderGraphMaterial] = []
  private var meshCache: [String: MeshResource] = [:]
  private var prototypes: [String: Entity] = [:]
  var oceanMaterial: ShaderGraphMaterial
  let skyMaterial: ShaderGraphMaterial
  private var ink: ShaderGraphMaterial
  private(set) var effects: [String: ShaderGraphMaterial] = [:]
  var distanceScale: Float = 1
  static let inkThickness: Float = 0.003  // the Ink shader's default
  var inkScale: Float = 1  // outline width relative to the web's

  static func url(_ name: String) throws -> URL {
    guard let url = Bundle.main.url(forResource: name, withExtension: nil) else {
      throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: name])
    }
    return url
  }

  init(immersive: Bool) async throws {
    document = try JSONDecoder().decode(
      Document.self, from: Data(contentsOf: Self.url("web-models.json")))
    data = try Data(contentsOf: Self.url("web-meshes.bin"))
    let shaders = try Self.url("WebShaders.usda")
    let toon = try await ShaderGraphMaterial(named: "/Shaders/Toon", from: shaders)
    let basic = try await ShaderGraphMaterial(named: "/Shaders/Basic", from: shaders)
    skyMaterial = try await ShaderGraphMaterial(named: "/Shaders/Sky", from: shaders)
    oceanMaterial = try await ShaderGraphMaterial(named: "/Shaders/Ocean", from: shaders)
    ink = try await ShaderGraphMaterial(named: "/Shaders/Ink", from: shaders)
    ink.faceCulling = .front
    let white = try await TextureResource(
      contentsOf: Self.url("web-white.png"), options: .init(semantic: .color))
    var textures: [TextureResource] = []
    for name in document.textures {
      textures.append(
        try await TextureResource(contentsOf: Self.url(name), options: .init(semantic: .color)))
    }
    var sun = simd_normalize(SIMD3<Float>(-40, 90, 55))
    if immersive { sun = simd_quatf(angle: -atan2(4.5, 5.5), axis: [0, 1, 0]).act(sun) }
    for name in ["Puff", "PuffInk", "Ring", "MuzzleJet", "Flash", "Trail", "Plume", "Wake"] {
      var fx = try await ShaderGraphMaterial(named: "/Shaders/\(name)", from: shaders)
      fx.faceCulling = name == "PuffInk" ? .front : .none
      if fx.parameterNames.contains("sunDirection") {
        try fx.setParameter(name: "sunDirection", value: .simd3Float(sun))
      }
      effects[name] = fx
    }
    for paint in document.materials {
      var m = paint.toon ? toon : basic
      try m.setParameter(name: "baseColor", value: .color(Self.linearColor(paint.color)))
      try m.setParameter(
        name: "image", value: .textureResource(paint.texture.map { textures[$0] } ?? white))
      try m.setParameter(name: "uvRepeat", value: .simd2Float(.init(paint.repeatUV)))
      try m.setParameter(name: "uvOffset", value: .simd2Float(.init(paint.offset)))
      try m.setParameter(name: "opacity", value: .float(paint.opacity))
      if paint.toon {
        try m.setParameter(name: "emissive", value: .color(Self.linearColor(paint.emissive)))
        try m.setParameter(name: "sunDirection", value: .simd3Float(sun))
      }
      m.faceCulling = paint.side == 2 ? .none : paint.side == 1 ? .front : .back
      m.writesDepth = paint.depthWrite
      materials.append(m)
    }
  }

  private static func linearColor(_ values: [Float]) -> CGColor {
    CGColor(
      colorSpace: CGColorSpace(name: CGColorSpace.extendedLinearSRGB)!,
      components: values.map(CGFloat.init) + [1])!
  }
  private func floats(_ range: [Int]) -> [Float] {
    data.withUnsafeBytes { bytes in
      (0..<range[1]).map { bytes.loadUnaligned(fromByteOffset: range[0] + $0 * 4, as: Float.self) }
    }
  }
  private func integers(_ range: [Int]) -> [UInt32] {
    data.withUnsafeBytes { bytes in
      (0..<range[1]).map { bytes.loadUnaligned(fromByteOffset: range[0] + $0 * 4, as: UInt32.self) }
    }
  }
  private func mesh(_ node: Node) throws -> MeshResource {
    let index = node.geometry!
    let key = "\(index)-\(node.faceMaterials?.first ?? -1)"
    if let cached = meshCache[key] { return cached }
    let g = document.geometries[index]
    var descriptor = MeshDescriptor(name: node.name)
    let p = floats(g.positions)
    descriptor.positions = .init(
      stride(from: 0, to: p.count, by: 3).map { SIMD3(p[$0], p[$0 + 1], p[$0 + 2]) })
    if let normals = g.normals {
      let n = floats(normals)
      descriptor.normals = .init(
        stride(from: 0, to: n.count, by: 3).map { SIMD3(n[$0], n[$0 + 1], n[$0 + 2]) })
    }
    if let uv = g.uv {
      let a = floats(uv)
      // THREE's canvas textures use bottom-left UVs. RealityKit uses top-left.
      descriptor.textureCoordinates = .init(
        stride(from: 0, to: a.count, by: 2).map { SIMD2(a[$0], 1 - a[$0 + 1]) })
    }
    descriptor.primitives = .triangles(integers(g.indices))
    if let faces = node.faceMaterials { descriptor.materials = .perFace(integers(faces)) }
    let result = try MeshResource.generate(from: [descriptor])
    meshCache[key] = result
    return result
  }
  private func build(_ node: Node) throws -> Entity {
    let e: Entity
    if node.geometry != nil {
      e = ModelEntity(
        mesh: try mesh(node),
        materials: node.outline == true ? [ink] : (node.materials ?? []).map { materials[$0] })
    } else {
      e = Entity()
    }
    e.name = node.name
    e.position = .init(node.position)
    e.orientation = simd_quatf(
      ix: node.rotation[0], iy: node.rotation[1], iz: node.rotation[2], r: node.rotation[3])
    e.scale = .init(node.scale)
    e.isEnabled = node.visible
    for child in node.children { e.addChild(try build(child)) }
    return e
  }
  private func scaledClone(_ e: Entity) -> Entity {
    let clone = e.clone(recursive: true)
    if distanceScale != 1 { updateDistanceScale(clone, to: distanceScale) }
    return clone
  }
  /// Outlines keep their on-screen width at a reduced scale: the ink extrudes by eye distance times
  /// its thickness. Distance haze stays in real metres, or a tabletop at arm's length would be
  /// shaded as if it were kilometres away.
  func updateDistanceScale(_ e: Entity, to scale: Float) {
    if let m = e as? ModelEntity, var model = m.model {
      model.materials = model.materials.map { value in
        // Puff outlines also have a thickness, but updatePuff sets theirs every frame
        guard var graph = value as? ShaderGraphMaterial,
          graph.parameterNames.contains("thickness"), !graph.parameterNames.contains("dissolve")
        else { return value }
        try? graph.setParameter(name: "thickness", value: .float(Self.inkThickness * inkScale * scale))
        return graph
      }
      m.model = model
    }
    for child in e.children { updateDistanceScale(child, to: scale) }
  }
  func model(_ name: String) -> Entity {
    if let prototype = prototypes[name] { return scaledClone(prototype) }
    // Asset validation runs during development; a missing bundled model is a build defect.
    guard let node = document.assets[name] else { preconditionFailure("Missing web model \(name)") }
    do {
      let prototype = try build(node)
      prototypes[name] = prototype
      return scaledClone(prototype)
    } catch { preconditionFailure("Invalid web geometry \(name): \(error)") }
  }
}
