#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonUI
import SwiftUI

/// 인물 · 관계도 화면. 관계도(화별 재생), 인물 · 두 사람 상세, 등장표 (웹 `cast.js` 의 `viewCast`).
/// 관계 수치 직접 보정(웹 '수치 직접 보정')은 아직 앱에 없다. 웹 화면에서 쓴다.
public struct CastScreen: View {
    @State private var model: CastModel
    let go: (Screen) -> Void

    /// `go` 는 다른 화면으로 옮긴다 (설정 도우미, 이야기 줄기, 인과율). 화면을 잇는 일은 `CanonAppUI` 가 한다.
    public init(server: CanonServer, project: String, go: @escaping (Screen) -> Void = { _ in }) {
        _model = State(initialValue: CastModel(name: project, source: LiveCastSource(server: server), store: DefaultsLayoutStore()))
        self.go = go
    }

    public var body: some View {
        content
            .navigationTitle("인물 · 관계도")
            .toolbar {
                ToolbarItemGroup {
                    if model.cast != nil {
                        Picker("인물 화면", selection: $model.tab) {
                            Text("관계도").tag(CastModel.Tab.graph)
                            Text("등장표").tag(CastModel.Tab.table)
                        }
                        .pickerStyle(.segmented)
                        .onChange(of: model.tab) { model.stop() }
                    }
                    Button("인물 · 관계 설정") { go(.setup) }
                    Button { Task { await model.load() } } label: { Label("다시 불러오기", systemImage: "arrow.clockwise") }
                        .disabled(model.loading)
                }
            }
            .task { await model.load() }
            .onDisappear { model.stop() }
    }

    @ViewBuilder
    private var content: some View {
        if model.cast == nil, let error = model.error {
            ContentUnavailableView {
                Label("인물 화면을 계산하지 못했어요", systemImage: "exclamationmark.triangle")
            } description: {
                Text(error)
            } actions: {
                Button("다시 불러오기") { Task { await model.load() } }.buttonStyle(.borderedProminent)
                Button("설정 도우미에서 인물 보기") { go(.setup) }
            }
        } else if model.cast == nil {
            ProgressView("불러오는 중…").frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if model.characters.isEmpty {
            ContentUnavailableView {
                Label("아직 인물이 없어요", systemImage: "person.2")
            } actions: {
                Button("설정 도우미에서 인물 만들기") { go(.setup) }.buttonStyle(.borderedProminent)
            }
        } else {
            VStack(spacing: 0) {
                if let error = model.error { Notice(error, isError: true).padding([.horizontal, .top]) }
                switch model.tab {
                case .graph: graphTab
                case .table: ScrollView { CastTableCard(model: model).padding() }
                }
            }
        }
    }

    private var graphTab: some View {
        GeometryReader { geo in
            if geo.size.width >= 900 {
                HStack(alignment: .top, spacing: 16) {
                    ScrollView { CastGraphCard(model: model).padding([.leading, .vertical]) }
                    ScrollView { CastDetail(model: model, go: go).padding([.trailing, .vertical]) }
                        .frame(width: min(440, geo.size.width * 0.4))
                }
            } else {
                ScrollView {
                    VStack(spacing: 16) {
                        CastGraphCard(model: model)
                        CastDetail(model: model, go: go)
                    }
                    .padding()
                }
            }
        }
    }
}

/// 카드 모양 묶음 (웹 `.card`).
struct CastCard<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) { content }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.background.secondary, in: RoundedRectangle(cornerRadius: 12))
    }
}

/// 말로 · 숫자로 (웹 `relationHeader`). 이 기기 화면에서만 바꾼다.
struct NumbersToggle: View {
    @Bindable var model: CastModel

    var body: some View {
        Picker("관계 보기 방식", selection: $model.showNumbers) {
            Text("말로").tag(false)
            Text("숫자로").tag(true)
        }
        .pickerStyle(.segmented)
        .fixedSize()
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }

    /// 화 상태 칸 색 (웹 `.cs-on.<status>`): 테두리 색. 칸은 이 색을 옅게 채운다.
    static func episodeStatus(_ raw: String) -> Color {
        switch raw {
        case "confirmed": Color(hex: 0x2B54C8)
        case "written": Color(hex: 0xA85300)
        case "finalized": Color(hex: 0x1C6E45)
        default: Color.secondary
        }
    }

    /// 기 · 승 · 전 · 결 띠 색 (웹 `--act-1-ink` ~ `--act-4-ink`).
    static func act(_ tone: Int) -> Color {
        switch tone {
        case 1: Color(hex: 0xB35A12)
        case 2: Color(hex: 0x2B54C8)
        case 3: Color(hex: 0x7A3FB0)
        case 4: Color(hex: 0x1C6E45)
        default: Color.secondary
        }
    }
}

/// 작은 표시 (웹 `.chip`).
struct Chip: View {
    let text: String
    var tint: Color = .secondary

    init(_ text: String, tint: Color = .secondary) {
        self.text = text
        self.tint = tint
    }

    var body: some View {
        Text(text).font(.caption).padding(.horizontal, 8).padding(.vertical, 2)
            .background(tint.opacity(0.15), in: Capsule())
    }
}
#endif
