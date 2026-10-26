import CanonAPI
import CanonCore
import FeatureSettings
import Foundation
import Testing

/// 키 · 환경 변수가 없는 기기의 `GET /api/config` (settings.public 을 그대로 찍은 것). changes 로 칸을 바꾼다.
func cfg(_ changes: [String: Any] = [:], stages: [String: [String: String]] = [:]) -> ConfigView {
    var stageRows: [String: Any] = [:]
    for (s, _) in SettingsText.stages {
        var row = ["provider": "gemini", "source": "default", "model": "gemini-4-argon", "model_source": "default", "env": "", "model_env": ""]
        row.merge(stages[s] ?? [:]) { _, new in new }
        stageRows[s] = row
    }
    var c: [String: Any] = [
        "provider": "gemini", "provider_source": "default", "model": "gemini-4-argon", "model_setting": "gemini-4-argon",
        "model_source": "default", "has_key": false, "key_hint": "", "key_source": "none", "gemini_auth": "key",
        "gemini_auth_source": "default", "vertex_credentials": "", "vertex_credentials_source": "none",
        "vertex_credentials_found": false, "vertex_project": "", "vertex_project_source": "default",
        "vertex_location": "global", "vertex_location_source": "default", "local_url": "http://localhost:11434/v1",
        "local_url_source": "default", "local_model": "", "local_model_source": "default", "has_local_key": false,
        "claude_model": "", "claude_model_source": "default", "claude_bin": "", "claude_bin_source": "default",
        "anthropic_key_hint": "", "anthropic_key_source": "none", "stages": stageRows,
        "stage_settings": [String: String](), "stage_model_settings": [String: String](), "path": "/home/me/.canon/config.json",
    ]
    c.merge(changes) { _, new in new }
    return try! JSONDecoder().decode(ConfigView.self, from: JSONSerialization.data(withJSONObject: c))
}

func decode<T: Decodable>(_ json: String, as _: T.Type = T.self) -> T {
    try! JSONDecoder().decode(T.self, from: Data(json.utf8))
}

/// 뒤 JSON 의 칸이 앞 JSON 의 같은 칸을 덮는다.
func merged<T: Decodable>(_ base: String, _ extra: String, as _: T.Type = T.self) -> T {
    var a = try! JSONSerialization.jsonObject(with: Data(base.utf8)) as! [String: Any]
    a.merge(try! JSONSerialization.jsonObject(with: Data("{\(extra)}".utf8)) as! [String: Any]) { _, new in new }
    return try! JSONDecoder().decode(T.self, from: JSONSerialization.data(withJSONObject: a))
}

func claude(_ extra: String) -> ClaudeStatus {
    merged(#"""
    {"installed": true, "path": "/usr/local/bin/claude", "version": "2.1.288 (Claude Code)", "logged_in": false,
     "account": {"loggedIn": false, "authMethod": "", "apiProvider": "", "email": "", "orgName": "", "organizationName": "", "subscriptionType": ""},
     "env_token": false, "api_key_ignored": false, "message": "", "reason": "login", "login_command": "claude auth login",
     "token_command": "claude setup-token", "auth_method": "", "metered": false}
    """#, extra)
}

@Suite struct StageTextTests {
    @Test func stagesMatchServer() {
        #expect(SettingsText.stages.map(\.id) == ["plan", "write", "check", "state", "name", "revise", "illustration"])
        #expect(SettingsText.providers.map(\.id) == ["gemini", "local", "claude", "claude-api", "mock"])
        #expect(SettingsText.followLabel("revise") == "본문 쓰기 단계를 따름")
        #expect(SettingsText.followLabel("write") == "위 생성 방식을 따름")
    }

    @Test func modelHintFollowsDraft() {
        let c = cfg()
        var d = SettingsDraft(c)
        #expect(SettingsText.stageModelHint("write", draft: d, config: c) == "모델: gemini-4-argon")
        d.model = ""
        #expect(SettingsText.stageModelHint("write", draft: d, config: c) == "모델: 기본")
        d.stages["write"] = "local"
        #expect(SettingsText.stageModelHint("write", draft: d, config: c) == "모델: 서버에 하나뿐인 모델")
        // revise 는 비우면 write 를 따른다
        d.localModel = "qwen3"
        #expect(SettingsText.stageModelHint("revise", draft: d, config: c) == "모델: qwen3")
        d.stages["plan"] = "claude"
        #expect(SettingsText.stageModelHint("name", draft: d, config: c) == "모델: Claude 기본")
        d.provider = "mock"
        #expect(SettingsText.stageModelHint("write", draft: d, config: c) == "모델: mock")
    }

    @Test func stageEnvWins() {
        let c = cfg(stages: ["write": ["provider": "local", "env": "CANON_LLM_WRITE"]])
        var d = SettingsDraft(c)
        d.stages["write"] = "claude"
        #expect(SettingsText.stageModelHint("write", draft: d, config: c) == "모델: 서버에 하나뿐인 모델")
        // 생성 방식이 환경 변수면 칸에서 고친 값이 아니라 서버 값을 따른다
        let e = cfg(["provider": "mock", "provider_source": "env"])
        var de = SettingsDraft(e)
        de.provider = "gemini"
        #expect(SettingsText.stageModelHint("plan", draft: de, config: e) == "모델: mock")
    }

    @Test func envLines() {
        #expect(SettingsText.envNote("env", "CANON_LLM") == "환경 변수 CANON_LLM 가 설정돼 있어 그 값이 우선해요.")
        #expect(SettingsText.envNote("file", "CANON_LLM") == nil)
        let st: StageConfig = decode(#"{"provider": "local", "source": "env", "model": "m", "model_source": "env", "env": "CANON_LLM", "model_env": "CANON_MODEL_STATE"}"#)
        #expect(SettingsText.stageEnvLines("state", st) == ["비워 두면 환경 변수 CANON_LLM 의 백엔드를 따라요.", "환경 변수 CANON_MODEL_STATE 가 우선해요."])
        let none: StageConfig = decode(#"{"provider": "gemini", "source": "default", "model": "m", "model_source": "default", "env": "", "model_env": ""}"#)
        #expect(SettingsText.stageEnvLines("state", none).isEmpty)
    }

    @Test func openSections() {
        #expect(!SettingsText.localOpen(cfg()))  // 기본 주소는 펼치지 않는다
        #expect(SettingsText.localOpen(cfg(["local_url_source": "file"])))
        #expect(SettingsText.localOpen(cfg(["stage_settings": ["write": "local"]])))
        #expect(!SettingsText.stageOpen(cfg(["stage_settings": ["write": ""]])))
        #expect(SettingsText.stageOpen(cfg(["stage_model_settings": ["state": "gemini-3.8-flash"]])))
        #expect(!SettingsText.claudeOpen(cfg()))
        #expect(SettingsText.claudeOpen(cfg(["provider": "claude-api"])))
        #expect(SettingsText.claudeOpen(cfg(["anthropic_key_source": "env"])))
    }
}

@Suite struct KeyTextTests {
    @Test func keyChips() {
        #expect(SettingsText.keyState(cfg()) == .init(text: "없음", ok: false))
        #expect(SettingsText.keyPlaceholder(cfg()) == "AIza… 로 시작하는 키")
        let c = cfg(["key_source": "file", "key_hint": "…1234", "has_key": true])
        #expect(SettingsText.keyState(c) == .init(text: "…1234", ok: true, source: "설정 파일"))
        #expect(SettingsText.keyPlaceholder(c) == "바꿀 때만 입력")
        let a = cfg(["anthropic_key_source": "env", "anthropic_key_hint": "…9999"])
        #expect(SettingsText.anthropicKeyState(a) == .init(text: "…9999", ok: true, source: "환경 변수"))
        #expect(SettingsText.anthropicKeyPlaceholder(cfg()) == "sk-ant- 로 시작하는 키")
    }

    @Test func vertex() {
        #expect(SettingsText.credentialState(cfg()) == nil)
        #expect(SettingsText.credentialState(cfg(["vertex_credentials": "~/.canon/k.json"])) == .init(text: "파일 없음", ok: false))
        #expect(SettingsText.credentialState(cfg(["vertex_credentials": "/k.json", "vertex_credentials_found": true])) == .init(text: "파일 있음", ok: true))
        #expect(SettingsText.projectState(cfg()) == "지금: 없음")
        #expect(SettingsText.projectState(cfg(["vertex_project": "p", "vertex_project_source": "key_file"])) == "지금: 키 파일의 project_id")
    }
}

@Suite struct ModelTextTests {
    let gem = ModelList(models: [], error: "Gemini API 키가 없어요", reason: "no_key")
    let local = ModelList(models: [], error: "연결하지 못했어요", reason: "unreachable")

    @Test func options() {
        #expect(SettingsText.modelOptions(nil).map(\.name) == ["gemini-4-argon", "gemini-3.8-flash"])
        let m = ["gemini": ModelList(models: ["g1"], error: "", reason: ""), "local": ModelList(models: ["q"], error: "", reason: ""),
                 "claude": ModelList(models: ["opus", "sonnet"], error: "", reason: ""), "claude-api": ModelList(models: ["opus", "x"], error: "", reason: "")]
        #expect(SettingsText.modelOptions(m).map(\.name) == ["g1", "q", "opus", "sonnet", "x"])
        #expect(SettingsText.modelOptions(m).map(\.label) == ["Gemini", "로컬 서버", "Claude", "Claude", "Claude"])
    }

    @Test func status() {
        #expect(SettingsText.modelStatus(nil, config: cfg()) == "모델 목록을 불러오는 중…")
        let m = ["gemini": gem, "local": local]
        // 로컬을 쓰지 않으면 로컬 오류는 알리지 않는다
        #expect(SettingsText.modelStatus(m, config: cfg()) == "Gemini: API 키를 넣고 저장하면 목록을 불러와요. 목록에 없으면 이름을 직접 적어도 돼요.")
        #expect(SettingsText.modelStatus(m, config: cfg(["gemini_auth": "vertex"])).hasPrefix("Gemini: 서비스 계정 키 파일과 프로젝트 ID를 넣고 저장하면 목록을 불러와요. "))
        let both = cfg(stages: ["write": ["provider": "local"]])
        #expect(SettingsText.modelStatus(m, config: both) == "Gemini: API 키를 넣고 저장하면 목록을 불러와요 · 로컬 서버: 로컬 서버가 응답하지 않아요. 주소를 확인하세요. 목록에 없으면 이름을 직접 적어도 돼요.")
        let ok = ["gemini": ModelList(models: ["a", "b"], error: "", reason: "")]
        #expect(SettingsText.modelStatus(ok, config: cfg()) == "Gemini 2개. 목록에 없으면 이름을 직접 적어도 돼요.")
        #expect(SettingsText.modelStatus(SettingsText.modelsFailed("서버가 꺼졌어요"), config: cfg()) == "Gemini: 목록을 못 불러왔어요 (서버가 꺼졌어요). 목록에 없으면 이름을 직접 적어도 돼요.")
        #expect(SettingsText.modelStatus(ok, config: cfg(["provider": "claude"], stages: Dictionary(uniqueKeysWithValues: SettingsText.stages.map { ($0.id, ["provider": "claude"]) }))) == "목록에 없으면 이름을 직접 적어도 돼요.")
    }

    @Test func aiWarning() {
        let health: (String) -> ConfigHealth = { merged(#"{"mock": false, "gemini": true, "has_key": true, "local_error": ""}"#, $0) }
        #expect(SettingsText.aiWarning(health: health(#""local": false, "local_error": "꺼짐""#), config: cfg()) == "AI 연결 안 됨: 로컬 모델 서버가 응답하지 않아요 (꺼짐).")
        #expect(SettingsText.aiWarning(health: health(#""local": false"#), config: cfg()) == "AI 연결 안 됨: 로컬 모델 서버가 응답하지 않아요 (주소를 확인하세요).")
        #expect(SettingsText.aiWarning(health: decode(#"{"mock": true, "gemini": false, "has_key": true, "local_error": ""}"#), config: cfg())?.hasPrefix("mock 모드: AI를 부르지 않고") == true)
        #expect(SettingsText.aiWarning(health: health(#""local": null"#), config: cfg(["gemini_auth": "vertex"]))?.hasPrefix("Vertex AI 설정이 덜 됐어요.") == true)
        #expect(SettingsText.aiWarning(health: nil, config: cfg())?.hasPrefix("Gemini API 키가 없어요.") == true)
        #expect(SettingsText.aiWarning(health: nil, config: cfg(["has_key": true])) == nil)
    }
}

@Suite struct ClaudeTextTests {
    @Test func notInstalled() {
        let s = claude(#""installed": false, "path": "", "version": "", "reason": "install", "message": "Claude Code 가 없어요""#)
        let card = SettingsText.claudeCard(s)
        #expect(card.chip == .init(text: "Claude Code 없음", ok: false))
        #expect(card.install == ["Claude Code 가 없어요", "설치: Claude Code 설치 안내 → 터미널에서 claude auth login"])
        #expect(card.steps.isEmpty)
    }

    @Test func loginNeeded() {
        let card = SettingsText.claudeCard(claude(#""api_key_ignored": true"#))
        #expect(card.chip == .init(text: "로그인 필요", ok: false))
        #expect(card.steps.count == 3)
        #expect(card.steps[1] == "claude auth login 을 실행하면 브라우저에 Anthropic 로그인 화면이 열려요. Pro 또는 Max 구독 계정으로 로그인하세요.")
        #expect(card.notes.first?.contains("claude setup-token 으로 1년짜리 토큰을 받아") == true)
        #expect(card.notes.contains("환경 변수 ANTHROPIC_API_KEY 는 구독 호출에 넘기지 않아요. API 키는 'Claude API 키' 방식에서만 써요."))
        #expect(card.notes.last == "Claude Code 2.1.288 (Claude Code) · /usr/local/bin/claude")
        #expect(card.warning == nil)
    }

    @Test func loggedIn() {
        let ok = claude(#""logged_in": true, "reason": "ok", "account": {"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "", "email": "a@b.c", "orgName": "", "organizationName": "Org", "subscriptionType": "max"}"#)
        let card = SettingsText.claudeCard(ok)
        #expect(card.chip == .init(text: "로그인됨", ok: true))
        #expect(card.who == "a@b.c · Org · max")
        #expect(card.steps.isEmpty)
        #expect(card.notes == ["Claude Code 2.1.288 (Claude Code) · /usr/local/bin/claude"])
        let metered = claude(#""logged_in": true, "reason": "metered", "metered": true, "auth_method": "api_key", "message": "종량제예요""#)
        let m = SettingsText.claudeCard(metered)
        #expect(m.chip == .init(text: "로그인됨 (Console API 계정)", ok: false))
        #expect(m.who == "api_key")
        #expect(m.warning == "종량제예요")
    }
}

@Suite struct DraftTests {
    @Test func untouchedSendsOnlyStagesAndClaude() {
        let c = cfg()
        let b = SettingsDraft(c).body(c)
        #expect(b.provider == nil)
        #expect(b.model == nil)
        #expect(b.localUrl == nil)
        #expect(b.localModel == nil)
        #expect(b.apiKey == nil)
        #expect(b.localKey == nil)
        #expect(b.anthropicApiKey == nil)
        #expect(b.geminiAuth == nil)
        #expect(b.vertexCredentials == nil)
        #expect(b.vertexProject == nil)
        #expect(b.vertexLocation == nil)
        #expect(b.claudeModel == "")
        #expect(b.claudeBin == "")
        #expect(b.stages?.additionalProperties == Dictionary(uniqueKeysWithValues: SettingsText.stages.map { ($0.id, "") }))
        #expect(b.stageModels?.additionalProperties.count == 7)
    }

    @Test func changedAndFileValuesAreSent() {
        let c = cfg(["provider_source": "file", "vertex_location_source": "file"])
        var d = SettingsDraft(c)
        d.model = " gemini-3.8-flash "
        d.apiKey = "  AIzaTEST  "
        d.geminiAuth = "vertex"
        d.stageModels["state"] = " flash "
        let b = d.body(c)
        #expect(b.provider == "gemini")  // 설정 파일 값은 그대로 다시 보낸다
        #expect(b.model == "gemini-3.8-flash")
        #expect(b.apiKey == "AIzaTEST")
        #expect(b.geminiAuth == "vertex")
        #expect(b.vertexLocation == "global")
        #expect(b.stageModels?.additionalProperties["state"] == "flash")
    }

    @Test func clearStages() {
        let c = cfg(["stage_settings": ["write": "local"], "stage_model_settings": ["state": "flash"]])
        var d = SettingsDraft(c)
        #expect(d.stages["write"] == "local")
        #expect(!d.stagesCleared)
        d.clearStages()
        #expect(d.stagesCleared)
        #expect(d.body(c).stages?.additionalProperties["write"] == "")
    }
}

final class FakeSettings: SettingsService, @unchecked Sendable {
    var current: ConfigView
    var sent: [SettingsIn] = []
    var tests = 0
    var fail: CanonError?

    init(_ c: ConfigView = cfg()) { current = c }

    func config() async throws -> ConfigView { current }

    func save(_ body: SettingsIn) async throws -> ConfigView {
        sent.append(body)
        if let fail { throw fail }
        if body.apiKey != nil { current = cfg(["key_source": "file", "key_hint": "…TEST", "has_key": true]) }
        if body.clearKey == true { current = cfg() }
        return current
    }

    func test() async throws -> String {
        tests += 1
        return "gemini-4-argon 에 연결됐어요."
    }

    func models() async throws -> [String: ModelList] { ["gemini": ModelList(models: ["gemini-4-argon"], error: "", reason: "")] }

    func health() async throws -> ConfigHealth { decode(#"{"mock": false, "gemini": true, "has_key": \#(current.hasKey), "local_error": ""}"#) }

    func claudeStatus() async throws -> ClaudeStatus { claude("") }
}

@MainActor
@Suite struct ModelTests {
    @Test func loadAndSaveForgetsKey() async {
        let fake = FakeSettings()
        let m = SettingsModel(service: fake, now: { Date(timeIntervalSince1970: 0) })
        await m.load()
        #expect(m.config != nil)
        #expect(m.models?["gemini"]?.models == ["gemini-4-argon"])
        #expect(m.claude?.reason == "login")
        #expect(m.aiWarning?.hasPrefix("Gemini API 키가 없어요.") == true)
        #expect(!m.dirty)
        m.draft.apiKey = "AIzaTEST"
        #expect(m.dirty)
        #expect(await m.save())
        #expect(fake.sent.last?.apiKey == "AIzaTEST")
        #expect(m.draft.apiKey == "")  // 키는 칸에 남기지 않는다
        #expect(!m.dirty)
        #expect(m.config?.keyHint == "…TEST")
        #expect(m.notice?.text == "설정을 저장했어요")
        #expect(m.saved?.what == "저장했어요")
        #expect(m.aiWarning == nil)
    }

    @Test func failedSaveKeepsTyping() async {
        let fake = FakeSettings()
        let m = SettingsModel(service: fake)
        await m.load()
        fake.fail = CanonError.server(status: 400, message: "provider 는 gemini / local 중 하나예요", code: nil)
        m.draft.apiKey = "AIzaTEST"
        #expect(await m.save() == false)
        #expect(m.draft.apiKey == "AIzaTEST")
        #expect(m.notice?.isError == true)
        // 저장하지 못하면 연결 확인도 하지 않는다
        await m.test(saveFirst: true)
        #expect(fake.tests == 0)
        fake.fail = nil
        await m.test(saveFirst: true)
        #expect(fake.tests == 1)
        #expect(m.notice?.text == "gemini-4-argon 에 연결됐어요.")
    }

    @Test func clearKey() async {
        let fake = FakeSettings(cfg(["key_source": "file", "key_hint": "…TEST", "has_key": true]))
        let m = SettingsModel(service: fake)
        await m.load()
        await m.clearKey()
        #expect(fake.sent.last?.clearKey == true)
        #expect(fake.sent.last?.apiKey == nil)
        #expect(m.config?.keySource == "none")
        #expect(m.notice?.text == "키를 지웠어요")
        m.draft.provider = "local"
        m.discard()
        #expect(!m.dirty)
    }
}
