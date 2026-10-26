#if canImport(SwiftUI)
import CanonCore
import CanonStore
import CanonUI
import FeatureForeshadow
import FeatureHome
import FeatureProjects
import FeatureStatWin
import SwiftUI

/// 앱 첫 화면: 왼쪽은 작품 목록이나 작품 메뉴, 오른쪽은 고른 화면.
public struct RootView: View {
    @State private var model = AppModel()
    @State private var showServer = false

    public init() {}

    public var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            VStack(spacing: 0) {
                if let n = model.notice {
                    Notice(n.text, isError: n.isError) { model.dismissNotice() }.padding()
                }
                if let doc = model.document { SaveBar(document: doc).padding(.horizontal) }
                detail.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: model.server.config) { await model.watchJobs() }
        .sheet(isPresented: $showServer) { ServerSettingsView(model: model) }
    }

    @ViewBuilder
    private var sidebar: some View {
        if let name = model.project {
            List(selection: selectedScreen) {
                Section { ForEach(Screen.allCases.filter { $0.group == .steps }) { item($0) } }
                Section("작품 도구") { ForEach(Screen.allCases.filter { $0.group == .tools }) { item($0) } }
                Section("본편과 분리") { ForEach(Screen.allCases.filter { $0.group == .separate }) { item($0) } }
            }
            .navigationTitle(name)
            .toolbar {
                Button("작품 목록") { model.open(nil) }
            }
        } else {
            ProjectsView(model: model.projects) { card in model.open(card.name) }
            .toolbar {
                Button("서버") { showServer = true }
            }
        }
    }

    /// iOS 의 `List(selection:)` 은 옵셔널 선택만 받는다. 선택을 지우는 동작(nil)은 무시한다.
    private var selectedScreen: Binding<Screen?> {
        Binding(get: { model.screen }, set: { if let s = $0 { model.screen = s } })
    }

    private func item(_ screen: Screen) -> some View {
        Label { Text(screen.label(serial: model.document?.serial ?? false)) } icon: { Text(screen.mark).font(.caption.monospaced()) }
            .tag(screen)
    }

    @ViewBuilder
    private var detail: some View {
        if let name = model.project {
            screen(model.screen, project: name).id("\(name)/\(model.screen.rawValue)")
        } else {
            ContentUnavailableView("작품을 고르세요", systemImage: "books.vertical")
        }
    }

    /// 화면 잇기. 화면 모듈을 옮기면 case 한 줄을 더한다 (README '새 화면 모듈을 만들 때' 5).
    /// 화면은 `model.server` 와 작품 이름을 받아 필요한 것을 스스로 받아 오거나, 작품 전체는 `model.document` 를 함께 쓴다.
    @ViewBuilder
    private func screen(_ screen: Screen, project: String) -> some View {
        switch screen {
        case .home: if let doc = model.document { HomeView(document: doc) { model.screen = $0 } }
        case .statwin: StatWinScreen(server: model.server, project: project)
        case .foreshadow: ForeshadowView(server: model.server, project: project)
        default:
            NotPortedYet(screen.label(serial: false))
        }
    }
}

/// 저장 띠: 저장하지 않은 변경, 다른 화면이 먼저 저장함(409), 저장 결과 알림 (웹 `renderSavebar`).
struct SaveBar: View {
    let document: ProjectDocument
    @State private var confirmRevert = false

    var body: some View {
        VStack(spacing: 8) {
            if let n = document.notice {
                Notice(n.text, isError: n.isError) { document.dismissNotice() }
            }
            if document.conflict {
                HStack {
                    Text(document.error ?? SaveText.conflictChoices).frame(maxWidth: .infinity, alignment: .leading)
                    Button("다시 불러오기") { Task { await document.reload() } }
                    Button("내 변경으로 덮기") { Task { await document.save(force: true) } }
                }
                .padding(10)
                .background(.orange.opacity(0.15), in: RoundedRectangle(cornerRadius: 8))
            } else if document.dirty {
                HStack {
                    Text("저장하지 않은 변경이 있어요").frame(maxWidth: .infinity, alignment: .leading)
                    Button("되돌리기") { confirmRevert = true }
                    Button("저장") { Task { await document.save() } }.buttonStyle(.borderedProminent)
                }
                .disabled(document.busy)
                .padding(10)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
            } else if let error = document.error, document.project != nil {
                Notice(error, isError: true)
            }
        }
        .padding(.top, 8)
        .confirmationDialog("저장하지 않은 변경을 모두 버리고 저장된 작품을 다시 불러올까요? 되돌릴 수 없어요.", isPresented: $confirmRevert, titleVisibility: .visible) {
            Button("버리고 다시 불러오기", role: .destructive) { Task { await document.reload() } }
        }
    }
}

/// 서버 주소 적기.
struct ServerSettingsView: View {
    let model: AppModel
    @State private var text = ""
    @State private var invalid = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            Section {
                TextField("http://127.0.0.1:8000", text: $text)
                    .autocorrectionDisabled()
                if invalid { Text("주소를 읽지 못했어요. http:// 나 https:// 로 시작하는 주소를 적으세요").foregroundStyle(.red) }
            } header: {
                Text("Canon 서버 주소")
            } footer: {
                Text("같은 기기에서는 python -m canon serve 주소를, 다른 기기에서는 Tailscale 주소를 적으세요")
            }
            Button("연결") {
                if model.connect(text) { dismiss() } else { invalid = true }
            }
        }
        .padding()
        .onAppear { text = model.server.config.baseURL.absoluteString }
    }
}
#endif
