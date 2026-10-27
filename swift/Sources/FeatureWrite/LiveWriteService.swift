import CanonAPI
import CanonCore
import CanonStore

/// 실제 서버에 붙는 집필 화면 호출 (web.py '4. 본문' · '4-0. 다시 생성' · '4-2. 복사 · 내보내기').
public struct LiveWriteService: WriteServing {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    public func saveText(_ project: String, ep: Int, text: String) async throws -> Project {
        switch try await server.call({ try await $0.putText(path: .init(name: project, n: ep), body: .json(.init(text: text))) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func rewriteInfo(_ project: String, ep: Int) async throws -> RewriteInfo {
        switch try await server.call({ try await $0.rewriteInfo(path: .init(name: project, n: ep)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func rewritePrompt(_ project: String, ep: Int, request: RewriteRequest) async throws -> String {
        switch try await server.call({ try await $0.rewritePrompt(path: .init(name: project, n: ep), body: .json(request)) }) {
        case let .ok(ok):
            let x = try ok.body.json
            return "[시스템]\n\(x.system)\n\n[프롬프트]\n\(x.prompt)"
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func adopt(_ project: String, ep: Int) async throws -> Project {
        switch try await server.call({ try await $0.adoptCandidate(path: .init(name: project, n: ep)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func dropCandidate(_ project: String, ep: Int) async throws -> Project {
        switch try await server.call({ try await $0.dropCandidate(path: .init(name: project, n: ep)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func restore(_ project: String, ep: Int, version: String) async throws -> Project {
        switch try await server.call({ try await $0.restoreVersion(path: .init(name: project, n: ep, vid: version)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func formats() async throws -> [PublishFormat] {
        switch try await server.call({ try await $0.publishFormats() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func export(_ project: String, episodes: [Int], format: String, title: Bool, drafts: [Int: String]) async throws -> ExportOut {
        let body = Components.Schemas.ExportIn(episodes: episodes, format: format, title: title,
                                               drafts: .init(additionalProperties: Dictionary(uniqueKeysWithValues: drafts.map { (String($0.key), $0.value) })))
        switch try await server.call({ try await $0.exportText(path: .init(name: project), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
