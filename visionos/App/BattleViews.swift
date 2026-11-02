import RealityKit
import SwiftUI

struct DeckView: View {
  @Bindable var model: BattleModel
  @State private var renderer: BattleRenderer?
  @Environment(\.scenePhase) private var scenePhase

  var body: some View {
    RealityView { content, attachments in
      do {
        let scene = try await BattleRenderer(model: model, presentation: .deck)
        renderer = scene
        content.add(scene.root)
        if let panel = attachments.entity(for: "station") {
          // World-stable controls below the horizon; no camera movement or head-locked HUD.
          panel.position = [0.35, 1.2, -1.5]
          panel.scale = .init(repeating: 1.5)
          content.add(panel)
        }
        scene.subscribe(content)
        model.enterDeck()
        model.deckOpen = true
        model.sceneActive = true
        // The deck shows while the sounds load; the battle waits for them
        Task { await scene.loadAudio() }
      } catch { model.audioMessage = "Scene could not load: \(error.localizedDescription)" }
    } attachments: {
      Attachment(id: "station") { StationPanel(model: model) }
    }
    .onChange(of: model.muted) { renderer?.refreshAudio() }
    .onChange(of: model.paused) { renderer?.refreshAudio() }
    .onChange(of: scenePhase) { _, phase in
      model.sceneActive = phase == .active
      renderer?.refreshAudio()
    }
    .onDisappear {
      renderer?.stop()
      renderer = nil
      model.deckOpen = false
      model.leaveDeck()
      model.sceneActive = true
    }
  }
}

struct TabletopView: View {
  let model: BattleModel
  @State private var renderer: BattleRenderer?
  @Environment(\.dismissWindow) private var dismissWindow
  @Environment(\.scenePhase) private var scenePhase

  var body: some View {
    GeometryReader3D { geometry in
      RealityView { content in
        guard model.tabletopRequested else {
          dismissWindow(id: "tabletop")
          return
        }
        do {
          let scene = try await BattleRenderer(model: model, presentation: .tabletop)
          renderer = scene
          content.add(scene.root)
          scene.fit(in: content.convert(geometry.frame(in: .local), from: .local, to: .scene))
          scene.subscribe(content)
          model.tabletopOpen = true
          if !model.deckOpen { model.sceneActive = true }
          Task { await scene.loadAudio() }
        } catch { model.audioMessage = "Scene could not load: \(error.localizedDescription)" }
      } update: { content in
        renderer?.fit(in: content.convert(geometry.frame(in: .local), from: .local, to: .scene))
        renderer?.root.isEnabled = !model.deckOpen
      }
    }
    .onChange(of: model.muted) { renderer?.refreshAudio() }
    .onChange(of: model.paused) { renderer?.refreshAudio() }
    .onChange(of: model.deckOpen) { renderer?.refreshAudio() }
    .ornament(attachmentAnchor: .scene(.bottomFront)) {
      StationPanel(model: model)
    }
    .onChange(of: scenePhase) { _, phase in
      if !model.deckOpen { model.sceneActive = phase == .active }
      renderer?.refreshAudio()
    }
    .onDisappear {
      renderer?.stop()
      renderer = nil
      model.tabletopOpen = false
    }
  }
}
