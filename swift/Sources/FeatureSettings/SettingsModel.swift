import CanonAPI
import CanonCore
import Foundation
import Observation

/// 설정을 주고받는 곳. 시험에서는 가짜로 바꾼다.
public protocol SettingsService: Sendable {
    func config() async throws -> ConfigView
    /// `PUT /api/config`. 저장한 뒤의 설정을 돌려준다.
    func save(_ body: SettingsIn) async throws -> ConfigView
    /// 저장된 설정으로 연결을 확인한다. 화면에 띄울 문구.
    func test() async throws -> String
    func models() async throws -> [String: ModelList]
    func health() async throws -> ConfigHealth
    func claudeStatus() async throws -> ClaudeStatus
}

/// 고치는 중인 설정. 키 칸은 적은 동안만 들고 있다가 저장하면 비운다 (앱에 키를 남기지 않는다).
public struct SettingsDraft: Equatable, Sendable {
    public var provider = ""
    public var model = ""
    public var apiKey = ""
    public var geminiAuth = "key"
    public var vertexCredentials = ""
    public var vertexProject = ""
    public var vertexLocation = ""
    public var localURL = ""
    public var localModel = ""
    public var localKey = ""
    public var claudeModel = ""
    public var claudeBin = ""
    public var anthropicKey = ""
    /// 단계 → 백엔드. '' 이면 위 생성 방식(또는 부모 단계)을 따른다.
    public var stages: [String: String] = [:]
    /// 단계 → 모델. '' 이면 그 백엔드의 기본 모델.
    public var stageModels: [String: String] = [:]

    public init() {}

    /// 서버 설정을 칸에 채운다 (웹 `viewSettings` 의 각 칸 value).
    public init(_ c: ConfigView) {
        provider = c.provider
        model = c.modelSetting
        geminiAuth = c.geminiAuth.isEmpty ? "key" : c.geminiAuth
        vertexCredentials = c.vertexCredentials
        vertexProject = c.vertexProject
        vertexLocation = c.vertexLocation
        localURL = c.localUrl
        localModel = c.localModel
        claudeModel = c.claudeModel
        claudeBin = c.claudeBin
        for (s, _) in SettingsText.stages {
            stages[s] = c.stageSettings.additionalProperties[s] ?? ""
            stageModels[s] = c.stageModelSettings.additionalProperties[s] ?? ""
        }
    }

    /// 단계별 백엔드 · 모델을 모두 비운다 (위 생성 방식과 백엔드 기본 모델을 따름). 저장해야 서버에 들어간다.
    public mutating func clearStages() {
        for (s, _) in SettingsText.stages {
            stages[s] = ""
            stageModels[s] = ""
        }
    }

    public var stagesCleared: Bool {
        !stages.values.contains { !$0.isEmpty } && !stageModels.values.contains { !$0.isEmpty }
    }

    private static func trim(_ s: String) -> String { s.trimmingCharacters(in: .whitespacesAndNewlines) }

    /// 서버에 보낼 값 (웹 `saveSettings` · `geminiAuthBody` · `claudeSettingsBody`).
    /// 환경 변수나 기본값을 보여 주기만 한 칸은 보내지 않는다. 보내면 설정 파일에 굳어 환경 변수를 바꿔도 따라가지 않는다.
    /// 키는 적었을 때만 보낸다 (빈 칸은 '그대로').
    public func body(_ c: ConfigView) -> SettingsIn {
        func shownOnly(_ value: String, source: String, shown: String, quiet: [String] = ["env", "default"]) -> String? {
            quiet.contains(source) && value == shown ? nil : value
        }
        let auth = ["env", "default", "key_file", "none"]
        func filled(_ s: String) -> String? { let t = Self.trim(s); return t.isEmpty ? nil : t }
        return SettingsIn(
            provider: shownOnly(Self.trim(provider), source: c.providerSource, shown: c.provider),
            model: shownOnly(Self.trim(model), source: c.modelSource, shown: c.modelSetting),
            apiKey: filled(apiKey),
            localUrl: shownOnly(Self.trim(localURL), source: c.localUrlSource, shown: c.localUrl),
            localModel: shownOnly(Self.trim(localModel), source: c.localModelSource, shown: c.localModel),
            localKey: filled(localKey),
            stages: .init(additionalProperties: Dictionary(uniqueKeysWithValues: SettingsText.stages.map { ($0.id, stages[$0.id] ?? "") })),
            stageModels: .init(additionalProperties: Dictionary(uniqueKeysWithValues: SettingsText.stages.map { ($0.id, Self.trim(stageModels[$0.id] ?? "")) })),
            claudeModel: Self.trim(claudeModel),
            claudeBin: Self.trim(claudeBin),
            anthropicApiKey: filled(anthropicKey),
            geminiAuth: shownOnly(Self.trim(geminiAuth), source: c.geminiAuthSource, shown: c.geminiAuth.isEmpty ? "key" : c.geminiAuth, quiet: auth),
            vertexCredentials: shownOnly(Self.trim(vertexCredentials), source: c.vertexCredentialsSource, shown: c.vertexCredentials, quiet: auth),
            vertexProject: shownOnly(Self.trim(vertexProject), source: c.vertexProjectSource, shown: c.vertexProject, quiet: auth),
            vertexLocation: shownOnly(Self.trim(vertexLocation), source: c.vertexLocationSource, shown: c.vertexLocation, quiet: auth)
        )
    }
}

/// 모델 · API 키 설정 화면 상태. 웹 `S.config` · `S.models` · `S.claudeStatus` · `S.settingsDirty` 와 같다.
@MainActor
@Observable
public final class SettingsModel {
    public private(set) var config: ConfigView?
    public var draft = SettingsDraft()
    /// 서버 값으로 채운 칸. 이것과 다르면 저장하지 않은 변경이다.
    public private(set) var base = SettingsDraft()
    /// nil 이면 불러오는 중.
    public private(set) var models: [String: ModelList]?
    public private(set) var claude: ClaudeStatus?
    public private(set) var claudeError: String?
    public private(set) var health: ConfigHealth?
    public private(set) var busy: String?
    public private(set) var notice: (text: String, isError: Bool)?
    /// 저장 버튼 옆 마지막 저장 줄.
    public private(set) var saved: (what: String, at: String)?
    private let service: any SettingsService
    private let now: @Sendable () -> Date

    public init(service: any SettingsService, now: @escaping @Sendable () -> Date = Date.init) {
        self.service = service
        self.now = now
    }

    public var dirty: Bool { draft != base }

    public func load() async {
        await run("불러오는 중") {
            setConfig(try await service.config())
        }
        guard config != nil else { return }
        async let m: Void = loadModels()
        async let c: Void = refreshClaude()
        async let h: Void = refreshHealth()
        _ = await (m, c, h)
    }

    private func setConfig(_ c: ConfigView) {
        config = c
        base = SettingsDraft(c)
        draft = base
    }

    public func loadModels() async {
        models = nil
        do {
            models = try await service.models()
        } catch {
            models = SettingsText.modelsFailed(CanonError.message(error))
        }
    }

    public func refreshClaude() async {
        claude = nil
        claudeError = nil
        do {
            claude = try await service.claudeStatus()
        } catch {
            claudeError = CanonError.message(error)
        }
    }

    private func refreshHealth() async {
        health = try? await service.health()
    }

    public var aiWarning: String? { SettingsText.aiWarning(health: health, config: config) }

    // MARK: 저장

    /// 저장. 실패하면 적은 값(키 포함)을 칸에 남긴다.
    @discardableResult
    public func save() async -> Bool {
        guard let c = config else { return false }
        let body = draft.body(c)
        return await change("저장 중", done: "설정을 저장했어요", saved: "저장했어요") { try await self.service.save(body) }
    }

    public func clearKey() async {
        await change("지우는 중", done: "키를 지웠어요", saved: "키를 지웠어요") { try await self.service.save(SettingsIn(clearKey: true)) }
    }

    public func clearAnthropicKey() async {
        await change("지우는 중", done: "Anthropic 키를 지웠어요", saved: nil) { try await self.service.save(SettingsIn(clearAnthropicKey: true)) }
    }

    /// 저장하지 않은 칸은 남기고 서버 값으로 바꾼 칸만 따라가면 헷갈린다. 웹처럼 저장 뒤에는 모든 칸을 서버 값으로 다시 채운다.
    @discardableResult
    private func change(_ label: String, done: String, saved what: String?, _ send: @escaping () async throws -> ConfigView) async -> Bool {
        var ok = false
        await run(label) {
            setConfig(try await send())
            if let what { saved = (what, ISO8601DateFormatter().string(from: now())) }
            notice = (done, false)
            ok = true
        }
        if ok {
            await refreshHealth()
            await loadModels()
        }
        return ok
    }

    /// 서버는 저장된 설정으로 시험한다. 저장하지 않은 칸이 있으면 화면이 먼저 묻고(`SettingsText.testUnsavedQuestion`) `saveFirst` 로 부른다.
    public func test(saveFirst: Bool = false) async {
        if saveFirst {
            guard await save(), !dirty else { return }  // 저장하지 못했다
        }
        await run("연결 확인 중") {
            notice = (try await service.test(), false)
        }
    }

    public func discard() {
        draft = base
    }

    public func dismissNotice() { notice = nil }

    private func run(_ label: String, _ body: () async throws -> Void) async {
        busy = label
        defer { busy = nil }
        do {
            try await body()
        } catch {
            notice = (CanonError.message(error), true)
        }
    }
}

/// 서버에서 설정을 받고 저장한다.
public struct LiveSettingsService: SettingsService {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    public func config() async throws -> ConfigView {
        switch try await server.call({ try await $0.config() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func save(_ body: SettingsIn) async throws -> ConfigView {
        switch try await server.call({ try await $0.putConfig(body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad):
            throw CanonError.from(status: 422, body: (try? JSONEncoder().encode(try bad.body.json)) ?? Data())
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func test() async throws -> String {
        switch try await server.call({ try await $0.testConfig() }) {
        case let .ok(ok): return try ok.body.json.message
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func models() async throws -> [String: ModelList] {
        switch try await server.call({ try await $0.configModels() }) {
        case let .ok(ok): return try ok.body.json.additionalProperties
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func health() async throws -> ConfigHealth {
        switch try await server.call({ try await $0.configHealth() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func claudeStatus() async throws -> ClaudeStatus {
        switch try await server.call({ try await $0.claudeStatus() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
