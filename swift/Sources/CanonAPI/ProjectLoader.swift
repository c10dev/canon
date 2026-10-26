import CanonCore
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// 작품 저장 결과: 서버가 저장한 작품과, 화면 값 대신 서버 것으로 둔 칸.
public struct SaveResult: Sendable {
    public let project: Components.Schemas.Project
    public let kept: [KeptField]

    public init(project: Components.Schemas.Project, kept: [KeptField]) {
        self.project = project
        self.kept = kept
    }
}

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

    /// 작품 전체를 저장한다 (`PUT /api/projects/{name}`). 웹 `save()` 와 같다.
    /// `merged` 는 결과를 이미 받아 간 작업(`<작업 id>:<done>`), `force` 는 다른 화면이 먼저 저장했어도 덮는다.
    /// 다른 화면이 먼저 저장했으면 409(`CanonError.isConflict`)를 던진다. 응답의 `X-Canon-Kept` 를 함께 돌려준다.
    public func save(_ name: String, _ project: Components.Schemas.Project, merged: [String] = [], force: Bool = false) async throws -> SaveResult {
        var parts = URLComponents(string: APIPath.project(name))!
        parts.queryItems = [URLQueryItem(name: "merged", value: merged.joined(separator: ","))]
        if force { parts.queryItems!.append(URLQueryItem(name: "force", value: "true")) }
        var request = URLRequest(url: parts.url(relativeTo: server.config.baseURL)!)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(server.clientID, forHTTPHeaderField: ClientIdentity.header)
        request.httpBody = try JSONEncoder().encode(project)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await server.session.data(for: request)
        } catch {
            throw CanonError.offline
        }
        let http = response as? HTTPURLResponse
        let status = http?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw CanonError.from(status: status, body: data) }
        cache[name] = nil  // 판이 바뀌었다. 다음에 받을 때 새로 받는다
        do {
            let saved = try JSONDecoder().decode(Components.Schemas.Project.self, from: data)
            return SaveResult(project: saved, kept: KeptField.parse(header: http?.value(forHTTPHeaderField: "X-Canon-Kept")))
        } catch {
            throw CanonError.badResponse(String(describing: error))
        }
    }

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
