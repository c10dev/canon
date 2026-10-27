#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 자동 집필: 목표 화까지 본문 쓰기, 검수, 상태 변경안, 반영을 서버가 반복한다. 승인 정책에 걸리면 그 화에서 멈춘다 (웹 `viewAuto`).
public struct AutoScreen: View {
    @State private var model: AutoModel
    let go: (Screen) -> Void
    @State private var ask: Question?

    public init(document: ProjectDocument, jobs: JobCenter, server: CanonServer, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: AutoModel(document: document, jobs: jobs, service: LiveAutoService(server: server)))
        self.go = go
    }

    init(model: AutoModel, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: model)
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
        .task { await model.watch() }
        .onChange(of: model.form) { old, new in
            guard old != nil, old != new else { return }
            Task { await model.estimate() }
        }
        .alert(ask?.text ?? "", isPresented: Binding(get: { ask != nil }, set: { if !$0 { ask = nil } }), presenting: ask) { q in
            Button(q.button, role: q.destructive ? .destructive : nil) { Task { await q.action() } }
            Button("취소", role: .cancel) {}
        }
    }

    private func content(_ p: Project) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("자동 집필").font(.title2.bold())
                    Text("목표 화까지 본문 쓰기, 검수, 상태 변경안, 반영을 알아서 반복해요. 정해 둔 기준에 걸리면 그 화에서 멈추고 검토를 기다려요.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                if let n = model.notice {
                    Notice(n.text, isError: n.isError) { model.dismissNotice() }
                }
                if let r = model.run { runCard(r, p) }
                if model.canStart {
                    startCard(p)
                } else if !model.active, !model.ended {
                    Button("설정을 바꿔 새로 시작") { model.formOpen = true }
                }
                appliedCard(p)
                logCard()
            }
            .padding()
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .disabled(model.busy)
    }

    // MARK: 실행 카드

    private func runCard(_ r: AutoRun, _ p: Project) -> some View {
        let (label, tone) = model.offline ? (AutoText.offlineLabel, EpisodeStatus.draft) : AutoText.status(r.status)
        let active = model.active
        let stale = r.status == .review && AutoText.pendingStale(r, p)
        let reviewDone = AutoText.reviewDone(r)
        let step = AutoText.stepLine(r, active: active)
        return Card {
            ViewThatFits(in: .horizontal) {
                HStack { runTitle(r, label, tone); Spacer(); batchRow(r) }
                VStack(alignment: .leading) { runTitle(r, label, tone); batchRow(r) }
            }
            ProgressView(value: Double(AutoText.doneCount(p, target: r.target)), total: Double(max(r.target, 1))).tint(.green)
            Text(AutoText.progressLine(r, done: AutoText.doneCount(p, target: r.target)))
                .font(.caption).foregroundStyle(.secondary)
                .help(r.restarts > 0 ? AutoText.restartsHelp : "")
            if model.offline { Text(AutoText.offlineNote).note(.warn) }
            if !step.isEmpty {
                HStack(spacing: 8) { ProgressView().controlSize(.small); Text(step).bold() }
            }
            if active, r.batch { Text(AutoText.batchWait).font(.caption).foregroundStyle(.secondary) }
            if !r.reasons.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(r.reasons.enumerated()), id: \.offset) { Text($0.element) }
                    if AutoText.needsSettings(r) { Text(AutoText.settingsHint) }
                    if !active, let link = AutoText.haltLink(r, p) {
                        Button(link.label) { go(link.screen) }.controlSize(.small)
                    }
                }
                .note(.warn)
            }
            if reviewDone, let n = r.ep { Text(AutoText.reviewDoneNote(n)).note(.ok) }
            if stale, let n = r.ep { Text(AutoText.staleNote(n)).note(.warn) }
            if r.status == .review, r.pending != nil {
                Text(AutoText.reviewHint).font(.caption).foregroundStyle(.secondary)
            }
            if !model.offline { Flow(spacing: 8) { runButtons(r, active: active, reviewDone: reviewDone, stale: stale) } }
            if model.canEditRunPolicy { runPolicy(r) }
        }
    }

    private func runTitle(_ r: AutoRun, _ label: String, _ tone: EpisodeStatus) -> some View {
        HStack(spacing: 8) {
            Text("\(r.target)화까지 자동 집필").font(.headline)
            Chip(label, tone: tone)
        }
    }

    private func batchRow(_ r: AutoRun) -> some View {
        HStack(spacing: 6) {
            Text("배치").font(.caption).foregroundStyle(.secondary)
            batchPicker(Binding(get: { r.batch }, set: { on in Task { await model.setBatch(on) } }))
                .disabled(model.batchLocked)
        }
    }

    @ViewBuilder
    private func runButtons(_ r: AutoRun, active: Bool, reviewDone: Bool, stale: Bool) -> some View {
        let n = r.ep ?? 0
        if active {
            Button("일시정지") { Task { await model.pause() } }
            Button("중지") { askStop() }
        } else if reviewDone {
            Button("이어 가기") { Task { await model.resume() } }.buttonStyle(.borderedProminent)
            Button("중지") { askStop() }
        } else if r.status == .review {
            Button("\(n)화 변경안 검토하기") {
                Task { if await model.sendToReview() { go(.review) } }
            }
            .buttonStyle(.borderedProminent)
            Button("그대로 반영하고 이어 가기") {
                ask = Question(text: AutoText.approveQuestion(n), button: "반영하고 이어 가기") { await model.resume(approve: true) }
            }
            .disabled(stale)
            Button("\(n)화 다시 쓰기") {
                ask = Question(text: AutoText.rewriteQuestion(n), button: "다시 쓰기") { await model.resume(rewrite: true) }
            }
            Button("중지") { askStop() }
        } else if r.status == .paused || r.status == .error {
            Button("이어 가기") { Task { await model.resume() } }.buttonStyle(.borderedProminent)
            Button("중지") { askStop() }
        }
    }

    private func askStop() {
        ask = Question(text: AutoText.stopQuestion, button: "중지", destructive: true) { await model.stop() }
    }

    private func runPolicy(_ r: AutoRun) -> some View {
        DisclosureGroup("승인 정책 바꾸기") {
            VStack(alignment: .leading, spacing: 10) {
                Text(AutoText.runPolicyNote(r)).font(.caption).foregroundStyle(.secondary)
                PolicyForm(policy: Binding(get: { model.runPolicy ?? r.policy }, set: { model.runPolicy = $0 }))
                Button("정책 적용") { Task { await model.applyRunPolicy() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.runPolicyChanged)
            }
            .padding(.top, 8)
        }
    }

    // MARK: 새로 시작

    @ViewBuilder
    private func startCard(_ p: Project) -> some View {
        if let f = model.form {
            Card {
                HStack(alignment: .firstTextBaseline) {
                    Text(model.run == nil ? "시작하기" : "새로 시작").font(.headline)
                    Spacer()
                    if !model.ended { Text(AutoText.restartWarning).font(.caption).foregroundStyle(.secondary) }
                }
                choice("어디까지 쓸까요", formBinding(\.target), targets(p, f.target).map { ($0, "\($0)화까지") })
                VStack(alignment: .leading, spacing: 4) {
                    Text("배치").font(.subheadline)
                    batchPicker(formBinding(\.batch))
                    Text(AutoText.batchNote(model.state?.batchStages ?? [])).font(.caption).foregroundStyle(.secondary)
                }
                PolicyForm(policy: formBinding(\.policy))
                Text("예상 비용과 시간").font(.subheadline.bold())
                estimateView(f)
                Button("\(f.target)화까지 자동 집필 시작") {
                    ask = Question(text: AutoText.startQuestion(f.target, model.pickedEstimate), button: "시작") { await model.begin() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.nothingLeft || model.estimates == nil)
            }
        }
    }

    private func formBinding<T>(_ key: WritableKeyPath<AutoForm, T>) -> Binding<T> {
        Binding(get: { model.form![keyPath: key] }, set: { model.form?[keyPath: key] = $0 })
    }

    /// 목표 화 고르기: 1화부터 작품 목표 화수까지 (플롯이 더 있으면 그 화까지).
    private func targets(_ p: Project, _ current: Int) -> [Int] {
        let last = max(p.meta?.targetEpisodes ?? 1, (p.episodes ?? []).map(\.plot.number).max() ?? 1, current)
        return Array(1...max(last, 1))
    }

    private func batchPicker(_ on: Binding<Bool>) -> some View {
        Picker("배치", selection: on) {
            Text("배치 끔 · 빠르게").tag(false)
            Text("배치 켬 · 절반 비용").tag(true)
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .fixedSize()
    }

    @ViewBuilder
    private func estimateView(_ f: AutoForm) -> some View {
        if let error = model.estimateError {
            Text(error).note(.warn)
        } else if let e = model.estimates {
            if AutoText.nothingLeft(e.off) {
                Text(AutoText.nothingLeftNote(e.off)).note(.plain)
            } else {
                Text(AutoText.estimateLine(e.off)).font(.caption).foregroundStyle(.secondary)
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top) { estimateColumn(e.off, on: false, picked: !f.batch); estimateColumn(e.on, on: true, picked: f.batch) }
                    VStack { estimateColumn(e.off, on: false, picked: !f.batch); estimateColumn(e.on, on: true, picked: f.batch) }
                }
                ForEach(AutoText.estimateWarnings(e.off), id: \.self) { Text($0).note(.warn) }
                ForEach(AutoText.estimateNotes(e.off), id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
            }
        } else {
            Text("추정하는 중…").font(.caption).foregroundStyle(.secondary)
        }
    }

    private func estimateColumn(_ e: AutoEstimate, on: Bool, picked: Bool) -> some View {
        let t = AutoText.estimateTime(e)
        return VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(on ? "배치 켬" : "배치 끔 (일반 호출)").bold()
                if picked { Chip("선택", tone: .confirmed) }
            }
            Text("비용 \(AutoText.cost(e.cost))")
            Text("시간 \(t.time)")
            if !t.note.isEmpty { Text(t.note).font(.caption).foregroundStyle(.secondary) }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).stroke(picked ? Color.accentColor : Color.secondary.opacity(0.3), lineWidth: picked ? 2 : 1))
    }

    // MARK: 검토 없이 반영한 화

    @ViewBuilder
    private func appliedCard(_ p: Project) -> some View {
        let eps = model.autoApplied
        if !eps.isEmpty {
            let style = AutoText.styleWarnings(model.run?.log ?? [])
            Card {
                HStack {
                    Text("검토 없이 반영한 화").font(.headline)
                    Spacer()
                    Text("\(eps.count)화").font(.caption).foregroundStyle(.secondary)
                }
                Text(AutoText.appliedHelp).font(.callout).foregroundStyle(.secondary)
                ForEach(eps, id: \.plot.number) { e in
                    let n = e.plot.number
                    HStack(spacing: 8) {
                        Button { go(.write) } label: { Text("\(n)화").bold() + Text(" \(e.plot.title)") }
                            .buttonStyle(.plain)
                        Spacer()
                        if let c = e.issues?.count, c > 0 { Chip("검수 \(c)", tone: .written) }
                        if let c = style[n] { Chip("문체 경고 \(c)", tone: .written) }
                        if !model.active {
                            Button("\(n)화부터 반영 취소") {
                                ask = Question(text: AutoText.revertQuestion(n, p), button: "반영 취소", destructive: true) { await model.revert(from: n) }
                            }
                            .controlSize(.small)
                        }
                    }
                    Divider()
                }
            }
        }
    }

    // MARK: 진행 로그

    @ViewBuilder
    private func logCard() -> some View {
        if let r = model.run, !r.log.isEmpty {
            Card {
                Text("진행 로그").font(.headline)
                Text("위가 최신이에요. 굵은 선 아래는 지난 실행이에요.").font(.caption).foregroundStyle(.secondary)
                Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 12, verticalSpacing: 6) {
                    GridRow {
                        Text("시각"); Text("화"); Text("내용"); Text("토큰 입력 / 출력"); Text("걸린 시간")
                    }
                    .font(.caption.bold()).foregroundStyle(.secondary)
                    ForEach(Array(model.shownLog.enumerated()), id: \.offset) { _, e in
                        GridRow {
                            Text(AutoText.logTime(e.at)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            Text(e.ep.map { "\($0)화" } ?? "")
                            HStack(spacing: 4) {
                                Text(e.message).foregroundStyle(e.level == .error ? .red : e.level == .warn ? .orange : .primary)
                                if e.batch { Chip("배치", tone: .draft) }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            Text(AutoText.logTokens(e)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            Text(e.seconds > 0 ? AutoText.duration(e.seconds) : "").font(.caption).foregroundStyle(.secondary)
                        }
                        if e.step == "start" {
                            Rectangle().fill(.secondary).frame(height: 2).gridCellUnsizedAxes(.horizontal)
                        }
                    }
                }
                if model.hiddenLog > 0 {
                    Button(AutoText.moreLog(model.hiddenLog)) { model.logAll = true }.controlSize(.small)
                }
            }
        }
    }
}

/// 승인 정책 칸. '진행 방식'(켜면 더 하거나 덜 멈추는 동작)과 '멈출 때'(켜면 더 멈추는 조건)로 나눈다 (웹 `autoPolicyForm`).
/// 칸 값은 서버가 준 정책 그대로다. 앱은 기본값을 정하지 않는다.
struct PolicyForm: View {
    @Binding var policy: Policy

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("진행 방식").font(.subheadline.bold())
            check(\.check, "화마다 검수하기", "앞선 본문·설정과 어긋나는 곳을 찾아요. 끄면 비용과 시간이 줄지만 모순을 놓칠 수 있어요.")
            check(\.confirmPlots, "초안 플롯도 자동으로 확정하고 쓰기", "켜면 덜 멈춰요. 끄면 초안 플롯을 만난 화에서 멈춰요")
            Text("이럴 때는 멈추고 저에게 물어봐 주세요").font(.subheadline.bold())
            Text("걸리는 게 없으면 상태 변경안을 검토 없이 반영하고 다음 화로 가요. 반영한 화는 표시해 두고, 화마다 남는 스냅샷으로 되돌릴 수 있어요.")
                .font(.caption).foregroundStyle(.secondary)
            choice("검수에서 어긋난 곳이 몇 개를 넘으면 멈출까요", value(\.maxIssues, 0), AutoText.issueOptions)
                .disabled(!(policy.check ?? false))
            choice("관계가 크게 움직이면 멈추기", value(\.maxShift, 0.0), AutoText.shiftOptions)
            check(\.stopOnStage, "관계 단계가 바뀌면 멈추기", "호감 → 신뢰, 신뢰 → 균열처럼 관계의 단계가 바뀔 때")
            check(\.stopOnWarnings, "상태 변경안에 경고가 있으면 멈추기", "플롯 사건 누락, 설정이나 말투 위반을 AI가 적었을 때")
            check(\.handPickOpening, "1~3화는 반영하기 전에 멈추기", "독자가 계속 읽을지 정하는 초반 화라 직접 읽고, 필요하면 여는 방식을 비교해 고르세요")
            choice("몇 화마다 멈춰서 읽어 볼까요", value(\.reviewEvery, 0), AutoText.everyOptions)
        }
    }

    private func check(_ key: WritableKeyPath<Policy, Bool?>, _ label: String, _ hint: String) -> some View {
        Toggle(isOn: Binding(get: { policy[keyPath: key] ?? false }, set: { policy[keyPath: key] = $0 })) {
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                Text(hint).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    /// 고르기 칸. 서버 값이 목록에 없으면 그 값도 그대로 보인다 (Picker 는 태그가 없으면 비어 보인다).
    private func value<T: Hashable>(_ key: WritableKeyPath<Policy, T?>, _ fallback: T) -> Binding<T> {
        Binding(get: { policy[keyPath: key] ?? fallback }, set: { policy[keyPath: key] = $0 })
    }
}

/// 이름을 붙인 고르기 칸. iOS 의 메뉴 Picker 는 Form 밖에서 이름을 보이지 않아 따로 적는다.
private func choice<T: Hashable>(_ label: String, _ selection: Binding<T>, _ options: [(value: T, label: String)]) -> some View {
    LabeledContent(label) {
        Picker(label, selection: selection) {
            ForEach(options, id: \.value) { Text($0.label).tag($0.value) }
        }
        .labelsHidden()
    }
}

/// 카드 한 장.
struct Card<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) { content }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.background.secondary, in: RoundedRectangle(cornerRadius: 12))
    }
}

/// 상태 칩. 색은 화 상태 이름으로 고른다 (웹 `.chip.<상태>`).
struct Chip: View {
    let text: String
    let tone: EpisodeStatus

    init(_ text: String, tone: EpisodeStatus) {
        self.text = text
        self.tone = tone
    }

    var body: some View {
        let color: Color = switch tone {
        case .draft: .secondary
        case .confirmed: .blue
        case .written: .orange
        case .finalized: .green
        }
        Text(text).font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2)
            .foregroundStyle(color)
            .background(color.opacity(0.15), in: Capsule())
    }
}

enum NoteKind { case ok, warn, plain }

extension View {
    /// 안내 띠 (웹 `.note`).
    func note(_ kind: NoteKind) -> some View {
        let color: Color = switch kind {
        case .ok: .green
        case .warn: .orange
        case .plain: .secondary
        }
        return self.font(.callout).padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }
}
#endif
