import CanonAPI
import CanonCore
import Foundation

/// 서버의 복선 센터 엔드포인트(`web.py` 의 `foreshadow_*`). 고치는 엔드포인트는 작품 전체를 돌려주지만
/// 이 화면은 쓰지 않고 계산값을 다시 받는다.
public struct LiveForeshadowService: ForeshadowService {
    let server: CanonServer
    let project: String

    public init(server: CanonServer, project: String) {
        self.server = server
        self.project = project
    }

    /// 앱이 보낸 칸이 서버 모델과 맞지 않는다 (422). 대개 서버와 앱의 판이 다르다.
    static let invalid = CanonError.server(status: 422, message: "입력 형식이 맞지 않아요", code: nil)

    public func center() async throws -> ForeshadowCenter {
        switch try await server.call({ try await $0.foreshadowCenter(path: .init(name: project)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func perform(_ change: ForeshadowChange) async throws {
        let name = project
        switch change {
        case let .add(description, episode, scope, due):
            let body = Components.Schemas.ForeshadowIn(
                description: description.trimmingCharacters(in: .whitespacesAndNewlines),
                episode: episode, scope: scope.rawValue, dueEp: due)
            switch try await server.call({ try await $0.foreshadowAdd(path: .init(name: name), body: .json(body)) }) {
            case .ok: return
            case .unprocessableContent: throw Self.invalid
            case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
            }
        case let .edit(id, description, scope, due):
            let body = Components.Schemas.ForeshadowEdit(
                description: description.trimmingCharacters(in: .whitespacesAndNewlines),
                scope: scope.rawValue, dueEp: due, clearDue: due == nil)
            switch try await server.call({ try await $0.foreshadowEdit(path: .init(name: name, fid: id), body: .json(body)) }) {
            case .ok: return
            case .unprocessableContent: throw Self.invalid
            case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
            }
        case let .resolve(id, episode):
            let body = Components.Schemas.EpisodeIn(episode: episode)
            switch try await server.call({ try await $0.foreshadowResolve(path: .init(name: name, fid: id), body: .json(body)) }) {
            case .ok: return
            case .unprocessableContent: throw Self.invalid
            case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
            }
        case let .reopen(id):
            switch try await server.call({ try await $0.foreshadowReopen(path: .init(name: name, fid: id)) }) {
            case .ok: return
            case .unprocessableContent: throw Self.invalid
            case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
            }
        case let .remove(id):
            switch try await server.call({ try await $0.foreshadowRemove(path: .init(name: name, fid: id)) }) {
            case .ok: return
            case .unprocessableContent: throw Self.invalid
            case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
            }
        case let .dropClue(id, episode, quote):
            let body = Components.Schemas.ClueKey(foreshadow: id, episode: episode, quote: quote)
            switch try await server.call({ try await $0.foreshadowClueRemove(path: .init(name: name), body: .json(body)) }) {
            case .ok: return
            case .unprocessableContent: throw Self.invalid
            case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
            }
        case .prune:
            switch try await server.call({ try await $0.foreshadowPrune(path: .init(name: name)) }) {
            case .ok: return
            case .unprocessableContent: throw Self.invalid
            case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
            }
        }
    }
}
