import Foundation

/// The web game's sound rules (AudioController in index.html), apart from the panning: RealityKit
/// places each source and tracks the head itself. Levels, distances, Doppler and air absorption
/// are taken at the deck station, as the web's VR listener hears them, under its default
/// EXTREME spatial profile.
public enum SoundRules {
  public static let speedOfSound = 343.0
  /// XR_STATION at standing eye height, beside the mount
  public static let listener = Vector3(4.5, 5.6, 3.5)
  /// The station's facing (XR_STATION.facing), level
  public static let facing = Vector3(-4.5, 0, -5.5).normalized
  public static let mountPosition = Vector3(0, 8, 0)  // MOUNT_AUDIO_POSITION
  // SPATIAL_PROFILES.extreme
  public static let rolloff = 1.5, dopplerScale = 2.6, windSweep = 0.9, reverbFalloff = 0.6
  public static let audibleFloor = 0.006  // AUDIBLE_FLOOR
  public static let maxOneShots = 32  // MAX_ONE_SHOTS

  public static func distanceGain(_ distance: Double, reference: Double) -> Double {
    reference / (reference + rolloff * max(0, distance - reference))
  }
  /// Air absorption: distant sounds lose their highs
  public static func airCutoff(_ distance: Double) -> Double { max(350, 18000 * exp(-distance / 260)) }
  /// Everything drops in pitch in slow motion
  public static func slowPitch(_ timeScale: Double) -> Double { 0.45 + 0.55 * timeScale }
  /// Pitch factor for a source closing on the listener at `speed` units/s, exaggerated by the profile
  public static func doppler(closingSpeed speed: Double) -> Double {
    clamp(speedOfSound / max(60, speedOfSound - speed * dopplerScale), 0.45, 2.4)
  }
  /// GUN_FATIGUE: full level for 10 s of play, then easing to `floor` by 120 s
  public static func gunFatigue(_ seconds: Double, floor: Double = 0.3) -> Double {
    1 - (1 - floor) * clamp((seconds - 10) / 110, 0, 1)
  }
  /// playAt's reverb send against its direct sound, both after the reverb return (0.55)
  public static func reverbRatio(wet: Double, distance: Double, distanceGain: Double) -> Double {
    wet * 2.squareRoot() * (1 + min(1.5, distance / 250)) * pow(distanceGain, reverbFalloff) * 0.55
      / max(distanceGain, 1e-6)
  }
}

extension Simulation {
  /// isOverOpenWater: clear of our ship and the friendlies, and low enough to splash
  public func isOverOpenWater(_ p: Vector3) -> Bool {
    let halfLength = 112.0 / 2 * 0.41, halfBeam = 8.5 * 0.44
    let overFriendly = friendlies.contains { f in
      guard f.alive else { return false }
      let local = (p - f.position).rotatedY(-f.heading)
      return abs(local.z) < halfLength && abs(local.x) < halfBeam
    }
    return !GameRules.nearShip(p, margin: 1.5) && !overFriendly && p.y < 4
  }
}
