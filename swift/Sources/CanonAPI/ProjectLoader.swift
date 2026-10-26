import CanonCore
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// 작품 전체(`GET /api/projects/{name}`)를 판(ETag)과 함께 받는다. 같은 판이면 서버가 304 로 본문 없이 답하고
/// 가진 것을 다시 쓴다 (장편은 수 MB). 이 응답은 openapi.json 에 타입이 없어(JSONResponse) 직접 읽는다.
public actor ProjectLoader {
    private let server: CanonServer
    private var cache: [String: (tag: String, data: Data)] = [:]

    public init(server: CanonServer) {
        self.server = server
    }

    public func load(_ name: String) async throws -> Components.Schemas.Project {
        let data = try await fetch(name)
        do {
            return try JSONDecoder().decode(Components.Schemas.Project.self, from: data)
        } catch {
            throw CanonError.badResponse(String(describing: error))
        }
    }

    /// 마지막으로 받은 판. 저장할 때 다른 화면이 먼저 저장했는지 서버가 `edit_rev` 로 본다.
    public func etag(_ name: String) -> String? { cache[name]?.tag }

    func fetch(_ name: String) async throws -> Data {
        let url = URL(string: APIPath.project(name), relativeTo: server.config.baseURL)!
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue(server.clientID, forHTTPHeaderField: ClientIdentity.header)
        if let tag = cache[name]?.tag { request.setValue(tag, forHTTPHeaderField: "If-None-Match") }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await server.session.data(for: request)
        } catch {
            throw CanonError.offline
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 304, let kept = cache[name] { return kept.data }
        guard (200..<300).contains(status) else { throw CanonError.from(status: status, body: data) }
        if let tag = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "ETag") {
            cache[name] = (tag, data)
        }
        return data
    }
}
