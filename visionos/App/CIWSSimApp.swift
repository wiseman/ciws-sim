import SwiftUI

/// One presentation at a time: the app launches onto the deck (Info.plist's preferred scene
/// role), and the station panel swaps it for the tabletop and back.
@main
struct CIWSSimApp: App {
  @State private var model = BattleModel()

  var body: some Scene {
    ImmersiveSpace(id: "deck") {
      DeckView(model: model)
    }
    .immersionStyle(selection: .constant(.full), in: .full)

    WindowGroup(id: "tabletop") {
      TabletopView(model: model)
    }
    .windowStyle(.volumetric)
    .defaultSize(width: 1.5, height: 0.65, depth: 1.5, in: .meters)
  }
}
