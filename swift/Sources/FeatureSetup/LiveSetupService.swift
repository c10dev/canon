import CanonAPI
import CanonCore
import Foundation

/// 서버의 설정 도우미 엔드포인트 (`web.py` 의 `genre_list` · `relation_views` · `naming_styles` · `names` · `names_check` · `apply_suggestion`).
public struct LiveSetupService: SetupService {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    /// 앱이 보낸 칸이 서버 모델과 맞지 않는다 (422). 대개 서버와 앱의 판이 다르다.
    static let invalid = CanonError.server(status: 422, message: "입력 형식이 맞지 않아요", code: nil)

    public func genres() async throws -> [Genre] {
        switch try await server.call({ try await $0.genreList() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func relationViews() async throws -> [String] {
        switch try await server.call({ try await $0.relationViews() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func namingStyles() async throws -> [NamingStyle] {
        switch try await server.call({ try await $0.namingStyles() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func names(_ project: String, _ body: Components.Schemas.NamesIn) async throws -> NamesOut {
        switch try await server.call({ try await $0.names(path: .init(name: project), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func checkNames(_ project: String, _ body: Components.Schemas.NameCheckIn) async throws -> NameCheck {
        switch try await server.call({ try await $0.namesCheck(path: .init(name: project), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func applySuggestion(_ project: String, _ s: SetupSuggestion) async throws {
        switch try await server.call({ try await $0.applySuggestion(path: .init(name: project), body: .json(s)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
