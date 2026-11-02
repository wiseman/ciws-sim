import CIWSSimulation
import SwiftUI

/// The station's controls, on the deck and under the tabletop
struct StationPanel: View {
  @Bindable var model: BattleModel

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Label("PHALANX · \(model.status.target.uppercased())", systemImage: "scope")
          .font(.headline)
        Spacer()
        ModeButton(model: model)
      }
      HStack(spacing: 28) {
        readout("INTEGRITY", "\(model.status.health)%", alarm: model.status.health <= 35)
        readout("WAVE", "\(model.status.wave)")
        readout("SPLASHES", "\(model.status.kills)")
        readout("CONTACTS", "\(model.status.contacts)")
      }
      Text(model.status.gameOver ? "Ship lost. Restart to take a new watch." : model.message)
        .font(.callout).foregroundStyle(.secondary).lineLimit(2)
      BattleControls(model: model)
      FireControlView(model: model)
      if let audioMessage = model.audioMessage {
        Text(audioMessage).font(.caption).foregroundStyle(.orange)
      }
    }
    .padding(20).frame(width: 620).glassBackgroundEffect()
  }

  private func readout(_ title: String, _ value: String, alarm: Bool = false) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      Text(title).font(.system(size: 10, weight: .bold)).tracking(1).foregroundStyle(.secondary)
      Text(value).font(.title3.monospacedDigit().bold()).foregroundStyle(alarm ? .red : .primary)
    }
  }
}

/// Swaps the deck for the tabletop or back, so only one is ever open
struct ModeButton: View {
  @Bindable var model: BattleModel
  @Environment(\.openImmersiveSpace) private var openImmersiveSpace
  @Environment(\.dismissImmersiveSpace) private var dismissImmersiveSpace
  @Environment(\.openWindow) private var openWindow
  @Environment(\.dismissWindow) private var dismissWindow

  var body: some View {
    Button {
      Task { await swap() }
    } label: {
      Label(
        model.deckOpen ? "Tabletop" : "Ship deck",
        systemImage: model.deckOpen ? "square.3.layers.3d" : "vision.pro")
    }
    .disabled(model.transitioning)
  }

  private func swap() async {
    model.transitioning = true
    defer { model.transitioning = false }
    if model.deckOpen {
      // The volume opens first: an app left with no scene closes
      model.tabletopRequested = true
      openWindow(id: "tabletop")
      await dismissImmersiveSpace()
    } else {
      switch await openImmersiveSpace(id: "deck") {
      case .opened: dismissWindow(id: "tabletop")
      case .userCancelled: model.message = "Deck entry cancelled."
      case .error: model.message = "Could not open the deck. Please try again."
      @unknown default: model.message = "Deck unavailable."
      }
    }
  }
}

struct BattleControls: View {
  @Bindable var model: BattleModel

  var body: some View {
    HStack(spacing: 10) {
      Button {
        model.paused.toggle()
      } label: {
        Image(systemName: model.paused ? "play.fill" : "pause.fill")
      }.help(model.paused ? "Resume" : "Pause").accessibilityLabel(
        model.paused ? "Resume" : "Pause")
      Toggle("⅒ speed", isOn: $model.slowMotion).toggleStyle(.button)
      Toggle("Hold fire", isOn: $model.holdFire).toggleStyle(.button)
      Button {
        model.muted.toggle()
      } label: {
        Image(systemName: model.muted ? "speaker.slash.fill" : "speaker.wave.2.fill")
      }.accessibilityLabel(model.muted ? "Unmute" : "Mute")
      Spacer(minLength: 0)
      Button("Send raid") { model.sendRaid() }.disabled(model.status.gameOver)
      Button {
        model.restart()
      } label: {
        Image(systemName: "arrow.counterclockwise")
      }
      .help("Restart battle").accessibilityLabel("Restart battle")
    }
    .disabled(model.transitioning)
  }
}

struct FireControlView: View {
  @Bindable var model: BattleModel
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Picker("Controller", selection: $model.controller) {
          Text("Classic solver").tag(ControllerMode.classic)
          Text("Neural").tag(ControllerMode.neural).disabled(model.status.trainingSteps == 0)
        }.pickerStyle(.segmented)
        Toggle("Learn", isOn: $model.training).toggleStyle(.button)
        Toggle("Zen", isOn: $model.zen).toggleStyle(.button)
        Button(model.resetArmed ? "Confirm reset?" : "Reset net") { model.resetLearning() }
      }
      Text(
        "\(model.status.afloat)/5 escorts · High score \(model.status.highScore) · \(model.status.cost, format: .currency(code: "USD").precision(.fractionLength(0))) spent"
      )
      .font(.caption.monospaced()).foregroundStyle(.secondary)
      if model.training || model.status.trainingSteps > 0 {
        Text(
          "\(model.status.samples) samples · \(model.status.trainingSteps) batches · Loss \(model.status.loss.isFinite ? String(format: "%.4f", model.status.loss) : "—") · Aim \(model.status.aimError.isFinite ? String(format: "%.2f°", model.status.aimError) : "—")"
        )
        .font(.caption.monospaced()).foregroundStyle(.secondary)
      }
    }
  }
}
