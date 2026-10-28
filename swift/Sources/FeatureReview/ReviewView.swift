#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 상태 승인: AI 변경안에서 고른 항목만 반영하고 화를 마친다. 반영 뒤 고친 화는 다시 맞춘다 (웹 `viewReview` · `restateCard`).
public struct ReviewView: View {
    @State private var model: ReviewModel
    let go: (Screen) -> Void
    @State private var ask: Question?
    @Environment(\.openBranchForm) private var openBranchForm
    /// 고치는 중인 항목 키.
    @State private var editing: Set<String> = []

    public init(document: ProjectDocument, jobs: JobCenter, service: any ReviewService, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: ReviewModel(document: document, jobs: jobs, service: service))
        self.go = go
    }

    /// 한 번 묻고 하는 동작.
    struct Question: Identifiable {
        let id = UUID()
        let text: String
        let button: String
        var destructive = false
        let action: () async -> Void
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
        .task(id: model.resultID) { model.sync() }
        .task(id: model.previewKey) {
            guard model.draft != nil, model.episode?.status == .written else { return }
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled else { return }
            await model.refreshPreview()
        }
        .alert(ask?.text ?? "", isPresented: Binding(get: { ask != nil }, set: { if !$0 { ask = nil } }), presenting: ask) { q in
            Button(q.button, role: q.destructive ? .destructive : nil) { Task { await q.action() } }
            Button("취소", role: .cancel) {}
        }
    }

    private func content(_ p: Project) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header(p)
                if let n = model.notice {
                    HStack {
                        Notice(n.text, isError: n.isError) { model.dismissNotice() }
                        if let next = model.nextWrite, !n.isError {
                            Button("\(next)화 집필로") { go(.write) }.buttonStyle(.borderedProminent)
                        }
                    }
                }
                if let f = model.failure {
                    HStack {
                        Text("지난 시도 실패 · \(f.label): \(f.error)").frame(maxWidth: .infinity, alignment: .leading)
                        Button("닫기") { Task { await model.jobs.dismissFailure(f.key) } }
                    }
                    .note(.warn)
                }
                if model.autoRunning {
                    HStack {
                        Text("자동 집필이 쓰는 중이에요. 손으로 쓰거나 반영하려면 자동 집필을 일시정지하세요.").frame(maxWidth: .infinity, alignment: .leading)
                        Button("자동 집필") { go(.auto) }
                    }
                    .note(.warn)
                }
                if let e = model.episode {
                    body(e, p)
                } else {
                    ContentUnavailableView("화가 없어요", systemImage: "doc", description: Text("기승전결 · 플롯에서 화별 플롯을 먼저 만드세요"))
                }
            }
            .padding()
            .frame(maxWidth: 1100, alignment: .leading)
        }
    }

    // MARK: 위쪽

    private func header(_ p: Project) -> some View {
        let eps = p.episodes ?? []
        let numbers = eps.map(\.plot.number)
        let i = numbers.firstIndex(of: model.ep)
        return HStack(alignment: .center, spacing: 12) {
            Button { if let i, i > 0 { model.select(numbers[i - 1]) } } label: { Image(systemName: "chevron.left") }
                .disabled(i == nil || i == 0)
                .accessibilityLabel("앞 화")
            Menu {
                ForEach(eps, id: \.plot.number) { e in
                    Button("\(e.plot.number)화 \(e.plot.title) · \(statusLabel(e))") { model.select(e.plot.number) }
                }
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(model.ep)화 \(model.episode?.plot.title ?? "")").font(.caption).foregroundStyle(.secondary)
                    Text("상태 승인").font(.title.bold())
                }
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            Button { if let i, i + 1 < numbers.count { model.select(numbers[i + 1]) } } label: { Image(systemName: "chevron.right") }
                .disabled(i == nil || i! + 1 >= numbers.count)
                .accessibilityLabel("다음 화")
            if let e = model.episode { Chip(statusLabel(e), tint: .secondary) }
            Spacer()
            if model.draft != nil, model.episode?.status == .written {
                Text("\(model.total)건 중 \(model.pickedCount)건 선택").font(.callout).foregroundStyle(.secondary)
            }
        }
    }

    private func statusLabel(_ e: Episode) -> String {
        EpisodeStatus(rawValue: e.status?.rawValue ?? "draft")?.label ?? ""
    }

    @ViewBuilder
    private func body(_ e: Episode, _ p: Project) -> some View {
        let n = model.ep
        switch e.status ?? .draft {
        case .finalized:
            finalized(e, p)
        case .written:
            if let d = model.draft {
                delta(d, e, p)
            } else {
                Text("AI가 본문에서 인물 상태, 관계, 확정 사실, 복선을 뽑아 변경안을 만들어요. 승인한 항목만 데이터에 반영돼요.").foregroundStyle(.secondary)
                if p.episodes?.contains(where: { $0.plot.number == n + 1 }) == true {
                    Text("\(n)화 상태를 반영해야 \(n + 1)화를 쓸 수 있어요.").note(.info)
                }
                Card("AI로 만들기") {
                    Text("\(n)화 본문을 읽고 변경안을 만들어요.").foregroundStyle(.secondary)
                    Button(model.extractLabel ?? "변경안 만들기") { Task { await model.extract() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.extractLabel != nil)
                    Text("채팅 앱에서 받은 JSON은 웹의 작업지시서 화면에서 가져와요.").font(.caption).foregroundStyle(.secondary)
                }
            }
        default:
            Card {
                Text("\(n)화 본문이 아직 없어요. 본문을 쓴 뒤 상태를 정리해요.")
                Button("\(n)화 집필로") { go(.write) }.buttonStyle(.borderedProminent)
            }
        }
    }

    // MARK: 반영이 끝난 화

    @ViewBuilder
    private func finalized(_ e: Episode, _ p: Project) -> some View {
        HStack {
            Text("이 화는 상태 반영이 끝났어요. 반영된 내용이에요.").foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
            if let openBranchForm {
                Button("\(model.ep)화부터 갈래 만들기") { openBranchForm(model.ep) }
                    .help("이 작품은 그대로 두고, 사본에서 \(model.ep)화부터 다른 전개를 써요")
            }
            if model.canRevert {
                Button("\(model.ep)화부터 반영 취소") {
                    ask = Question(text: ReviewText.revertQuestion(model.ep, p), button: "반영 취소", destructive: true) { await model.revert() }
                }
                .disabled(model.busy)
            }
        }
        if ReviewText.editedAfterFinal(e) { restate(e, p) }
        if let h = model.history {
            historyView(h, p)
        } else {
            Text("반영 기록이 없어요.").note(.plain)
        }
    }

    /// 반영 뒤 고친 화 다시 맞추기 (웹 `restateCard`).
    @ViewBuilder
    private func restate(_ e: Episode, _ p: Project) -> some View {
        let n = model.ep
        let later = ReviewText.laterWritten(n, p)
        Card("고친 본문으로 다시 맞추기") {
            Text("\(n)화는 반영한 뒤 본문을 고쳤어요. 인물 상태 · 관계 · 비밀은 \(later.isEmpty ? "" : "뒤 화(\(ReviewText.rangeText(later))화)가 그 위에 쌓아서 ")여기서 바꾸지 않아요. 고친 본문에서 변경안을 다시 뽑아 요약 · 새 사실 · 새 복선 · 새 장소만 골라 반영할 수 있어요. 인물 상태까지 바꿔야 하면 '\(n)화부터 반영 취소'를 쓰세요.")
                .font(.callout).foregroundStyle(.secondary)
            if let d = model.draft {
                let it = ReviewText.restateItems(d, p)
                VStack(alignment: .leading, spacing: 6) {
                    Text("요약").font(.caption).foregroundStyle(.secondary)
                    if let s = e.summary, !s.isEmpty, s != d.summary { Text("지금: \(s)").font(.caption).foregroundStyle(.secondary) }
                    CheckRow(on: model.restatePicks.contains("sum"), toggle: { model.toggleRestate("sum") }) { Text("새 요약으로 바꾸기").font(.callout) }
                    TextEditor(text: Binding(get: { model.draft?.summary ?? "" }, set: { v in model.edit { $0.summary = v } }))
                        .frame(minHeight: 90).editorBox()
                        .accessibilityLabel("\(n)화 새 요약")
                }
                group("새 사실 \(it.facts.count)", empty: it.facts.isEmpty ? "새로 나온 사실이 없어요." : nil) {
                    ForEach(it.facts, id: \.self) { i in
                        CheckRow(on: model.restatePicks.contains("f\(i)"), toggle: { model.toggleRestate("f\(i)") }) { Text(d.newFacts?[i] ?? "") }
                    }
                }
                group("새 복선 \(it.plants.count)", empty: it.plants.isEmpty ? "새로 심은 복선이 없어요." : nil) {
                    ForEach(it.plants, id: \.self) { i in
                        CheckRow(on: model.restatePicks.contains("p\(i)"), toggle: { model.toggleRestate("p\(i)") }) { Text("심음: \(d.foreshadowPlanted?[i].description ?? "")") }
                    }
                }
                if !it.places.isEmpty {
                    group("새 장소 \(it.places.count)") {
                        ForEach(it.places, id: \.self) { i in
                            CheckRow(on: model.restatePicks.contains("l\(i)"), toggle: { model.toggleRestate("l\(i)") }) { placeLabel(d.newPlaces![i]) }
                        }
                    }
                }
                let skipped = ReviewText.restateSkipped(d)
                if !skipped.isEmpty { Text("반영하지 않는 항목: \(skipped.joined(separator: ", ")). 뒤 화가 이미 그 상태로 쓰였어요.").note(.plain) }
                if let w = d.warnings, !w.isEmpty { Text(w.joined(separator: "\n")).note(.warn) }
                HStack {
                    Button(model.extractLabel ?? "다시 뽑기") { Task { await model.extract() } }.disabled(model.extractLabel != nil)
                    Button("버리기") { ask = Question(text: "이 변경안을 버릴까요?", button: "버리기", destructive: true) { await model.discard() } }
                    Spacer()
                    Text("고른 것만 반영하고 반영 뒤 고침 표시를 지워요").font(.caption).foregroundStyle(.secondary)
                    Button("선택한 항목 반영") { Task { await model.applyRestate() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.autoRunning || model.busy)
                }
            } else {
                HStack {
                    Button(model.extractLabel ?? "고친 본문에서 다시 뽑기") { Task { await model.extract() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.extractLabel != nil)
                    Button("그대로 두기 (오타 · 문장만 고침)") { Task { await model.keepState() } }
                        .disabled(model.autoRunning || model.busy)
                }
            }
        }
    }

    /// 반영한 변경안 (웹 `historyView`).
    @ViewBuilder
    private func historyView(_ h: StateDelta, _ p: Project) -> some View {
        Card("요약") { Text(h.summary) }
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), alignment: .top)], alignment: .leading, spacing: 16) {
            Card("인물 상태") {
                list((h.characterUpdates ?? []).map { u in
                    let s = [u.emotionalState, u.currentGoal, u.location].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " / ")
                    let k = (u.knows ?? []).isEmpty ? "" : " · 앎: \(u.knows!.joined(separator: ", "))"
                    return "\(ReviewText.name(u.characterId, p)) \(s)\(k)"
                })
            }
            Card("관계 사건") {
                list((h.events ?? []).map { ev in eventLine(ev, h, p) + ((ev.quote ?? "").isEmpty ? "" : "\n“\(ev.quote!)”") })
            }
            Card("사실과 복선") {
                list((h.newFacts ?? []) + (h.foreshadowPlanted ?? []).map { "심음: \($0.description)" }
                    + (h.foreshadowResolved ?? []).map { id in "회수: \((p.foreshadows ?? []).first { $0.id == id }?.description ?? id)" })
            }
            if let c = h.newCharacters, !c.isEmpty {
                Card("새로 나온 인물") { list(c.map { "\($0.name.isEmpty ? $0.id : $0.name) · \($0.role)" }) }
            }
            if let l = h.newPlaces, !l.isEmpty {
                Card("새로 나온 장소") { ForEach(Array(l.enumerated()), id: \.offset) { placeLabel($0.element) } }
            }
            if let s = h.secretsAdded, !s.isEmpty {
                Card("새로 생긴 비밀") { list(s.map { "\(ReviewText.name($0.owner, p)) \($0.content)" }) }
            }
            if let r = h.relationshipUpdates, !r.isEmpty {
                Card("관계 유형 · 설명 변경") {
                    list(r.map { "\(ReviewText.name($0.a, p)) ↔ \(ReviewText.name($0.b, p)) · \($0._type)\(($0.description ?? "").isEmpty ? "" : " · \($0.description!)")" })
                }
            }
        }
    }

    // MARK: 변경안

    @ViewBuilder
    private func delta(_ d: StateDelta, _ e: Episode, _ p: Project) -> some View {
        let n = model.ep
        Text(model.fromHistory ? "반영을 취소한 변경안이에요. 체크한 항목만 데이터에 반영되고, 반영해야 다음 화를 쓸 수 있어요."
            : "AI가 본문에서 뽑은 변경안이에요. 체크한 항목만 데이터에 반영되고, 반영해야 다음 화를 쓸 수 있어요.")
            .foregroundStyle(.secondary)
        if model.document.dirty {
            Text("저장하지 않은 변경이 있어요. 반영하면 먼저 저장해요.").note(.warn)
        } else if model.textChanged {
            HStack {
                Text("이 변경안을 만든 뒤 본문을 고쳤어요. 고친 내용이 상태에 영향을 준다면 변경안을 다시 만드세요.").frame(maxWidth: .infinity, alignment: .leading)
                remakeButton()
            }
            .note(.warn)
        }
        // 열린 검수 지적이 남았거나 검수하지 않았으면 알린다 (웹 `viewReview` 의 issues). 반영은 막지 않는다
        let cs = e.checkState
        if cs.open > 0 {
            HStack {
                Text("열린 검수 지적 \(cs.open)곳이 남아 있어요\(cs.stale ? " (검수 뒤 본문을 고쳤어요)" : "").").frame(maxWidth: .infinity, alignment: .leading)
                Button("검수에서 보기") { go(.check) }
            }
            .note(.warn)
        } else if !cs.checked {
            HStack {
                Text("\(e.plot.number)화는 아직 검수하지 않았어요. 반영해도 되지만, 앞 화와 어긋나는 곳이 있는지 검수에서 먼저 볼 수 있어요.").frame(maxWidth: .infinity, alignment: .leading)
                Button("검수") { go(.check) }
            }
            .note(.plain)
        }
        if let w = d.warnings, !w.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text("경고 \(w.count)건 · 본문을 고칠지 확인하세요").bold()
                ForEach(Array(w.enumerated()), id: \.offset) { Text("• \($0.element)") }
                Button("본문으로") { go(.write) }.buttonStyle(.borderless)
            }
            .note(.warn)
        }
        Card("인물 상태") { characters(d, p) }
        if let c = d.newCharacters, !c.isEmpty {
            Card("새로 나온 인물") {
                ForEach(Array(c.enumerated()), id: \.offset) { i, c in
                    pick("n\(i)") {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(c.name).bold() + Text("  \(c.id) · \(c.role) · \(c.tier == .minor ? "단역" : "조연")으로 추가").font(.caption).foregroundStyle(.secondary)
                            let about = [c.personality, c.appearance, c.goal].compactMap { $0 }.first { !$0.isEmpty }
                            if let about { Text(about).font(.callout) }
                            if let s = c.speechStyle, !s.isEmpty { Text("말투: \(s)").font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
        }
        if let l = d.newPlaces, !l.isEmpty {
            Card("새로 나온 장소") {
                Text("반영하면 인과율에 장소로 등록돼요. 그 뒤로는 이 장소가 나오는 화를 쓸 때 설명이 함께 들어가요.").font(.caption).foregroundStyle(.secondary)
                ForEach(Array(l.enumerated()), id: \.offset) { i, x in pick("l\(i)") { placeLabel(x) } }
            }
        }
        // 관계 줄이 길어 나란히 두면 미리 보기가 올 때마다 자리가 바뀐다. 위아래로 둔다
        events(d, p)
        relations()
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), alignment: .top)], alignment: .leading, spacing: 16) {
            Card("확정 사실") { facts(d) }
            Card("복선") { foreshadows(d, p) }
        }
        timeCard(d, p)
        settingCard(d, p)
        Card {
            HStack {
                Text("\(n)화 요약").font(.headline)
                Spacer()
                Text("\(d.summary.count.formatted())자 · 다음 화 생성에 이 요약이 들어가요").font(.caption).foregroundStyle(.secondary)
            }
            TextEditor(text: Binding(get: { model.draft?.summary ?? "" }, set: { v in model.edit { $0.summary = v } }))
                .frame(minHeight: 100).editorBox()
                .accessibilityLabel("\(n)화 요약")
        }
        HStack {
            remakeButton()
            Button("버리기") { ask = Question(text: "이 변경안을 버릴까요?", button: "버리기", destructive: true) { await model.discard() } }
            Button("본문으로") { go(.write) }
        }
        HStack {
            Text("\(model.total)건 중 \(model.pickedCount)건 선택").foregroundStyle(.secondary)
            Spacer()
            Button("선택한 항목 반영하고 \(n)화 완료") {
                let why = model.applyReasons
                if why.isEmpty { Task { await model.apply() } } else {
                    ask = Question(text: ReviewText.applyQuestion(why, ep: n), button: "\(n)화 마치기") { await model.apply() }
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.autoRunning || model.busy)
        }
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
    }

    private func remakeButton() -> some View {
        Button(model.extractLabel ?? "변경안 다시 만들기") {
            if model.edited {
                ask = Question(text: "고친 요약과 체크를 버리고 변경안을 다시 만들까요?", button: "다시 만들기", destructive: true) { await model.extract() }
            } else {
                Task { await model.extract() }
            }
        }
        .disabled(model.extractLabel != nil)
    }

    @ViewBuilder
    private func characters(_ d: StateDelta, _ p: Project) -> some View {
        let updates = d.characterUpdates ?? []
        if updates.isEmpty { Text("변경 없음").font(.caption).foregroundStyle(.secondary) }
        ForEach(Array(updates.enumerated()), id: \.offset) { i, u in
            let cur = (p.states ?? []).first { $0.characterId == u.characterId }
            pick("c\(i)") {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(ReviewText.name(u.characterId, p)).bold()
                        if ReviewText.unknown(u.characterId, d, p) { Chip("설정에 없는 인물", tint: .orange) }
                        Spacer()
                        editButton("c\(i)")
                    }
                    if editing.contains("c\(i)") {
                        field("감정", \.emotionalState, i)
                        field("목표", \.currentGoal, i)
                        field("위치", \.location, i)
                        field("메모", \.notes, i)
                    } else {
                        ForEach(ReviewText.stateRows(u, current: cur), id: \.label) { diff($0) }
                    }
                    let stats = ReviewText.statRows(u, current: cur)
                    if !stats.isEmpty {
                        Text("상태창").font(.caption).foregroundStyle(.secondary)
                        ForEach(Array(stats.enumerated()), id: \.offset) { _, s in
                            HStack(spacing: 6) {
                                Text(s.name).font(.caption).foregroundStyle(.secondary).frame(minWidth: 60, alignment: .leading)
                                if let b = s.before { Text(b).strikethrough().foregroundStyle(.secondary); Text("→").font(.caption) }
                                if let a = s.after {
                                    Text(a).foregroundStyle(.green)
                                    if let r = s.raw { Text("(\(r))").font(.caption).foregroundStyle(.secondary) }
                                } else {
                                    Text("지움").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    let knows = ReviewText.newKnows(u, current: cur)
                    if !knows.isEmpty {
                        Text("알게 된 정보").font(.caption).foregroundStyle(.secondary)
                        Text(knows.map { "+ \($0)" }.joined(separator: "  ")).foregroundStyle(.green)
                    }
                }
            }
        }
    }

    /// 인물 상태 칸 하나 고치기.
    private func field(_ label: String, _ path: WritableKeyPath<CharacterState, String?>, _ i: Int) -> some View {
        LabeledContent(label) {
            TextField(label, text: Binding(get: { model.draft?.characterUpdates?[i][keyPath: path] ?? "" },
                                           set: { v in model.edit { $0.characterUpdates?[i][keyPath: path] = v } }))
        }
        .font(.callout)
    }

    private func events(_ d: StateDelta, _ p: Project) -> some View {
        Card {
            HStack {
                Text("관계 사건").font(.headline)
                Spacer()
                Text("AI는 사건만 적고, 관계 수치는 Canon 이 계산해요").font(.caption).foregroundStyle(.secondary)
            }
            let evs = d.events ?? []
            if evs.isEmpty { Text("이번 화에 관계 사건이 없어요").font(.caption).foregroundStyle(.secondary) }
            ForEach(Array(evs.enumerated()), id: \.offset) { i, ev in
                pick("e\(i)") {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 6) {
                            Text("\(ReviewText.name(ev.actor, p)) → \(ReviewText.name(ev.target, p))").bold()
                            Chip(ev.kind.rawValue, tint: ReviewText.goodEvents.contains(ev.kind.rawValue) ? .green : .red)
                        }
                        Text(eventDetail(ev, d, p)).font(.caption).foregroundStyle(.secondary)
                        if let q = ev.quote, !q.isEmpty { Text("“\(q)”").font(.callout.italic()).foregroundStyle(.secondary) }
                    }
                }
            }
            if let s = d.secretsAdded, !s.isEmpty {
                Text("새로 생긴 비밀").font(.subheadline.bold()).padding(.top, 6)
                ForEach(Array(s.enumerated()), id: \.offset) { i, x in
                    pick("s\(i)") {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text(ReviewText.name(x.owner, p)).bold()
                                if editing.contains("s\(i)") {
                                    TextField("비밀", text: Binding(get: { model.draft?.secretsAdded?[i].content ?? "" }, set: { v in model.edit { $0.secretsAdded?[i].content = v } }))
                                } else {
                                    Text(x.content)
                                }
                                Spacer()
                                editButton("s\(i)")
                            }
                            Text("모르는 인물: \((x.hiddenFrom ?? []).map { ReviewText.name($0, p) }.joined(separator: ", ").ifEmpty("없음"))").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            if let r = d.relationshipUpdates, !r.isEmpty {
                Text("관계 유형 · 설명 변경").font(.subheadline.bold()).padding(.top, 6)
                ForEach(Array(r.enumerated()), id: \.offset) { i, x in
                    let cur = ReviewText.relation(x.a, x.b, p)
                    pick("r\(i)") {
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text("\(ReviewText.name(x.a, p)) ↔ \(ReviewText.name(x.b, p))").bold()
                                Spacer()
                                editButton("r\(i)")
                            }
                            if editing.contains("r\(i)") {
                                TextField("관계 유형", text: Binding(get: { model.draft?.relationshipUpdates?[i]._type ?? "" }, set: { v in model.edit { $0.relationshipUpdates?[i]._type = v } }))
                                TextField("설명", text: Binding(get: { model.draft?.relationshipUpdates?[i].description ?? "" }, set: { v in model.edit { $0.relationshipUpdates?[i].description = v } }))
                            } else {
                                diff(ReviewText.change("유형", cur?._type, x._type), label: false)
                                if let desc = x.description, !desc.isEmpty { diff(ReviewText.change("설명", cur?.description, desc), label: false) }
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private func eventDetail(_ ev: Components.Schemas.StoryEvent, _ d: StateDelta, _ p: Project) -> String {
        var s = ReviewText.intensity(ev.intensity)
        if let w = ev.witnesses, !w.isEmpty { s += " · 목격: \(w.map { ReviewText.name($0, p) }.joined(separator: ", "))" }
        if let r = ev.revealsSecret, !r.isEmpty { s += " · 드러난 비밀: \(ReviewText.secret(r, d, p))" }
        return s
    }

    private func eventLine(_ ev: Components.Schemas.StoryEvent, _ h: StateDelta, _ p: Project) -> String {
        "\(ReviewText.name(ev.actor, p)) → \(ReviewText.name(ev.target, p)) · \(ev.kind.rawValue) \(eventDetail(ev, h, p))"
    }

    /// 반영하면 계산될 관계 (웹 `relationHeader` · `relationLines`).
    private func relations() -> some View {
        Card {
            HStack {
                Text("반영하면 이렇게 계산돼요").font(.headline)
                Spacer()
                Picker("관계 보기 방식", selection: Binding(get: { model.showNumbers }, set: { v in Task { await model.setShowNumbers(v) } })) {
                    Text("말로").tag(false)
                    Text("숫자로").tag(true)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 160)
            }
            if let error = model.previewError {
                Text(error).note(.error)
            } else if let rel = model.preview {
                let out = ReviewText.relationLines(rel, numbers: model.showNumbers)
                Text(out.head).font(.caption).foregroundStyle(.secondary)
                ForEach(Array(out.lines.enumerated()), id: \.offset) { _, l in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(l.text).foregroundStyle(l.changed ? Color.primary : Color.secondary).fontWeight(l.changed ? .semibold : .regular)
                        if l.changed { Text(l.was.map { "지금: \($0)" } ?? "새 관계").font(.caption).foregroundStyle(.secondary) }
                    }
                }
            } else {
                Text("계산하는 중…").font(.caption).foregroundStyle(.secondary)
            }
            Text("체크를 바꾸면 바로 다시 계산해요. 저장은 반영할 때만 돼요.").font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    @ViewBuilder
    private func facts(_ d: StateDelta) -> some View {
        let facts = d.newFacts ?? []
        if facts.isEmpty { Text("변경 없음").font(.caption).foregroundStyle(.secondary) }
        ForEach(Array(facts.enumerated()), id: \.offset) { i, f in
            pick("f\(i)") {
                HStack {
                    if editing.contains("f\(i)") {
                        TextField("사실", text: Binding(get: { model.draft?.newFacts?[i] ?? "" }, set: { v in model.edit { $0.newFacts?[i] = v } }), axis: .vertical)
                    } else {
                        Text(f)
                    }
                    Spacer()
                    editButton("f\(i)")
                }
            }
        }
    }

    /// 작품 속 시간: 이 화가 끝난 시점과 기한 고르기 (웹 `tlDeltaCard`, 키 k · o). 시점은 보기만 하고 고치기는 웹에서.
    @ViewBuilder
    private func timeCard(_ d: StateDelta, _ p: Project) -> some View {
        let added = d.deadlinesAdded ?? []
        let done = d.deadlinesDone ?? []
        let time = ReviewText.timeText(d.time)
        if time != nil || !added.isEmpty || !done.isEmpty {
            Card("작품 속 시간") {
                if let time { Text("\(model.ep)화가 끝난 시점: \(time)").font(.callout) }
                let have = p.timeline?.deadlines ?? []
                ForEach(Array(added.enumerated()), id: \.offset) { i, x in
                    let old = have.first { $0.id == x.id }
                    pick("k\(i)") {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Chip(old == nil ? "새 기한" : "날 바뀜", tint: .blue)
                                Text(x.what).bold()
                                Text(ReviewText.deadlineDay(x, old: old)).font(.caption).foregroundStyle(.secondary)
                            }
                            if let note = x.note, !note.isEmpty { Text("“\(note)”").font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                }
                ForEach(Array(done.enumerated()), id: \.offset) { i, id in
                    let x = have.first { $0.id == id } ?? added.first { $0.id == id }
                    pick("o\(i)") {
                        HStack {
                            Chip("닫힘", tint: .green)
                            Text(x?.what ?? id)
                            if let day = x?.day, day > 0 { Text("\(day)일째").font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
        }
    }

    /// 인물 설정 바꾸기 (웹 `scDeltaCard`, 키 t). 기본으로 고르지 않는다. 바꾼 뒤 값은 고칠 수 있다.
    @ViewBuilder
    private func settingCard(_ d: StateDelta, _ p: Project) -> some View {
        let list = d.settingChanges ?? []
        if !list.isEmpty {
            Card("인물 설정 바꾸기") {
                Text("기본으로 고르지 않았어요. \(ReviewText.settingNote)").font(.caption).foregroundStyle(.secondary)
                ForEach(Array(list.enumerated()), id: \.offset) { i, x in
                    let field = x.field.rawValue
                    let before = (p.characters ?? []).first { $0.id == x.characterId }.flatMap { ReviewText.settingValue($0, field) }
                    pick("t\(i)") {
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text("\(ReviewText.name(x.characterId, p)) · \(ReviewText.settingLabel(field))").bold()
                                Spacer()
                                editButton("t\(i)")
                            }
                            if let before, !before.isEmpty { Text("\(before) →").font(.caption).foregroundStyle(.secondary) } else { Text("지금은 비어 있어요").font(.caption).foregroundStyle(.secondary) }
                            if editing.contains("t\(i)") {
                                TextField("바꾼 뒤", text: Binding(get: { model.draft?.settingChanges?[i].value ?? "" }, set: { v in model.edit { $0.settingChanges?[i].value = v } }), axis: .vertical)
                            } else {
                                Text(x.value)
                            }
                            if let r = x.reason, !r.isEmpty { Text(r).font(.caption).foregroundStyle(.secondary) }
                            if let q = x.quote, !q.isEmpty { Text("“\(q)”").font(.callout.italic()).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func foreshadows(_ d: StateDelta, _ p: Project) -> some View {
        let planted = d.foreshadowPlanted ?? []
        let resolved = d.foreshadowResolved ?? []
        let clues = ReviewText.clueRows(d, p)
        if planted.isEmpty, resolved.isEmpty, clues.isEmpty { Text("변경 없음").font(.caption).foregroundStyle(.secondary) }
        ForEach(Array(planted.enumerated()), id: \.offset) { i, f in
            pick("p\(i)") {
                HStack {
                    Chip("심음", tint: .blue)
                    if editing.contains("p\(i)") {
                        TextField("복선", text: Binding(get: { model.draft?.foreshadowPlanted?[i].description ?? "" }, set: { v in model.edit { $0.foreshadowPlanted?[i].description = v } }), axis: .vertical)
                    } else {
                        Text(f.description)
                    }
                    Text(f.id).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    editButton("p\(i)")
                }
            }
        }
        ForEach(Array(resolved.enumerated()), id: \.offset) { i, id in
            let f = (p.foreshadows ?? []).first { $0.id == id }
            pick("x\(i)") {
                HStack {
                    Chip("회수", tint: .green)
                    Text(f?.description ?? id)
                    Text(f.map { "\($0.plantedEp)화에 심음" } ?? "알 수 없는 id").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        ForEach(Array(clues.enumerated()), id: \.offset) { i, c in
            pick("q\(i)") {
                VStack(alignment: .leading, spacing: 2) {
                    HStack { Chip(c.note, tint: c.payoff ? .green : .blue); Text(c.label) }
                    Text("“\(c.quote)”").font(.callout.italic()).foregroundStyle(.secondary)
                }
            }
        }
    }

    // MARK: 조각

    private func pick<Content: View>(_ key: String, @ViewBuilder _ content: () -> Content) -> some View {
        CheckRow(on: model.picks.contains(key), toggle: { model.toggle(key) }, content: content)
    }

    private func editButton(_ key: String) -> some View {
        Button(editing.contains(key) ? "완료" : "고치기") {
            if editing.contains(key) { editing.remove(key) } else { editing.insert(key) }
        }
        .buttonStyle(.borderless)
        .font(.caption)
    }

    @ViewBuilder
    private func diff(_ c: ReviewText.Change, label: Bool = true) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            if label { Text(c.label).font(.caption).foregroundStyle(.secondary) }
            HStack(spacing: 6) {
                if let b = c.before { Text(b).strikethrough().foregroundStyle(.secondary); Text("→").font(.caption) }
                Text(c.after).foregroundStyle(.green)
            }
        }
    }

    private func placeLabel(_ x: NewPlace) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(x.name).bold()
                let more = ReviewText.placeDetail(x)
                if !more.isEmpty { Text(more).font(.caption).foregroundStyle(.secondary) }
            }
            if let d = x.description, !d.isEmpty { Text(d).font(.callout) }
        }
    }

    private func group<Content: View>(_ title: String, empty: String? = nil, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            if let empty { Text(empty).font(.caption).foregroundStyle(.secondary) }
            content()
        }
    }

    @ViewBuilder
    private func list(_ items: [String]) -> some View {
        if items.isEmpty {
            Text("없음").font(.caption).foregroundStyle(.secondary)
        } else {
            ForEach(Array(items.enumerated()), id: \.offset) { Text("• \($0.element)").font(.callout) }
        }
    }
}

/// 체크 칸이 붙은 줄. iOS 에는 체크 상자 모양 Toggle 이 없어 단추로 그린다.
struct CheckRow<Content: View>: View {
    let on: Bool
    let toggle: () -> Void
    let content: Content

    init(on: Bool, toggle: @escaping () -> Void, @ViewBuilder content: () -> Content) {
        self.on = on
        self.toggle = toggle
        self.content = content()
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Button(action: toggle) {
                Image(systemName: on ? "checkmark.square.fill" : "square").font(.title3)
                    .foregroundStyle(on ? Color.accentColor : Color.secondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(on ? "고름" : "고르지 않음")
            content.frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 4)
    }
}

/// 제목이 있는 칸 (웹 `.card`).
struct Card<Content: View>: View {
    let title: String?
    @ViewBuilder let content: () -> Content

    init(_ title: String? = nil, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title { Text(title).font(.headline) }
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
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

    func editorBox() -> some View {
        self.scrollContentBackground(.hidden).padding(6)
            .background(.background, in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
    }
}

extension String {
    func ifEmpty(_ other: String) -> String { isEmpty ? other : self }
}
#endif
