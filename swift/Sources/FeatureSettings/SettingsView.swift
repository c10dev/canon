#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonUI
import SwiftUI

/// 모델 · API 키 설정 (웹 `viewSettings`, `vertex.js`, `claude.js`). 작품 목록이나 작품 사이드바에서 시트로 연다.
/// 키는 칸에 적는 동안만 들고 있다가 서버로 보낸다. 앱은 키를 기기에 저장하지 않고, 다시 보일 때는 서버가 주는 끝 네 글자만 쓴다.
/// Claude 구독 로그인은 앱이 하지 않는다. 서버 컴퓨터의 Claude Code 로그인 상태만 보이고 안내한다.
public struct SettingsView: View {
    @State private var model: SettingsModel
    @State private var question: Question?
    @State private var confirmClose = false
    @State private var open: Set<Part> = []
    @State private var opened = false
    @Environment(\.dismiss) private var dismiss

    private enum Part: Hashable { case local, claude, stages }

    private enum Question: String, Identifiable {
        case clearKey, clearAnthropicKey, testUnsaved
        var id: String { rawValue }
        var text: String {
            switch self {
            case .clearKey: SettingsText.clearKeyQuestion
            case .clearAnthropicKey: SettingsText.clearAnthropicKeyQuestion
            case .testUnsaved: SettingsText.testUnsavedQuestion
            }
        }
    }

    public init(model: SettingsModel) {
        _model = State(initialValue: model)
    }

    public init(server: CanonServer) {
        self.init(model: SettingsModel(service: LiveSettingsService(server: server)))
    }

    public var body: some View {
        NavigationStack {
            Group {
                if let c = model.config {
                    form(c)
                } else if model.busy != nil {
                    ProgressView("불러오는 중…").frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ContentUnavailableView {
                        Label("설정을 불러오지 못했어요", systemImage: "exclamationmark.triangle")
                    } description: {
                        Text(model.notice?.text ?? "")
                    } actions: {
                        Button("다시 시도") { Task { await model.load() } }
                    }
                }
            }
            .navigationTitle(SettingsText.title)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar { toolbar }
            .safeAreaInset(edge: .bottom) {
                if let n = model.notice, model.config != nil {
                    Notice(n.text, isError: n.isError) { model.dismissNotice() }.padding()
                }
            }
        }
        #if os(macOS)
        .frame(minWidth: 620, idealWidth: 720, minHeight: 640, idealHeight: 820)
        #endif
        .interactiveDismissDisabled(model.dirty)
        .task {
            await model.load()
            if !opened, let c = model.config {
                opened = true
                if SettingsText.localOpen(c) { open.insert(.local) }
                if SettingsText.claudeOpen(c) { open.insert(.claude) }
                if SettingsText.stageOpen(c) { open.insert(.stages) }
            }
        }
        .alert(question?.text ?? "", isPresented: Binding(get: { question != nil }, set: { if !$0 { question = nil } }), presenting: question) { q in
            switch q {
            case .clearKey: Button("지우기", role: .destructive) { Task { await model.clearKey() } }
            case .clearAnthropicKey: Button("지우기", role: .destructive) { Task { await model.clearAnthropicKey() } }
            case .testUnsaved: Button("저장하고 확인") { Task { await model.test(saveFirst: true) } }
            }
            Button("취소", role: .cancel) {}
        }
        .confirmationDialog("저장하지 않은 설정이 있어요. 닫으면 적은 값이 사라져요.", isPresented: $confirmClose, titleVisibility: .visible) {
            Button("버리고 닫기", role: .destructive) { dismiss() }
        }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .cancellationAction) {
            Button("닫기") { if model.dirty { confirmClose = true } else { dismiss() } }
        }
        ToolbarItemGroup(placement: .confirmationAction) {
            Button("연결 확인") { if model.dirty { question = .testUnsaved } else { Task { await model.test() } } }
                .disabled(model.config == nil || model.busy != nil)
            Button("저장") { Task { await model.save() } }
                .disabled(model.config == nil || model.busy != nil)
        }
    }

    // MARK: 칸

    private func form(_ c: ConfigView) -> some View {
        Form {
            Section {
                Text(SettingsText.intro)
                Text(SettingsText.appNote).foregroundStyle(.secondary)
                if let w = model.aiWarning {
                    Label(w, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                }
            }
            .font(.callout)
            providerSection(c)
            geminiSection(c)
            modelSection(c)
            Section { DisclosureGroup(isExpanded: expanded(.local)) { localFields(c) } label: { partLabel("로컬 서버", "Ollama · llama.cpp 같은 내 컴퓨터의 모델을 쓸 때") } }
            Section { DisclosureGroup(isExpanded: expanded(.claude)) { claudeFields(c) } label: { partLabel("Claude", "구독 로그인이나 API 키로 쓸 때") } }
            Section { DisclosureGroup(isExpanded: expanded(.stages)) { stageFields(c) } label: { partLabel("단계별 백엔드와 모델", "계획 · 본문 · 검수마다 다른 모델을 쓸 때") } }
            Section {
                HStack {
                    Button("저장") { Task { await model.save() } }.buttonStyle(.borderedProminent)
                    Button("연결 확인") { if model.dirty { question = .testUnsaved } else { Task { await model.test() } } }
                        .buttonStyle(.bordered)
                    if model.dirty { Button("고친 것 버리기") { model.discard() }.buttonStyle(.bordered) }
                    Spacer()
                    if let busy = model.busy {
                        ProgressView().controlSize(.small)
                        Text(busy).font(.caption).foregroundStyle(.secondary)
                    } else if let s = model.saved {
                        Text(SettingsText.savedLine(s.what, at: s.at)).font(.caption).foregroundStyle(.secondary)
                    }
                }
                .disabled(model.busy != nil)
            } footer: {
                Text("설정 파일: \(c.path)").textSelection(.enabled)
            }
        }
        .formStyle(.grouped)
    }

    private func providerSection(_ c: ConfigView) -> some View {
        Section {
            Picker("생성 방식", selection: $model.draft.provider) {
                ForEach(SettingsText.providers, id: \.id) { Text($0.label).tag($0.id) }
            }
            notes([SettingsText.envNote(c.providerSource, "CANON_LLM"), "단계별로 다르게 쓰려면 아래 '단계별 백엔드'에서 고르세요."])
        }
    }

    private func geminiSection(_ c: ConfigView) -> some View {
        Section("Gemini") {
            Picker("Gemini 연결 방식", selection: $model.draft.geminiAuth) {
                ForEach(SettingsText.authChoices, id: \.id) { Text($0.label).tag($0.id) }
            }
            notes([SettingsText.envNote(c.geminiAuthSource, "CANON_GEMINI_AUTH 또는 GOOGLE_GENAI_USE_VERTEXAI"), SettingsText.authHelp])
            if model.draft.geminiAuth == "vertex" {
                vertexFields(c)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        Text("Gemini API 키")
                        Text("지금:").font(.caption).foregroundStyle(.secondary)
                        chip(SettingsText.keyState(c))
                    }
                    SecureField(SettingsText.keyPlaceholder(c), text: $model.draft.apiKey)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityLabel("Gemini API 키")
                        .plainInput()
                    linkNote(SettingsText.keyHelp, link: "Google AI Studio", url: SettingsText.keyURL)
                    notes([SettingsText.envNote(c.keySource, "GEMINI_API_KEY")])
                    if c.keySource == "file" {
                        Button("저장된 키 지우기", role: .destructive) { question = .clearKey }.buttonStyle(.bordered)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func vertexFields(_ c: ConfigView) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text("서비스 계정 키 파일 경로")
                if let s = SettingsText.credentialState(c) {
                    Text("지금:").font(.caption).foregroundStyle(.secondary)
                    chip(s)
                } else {
                    Text(SettingsText.credentialEmpty).font(.caption).foregroundStyle(.secondary)
                }
            }
            TextField("예: ~/.canon/vertex-key.json", text: $model.draft.vertexCredentials)
                .textFieldStyle(.roundedBorder).plainInput()
                .accessibilityLabel("서비스 계정 키 파일 경로")
            notes([SettingsText.credentialHelp,
                   SettingsText.envNote(c.vertexCredentialsSource, "CANON_VERTEX_CREDENTIALS 또는 GOOGLE_APPLICATION_CREDENTIALS")])
        }
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text("프로젝트 ID")
                Text(SettingsText.projectState(c)).font(.caption).foregroundStyle(.secondary)
            }
            TextField("비우면 키 파일의 project_id", text: $model.draft.vertexProject)
                .textFieldStyle(.roundedBorder).plainInput()
                .accessibilityLabel("프로젝트 ID")
            notes([SettingsText.envNote(c.vertexProjectSource, "GOOGLE_CLOUD_PROJECT")])
        }
        VStack(alignment: .leading, spacing: 6) {
            Text("리전")
            TextField("global", text: $model.draft.vertexLocation)
                .textFieldStyle(.roundedBorder).plainInput()
                .accessibilityLabel("리전")
            notes([SettingsText.locationHelp, SettingsText.envNote(c.vertexLocationSource, "GOOGLE_CLOUD_LOCATION")])
        }
        notes([SettingsText.vertexNote])
    }

    private func modelSection(_ c: ConfigView) -> some View {
        Section("모델") {
            VStack(alignment: .leading, spacing: 6) {
                modelField("모델", text: $model.draft.model, placeholder: "gemini-4-argon")
                notes(["모든 단계의 기본 Gemini 모델이에요. gemini-4-argon 이 기본이고, 단계마다 바꾸려면 아래 '단계별 백엔드와 모델'에서 고르세요.",
                       SettingsText.envNote(c.modelSource, "CANON_MODEL")])
                HStack(alignment: .firstTextBaseline) {
                    Text(model.models == nil ? SettingsText.modelStatus(nil, config: c)
                         : SettingsText.modelPick + " " + SettingsText.modelStatus(model.models, config: c))
                        .font(.caption).foregroundStyle(.secondary)
                    Button("다시 불러오기") { Task { await model.loadModels() } }
                        .buttonStyle(.borderless).font(.caption).disabled(model.models == nil)
                }
            }
        }
    }

    // MARK: 접는 칸

    @ViewBuilder
    private func localFields(_ c: ConfigView) -> some View {
        notes(["Ollama, llama.cpp, vLLM, LM Studio 처럼 OpenAI 호환 API 를 여는 서버예요. 주소는 /v1 까지 적어요."])
        VStack(alignment: .leading, spacing: 6) {
            Text("서버 주소")
            TextField("http://localhost:11434/v1", text: $model.draft.localURL)
                .textFieldStyle(.roundedBorder).plainInput()
                .accessibilityLabel("로컬 서버 주소")
            notes(["Ollama :11434/v1 · llama.cpp :8080/v1 · vLLM :8000/v1 · LM Studio :1234/v1",
                   SettingsText.envNote(c.localUrlSource, "CANON_LOCAL_URL")])
        }
        VStack(alignment: .leading, spacing: 6) {
            modelField("모델 이름", text: $model.draft.localModel, placeholder: "비우면 서버에 하나뿐인 모델")
            notes([SettingsText.envNote(c.localModelSource, "CANON_LOCAL_MODEL")])
        }
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text("서버 키")
                Text("지금: \(c.hasLocalKey ? "있음" : "없음")").font(.caption).foregroundStyle(.secondary)
            }
            SecureField("서버가 키를 요구할 때만", text: $model.draft.localKey)
                .textFieldStyle(.roundedBorder).plainInput()
                .accessibilityLabel("로컬 서버 키")
        }
    }

    @ViewBuilder
    private func claudeFields(_ c: ConfigView) -> some View {
        notes([SettingsText.claudeIntro, SettingsText.claudePolicy])
        claudeStatus
        VStack(alignment: .leading, spacing: 6) {
            modelField("Claude 모델", text: $model.draft.claudeModel, placeholder: SettingsText.claudeModelPlaceholder)
            notes([SettingsText.claudeModelHelp, c.claudeModelSource == "env" ? "환경 변수 CANON_CLAUDE_MODEL 이 우선해요." : nil])
        }
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text("claude 실행 파일")
                Text("PATH 에서 못 찾을 때만").font(.caption).foregroundStyle(.secondary)
            }
            TextField("예: ~/.local/bin/claude", text: $model.draft.claudeBin)
                .textFieldStyle(.roundedBorder).plainInput()
                .accessibilityLabel("claude 실행 파일")
            notes([c.claudeBinSource == "env" ? "환경 변수 CANON_CLAUDE_BIN 이 우선해요." : nil])
        }
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text("Anthropic API 키")
                Text("'Claude API 키' 방식만 · 지금:").font(.caption).foregroundStyle(.secondary)
                chip(SettingsText.anthropicKeyState(c))
            }
            SecureField(SettingsText.anthropicKeyPlaceholder(c), text: $model.draft.anthropicKey)
                .textFieldStyle(.roundedBorder).plainInput()
                .accessibilityLabel("Anthropic API 키")
            linkNote(SettingsText.anthropicKeyHelp, link: "Claude Console", url: SettingsText.anthropicKeyURL)
            notes([c.anthropicKeySource == "env" ? "환경 변수 ANTHROPIC_API_KEY 가 우선해요." : nil])
            if c.anthropicKeySource == "file" {
                Button("저장된 Anthropic 키 지우기", role: .destructive) { question = .clearAnthropicKey }.buttonStyle(.bordered)
            }
        }
    }

    /// 구독 로그인 상태 (`claudeStatusView`). 로그인 칸은 두지 않는다.
    @ViewBuilder
    private var claudeStatus: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let s = model.claude {
                let card = SettingsText.claudeCard(s)
                HStack(spacing: 6) {
                    Text("구독 로그인")
                    chip(card.chip)
                    if !card.who.isEmpty { Text(card.who).font(.caption).foregroundStyle(.secondary) }
                }
                if let w = card.warning {
                    Label(w, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
                }
                if !card.install.isEmpty {
                    notes(card.install.map(Optional.some))
                    if let url = URL(string: SettingsText.installURL) { Link("Claude Code 설치 안내", destination: url).font(.caption) }
                }
                ForEach(Array(card.steps.enumerated()), id: \.offset) { i, step in
                    Text("\(i + 1). \(step)").font(.caption)
                }
                notes(card.notes.map(Optional.some))
            } else if let e = model.claudeError {
                Label(SettingsText.claudeFailed(e), systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
            } else {
                Text(SettingsText.claudeChecking).font(.caption).foregroundStyle(.secondary)
            }
            Button("다시 확인") { Task { await model.refreshClaude() } }
                .buttonStyle(.bordered)
                .disabled(model.claude == nil && model.claudeError == nil)
        }
    }

    @ViewBuilder
    private func stageFields(_ c: ConfigView) -> some View {
        notes(["예: 계획과 검수는 gemini-4-argon, 상태 변경안과 이름 추천은 빠르고 싼 gemini-3.8-flash, 본문은 로컬 모델. 모델 칸을 비우면 그 백엔드의 기본 모델(위 '모델' 또는 로컬 '모델 이름')을 써요."])
        ForEach(SettingsText.stages, id: \.id) { s in
            let st = c.stages.additionalProperties[s.id]
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(s.label)
                    Text("지금: \(st?.model ?? "")").font(.caption).foregroundStyle(.secondary)
                }
                ViewThatFits(in: .horizontal) {
                    HStack { stagePicker(s); stageModel(s, c) }
                    VStack(alignment: .leading) { stagePicker(s); stageModel(s, c) }
                }
                notes(SettingsText.stageEnvLines(s.id, st).map(Optional.some))
            }
        }
        Button("모두 기본값으로") { model.draft.clearStages() }
            .buttonStyle(.bordered)
            .disabled(model.draft.stagesCleared)
            .help("단계별 백엔드와 모델을 모두 비워요. 저장해야 반영돼요")
    }

    private func stagePicker(_ s: (id: String, label: String)) -> some View {
        Picker("\(s.label) 백엔드", selection: Binding(get: { model.draft.stages[s.id] ?? "" }, set: { model.draft.stages[s.id] = $0 })) {
            Text(SettingsText.followLabel(s.id)).tag("")
            ForEach(SettingsText.providers, id: \.id) { Text($0.label).tag($0.id) }
        }
        .labelsHidden()
        .fixedSize()
        .accessibilityLabel("\(s.label) 백엔드")
    }

    private func stageModel(_ s: (id: String, label: String), _ c: ConfigView) -> some View {
        modelField("\(s.label) 모델", text: Binding(get: { model.draft.stageModels[s.id] ?? "" }, set: { model.draft.stageModels[s.id] = $0 }),
                   placeholder: SettingsText.stageModelHint(s.id, draft: model.draft, config: c), showLabel: false)
    }

    // MARK: 조각

    /// 모델 이름 칸과 추천 목록 단추 (웹 `datalist`).
    private func modelField(_ label: String, text: Binding<String>, placeholder: String, showLabel: Bool = true) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if showLabel { Text(label) }
            HStack(spacing: 6) {
                TextField(placeholder, text: text)
                    .textFieldStyle(.roundedBorder).plainInput()
                    .accessibilityLabel(label)
                Menu {
                    ForEach(Array(SettingsText.modelOptions(model.models).enumerated()), id: \.offset) { _, o in
                        Button("\(o.name) · \(o.label)") { text.wrappedValue = o.name }
                    }
                    if !text.wrappedValue.isEmpty {
                        Divider()
                        Button("비우기") { text.wrappedValue = "" }
                    }
                } label: {
                    Image(systemName: "list.bullet")
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .accessibilityLabel("\(label) 목록")
            }
        }
    }

    private func partLabel(_ title: String, _ sub: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.headline)
            Text(sub).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func expanded(_ part: Part) -> Binding<Bool> {
        Binding(get: { open.contains(part) }, set: { if $0 { open.insert(part) } else { open.remove(part) } })
    }

    /// 회색 안내 줄들. nil 은 빼고, 한 덩어리로 보인다 (Form 안에서 줄마다 칸이 나뉘지 않게).
    @ViewBuilder
    private func notes(_ lines: [String?]) -> some View {
        let shown = lines.compactMap { $0 }
        if !shown.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(shown.enumerated()), id: \.offset) { _, line in
                    Text(line).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    /// 안내 글의 첫 이름(예: 'Google AI Studio')을 링크로.
    private func linkNote(_ text: String, link: String, url: String) -> some View {
        var a = AttributedString(text)
        if let r = a.range(of: link) { a[r].link = URL(string: url) }
        return Text(a).font(.caption).foregroundStyle(.secondary)
    }

    private func chip(_ c: SettingsText.Chip) -> some View {
        HStack(spacing: 4) {
            Text(c.text).font(.caption2.weight(.medium)).lineLimit(1).fixedSize()
                .padding(.horizontal, 6).padding(.vertical, 2)
                .foregroundStyle(c.ok ? Color.green : Color.red)
                .background((c.ok ? Color.green : Color.red).opacity(0.12), in: Capsule())
            if !c.source.isEmpty { Text(c.source).font(.caption).foregroundStyle(.secondary) }
        }
    }
}

private extension View {
    /// 주소 · 키 · 모델 이름 칸: 자동 고침과 첫 글자 대문자를 끈다.
    func plainInput() -> some View {
        #if os(iOS)
        autocorrectionDisabled().textInputAutocapitalization(.never)
        #else
        autocorrectionDisabled()
        #endif
    }
}
#endif
