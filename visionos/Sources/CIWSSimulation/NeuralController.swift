import Foundation
import simd

public enum ControllerMode: String, Codable, Sendable, CaseIterable { case classic, neural }
public struct TrainingSample: Codable, Sendable {
  public var inputs: [Double]
  public var targets: [Double]
  public init(inputs: [Double], targets: [Double]) {
    self.inputs = inputs
    self.targets = targets
  }
}
public func makeControllerInputs(displacement d: Vector3, velocity v: Vector3, isMortar: Bool)
  -> [Double]
{
  let yaw = atan2(d.x, d.z)
  let elevation = atan2(d.y, hypot(d.x, d.z))
  let sy = sin(yaw)
  let cy = cos(yaw)
  let se = sin(elevation)
  let ce = cos(elevation)
  let closing = v.x * ce * sy + v.y * se + v.z * ce * cy
  let sideways = v.x * cy - v.z * sy
  let vertical = -v.x * se * sy + v.y * ce - v.z * se * cy
  return [
    d.length / 472 - 1, 2 * closing / 8, 2 * sideways / 8, 2 * vertical / 8, se, 2 * ce - 1,
    isMortar ? 1 : -1,
  ]
}
public func makeControllerTargets(solution: AimSolution, sight: AimSolution) -> [Double] {
  [
    wrapAngle(solution.targetYaw - sight.targetYaw) * cos(sight.targetPitch) / 0.15,
    (solution.targetPitch - sight.targetPitch) / 0.3, solution.inReach ? 1 : 0,
  ]
}
public func aimAngleBetween(_ a: AimSolution, _ b: AimSolution) -> Double {
  func direction(_ s: AimSolution) -> Vector3 {
    [
      cos(s.targetPitch) * sin(s.targetYaw), -sin(s.targetPitch),
      cos(s.targetPitch) * cos(s.targetYaw),
    ]
  }
  return acos(clamp(simd_dot(direction(a), direction(b)), -1, 1))
}

/// Line-for-line numerical equivalent of NeuralController in index.html: 7–32–24–3, tanh + Adam.
public final class NeuralController {
  public static let spec = "los-v1|7-32-24-3|reach472|s8|lat0.15|ps0.3"
  public var weights: [[[Double]]] = []
  public var isTraining = false
  public private(set) var isTrained = false
  public private(set) var trainSteps = 0
  public private(set) var observedSamples = 0
  public private(set) var liveReplay: [TrainingSample] = []
  public private(set) var liveValidation: [TrainingSample] = []
  public private(set) var lossEma = Double.nan
  public private(set) var aimErrEma = Double.nan
  public private(set) var fireAgreeEma = Double.nan
  public private(set) var lossHistory: [Double] = []
  public private(set) var lastInputs = Array(repeating: 0.0, count: 7)
  public private(set) var lastHidden1 = Array(repeating: 0.0, count: 32)
  public private(set) var lastHidden2 = Array(repeating: 0.0, count: 24)
  public private(set) var lastOutputs = Array(repeating: 0.0, count: 3)
  public private(set) var lastSampleAt = 0.0
  public private(set) var lastSavedAt = 0.0
  public var onSave: ((Data) -> Void)?
  private let random: GameRandom
  private var moment: [[[Double]]] = [], variance: [[[Double]]] = []
  private var adamStep = 0
  private var lastHistoryAt = 0.0

  public init(random: GameRandom) {
    self.random = random
    reset()
  }
  public func reset() {
    weights = [(7, 32), (32, 24), (24, 3)].map { input, output in
      let limit = sqrt(6 / Double(input + output))
      return (0..<output).map { _ in (0..<input).map { _ in random.signed(limit) } + [0] }
    }
    resetOptimizer()
    isTraining = false
    isTrained = false
    trainSteps = 0
    observedSamples = 0
    lastInputs = Array(repeating: 0, count: 7)
    lastHidden1 = Array(repeating: 0, count: 32)
    lastHidden2 = Array(repeating: 0, count: 24)
    lastOutputs = Array(repeating: 0, count: 3)
    liveReplay = []
    liveValidation = []
    lossHistory = []
    lossEma = .nan
    aimErrEma = .nan
    fireAgreeEma = .nan
    lastHistoryAt = 0
    lastSampleAt = 0
    lastSavedAt = 0
  }
  public func resetOptimizer() {
    moment = weights.map { $0.map { Array(repeating: 0, count: $0.count) } }
    variance = moment
    adamStep = 0
  }
  private func layer(_ weights: [[Double]], _ inputs: [Double], activate: Bool) -> [Double] {
    weights.map { row in
      var sum = row[inputs.count]
      for i in inputs.indices { sum += row[i] * inputs[i] }
      return activate ? tanh(sum) : sum
    }
  }
  private func forward(_ inputs: [Double]) -> (h1: [Double], h2: [Double], output: [Double]) {
    let h1 = layer(weights[0], inputs, activate: true)
    let h2 = layer(weights[1], h1, activate: true)
    return (h1, h2, layer(weights[2], h2, activate: false))
  }
  public func predict(_ inputs: [Double], record: Bool = false) -> [Double] {
    let result = forward(inputs)
    if record {
      lastInputs = inputs
      lastHidden1 = result.h1
      lastHidden2 = result.h2
      lastOutputs = [
        tanh(result.output[0]), tanh(result.output[1]), 2 * sigmoid(result.output[2]) - 1,
      ]
    }
    return result.output
  }
  public func lossFor(_ outputs: [Double], _ targets: [Double]) -> Double {
    let yaw = outputs[0] - targets[0]
    let pitch = outputs[1] - targets[1]
    let p = clamp(sigmoid(outputs[2]), 1e-6, 1 - 1e-6)
    let bce = -(targets[2] * log(p) + (1 - targets[2]) * log(1 - p))
    return 0.5 * (yaw * yaw + pitch * pitch) + 0.2 * bce
  }
  public func evaluateReplayLoss(count: Int) -> Double {
    let samples = liveValidation.isEmpty ? liveReplay : liveValidation
    guard !samples.isEmpty else { return .nan }
    var loss = 0.0
    for _ in 0..<count {
      let sample = random.pick(samples)
      loss += lossFor(predict(sample.inputs), sample.targets)
    }
    return loss / Double(count)
  }
  @discardableResult public func trainBatch(_ batch: [TrainingSample]) -> Double {
    precondition(!batch.isEmpty)
    var gradients = weights.map { $0.map { Array(repeating: 0.0, count: $0.count) } }
    var loss = 0.0
    for sample in batch {
      let (h1, h2, outputs) = forward(sample.inputs)
      loss += lossFor(outputs, sample.targets)
      let dOut = [
        outputs[0] - sample.targets[0], outputs[1] - sample.targets[1],
        0.2 * (sigmoid(outputs[2]) - sample.targets[2]),
      ]
      var dh2 = Array(repeating: 0.0, count: 24)
      var dh1 = Array(repeating: 0.0, count: 32)
      for o in 0..<3 {
        for h in 0..<24 {
          gradients[2][o][h] += dOut[o] * h2[h]
          dh2[h] += dOut[o] * weights[2][o][h]
        }
        gradients[2][o][24] += dOut[o]
      }
      for h in 0..<24 { dh2[h] *= 1 - h2[h] * h2[h] }
      for h in 0..<24 {
        for i in 0..<32 {
          gradients[1][h][i] += dh2[h] * h1[i]
          dh1[i] += dh2[h] * weights[1][h][i]
        }
        gradients[1][h][32] += dh2[h]
      }
      for i in 0..<32 { dh1[i] *= 1 - h1[i] * h1[i] }
      for h in 0..<32 {
        for i in 0..<7 { gradients[0][h][i] += dh1[h] * sample.inputs[i] }
        gradients[0][h][7] += dh1[h]
      }
    }
    adamStep += 1
    let lr = max(0.0002, 0.003 / (1 + Double(adamStep) / 3000))
    let b1 = 0.9
    let b2 = 0.999
    let c1 = 1 - pow(b1, Double(adamStep))
    let c2 = 1 - pow(b2, Double(adamStep))
    let scale = 1 / Double(batch.count)
    for l in weights.indices {
      for r in weights[l].indices {
        for k in weights[l][r].indices {
          let g = gradients[l][r][k] * scale
          moment[l][r][k] = b1 * moment[l][r][k] + (1 - b1) * g
          variance[l][r][k] = b2 * variance[l][r][k] + (1 - b2) * g * g
          weights[l][r][k] -= lr * (moment[l][r][k] / c1) / (sqrt(variance[l][r][k] / c2) + 1e-8)
        }
      }
    }
    return loss / Double(batch.count)
  }
  public func rememberLiveSample(inputs: [Double], targets: [Double]) {
    observedSamples += 1
    let sample = TrainingSample(inputs: inputs, targets: targets)
    if observedSamples % 5 == 0 {
      liveValidation.append(sample)
      if liveValidation.count > 1500 { liveValidation.removeFirst() }
    } else {
      liveReplay.append(sample)
      if liveReplay.count > 6000 { liveReplay.removeFirst() }
    }
  }
  public func trainFromLiveReplay(
    batchCount: Int = 2, milliseconds: Double,
    wallMilliseconds: Double = Date().timeIntervalSince1970 * 1000
  ) {
    guard !liveReplay.isEmpty else { return }
    for _ in 0..<batchCount { trainBatch((0..<32).map { _ in random.pick(liveReplay) }) }
    trainSteps += batchCount
    isTrained = true
    lastSampleAt = milliseconds
    if milliseconds - lastHistoryAt > 500 {
      lastHistoryAt = milliseconds
      let loss = evaluateReplayLoss(count: 128)
      if loss.isFinite {
        lossEma = ema(lossEma, loss, 0.3)
        lossHistory.append(lossEma)
        if lossHistory.count > 120 { lossHistory.removeFirst() }
      }
    }
    if wallMilliseconds - lastSavedAt > 15000 { save(milliseconds: wallMilliseconds) }
  }
  public func recordAgreement(net: AimSolution, teacher: AimSolution) {
    aimErrEma = ema(aimErrEma, aimAngleBetween(net, teacher) * 180 / .pi, 0.03)
    fireAgreeEma = ema(fireAgreeEma, net.canFire == teacher.inReach ? 1 : 0, 0.03)
  }
  public func decide(inputs: [Double], sight: AimSolution) -> AimSolution {
    let outputs = predict(inputs, record: true)
    return AimSolution(
      targetYaw: wrapAngle(sight.targetYaw + outputs[0] * 0.15 / max(0.05, cos(sight.targetPitch))),
      targetPitch: sight.targetPitch + outputs[1] * 0.3, interceptSteps: nil,
      canFire: outputs[2] > 0)
  }
  public struct SavedState: Codable {
    var spec: String
    var hiddenWeights1: [[Double]], hiddenWeights2: [[Double]], outputWeights: [[Double]]
    var trainSteps: Int
    var lossEma: Double?
    var lossHistory: [Double]
    var savedAt: Double
  }
  public func save(milliseconds: Double) {
    guard isTrained else { return }
    let state = SavedState(
      spec: Self.spec, hiddenWeights1: weights[0], hiddenWeights2: weights[1],
      outputWeights: weights[2], trainSteps: trainSteps,
      lossEma: lossEma.isFinite ? lossEma : nil, lossHistory: lossHistory, savedAt: milliseconds)
    if let data = try? JSONEncoder().encode(state) {
      onSave?(data)
      lastSavedAt = milliseconds
    }
  }
  @discardableResult public func load(_ data: Data) -> Bool {
    guard let state = try? JSONDecoder().decode(SavedState.self, from: data),
      state.spec == Self.spec
    else { return false }
    let layers = [state.hiddenWeights1, state.hiddenWeights2, state.outputWeights]
    for (layer, (rows, columns)) in zip(layers, [(32, 8), (24, 33), (3, 25)]) {
      guard layer.count == rows,
        layer.allSatisfy({ $0.count == columns && $0.allSatisfy(\.isFinite) })
      else { return false }
    }
    reset()
    weights = layers
    resetOptimizer()
    trainSteps = state.trainSteps
    lossEma = state.lossEma ?? .nan
    lossHistory = Array(state.lossHistory.suffix(120))
    lastSavedAt = state.savedAt
    isTrained = trainSteps > 0
    return isTrained
  }
}
