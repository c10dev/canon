import Foundation

/// Canon 서버 주소. 서버는 `python -m canon serve` 이고, 다른 기기에서는 Tailscale 로 연다.
public struct ServerConfig: Sendable, Equatable, Codable {
    public var baseURL: URL

    public init(baseURL: URL) {
        self.baseURL = baseURL
    }

    /// 같은 기기에서 띄운 서버 (`serve` 기본 포트).
    public static let local = ServerConfig(baseURL: URL(string: "http://127.0.0.1:8000")!)

    /// 사용자가 적은 주소를 읽는다. 앞뒤 공백과 끝의 `/` 를 지우고, 주소 형식이 없으면 `http://` 를 붙인다.
    /// 호스트가 없거나 http(s) 가 아니면 nil.
    public static func parse(_ text: String) -> ServerConfig? {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasSuffix("/") { s.removeLast() }
        if s.isEmpty { return nil }
        if !s.contains("://") { s = "http://" + s }
        guard let url = URL(string: s), let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = url.host, !host.isEmpty else { return nil }
        return ServerConfig(baseURL: url)
    }
}

/// 서버가 저장한 화면을 알아보는 헤더. 다른 화면이 먼저 저장했으면 서버가 오래된 화면의 저장을 409 로 막는다.
public enum ClientIdentity {
    public static let header = "X-Canon-Client"

    /// 웹 화면(`app.js` 의 CLIENT)과 같은 모양: 무작위 8자 + 시각, 둘 다 36진수.
    public static func make(now: Date = Date()) -> String {
        let alphabet = Array("0123456789abcdefghijklmnopqrstuvwxyz")
        let random = String((0..<8).map { _ in alphabet.randomElement()! })
        let millis = Int64(now.timeIntervalSince1970 * 1000)
        return random + String(millis, radix: 36)
    }
}
