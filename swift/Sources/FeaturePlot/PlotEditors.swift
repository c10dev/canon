#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import SwiftUI

/// 오른쪽 편집 칸: 화 플롯, 구간, 아크, 부 (웹 `drawerHtml`).
struct PanelView: View {
    let model: PlotModel
    let project: Project
    let go: (Screen) -> Void

    var body: some View {
        switch model.panel {
        case let .episode(n):
            if let e = project.episodes?.first(where: { $0.plot.number == n }) {
                PlotEditor(model: model, project: project, episode: e, go: go).id(n)
            }
        case let .act(i):
            if model.acts.indices.contains(i) { ActEditor(model: model, project: project, index: i).id("\(model.currentArc?.number ?? 0)/\(i)") }
        case .arc:
            if let a = model.currentArc { ArcEditor(model: model, project: project, arc: a).id(a.number) }
        case let .part(n):
            if let x = project.parts?.first(where: { $0.number == n }) { PartEditor(model: model, project: project, part: x).id(n) }
        case nil:
            EmptyView()
        }
    }
}

/// 화 플롯 편집기 (웹 `plotEditor`).
struct PlotEditor: View {
    let model: PlotModel
    let project: Project
    let episode: Episode
    let go: (Screen) -> Void

    var body: some View {
        let n = episode.plot.number
        let busy = model.owns(n)
        let pj = model.jobs.running("plots")
        let info = PlotEditorInfo(project, episode: episode, busy: busy, busyNote: pj.flatMap { $0.note.isEmpty ? nil : $0.note })
        let plot = episode.plot
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("\(n)화 플롯").font(.title2.bold())
                Spacer()
                if let p = info.prev { Button("◀ \(p)화") { model.select(.episode(p)) }.accessibilityLabel("이전 \(p)화 플롯") }
                if let x = info.next { Button("\(x)화 ▶") { model.select(.episode(x)) }.accessibilityLabel("다음 \(x)화 플롯") }
                Chip(text: info.status.label, color: info.status.color)
            }
            .buttonStyle(.bordered).controlSize(.small)
            if let s = info.arcNote { NoteBox(text: s, tone: .plain) }
            if let s = info.actNote { NoteBox(text: s) }
            if let s = info.lockNote { NoteBox(text: s, tone: busy ? .warn : .plain) }
            Group {
                TextRow(label: "제목", text: field(n, \.title))
                TextRow(label: "요약", text: field(n, \.summary), lines: 3)
                ListRow(label: "사건 순서", value: model.project?.episodes?.first { $0.plot.number == n }?.plot.events ?? [], set: { v in model.editPlot(n) { $0.events = v } }, lines: 5)
                castField(info, plot)
                if info.showOpening { TextRow(label: "여는 장면", text: optField(n, \.opening), hint: n <= 3 ? "초반 화는 첫 장면이 독자를 붙잡아요" : nil) }
                TextRow(label: "감정 변화", text: field(n, \.emotionalShift))
                TextRow(label: "엔딩 훅", text: field(n, \.endingHook))
                if info.showQuestion { TextRow(label: "독자가 들고 갈 질문", text: optField(n, \.readerQuestion), hint: n <= 3 ? "이 화를 읽고 다음 화를 누르게 하는 질문" : nil) }
                ListRow(label: "심을 복선", value: model.project?.episodes?.first { $0.plot.number == n }?.plot.foreshadowPlant ?? [], set: { v in model.editPlot(n) { $0.foreshadowPlant = v } }, lines: 2)
            }
            .disabled(info.locked)
            payoffs(info)
            insertBlock(n)
            actions(info)
        }
    }

    private func field(_ n: Int, _ key: WritableKeyPath<EpisodePlot, String>) -> Binding<String> {
        Binding(get: { model.project?.episodes?.first { $0.plot.number == n }?.plot[keyPath: key] ?? "" }, set: { v in model.editPlot(n) { $0[keyPath: key] = v } })
    }

    private func optField(_ n: Int, _ key: WritableKeyPath<EpisodePlot, String?>) -> Binding<String> {
        Binding(get: { model.project?.episodes?.first { $0.plot.number == n }?.plot[keyPath: key] ?? "" }, set: { v in model.editPlot(n) { $0[keyPath: key] = v } })
    }

    /// 등장 인물: 비중별로 묶고, AI 플롯이 데려온 새 인물 후보와 설정 없는 id 를 따로 보인다 (웹 `castField`).
    private func castField(_ info: PlotEditorInfo, _ plot: EpisodePlot) -> some View {
        let n = info.number
        return VStack(alignment: .leading, spacing: 6) {
            Text("등장 인물").font(.caption.bold()).foregroundStyle(.secondary)
            ForEach(info.castGroups, id: \.label) { g in
                HStack(alignment: .top) {
                    if !g.label.isEmpty { Text(g.label).font(.caption).foregroundStyle(.secondary).frame(width: 32, alignment: .leading) }
                    FlowToggles(items: g.characters.map { ($0.id, $0.name.isEmpty ? "\($0.id) (이름 없음)" : $0.name) },
                                isOn: { plot.characters.contains($0) }, set: { id, on in model.toggleCast(n, id, on) })
                }
            }
            ForEach(info.candidates, id: \.id) { c in
                VStack(alignment: .leading, spacing: 4) {
                    Text("새 인물 제안 · \(c.name.isEmpty ? c.id : c.name)").font(.callout.bold())
                    Text("\(c.role) · \(c.tier == .minor ? "단역" : "조연")").font(.caption)
                    if let s = c.personality ?? c.goal, !s.isEmpty { Text(s).font(.caption) }
                    if let s = c.speechStyle, !s.isEmpty { Text("말투: \(s)").font(.caption).foregroundStyle(.secondary) }
                    Text("AI 플롯이 데려온 인물이에요. 이 화를 확정하면 함께 등록돼요.").font(.caption).foregroundStyle(.secondary)
                    if !info.locked { Button("이 화에서 빼기") { model.toggleCast(n, c.id, false) }.controlSize(.small) }
                }
                .padding(8).background(.blue.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
            }
            ForEach(info.unknown, id: \.self) { id in
                VStack(alignment: .leading, spacing: 4) {
                    Text("설정 없는 인물 · \(id)").font(.callout.bold())
                    Text("플롯에 이름만 있고 인물 설정이 없어 본문을 쓸 때 이 인물 정보가 들어가지 않아요. 인물은 설정 도우미에서 만들어요.").font(.caption)
                    if !info.locked { Button("이 화에서 빼기") { model.toggleCast(n, id, false) }.controlSize(.small) }
                }
                .padding(8).background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
            }
        }
        .disabled(info.locked)
    }

    /// 회수할 복선 고르기 (웹 `payoffPicker`).
    private func payoffs(_ info: PlotEditorInfo) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("회수할 복선").font(.caption.bold()).foregroundStyle(.secondary)
            if info.payoffs.isEmpty {
                Text("회수할 수 있는 열린 복선이 없어요. 복선은 상태 승인에서 심으면 생겨요.").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(info.payoffs) { f in
                Toggle(isOn: Binding(get: { f.on }, set: { model.togglePayoff(info.number, f.id, $0) })) {
                    VStack(alignment: .leading) {
                        Text(f.text).font(.callout)
                        Text(f.detail).font(.caption).foregroundStyle(.secondary)
                    }
                }
                .disabled(f.fixed)
                #if os(macOS)
                .toggleStyle(.checkbox)
                #endif
            }
        }
    }

    /// 화 끼워 넣기 칸 (웹 `insertBlock`).
    @ViewBuilder
    private func insertBlock(_ n: Int) -> some View {
        let slots = PlotRules.insertSlots(project, n)
        if let f = model.insForm, f.at == n || (slots.after && f.at == n + 1) {
            InsertFormView(model: model, project: project)
        } else if slots.before || slots.after {
            VStack(alignment: .leading, spacing: 6) {
                Text("화 끼워 넣기").font(.caption.bold()).foregroundStyle(.secondary)
                Text("외전이나 중간 이야기를 넣으면 뒤 화가 한 칸씩 밀려요").font(.caption2).foregroundStyle(.secondary)
                HStack {
                    if slots.before { Button("\(n)화 앞에 새 화 넣기") { model.openInsert(at: n) } }
                    if slots.after { Button("\(n)화 뒤에 새 화 넣기") { model.openInsert(at: n + 1) } }
                    if slots.before { Button("\(n)화 빼기", role: .destructive) { model.removeEpisode(n) } }
                }
                .buttonStyle(.bordered).controlSize(.small)
                .disabled(model.projectBusy || model.busy)
                if model.projectBusy { Text("AI 작업이 끝난 뒤에 할 수 있어요").font(.caption2).foregroundStyle(.secondary) }
            }
        }
    }

    private func actions(_ info: PlotEditorInfo) -> some View {
        let n = info.number
        return HStack {
            if info.status == .draft {
                JobButton(model: model, kind: "plot_one", ep: n, idle: "AI로 이 화 채우기") { await model.draftOne(n) }
                Button("\(n)화 확정") { Task { await model.confirm(n) } }
                    .buttonStyle(.borderedProminent).disabled(model.owns(n) || model.busy)
            }
            if info.status == .confirmed {
                Button("초안으로 되돌리기") { Task { await model.unconfirm(n) } }.buttonStyle(.bordered).disabled(model.busy)
                Button("\(n)화 쓰기") { go(.write) }.buttonStyle(.borderedProminent)
            }
            if info.status == .written || info.status == .finalized {
                Button("본문 보기") { go(.write) }.buttonStyle(.bordered)
            }
        }
    }
}

/// 체크 칸 여러 개를 줄바꿈하며 늘어놓는다.
struct FlowToggles: View {
    let items: [(id: String, label: String)]
    let isOn: (String) -> Bool
    let set: (String, Bool) -> Void

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), alignment: .leading)], alignment: .leading, spacing: 4) {
            ForEach(items, id: \.id) { item in
                Toggle(item.label, isOn: Binding(get: { isOn(item.id) }, set: { set(item.id, $0) }))
                    .font(.callout)
                    #if os(macOS)
                    .toggleStyle(.checkbox)
                    #else
                    .toggleStyle(.button)
                    #endif
            }
        }
    }
}

/// 새 화 넣기 양식 (웹 `insertForm`).
struct InsertFormView: View {
    @Bindable var model: PlotModel
    let project: Project

    var body: some View {
        if let at = model.insForm?.at {
            CardBox {
                HStack {
                    Text("\(at)화 자리에 새 화").font(.headline)
                    Spacer()
                    Button("취소") { model.insForm = nil }.controlSize(.small)
                }
                NoteBox(text: PlotRules.insertNote(project, at: at))
                TextRow(label: "제목", text: bind(\.title), placeholder: "예: 외전 · 등대지기의 겨울")
                TextRow(label: "어떤 화인지", text: bind(\.summary), lines: 3, placeholder: "무슨 일이 일어나는 화인지 한두 문장. AI가 앞뒤 화에 맞춰 나머지를 채워요")
                Picker("이야기 줄기", selection: bind(\.storyline)) {
                    Text("메인 줄기").tag("")
                    ForEach(project.storylines ?? [], id: \.id) { s in Text("\(s.kind?.rawValue ?? "서브플롯") · \((s.title ?? "").isEmpty ? s.id : s.title!)").tag(s.id) }
                }
                if (project.storylines ?? []).isEmpty {
                    Text("외전이나 과거 회상 줄기는 이야기 줄기 화면에서 만들 수 있어요.").font(.caption).foregroundStyle(.secondary)
                }
                Toggle("넣은 뒤 AI가 앞뒤 화에 맞춰 플롯 채우기", isOn: Binding(get: { model.insForm?.ai ?? true }, set: { model.insForm?.ai = $0 }))
                Button("\(at)화에 넣기") { Task { await model.submitInsert() } }
                    .buttonStyle(.borderedProminent).frame(maxWidth: .infinity).disabled(model.busy)
            }
        }
    }

    private func bind(_ key: WritableKeyPath<PlotModel.InsertForm, String>) -> Binding<String> {
        Binding(get: { model.insForm?[keyPath: key] ?? "" }, set: { model.insForm?[keyPath: key] = $0 })
    }
}

/// 구간 고치기 (웹 `actEditor`).
struct ActEditor: View {
    let model: PlotModel
    let project: Project
    let index: Int

    var body: some View {
        let arc = model.serial ? model.currentArc : nil
        let acts = model.acts
        let a = acts[index]
        let warn = arc.map { PlotRules.coverage(acts, start: $0.startEp, end: $0.endEp) }
            ?? PlotRules.coverage(acts, start: 1, end: project.meta?.targetEpisodes ?? 0)
        let inAct = (project.episodes ?? []).filter { $0.plot.number >= a.startEp && $0.plot.number <= a.endEp }
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("\(arc.map { "아크 \($0.number) · " } ?? "")\(a.name.rawValue) 구간").font(.title2.bold())
                Spacer()
                Chip(text: "\(a.startEp)~\(a.endEp)화", color: actColor(a.name))
            }
            HStack {
                NumberRow(label: "시작 화", value: int(\.startEp))
                NumberRow(label: "끝 화", value: int(\.endEp))
            }
            Text(arc != nil ? "아크 안 기승전결 네 구간이 아크 첫 화부터 끝 화까지 빈틈없이 이어져야 저장돼요." : "기승전결 네 구간이 1화부터 마지막 화까지 빈틈없이 이어져야 저장돼요.")
                .font(.caption).foregroundStyle(.secondary)
            if !warn.isEmpty { NoteBox(text: warn.joined(separator: "\n"), tone: .warn) }
            TextRow(label: "구간 목표", text: text(\.goal), lines: 5, hint: "이 구간이 끝날 때 이야기가 어디까지 와 있어야 하나")
            TextRow(label: "전환점", text: opt(\.keyTurn), lines: 4, hint: "이 구간을 다음으로 넘기는 사건")
            TextRow(label: "서술 시점", text: opt(\.pov), hint: "화별 플롯을 만들 때 AI가 이 시점을 화마다 채워요",
                    placeholder: "비우면 작품 기본 (\(defaultPov))")
            if !inAct.isEmpty {
                Text("이 구간의 화").font(.caption.bold()).foregroundStyle(.secondary)
                FlowButtons(numbers: inAct.map(\.plot.number)) { model.select(.episode($0)) }
            }
        }
    }

    private var defaultPov: String {
        let s = project.style?.narrationPov ?? ""
        return s.isEmpty ? "정하지 않음" : s
    }

    private func current() -> Act? { model.acts.indices.contains(index) ? model.acts[index] : nil }
    private func int(_ key: WritableKeyPath<Act, Int>) -> Binding<Int> {
        Binding(get: { current()?[keyPath: key] ?? 0 }, set: { v in model.editAct(index) { $0[keyPath: key] = v } })
    }
    private func text(_ key: WritableKeyPath<Act, String>) -> Binding<String> {
        Binding(get: { current()?[keyPath: key] ?? "" }, set: { v in model.editAct(index) { $0[keyPath: key] = v } })
    }
    private func opt(_ key: WritableKeyPath<Act, String?>) -> Binding<String> {
        Binding(get: { current()?[keyPath: key] ?? "" }, set: { v in model.editAct(index) { $0[keyPath: key] = v } })
    }
}

/// 화 번호 단추 줄.
struct FlowButtons: View {
    let numbers: [Int]
    let action: (Int) -> Void

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 56), alignment: .leading)], alignment: .leading, spacing: 4) {
            ForEach(numbers, id: \.self) { n in Button("\(n)화") { action(n) }.buttonStyle(.bordered).controlSize(.small) }
        }
    }
}
#endif
