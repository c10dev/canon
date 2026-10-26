#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 기승전결 · 플롯 화면 (장편은 부 · 아크 · 플롯). 구간을 확인하고, 화 카드를 눌러 플롯을 다듬은 뒤 확정한다 (웹 `viewArc` · `viewSerial`).
/// AI 대화 패널, 이야기 줄기 칸, 단편 → 장편 전환, 여는 방식은 아직 웹에서 쓴다.
public struct PlotScreen: View {
    @State private var model: PlotModel
    let go: (Screen) -> Void

    public init(document: ProjectDocument, jobs: JobCenter, server: CanonServer, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: PlotModel(document: document, jobs: jobs, service: LivePlotService(server: server, project: document.name)))
        self.go = go
    }

    public init(model: PlotModel, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: model)
        self.go = go
    }

    public var body: some View {
        Group {
            if let p = model.project {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header(p)
                        notices
                        if model.serial { SerialContent(model: model, project: p, go: go) } else { ShortContent(model: model, project: p, go: go) }
                    }
                    .padding()
                    .frame(maxWidth: 1200, alignment: .leading)
                }
            } else if let error = model.document.error {
                ContentUnavailableView("작품을 불러오지 못했어요", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("불러오는 중")
            }
        }
        .navigationTitle(model.serial ? "부 · 아크 · 화별 플롯" : "기승전결 · 화별 플롯")
        .inspector(isPresented: inspectorShown) {
            if let p = model.project {
                ScrollView { PanelView(model: model, project: p, go: go).padding() }
                    .inspectorColumnWidth(min: 320, ideal: 400, max: 560)
            }
        }
        .confirmationDialog(model.ask?.message ?? "", isPresented: askShown, titleVisibility: .visible, presenting: model.ask) { ask in
            Button(ask.button, role: ask.destructive ? .destructive : nil) { Task { await ask.run() } }
        }
        .task {
            await model.document.load()
            model.syncResults()
        }
        .onChange(of: model.jobs.results) { model.syncResults() }
        .onChange(of: model.project?.episodes?.count) { model.tidy() }
        .refreshable { await model.document.load() }
    }

    private var inspectorShown: Binding<Bool> {
        Binding(get: { model.panel != nil }, set: { if !$0 { model.select(nil) } })
    }

    private var askShown: Binding<Bool> {
        Binding(get: { model.ask != nil }, set: { if !$0 { model.ask = nil } })
    }

    private func header(_ p: Project) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("3단계").font(.caption).foregroundStyle(.secondary)
            Text(model.serial ? "부 · 아크 · 화별 플롯" : "기승전결 · 화별 플롯").font(.title.bold())
            Text(model.serial
                 ? "장편은 작품을 부와 아크로 나누고, 다음 아크 하나씩 기획해 그 아크의 플롯만 만들어요. 끝난 아크는 요약으로 접혀서 몇백 화를 써도 프롬프트 크기가 일정해요."
                 : "구간 목표를 확인하고, 화 카드를 눌러 플롯을 다듬은 뒤 확정하세요. 확정된 화만 본문을 쓸 수 있고, 초안을 다시 만들어도 확정된 화는 그대로예요.")
                .font(.callout).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var notices: some View {
        if let n = model.notice { Notice(n.text, isError: n.isError) { model.dismissNotice() } }
        if model.busy { HStack(spacing: 8) { ProgressView(); Text("서버에 보내는 중…") } }
        ForEach(model.failures, id: \.key) { f in
            HStack {
                Text("지난 시도 실패 · \(f.label): \(f.error)").frame(maxWidth: .infinity, alignment: .leading)
                Button("다시 시도") { Task { await model.retry(f) } }
                Button("닫기") { Task { await model.jobs.dismissFailure(f.key) } }
            }
            .font(.callout)
            .padding(10)
            .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
        }
    }
}

/// 구조 · 부 구성 · 초안을 다시 받을 때 함께 보낼 한 줄 요청 (웹 `planNoteField`).
struct PlanNoteField: View {
    @Bindable var model: PlotModel
    let what: String

    var body: some View {
        TextRow(label: "\(what)에 함께 보낼 요청 (선택)", text: $model.planNote, placeholder: "예: 3화 안에 첫 반전, 로맨스 비중은 줄이기")
    }
}

/// 작업 단추. 작업이 돌면 진행 글자를 보이고 막는다 (웹 `jobBtn`).
struct JobButton: View {
    let model: PlotModel
    let kind: String
    var ep: Int?
    let idle: String
    var prominent = false
    let action: () async -> Void

    var body: some View {
        let busy = model.jobs.busyLabel(kind, ep: ep)
        Button { Task { await action() } } label: {
            HStack(spacing: 6) {
                if busy != nil { ProgressView().controlSize(.small) }
                Text(busy ?? idle)
            }
        }
        .disabled(busy != nil)
        .modify { if prominent { $0.buttonStyle(.borderedProminent) } else { $0.buttonStyle(.bordered) } }
    }
}

extension View {
    @ViewBuilder
    func modify(@ViewBuilder _ f: (Self) -> some View) -> some View { f(self) }
}

// MARK: 단편

struct ShortContent: View {
    let model: PlotModel
    let project: Project
    let go: (Screen) -> Void

    var body: some View {
        let p = project
        let eps = p.episodes ?? []
        let acts = p.arc ?? []
        let drafts = eps.filter { PlotRules.status($0) == .draft }.count
        let end = acts.map(\.endEp).max() ?? 0
        VStack(alignment: .leading, spacing: 16) {
            if !acts.isEmpty {
                HStack {
                    JobButton(model: model, kind: "arc", idle: "구조 다시 제안") { await model.planArc() }
                    if PlotRules.needsDraft(eps, 1, end) || model.jobs.running("plots") != nil {
                        JobButton(model: model, kind: "plots", idle: eps.isEmpty ? "화별 플롯 초안 만들기" : "초안 다시 만들기 (확정 화 제외)") { await model.draftPlots() }
                    }
                    if drafts > 0 {
                        Button("초안 \(drafts)화 모두 확정") { model.confirmAll() }
                            .buttonStyle(.borderedProminent).disabled(model.jobs.running("plots") != nil || model.busy)
                    } else if let n = PlotRules.writeNext(p) {
                        Button("\(n)화 쓰기") { go(.write) }.buttonStyle(.borderedProminent)
                    }
                }
                if model.arcProposal == nil { PlanNoteField(model: model, what: "구조 다시 제안 · 초안 만들기") }
            }
            if let proposal = model.arcProposal {
                ArcProposalCard(model: model, proposal: proposal, current: acts)
            } else if acts.isEmpty {
                CardBox {
                    Text("아직 기승전결 구조가 없어요.").font(.headline)
                    if (p.meta?.logline ?? "").trimmingCharacters(in: .whitespaces).isEmpty || (p.characters ?? []).isEmpty {
                        NoteBox(text: "설정 도우미에서 로그라인과 인물을 먼저 채우면 AI가 더 맞는 구조를 만들어요.", tone: .warn)
                        Button("설정 도우미") { go(.setup) }
                    }
                    HStack {
                        JobButton(model: model, kind: "arc", idle: "AI로 구조 만들기", prominent: true) { await model.planArc() }
                        Button("직접 나누기") { model.splitArc() }.buttonStyle(.bordered)
                    }
                    Text("직접 나누면 \(p.meta?.targetEpisodes ?? 0)화를 기 · 승 · 전 · 결 네 구간으로 나눠요. 구간 목표는 구간 고치기에서 적어요.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                if let pj = model.jobs.running("plots") {
                    NoteBox(text: "구간마다 초안을 만드는 중이에요\(pj.note.isEmpty ? "" : " (\(pj.note))"). 끝난 구간부터 카드가 채워지고, 채워진 화는 바로 고칠 수 있어요.")
                } else if eps.isEmpty {
                    NoteBox(text: "구간을 확인한 뒤 '화별 플롯 초안 만들기'를 누르면 각 구간에 화 카드가 채워져요.")
                }
                BoardView(model: model, board: PlotBoard(acts: acts, episodes: eps))
            }
            if !eps.isEmpty && eps.count == p.meta?.targetEpisodes && eps.allSatisfy({ PlotRules.status($0) == .finalized }) {
                Text("모든 화를 반영했어요. 장편으로 늘리기는 아직 웹에서 해요.").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// 구조 제안: 구간마다 지금 값과 바꿀 값을 나란히 보인다 (웹 `arcProposalCard`).
struct ArcProposalCard: View {
    let model: PlotModel
    let proposal: [Act]
    let current: [Act]

    var body: some View {
        CardBox {
            HStack {
                Text("AI 구조 제안").font(.headline)
                Chip(text: "적용 전", color: .purple)
                Spacer()
                Button("버리기") { model.dropArcProposal() }.buttonStyle(.bordered)
                Button(current.isEmpty ? "이 구조로 시작" : "이 구조로 바꾸기") { Task { await model.useArcProposal() } }.buttonStyle(.borderedProminent)
            }
            Text(current.isEmpty ? "고르면 구조가 생기고, 저장하면 작품에 들어가요." : "지금 값은 위, 바꿀 값은 아래예요. 바꿔도 저장하기 전에는 작품에 들어가지 않아요.")
                .font(.caption).foregroundStyle(.secondary)
            ForEach(Array(proposal.enumerated()), id: \.offset) { _, a in
                let old = current.first { $0.name == a.name }
                VStack(alignment: .leading, spacing: 4) {
                    Chip(text: a.name.rawValue, color: actColor(a.name))
                    row("범위", old.map { "\($0.startEp)~\($0.endEp)화" }, "\(a.startEp)~\(a.endEp)화")
                    row("구간 목표", old?.goal, a.goal)
                    row("전환점", old?.keyTurn, a.keyTurn ?? "")
                    row("서술 시점", old?.pov, a.pov ?? "")
                }
                .padding(.vertical, 4)
            }
        }
    }

    @ViewBuilder
    private func row(_ label: String, _ old: String?, _ new: String) -> some View {
        if (old ?? "") != new {
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.caption.bold()).foregroundStyle(.secondary)
                if let old, !old.isEmpty { Text(old).strikethrough().foregroundStyle(.red) }
                if !new.isEmpty { Text(new).foregroundStyle(.green) }
            }
        }
    }
}

// MARK: 보드

/// 기승전결 네 칸 보드 (웹 `actBoard`).
struct BoardView: View {
    let model: PlotModel
    let board: PlotBoard
    @Environment(\.plotSlots) private var slots

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 230), alignment: .top)], alignment: .leading, spacing: 12) {
            ForEach(board.columns, id: \.index) { col in column(col) }
            if !board.loose.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    HStack { Text("구간 밖").font(.headline); Spacer(); Text("\(board.loose.count)화").font(.caption) }
                    NoteBox(text: "어느 구간에도 들지 않는 화예요. 구간 범위를 고치면 제자리로 가요.", tone: .warn)
                    ForEach(board.loose, id: \.plot.number) { card($0) }
                }
            }
        }
    }

    private func column(_ col: PlotBoard.Column) -> some View {
        let a = col.act
        return VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(a.name.rawValue).font(.title3.bold())
                    Spacer()
                    Text("\(a.startEp)~\(a.endEp)화 · \(col.count)화").font(.caption).foregroundStyle(.secondary)
                }
                block("구간 목표", a.goal)
                block("전환점", a.keyTurn ?? "")
                if let pov = a.pov, !pov.isEmpty { block("서술 시점", pov) }
                Button("구간 고치기") { model.select(.act(col.index)) }.buttonStyle(.bordered).controlSize(.small)
            }
            .padding(10)
            .background(actColor(a.name).opacity(model.panel == .act(col.index) ? 0.25 : 0.1), in: RoundedRectangle(cornerRadius: 8))
            .accessibilityElement(children: .contain)
            .accessibilityLabel("\(a.name.rawValue) 구간")
            Text("화별 플롯\(col.episodes.isEmpty ? "" : " \(col.episodes.count)화")").font(.caption.bold()).foregroundStyle(.secondary)
            if let shared = col.shared { Text(shared).font(.caption).foregroundStyle(.secondary) }
            if col.episodes.isEmpty {
                ForEach(col.numbers, id: \.self) { n in
                    HStack(spacing: 6) {
                        if model.owns(n) { ProgressView().controlSize(.small) }
                        Text("\(n)화\(model.owns(n) ? " 만드는 중" : "")")
                    }
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 32, alignment: .leading)
                    .padding(.horizontal, 8)
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary, style: StrokeStyle(lineWidth: 1, dash: [4])))
                    .accessibilityHidden(true)
                }
            } else {
                ForEach(col.episodes, id: \.plot.number) { card($0) }
            }
        }
    }

    private func block(_ label: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2.bold()).foregroundStyle(.secondary)
            Text(text.isEmpty ? "비어 있음" : text).font(.caption).foregroundStyle(text.isEmpty ? .secondary : .primary)
        }
    }

    private func card(_ e: Episode) -> some View {
        let c = EpisodeCard(e, busy: model.owns(e.plot.number))
        let badges = model.project.map { slots.cardBadges($0, e.plot) } ?? AnyView(EmptyView())
        let selected = model.panel == .episode(c.number)
        return Button { model.select(.episode(c.number)) } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("\(c.number)화").font(.subheadline.bold())
                    Spacer()
                    if c.busy { ProgressView().controlSize(.mini); Chip(text: "새로 만드는 중", color: .purple) }
                    Chip(text: c.status.label, color: c.status.color)
                }
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(c.title).font(.subheadline)
                    badges
                }
                if !c.summary.isEmpty { Text(c.summary).font(.caption).foregroundStyle(.secondary).lineLimit(3) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background(.background, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(selected ? Color.accentColor : Color.secondary.opacity(0.25), lineWidth: selected ? 2 : 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(c.accessibilityLabel)
    }
}
#endif
