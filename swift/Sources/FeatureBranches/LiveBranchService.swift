import CanonAPI
import CanonCore
import Foundation

/// 서버의 갈래 엔드포인트. 갈래 계산(복사 · 되돌리기 · 비교)은 서버 `branches.py` 가 한다.
public struct LiveBranchService: BranchService {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    /// 앱이 보낸 칸이 서버 모델과 맞지 않는다 (422). 대개 서버와 앱의 판이 다르다.
    static let invalid = CanonError.server(status: 422, message: "입력 형식이 맞지 않아요", code: nil)

    public func family(_ project: String) async throws -> BranchFamily {
        switch try await server.call({ try await $0.branchFamily(path: .init(name: project)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func make(_ project: String, _ body: BranchIn) async throws -> BranchMember {
        switch try await server.call({ try await $0.makeBranch(path: .init(name: project), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func compare(_ project: String, with other: String, ep: Int?) async throws -> BranchDiff {
        switch try await server.call({ try await $0.compareBranches(path: .init(name: project, other: other), query: .init(ep: ep)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func promote(_ project: String) async throws -> BranchFamily {
        switch try await server.call({ try await $0.promoteBranch(path: .init(name: project)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func detach(_ project: String) async throws -> BranchFamily {
        switch try await server.call({ try await $0.detachBranch(path: .init(name: project)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
