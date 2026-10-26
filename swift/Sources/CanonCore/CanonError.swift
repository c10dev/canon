import Foundation

/// 화면에 보일 오류. 문구는 웹 화면(`app.js` 의 `fmtErr`, `api`)과 같다.
public enum CanonError: Error, Equatable, LocalizedError, Sendable {
    /// 서버가 꺼졌거나 네트워크가 끊겼다.
    case offline
    /// 서버가 답했지만 실패했다. `code` 는 서버가 붙인 오류 이름(있을 때만).
    case server(status: Int, message: String, code: String?)
    /// 서버가 답한 내용을 앱이 읽지 못했다. 대개 서버와 앱의 판이 다르다 (openapi.json 을 다시 만들 때).
    case badResponse(String)

    public var errorDescription: String? {
        switch self {
        case .offline:
            return "서버에 연결하지 못했어요. 서버가 켜져 있는지, 네트워크가 연결됐는지 확인하세요"
        case let .server(_, message, _):
            return message
        case let .badResponse(detail):
            return "서버 응답을 읽지 못했어요. 서버와 앱이 같은 판인지 확인하세요 (\(detail))"
        }
    }

    /// HTTP 상태. 연결하지 못했으면 0.
    public var status: Int {
        if case let .server(status, _, _) = self { return status }
        return 0
    }

    /// 다른 탭이나 기기가 먼저 저장했다 (작품 저장의 409).
    public var isConflict: Bool { status == 409 }

    /// 아무 오류나 화면 문구로.
    public static func message(_ error: any Error) -> String {
        (error as? CanonError)?.errorDescription ?? String(describing: error)
    }

    /// 실패 응답 본문(FastAPI 의 `{"detail": ...}`)을 읽는다.
    public static func from(status: Int, body: Data) -> CanonError {
        let json = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any]
        let code = json?["code"] as? String
        if let items = json?["detail"] as? [[String: Any]] {
            let lines = items.map { item -> String in
                let loc = (item["loc"] as? [Any] ?? []).dropFirst().map { "\($0)" }.joined(separator: ".")
                let msg = item["msg"] as? String ?? ""
                return "입력 형식이 맞지 않아요\(loc.isEmpty ? "" : " (칸: \(loc))"): \(msg)"
            }
            return .server(status: status, message: lines.joined(separator: "\n"), code: code)
        }
        if let text = json?["detail"] as? String, !text.isEmpty {
            return .server(status: status, message: text, code: code)
        }
        return .server(status: status, message: "요청 실패 (\(status))", code: code)
    }
}
