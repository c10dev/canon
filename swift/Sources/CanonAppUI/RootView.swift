#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import FeatureAuto
import FeatureBranches
import FeatureForeshadow
import FeatureHome
import FeatureLines
import FeatureCast
import FeatureCausal
import FeatureBrief
import FeatureCheck
import FeaturePlot
import FeatureProjects
import FeatureReview
import FeatureSettings
import FeatureSetup
import FeatureStatWin
import FeatureStyle
import FeatureUsage
import FeatureWrite
import Foundation
import SwiftUI

/// 앱 첫 화면: 왼쪽은 작품 목록이나 작품 메뉴, 오른쪽은 고른 화면.
public struct RootView: View {
    @State private var model = AppModel()
    @State private var showServer = false
    @State private var showSettings = false

    public init() {}

    public var body: some View {
        NavigationSplitView {
            sidebar
                #if os(macOS)
                // Mac 은 사이드바 칸의 툴바에 단추 둘('서버' · '작품 목록', '모델 · API 키')과 신호등 단추가 함께 들어간다.
                // 기본 폭(233pt)에서는 넘친 단추가 보이지 않아 그보다 좁아지지 않게 한다
                .navigationSplitViewColumnWidth(min: 300, ideal: 320)
                #endif
        } detail: {
            VStack(spacing: 0) {
                if let n = model.jobs.notice {
                    Notice(n.text, isError: n.isError) { model.jobs.dismissNotice() }.padding()
                }
                if let doc = model.document { SaveBar(document: doc).padding(.horizontal) }
                if let b = model.branches {
                    if let n = b.notice { Notice(n) { b.dismissNotice() }.padding(.horizontal).padding(.top, 8) }
                    BranchStrip(model: b, home: model.screen == .home) { model.open($0) }.padding(.horizontal).padding(.top, 8)
                }
                detail.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .environment(\.openBranchForm, BranchOpener { [model] n in model.openBranchForm(n) })
            .environment(\.homeSlots, homeSlots)
        }
        .task(id: model.server.config) { await model.jobs.watch() }
        .sheet(isPresented: $showServer) { ServerSettingsView(model: model) }
        .sheet(isPresented: $showSettings) { SettingsView(server: model.server) }
        .sheet(item: Binding(get: { model.branchForm }, set: { model.branchForm = $0 })) { draft in
            if let b = model.branches, let doc = model.document {
                BranchFormView(model: b, document: doc, draft: draft) { model.openBranch($0) }
            }
        }
    }

    /// 작품 홈의 갈래 카드 (FeatureBranches). 작품 홈에 올 때마다 집안을 다시 읽는다 (웹 `route` 의 `branchLoad`).
    private var homeSlots: HomeSlots {
        let m = model
        return HomeSlots(branchCard: {
            guard let b = m.branches else { return AnyView(EmptyView()) }
            return AnyView(BranchHomeCard(model: b, open: { m.open($0) }, compare: { other in
                b.wanted = other
                m.screen = .branches
            }).task { await b.load() })
        })
    }

    @ViewBuilder
    private var sidebar: some View {
        if let name = model.project {
            List(selection: selectedScreen) {
                Section {
                    ForEach(Screen.allCases.filter { $0.group == .steps }) { item($0) }
                } header: {
                    if let b = model.branches { BranchSideTag(model: b) }
                }
                Section { ForEach(Screen.allCases.filter { $0.group == .autoRun }) { item($0) } }
                Section("작품 도구") { ForEach(Screen.allCases.filter { $0.group == .tools }) { item($0) } }
                Section("본편과 분리") { ForEach(Screen.allCases.filter { $0.group == .separate }) { item($0) } }
            }
            .navigationTitle(name)
            .toolbar {
                Button("작품 목록") { model.open(nil) }
                Button("모델 · API 키") { showSettings = true }
            }
        } else {
            ProjectsView(model: model.projects) { card in model.open(card.name) }
            .toolbar {
                Button("서버") { showServer = true }
                Button("모델 · API 키") { showSettings = true }
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

    /// 작업지시서에서 확인한 상태 변경안을 상태 승인 화면의 검토 대기로 넘긴다 (웹 `importJson` → `setDelta(n, d, 'chat')`).
    /// 변경안을 만든 본문은 지금 본문이다. 그 뒤 본문을 고치면 상태 승인 화면이 알린다.
    private func handOff(_ doc: ProjectDocument, _ n: Int, _ delta: Components.Schemas.StateDelta) {
        guard let result = try? JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(delta)) else { return }
        let text = doc.project?.episodes?.first { $0.plot.number == n }?.text
        model.jobs.offer(PendingResult(key: Job.key("state", n), id: "chat:\(n)", kind: "state", ep: n, label: "\(n)화 상태 변경안", result: result, base: text))
    }

    /// 플롯 화면에 끼우는 이야기 줄기 칸 · 화 카드 표시 (FeatureLines). 화면 모듈끼리는 서로 기대지 않아 여기서 잇는다.
    static let plotSlots = PlotSlots(
        episodeField: { p, plot, locked, written, change in AnyView(LineField(project: p, plot: plot, locked: locked, written: written, change: change)) },
        cardBadges: { p, plot in AnyView(LineBadges(project: p, plot: plot)) })

    /// 화면 잇기. 화면 모듈을 옮기면 case 한 줄을 더한다 (README '새 화면 모듈을 만들 때' 5).
    /// 화면은 `model.server` 와 작품 이름을 받아 필요한 것을 스스로 받아 오거나, 작품 전체는 `model.document` 를 함께 쓴다.
    @ViewBuilder
    private func screen(_ screen: Screen, project: String) -> some View {
        switch screen {
        case .home: if let doc = model.document { HomeView(document: doc) { model.screen = $0 } }
        case .setup: if let doc = model.document { SetupView(document: doc, jobs: model.jobs, server: model.server) { model.screen = $0 } }
        case .style: if let doc = model.document { StyleView(document: doc, server: model.server) { model.screen = $0 } }
        case .statwin: StatWinScreen(server: model.server, project: project)
        case .foreshadow: ForeshadowView(server: model.server, project: project)
        case .usage: UsageView(model: UsageModel(source: LiveUsageSource(server: model.server), project: project))
        case .cast: CastScreen(server: model.server, project: project) { model.screen = $0 }
        case .review: if let doc = model.document { ReviewView(document: doc, jobs: model.jobs, service: LiveReviewService(server: model.server)) { model.screen = $0 } }
        case .write: if let doc = model.document { WriteView(document: doc, jobs: model.jobs, server: model.server) { model.screen = $0 } }
        case .check: if let doc = model.document { CheckView(document: doc, jobs: model.jobs, service: LiveCheckService(server: model.server)) { model.screen = $0 } }
        case .arc: if let doc = model.document { PlotScreen(document: doc, jobs: model.jobs, server: model.server) { model.screen = $0 }.environment(\.plotSlots, Self.plotSlots) }
        case .auto: if let doc = model.document { AutoScreen(document: doc, jobs: model.jobs, server: model.server) { model.screen = $0 } }
        case .lines: if let doc = model.document { LinesScreen(document: doc, jobs: model.jobs, server: model.server) { model.screen = $0 } }
        case .causal: if let doc = model.document { CausalView(document: doc, jobs: model.jobs, service: LiveCausalService(server: model.server)) { model.screen = $0 } }
        case .branches: if let doc = model.document, let b = model.branches { BranchCompareScreen(model: b, document: doc, open: { model.open($0) }) { model.screen = $0 } }
        case .brief: if let doc = model.document { BriefView(document: doc, service: LiveBriefService(server: model.server), go: { model.screen = $0 }, handOff: { n, d in handOff(doc, n, d) }) }
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
