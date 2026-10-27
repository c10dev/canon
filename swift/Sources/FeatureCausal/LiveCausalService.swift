import CanonAPI
import CanonCore
import CanonStore

/// 실제 서버에 붙는 인과율 호출 (web.py '3-2. 인과율'). 고치는 엔드포인트는 저장한 작품을 돌려준다.
public struct LiveCausalService: CausalService {
    let server: CanonServer
    let loader: ProjectLoader

    public init(server: CanonServer) {
        self.server = server
        loader = ProjectLoader(server: server)
    }

    public func links(_ project: String) async throws -> [String: [ElementLink]] {
        switch try await server.call({ try await $0.elementLinks(path: .init(name: project)) }) {
        case let .ok(ok): return try ok.body.json.additionalProperties
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func apply(_ project: String, element: String, _ body: Components.Schemas.ImpactApply) async throws -> Project {
        switch try await server.call({ try await $0.impactApply(path: .init(name: project, eid: element), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func dismiss(_ project: String, element: String) async throws -> Project {
        switch try await server.call({ try await $0.impactDismiss(path: .init(name: project, eid: element)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func reopen(_ project: String, element: String) async throws -> Project {
        switch try await server.call({ try await $0.impactReopen(path: .init(name: project, eid: element)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func load(_ project: String) async throws -> Project {
        try await loader.load(project)
    }
}
