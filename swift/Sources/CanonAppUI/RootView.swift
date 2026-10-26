#if canImport(SwiftUI)
import CanonCore
import CanonUI
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
                Button("작품 목록") { model.project = nil }
            }
        } else {
            ProjectsView(model: model.projects) { card in
                model.project = card.name
                model.screen = .home
            }
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
        // 장편 여부는 작품을 받아 오면 알 수 있다. 작품 홈을 옮길 때 작품 전체를 받아 serial 을 넘긴다
        Label { Text(screen.label(serial: false)) } icon: { Text(screen.mark).font(.caption.monospaced()) }
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
    /// 화면은 `server` 와 작품 이름을 받아 필요한 것을 스스로 받아 온다.
    @ViewBuilder
    private func screen(_ screen: Screen, project: String) -> some View {
        switch screen {
        case .statwin: StatWinScreen(server: model.server, project: project)
        default:
            NotPortedYet(screen.label(serial: false))
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
