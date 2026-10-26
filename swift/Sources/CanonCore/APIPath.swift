import Foundation

/// 서버 경로 만들기. 작품 이름(폴더 이름)은 한글과 띄어쓰기가 흔해 경로 한 칸으로 인코딩한다
/// (웹 화면의 `encodeURIComponent`, 서버의 `unquote`).
public enum APIPath {
    private static let segmentAllowed: CharacterSet = {
        var set = CharacterSet.alphanumerics.intersection(CharacterSet(charactersIn: Unicode.Scalar(0)..<Unicode.Scalar(128)))
        set.insert(charactersIn: "-_.!~*'()")
        return set
    }()

    /// 경로 한 칸. `/` 도 인코딩한다.
    public static func segment(_ text: String) -> String {
        text.addingPercentEncoding(withAllowedCharacters: segmentAllowed) ?? text
    }

    /// `/api/projects/<이름>` 과 그 아래 경로.
    public static func project(_ name: String, _ rest: String = "") -> String {
        "/api/projects/" + segment(name) + (rest.isEmpty ? "" : "/" + rest)
    }
}
