#if canImport(SwiftUI)
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 작품 홈에 다른 화면 모듈이 끼우는 칸. 화면 모듈끼리는 서로 기대지 않아 `CanonAppUI` 가 채운다.
public struct HomeSlots: Sendable {
    /// 화별 진행 아래 (웹 `viewHome` 의 `branchHomeCard`).
    public var branchCard: @MainActor @Sendable () -> AnyView

    public init(branchCard: @escaping @MainActor @Sendable () -> AnyView) {
        self.branchCard = branchCard
    }

    public static let none = HomeSlots(branchCard: { AnyView(EmptyView()) })
}

extension EnvironmentValues {
    @Entry public var homeSlots: HomeSlots = .none
}

/// 작품 홈: 진행 단계, 화별 진행, 인물 현재 상태, 열린 복선, 확정 사실 (웹 `viewHome`).
public struct HomeView: View {
    let document: ProjectDocument
    let go: (Screen) -> Void
    @Environment(\.homeSlots) private var slots
    @Environment(\.openBranchForm) private var openBranchForm

    public init(document: ProjectDocument, go: @escaping (Screen) -> Void) {
        self.document = document
        self.go = go
    }

    public var body: some View {
        Group {
            if let p = document.project {
                content(HomeSummary(p, name: document.name))
            } else if let error = document.error {
                ContentUnavailableView("작품을 불러오지 못했어요", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("불러오는 중")
            }
        }
        .task { await document.load() }
        .refreshable { await document.load() }
    }

    private func content(_ s: HomeSummary) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header(s)
                stages(s)
                episodes(s)
                slots.branchCard()
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 280), alignment: .top)], alignment: .leading, spacing: 16) {
                    characters(s)
                    clues(s)
                    facts(s)
                }
            }
            .padding()
            .frame(maxWidth: 1100, alignment: .leading)
        }
    }

    private func header(_ s: HomeSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(s.subtitle).font(.caption).foregroundStyle(.secondary)
            Text(s.title).font(.largeTitle.bold())
            if !s.logline.isEmpty { Text(s.logline).foregroundStyle(.secondary) }
            HStack {
                Button(s.serial ? "부 · 아크 · 플롯" : "기승전결 · 플롯") { go(.arc) }
                if s.finalized > 0, let openBranchForm {
                    Button("갈래 만들기") { openBranchForm() }
                        .help("이 작품은 그대로 두고, 사본에서 다른 전개를 써요")
                }
                if let recap = s.recap { Button(recap) { go(.arc) } }
                Button(s.next.label) { go(s.next.screen) }.buttonStyle(.borderedProminent)
            }
            .buttonStyle(.bordered)
        }
    }

    private func stages(_ s: HomeSummary) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 8)], spacing: 8) {
            ForEach(s.stages, id: \.title) { st in
                Button { go(st.screen) } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Capsule().fill(color(st.state)).frame(height: 4)
                        Text(st.state.label).font(.caption2).foregroundStyle(.secondary)
                        Text(st.title).font(.subheadline.bold())
                        Text(st.detail).font(.caption).foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("진행 단계")
    }

    private func color(_ state: HomeSummary.Stage.State) -> Color {
        switch state {
        case .done: .green
        case .doing: .orange
        case .notStarted: .secondary.opacity(0.3)
        }
    }

    private func episodes(_ s: HomeSummary) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("화별 진행").font(.title3.bold())
            if s.cells.isEmpty {
                Text("아직 화별 플롯이 없어요. 다음 할 일: \(s.next.label)").foregroundStyle(.secondary)
            } else {
                if !s.bands.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack { ForEach(s.bands, id: \.title) { b in Text("\(b.title) \(b.range)").font(.caption).padding(.horizontal, 8).padding(.vertical, 4).background(.quaternary, in: Capsule()) } }
                    }
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 56), spacing: 6)], spacing: 6) {
                    ForEach(s.cells, id: \.number) { cell in
                        Button { go(cell.screen) } label: {
                            VStack(spacing: 2) {
                                Text("\(cell.number)").font(.headline)
                                Text(cell.label).font(.caption2).lineLimit(1).minimumScaleFactor(0.7)
                            }
                            .frame(maxWidth: .infinity, minHeight: 48)
                            .background(fill(cell.status).opacity(0.25), in: RoundedRectangle(cornerRadius: 6))
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(cell.current ? Color.accentColor : .clear, lineWidth: 2))
                        }
                        .buttonStyle(.plain)
                        .help(cell.title)
                        .accessibilityLabel(cell.accessibilityLabel)
                    }
                }
                if let note = s.partNote { Text(note).font(.caption).foregroundStyle(.secondary) }
            }
            ForEach(s.notes, id: \.self) { Notice($0, isError: true) }
        }
    }

    private func fill(_ status: EpisodeStatus) -> Color {
        switch status {
        case .draft: .gray
        case .confirmed: .accentColor
        case .written: .orange
        case .finalized: .green
        }
    }

    private func card<Content: View>(_ title: String, trailing: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title).font(.headline)
                Spacer()
                Text(trailing).font(.caption).foregroundStyle(.secondary)
            }
            content()
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
    }

    private func characters(_ s: HomeSummary) -> some View {
        card("인물 현재 상태", trailing: s.statesBasis) {
            if s.characters.isEmpty { Text("인물이 없어요").font(.caption).foregroundStyle(.secondary) }
            ForEach(s.characters, id: \.name) { c in
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(c.name) ").font(.subheadline.bold()) + Text(c.role).font(.caption).foregroundStyle(.secondary)
                    if c.lines.isEmpty {
                        Text("아직 변화 없음").font(.caption).foregroundStyle(.secondary)
                    } else {
                        ForEach(c.lines, id: \.self) { Text($0).font(.caption) }
                    }
                }
            }
        }
    }

    private func clues(_ s: HomeSummary) -> some View {
        card("열린 복선", trailing: "\(s.openClues.count)개") {
            if s.openClues.isEmpty { Text("없음").font(.caption).foregroundStyle(.secondary) }
            ForEach(s.openClues, id: \.id) { f in
                HStack(alignment: .top) {
                    Text("\(f.plantedEp)화").font(.caption2).padding(.horizontal, 6).padding(.vertical, 2).background(.quaternary, in: Capsule())
                    VStack(alignment: .leading) {
                        Text(f.description).font(.caption)
                        Text(f.id).font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
            Button("복선 센터") { go(.foreshadow) }.font(.caption)
        }
    }

    private func facts(_ s: HomeSummary) -> some View {
        card("확정 사실", trailing: "\(s.factCount)개") {
            if s.facts.isEmpty { Text("없음").font(.caption).foregroundStyle(.secondary) }
            ForEach(Array(s.facts.enumerated()), id: \.offset) { _, f in Text("• \(f)").font(.caption) }
        }
    }
}
#endif
