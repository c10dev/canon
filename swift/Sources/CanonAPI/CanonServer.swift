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

    /// openapi.json 에 타입이 없는 요청을 직접 보낸다 (작업 시작처럼 dict 를 돌려주는 곳).
    public func send<T: Decodable & Sendable>(_ method: String, _ path: String, body: (any Encodable & Sendable)? = nil, as type: T.Type) async throws -> T {
        var request = URLRequest(url: URL(string: path, relativeTo: config.baseURL)!)
        request.httpMethod = method
        request.setValue(clientID, forHTTPHeaderField: ClientIdentity.header)
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
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

    /// 작업을 시작한다. 같은 작업이 이미 돌면 서버가 그 작업을 돌려준다 (`already`).
    public func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        let out = try await send("POST", APIPath.project(project, "jobs"), body: request, as: StartedJob.self)
        return (out.job, out.already ?? false)
    }

    public func stopJob(_ id: String) async throws -> Job {
        try await send("POST", "/api/jobs/\(id)/stop", as: Job.self)
    }

    /// 검토를 기다리는 결과와 실패한 작업.
    public func pending(_ project: String) async throws -> PendingList {
        try await get(APIPath.project(project, "pending"), as: PendingList.self)
    }

    /// 반영하거나 버린 결과(`failure` 면 닫은 실패)를 서버에서 지운다.
    public func dropPending(_ project: String, key: String, failure: Bool = false) async throws {
        let path = APIPath.project(project, "pending/" + APIPath.segment(key)) + (failure ? "?failure=true" : "")
        _ = try await send("DELETE", path, as: JSONValue.self)
    }
}

/// 작업 시작 응답: 작업 칸에 `already` 가 더해진다.
struct StartedJob: Decodable, Sendable {
    let job: Job
    let already: Bool?

    init(from decoder: any Decoder) throws {
        job = try Job(from: decoder)
        already = try decoder.container(keyedBy: Key.self).decodeIfPresent(Bool.self, forKey: .already)
    }

    enum Key: String, CodingKey { case already }
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
