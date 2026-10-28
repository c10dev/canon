#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI
import UniformTypeIdentifiers
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

/// 채팅 앱 작업지시서 (API 없이 쓰기): 지시서를 복사해 채팅 앱에 붙여 넣고, 받은 본문 · JSON 을 가져온다 (웹 `viewBrief`).
public struct BriefView: View {
    @State private var model: BriefModel
    let go: (Screen) -> Void
    /// 확인한 변경안을 상태 승인 화면에 넘긴다. 없으면 이 화면에 확인 결과만 보인다.
    let handOff: ((Int, StateDelta) -> Void)?
    @State private var askReplace = false
    @State private var file: BriefFile?

    public init(document: ProjectDocument, service: any BriefService, go: @escaping (Screen) -> Void,
                handOff: ((Int, StateDelta) -> Void)? = nil) {
        _model = State(initialValue: BriefModel(document: document, service: service))
        self.go = go
        self.handOff = handOff
    }

    public var body: some View {
        Group {
            if model.project != nil {
                if let e = model.episode {
                    content(e)
                } else {
                    ContentUnavailableView {
                        Label("아직 화별 플롯이 없어요.", systemImage: "list.number")
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
        .task { await model.start() }
        .alert(BriefText.replaceQuestion(model.ep), isPresented: $askReplace) {
            Button("바꾸기", role: .destructive) { Task { await saveText() } }
            Button("취소", role: .cancel) {}
        }
        .fileExporter(isPresented: Binding(get: { file != nil }, set: { if !$0 { file = nil } }), document: file,
                      contentType: BriefFile.markdown, defaultFilename: file?.name) { _ in }
    }

    private func content(_ e: Episode) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header(e)
                if let n = model.notice { Notice(n.text, isError: n.isError) { model.dismissNotice() } }
                Picker("지시서 종류", selection: Binding(get: { model.kind }, set: { k in Task { await model.setKind(k) } })) {
                    ForEach(BriefKind.allCases, id: \.self) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 16) {
                        briefCard(e).frame(minWidth: 420)
                        importCard(e).frame(minWidth: 340)
                    }
                    VStack(alignment: .leading, spacing: 16) {
                        briefCard(e)
                        importCard(e)
                    }
                }
            }
            .padding()
            .frame(maxWidth: 1200, alignment: .leading)
        }
    }

    private func header(_ e: Episode) -> some View {
        let nums = model.episodes.map(\.plot.number)
        let prev = nums.last { $0 < model.ep }, next = nums.first { $0 > model.ep }
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Button { if let prev { Task { await model.select(prev) } } } label: { Image(systemName: "chevron.left") }
                    .disabled(prev == nil).accessibilityLabel("이전 화")
                Button { if let next { Task { await model.select(next) } } } label: { Image(systemName: "chevron.right") }
                    .disabled(next == nil).accessibilityLabel("다음 화")
                Picker("화", selection: Binding(get: { model.ep }, set: { n in Task { await model.select(n) } })) {
                    ForEach(model.episodes, id: \.plot.number) { x in Text("\(x.plot.number)화 \(x.plot.title)").tag(x.plot.number) }
                }
                .labelsHidden()
                .fixedSize()
                Text(model.status.label).font(.caption.bold()).padding(.horizontal, 6).padding(.vertical, 2)
                    .background(.secondary.opacity(0.15), in: Capsule())
            }
            Text("\(e.plot.number)화 \(e.plot.title) · API 없이 쓰기").font(.caption).foregroundStyle(.secondary)
            Text("채팅 앱 작업지시서").font(.title2.bold())
            Text(BriefText.description).font(.callout).foregroundStyle(.secondary)
        }
    }

    // MARK: ① 지시서

    private func briefCard(_ e: Episode) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("① 복사해서 채팅 앱에 붙여 넣기").font(.headline)
                Spacer()
                Button(".md 내려받기") {
                    if let t = model.text { file = BriefFile(text: t, name: BriefText.filename(model.document.name, ep: model.ep, kind: model.kind)) }
                }
                .disabled(model.text == nil)
                Button("복사") { copy() }.buttonStyle(.borderedProminent).disabled(model.text == nil)
            }
            .controlSize(.small)
            if model.status == .draft, model.kind == .episode { Text(BriefText.draftWarning).note(.warn) }
            if model.stateBlocked {
                VStack(alignment: .leading, spacing: 8) {
                    Text(BriefText.stateBlocked(model.ep, kind: model.kind))
                    Button("본문 작성 지시서로") { Task { await model.setKind(.episode) } }.controlSize(.small)
                }
                .note(.plain)
            } else if let error = model.loadError {
                Text("※ " + error).note(.error)
            } else if let t = model.text {
                ScrollView {
                    Text(t).font(.callout).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(10)
                }
                .frame(minHeight: 240, maxHeight: 420)
                .background(.background, in: RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
                Text(BriefText.length(t)).font(.caption).foregroundStyle(.secondary)
            } else {
                ProgressView("불러오는 중…")
            }
        }
        .card()
    }

    private func copy() {
        guard let t = model.text else { return }
        #if canImport(UIKit)
        UIPasteboard.general.string = t
        model.copied()
        #elseif canImport(AppKit)
        NSPasteboard.general.clearContents()
        if NSPasteboard.general.setString(t, forType: .string) { model.copied() } else { model.copyFailed() }
        #endif
    }

    // MARK: ② 가져오기

    private func importCard(_ e: Episode) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            switch model.kind {
            case .episode: textImport(e)
            case .check: checkImport
            case .state: jsonImport
            }
            Divider()
            Text("순서").font(.caption.bold())
            ForEach(Array(BriefText.steps.enumerated()), id: \.offset) { i, s in
                Text("\(i + 1). \(s)").font(.caption).foregroundStyle(.secondary)
            }
        }
        .card()
    }

    private var draft: Binding<String> {
        Binding(get: { model.draft }, set: { model.draft = $0 })
    }

    @ViewBuilder
    private func textImport(_ e: Episode) -> some View {
        Text("② 받은 본문 가져오기").font(.headline)
        Text("채팅 앱이 쓴 본문을 그대로 붙여 넣으세요.").font(.caption).foregroundStyle(.secondary)
        editor(mono: false).disabled(!BriefText.canImportText(model.status))
        let c = BriefText.count(model.draft, goal: model.project?.meta?.wordsPerEpisode ?? 0)
        HStack(spacing: 6) {
            Text(c.text).font(.caption)
            if c.short { Text(BriefText.shortWarning).font(.caption2.bold()).foregroundStyle(.orange) }
        }
        if let note = BriefText.textNote(model.status) { Text(note).font(.caption).foregroundStyle(.secondary) }
        orderNote
        HStack {
            Spacer()
            Button(BriefText.saveTextButton(model.ep)) {
                if !(e.text ?? "").isEmpty { askReplace = true } else { Task { await saveText() } }
            }
            .buttonStyle(.borderedProminent)
            .disabled(!model.canImport || model.busy)
        }
    }

    @ViewBuilder
    private var checkImport: some View {
        Text("② 받은 검수 JSON 가져오기").font(.headline)
        Text(BriefText.checkNote).font(.caption).foregroundStyle(.secondary)
        editor(mono: true).disabled(!model.canImport)
        if let err = model.importError { Text(err).note(.error).accessibilityAddTraits(.isStaticText) }
        HStack {
            Spacer()
            Button("가져오고 검수로") { Task { if await model.importCheck() { go(.check) } } }
                .buttonStyle(.borderedProminent)
                .disabled(!model.canImport || model.busy)
        }
    }

    @ViewBuilder
    private var jsonImport: some View {
        Text("② 받은 JSON 가져오기").font(.headline)
        Text("채팅 앱의 JSON 답변을 붙여 넣으세요. 코드 블록 표시는 자동으로 지워요.").font(.caption).foregroundStyle(.secondary)
        editor(mono: true).disabled(model.status != .written)
        if model.status != .written { Text(BriefText.jsonNote).font(.caption).foregroundStyle(.secondary) }
        if let err = model.importError { Text(err).note(.error).accessibilityAddTraits(.isStaticText) }
        if let d = model.parsed {
            VStack(alignment: .leading, spacing: 4) {
                Text(BriefText.parsedSummary(d))
                if handOff == nil { Text(BriefText.noHandOff).font(.caption) }
            }
            .note(.info)
        }
        orderNote
        HStack {
            Spacer()
            Button("확인하고 변경안 검토로") { Task { await parseJSON() } }
                .buttonStyle(.borderedProminent)
                .disabled(!model.canImport || model.busy)
        }
    }

    @ViewBuilder
    private var orderNote: some View {
        if let note = BriefText.orderNote(model.order, in: model.episodes) {
            HStack {
                Text(note.text).frame(maxWidth: .infinity, alignment: .leading)
                Button(note.button) { go(note.screen) }
            }
            .note(.warn)
        }
    }

    private func editor(mono: Bool) -> some View {
        TextEditor(text: draft)
            .font(mono ? .callout.monospaced() : .body)
            .frame(minHeight: 220)
            .scrollContentBackground(.hidden)
            .padding(6)
            .background(.background, in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
            .accessibilityLabel(mono ? "받은 JSON" : "받은 본문")
            .autocorrectionDisabled(mono)
            #if os(iOS)
            .textInputAutocapitalization(mono ? .never : .sentences)
            #endif
    }

    private func saveText() async {
        if await model.importText() { go(.write) }
    }

    private func parseJSON() async {
        guard let d = await model.importJSON() else { return }
        if let handOff {
            handOff(model.ep, d)
            go(.review)
        }
    }
}

/// .md 내려받기 (웹 `downloadBrief`).
struct BriefFile: FileDocument {
    static let markdown = UTType(filenameExtension: "md") ?? .plainText
    static let readableContentTypes: [UTType] = [markdown]
    var text: String
    var name: String

    init(text: String, name: String) {
        self.text = text
        self.name = name
    }

    init(configuration: ReadConfiguration) throws {
        text = String(decoding: configuration.file.regularFileContents ?? Data(), as: UTF8.self)
        name = ""
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: Data(text.utf8))
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
#endif
