import CanonAPI
import CanonCore
import CanonStore

/// 실제 서버에 붙는 작업지시서 호출 (web.py '작업지시서', '4. 본문'의 `put_text`, '5. 상태 변경안'의 `parse_state`).
public struct LiveBriefService: BriefService {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    public func brief(_ project: String, ep: Int, kind: BriefKind) async throws -> String {
        switch try await server.call({ try await $0.brief(path: .init(name: project, n: ep), query: .init(kind: kind.rawValue)) }) {
        case let .ok(ok): return try ok.body.json.text
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func saveText(_ project: String, ep: Int, text: String) async throws -> Project {
        switch try await server.call({ try await $0.putText(path: .init(name: project, n: ep), body: .json(.init(text: text))) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func parseState(_ project: String, ep: Int, raw: String) async throws -> StateDelta {
        switch try await server.call({ try await $0.parseState(path: .init(name: project, n: ep), body: .json(.init(raw: raw))) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
