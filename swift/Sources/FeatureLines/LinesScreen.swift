#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 이야기 줄기 화면 (웹 `viewLines`): 노선도, 줄기 목록 · 편집, 화 붙이기, AI 제안.
/// 화 점을 누르면 기승전결 · 플롯 화면으로 옮긴다 (그 화를 여는 것은 아직 웹만 한다).
public struct LinesScreen: View {
    @State private var model: LinesModel
    let go: (Screen) -> Void

    public init(document: ProjectDocument, jobs: JobCenter, server: CanonServer, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: LinesModel(document: document, jobs: jobs, service: LiveLinesService(server: server, project: document.name)))
        self.go = go
    }

    public init(model: LinesModel, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: model)
        self.go = go
    }

    public var body: some View {
        Group {
            if let p = model.project {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header
                        notices(p)
                        LineMapCard(model: model, project: p) { _ in go(.arc) }
                        ViewThatFits(in: .horizontal) {
                            HStack(alignment: .top, spacing: 16) {
                                LineList(model: model, project: p).frame(width: 300)
                                main(p).frame(minWidth: 440)
                            }
                            VStack(alignment: .leading, spacing: 16) {
                                LineList(model: model, project: p)
                                main(p)
                            }
                        }
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
        .navigationTitle("이야기 줄기")
        .confirmationDialog(model.ask?.message ?? "", isPresented: askShown, titleVisibility: .visible, presenting: model.ask) { ask in
            Button(ask.button, role: ask.destructive ? .destructive : nil) { Task { await ask.run() } }
        }
        .task {
            await model.document.load()
            model.syncResults()
        }
        .onChange(of: model.jobs.results) { model.syncResults() }
        .refreshable { await model.document.load() }
    }

    private var askShown: Binding<Bool> {
        Binding(get: { model.ask != nil }, set: { if !$0 { model.ask = nil } })
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 6) {
                Text("메인 · 서브플롯 · 회상 · 외전").font(.caption).foregroundStyle(.secondary)
                Text("이야기 줄기").font(.title.bold())
                Text("메인 줄기에서 갈라졌다 다시 합류하는 서브플롯, 과거 회상, 외전, 인물 이야기를 한눈에 봐요. 화마다 어느 줄기를 따라가는지, 메인 화 안에 어느 줄기 장면이 끼어드는지 표시하면 본문을 쓸 때 AI가 그 줄기의 맥락과 시점을 지켜요.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            Button("+ 줄기 추가") { model.newLine() }.buttonStyle(.bordered)
        }
    }

    @ViewBuilder
    private func notices(_ p: Project) -> some View {
        if let n = model.notice {
            Notice(n.text, isError: n.isError) { model.dismissNotice() }
        }
        if let f = model.failure {
            HStack {
                Text("AI 줄기 제안이 실패했어요: \(f.error)").frame(maxWidth: .infinity, alignment: .leading)
                Button("다시 시도") { Task { await model.retry() } }
                Button("닫기") { Task { await model.dismissFailure() } }
            }
            .font(.callout)
            .padding(10)
            .background(Color.red.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
        }
        if (p.episodes ?? []).isEmpty {
            LinesNote(text: "화별 플롯이 생기면 화를 줄기에 붙일 수 있어요. 줄기는 지금 만들어 둬도 돼요.")
        }
    }

    @ViewBuilder
    private func main(_ p: Project) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            if let s = model.selected { LineEditor(model: model, project: p, line: s) { _ in go(.arc) } }
            SuggestPanel(model: model, project: p)
        }
    }
}

/// 줄기 목록 (웹 `lineList`).
struct LineList: View {
    let model: LinesModel
    let project: Project

    var body: some View {
        let lines = LineRules.lines(project)
        if lines.isEmpty {
            LinesCard {
                Text("아직 갈라진 줄기가 없어요.")
                Text("예: 주인공의 빚(서브플롯), 친구가 떠난 밤(과거 회상, 10년 전)").font(.caption).foregroundStyle(.secondary)
            }
        } else {
            VStack(spacing: 8) {
                ForEach(lines, id: \.id) { s in
                    Button { model.select(s.id) } label: { row(s) }
                        .buttonStyle(.plain)
                        .accessibilityAddTraits(s.id == model.selected?.id ? .isSelected : [])
                }
            }
        }
    }

    private func row(_ s: Storyline) -> some View {
        let sel = s.id == model.selected?.id
        let color = Color(lineHex: LineRules.color(project, s.id))
        return VStack(alignment: .leading, spacing: 4) {
            HStack {
                LineBadgeView(text: LineRules.kind(s).rawValue, color: color)
                Spacer()
                Text(LineRules.rangeLabel(project, s)).font(.caption).foregroundStyle(.secondary)
            }
            Text(LineRules.title(s)).font(.headline)
            Text(LineRules.listDetail(project, s)).font(.caption).foregroundStyle(.secondary)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(sel ? color.opacity(0.12) : Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(sel ? color : .clear, lineWidth: 1.5))
        .contentShape(Rectangle())
    }
}

/// 고른 줄기 고치기와 화 붙이기 (웹 `lineEditor`).
struct LineEditor: View {
    @Bindable var model: LinesModel
    let project: Project
    let line: Storyline
    let openPlot: (Int) -> Void

    var body: some View {
        LinesCard {
            HStack {
                Text("줄기").font(.title3.bold())
                Spacer()
                Button("삭제", role: .destructive) { model.delete() }.controlSize(.small).disabled(model.busy)
            }
            KindPicker(kind: Binding(get: { LineRules.kind(line) }, set: { k in model.edit { $0.kind = k } }))
            LabeledText("이름", text: text(\.title), placeholder: "예: 주인공이 진 빚")
            FocusPicker(project: project, focus: line.focus ?? []) { model.toggleFocus($0) }
            LabeledText("이야기 속 시점", text: text(\.when), hint: "메인과 같은 시간이면 비워 두세요", placeholder: "예: 10년 전")
            LabeledText("풀어 갈 것", text: text(\.goal), placeholder: "이 줄기가 답할 질문")
            HStack(alignment: .top, spacing: 12) {
                EpisodeNumberField(label: "갈라지는 화", hint: "메인에서 이 줄기를 부르는 계기가 나오는 화", placeholder: "정하지 않음", value: number(\.branchEp))
                EpisodeNumberField(label: "합류하는 화", hint: "메인으로 돌아오는 화", placeholder: "아직 열림", value: number(\.joinEp))
            }
            let notes = LineRules.rangeNotes(project, line)
            if !notes.isEmpty { LinesNote(text: notes.joined(separator: "\n"), warn: true) }
            LabeledText("합류할 때 메인에 남기는 것", text: text(\.rejoin), placeholder: "드러나는 비밀, 바뀐 관계, 얻거나 잃는 것", lines: 2)
            LabeledText("줄기 요약", text: text(\.summary), hint: "비워 두면 이 줄기 화들의 요약을 써요", lines: 3)
            attached
            tagRow
            Text(LineRules.timeNote(line)).font(.caption).foregroundStyle(.secondary)
        }
    }

    private var attached: some View {
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel("붙은 화")
            let eps = LineRules.episodes(project, line.id)
            if eps.isEmpty {
                Text("아직 없어요.").font(.caption).foregroundStyle(.secondary)
            } else {
                Flow(spacing: 6) {
                    ForEach(eps, id: \.n) { e in
                        HStack(spacing: 2) {
                            Button("\(e.n)화\(e.role == .thread ? " 장면" : "")") { openPlot(e.n) }
                            Button { model.untag(e.n) } label: { Image(systemName: "xmark") }
                                .accessibilityLabel("\(e.n)화를 이 줄기에서 빼기")
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }
            }
        }
    }

    private var tagRow: some View {
        Flow(spacing: 8) {
            HStack(spacing: 6) {
                Text("화")
                TextField("예: 7, 8", text: $model.tagText)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 120)
                    .accessibilityLabel("붙일 화")
            }
            Button("이 줄기를 따라가는 화로") { model.tag(.main) }
            Button("메인 화에 장면으로") { model.tag(.thread) }
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
    }

    private func text(_ key: WritableKeyPath<Storyline, String?>) -> Binding<String> {
        Binding(get: { line[keyPath: key] ?? "" }, set: { v in model.edit { $0[keyPath: key] = v } })
    }

    private func number(_ key: WritableKeyPath<Storyline, Int?>) -> Binding<Int> {
        Binding(get: { line[keyPath: key] ?? 0 }, set: { v in model.edit { $0[keyPath: key] = v } })
    }
}

/// AI 제안 받기와 제안 카드 (웹 `lineSuggestPanel` · `lineDraftCard`).
struct SuggestPanel: View {
    @Bindable var model: LinesModel
    let project: Project

    var body: some View {
        LinesCard {
            Text("AI 제안").font(.title3.bold())
            Text("비밀, 열린 복선, 인물의 결핍처럼 작품이 이미 품고 있는 것에서 줄기를 찾아, 갈라지는 화와 합류하는 화, 붙일 화까지 제안해요. 플롯 내용은 바꾸지 않아요.")
                .font(.caption).foregroundStyle(.secondary)
            LabeledText("바라는 것", text: $model.note, placeholder: "예: 조연의 과거를 7화쯤에 두 화 정도", lines: 2)
            HStack {
                Text("종류")
                Picker("종류", selection: $model.aiKind) {
                    Text("AI가 고름").tag(StorylineKind?.none)
                    ForEach(LineRules.kinds, id: \.self) { Text($0.rawValue).tag(Optional($0)) }
                }
                .labelsHidden()
                .fixedSize()
                Spacer()
                if let label = model.busyLabel {
                    Button("\(label) 중…") {}.disabled(true)
                } else {
                    Button("AI에게 줄기 제안받기") { Task { await model.suggest() } }.buttonStyle(.borderedProminent)
                }
            }
            if let d = model.draft { DraftCard(model: model, project: project, draft: d) }
        }
    }
}

/// AI 줄기 제안: 고쳐서 고른 화와 함께 더한다 (웹 `lineDraftCard`).
struct DraftCard: View {
    @Bindable var model: LinesModel
    let project: Project
    let draft: LinesModel.Draft

    var body: some View {
        let s = draft.proposal.storyline
        VStack(alignment: .leading, spacing: 10) {
            if let reply = draft.proposal.reply, !reply.isEmpty {
                Text(reply).font(.callout).frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10).background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
            }
            KindPicker(kind: Binding(get: { LineRules.kind(s) }, set: { k in model.editDraft { $0.kind = k } }))
            LabeledText("이름", text: text(\.title))
            FocusPicker(project: project, focus: s.focus ?? []) { id in
                model.editDraft { l in
                    var f = l.focus ?? []
                    if f.contains(id) { f.removeAll { $0 == id } } else { f.append(id) }
                    l.focus = f
                }
            }
            LabeledText("이야기 속 시점", text: text(\.when))
            LabeledText("풀어 갈 것", text: text(\.goal))
            HStack(alignment: .top, spacing: 12) {
                EpisodeNumberField(label: "갈라지는 화", hint: "", placeholder: "정하지 않음", value: number(\.branchEp))
                EpisodeNumberField(label: "합류하는 화", hint: "", placeholder: "아직 열림", value: number(\.joinEp))
            }
            LabeledText("합류할 때 메인에 남기는 것", text: text(\.rejoin), lines: 2)
            picks("이 줄기를 따라갈 화", draft.proposal.episodes ?? [], .main)
            picks("메인 화에 장면을 끼울 화", draft.proposal.threads ?? [], .thread)
            HStack {
                Spacer()
                Button("버리기") { model.dropDraft() }
                Button("이 줄기 더하기") { Task { await model.applyDraft() } }.buttonStyle(.borderedProminent).disabled(model.busy)
            }
            .controlSize(.small)
        }
        .padding(12)
        .background(.background.opacity(0.7), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.accentColor.opacity(0.4)))
    }

    @ViewBuilder
    private func picks(_ label: String, _ eps: [Int], _ role: LineRules.Role) -> some View {
        if !eps.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                FieldLabel(label)
                Flow(spacing: 10) {
                    ForEach(eps, id: \.self) { n in
                        let title = project.episodes?.first { $0.plot.number == n }?.plot.title ?? ""
                        Toggle("\(n)화\(title.isEmpty ? "" : " " + title)", isOn: Binding(
                            get: { model.draft?.picked(role, n) ?? false },
                            set: { model.draft?.pick(role, n, $0) }))
                        .toggleStyle(.checkboxLike)
                    }
                }
            }
        }
    }

    private func text(_ key: WritableKeyPath<Storyline, String?>) -> Binding<String> {
        Binding(get: { model.draft?.proposal.storyline[keyPath: key] ?? "" }, set: { v in model.editDraft { $0[keyPath: key] = v } })
    }

    private func number(_ key: WritableKeyPath<Storyline, Int?>) -> Binding<Int> {
        Binding(get: { model.draft?.proposal.storyline[keyPath: key] ?? 0 }, set: { v in model.editDraft { $0[keyPath: key] = v } })
    }
}
#endif
