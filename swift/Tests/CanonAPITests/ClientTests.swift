@testable import CanonAPI
import CanonCore
import Foundation
import HTTPTypes
import OpenAPIRuntime
import Testing

/// 네트워크 대신 요청을 받아 적고 정해 둔 답을 돌려준다.
final class RecordingTransport: ClientTransport, @unchecked Sendable {
    var requests: [HTTPRequest] = []
    let status: HTTPResponse.Status
    let body: String

    init(status: HTTPResponse.Status = .ok, body: String) {
        self.status = status
        self.body = body
    }

    func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String) async throws -> (HTTPResponse, HTTPBody?) {
        requests.append(request)
        var response = HTTPResponse(status: status)
        response.headerFields[.contentType] = "application/json"
        return (response, HTTPBody(self.body))
    }
}

@Suite struct ClientTests {
    let card = #"[{"name":"등대","title":"등대지기","genre":"미스터리","form":"short","episodes":12,"finalized":3,"planned":12,"open_ep":4,"open_status":"confirmed","updated_at":"2026-10-26T05:04:03.123456+00:00"}]"#

    @Test func listsProjectsWithClientHeader() async throws {
        let transport = RecordingTransport(body: card)
        let server = CanonServer(config: .local, clientID: "abc", transport: transport)
        guard case let .ok(ok) = try await server.call({ try await $0.listProjects() }) else {
            Issue.record("200 이 아니에요")
            return
        }
        let cards = try ok.body.json
        #expect(cards.first?.openEp == 4)
        #expect(cards.first?.updatedAt.hasPrefix("2026-10-26") == true)
        #expect(transport.requests.first?.path == "/api/projects")
        #expect(transport.requests.first?.headerFields[HTTPField.Name(ClientIdentity.header)!] == "abc")
    }

    @Test func encodesKoreanProjectNameInPath() async throws {
        let transport = RecordingTransport(body: "{}")
        let server = CanonServer(config: .local, transport: transport)
        _ = try? await server.call({ try await $0.relations(path: .init(name: "등대 1")) })
        #expect(transport.requests.first?.path == APIPath.project("등대 1", "relations"))
    }

    @Test func turnsUndocumentedStatusIntoError() async throws {
        let transport = RecordingTransport(status: .notFound, body: #"{"detail":"프로젝트가 없어요: x"}"#)
        let server = CanonServer(config: .local, transport: transport)
        let out = try await server.call({ try await $0.relations(path: .init(name: "x")) })
        guard case let .undocumented(status, payload) = out else {
            Issue.record("404 는 문서에 없는 상태예요")
            return
        }
        let error = await CanonServer.failure(status, payload)
        #expect(error == .server(status: 404, message: "프로젝트가 없어요: x", code: nil))
    }
}

@Suite struct NullableFieldTests {
    // 서버의 `int | None` 칸이 생성 타입에 남아야 작품을 저장할 때 지워지지 않는다 (scripts/make_openapi.py 의 drop_null)
    @Test func keepsNullableFieldsThroughSave() throws {
        let json = #"[{"id":"fs-1","description":"열쇠","planted_ep":2,"payoff_ep":9,"due_ep":null}]"#
        let items = try JSONDecoder().decode([Components.Schemas.Foreshadow].self, from: Data(json.utf8))
        #expect(items[0].payoffEp == 9)
        #expect(items[0].dueEp == nil)
        let again = try JSONSerialization.jsonObject(with: JSONEncoder().encode(items)) as? [[String: Any]]
        #expect(again?[0]["payoff_ep"] as? Int == 9)
    }
}
