import CanonAPI
import CanonCore
import Foundation

public typealias ConfigView = Components.Schemas.ConfigView
public typealias StageConfig = Components.Schemas.StageConfig
public typealias ConfigHealth = Components.Schemas.ConfigHealth
public typealias ModelList = Components.Schemas.ModelList
public typealias ClaudeStatus = Components.Schemas.ClaudeStatus
public typealias SettingsIn = Components.Schemas.SettingsIn

/// 설정 화면의 문구와 규칙. 웹 `app.js` 의 `viewSettings` · `stageModelHint` · `modelStatus` · `aiWarning`,
/// `vertex.js` 의 `geminiAuthSettings`, `claude.js` 의 `claudeStatusView` · `claudeSettings` 와 같다.
public enum SettingsText {
    public static let title = "모델 · API 키 설정"
    public static let intro = "여기서 저장한 값은 이 컴퓨터의 설정 파일에만 들어가요. 작품 폴더나 저장소에는 들어가지 않아요."
    /// 앱에서 덧붙이는 말: 설정 파일은 앱이 아니라 서버 컴퓨터에 있다.
    public static let appNote = "앱은 키를 기기에 저장하지 않아요. 적은 키는 서버로 보내 서버 컴퓨터의 설정 파일에 들어가요."

    // MARK: 생성 방식과 단계

    /// 생성 방식 고르기 (`providerOptions`). 서버 `settings.PROVIDERS` 와 같은 값.
    public static let providers: [(id: String, label: String)] = [
        ("gemini", "Gemini API"), ("local", "로컬 서버 (OpenAI 호환)"), ("claude", "Claude 구독 로그인 (Claude Code)"),
        ("claude-api", "Claude API 키"), ("mock", "mock (AI 호출 없이 화면 확인용)"),
    ]

    public static func providerLabel(_ id: String) -> String {
        providers.first { $0.id == id }?.label ?? id
    }

    /// 단계 (`STAGES`, 서버 `settings.STAGES`).
    public static let stages: [(id: String, label: String)] = [
        ("plan", "계획 (설정 제안, 문체 분석, 기승전결, 화별 플롯)"), ("write", "본문 쓰기"), ("check", "검수"), ("state", "상태 변경안"),
        ("name", "이름·지명 AI 추천"), ("revise", "본문 부분 수정"), ("illustration", "삽화 프롬프트"),
    ]

    /// 백엔드를 비우면 따르는 단계 (`STAGE_PARENT`, 서버 `settings.STAGE_PARENT`).
    public static let stageParent = ["name": "plan", "revise": "write", "illustration": "plan"]

    /// 단계 백엔드의 빈 선택 이름 (`STAGE_PARENT_LABEL`).
    public static func followLabel(_ stage: String) -> String {
        ["name": "계획 단계를 따름", "revise": "본문 쓰기 단계를 따름", "illustration": "계획 단계를 따름"][stage] ?? "위 생성 방식을 따름"
    }

    /// 값의 출처 이름 (`src`).
    public static func sourceLabel(_ source: String) -> String {
        ["env": "환경 변수", "file": "설정 파일", "default": "기본값", "none": "없음"][source] ?? ""
    }

    /// 환경 변수가 이긴다는 안내 (`envNote`). 환경 변수가 아니면 nil.
    public static func envNote(_ source: String, _ name: String) -> String? {
        source == "env" ? "환경 변수 \(name) 가 설정돼 있어 그 값이 우선해요." : nil
    }

    /// 단계 줄의 환경 변수 안내. 단계 자체의 환경 변수는 선택보다 우선하고, 물려받은 것(CANON_LLM, 부모 단계)은 비워 둘 때만 따른다.
    public static func stageEnvLine(_ name: String, own: String, what: String) -> String? {
        if name.isEmpty { return nil }
        return name == own ? "환경 변수 \(name) 가 우선해요." : "비워 두면 환경 변수 \(name) 의 \(what) 따라요."
    }

    public static func stageEnvLines(_ stage: String, _ st: StageConfig?) -> [String] {
        guard let st else { return [] }
        let up = stage.uppercased()
        return [stageEnvLine(st.env, own: "CANON_LLM_\(up)", what: "백엔드를"),
                stageEnvLine(st.modelEnv, own: "CANON_MODEL_\(up)", what: "모델을")].compactMap { $0 }
    }

    /// 단계 줄의 모델 칸 안내: 지금 고른 백엔드(비우면 부모 단계, 그다음 위 생성 방식)의 기본 모델 (`stageModelHint`).
    /// 저장 전에도 고친 값을 따라간다.
    public static func stageModelHint(_ stage: String, draft: SettingsDraft, config c: ConfigView) -> String {
        let top = c.providerSource == "env" ? c.provider : draft.provider
        func prov(_ x: String) -> String {
            let st = c.stages.additionalProperties[x]
            if let st, st.env == "CANON_LLM_\(x.uppercased())" { return st.provider }  // 단계 환경 변수가 이긴다
            let own = draft.stages[x] ?? ""
            if !own.isEmpty { return own }
            return stageParent[x].map(prov) ?? top
        }
        let p = top == "mock" ? "mock" : prov(stage)  // 생성 방식이 mock 이면 모든 단계가 mock
        if p == "mock" { return "모델: mock" }
        if p == "local" { return "모델: \(draft.localModel.isEmpty ? "서버에 하나뿐인 모델" : draft.localModel)" }
        if p.hasPrefix("claude") { return "모델: \(draft.claudeModel.isEmpty ? "Claude 기본" : draft.claudeModel)" }
        return "모델: \(draft.model.isEmpty ? "기본" : draft.model)"
    }

    // MARK: 펼침

    /// 로컬 서버 칸을 펼쳐 둘지: 쓰고 있을 때만.
    public static func localOpen(_ c: ConfigView) -> Bool {
        c.provider == "local" || (!c.localUrl.isEmpty && !["default", "none"].contains(c.localUrlSource))
            || c.stageSettings.additionalProperties.values.contains("local")
    }

    public static func stageOpen(_ c: ConfigView) -> Bool {
        c.stageSettings.additionalProperties.values.contains { !$0.isEmpty }
            || c.stageModelSettings.additionalProperties.values.contains { !$0.isEmpty }
    }

    /// Claude 칸: Claude 를 쓰고 있거나 키 · 모델을 넣었으면 펼친다.
    public static func claudeOpen(_ c: ConfigView) -> Bool {
        c.provider.hasPrefix("claude") || c.stageSettings.additionalProperties.values.contains { $0.hasPrefix("claude") }
            || c.anthropicKeySource != "none" || !c.claudeModel.isEmpty
    }

    // MARK: 키

    /// 지금 키 상태 칩. ok 가 false 면 빨강.
    public struct Chip: Equatable, Sendable {
        public let text: String
        public let ok: Bool
        /// 칩 옆의 출처 ('환경 변수', '설정 파일').
        public var source = ""

        public init(text: String, ok: Bool, source: String = "") {
            self.text = text
            self.ok = ok
            self.source = source
        }
    }

    public static func keyState(_ c: ConfigView) -> Chip {
        c.keySource == "none" ? Chip(text: "없음", ok: false) : Chip(text: c.keyHint, ok: true, source: sourceLabel(c.keySource))
    }

    public static func keyPlaceholder(_ c: ConfigView) -> String {
        c.keySource == "none" ? "AIza… 로 시작하는 키" : "바꿀 때만 입력"
    }

    public static let keyHelp = "Google AI Studio에서 무료로 발급받을 수 있어요. 저장한 키는 화면에 다시 보여주지 않아요."
    public static let keyURL = "https://aistudio.google.com/apikey"

    public static func anthropicKeyState(_ c: ConfigView) -> Chip {
        let src = c.anthropicKeySource
        return src == "none" ? Chip(text: "없음", ok: false)
            : Chip(text: c.anthropicKeyHint, ok: true, source: src == "env" ? "환경 변수" : "설정 파일")
    }

    public static func anthropicKeyPlaceholder(_ c: ConfigView) -> String {
        c.anthropicKeySource == "none" ? "sk-ant- 로 시작하는 키" : "바꿀 때만 입력"
    }

    public static let anthropicKeyHelp = "Claude Console에서 발급해요. 구독 로그인 토큰이 아니에요. 저장한 키는 화면에 다시 보여주지 않아요."
    public static let anthropicKeyURL = "https://platform.claude.com/settings/keys"

    public static let clearKeyQuestion = "저장된 API 키를 지울까요?"
    public static let clearAnthropicKeyQuestion = "저장된 Anthropic API 키를 지울까요?"
    public static let testUnsavedQuestion = "입력한 설정을 아직 저장하지 않았어요. 저장한 뒤 연결을 확인할까요?"

    // MARK: Gemini 연결 방식 (vertex.js)

    public static let authChoices: [(id: String, label: String)] = [
        ("key", "API 키 (Google AI Studio)"), ("vertex", "서비스 계정 (Google Cloud Vertex AI)"),
    ]

    public static let authHelp = "Google Cloud 에서 받은 .json 키 파일이 있으면 서비스 계정을 고르세요. AIza… 로 시작하는 키라면 API 키예요."

    /// `VERTEX_SRC`.
    public static func vertexSource(_ source: String) -> String {
        ["env": "환경 변수", "file": "설정 파일", "key_file": "키 파일의 project_id", "default": "기본값", "none": "없음"][source] ?? ""
    }

    /// 키 파일 칸 옆 상태. 비었으면 칩 없이 안내만 (ok 는 무시).
    public static func credentialState(_ c: ConfigView) -> Chip? {
        if c.vertexCredentials.isEmpty { return nil }
        return c.vertexCredentialsFound ? Chip(text: "파일 있음", ok: true) : Chip(text: "파일 없음", ok: false)
    }

    public static let credentialEmpty = "비우면 gcloud 기본 자격 증명"
    public static let credentialHelp = "Canon 을 실행하는 컴퓨터의 파일 경로를 적어요. 파일 내용은 붙여 넣지 마세요. 키 파일은 canon 폴더(저장소) 밖, 예를 들어 ~/.canon/ 에 두고 다른 사람과 나누지 마세요."

    public static func projectState(_ c: ConfigView) -> String {
        "지금: " + (c.vertexProject.isEmpty ? "없음" : vertexSource(c.vertexProjectSource))
    }

    public static let locationHelp = "새 Gemini 모델은 global 에 먼저 나와요. 특정 리전(예: us-central1)에서만 쓰는 모델이면 바꾸세요."
    public static let vertexNote = "Google Cloud 콘솔에서 이 프로젝트의 Vertex AI API 를 켜고, 서비스 계정에 'Vertex AI 사용자' 역할을 줘야 해요. 요금은 그 프로젝트의 결제 계정으로 나가요. Vertex AI 는 배치를 Cloud Storage 로만 받아서, 자동 집필의 배치는 일반 호출로 진행해요."

    // MARK: 모델 목록

    /// 모델 칸 추천 목록에 Gemini 목록을 못 받았을 때 (`KNOWN_MODELS`).
    public static let knownModels = ["gemini-4-argon", "gemini-3.8-flash"]

    /// 모델 칸 추천 (`modelDatalist`): Gemini, 로컬 서버, Claude 순.
    public static func modelOptions(_ m: [String: ModelList]?) -> [(name: String, label: String)] {
        let gemini = m?["gemini"]?.models ?? []
        var out = (gemini.isEmpty ? knownModels : gemini).map { ($0, "Gemini") }
        out += (m?["local"]?.models ?? []).map { ($0, "로컬 서버") }
        var seen = Set<String>()
        out += ((m?["claude"]?.models ?? []) + (m?["claude-api"]?.models ?? [])).filter { seen.insert($0).inserted }.map { ($0, "Claude") }
        return out
    }

    /// 모델 목록 안내 (`modelStatus`). 단계에서 쓰는 백엔드만 알린다 (Gemini 만 쓰면 꺼진 로컬 서버 오류는 보이지 않는다).
    /// nil 이면 불러오는 중. 앱은 첫 문장을 `modelPick` 으로 바꿔 앞에 붙인다.
    public static func modelStatus(_ m: [String: ModelList]?, config c: ConfigView?) -> String {
        guard let m else { return "모델 목록을 불러오는 중…" }
        var used: Set<String> = []
        if let c { used = Set([c.provider] + c.stages.additionalProperties.values.map(\.provider)) }
        func why(_ r: ModelList) -> String {
            switch r.reason {
            case "no_key": c?.geminiAuth == "vertex" ? "서비스 계정 키 파일과 프로젝트 ID를 넣고 저장하면 목록을 불러와요" : "API 키를 넣고 저장하면 목록을 불러와요"
            case "unreachable": "로컬 서버가 응답하지 않아요. 주소를 확인하세요"
            default: "목록을 못 불러왔어요 (\(r.error.prefix(120)))"
            }
        }
        let parts = [("gemini", "Gemini"), ("local", "로컬 서버")].compactMap { k, name -> String? in
            guard used.contains(k), let r = m[k] else { return nil }
            return r.error.isEmpty ? "\(name) \(r.models.count)개" : "\(name): \(why(r))"
        }
        return (parts.isEmpty ? "" : parts.joined(separator: " · ") + ". ") + "목록에 없으면 이름을 직접 적어도 돼요."
    }

    /// 웹은 '모델 칸을 누르면 고를 수 있어요.' 앱은 칸 옆 목록 단추로 고른다.
    public static let modelPick = "모델 칸 옆 목록 단추로 고를 수 있어요."

    /// 모델 목록을 못 받았을 때 (`loadModelList` 의 catch).
    public static func modelsFailed(_ message: String) -> [String: ModelList] {
        ["gemini": ModelList(models: [], error: message, reason: ""), "local": ModelList(models: [], error: message, reason: "")]
    }

    // MARK: AI 연결 경고 (작품 목록 · 사이드바의 `aiWarning`)

    /// AI를 쓸 수 있는지 한 줄. 쓸 수 있으면 nil.
    public static func aiWarning(health h: ConfigHealth?, config c: ConfigView?) -> String? {
        if let h, h.local == false {
            return "AI 연결 안 됨: 로컬 모델 서버가 응답하지 않아요 (\(h.localError.isEmpty ? "주소를 확인하세요" : h.localError))."
        }
        if let h, h.mock { return "mock 모드: AI를 부르지 않고 가짜 결과를 내요. 실제로 쓰려면 설정에서 Gemini 나 로컬을 고르세요." }
        guard let c else { return nil }
        if !c.hasKey && c.geminiAuth == "vertex" { return "Vertex AI 설정이 덜 됐어요. 설정에서 서비스 계정 키 파일 경로와 프로젝트 ID를 확인하세요." }
        if !c.hasKey { return "Gemini API 키가 없어요. 키 없이는 인물 · 설정을 직접 적을 수 있고, 플롯이 생긴 화부터는 채팅 앱 작업지시서로 쓸 수 있어요." }
        return nil
    }

    // MARK: Claude (claude.js)

    public static let claudeIntro = "두 가지 방식이 있어요. Claude 구독 로그인은 이 컴퓨터에 설치하고 로그인한 Claude Code 를 불러 Pro · Max 구독 한도 안에서 써요. Claude API 키는 Claude Console 의 키로 종량제로 써요. 위 '생성 방식'이나 아래 '단계별 백엔드와 모델'에서 고르세요."
    public static let claudePolicy = "Anthropic 정책상 Canon 같은 다른 앱이 Claude 계정 로그인을 받거나 토큰을 보관할 수 없어서, 로그인은 Claude Code 에서 직접 해요. Canon 은 로그인 상태만 확인하고 계정 정보는 저장하지 않아요. 구독 한도는 평범한 개인 사용을 기준으로 하니, 자동 집필처럼 오래 도는 작업은 API 키가 맞아요."
    public static let claudeModelPlaceholder = "비우면 구독은 Claude Code 기본 모델, API 키는 claude-opus-5-5"
    public static let claudeModelHelp = "구독 방식은 opus · sonnet · haiku 같은 별칭도 받아요. 단계마다 바꾸려면 아래 단계별 모델 칸에 적으세요."
    public static let installURL = "https://code.claude.com/docs/en/setup"

    /// 구독 로그인 상태 칸 (`claudeStatusView`).
    public struct ClaudeCard: Equatable, Sendable {
        public var chip: Chip
        /// 칩 옆 계정 줄.
        public var who = ""
        /// 노란 안내 (metered · error).
        public var warning: String?
        /// 설치 안 됨: 안내와 설치 줄.
        public var install: [String] = []
        /// 로그인 순서.
        public var steps: [String] = []
        /// 회색 안내 줄들.
        public var notes: [String] = []
    }

    public static let claudeChecking = "Claude Code 로그인 상태를 확인하는 중…"

    public static func claudeFailed(_ message: String) -> String { "상태를 확인하지 못했어요: \(message)" }

    public static func claudeCard(_ s: ClaudeStatus) -> ClaudeCard {
        if !s.installed {
            return ClaudeCard(chip: Chip(text: "Claude Code 없음", ok: false),
                              install: [s.message, "설치: Claude Code 설치 안내 → 터미널에서 \(s.loginCommand)"])
        }
        let a = s.account
        let org = a.orgName.isEmpty ? a.organizationName : a.orgName
        let who = [a.email, org, a.subscriptionType].filter { !$0.isEmpty }.joined(separator: " · ")
        var card = ClaudeCard(chip: s.loggedIn ? Chip(text: s.metered ? "로그인됨 (Console API 계정)" : "로그인됨", ok: !s.metered)
                                               : Chip(text: "로그인 필요", ok: false))
        if s.loggedIn { card.who = who.isEmpty ? s.authMethod : who }
        if ["metered", "error"].contains(s.reason) { card.warning = s.message }
        if !s.loggedIn {
            card.steps = ["이 컴퓨터(Canon 을 실행하는 곳)에서 터미널을 열어요.",
                          "\(s.loginCommand) 을 실행하면 브라우저에 Anthropic 로그인 화면이 열려요. Pro 또는 Max 구독 계정으로 로그인하세요.",
                          "끝나면 아래 '다시 확인'을 눌러요."]
            card.notes.append("브라우저가 없는 서버(상시 실행)라면 아무 컴퓨터에서 \(s.tokenCommand) 으로 1년짜리 토큰을 받아, Canon 설정이 아니라 서버의 실행 환경 변수 CLAUDE_CODE_OAUTH_TOKEN 에 두세요.")
        }
        if s.envToken { card.notes.append("환경 변수 CLAUDE_CODE_OAUTH_TOKEN 의 토큰으로 로그인해요.") }
        if s.apiKeyIgnored { card.notes.append("환경 변수 ANTHROPIC_API_KEY 는 구독 호출에 넘기지 않아요. API 키는 'Claude API 키' 방식에서만 써요.") }
        card.notes.append("Claude Code \(s.version) · \(s.path)")
        return card
    }

    // MARK: 저장 띠

    /// 저장 버튼 옆 마지막 저장 줄: '저장했어요 · 2026.10.26 14:05'.
    public static func savedLine(_ what: String, at iso: String) -> String {
        "\(what) · \(KoreanText.dateTime(iso))"
    }
}
