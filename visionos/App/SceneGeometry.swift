import CIWSSimulation
import RealityKit
import UIKit
import simd

@MainActor
enum SceneGeometry {
  static let hullColor = UIColor(red: 0.36, green: 0.43, blue: 0.48, alpha: 1)
  static let gray = UIColor(red: 0.65, green: 0.70, blue: 0.71, alpha: 1)
  static let dark = UIColor(red: 0.10, green: 0.15, blue: 0.18, alpha: 1)

  static func box(
    _ size: SIMD3<Float>, _ position: SIMD3<Float>, _ color: UIColor,
    parent: Entity, unlit: Bool = false
  ) -> ModelEntity {
    let mesh = MeshResource.generateBox(size: size)
    let entity = ModelEntity(mesh: mesh, materials: [material(color, unlit: unlit)])
    entity.position = position
    parent.addChild(entity)
    return entity
  }

  static func material(_ color: UIColor, unlit: Bool = false) -> any Material {
    if unlit { return UnlitMaterial(color: color) }
    return SimpleMaterial(color: color, roughness: 0.75, isMetallic: false)
  }

  @discardableResult
  static func cylinder(
    radius: Float, height: Float, at position: SIMD3<Float>,
    color: UIColor, parent: Entity
  ) -> ModelEntity {
    let entity = ModelEntity(
      mesh: .generateCylinder(height: height, radius: radius),
      materials: [material(color)])
    entity.position = position
    parent.addChild(entity)
    return entity
  }

  static func environment(parent: Entity, immersive: Bool, assets: WebVisualAssets) -> ModelEntity {
    let ocean = ModelEntity(
      mesh: .generatePlane(width: 8000, depth: 8000), materials: [assets.oceanMaterial])
    ocean.position.y = -1.5
    parent.addChild(ocean)
    let environment = assets.model("environment")
    parent.addChild(environment)
    if !immersive {
      // From above, the clouds (groups of puffs) would hang between the viewer and the action
      for cloud in environment.children where !(cloud is ModelEntity) { cloud.isEnabled = false }
    }
    if immersive {
      var skyMaterial = assets.skyMaterial
      skyMaterial.faceCulling = .none
      skyMaterial.writesDepth = true
      let sky = ModelEntity(mesh: .generateSphere(radius: 3000), materials: [skyMaterial])
      parent.addChild(sky)
    }
    return ocean
  }
}
