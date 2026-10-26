import CanonCore
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import HTTPTypes
import OpenAPIRuntime
import OpenAPIURLSession

/// 서버 하나에 붙는 연결. 생성된 `Client`(openapi.json 의 연산 전부)에 화면 id 헤더를 붙인다.
public struct CanonServer: Sendable {
    public let config: ServerConfig
    /// 이 앱 실행의 화면 id. 저장 충돌(409)을 가리는 데 쓴다.
    public let clientID: String
    public let client: Client
    let session: URLSession

    public init(config: ServerConfig, clientID: String = ClientIdentity.make(), session: URLSession = .shared,
                transport: (any ClientTransport)? = nil) {
        self.config = config
        self.clientID = clientID
        self.session = session
        self.client = Client(
            serverURL: config.baseURL,
            transport: transport ?? URLSessionTransport(configuration: .init(session: session)),
            middlewares: [ClientHeaderMiddleware(clientID: clientID)]
        )
    }

    /// 생성된 연산을 부르고, 연결 실패와 응답 읽기 실패를 `CanonError` 로 바꾼다.
    public func call<T: Sendable>(_ operation: (Client) async throws -> T) async throws -> T {
        do {
            return try await operation(client)
        } catch let error as ClientError {
            if error.response == nil, error.underlyingError is URLError { throw CanonError.offline }
            throw CanonError.badResponse(String(describing: error.underlyingError))
        }
    }

    /// 문서에 없는 상태(대개 4xx · 5xx)로 답했다. 본문의 `detail` 로 오류 문구를 만든다.
    public static func failure(_ status: Int, _ payload: UndocumentedPayload) async -> CanonError {
        var data = Data()
        if let body = payload.body, let collected = try? await Data(collecting: body, upTo: 1 << 20) {
            data = collected
        }
        return CanonError.from(status: status, body: data)
    }
}

extension CanonServer {
    /// openapi.json 에 타입이 없는 GET 응답을 직접 읽는다 (`/api/jobs` 처럼 dict 를 돌려주는 곳).
    public func get<T: Decodable & Sendable>(_ path: String, as type: T.Type) async throws -> T {
        var request = URLRequest(url: URL(string: path, relativeTo: config.baseURL)!)
        request.setValue(clientID, forHTTPHeaderField: ClientIdentity.header)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw CanonError.offline
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw CanonError.from(status: status, body: data) }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw CanonError.badResponse(String(describing: error))
        }
    }

    /// 진행 중이거나 최근에 끝난 작업 (`GET /api/jobs`).
    public func listJobs() async throws -> [Job] {
        try await get("/api/jobs", as: [Job].self)
    }
}

/// 요청마다 `X-Canon-Client` 헤더를 붙인다.
struct ClientHeaderMiddleware: ClientMiddleware {
    let clientID: String

    func intercept(
        _ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String,
        next: @Sendable (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?)
    ) async throws -> (HTTPResponse, HTTPBody?) {
        var request = request
        request.headerFields[HTTPField.Name(ClientIdentity.header)!] = clientID
        return try await next(request, body, baseURL)
    }
}
