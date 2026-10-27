#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 인과율: 요소 · 특징 · 설정 · 사건을 더하고, 관련 화 지도와 영향 분석 변경안을 본다 (웹 `viewCausal`).
public struct CausalView: View {
    @State private var model: CausalModel
    let go: (Screen) -> Void
    @State private var confirmDelete = false

    public init(document: ProjectDocument, jobs: JobCenter, service: any CausalService, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: CausalModel(document: document, jobs: jobs, service: service))
        self.go = go
    }

    public var body: some View {
        Group {
            if let p = model.project {
                content(p)
            } else if let error = model.document.error {
                ContentUnavailableView("작품을 불러오지 못했어요", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("불러오는 중")
            }
        }
        .task { await model.start() }
        .task(id: model.impactJobsKey) { await model.jobsChanged() }
        .task(id: model.linksKey) { await model.loadLinks() }
        .onChange(of: model.elements.map(\.id)) { model.fixSelection() }
        .alert(model.element.map { CausalText.deleteQuestion($0, dirty: model.document.dirty) } ?? "", isPresented: $confirmDelete) {
            Button("지우기", role: .destructive) { Task { await model.delete() } }
            Button("취소", role: .cancel) {}
        }
    }

    private func content(_ p: Project) -> some View {
        GeometryReader { geo in
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    if let n = model.notice { Notice(n.text, isError: n.isError) { model.dismissNotice() } }
                    if let el = model.gone {
                        HStack {
                            Text(CausalText.goneNote(el)).frame(maxWidth: .infinity, alignment: .leading)
                            Button("되살리기") { Task { await model.restore() } }.disabled(model.busy)
                        }
                        .note(.info)
                    }
                    if model.elements.isEmpty {
                        empty(p)
                    } else if geo.size.width > 720 {
                        HStack(alignment: .top, spacing: 16) {
                            list.frame(width: 260)
                            main(p)
                        }
                    } else {
                        list
                        main(p)
                    }
                }
                .padding()
                .frame(maxWidth: 1100, alignment: .leading)
            }
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text("인과율").font(.caption).foregroundStyle(.secondary)
                Text("요소 · 특징 · 설정 · 사건").font(.title2.bold())
                Text(CausalText.introSummary).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            if !model.elements.isEmpty {
                Button("+ 요소 추가") { model.add() }.buttonStyle(.borderedProminent)
            }
        }
    }

    private func empty(_ p: Project) -> some View {
        VStack(spacing: 10) {
            Text("아직 더한 요소가 없어요.")
            Text(CausalText.emptyExample(p)).font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Button("+ 요소 추가") { model.add() }.buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity)
        .padding(24)
        .card()
    }

    // MARK: 목록

    private var list: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !model.filterKinds.isEmpty {
                Flow(spacing: 6) {
                    filterButton(nil, "전부")
                    ForEach(model.filterKinds, id: \.self) { filterButton($0, $0.rawValue) }
                }
            }
            if model.shown.isEmpty { Text("이 종류의 요소가 없어요.").font(.caption).foregroundStyle(.secondary) }
            ForEach(model.shown, id: \.id) { el in
                Button { model.select(el.id) } label: { row(el) }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(el.id == model.selected ? .isSelected : [])
            }
        }
    }

    private func filterButton(_ kind: StoryElement.KindPayload?, _ label: String) -> some View {
        let on = model.kindFilter == kind
        return Button(label) { model.kindFilter = kind }
            .buttonStyle(.bordered).controlSize(.small).tint(on ? .accentColor : .secondary)
            .accessibilityAddTraits(on ? .isSelected : [])
    }

    private func row(_ el: StoryElement) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Chip((el.kind ?? .기타).rawValue, tint: .secondary)
                Spacer()
                if let b = CausalText.badge(el) { Chip(b.text, tint: b.tone.color) }
            }
            Text(CausalText.label(el)).font(.headline)
            let chars = (el.characters ?? []).map { model.names[$0] ?? $0 }
            Text(CausalText.timing(el) + (chars.isEmpty ? "" : " · " + chars.joined(separator: ", ")))
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(el.id == model.selected ? Color.accentColor.opacity(0.12) : Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(el.id == model.selected ? Color.accentColor : .clear))
        .contentShape(Rectangle())
    }

    // MARK: 본문

    @ViewBuilder
    private func main(_ p: Project) -> some View {
        if let el = model.element {
            VStack(alignment: .leading, spacing: 16) {
                ElementEditor(model: model, element: el, askDelete: { confirmDelete = true }).id(el.id)
                StripCard(model: model, element: el, project: p, go: go)
                ImpactCard(model: model, element: el, project: p)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: - 편집

struct ElementEditor: View {
    let model: CausalModel
    let element: StoryElement
    let askDelete: () -> Void
    @State private var episodesText = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("요소").font(.title3.bold())
                Spacer()
                Button("삭제", role: .destructive, action: askDelete).controlSize(.small).disabled(model.busy)
            }
            if let note = CausalText.foundNote(element) { Text(note).note(.plain) }
            HStack(alignment: .bottom, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    FieldLabel("종류")
                    Picker("종류", selection: Binding(get: { element.kind ?? .기타 }, set: { k in model.edit { $0.kind = k } })) {
                        ForEach(CausalText.kinds, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    .labelsHidden()
                }
                LabeledText("이름", text: text(\.name), placeholder: "본문과 플롯에서 찾을 이름")
            }
            LabeledText("설명", text: text(\.description), hint: "지켜야 할 내용을 구체적으로", placeholder: CausalText.hint(element.kind ?? .기타), lines: 3)
            ListField("다른 이름", items: Binding(get: { element.aliases ?? [] }, set: { v in model.edit { $0.aliases = v } }),
                      hint: "본문에서 다르게 부르는 말. 두 글자 이상", lines: 2)
            characters
            since
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    FieldLabel("나올 화", hint: "일어나거나 꼭 나와야 하는 화. 쉼표로")
                    TextField("예: 7, 12", text: $episodesText)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityLabel("나올 화")
                        .onSubmit(commitEpisodes)
                        .onChange(of: episodesText) { commitEpisodes() }
                }
                VStack(alignment: .leading, spacing: 4) {
                    FieldLabel("독자에게 드러나는 화", hint: "비우면 숨기지 않음. 그 전에는 암시만")
                    TextField("숨기지 않음", text: number(\.revealEp))
                        .textFieldStyle(.roundedBorder)
                        .accessibilityLabel("독자에게 드러나는 화")
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                FieldLabel("본문을 쓸 때 AI에 넣기")
                Picker("AI에 넣기", selection: Binding(get: { element.context ?? .auto }, set: { c in model.edit { $0.context = c } })) {
                    ForEach(CausalText.contexts.indices, id: \.self) { i in Text(CausalText.contexts[i].1).tag(CausalText.contexts[i].0) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                Text("관련 있을 때: 그 화에 관련 인물이 나오거나, 플롯에 이름이 있거나, 나올 화일 때만 넣어요.").font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .card()
        .onAppear { episodesText = (element.episodes ?? []).map(String.init).joined(separator: ", ") }
        .onChange(of: element.episodes ?? []) { _, eps in
            // 다시 불러오기 등으로 바깥에서 바뀌면 칸을 다시 채운다 (적는 중인 글이 같은 화를 뜻하면 그대로 둔다)
            if CausalText.parseEpisodes(episodesText) != eps { episodesText = eps.map(String.init).joined(separator: ", ") }
        }
    }

    private var characters: some View {
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel("관련 인물")
            let chars = model.project?.characters ?? []
            if chars.isEmpty {
                Text("인물이 아직 없어요.").font(.caption).foregroundStyle(.secondary)
            } else {
                Flow(spacing: 6) {
                    ForEach(chars, id: \.id) { c in
                        let on = (element.characters ?? []).contains(c.id)
                        Button { model.toggleCharacter(c.id) } label: {
                            Label(c.name.isEmpty ? c.id : c.name, systemImage: on ? "checkmark.square" : "square").font(.callout)
                        }
                        .buttonStyle(.bordered).controlSize(.small).tint(on ? .accentColor : .secondary)
                        .accessibilityAddTraits(on ? .isSelected : [])
                    }
                }
            }
        }
    }

    private var since: some View {
        let fromStart = (element.sinceEp ?? 0) <= 0
        return VStack(alignment: .leading, spacing: 6) {
            FieldLabel("언제부터 사실인가요?")
            HStack {
                Picker("사실이 되는 화", selection: Binding(get: { fromStart }, set: { model.setSince(start: $0) })) {
                    Text("처음부터 사실이었다").tag(true)
                    Text("어느 화부터 생긴다").tag(false)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .fixedSize()
                if !fromStart {
                    TextField("화", text: number(\.sinceEp, min: 1)).textFieldStyle(.roundedBorder).frame(width: 70)
                        .accessibilityLabel("생기는 화")
                    Text("화부터")
                }
            }
            Text(CausalText.sinceNote(element)).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func commitEpisodes() {
        let eps = CausalText.parseEpisodes(episodesText)
        if eps != (element.episodes ?? []) { model.edit { $0.episodes = eps } }
    }

    private func text(_ key: WritableKeyPath<StoryElement, String?>) -> Binding<String> {
        Binding(get: { element[keyPath: key] ?? "" }, set: { v in model.edit { $0[keyPath: key] = v } })
    }

    /// 숫자 칸. 0 은 비운다 (웹 `zeroBlank`). 숫자가 아닌 글은 받지 않는다.
    private func number(_ key: WritableKeyPath<StoryElement, Int?>, min: Int = 0) -> Binding<String> {
        Binding(get: {
            let v = element[keyPath: key] ?? 0
            return v == 0 ? "" : String(v)
        }, set: { s in
            let digits = s.filter(\.isNumber)
            let v = Swift.max(min, Int(digits) ?? 0)
            if v != (element[keyPath: key] ?? 0) { model.edit { $0[keyPath: key] = v } }
        })
    }
}

// MARK: - 관련 화 지도

struct StripCard: View {
    let model: CausalModel
    let element: StoryElement
    let project: Project
    let go: (Screen) -> Void
    @State private var focused: Int?

    var body: some View {
        let cells = CausalText.strip(element, links: model.links[element.id] ?? [], project: project, names: model.names)
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("관련 화 지도").font(.title3.bold())
                Spacer()
                Text("이름, 다른 이름, 관련 인물로 찾았어요 (AI 없이)").font(.caption).foregroundStyle(.secondary)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 36, maximum: 60), spacing: 4)], spacing: 4) {
                ForEach(cells) { c in
                    Button { focused = focused == c.ep ? nil : c.ep } label: { CellView(cell: c, focused: focused == c.ep) }
                        .buttonStyle(.plain)
                        .help(c.title)
                        .accessibilityLabel(c.title)
                }
            }
            if let n = focused, let c = cells.first(where: { $0.ep == n }) {
                HStack {
                    Text(c.title).font(.callout).frame(maxWidth: .infinity, alignment: .leading)
                    if c.hasText { Button("집필로") { go(.write) } } else { Button("플롯으로") { go(.arc) } }
                }
                .note(.plain)
            }
            legend(cells)
            let snippets = CausalText.snippets(model.links[element.id] ?? [])
            if !snippets.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(snippets.enumerated()), id: \.offset) { _, s in
                        (Text(s.head).bold() + Text("  " + s.text).foregroundStyle(.secondary)).font(.caption)
                    }
                }
            }
        }
        .card()
    }

    private func legend(_ cells: [CausalText.Cell]) -> some View {
        Flow(spacing: 10) {
            swatch(.red, "모순")
            swatch(.orange, "고칠 화")
            if cells.contains(where: { $0.kind == .done }) { swatch(.green, "반영함") }
            swatch(.accentColor, "언급 · 나올 화")
            Label { Text("관련 인물만 나옴") } icon: { RoundedRectangle(cornerRadius: 2).strokeBorder(Color.accentColor, style: .init(lineWidth: 1, dash: [2])).frame(width: 12, height: 12) }
            Label { Text("본문 있음") } icon: { Rectangle().fill(.secondary).frame(width: 12, height: 3) }
            if (element.sinceEp ?? 0) > 0 { Label { Text("생기는 화") } icon: { Rectangle().fill(Color.accentColor).frame(width: 3, height: 12) } }
            if (element.revealEp ?? 0) > 0 { Label { Text("드러나는 화") } icon: { Image(systemName: "eye") } }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func swatch(_ color: Color, _ text: String) -> some View {
        Label { Text(text) } icon: { RoundedRectangle(cornerRadius: 2).fill(color.opacity(0.25)).overlay(RoundedRectangle(cornerRadius: 2).stroke(color)).frame(width: 12, height: 12) }
    }
}

struct CellView: View {
    let cell: CausalText.Cell
    let focused: Bool

    var body: some View {
        let color = cell.kind.color
        VStack(spacing: 0) {
            Text("\(cell.ep)").font(.caption.monospacedDigit().bold())
            Text(cell.tag.isEmpty ? " " : cell.tag).font(.system(size: 9))
        }
        .frame(maxWidth: .infinity, minHeight: 36)
        .background(cell.kind == .none || cell.kind == .weak ? Color.clear : color.opacity(0.18), in: RoundedRectangle(cornerRadius: 4))
        .overlay {
            RoundedRectangle(cornerRadius: 4).strokeBorder(cell.kind == .none ? Color.secondary.opacity(0.3) : color,
                                                           style: .init(lineWidth: focused ? 2 : 1, dash: cell.kind == .weak ? [2] : []))
        }
        .overlay(alignment: .bottom) { if cell.hasText { Rectangle().fill(.secondary).frame(height: 3).padding(.horizontal, 3) } }
        .overlay(alignment: .leading) { if cell.since { Rectangle().fill(Color.accentColor).frame(width: 3) } }
        .overlay(alignment: .topTrailing) { if cell.reveal { Image(systemName: "eye").font(.system(size: 8)).padding(2) } }
        .opacity(cell.before ? 0.5 : 1)
    }
}

// MARK: - 영향 분석

struct ImpactCard: View {
    let model: CausalModel
    let element: StoryElement
    let project: Project

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("영향 분석").font(.title3.bold())
                Spacer()
                if let busy = model.analyzing {
                    Button(busy) {}.disabled(true)
                } else if element.impact != nil {
                    Button("다시 분석") { Task { await model.analyze() } }
                } else {
                    Button("영향 분석") { Task { await model.analyze() } }.buttonStyle(.borderedProminent)
                }
            }
            if let imp = element.impact {
                report(imp)
            } else {
                Text(CausalText.why(lastWritten: model.lastWritten)).note(.info)
            }
        }
        .card()
    }

    private var eps: [Int: Episode] {
        Dictionary((project.episodes ?? []).map { ($0.plot.number, $0) }, uniquingKeysWith: { a, _ in a })
    }

    @ViewBuilder
    private func report(_ imp: ElementImpact) -> some View {
        let r = imp.report
        let open = imp.outcome ?? ._empty_ == ._empty_
        if CausalText.stale(element) { Text(CausalText.staleNote).note(.warn) }
        HStack(spacing: 6) {
            Text("\(KoreanText.date(imp.at ?? "")) 분석").font(.caption).foregroundStyle(.secondary)
            if imp.outcome == .applied { Chip("적용함 · \(CausalText.appliedText(imp))", tint: .green) }
            if imp.outcome == .dismissed { Chip("버림", tint: .secondary) }
        }
        Text(r.summary).textSelection(.enabled)
        if open, CausalText.suggestsTiming(r) { Text(CausalText.timingTip).note(.info) }
        if open {
            details(r, open: true)
            if !(r.episodes ?? []).isEmpty || !(r.patches ?? []).isEmpty || !(r.newFacts ?? []).isEmpty {
                HStack {
                    Spacer()
                    Button("버리기") { Task { await model.dismiss() } }
                    Button("고른 것 적용") { Task { await model.apply() } }.buttonStyle(.borderedProminent)
                }
                .disabled(model.busy)
            }
        } else {
            DisclosureGroup("분석 내용 다시 보기") {
                VStack(alignment: .leading, spacing: 12) {
                    details(r, open: false)
                    if imp.outcome == .dismissed {
                        Button("다시 검토") { Task { await model.reopen() } }.disabled(model.busy)
                    }
                }
                .padding(.top, 8)
            }
        }
    }

    @ViewBuilder
    private func details(_ r: ImpactReport, open: Bool) -> some View {
        let conflicts = r.conflicts ?? []
        if !conflicts.isEmpty {
            Text("어긋나는 곳 \(conflicts.count)").font(.headline)
            ForEach(Array(conflicts.enumerated()), id: \.offset) { _, c in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        Chip(c.target.rawValue + ((c.episode ?? 0) > 0 ? " · \(c.episode!)화" : ""), tint: .secondary)
                        Chip(c.fix.rawValue, tint: CausalText.fixTone(c.fix).color)
                    }
                    Text(c.quote).italic().padding(.leading, 8).overlay(alignment: .leading) { Rectangle().fill(.secondary).frame(width: 2) }
                    Text(c.problem)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.red.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
            }
        }
        let plots = r.episodes ?? []
        if !plots.isEmpty {
            Text("플롯 고치기").font(.headline)
            ForEach(plots, id: \.number) { e in
                let cur = eps[e.number]
                let locked = CausalText.locked(cur)
                part(open: open, part: "ep:\(e.number)", disabled: locked) {
                    Text("\(e.number)화").bold() + Text(" \(e.title)") + Text(cur.map { "  \(CausalText.status($0).label)" } ?? "").font(.caption).foregroundStyle(.secondary)
                } content: {
                    if let note = CausalText.plotNote(cur, open: open) { Text(note.text).note(note.warn ? .warn : .plain) }
                    DiffRows(rows: CausalText.plotDiff(e, current: cur?.plot, names: model.names, lines: model.lineNames))
                }
            }
        }
        let patches = r.patches ?? []
        if !patches.isEmpty {
            Text("이미 쓴 본문 고치기").font(.headline)
            ForEach(Array(patches.enumerated()), id: \.offset) { i, t in
                let cur = eps[t.episode]
                part(open: open, part: "patch:\(i)", disabled: false) {
                    Text("\(t.episode)화 본문").bold() + Text(cur.map { "  \(CausalText.status($0).label)" } ?? "").font(.caption).foregroundStyle(.secondary)
                } content: {
                    if open, let cur, CausalText.status(cur) == .finalized { Text(CausalText.finalizedPatchNote).note(.warn) }
                    Text(t.quote).strikethrough().foregroundStyle(.red)
                    Text(t.replacement).foregroundStyle(.green)
                    if let why = t.reason, !why.isEmpty { Text(why).font(.caption).foregroundStyle(.secondary) }
                }
            }
        }
        let facts = r.newFacts ?? []
        if !facts.isEmpty {
            Text("설명으로 덮기").font(.headline)
            ForEach(Array(facts.enumerated()), id: \.offset) { i, f in
                part(open: open, part: "fact:\(i)", disabled: false) {
                    Text("확정 사실 더하기").bold()
                } content: {
                    Text(f).foregroundStyle(.green)
                }
            }
        }
    }

    /// 체크 하나와 그 내용 (웹 `prop-part`). 닫힌 분석은 체크 없이 보인다.
    private func part(open: Bool, part: String, disabled: Bool, @ViewBuilder title: () -> Text, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if open {
                Toggle(isOn: Binding(get: { model.isPicked(part) && !disabled }, set: { model.setPicked(part, $0) })) { title() }
                    .toggleStyle(.checkbox)
                    .disabled(disabled)
            } else {
                title()
            }
            content()
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
    }
}

struct DiffRows: View {
    let rows: [CausalText.DiffRow]

    var body: some View {
        if rows.isEmpty {
            Text("지금 플롯과 같아요.").font(.caption).foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(row.label).font(.caption.bold()).foregroundStyle(.secondary)
                        if row.ordered {
                            if !row.removed.isEmpty { numbered(row.removed).strikethrough().foregroundStyle(.red) }
                            numbered(row.added).foregroundStyle(.green)
                        } else {
                            ForEach(Array(row.removed.enumerated()), id: \.offset) { _, x in Text(x).strikethrough().foregroundStyle(.red) }
                            ForEach(Array(row.added.enumerated()), id: \.offset) { _, x in Text(x).foregroundStyle(.green) }
                        }
                    }
                }
            }
            .font(.callout)
        }
    }

    private func numbered(_ items: [String]) -> Text {
        Text(items.enumerated().map { "\($0.offset + 1). \($0.element)" }.joined(separator: "\n"))
    }
}

// MARK: - 조각

extension CausalText.Tone {
    var color: Color {
        switch self {
        case .plain: .secondary
        case .warn: .orange
        case .done: .green
        }
    }
}

extension CausalText.CellKind {
    var color: Color {
        switch self {
        case .bad: .red
        case .plot: .orange
        case .done: .green
        case .rel, .weak: .accentColor
        case .none: .secondary
        }
    }
}

/// 작은 표 (웹 `.chip`).
struct Chip: View {
    let text: String
    let tint: Color

    init(_ text: String, tint: Color) {
        self.text = text
        self.tint = tint
    }

    var body: some View {
        Text(text).font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2)
            .foregroundStyle(tint)
            .background(tint.opacity(0.15), in: Capsule())
    }
}

enum NoteKind { case info, warn, error, plain }

extension View {
    /// 안내 띠 (웹 `.note`).
    func note(_ kind: NoteKind) -> some View {
        let color: Color = switch kind {
        case .info: .blue
        case .warn: .orange
        case .error: .red
        case .plain: .secondary
        }
        return self.font(.callout).padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }

    /// 카드 (웹 `.card`).
    func card() -> some View {
        self.padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
    }
}

#if os(iOS)
extension ToggleStyle where Self == SwitchToggleStyle {
    /// iOS 에는 체크 상자가 없어 스위치로 보인다.
    static var checkbox: SwitchToggleStyle { .switch }
}
#endif
#endif
