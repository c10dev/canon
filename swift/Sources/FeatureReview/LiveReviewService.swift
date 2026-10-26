import CanonAPI
import CanonCore
import Foundation

/// 서버의 상태 승인 엔드포인트(`web.py` 의 `apply_state` · `apply_restate` · `keep_state` · `revert` · `preview` · `set_view`).
/// 고치는 엔드포인트는 작품 전체를 돌려주지만, 화면은 연 작품(`ProjectDocument`)을 다시 받는다.
public struct LiveReviewService: ReviewService {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    /// 앱이 보낸 칸이 서버 모델과 맞지 않는다 (422). 대개 서버와 앱의 판이 다르다.
    static let invalid = CanonError.server(status: 422, message: "입력 형식이 맞지 않아요", code: nil)

    public func apply(_ project: String, ep: Int, delta: StateDelta) async throws {
        switch try await server.call({ try await $0.applyState(path: .init(name: project, n: ep), body: .json(delta)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func restate(_ project: String, ep: Int, delta: StateDelta) async throws {
        switch try await server.call({ try await $0.applyRestate(path: .init(name: project, n: ep), body: .json(delta)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func keepState(_ project: String, ep: Int) async throws {
        switch try await server.call({ try await $0.keepState(path: .init(name: project, n: ep)) }) {
        case .ok: return
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

    public func preview(_ project: String, ep: Int, delta: StateDelta) async throws -> RelationPreview {
        switch try await server.call({ try await $0.preview(path: .init(name: project, n: ep), body: .json(delta)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func setShowNumbers(_ project: String, _ show: Bool) async throws {
        switch try await server.call({ try await $0.setView(path: .init(name: project), body: .json(.init(showNumbers: show))) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
