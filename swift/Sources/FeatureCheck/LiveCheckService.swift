import CanonAPI
import CanonCore

/// 실제 서버에 붙는 검수 호출 (`web.py` 의 `set_finding` · `episode_style`). 검수 작업 자체는 `JobCenter` 가 시작한다.
public struct LiveCheckService: CheckService {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    public func setFinding(_ project: String, ep: Int, id: String, status: CheckText.Status, note: String?) async throws {
        let body = Components.Schemas.FindingIn(status: .init(rawValue: status.rawValue)!, note: note)
        switch try await server.call({ try await $0.setFinding(path: .init(name: project, n: ep, fid: id), body: .json(body)) }) {
        case .ok: return
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func style(_ project: String, ep: Int) async throws -> StyleDrift {
        switch try await server.call({ try await $0.episodeStyle(path: .init(name: project, n: ep)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
