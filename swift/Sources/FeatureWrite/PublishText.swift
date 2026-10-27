import CanonCore

/// 복사 · 내보내기 문구와 범위. 웹 `publish.js` 와 같은 규칙이라 함께 고친다.
public enum PublishText {
    public static let defaultFormat = "blank"

    /// 여러 화 범위: 고치지 않았으면 쓴 첫 화 ~ 마지막 화 (웹 `copyRangeOf`).
    public static func range(_ nums: [Int], picked: (from: Int?, to: Int?)) -> (from: Int, to: Int) {
        (picked.from ?? nums.first ?? 1, picked.to ?? nums.last ?? 1)
    }

    /// 범위 칸에 적은 값을 1~마지막 화로 묶는다 (웹 `change` 처리).
    public static func clamp(_ v: Int, last: Int) -> Int {
        min(last, max(1, v))
    }

    /// 시작 화가 끝 화보다 크면 안내.
    public static func rangeError(from: Int, to: Int) -> String? {
        from > to ? "시작 화가 끝 화보다 커요. \(to)~\(from)화로 바꿔 보세요" : nil
    }

    /// 범위 안 본문이 있는 화.
    public static func pick(_ nums: [Int], from: Int, to: Int) -> [Int] {
        nums.filter { $0 >= from && $0 <= to }
    }

    public static let emptyRange = "그 범위에 본문이 있는 화가 없어요"
    public static let rangeHelp = "여러 화는 화마다 제목 줄을 넣어 잇고, 본문이 없는 화는 건너뛰어요."

    /// 제목 줄 넣기 칸 글자.
    public static func titleToggle(_ n: Int) -> String {
        "맨 위에 '\(n)화. 제목' 줄 넣기"
    }

    /// 복사한 뒤 알림 'a~b화 복사했어요 (1,234자, 56줄)' (웹 `copyEpisodes`).
    public static func copied(_ out: ExportOut) -> String {
        let eps = out.episodes
        let span = eps.count > 1 ? "\(eps.first!)~\(eps.last!)화 " : ""
        let lines = out.text.split(separator: "\n", omittingEmptySubsequences: false).count
        return "\(span)복사했어요 (\(WriteText.number(out.text.utf16.count))자, \(WriteText.number(lines))줄)"
    }

    /// 내려받을 파일 이름 '<작품>-3화.txt', '<작품>-1-5화.txt' (웹 `downloadTxt`).
    public static func filename(_ project: String, from: Int, to: Int) -> String {
        "\(project)-\(from == to ? "\(from)화" : "\(from)-\(to)화").txt"
    }
}
