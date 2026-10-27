import CanonAPI
import CanonCore
import Foundation

/// 서버의 문체 엔드포인트 (`web.py` 의 `analyze_style` · `measure` · `style_link` · `list_styles` · `apply_library_style` · `keep_style`).
public struct LiveStyleService: StyleService {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    /// 앱이 보낸 칸이 서버 모델과 맞지 않는다 (422). 대개 서버와 앱의 판이 다르다.
    static let invalid = CanonError.server(status: 422, message: "입력 형식이 맞지 않아요", code: nil)

    public func analyze(_ project: String, _ text: String) async throws -> StyleProfile {
        switch try await server.call({ try await $0.analyzeStyle(path: .init(name: project), body: .json(.init(text: text))) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func measure(_ text: String) async throws -> StyleMetrics {
        switch try await server.call({ try await $0.measure(body: .json(.init(text: text))) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func link(_ project: String) async throws -> StyleLink {
        switch try await server.call({ try await $0.styleLink(path: .init(name: project)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func library() async throws -> [StyleSummary] {
        switch try await server.call({ try await $0.listStyles() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func apply(_ project: String, styleID: String) async throws {
        switch try await server.call({ try await $0.applyLibraryStyle(path: .init(name: project), body: .json(.init(styleId: styleID))) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func keep(_ project: String, _ body: Components.Schemas.StyleKeep) async throws -> StyleSummary {
        switch try await server.call({ try await $0.keepStyle(path: .init(name: project), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json.entry
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
