import CanonAPI
import CanonCore
import Foundation

/// 서버의 자동 집필 엔드포인트 (`web.py` 의 `auto_*`) 와 반영 취소(`revert`).
public struct LiveAutoService: AutoService {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    /// 앱이 보낸 칸이 서버 모델과 맞지 않는다 (422). 대개 서버와 앱의 판이 다르다.
    static let invalid = CanonError.server(status: 422, message: "입력 형식이 맞지 않아요", code: nil)

    public func status(_ project: String) async throws -> AutoState {
        switch try await server.call({ try await $0.autoGet(path: .init(name: project)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func estimate(_ project: String, target: Int, batch: Bool, policy: Policy) async throws -> AutoEstimate {
        let body = Components.Schemas.AutoIn(target: target, batch: batch, policy: policy)
        switch try await server.call({ try await $0.autoEstimate(path: .init(name: project), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func start(_ project: String, target: Int, batch: Bool, policy: Policy) async throws -> AutoState {
        let body = Components.Schemas.AutoIn(target: target, batch: batch, policy: policy)
        switch try await server.call({ try await $0.autoStart(path: .init(name: project), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func request(_ project: String, _ what: String) async throws -> AutoState {
        switch try await server.call({ try await $0.autoRequest(path: .init(name: project, what: what)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func resume(_ project: String, approve: Bool, rewrite: Bool) async throws -> AutoState {
        let body = Components.Schemas.AutoResume(approve: approve, rewrite: rewrite)
        switch try await server.call({ try await $0.autoResume(path: .init(name: project), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func setBatch(_ project: String, _ on: Bool) async throws -> AutoState {
        switch try await server.call({ try await $0.autoBatch(path: .init(name: project), body: .json(.init(batch: on))) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func setPolicy(_ project: String, _ policy: Policy) async throws -> AutoState {
        switch try await server.call({ try await $0.autoPolicy(path: .init(name: project), body: .json(policy)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func sendToReview(_ project: String) async throws -> AutoState {
        switch try await server.call({ try await $0.autoReview(path: .init(name: project)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func revert(_ project: String, after: Int) async throws {
        switch try await server.call({ try await $0.revert(path: .init(name: project, n: after)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
