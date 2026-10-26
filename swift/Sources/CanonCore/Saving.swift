import Foundation

/// 작품 저장에서 서버가 화면 값 대신 디스크 것으로 둔 칸 (`X-Canon-Kept` 헤더, `web._save` 의 `kept`).
/// 작업 · 자동 집필 · 다른 곳의 반영이 맡은 화를 지키려고 그렇게 한다.
public struct KeptField: Decodable, Equatable, Sendable {
    /// "plot" · "relationships" · "character"
    public let field: String
    public let ep: Int?
    public let name: String?

    public init(field: String, ep: Int? = nil, name: String? = nil) {
        self.field = field
        self.ep = ep
        self.name = name
    }

    /// 헤더 값(퍼센트 인코딩한 JSON 목록)을 읽는다. 없거나 읽지 못하면 빈 목록.
    public static func parse(header: String?) -> [KeptField] {
        guard let header, let text = header.removingPercentEncoding else { return [] }
        return (try? JSONDecoder().decode([KeptField].self, from: Data(text.utf8))) ?? []
    }
}

/// 저장 뒤 알림 문구. 웹 `save()` 의 토스트와 같다.
public enum SaveText {
    public static let saved = "저장했어요"

    /// 화면이 고친 칸인데 서버 것으로 둔 칸. `edited` 는 그 칸을 이 화면이 고쳤는지.
    public static func dropped(_ kept: [KeptField], edited: (KeptField) -> Bool) -> String? {
        let names = kept.filter { $0.field != "character" && edited($0) }
            .map { $0.field == "relationships" ? "관계" : "\($0.ep ?? 0)화 플롯" }
        guard !names.isEmpty else { return nil }
        return "작업이나 반영된 진행과 겹쳐 이 부분은 저장하지 않고 서버에 있는 것으로 두었어요: \(names.joined(separator: ", "))"
    }

    /// 이 화면이 모르는 사이 반영으로 더해진 인물.
    public static func keptCharacters(_ kept: [KeptField]) -> String? {
        let names = kept.filter { $0.field == "character" }.compactMap(\.name)
        guard !names.isEmpty else { return nil }
        return "이 화면이 모르는 사이 반영으로 더해진 인물(\(names.joined(separator: ", ")))은 지우지 않고 남겼어요"
    }

    /// 다른 화면이 먼저 저장했다 (409). 서버 문구가 있으면 그것을 쓴다.
    public static let conflictChoices = "다시 불러와 그 변경을 보거나, 내 변경으로 덮어쓰세요"
}
