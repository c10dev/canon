import Foundation

/// 화면 문구 규칙. 웹 화면(`app.js`)과 같은 규칙이라 함께 고친다.
public enum KoreanText {
    /// 숫자를 한국어로 읽은 받침 여부: 영 일 이 삼 사 오 육 칠 팔 구 (`logline.DIGIT_FINAL`)
    private static let digitFinal: [Character: Bool] = [
        "0": true, "1": true, "2": false, "3": true, "4": false,
        "5": false, "6": true, "7": true, "8": true, "9": false,
    ]

    /// 받침이 있으면 `withFinal`, 없으면 `withoutFinal`. 한글이나 숫자로 끝나지 않으면 '이(가)' 처럼 둘 다 쓴다.
    public static func josa(_ word: String, _ withFinal: String, _ withoutFinal: String) -> String {
        let w = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let last = w.last else { return "" }
        if let final = digitFinal[last] { return final ? withFinal : withoutFinal }
        guard let scalar = last.unicodeScalars.first, last.unicodeScalars.count == 1,
              (0xAC00...0xD7A3).contains(scalar.value) else { return "\(withFinal)(\(withoutFinal))" }
        return (scalar.value - 0xAC00) % 28 != 0 ? withFinal : withoutFinal
    }

    /// 화 범위 'a~b화' (한 화면 'a화').
    public static func episodeRange(_ a: Int, _ b: Int) -> String {
        a == b ? "\(a)화" : "\(a)~\(b)화"
    }

    /// '2026.10.26' (기기 시간대). 읽지 못하면 받은 글을 그대로.
    public static func date(_ iso: String, timeZone: TimeZone = .current) -> String {
        guard let d = parseISO(iso) else { return iso }
        let c = calendar(timeZone).dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d.%02d.%02d", c.year!, c.month!, c.day!)
    }

    /// '2026.10.26 14:05' (기기 시간대). 읽지 못하면 받은 글을 그대로.
    public static func dateTime(_ iso: String, timeZone: TimeZone = .current) -> String {
        guard let d = parseISO(iso) else { return iso }
        let c = calendar(timeZone).dateComponents([.hour, .minute], from: d)
        return date(iso, timeZone: timeZone) + String(format: " %02d:%02d", c.hour!, c.minute!)
    }

    /// Python `isoformat()` 글을 읽는다. 소수 초(6자리)는 버리고, 시간대가 없으면 기기 시간대로 본다.
    static func parseISO(_ text: String) -> Date? {
        var s = text.trimmingCharacters(in: .whitespaces)
        if let dot = s.firstIndex(of: ".") {
            let end = s[dot...].dropFirst().firstIndex(where: { !$0.isNumber }) ?? s.endIndex
            s.removeSubrange(dot..<end)
        }
        let withZone = ISO8601DateFormatter()
        if let d = withZone.date(from: s) { return d }
        let local = DateFormatter()
        local.locale = Locale(identifier: "en_US_POSIX")
        local.timeZone = .current
        for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd"] {
            local.dateFormat = format
            if let d = local.date(from: s) { return d }
        }
        return nil
    }

    private static func calendar(_ tz: TimeZone) -> Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = tz
        return c
    }
}

/// 화 진행 상태 이름. 웹 화면의 `STATUS` 와 같다.
public enum EpisodeStatus: String, CaseIterable, Sendable {
    case draft, confirmed, written, finalized

    public var label: String {
        switch self {
        case .draft: "플롯 초안"
        case .confirmed: "플롯 확정"
        case .written: "본문 작성됨"
        case .finalized: "반영 완료"
        }
    }

    /// 작품 카드의 다음 할 일에 붙는 말 (`app.js` 의 `projectNext`).
    public var waiting: String {
        switch self {
        case .draft: "플롯 확정 대기"
        case .confirmed: "쓰기 대기"
        case .written: "상태 승인 대기"
        case .finalized: ""
        }
    }
}
