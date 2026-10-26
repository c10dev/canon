#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import SwiftUI

/// 장편: 부 구성, 아크 줄, 고른 아크나 다음 아크 기획 (웹 `viewSerial`).
struct SerialContent: View {
    let model: PlotModel
    let project: Project
    let go: (Screen) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PlanNoteField(model: model, what: model.currentArc != nil ? "부 구성 제안 · 이 아크 초안 만들기" : "부 구성 제안")
            SeriesCard(model: model, project: project)
            ArcRail(model: model, project: project)
            if let arc = model.currentArc {
                ArcPanel(model: model, project: project, arc: arc, go: go)
            } else {
                NextArcPanel(model: model, project: project)
            }
        }
    }
}

/// 부 구성과 AI 부 구성 제안 (웹 `viewSerial` 의 `series`).
struct SeriesCard: View {
    @Bindable var model: PlotModel
    let project: Project

    var body: some View {
        let p = project
        let parts = p.parts ?? []
        let next = PlotRules.plannedUntil(p) + 1
        CardBox {
            HStack {
                Text("부 구성").font(.title3.bold())
                Text("총 \(p.meta?.targetEpisodes ?? 0)화 · \(next - 1)화까지 아크 기획").font(.caption).foregroundStyle(.secondary)
                Spacer()
                JobButton(model: model, kind: "series", idle: parts.isEmpty ? "AI로 부 구성 만들기" : "부 구성 다시 제안") { await model.planSeries() }
                    .controlSize(.small)
            }
            if parts.isEmpty {
                Text("무대와 판이 바뀌는 큰 단위(50~150화)예요. 없어도 아크를 이어 갈 수 있지만, 있으면 아크 기획이 부 목표를 따라가요.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 8) { ForEach(parts, id: \.number) { partCard($0, next: next) } }
                }
            }
            if model.seriesDraft != nil { draft }
        }
    }

    private func partCard(_ x: Part, next: Int) -> some View {
        let done = (project.episodes ?? []).filter { PlotRules.status($0) == .finalized && $0.plot.number >= x.startEp && $0.plot.number <= x.endEp }.count
        let size = x.endEp - x.startEp + 1
        let arcs = (project.storyArcs ?? []).filter { $0.startEp >= x.startEp && $0.startEp <= x.endEp }.count
        let here = next >= x.startEp && next <= x.endEp
        let selected = model.panel == .part(x.number)
        return Button { model.select(.part(x.number)) } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("\(x.number)부 \(x.title)").font(.subheadline.bold())
                    Spacer()
                    Text("\(x.startEp)~\(x.endEp)화").font(.caption).foregroundStyle(.secondary)
                }
                Text(x.goal).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                HStack {
                    if here { Chip(text: "지금 쓰는 부", color: .accentColor) }
                    Chip(text: "아크 \(arcs)개")
                    Chip(text: "반영 \(done)/\(size)", color: done > 0 ? .green : .secondary)
                    if done == size { Chip(text: (x.summary ?? "").isEmpty ? "요약 필요" : "요약 있음", color: (x.summary ?? "").isEmpty ? .orange : .green) }
                }
            }
            .frame(width: 260, alignment: .leading)
            .padding(10)
            .background(.background, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(selected ? Color.accentColor : here ? Color.accentColor.opacity(0.4) : Color.secondary.opacity(0.25), lineWidth: selected ? 2 : 1))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    @ViewBuilder
    private var draft: some View {
        let lost = model.seriesDraft.map { PlotRules.lostPartSummaries(project, $0) } ?? []
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("AI 부 구성 제안").font(.headline)
                Chip(text: "적용 전", color: .purple)
                Spacer()
                Button("버리기") { model.dropSeries() }.buttonStyle(.bordered)
                Button("이 부 구성 적용") { Task { await model.applySeries() } }.buttonStyle(.borderedProminent).disabled(model.busy)
            }
            ForEach(Array((model.seriesDraft?.parts ?? []).indices), id: \.self) { i in
                VStack(alignment: .leading, spacing: 8) {
                    TextRow(label: "\(model.seriesDraft!.parts[i].number)부 제목", text: part(i, \.title))
                    HStack {
                        NumberRow(label: "시작 화", value: partInt(i, \.startEp))
                        NumberRow(label: "끝 화", value: partInt(i, \.endEp))
                    }
                    TextRow(label: "부 목표", text: part(i, \.goal), lines: 2)
                    TextRow(label: "전환점", text: partOpt(i, \.keyTurn), lines: 2, hint: "부를 마무리하는 큰 사건이나 드러나는 비밀")
                    ListRow(label: "아크 후보", value: model.seriesDraft?.parts[safe: i]?.arcIdeas ?? [], set: { v in model.seriesDraft?.parts[i].arcIdeas = v })
                }
                .padding(10)
                .background(.background, in: RoundedRectangle(cornerRadius: 8))
            }
            Text("부는 1화부터 \(project.meta?.targetEpisodes ?? 0)화까지 빈틈없이 이어져야 반영돼요. 이미 기획한 아크가 새 부 경계를 넘으면 반영하지 않아요.")
                .font(.caption).foregroundStyle(.secondary)
            if !lost.isEmpty {
                NoteBox(text: "이 구성으로 반영하면 범위가 바뀌어 저장된 \(lost.map { "\($0.number)부(\($0.startEp)~\($0.endEp)화)" }.joined(separator: ", ")) 요약이 사라져요. 지키려면 그 부의 시작 화와 끝 화를 지금과 같게 두세요.", tone: .warn)
            }
        }
        .padding(10)
        .background(.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
    }

    private func part(_ i: Int, _ key: WritableKeyPath<Part, String>) -> Binding<String> {
        Binding(get: { model.seriesDraft?.parts[safe: i]?[keyPath: key] ?? "" }, set: { model.seriesDraft?.parts[i][keyPath: key] = $0 })
    }
    private func partOpt(_ i: Int, _ key: WritableKeyPath<Part, String?>) -> Binding<String> {
        Binding(get: { model.seriesDraft?.parts[safe: i]?[keyPath: key] ?? "" }, set: { model.seriesDraft?.parts[i][keyPath: key] = $0 })
    }
    private func partInt(_ i: Int, _ key: WritableKeyPath<Part, Int>) -> Binding<Int> {
        Binding(get: { model.seriesDraft?.parts[safe: i]?[keyPath: key] ?? 0 }, set: { model.seriesDraft?.parts[i][keyPath: key] = $0 })
    }
}

extension Array {
    subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}

/// 아크 줄과 요약이 필요한 아크 · 부 안내 (웹 `viewSerial` 의 `rail`).
struct ArcRail: View {
    @Bindable var model: PlotModel
    let project: Project

    var body: some View {
        let p = project
        let picked = model.selectedArc
        let selected: Int? = if case let .arc(n) = picked { n } else { nil }
        let rail = PlotRules.rail(p, selected: selected, all: model.railAll)
        let next = PlotRules.plannedUntil(p) + 1
        let pending = PlotRules.pendingRecaps(p)
        CardBox {
            HStack {
                Text("아크").font(.title3.bold())
                Spacer()
                Text("아크 하나는 5~30화짜리 작은 이야기예요. 다음 아크의 플롯만 그때그때 만들어요.").font(.caption).foregroundStyle(.secondary)
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    if let f = rail.folded {
                        Button { model.railAll = true } label: {
                            VStack(alignment: .leading) {
                                Text("아크 \(f.first)~\(f.last)").bold()
                                Text("완료 \(f.count)개 · 펼치기").font(.caption)
                            }
                        }
                        .buttonStyle(.bordered)
                    }
                    ForEach(rail.shown, id: \.number) { a in chip(a, selected: picked == .arc(a.number)) }
                    if next - 1 < (p.meta?.targetEpisodes ?? 0) {
                        Button { model.pickArc(.next) } label: {
                            VStack(alignment: .leading) {
                                Text("+ 다음 아크").bold()
                                Text("\(next)화부터").font(.caption)
                            }
                        }
                        .modify { if picked == .next { $0.buttonStyle(.borderedProminent) } else { $0.buttonStyle(.bordered) } }
                    }
                }
            }
            if let a = pending.arcs.first {
                HStack {
                    Text("요약이 필요한 끝난 아크 \(pending.arcs.count)개 · 가장 오래된 아크 \(a.number)부터 받으세요. 요약이 있어야 오래된 줄거리를 짧게 접어 넣을 수 있어요.")
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Button("아크 \(a.number) 보기") { model.pickArc(.arc(a.number)) }.buttonStyle(.bordered)
                    JobButton(model: model, kind: "recap_arc", ep: a.number, idle: "아크 \(a.number) 요약 받기") { await model.recap("arc", a.number) }
                }
                .font(.callout).padding(10).background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
            }
            if let x = pending.parts.first {
                let first = pending.arcs.contains { a in pending.parts.contains { $0.startEp <= a.startEp && a.startEp <= $0.endEp } }
                HStack {
                    Text("요약이 필요한 끝난 부 \(pending.parts.count)개 · \(pending.parts.map { "\($0.number)부" }.joined(separator: ", ")). 부 요약은 그 부의 아크를 한 덩어리로 접어 프롬프트를 더 줄여요.\(first ? " 그 부의 아크 요약을 먼저 받으면 부 요약에 쓰여요." : "")")
                        .frame(maxWidth: .infinity, alignment: .leading)
                    JobButton(model: model, kind: "recap_part", ep: x.number, idle: "\(x.number)부 요약 받기") { await model.recap("part", x.number) }
                }
                .font(.callout).padding(10).background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private func chip(_ a: StoryArc, selected: Bool) -> some View {
        let c = PlotRules.arcChip(project, a)
        return Button { model.pickArc(.arc(a.number)) } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text("아크 \(a.number)").bold()
                Text("\(a.startEp)~\(a.endEp)화").font(.caption)
                Chip(text: c.label, color: c.status?.color ?? .secondary)
            }
        }
        .modify { if selected { $0.buttonStyle(.borderedProminent) } else { $0.buttonStyle(.bordered) } }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// 다음 아크 기획과 AI 다음 아크 제안 (웹 `nextArcPanel`).
struct NextArcPanel: View {
    @Bindable var model: PlotModel
    let project: Project

    var body: some View {
        let p = project
        let start = PlotRules.plannedUntil(p) + 1
        let total = p.meta?.targetEpisodes ?? 0
        if start > total {
            CardBox {
                Text("총 \(total)화까지 아크가 모두 있어요.").font(.headline)
                Text("더 쓰려면 설정 도우미에서 총 화수를 늘리세요. 마지막 부 끝 화가 따라 늘어나요.").font(.caption).foregroundStyle(.secondary)
            }
        } else if let d = model.arcDraft {
            draft(d)
        } else {
            let part = (p.parts ?? []).first { $0.startEp <= start && start <= $0.endEp }
            let old = (p.foreshadows ?? []).filter { ($0.status ?? .open) == .open && start - $0.plantedEp > 50 }
            CardBox {
                HStack(alignment: .firstTextBaseline) {
                    Text("다음 아크 기획").font(.title3.bold())
                    Text("\(start)화부터\(part.map { " · \($0.number)부 \($0.title) (\($0.endEp)화까지)" } ?? "")").font(.caption).foregroundStyle(.secondary)
                }
                if let part {
                    let ideas = part.arcIdeas ?? []
                    NoteBox(text: "\(part.number)부 목표 · \(part.goal)\(ideas.isEmpty ? "" : "\n아크 후보: \(ideas.joined(separator: " / "))")", tone: .plain)
                }
                if !old.isEmpty {
                    NoteBox(text: "50화 넘게 열린 복선이 \(old.count)개 있어요. 이번 아크에서 회수하거나 다시 떠올리도록 AI에게 함께 보여 줘요.", tone: .warn)
                }
                NumberRow(label: "아크 길이 (화)", value: $model.arcLength, hint: "0 이면 AI가 내용에 맞게 정해요 (보통 10~25화)")
                    .frame(maxWidth: 240)
                TextRow(label: "이번 아크에 바라는 것 (선택)", text: $model.arcNote, lines: 3, placeholder: "예: 학교 밖으로 무대를 넓히고, 라이벌과 처음 손잡게")
                HStack {
                    JobButton(model: model, kind: "nextarc", idle: "AI로 다음 아크 제안", prominent: true) { await model.planNextArc() }
                    Text("지금까지 실제로 쓴 줄거리(요약), 부 목표, 열린 복선을 보고 아크 하나를 제안해요. 적용 전에 고칠 수 있어요.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func draft(_ d: ArcProposal) -> some View {
        CardBox {
            HStack {
                Text("아크 \(d.arc.number) 제안").font(.title3.bold())
                Chip(text: "적용 전", color: .purple)
                Spacer()
                Button("버리기") { model.dropArc() }.buttonStyle(.bordered)
                Button("이 아크 적용") { Task { await model.applyArc() } }.buttonStyle(.borderedProminent).disabled(model.busy)
            }
            if let r = d.reply, !r.isEmpty { NoteBox(text: r) }
            TextRow(label: "아크 제목", text: arc(\.title))
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("시작 화").font(.caption.bold()).foregroundStyle(.secondary)
                    Text("\(d.arc.startEp)화")
                }
                NumberRow(label: "끝 화", value: Binding(get: { model.arcDraft?.arc.endEp ?? 0 }, set: { model.setDraftEnd($0) }))
            }
            TextRow(label: "아크 목표", text: arc(\.goal), lines: 2, hint: "아크가 끝날 때 바뀌어 있어야 하는 것")
            TextRow(label: "갈등", text: arcOpt(\.conflict), lines: 2, hint: "주인공을 막는 문제나 상대")
            TextRow(label: "보상 (사이다)", text: arcOpt(\.payoff), lines: 2, hint: "클라이맥스에서 독자가 받는 것")
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 200), alignment: .topLeading)], alignment: .leading, spacing: 8) {
                ForEach(Array((d.arc.acts ?? []).enumerated()), id: \.offset) { i, a in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack { Text(a.name.rawValue).bold(); Spacer(); Text("\(a.startEp)~\(a.endEp)화").font(.caption) }
                        TextRow(label: "구간 목표", text: Binding(get: { model.arcDraft?.arc.acts?[safe: i]?.goal ?? "" }, set: { model.arcDraft?.arc.acts?[i].goal = $0 }), lines: 3)
                    }
                    .padding(8).background(actColor(a.name).opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                }
            }
            TextRow(label: "서술 시점", text: arcOpt(\.pov), placeholder: "비우면 작품 기본")
            HStack(alignment: .top) {
                ListRow(label: "주요 인물 id", value: model.arcDraft?.arc.cast ?? [], set: { model.arcDraft?.arc.cast = $0 })
                ListRow(label: "회수할 복선 id", value: model.arcDraft?.arc.payoffs ?? [], set: { model.arcDraft?.arc.payoffs = $0 })
            }
            if let cs = d.newCharacters, !cs.isEmpty {
                Text("새 인물 (조연으로 들어와요. 주역으로 올리려면 설정 도우미에서 비중을 바꾸세요)").font(.caption.bold()).foregroundStyle(.secondary)
                ForEach(cs, id: \.id) { c in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(c.name).bold() + Text("  \(c.id) · \(c.role)").font(.caption)
                        if let s = c.personality ?? c.goal, !s.isEmpty { Text(s).font(.caption) }
                        if let s = c.speechStyle, !s.isEmpty { Text("말투: \(s)").font(.caption).foregroundStyle(.secondary) }
                    }
                    .padding(8).frame(maxWidth: .infinity, alignment: .leading).background(.gray.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                }
            }
            Text("끝 화를 바꾸면 결 구간이 따라 늘거나 줄어요. 다른 구간 범위는 반영한 뒤 구간 고치기에서 바꿀 수 있어요.").font(.caption).foregroundStyle(.secondary)
        }
    }

    private func arc(_ key: WritableKeyPath<StoryArc, String>) -> Binding<String> {
        Binding(get: { model.arcDraft?.arc[keyPath: key] ?? "" }, set: { model.arcDraft?.arc[keyPath: key] = $0 })
    }
    private func arcOpt(_ key: WritableKeyPath<StoryArc, String?>) -> Binding<String> {
        Binding(get: { model.arcDraft?.arc[keyPath: key] ?? "" }, set: { model.arcDraft?.arc[keyPath: key] = $0 })
    }
}

/// 고른 아크: 목표 · 갈등 · 보상, 요약, 구간 보드 (웹 `arcPanel`).
struct ArcPanel: View {
    let model: PlotModel
    let project: Project
    let arc: StoryArc
    let go: (Screen) -> Void

    var body: some View {
        let p = project
        let a = arc
        let g = PlotRules.progress(p, a)
        let eps = (p.episodes ?? []).filter { $0.plot.number >= a.startEp && $0.plot.number <= a.endEp }
        let last = (p.storyArcs ?? []).map(\.startEp).max() == a.startEp
        let finished = PlotRules.finished(p, a.startEp, a.endEp)
        let names = (a.cast ?? []).map { id in (p.characters ?? []).first { $0.id == id }.map { $0.name.isEmpty ? id : $0.name } ?? id }
        VStack(alignment: .leading, spacing: 12) {
            CardBox {
                HStack(alignment: .firstTextBaseline) {
                    Text("아크 \(a.number) \(a.title)").font(.title3.bold())
                    Text("\(a.startEp)~\(a.endEp)화 · \(g.count)화 · 반영 \(g.done)/\(g.count)").font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    Button("아크 고치기") { model.select(.arc) }
                    if PlotRules.needsDraft(p.episodes ?? [], a.startEp, a.endEp) || model.jobs.running("plots", ep: a.number) != nil {
                        JobButton(model: model, kind: "plots", ep: a.number, idle: g.plotted > 0 ? "초안 다시 만들기 (확정 화 제외)" : "화별 플롯 초안 만들기") {
                            await model.draftPlots(arc: a.number)
                        }
                    }
                    if g.drafts > 0 {
                        Button("초안 \(g.drafts)화 모두 확정") { model.confirmAll(arc: a.number) }
                            .buttonStyle(.borderedProminent).disabled(model.jobs.running("plots") != nil || model.busy)
                    } else if let n = PlotRules.writeNext(p, arc: a) {
                        Button("\(n)화 쓰기") { go(.write) }.buttonStyle(.borderedProminent)
                    }
                    if last && !eps.contains(where: { PlotRules.status($0) != .draft }) {
                        Button("지우고 다시 기획", role: .destructive) { model.removeLastArc() }
                    }
                }
                .buttonStyle(.bordered).controlSize(.small)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 200), alignment: .topLeading)], alignment: .leading) {
                    fact("아크 목표", a.goal)
                    fact("갈등", a.conflict ?? "")
                    fact("보상 (사이다)", a.payoff ?? "")
                }
                let line = [names.isEmpty ? nil : "주요 인물: \(names.joined(separator: ", "))",
                            (a.payoffs ?? []).isEmpty ? nil : "회수할 복선: \((a.payoffs ?? []).joined(separator: ", "))"].compactMap { $0 }
                if !line.isEmpty { Text(line.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary) }
                if finished { RecapBlock(model: model, kind: "arc", number: a.number, saved: a.summary ?? "") }
            }
            if let pj = model.jobs.running("plots", ep: a.number) {
                NoteBox(text: "구간마다 초안을 만드는 중이에요\(pj.note.isEmpty ? "" : " (\(pj.note))"). 끝난 구간부터 카드가 채워지고, 채워진 화는 바로 고칠 수 있어요.")
            } else if g.plotted == 0 {
                NoteBox(text: "구간을 확인한 뒤 '화별 플롯 초안 만들기'를 누르면 이 아크의 화 카드가 채워져요.")
            }
            BoardView(model: model, board: PlotBoard(acts: a.acts ?? [], episodes: eps))
        }
    }

    private func fact(_ label: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2.bold()).foregroundStyle(.secondary)
            Text(text.isEmpty ? "비어 있음" : text).font(.callout).foregroundStyle(text.isEmpty ? .secondary : .primary)
        }
    }
}

/// 아크 · 부 요약: AI 요약 제안을 고쳐 저장하고, 저장된 요약을 직접 고친다 (웹 `arcPanel` · `partEditor` 의 요약).
struct RecapBlock: View {
    let model: PlotModel
    /// "arc" 나 "part"
    let kind: String
    let number: Int
    let saved: String

    var body: some View {
        let key = kind + "\(number)"
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(kind == "arc" ? "아크 요약" : "부 요약").font(.headline)
                Chip(text: saved.isEmpty ? "필요" : "있음", color: saved.isEmpty ? .orange : .green)
                Spacer()
                JobButton(model: model, kind: "recap_" + kind, ep: number, idle: saved.isEmpty ? "AI로 요약 제안" : "AI로 요약 다시 제안") {
                    await model.recap(kind, number)
                }
                .controlSize(.small)
            }
            if model.recapDrafts[key] != nil {
                TextRow(label: "AI 요약 제안 (고친 뒤 저장)", text: Binding(get: { model.recapDrafts[key]?.summary ?? "" }, set: { model.recapDrafts[key]?.summary = $0 }), lines: 6)
                HStack {
                    Button("버리기") { model.dropRecap(key) }.buttonStyle(.bordered)
                    Button("이 요약 저장") { Task { await model.applyRecap(key) } }.buttonStyle(.borderedProminent).disabled(model.busy)
                }
                .controlSize(.small)
            }
            TextRow(label: "저장된 요약", text: Binding(get: { saved }, set: { v in
                if kind == "arc" { model.editArc(number) { $0.summary = v } } else { model.editPart(number) { $0.summary = v } }
            }), lines: 4, hint: kind == "arc" ? "앞으로 이 아크의 화별 요약 대신 프롬프트에 들어가요. 요약이 없으면 화마다 첫 문장만 들어가 앞 이야기가 흐려져요" : nil)
        }
    }
}

/// 아크 고치기 (웹 `arcEditor`).
struct ArcEditor: View {
    let model: PlotModel
    let project: Project
    let arc: StoryArc

    var body: some View {
        let a = arc
        let last = PlotRules.arcs(project).last?.number == a.number
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("아크 \(a.number) 고치기").font(.title2.bold())
                Spacer()
                Chip(text: "\(a.startEp)~\(a.endEp)화")
            }
            TextRow(label: "제목", text: text(\.title))
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("시작 화").font(.caption.bold()).foregroundStyle(.secondary)
                    Text("\(a.startEp)화")
                }
                if last {
                    NumberRow(label: "끝 화", value: Binding(get: { a.endEp }, set: { v in
                        if v >= a.startEp { model.editArc(a.number) { PlotRules.setArcEnd(&$0, v) } }
                    }))
                } else {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("끝 화").font(.caption.bold()).foregroundStyle(.secondary)
                        Text("\(a.endEp)화")
                    }
                }
            }
            Text(last ? "끝 화를 바꾸면 구간도 따라 바뀌어요. 길이를 크게 바꾸려면 이 아크를 지우고 다시 기획하는 편이 쉬워요."
                      : "마지막 아크만 길이를 바꿀 수 있어요. 뒤 아크가 이 아크 다음 화부터 시작해요.")
                .font(.caption).foregroundStyle(.secondary)
            TextRow(label: "아크 목표", text: text(\.goal), lines: 3)
            TextRow(label: "갈등", text: opt(\.conflict), lines: 2)
            TextRow(label: "보상 (사이다)", text: opt(\.payoff), lines: 2)
            TextRow(label: "서술 시점", text: opt(\.pov), hint: "이 아크를 누구 시점으로 쓸지. 구간마다 다르면 구간 고치기에서", placeholder: "비우면 작품 기본")
            ListRow(label: "주요 인물 id", value: current()?.cast ?? [], set: { v in model.editArc(a.number) { $0.cast = v } })
            payoffs(a)
        }
    }

    private func current() -> StoryArc? { model.project?.storyArcs?.first { $0.number == arc.number } }
    private func text(_ key: WritableKeyPath<StoryArc, String>) -> Binding<String> {
        Binding(get: { current()?[keyPath: key] ?? "" }, set: { v in model.editArc(arc.number) { $0[keyPath: key] = v } })
    }
    private func opt(_ key: WritableKeyPath<StoryArc, String?>) -> Binding<String> {
        Binding(get: { current()?[keyPath: key] ?? "" }, set: { v in model.editArc(arc.number) { $0[keyPath: key] = v } })
    }

    /// 회수할 복선: 열린 복선과 이미 고른 것 (웹 `payoffPicker` 를 아크 칸에).
    private func payoffs(_ a: StoryArc) -> some View {
        let fs = project.foreshadows ?? []
        let cur = a.payoffs ?? []
        let open = fs.filter { ($0.status ?? .open) == .open }
        let extra = cur.filter { id in !open.contains { $0.id == id } }
        return VStack(alignment: .leading, spacing: 6) {
            Text("회수할 복선").font(.caption.bold()).foregroundStyle(.secondary)
            if open.isEmpty && extra.isEmpty { Text("회수할 수 있는 열린 복선이 없어요.").font(.caption).foregroundStyle(.secondary) }
            ForEach(open, id: \.id) { f in
                Toggle(isOn: Binding(get: { cur.contains(f.id) }, set: { model.toggleArcPayoff(a.number, f.id, $0) })) {
                    VStack(alignment: .leading) {
                        Text(f.description).font(.callout)
                        Text("\(f.plantedEp)화에 심음\(f.dueEp.map { " · \($0)화 회수 예정" } ?? "")").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            ForEach(extra, id: \.self) { id in
                Toggle(isOn: .constant(true)) {
                    Text("\(fs.first { $0.id == id }?.description ?? id) (\(fs.contains { $0.id == id } ? "이미 회수함" : "없는 복선 id"))").font(.callout)
                }
                .disabled(true)
            }
        }
    }
}

/// 부 고치기 (웹 `partEditor`).
struct PartEditor: View {
    let model: PlotModel
    let project: Project
    let part: Part

    var body: some View {
        let x = part
        let finished = PlotRules.finished(project, x.startEp, x.endEp)
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("\(x.number)부 고치기").font(.title2.bold())
                Spacer()
                Chip(text: "\(x.startEp)~\(x.endEp)화")
            }
            TextRow(label: "제목", text: text(\.title))
            HStack {
                NumberRow(label: "시작 화", value: int(\.startEp))
                NumberRow(label: "끝 화", value: int(\.endEp))
            }
            Text("부는 1화부터 마지막 화까지 빈틈없이 이어져야 저장돼요.").font(.caption).foregroundStyle(.secondary)
            TextRow(label: "부 목표", text: text(\.goal), lines: 3)
            TextRow(label: "전환점", text: opt(\.keyTurn), lines: 2)
            ListRow(label: "아크 후보", value: current()?.arcIdeas ?? [], set: { v in model.editPart(x.number) { $0.arcIdeas = v } }, lines: 5,
                    hint: "다음 아크를 기획할 때 참고해요")
            if finished {
                RecapBlock(model: model, kind: "part", number: x.number, saved: current()?.summary ?? "")
            } else {
                Text("부의 모든 화가 반영되면 요약을 만들 수 있어요.").font(.caption).foregroundStyle(.secondary)
                TextRow(label: "저장된 요약", text: opt(\.summary), lines: 4)
            }
        }
    }

    private func current() -> Part? { model.project?.parts?.first { $0.number == part.number } }
    private func text(_ key: WritableKeyPath<Part, String>) -> Binding<String> {
        Binding(get: { current()?[keyPath: key] ?? "" }, set: { v in model.editPart(part.number) { $0[keyPath: key] = v } })
    }
    private func opt(_ key: WritableKeyPath<Part, String?>) -> Binding<String> {
        Binding(get: { current()?[keyPath: key] ?? "" }, set: { v in model.editPart(part.number) { $0[keyPath: key] = v } })
    }
    private func int(_ key: WritableKeyPath<Part, Int>) -> Binding<Int> {
        Binding(get: { current()?[keyPath: key] ?? 0 }, set: { v in model.editPart(part.number) { $0[keyPath: key] = v } })
    }
}
#endif
