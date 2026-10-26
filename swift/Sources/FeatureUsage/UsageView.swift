#if canImport(SwiftUI)
import CanonCore
import CanonUI
import SwiftUI

/// 사용량 · 비용 화면 (웹 `usage.js` 의 `viewUsage`). 비용은 서버가 가격표로 계산한 추정치다.
public struct UsageView: View {
    @State private var model: UsageModel
    @State private var question: Question?
    @State private var jump: PriceDraft.ID?
    @FocusState private var chartFocused: Bool
    #if os(iOS)
    @Environment(\.horizontalSizeClass) private var sizeClass
    #endif

    /// 저장 · 되돌리기 전에 묻는 말.
    private enum Question: Identifiable {
        case save(String), reset
        var id: String { if case let .save(t) = self { t } else { "reset" } }
        var text: String { if case let .save(t) = self { t } else { UsageModel.resetQuestion } }
    }

    public init(model: UsageModel) {
        _model = State(initialValue: model)
    }

    private static let priceActions = "price-actions"

    private var narrow: Bool {
        #if os(iOS)
        sizeClass == .compact
        #else
        false
        #endif
    }

    public var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    filters
                    if let u = model.summary {
                        if u.total.calls == 0 {
                            note(UsageText.empty(project: model.project, titles: model.titles))
                        } else {
                            content(u)
                        }
                    } else if model.busy != nil {
                        Text("불러오는 중…").font(.caption).foregroundStyle(.secondary)
                    }
                    priceSection
                }
                .padding()
                .frame(maxWidth: 1100, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            // 줄은 가로 스크롤 안에 있어 세로로는 가격표 아래 버튼 줄로 옮긴다 (새 줄은 표 끝에 붙는다)
            .onChange(of: jump) { _, id in
                guard id != nil else { return }
                withAnimation { proxy.scrollTo(Self.priceActions, anchor: .bottom) }
                jump = nil
            }
        }
        // 알림은 어디까지 내려 봐도 보이게 아래에 띄운다 (웹의 toast)
        .safeAreaInset(edge: .bottom) {
            if let n = model.notice {
                Notice(n.text, isError: n.isError) { model.dismissNotice() }.padding()
            }
        }
        .navigationTitle(UsageText.title)
        .overlay(alignment: .top) {
            if let busy = model.busy {
                Label(busy, systemImage: "hourglass").font(.caption).padding(6)
                    .background(.thinMaterial, in: Capsule()).padding(.top, 4)
            }
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .alert(question?.text ?? "", isPresented: Binding(get: { question != nil }, set: { if !$0 { question = nil } })) {
            if case .reset = question {
                Button("되돌리기", role: .destructive) { Task { await model.reset() } }
            } else {
                Button("저장") { Task { await model.save() } }
            }
            Button("취소", role: .cancel) {}
        }
    }

    // MARK: 머리와 거르기

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(UsageText.intro).font(.callout).foregroundStyle(.secondary)
            if let url = URL(string: model.summary?.billingUrl ?? UsageText.defaultBillingURL) {
                Link(UsageText.billingLink, destination: url).buttonStyle(.bordered)
            }
        }
    }

    private var filters: some View {
        ViewThatFits(in: .horizontal) {
            HStack { daysPicker; Spacer(); projectPicker }
            VStack(alignment: .leading) { daysPicker; projectPicker }
        }
    }

    private var daysPicker: some View {
        Picker("기간", selection: Binding(get: { model.days }, set: { d in Task { await model.setDays(d) } })) {
            ForEach(UsageText.days, id: \.days) { Text($0.label).tag($0.days) }
        }
        .pickerStyle(.segmented)
        .fixedSize()
    }

    private var projectPicker: some View {
        Picker("작품", selection: Binding(get: { model.project }, set: { p in Task { await model.setProject(p) } })) {
            Text("모든 작품").tag("")
            ForEach(model.projectChoices, id: \.self) { Text(UsageText.projectName($0, titles: model.titles)).tag($0) }
        }
        .pickerStyle(.menu)
    }

    // MARK: 본문

    @ViewBuilder
    private func content(_ u: UsageSummary) -> some View {
        if !u.unpriced.isEmpty { unpriced(u.unpriced) }
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 160), alignment: .top)], alignment: .leading, spacing: 10) {
            ForEach(UsageText.tiles(u.total), id: \.title) { t in
                VStack(alignment: .leading, spacing: 4) {
                    Text(t.title).font(.caption).foregroundStyle(.secondary)
                    Text(t.value).font(.title2.weight(.semibold)).monospacedDigit()
                    Text(t.note).font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
            }
        }
        card { chart(UsageChart.make(u.byDay, days: model.days, narrow: narrow)) }
        // 웹의 좁은 화면 순서. 두 칸으로 놓으면 iPad 세로에서도 이름 칸이 너무 좁아진다
        table(.stage, u)
        table(.model, u)
        table(model.project.isEmpty ? .project : .episode, u)
        table(.source, u)
        calls(u)
    }

    private func unpriced(_ models: [String]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(UsageText.unpricedWarning, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
            FlowRow {
                ForEach(models, id: \.self) { m in
                    HStack(spacing: 4) {
                        Text(m.isEmpty ? "(이름 없음)" : m).font(.callout.monospaced())
                        if !m.isEmpty {
                            Button("가격 넣기") { jump = model.addModel(m) }.buttonStyle(.bordered).controlSize(.small)
                        }
                    }
                }
            }
        }
        .padding(10)
        .background(Color.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
    }

    // MARK: 막대

    private func chart(_ c: UsageChart) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(c.title).font(.headline)
                Spacer()
                Text(c.scale).font(.caption).foregroundStyle(.secondary)
            }
            HStack(alignment: .bottom, spacing: c.bars.count > 60 ? 1 : 2) {
                ForEach(c.bars) { b in
                    GeometryReader { g in
                        VStack(spacing: 0) {
                            Spacer(minLength: 0)
                            Rectangle()
                                .fill(model.bar == b.key ? Color.accentColor : Color.accentColor.opacity(0.55))
                                .frame(height: g.size.height * CGFloat(b.height) / 100)
                        }
                    }
                    .contentShape(Rectangle())
                    .onTapGesture { model.bar = b.key }
                    .accessibilityElement()
                    .accessibilityLabel(b.tip)
                    .accessibilityAddTraits(.isButton)
                }
            }
            .frame(height: 140)
            .padding(4)
            .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 6))
            .focusable()
            .focused($chartFocused)
            .onKeyPress(.leftArrow) { move(c, .left) }
            .onKeyPress(.rightArrow) { move(c, .right) }
            .onKeyPress(.home) { move(c, .home) }
            .onKeyPress(.end) { move(c, .end) }
            .accessibilityLabel(c.label)
            HStack { Text(c.first); Spacer(); Text(c.last) }.font(.caption).foregroundStyle(.secondary)
            Text(c.tip(model.bar) ?? UsageChart.hint).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func move(_ c: UsageChart, _ m: UsageChart.Move) -> KeyPress.Result {
        model.bar = c.move(m, from: model.bar)
        return .handled
    }

    // MARK: 묶음 표

    private func table(_ kind: UsageTableKind, _ u: UsageSummary) -> some View {
        let rows = UsageText.tableRows(kind, kind.rows(u), titles: model.titles)
        return card {
            VStack(alignment: .leading, spacing: 8) {
                Text(kind.title).font(.headline)
                if rows.isEmpty {
                    Text(kind.note.isEmpty ? "기록 없음" : kind.note).font(.caption).foregroundStyle(.secondary)
                } else {
                    Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                        GridRow {
                            Text(kind.column)
                            Text("호출").gridColumnAlignment(.trailing)
                            Text("입력").gridColumnAlignment(.trailing)
                            Text("출력").gridColumnAlignment(.trailing)
                            Text("추정 비용").gridColumnAlignment(.trailing)
                        }
                        .font(.caption).foregroundStyle(.secondary)
                        ForEach(Array(rows.enumerated()), id: \.offset) { _, r in
                            GridRow {
                                tableLabel(r).layoutPriority(1)
                                Text(r.calls).fixedSize()
                                Text(r.input).fixedSize()
                                Text(r.output).fixedSize()
                                VStack(alignment: .trailing, spacing: 2) {
                                    Text(r.cost).bold().fixedSize()
                                    share(r.share)
                                }
                            }
                            .font(.callout.monospacedDigit())
                        }
                    }
                    if !kind.note.isEmpty { Text(kind.note).font(.caption).foregroundStyle(.secondary) }
                }
            }
        }
    }

    @ViewBuilder
    private func tableLabel(_ r: UsageTableRow) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                if let p = r.project {
                    Button(r.label) { Task { await model.setProject(p) } }.buttonStyle(.borderless)
                } else if !r.label.isEmpty {
                    Text(r.label)
                }
                if r.failed > 0 { chip("실패 \(r.failed)", .red) }
                if r.batch > 0 { chip("배치 \(r.batch)", .secondary) }
            }
            if !r.sub.isEmpty { Text(r.sub).font(.caption).foregroundStyle(.secondary) }
        }
    }

    private func share(_ pct: Int) -> some View {
        Capsule().fill(.quaternary).frame(width: 60, height: 4)
            .overlay(alignment: .leading) { Capsule().fill(Color.accentColor).frame(width: 60 * CGFloat(pct) / 100, height: 4) }
            .accessibilityLabel("비중 \(pct)%")
    }

    // MARK: 호출 목록

    private func calls(_ u: UsageSummary) -> some View {
        let (_, shown) = model.calls
        return card {
            VStack(alignment: .leading, spacing: 10) {
                Picker("호출 목록", selection: $model.list) {
                    ForEach(UsageText.tabs(u), id: \.list) { Text($0.label).tag($0.list) }
                }
                .pickerStyle(.segmented)
                .fixedSize()
                if shown.isEmpty {
                    Text(UsageText.noTrouble).font(.caption).foregroundStyle(.secondary)
                } else {
                    ForEach(Array(shown.enumerated()), id: \.offset) { i, r in
                        if i > 0 { Divider() }
                        callRow(UsageText.callRow(r))
                    }
                    moreLine
                }
            }
        }
    }

    private func callRow(_ r: UsageCallRow) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(r.when).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                Text(r.place).font(.caption)
                Spacer()
                switch r.state {
                case .failed: chip(r.stateLabel, .red)
                case .retried: chip(r.stateLabel, .orange)
                case .ok: chip(r.stateLabel, .green)
                }
                Text(r.cost).bold().monospacedDigit()
            }
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(r.task).font(.callout)
                Text(r.detail).font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 4) {
                Text(r.model).font(.caption.monospaced())
                if r.batch { chip("배치", .secondary) }
            }
            Text(tokens(r)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            if !r.blocksTop.isEmpty {
                DisclosureGroup(r.blocksTop) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.promptChars)
                        ForEach(r.blocks, id: \.self) { Text($0) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .font(.caption)
            }
            if !r.error.isEmpty {
                if r.error != r.errorShort {
                    DisclosureGroup(r.errorShort) { Text(r.error).textSelection(.enabled) }.font(.caption).foregroundStyle(.red)
                } else {
                    Text(r.error).font(.caption).foregroundStyle(.red).textSelection(.enabled)
                }
            }
        }
    }

    /// '입력 12K (캐시 4,000) · 출력 3,500 (생각 500) · 12.3초 · 아낌 $0.0100'
    private func tokens(_ r: UsageCallRow) -> String {
        var parts = ["입력 \(r.input)" + (r.cached.isEmpty ? "" : " (\(r.cached))"),
                     "출력 \(r.output)" + (r.thought.isEmpty ? "" : " (\(r.thought))"),
                     r.seconds]
        if !r.saved.isEmpty { parts.append(r.saved) }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var moreLine: some View {
        if let m = model.moreLine {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    switch m.action {
                    case .showAll: Button(m.button ?? "") { model.expand() }.buttonStyle(.bordered)
                    case .loadMore:
                        Text(m.text)
                        Button(m.button ?? "") { Task { await model.loadMore() } }.buttonStyle(.bordered)
                    case .none: Text(m.text)
                    }
                }
                Text(UsageText.tokenNote)
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    // MARK: 가격표

    private var priceSection: some View {
        card {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text("AI 요금 가격표").font(.headline)
                    Spacer()
                    Text("USD / 100만 토큰").font(.caption).foregroundStyle(.secondary)
                }
                if let pr = model.prices {
                    priceIntro(pr)
                    ScrollView(.horizontal) { priceGrid }
                    HStack {
                        Button("줄 추가") { model.addRow() }
                        Button("가격표 저장") { trySave() }.buttonStyle(.borderedProminent).disabled(!model.dirty)
                        if model.dirty { Button("고친 것 버리기") { model.cancelEdits() } }
                        if model.canReset { Button("기본값으로 되돌리기", role: .destructive) { question = .reset } }
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.busy != nil)
                    .id(Self.priceActions)
                    Text(UsageText.priceFooter).font(.caption).foregroundStyle(.secondary)
                } else {
                    Text("불러오는 중…").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func priceIntro(_ pr: PriceTable) -> some View {
        var text = AttributedString("기본값은 \(pr.checked)에 ")
        var link = AttributedString("Google Gemini API 가격표")
        link.link = URL(string: pr.url)
        text += link
        text += AttributedString(UsageText.priceIntroTail)
        return Text(text).font(.callout).foregroundStyle(.secondary)
    }

    private var priceGrid: some View {
        Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 8) {
            GridRow {
                Text("모델")
                Text("적용 시작일")
                ForEach(PriceDraft.Field.allCases, id: \.self) { Text($0.label) }
                Text("")
            }
            .font(.caption).foregroundStyle(.secondary)
            ForEach(model.rows) { r in
                GridRow(alignment: .top) {
                    VStack(alignment: .leading, spacing: 2) {
                        TextField("모델 이름", text: field(r.id, \.model)).frame(width: 200)
                        if !r.status.isEmpty || !r.note.isEmpty {
                            HStack(spacing: 4) {
                                if !r.status.isEmpty { chip(r.status, r.custom == true ? .blue : r.upcoming ? .orange : .green) }
                                if !r.note.isEmpty { Text(r.note).font(.caption).foregroundStyle(.secondary) }
                            }
                        }
                    }
                    TextField("처음부터", text: field(r.id, \.since)).frame(width: 110)
                    ForEach(PriceDraft.Field.allCases, id: \.self) { f in
                        TextField(r.placeholder(f), text: Binding(get: { r[f] }, set: { v in model.edit(r.id) { $0[f] = v } }))
                            .frame(width: 80)
                            .accessibilityLabel("\(r.model) \(f.label)")
                        #if os(iOS)
                            .keyboardType(.decimalPad)
                        #endif
                    }
                    if r.fixed {
                        Text("기본 줄").font(.caption).foregroundStyle(.secondary)
                            .help("기본 줄은 지울 수 없어요. 값을 고치면 내 값으로 대신해요")
                    } else {
                        Button("지우기") { model.removeRow(r.id) }.buttonStyle(.bordered).controlSize(.small)
                            .accessibilityLabel("\(r.model.isEmpty ? "이름 없는" : r.model) 줄 지우기")
                    }
                }
                .textFieldStyle(.roundedBorder)
            }
        }
        .padding(.bottom, 4)
    }

    private func field(_ id: PriceDraft.ID, _ key: WritableKeyPath<PriceDraft, String>) -> Binding<String> {
        Binding(get: { model.rows.first { $0.id == id }?[keyPath: key] ?? "" },
                set: { v in model.edit(id) { $0[keyPath: key] = v } })
    }

    private func trySave() {
        switch model.checkSave() {
        case .ready: Task { await model.save() }
        case let .confirm(text): question = .save(text)
        case let .blocked(text, id):
            jump = id
            model.showError(text)
        }
    }

    // MARK: 조각

    private func card<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        content()
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(.background.secondary, in: RoundedRectangle(cornerRadius: 10))
    }

    private func note(_ text: String) -> some View {
        Text(text).padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
    }

    private func chip(_ text: String, _ color: Color) -> some View {
        Text(text).font(.caption2.weight(.medium)).lineLimit(1).fixedSize().padding(.horizontal, 6).padding(.vertical, 2)
            .foregroundStyle(color).background(color.opacity(0.12), in: Capsule())
    }
}

/// 줄을 넘기며 늘어놓는 칸 (가격 없는 모델 목록).
struct FlowRow: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, line: CGFloat = 0, widest: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                y += line + spacing
                x = 0
                line = 0
            }
            x += size.width + spacing
            line = max(line, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: widest, height: y + line)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, line: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                y += line + spacing
                x = bounds.minX
                line = 0
            }
            s.place(at: CGPoint(x: x, y: y), proposal: .unspecified)
            x += size.width + spacing
            line = max(line, size.height)
        }
    }
}
#endif
