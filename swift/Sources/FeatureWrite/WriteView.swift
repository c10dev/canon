#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 집필 화면: 화 고르기, 이번 화 플롯, 본문 보기 · 직접 고치기, 쓰기 · 검수 작업, 다시 생성, 복사 · 내보내기 (웹 `viewWrite`).
public struct WriteView: View {
    @State private var model: WriteModel
    let go: (Screen) -> Void
    #if os(iOS)
    @Environment(\.horizontalSizeClass) private var sizeClass
    private var compact: Bool { sizeClass == .compact }
    #else
    private let compact = false
    #endif
    @State private var askSave: (() -> Void)?
    @State private var askRestore: String?

    public init(document: ProjectDocument, jobs: JobCenter, server: CanonServer, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: WriteModel(document: document, jobs: jobs, service: LiveWriteService(server: server)))
        self.go = go
    }

    public var body: some View {
        Group {
            if model.document.project != nil {
                if let e = model.episode {
                    content(e)
                } else {
                    ContentUnavailableView {
                        Label("아직 화별 플롯이 없어요", systemImage: "doc.text")
                    } actions: {
                        Button("기승전결 · 플롯 만들기") { go(.arc) }.buttonStyle(.borderedProminent)
                    }
                }
            } else if let error = model.document.error {
                ContentUnavailableView("작품을 불러오지 못했어요", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("불러오는 중")
            }
        }
        .task {
            await model.document.load()
            await model.loadFormats()
        }
        .confirmationDialog("저장하지 않은 변경이 있어요. 저장하고 작업을 시작할까요?", isPresented: Binding(get: { askSave != nil }, set: { if !$0 { askSave = nil } }), titleVisibility: .visible) {
            Button("저장하고 시작") { askSave?(); askSave = nil }
        }
        .confirmationDialog(RewriteText.restoreAsk, isPresented: Binding(get: { askRestore != nil }, set: { if !$0 { askRestore = nil } }), titleVisibility: .visible) {
            Button("이 판으로 복원") {
                let id = askRestore
                askRestore = nil
                if let id { Task { await model.restore(model.number, version: id) } }
            }
        }
    }

    /// 작업을 시작한다. 저장하지 않은 작품 변경이 있으면 먼저 묻는다 (웹 `startJob` 의 confirm).
    private func startJob(_ run: @escaping () async -> Void) {
        if model.document.dirty {
            askSave = { Task { await run() } }
        } else {
            Task { await run() }
        }
    }

    private func content(_ e: Episode) -> some View {
        let n = e.plot.number
        return ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header(e)
                if let note = model.notice {
                    Notice(note.text, isError: note.isError) { model.dismissNotice() }
                }
                failures(n)
                if e.auto == true {
                    Notice("이 화는 자동 집필이 검토 없이 반영했어요. 읽어 보고 문제가 있으면 자동 집필에서 이 화부터 되돌릴 수 있어요.")
                }
                if let orphan = model.orphan(n) { orphanNote(n, orphan) }
                if !(e.text ?? "").isEmpty && WriteText.editable(e) {
                    if model.rewriteOpen { RewritePanel(model: model, n: n) { startJob($0) } }
                    if let c = e.candidate { CandidateCard(model: model, n: n, candidate: c) }
                }
                if compact {
                    VStack(alignment: .leading, spacing: 16) {
                        bodyCard(e)
                        PlotCard(model: model, episode: e, go: go) { startJob($0) }
                        PublishCard(model: model, n: n)
                    }
                } else {
                    // 넓으면 플롯 · 본문 · 복사를 나란히, 본문 칸이 520pt 보다 좁아지면 본문 아래에 둘을 나란히
                    ViewThatFits(in: .horizontal) {
                        HStack(alignment: .top, spacing: 16) {
                            PlotCard(model: model, episode: e, go: go) { startJob($0) }.frame(width: 260)
                            bodyCard(e).frame(minWidth: 520, maxWidth: .infinity)
                            PublishCard(model: model, n: n).frame(width: 260)
                        }
                        VStack(alignment: .leading, spacing: 16) {
                            bodyCard(e)
                            HStack(alignment: .top, spacing: 16) {
                                PlotCard(model: model, episode: e, go: go) { startJob($0) }
                                PublishCard(model: model, n: n)
                            }
                        }
                    }
                }
                if !(e.versions ?? []).isEmpty { VersionsPanel(model: model, episode: e) { askRestore = $0 } }
            }
            .padding()
            .frame(maxWidth: 1400, alignment: .leading)
        }
        .refreshable { await model.document.load() }
    }

    // MARK: 머리

    private func header(_ e: Episode) -> some View {
        let n = e.plot.number
        let p = model.document.project
        let status = WriteText.status(e)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Button { model.picked = model.previous } label: { Image(systemName: "chevron.left") }
                    .disabled(model.previous == nil).accessibilityLabel("이전 화")
                Button { model.picked = model.next } label: { Image(systemName: "chevron.right") }
                    .disabled(model.next == nil).accessibilityLabel("다음 화")
                Picker("화", selection: Binding(get: { model.number }, set: { model.picked = $0 })) {
                    ForEach(model.episodes, id: \.plot.number) { x in
                        Text("\(x.plot.number)화 \(x.plot.title)").tag(x.plot.number)
                    }
                }
                .labelsHidden()
                .frame(maxWidth: 280)
            }
            .buttonStyle(.bordered)
            Text(WriteText.eyebrow(act: p.flatMap { WriteText.act(n, in: $0) }?.name.rawValue, n: n, target: p?.meta?.targetEpisodes ?? 0))
                .font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 8) {
                Text("\(n)화 \(e.plot.title)").font(.title.bold())
                chip(status.label, color: color(status))
                if e.auto == true { chip("자동 반영", color: .purple) }
            }
            HStack {
                if !(e.text ?? "").isEmpty && WriteText.editable(e) {
                    let label = model.jobs.busyLabel("write", ep: n)
                    Button(label ?? "다시 생성") {
                        if model.rewriteOpen { model.closeRewrite() } else { Task { await model.openRewrite(n) } }
                    }
                    .disabled(label != nil)
                }
                if status == .written {
                    Button("상태 승인으로") { go(.review) }.buttonStyle(.borderedProminent)
                }
            }
            .buttonStyle(.bordered)
        }
    }

    private func chip(_ text: String, color: Color) -> some View {
        Text(text).font(.caption).padding(.horizontal, 8).padding(.vertical, 3)
            .background(color.opacity(0.18), in: Capsule())
    }

    private func color(_ s: EpisodeStatus) -> Color {
        switch s {
        case .draft: .gray
        case .confirmed: .accentColor
        case .written: .orange
        case .finalized: .green
        }
    }

    /// 실패한 쓰기 · 검수 작업: 다시 시도와 닫기.
    @ViewBuilder
    private func failures(_ n: Int) -> some View {
        ForEach(["write", "check"], id: \.self) { kind in
            if let f = model.jobs.failures[Job.key(kind, n)] {
                HStack {
                    Notice("\(f.label) 실패: \(f.error)", isError: true)
                    Button("다시 시도") {
                        startJob { kind == "write" ? await model.write(n) : await model.check(n) }
                    }
                    Button("닫기") { Task { await model.jobs.dismissFailure(f.key) } }
                }
                .buttonStyle(.bordered)
            }
        }
    }

    private func orphanNote(_ n: Int, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("저장하지 않은 \(n)화 초고가 남아 있어요. 이 화는 플롯이 초안이라 본문으로 저장할 수 없어서, 아래에는 저장된 본문을 보여요.")
            DisclosureGroup("남은 초고 보기 (\(WriteText.number(text.utf16.count))자)") {
                Text(text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack {
                Button("초고 복사") { Clipboard.copy(text: text, html: nil) }
                Button("초고 버리기", role: .destructive) { model.discardDraft(n) }
            }
            .buttonStyle(.bordered)
        }
        .padding(10)
        .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }

    // MARK: 본문

    private func bodyCard(_ e: Episode) -> some View {
        let n = e.plot.number
        let status = WriteText.status(e)
        let editable = WriteText.editable(e)
        let text = model.text(n)
        let hasDraft = model.drafts[n] != nil
        let writing = model.writing(n)
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(WriteText.bodyHint(e)).font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
                if status != .draft {
                    Text(WriteText.count(text, goal: model.document.project?.meta?.wordsPerEpisode ?? 0)).font(.caption.monospacedDigit())
                    if !text.isEmpty {
                        Button("복사") { copy([n]) }
                    }
                    if editable && (!(e.text ?? "").isEmpty || hasDraft) {
                        Button("본문 저장") { Task { await model.saveText(n) } }
                            .buttonStyle(.borderedProminent)
                            .tint(model.unsaved(n) ? .accentColor : .secondary)
                            .disabled(!hasDraft || writing || model.busy != nil)
                            .keyboardShortcut("s", modifiers: .command)
                    }
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .padding(10)
            Divider()
            if status == .draft {
                emptyState {
                    Text("\(n)화 플롯이 아직 초안이에요. 확정해야 쓸 수 있어요.")
                    Button("\(n)화 플롯 확정하러 가기") { go(.arc) }.buttonStyle(.borderedProminent)
                }
            } else if (e.text ?? "").isEmpty && !hasDraft {
                writeStart(n)
            } else if editable {
                if writing && (e.text ?? "").isEmpty {
                    Notice("\(n)화 본문을 만드는 중이에요. 끝나면 이 칸이 AI 본문으로 바뀌니 그때 고치세요.").padding(10)
                }
                if model.unsaved(n) {
                    HStack {
                        Text("\(n)화 본문을 저장하지 않았어요").font(.callout)
                        Spacer()
                        Button("고친 것 버리기") { model.discardDraft(n) }
                        Button("본문 저장") { Task { await model.saveText(n) } }.buttonStyle(.borderedProminent).disabled(writing || model.busy != nil)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .padding(10)
                    .background(.thinMaterial)
                }
                TextEditor(text: Binding(get: { model.text(n) }, set: { model.setDraft(n, $0) }))
                    .font(.system(.body, design: .serif))
                    .lineSpacing(6)
                    .frame(minHeight: 560)
                    .padding(8)
                    .disabled(writing && (e.text ?? "").isEmpty)
                    .accessibilityLabel("\(n)화 본문")
            } else {
                Text(text).font(.system(.body, design: .serif)).lineSpacing(6).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(16)
            }
        }
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10))
    }

    /// 본문이 아직 없는 화: AI로 쓰기, 직접 쓰기. 앞 화 반영이 끝나지 않았으면 막는다.
    private func writeStart(_ n: Int) -> some View {
        let blocked = model.blocked(n)
        let busy = model.jobs.busyLabel("write", ep: n)
        return emptyState {
            if let note = WriteText.orderNote(blocked, in: model.episodes) {
                VStack(spacing: 6) {
                    Text(note.text).multilineTextAlignment(.center)
                    Button(note.button) {
                        model.picked = note.ep
                        if note.screen != .write { go(note.screen) }
                    }
                }
                .padding(10)
                .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
            }
            Text("확정된 플롯과 지금까지의 데이터로 \(n)화를 써요.")
            HStack {
                Button(busy ?? "\(n)화 본문 생성") { startJob { await model.write(n) } }
                    .buttonStyle(.borderedProminent)
                    .disabled(!blocked.isEmpty || busy != nil)
                Button("직접 쓰기") { model.startManual(n) }
                    .buttonStyle(.bordered)
                    .disabled(!blocked.isEmpty || model.writing(n))
            }
            if model.writing(n) {
                Text("다른 화면으로 옮겨 가도 계속 써요. 끝나면 알려 드려요.").font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func emptyState<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        VStack(spacing: 12) { content() }
            .frame(maxWidth: .infinity, minHeight: 320)
            .padding()
    }

    private func copy(_ numbers: [Int]) {
        Task {
            guard let out = await model.export(numbers) else { return }
            Clipboard.copy(text: out.text, html: out.html)
            model.copied(out)
        }
    }
}

// MARK: 이번 화 플롯

/// 이번 화 플롯, 승인된 요약, 검수 결과와 검수 단추 (웹 `viewWrite` 왼쪽 칸, `issuesBlock`).
struct PlotCard: View {
    let model: WriteModel
    let episode: Episode
    let go: (Screen) -> Void
    let startJob: (@escaping () async -> Void) -> Void

    var body: some View {
        let e = episode
        let n = e.plot.number
        let p = model.document.project
        VStack(alignment: .leading, spacing: 10) {
            Text("이번 화 플롯").font(.headline)
            if let act = p.flatMap({ WriteText.act(n, in: $0) }) {
                (Text("구간 목표").bold() + Text(" · \(act.goal)")).font(.caption)
                    .padding(8).frame(maxWidth: .infinity, alignment: .leading)
                    .background(.blue.opacity(0.1), in: RoundedRectangle(cornerRadius: 6))
            }
            Text(e.plot.summary).font(.caption).foregroundStyle(.secondary)
            field("사건") {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(e.plot.events.enumerated()), id: \.offset) { i, x in Text("\(i + 1). \(x)").font(.caption) }
                }
            }
            field("등장 인물") { Text(e.plot.characters.map { id in p.map { WriteText.name(id, in: $0) } ?? id }.joined(separator: ", ")).font(.caption) }
            field("감정 변화") { Text(e.plot.emotionalShift).font(.caption) }
            if let o = e.plot.opening, !o.isEmpty { field("여는 장면") { Text(o).font(.caption) } }
            field("엔딩 훅") { Text(e.plot.endingHook).font(.caption) }
            if let q = e.plot.readerQuestion, !q.isEmpty { field("독자가 들고 갈 질문") { Text(q).font(.caption) } }
            if let s = e.summary, !s.isEmpty { field("승인된 요약") { Text(s).font(.caption) } }
            issues(e)
            if !(e.text ?? "").isEmpty {
                let busy = model.jobs.busyLabel("check", ep: n)
                Button(busy ?? WriteText.checkLabel(e)) { startJob { await model.check(n) } }
                    .buttonStyle(.bordered).controlSize(.small)
                    .disabled(busy != nil)
            }
            Button("플롯 보기") { go(.arc) }.font(.caption).buttonStyle(.borderless)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10))
    }

    private func field<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            content()
        }
    }

    @ViewBuilder
    private func issues(_ e: Episode) -> some View {
        let list = e.issues ?? []
        if !list.isEmpty {
            let text = model.text(e.plot.number)
            field("검수에서 찾은 곳 \(list.count)") {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(list.enumerated()), id: \.offset) { i, x in
                        let line = WriteText.issue(x, text: text)
                        VStack(alignment: .leading, spacing: 2) {
                            (Text("\(i + 1). ") + Text(line.type).bold() + Text(" \(line.description)")).font(.caption)
                            if line.current != nil || line.source != nil || line.suggestion != nil {
                                DisclosureGroup("근거와 고칠 방향") {
                                    VStack(alignment: .leading, spacing: 2) {
                                        if let c = line.current { Text(c) }
                                        if let s = line.source { Text(s) }
                                        if let s = line.suggestion { Text(s) }
                                    }
                                    .font(.caption2).textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .font(.caption2)
                            }
                        }
                    }
                }
            }
        }
    }
}
#endif
