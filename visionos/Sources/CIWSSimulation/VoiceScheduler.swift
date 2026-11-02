import Foundation

public struct VoiceBucket: Decodable, Sendable {
  public var name: String
  public var clips: [String]
  public var channel: String
  public var urgent: Bool?
  public var keep: Bool?
  public var aside: Bool?
  public var onlyIfClear: Bool?
  public var hush: String?
  public var cooldown: Double?
  public var once: Bool?
  public var `repeat`: Double?
  public var lead: Double?
  public var jitter: Double?
  public var chance: Double?
  public var stale: Double?
  public var rank: String?
  public var then: String?
  public var thenAlways: Bool?
}
public struct VoiceParameters: Sendable {
  public var ship = ""
  public var side = ""
  public var bearing = ""
  public var named = false
  public var damageSide = 0.0
  public var frame = 0.0
  public var missile = false
  public init(
    ship: String = "", side: String = "", bearing: String = "", named: Bool = false,
    damageSide: Double = 0, frame: Double = 0, missile: Bool = false
  ) {
    self.ship = ship
    self.side = side
    self.bearing = bearing
    self.named = named
    self.damageSide = damageSide
    self.frame = frame
    self.missile = missile
  }
  func expand(_ clip: String) -> String {
    clip.replacingOccurrences(of: "{ship}", with: ship)
      .replacingOccurrences(of: "{side}", with: side).replacingOccurrences(
        of: "{bearing}", with: bearing)
  }
}
public struct VoicePlayback: Identifiable, Sendable {
  public var id: Int
  public var clip: String
  public var bucket: String
  public var channel: String
  public var start: Double
  public var duration: Double
  public var position: Vector3
  public var level: Double
  public var duck: Double
  public var end: Double { start + duration }
}

/// Swift equivalent of a JS promise returned by play/queuePA. Keeps cooldown reservations
/// and chained lines correct when a nonurgent clip is still loading on the native audio side.
public final class VoiceAttempt {
  public private(set) var resolved = false
  public private(set) var end: Double?
  private var callbacks: [(Double?) -> Void] = []
  public func then(_ callback: @escaping (Double?) -> Void) {
    if resolved { callback(end) } else { callbacks.append(callback) }
  }
  func settle(_ end: Double?) {
    guard !resolved else { return }
    resolved = true
    self.end = end
    let callbacks = self.callbacks
    self.callbacks = []
    for callback in callbacks { callback(end) }
  }
}

public final class VoiceScheduler {
  struct Catalog: Decodable { var buckets: [VoiceBucket] }
  public static var bundledBuckets: [VoiceBucket] {
    let url = Bundle.module.url(forResource: "voice-buckets", withExtension: "json")!
    return try! JSONDecoder().decode(Catalog.self, from: Data(contentsOf: url)).buckets
  }
  public static var bundledDurations: [String: Double] {
    let url = Bundle.module.url(forResource: "voice-durations", withExtension: "json")!
    return try! JSONDecoder().decode([String: Double].self, from: Data(contentsOf: url))
  }
  public struct BucketState {
    public var last = -Double.infinity
    var held = -Double.infinity
    public var cursor: Int
    public var voice = (-Double.infinity, -Double.infinity)
  }
  final class PAItem {
    var bucket: String, clip: String
    var due: Double
    var ready = false
    var duration: Double?
    let attempt = VoiceAttempt()
    init(_ bucket: String, _ clip: String, _ due: Double) {
      self.bucket = bucket
      self.clip = clip
      self.due = due
    }
  }
  public private(set) var buckets: [String: VoiceBucket]
  public private(set) var bucketState: [String: BucketState] = [:]
  public private(set) var spokenAt: [String: Double] = [:]
  public private(set) var busy = ["net": 0.0, "pa": 0.0, "crew": 0.0]
  public private(set) var lastClip = ""
  public private(set) var now = 0.0
  public var isMuted = false
  public var stopped = false
  public var speakerOf: [String: Int] = [:]
  public private(set) var launchUntil = 0.0
  public private(set) var nextChatter = Double.infinity
  public private(set) var captainKills = 0
  public private(set) var loadRequests: Set<String> = []
  public private(set) var ducks: [(from: Double, to: Double, level: Double)] = []
  private var output: [VoicePlayback] = []
  private var available: Set<String>
  private var failed: Set<String> = []
  private var loading: [String: [(Double?) -> Void]] = [:]
  private var durations: [String: Double]
  private var paQueue: [PAItem] = []
  private var hushUntil = [
    "net": -Double.infinity, "1mc": -Double.infinity, "crew": -Double.infinity,
  ]
  private var alarmAt = -Double.infinity, captainAt = -Double.infinity, actionSince = 0.0
  private var killTimes: [Double] = []
  private var nextID = 0
  private let random: GameRandom
  public static let crewPositions: [Vector3] = [
    [5.2, 5.55, 5.5], [2.2, 5.55, 4.8], [5.3, 5.55, 1.5], [3, 5.55, 6.8],
    [4.9, 5.55, -0.8], [1.2, 5.55, 7.2], [5.1, 5.55, 8], [-1.5, 5.55, 7.5],
  ]

  public init(
    random: GameRandom, buckets: [VoiceBucket] = VoiceScheduler.bundledBuckets,
    durations: [String: Double] = VoiceScheduler.bundledDurations, allClipsReady: Bool = true
  ) {
    self.random = random
    self.buckets = Dictionary(uniqueKeysWithValues: buckets.map { ($0.name, $0) })
    self.durations = durations
    available = allClipsReady ? Set(durations.keys) : []
    for bucket in buckets {
      bucketState[bucket.name] = BucketState(
        cursor: Int(random.unit() * Double(bucket.clips.count)))
    }
  }
  public var urgentClips: Set<String> {
    Set(
      buckets.values.filter { $0.urgent == true }.flatMap { b in
        (b.keep == true ? b.clips : Array(b.clips.prefix(1))).flatMap { clip in
          clip.contains("{bearing}")
            ? (0..<12).map {
              clip.replacingOccurrences(of: "{bearing}", with: String(format: "%03d", $0 * 30))
            } : [clip]
        }
      })
  }
  public func advanceClock(_ seconds: Double) {
    now += seconds
    ducks.removeAll { $0.to + 1 < now }
  }
  public func takeOutput() -> [VoicePlayback] {
    let result = output
    output = []
    return result
  }
  public func supplyClip(_ name: String, duration: Double?) {
    loadRequests.remove(name)
    if let duration {
      durations[name] = duration
      available.insert(name)
    } else {
      failed.insert(name)
    }
    let callbacks = loading.removeValue(forKey: name) ?? []
    for callback in callbacks { callback(duration) }
  }
  public func evictClip(_ name: String) { available.remove(name) }
  private func getClip(_ name: String, _ completion: @escaping (Double?) -> Void = { _ in }) {
    if available.contains(name) {
      completion(durations[name])
      return
    }
    if failed.contains(name) || durations[name] == nil {
      completion(nil)
      return
    }
    loadRequests.insert(name)
    loading[name, default: []].append(completion)
  }
  public func ready(_ name: String, at time: Double) -> Bool {
    guard let b = buckets[name], let s = bucketState[name] else { return false }
    return time - s.last >= (b.once == true ? .infinity : b.cooldown ?? 0)
  }
  public func clearFrom(_ time: Double = -.infinity) -> Double {
    max(time, busy["net"]! + 0.6, busy["pa"]! + 0.6, busy["crew"]! + 0.3, launchUntil)
  }
  public func fresh(_ name: String, params: VoiceParameters = .init(), at time: Double) -> [(
    Int, String
  )] {
    let b = buckets[name]!
    let state = bucketState[name]!
    return b.clips.indices.map { (state.cursor + $0) % b.clips.count }.map {
      ($0, params.expand(b.clips[$0]))
    }
    .filter { time - (spokenAt[$0.1] ?? -.infinity) >= (b.repeat ?? 300) }
  }
  @discardableResult public func play(
    _ name: String, params: VoiceParameters = .init(), at time: Double? = nil,
    lead: Double? = nil
  ) -> VoiceAttempt? {
    guard !isMuted, !stopped, let b = buckets[name] else { return nil }
    let t = time ?? now
    func follow(_ end: Double?) {
      if let next = b.then, end != nil || b.thenAlways == true {
        play(next, params: params, at: end ?? t)
      }
    }
    if b.onlyIfClear == true && clearFrom(t) > t {
      follow(nil)
      return nil
    }
    guard ready(name, at: t), random.unit() < (b.chance ?? 1) else {
      follow(nil)
      return nil
    }
    let fresh = fresh(name, params: params, at: t)
    if b.urgent == true { for (_, clip) in fresh { getClip(clip) } }
    var pool = b.urgent == true ? fresh.filter { available.contains($0.1) } : fresh
    guard !pool.isEmpty else {
      follow(nil)
      return nil
    }
    if b.rank != nil {
      let best = pool.map { rank($0.1, bucket: name, params: params) }.min()!
      pool = pool.filter { rank($0.1, bucket: name, params: params) == best }
    }
    let (index, clip) = pool[0]
    bucketState[name]!.cursor = (index + 1) % b.clips.count
    let due = t + (lead ?? b.lead ?? 0) + random.range(0, b.jitter ?? 0)
    bucketState[name]!.held = bucketState[name]!.last
    bucketState[name]!.last = t
    let attempt: VoiceAttempt
    if b.channel == "1mc" {
      let item = PAItem(name, clip, due)
      paQueue.append(item)
      attempt = item.attempt
      getClip(clip) { [weak self, weak item] duration in
        guard let item else { return }
        item.ready = true
        item.duration = duration
        self?.pumpPA()
      }
    } else {
      attempt = VoiceAttempt()
      getClip(clip) { [weak self, attempt] duration in
        attempt.settle(self?.say(name, clip: clip, duration: duration, due: due))
      }
    }
    attempt.then { [weak self] end in
      guard let self else { return }
      if end == nil, self.bucketState[name]!.last == t {
        self.bucketState[name]!.last = self.bucketState[name]!.held
      }
      if let next = b.then, end != nil || b.thenAlways == true {
        self.play(next, params: params, at: end ?? t)
      }
    }
    return attempt.resolved && attempt.end == nil ? nil : attempt
  }
  private func pumpPA() {
    while let item = paQueue.first, item.ready {
      paQueue.removeFirst()
      item.attempt.settle(say(item.bucket, clip: item.clip, duration: item.duration, due: item.due))
    }
  }
  private func say(_ name: String, clip: String, duration: Double?, due: Double) -> Double? {
    guard !stopped, let duration else { return nil }
    let b = buckets[name]!
    let line = b.channel == "1mc" ? "pa" : b.channel
    let gap = b.channel == "crew" ? 0.3 : 0.6
    if b.aside == true && line == "net" && now < launchUntil { return nil }
    var start = max(due, busy[line]! + gap, hushUntil[b.channel]! + gap, now + 0.02)
    if b.aside == true { start = clearFrom(start) }
    if start - due > (b.stale ?? (b.channel == "1mc" ? 8 : 3)) { return nil }
    let end = start + duration
    spokenAt[clip] = start
    busy[line] = max(busy[line]!, end)
    lastClip = clip
    bucketState[name]!.voice = (start, end)
    if let hush = b.hush { hushUntil[hush] = max(hushUntil[hush]!, end) }
    let duck = b.channel == "crew" ? 0.75 : 0.5
    ducks.append((start, end, duck))
    output.append(
      VoicePlayback(
        id: allocateID(), clip: clip, bucket: name, channel: b.channel,
        start: start, duration: duration, position: position(channel: b.channel, clip: clip),
        level: 1, duck: duck))
    return end
  }
  public func position(channel: String, clip: String = "") -> Vector3 {
    if channel == "crew" {
      return Self.crewPositions[(speakerOf[clip] ?? 0) % Self.crewPositions.count]
    }
    return channel == "1mc" ? [-1, 6.8, 9.7] : [3.2, 5.6, 9.4]
  }
  private func allocateID() -> Int {
    defer { nextID += 1 }
    return nextID
  }
  private func rank(_ clip: String, bucket: String, params: VoiceParameters) -> Double {
    if bucket == "reaction" { return clip.hasPrefix("hit-\(params.ship)-") == params.named ? 0 : 1 }
    let calls: [String: (Double, Double, Bool)] = [
      "dc-hit-stbd-fwd": (1, 80, true), "dc-hit": (1, 210, true), "dc-hit-port": (-1, 160, true),
      "dc-hit-port-aft": (-1, 310, true),
      "dc-fire-bravo": (1, 120, false), "dc-fire-charlie-stbd": (1, 150, false),
      "dc-fire-alpha-port": (-1, 96, false),
      "dc-flooding-port": (-1, 180, false), "dc-fire-bravo-port": (-1, 220, false),
      "dc-fire-charlie": (-1, 240, false), "dc-flooding": (0, 142, false),
    ]
    guard let (side, frame, missile) = calls[clip] else { return 0 }
    return (side != params.damageSide ? 2000 : missile != params.missile ? 1000 : 0)
      + abs(frame - params.frame)
  }
  public func announceVampire(bearing: Double) {
    guard !isMuted, !stopped else { return }
    let ring = now - alarmAt >= 40
    let called = String(format: "%03d", (Int(floor(bearing / 30 + 0.5)) % 12) * 30)
    guard play("vampire", params: .init(bearing: called), lead: ring ? 1.5 : nil) != nil, ring
    else { return }
    alarmAt = now
    alarm(clip: "general-alarm", at: now, duration: 5.4, level: 0.32)
  }
  private func alarm(clip: String, at time: Double, duration: Double, level: Double) {
    output.append(
      VoicePlayback(
        id: allocateID(), clip: clip, bucket: "alarm", channel: "1mc", start: time,
        duration: duration, position: position(channel: "1mc"), level: level, duck: 1))
  }
  public func warnVLSLaunch(routine: Bool, timeScale: Double) -> Double {
    guard !isMuted, !stopped else { return 0 }
    let at = max(now, bucketState["vampire"]!.voice.1)
    let call = routine ? play("missile-launch", at: at)?.end : nil
    let start = call.map { $0 + 0.4 } ?? at
    let end = start + 1.2
    alarm(clip: "launch-alarm", at: start, duration: 1.2, level: 0.22)
    let fires = end + 0.8 / timeScale
    launchUntil = max(launchUntil, ready("birds-away", at: fires) ? fires + 2 : end)
    return end - now
  }
  public func noteThreat(_ threat: Threat) {
    guard !isMuted else { return }
    play("weapons-free")
    if threat.kind == .mortar && threat.targetInfo.position.length < 150 { play("shells") }
  }
  public func announceKill(kind: ThreatKind, distance: Double) {
    guard !isMuted, !stopped else { return }
    if captainKills == 0 { actionSince = now }
    captainKills += 1
    if nextChatter == .infinity { nextChatter = now + random.range(45, 90) }
    killTimes = killTimes.filter { now - $0 < 2.5 }
    killTimes.append(now)
    if kind == .ascm { play("kill") }
    let close = kind == .ascm && distance < 300
    if (!close || play("close-call") == nil) && killTimes.count >= 2 { play("multi-splash") }
  }
  public func announceDamage(point: Vector3, kind: ThreatKind) {
    play(
      "we-hit",
      params: .init(
        damageSide: abs(point.x) < 1.2 ? 0 : sign(point.x),
        frame: (point.z + 42) / 112 * 460, missile: kind == .ascm))
  }
  public func announceFriendlyHit(key: String, side: Double) {
    let time = now
    let reacted = play("reaction", params: .init(ship: key, named: random.unit() < 0.7))
    let follow: (Double?) -> Void = { [weak self] end in
      guard let self else { return }
      let rescue: VoiceAttempt?
      if let end {
        rescue = self.play("rescue", params: .init(ship: key), at: end, lead: 0.8)
      } else {
        rescue = self.play("rescue", params: .init(ship: key), at: time)
      }
      if rescue == nil || self.random.unit() < 0.5 {
        self.play("rescue-followup", params: .init(side: side > 0 ? "stbd" : "port"), at: time)
      }
    }
    if let reacted { reacted.then(follow) } else { follow(nil) }
  }
  public func updateIdle(threats: [Threat], gameOver: Bool, played: Double) {
    guard !isMuted, !stopped, !gameOver else { return }
    if now >= nextChatter {
      nextChatter = now + 4
      let over = random.unit() * Double(buckets["chatter"]!.clips.count + 1) < 1
      let tired: [(String, Double)] = [
        ("tired-1", 900), ("tired-2", 1800), ("tired-3", 3600), ("r2", 3600), ("tired-4", 7200),
      ]
      let lots = random.randomizedLots(["chatter"] + tired.filter { played >= $0.1 }.map(\.0))
        .flatMap {
          $0 == "chatter" ? (over ? ["is-it-over", "chatter"] : ["chatter", "is-it-over"]) : [$0]
        }
      for name in lots {
        if let result = play(name) {
          result.then { [weak self] end in if end != nil { self?.nextChatter = .infinity } }
          break
        }
      }
    }
    let fought = captainKills >= 25 || (captainKills > 0 && now - actionSince >= 270)
    guard fought, now - captainAt >= 240, now - clearFrom() >= 5, paQueue.isEmpty,
      !threats.contains(where: { $0.position.length < 250 })
    else { return }
    let all: [(String, Double)] = [
      ("captain", 0), ("captain-medal", 1200), ("captain-cost", 3600), ("captain-long", 7200),
    ]
    var lots = Array(all.filter { played >= $0.1 }.map(\.0).reversed())
    if lots.count > 1 && random.unit() < 1 / 3 { lots.append(lots.removeFirst()) }
    for name in lots where play(name) != nil {
      captainKills = 0
      captainAt = now
      break
    }
  }
  public func stop() {
    stopped = true
    output = []
    let pending = paQueue
    paQueue = []
    for item in pending { item.attempt.settle(nil) }
  }
}
