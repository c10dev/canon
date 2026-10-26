#if canImport(SwiftUI)
import CanonAPI
import CanonUI
import SwiftUI

/// 복선 센터. 복선마다 심은 문장 · 회수한 문장, 회수율, 끊어진 연결, 회수 예정이 지난 복선을 본다.
/// 계산은 서버(`foreshadows.center`)가 하고, 작가가 고친 것은 서버가 바로 저장한다.
public struct ForeshadowView: View {
    @State private var model: ForeshadowModel

    public init(server: CanonServer, project: String) {
        _model = State(initialValue: ForeshadowModel(service: LiveForeshadowService(server: server, project: project)))
    }

    public init(model: ForeshadowModel) {
        _model = State(initialValue: model)
    }

    public var body: some View {
        List {
            Section {
                Text(ForeshadowText.intro).font(.callout).foregroundStyle(.secondary)
                if let error = model.error {
                    Notice(error, isError: true) { model.dismissError() }
                }
                if let busy = model.busy {
                    HStack(spacing: 8) { ProgressView(); Text(busy) }
                }
            }
            if let c = model.center {
                SummarySection(center: c, model: model)
                if model.adding { AddSection(center: c, model: model) }
                ListSection(center: c, model: model)
            } else if model.loading {
                Section { Text("불러오는 중…").foregroundStyle(.secondary) }
            }
        }
        .navigationTitle("복선 센터")
        .toolbar {
            Button(model.adding ? "닫기" : "+ 복선 직접 더하기") { model.adding.toggle() }
        }
        .refreshable { await model.load() }
        .task { await model.load() }
    }
}

/// 숫자 요약, 끊어진 연결 정리, 범례.
private struct SummarySection: View {
    let center: ForeshadowCenter
    let model: ForeshadowModel

    var body: some View {
        Section {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), alignment: .leading)], alignment: .leading, spacing: 12) {
                number("복선", "\(center.total)")
                number("열림", "\(center.open)")
                VStack(alignment: .leading, spacing: 4) {
                    number("회수율", ForeshadowText.rate(center))
                    ProgressView(value: center.rate ?? 0).tint(.green).accessibilityHidden(true)
                }
                number("예정 지남", "\(center.overdue)", warn: center.overdue > 0 ? .orange : nil)
                number("50화 넘게 묵음", "\(center.stale)", warn: center.stale > 0 ? .orange : nil)
                number("끊어진 연결", "\(center.broken)", warn: center.broken > 0 ? .red : nil)
            }
            .padding(.vertical, 4)
            if center.broken > 0 {
                VStack(alignment: .leading, spacing: 8) {
                    Label(ForeshadowText.brokenNote(center), systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                    Button("끊어진 연결 정리") { Task { await model.apply(.prune) } }
                        .buttonStyle(.bordered)
                        .disabled(model.busy != nil)
                }
            }
            Legend(done: center.done)
        }
    }

    private func number(_ label: String, _ value: String, warn: Color? = nil) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title2.bold()).foregroundStyle(warn ?? .primary)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct Legend: View {
    let done: Int

    var body: some View {
        ViewThatFits {
            HStack(spacing: 14) { items }
            VStack(alignment: .leading, spacing: 4) { items }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    @ViewBuilder
    private var items: some View {
        key(Circle().fill(Color.accentColor), "심은 문장")
        key(Circle().fill(Color.green), "회수한 문장")
        key(Rectangle().fill(Color.orange).frame(width: 2), "회수 예정")
        key(DashedLine().stroke(Color.green, style: StrokeStyle(lineWidth: 2, dash: [3, 2])).frame(width: 2), "플롯에서 회수 예정")
        key(Circle().fill(Color.red), "끊어진 연결")
        Text("세로선은 \(done)화(마지막 반영)")
    }

    private func key(_ mark: some View, _ text: String) -> some View {
        HStack(spacing: 4) { mark.frame(width: 10, height: 10); Text(text) }
    }
}

/// 복선 직접 더하기.
private struct AddSection: View {
    let center: ForeshadowCenter
    let model: ForeshadowModel
    @State private var description = ""
    @State private var scope: ForeshadowScope = .arc
    @State private var due = ""
    @State private var episode = ""

    var body: some View {
        Section {
            TextField("내용", text: $description, prompt: Text("예: 서윤의 목걸이에 새겨진 문양"))
            Picker("회수 범위", selection: $scope) {
                ForEach(ForeshadowScope.allCases, id: \.self) { Text(ForeshadowText.scope($0)).tag($0) }
            }
            EpisodeField(label: "회수 예정 화", text: $due, prompt: "미정")
            EpisodeField(label: "심은 화", text: $episode, prompt: "")
            HStack {
                Button("더하기") {
                    let change = ForeshadowChange.add(description: description, episode: Int(episode) ?? 0,
                                                      scope: scope, due: ForeshadowText.number(due))
                    Task { await model.apply(change) }
                }
                .buttonStyle(.borderedProminent)
                Button("닫기") { model.adding = false }.buttonStyle(.bordered)
            }
            .disabled(model.busy != nil)
        } header: {
            Text("복선 직접 더하기")
        } footer: {
            Text(ForeshadowText.addHint)
        }
        .onAppear { episode = "\(ForeshadowText.addEpisode(center))" }
    }
}

/// 탭 · 범위로 거른 복선 목록.
private struct ListSection: View {
    let center: ForeshadowCenter
    @Bindable var model: ForeshadowModel

    var body: some View {
        Section {
            Picker("복선 거르기", selection: $model.tab) {
                ForEach(ForeshadowTab.allCases) { Text(ForeshadowText.tab($0, center)).tag($0) }
            }
            .pickerStyle(.segmented)
            Picker("범위", selection: $model.scope) {
                Text("전체").tag(ForeshadowScope?.none)
                ForEach(ForeshadowScope.allCases, id: \.self) { Text(ForeshadowText.scope($0)).tag(Optional($0)) }
            }
            let items = model.shown
            if items.isEmpty {
                Text(ForeshadowText.empty).foregroundStyle(.secondary)
            }
            ForEach(items, id: \.id) { item in
                ItemRow(item: item, center: center, model: model)
            }
        }
    }
}

private struct ItemRow: View {
    let item: ForeshadowItem
    let center: ForeshadowCenter
    let model: ForeshadowModel

    var body: some View {
        let open = model.expanded.contains(item.id)
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 6) {
                    chips
                    (Text(item.description) + Text("  \(item.id)").font(.caption).foregroundStyle(.secondary))
                    Text(ForeshadowText.meta(item)).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                Button(open ? "접기" : "자세히") { model.toggle(item.id) }
                    .buttonStyle(.bordered)
                    .accessibilityValue(open ? "펼침" : "접힘")
            }
            TrackView(track: ForeshadowTrack(item, last: center.lastEp, done: center.done))
            if open {
                ClueList(item: item, model: model)
                ItemEditor(item: item, done: center.done, model: model)
                    .id("\(item.id)-\(item.hashValue)")
            }
        }
        .padding(.vertical, 6)
    }

    private var chips: some View {
        FlowRow {
            Chip(ForeshadowText.status(item), color: item.status == .resolved ? .green : .accentColor)
            Chip(ForeshadowText.scope(item.scope), color: .secondary)
            ForEach(ForeshadowText.flags(item), id: \.self) { flag in
                Chip(flag, color: flag.hasPrefix("끊어진") ? .red : .orange)
            }
        }
    }
}

/// 걸린 문장 목록과 연결 지우기.
private struct ClueList: View {
    let item: ForeshadowItem
    let model: ForeshadowModel

    var body: some View {
        let rows = ForeshadowText.clues(item)
        if rows.isEmpty {
            Text(ForeshadowText.noClues).font(.caption).foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(rows) { row in
                    HStack(alignment: .top, spacing: 10) {
                        Chip(row.label, color: row.payoff ? .green : .accentColor)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("“\(row.clue.quote)”")
                                .font(.system(.callout, design: .serif))
                                .strikethrough(row.clue.broken)
                                .foregroundStyle(row.clue.broken ? Color.red : Color.primary)
                            HStack(spacing: 6) {
                                if row.byAuthor { Text("작가") }
                                if row.clue.broken { Text("본문에서 사라짐").foregroundStyle(.red) }
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                        Button("지우기") {
                            Task { await model.apply(.dropClue(id: item.id, episode: row.clue.episode, quote: row.clue.quote)) }
                        }
                        .buttonStyle(.borderless)
                        .disabled(model.busy != nil)
                        .accessibilityLabel("이 문장 연결 지우기")
                    }
                }
            }
        }
    }
}

/// 내용 · 회수 범위 · 회수 예정 화 고치기, 회수로 표시 · 다시 열기, 지우기.
private struct ItemEditor: View {
    let item: ForeshadowItem
    let model: ForeshadowModel
    @State private var description: String
    @State private var scope: ForeshadowScope
    @State private var due: String
    @State private var resolveAt: String
    @State private var confirmRemove = false

    init(item: ForeshadowItem, done: Int, model: ForeshadowModel) {
        self.item = item
        self.model = model
        _description = State(initialValue: item.description)
        _scope = State(initialValue: item.scope)
        _due = State(initialValue: item.dueEp.map(String.init) ?? "")
        _resolveAt = State(initialValue: "\(ForeshadowText.resolveEpisode(item, done: done))")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("내용", text: $description)
                .textFieldStyle(.roundedBorder)
            HStack(spacing: 24) {
                Picker("회수 범위", selection: $scope) {
                    ForEach(ForeshadowScope.allCases, id: \.self) { Text(ForeshadowText.scope($0)).tag($0) }
                }
                .fixedSize()
                EpisodeField(label: "회수 예정 화", text: $due, prompt: "미정")
            }
            FlowRow {
                Button("저장") {
                    let change = ForeshadowChange.edit(id: item.id, description: description, scope: scope,
                                                       due: ForeshadowText.number(due))
                    Task { await model.apply(change) }
                }
                .buttonStyle(.borderedProminent)
                if item.status == .open {
                    HStack(spacing: 6) {
                        EpisodeField(label: "회수한 화", text: $resolveAt, prompt: "")
                        Button("회수로 표시") {
                            Task { await model.apply(.resolve(id: item.id, episode: Int(resolveAt) ?? 0)) }
                        }
                        .buttonStyle(.bordered)
                    }
                } else {
                    Button("다시 열기") { Task { await model.apply(.reopen(id: item.id)) } }
                        .buttonStyle(.bordered)
                }
                Button("복선 지우기", role: .destructive) { confirmRemove = true }
                    .buttonStyle(.bordered)
            }
            .disabled(model.busy != nil)
        }
        // iPad 의 List 줄 안에서는 confirmationDialog 가 뜨지 않아 alert 로 묻는다
        .alert(ForeshadowText.removeConfirm, isPresented: $confirmRemove) {
            Button("복선 지우기", role: .destructive) { Task { await model.apply(.remove(id: item.id)) } }
            Button("취소", role: .cancel) {}
        }
    }
}

/// 화 번호 칸.
private struct EpisodeField: View {
    let label: String
    @Binding var text: String
    let prompt: String

    var body: some View {
        LabeledContent(label) {
            TextField(label, text: $text, prompt: Text(prompt))
                .multilineTextAlignment(.trailing)
                .frame(width: 70)
                .textFieldStyle(.roundedBorder)
                #if os(iOS)
                .keyboardType(.numberPad)
                #endif
        }
        .fixedSize()
    }
}

/// 화 막대 (웹 `fsTrack`).
private struct TrackView: View {
    let track: ForeshadowTrack

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            ZStack(alignment: .topLeading) {
                Rectangle().fill(Color.secondary.opacity(0.3)).frame(width: w, height: 2).offset(y: 8)
                Capsule().fill(Color.accentColor.opacity(0.3))
                    .frame(width: max(0, (track.spanTo - track.spanFrom) * w), height: 4)
                    .offset(x: track.spanFrom * w, y: 7)
                if let now = track.now {
                    Rectangle().fill(Color.secondary).frame(width: 1, height: 22).offset(x: now * w, y: -2)
                }
                ForEach(Array(track.ticks.enumerated()), id: \.offset) { _, tick in
                    if tick.kind == .due {
                        Rectangle().fill(Color.orange).frame(width: 2, height: 18).offset(x: tick.at * w - 1)
                    } else {
                        DashedLine().stroke(Color.green, style: StrokeStyle(lineWidth: 2, dash: [3, 2]))
                            .frame(width: 2, height: 18).offset(x: tick.at * w - 1)
                    }
                }
                ForEach(Array(track.dots.enumerated()), id: \.offset) { _, dot in
                    Circle().fill(color(dot.kind))
                        .overlay(Circle().stroke(Color(white: 1, opacity: 0.9), lineWidth: 2))
                        .frame(width: 12, height: 12)
                        .offset(x: dot.at * w - 6, y: 3)
                }
            }
        }
        .frame(height: 18)
        .padding(.horizontal, 6)
        .accessibilityHidden(true)
    }

    private func color(_ kind: ForeshadowTrack.Dot) -> Color {
        switch kind {
        case .plant: .accentColor
        case .payoff: .green
        case .broken: .red
        }
    }
}

private struct DashedLine: Shape {
    func path(in rect: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: rect.midX, y: rect.minY))
            p.addLine(to: CGPoint(x: rect.midX, y: rect.maxY))
        }
    }
}

private struct Chip: View {
    let text: String
    let color: Color

    init(_ text: String, color: Color) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .foregroundStyle(color)
            .background(color.opacity(0.12), in: Capsule())
    }
}

/// 줄이 넘치면 다음 줄로 넘기는 가로 배치.
private struct FlowRow: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        return CGSize(width: rows.map(\.width).max() ?? 0, height: rows.reduce(0) { $0 + $1.height } + spacing * CGFloat(max(0, rows.count - 1)))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for i in row.items {
                let size = subviews[i].sizeThatFits(.unspecified)
                subviews[i].place(at: CGPoint(x: x, y: y + (row.height - size.height) / 2), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row { var items: [Int] = []; var width: CGFloat = 0; var height: CGFloat = 0 }

    private func arrange(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows = [Row()]
        for i in subviews.indices {
            let size = subviews[i].sizeThatFits(.unspecified)
            if !rows[rows.count - 1].items.isEmpty && rows[rows.count - 1].width + spacing + size.width > width {
                rows.append(Row())
            }
            var row = rows[rows.count - 1]
            row.width += (row.items.isEmpty ? 0 : spacing) + size.width
            row.height = max(row.height, size.height)
            row.items.append(i)
            rows[rows.count - 1] = row
        }
        return rows
    }
}
#endif
