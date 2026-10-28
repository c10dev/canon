import CanonAPI
import CanonCore
import CanonStore
import Foundation

public typealias ConsistencyIssue = Components.Schemas.ConsistencyIssue
public typealias TextVersion = Components.Schemas.TextVersion
public typealias RewriteRequest = Components.Schemas.RewriteRequest
public typealias RewriteInfo = Components.Schemas.RewriteInfo
public typealias PublishFormat = Components.Schemas.PublishFormat
public typealias ExportOut = Components.Schemas.ExportOut
typealias Act = Components.Schemas.Act

/// 집필 화면의 표시 규칙. 웹 `app.js` 의 `viewWrite` · `blockedBefore` · `orderNote` · `textUnsaved`,
/// `passage.js` 의 `editableEp` · `clip` · `editTime` 와 같은 문구라 함께 고친다.
public enum WriteText {
    static func status(_ e: Episode) -> EpisodeStatus {
        EpisodeStatus(rawValue: e.status?.rawValue ?? "draft") ?? .draft
    }

    /// 본문을 고칠 수 있는 화: 확정 · 작성 · 반영 완료 (웹 `editableEp`). 플롯 초안은 못 고친다.
    public static func editable(_ e: Episode) -> Bool {
        status(e) != .draft
    }

    /// n화보다 앞인데 상태 반영이 끝나지 않은 화 (웹 `blockedBefore`, 서버 `pipeline.require_previous`).
    public static func blockedBefore(_ n: Int, in eps: [Episode]) -> [Int] {
        eps.filter { $0.plot.number < n && status($0) != .finalized }.map(\.plot.number)
    }

    /// 앞 화가 반영되지 않아 쓰지 못한다는 안내와, 그 화로 가는 단추 (웹 `orderNote`).
    public struct OrderNote: Equatable, Sendable {
        public let text: String
        public let ep: Int
        public let button: String
        public let screen: Screen
    }

    public static func orderNote(_ blocked: [Int], in eps: [Episode]) -> OrderNote? {
        guard let first = blocked.first, let e = eps.first(where: { $0.plot.number == first }) else { return nil }
        let written = status(e) == .written
        return OrderNote(text: "이전 화(\(blocked.map(String.init).joined(separator: ", "))화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙이에요.",
                         ep: first, button: "\(first)화 \(written ? "상태 승인으로" : "집필로")", screen: written ? .review : .write)
    }

    /// 본문 초안이 저장한 본문과 다르다. 서버는 앞뒤 공백을 지워 저장한다 (웹 `textUnsaved`).
    public static func unsaved(draft: String?, saved: String) -> Bool {
        guard let draft else { return false }
        return draft.trimmingCharacters(in: .whitespacesAndNewlines) != saved.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// 길면 자르고 '…' (웹 `clip`).
    public static func clip(_ t: String, _ n: Int) -> String {
        t.count > n ? String(t.prefix(n)) + "…" : t
    }

    static let korean = Locale(identifier: "ko_KR")

    /// '1,234'
    public static func number(_ n: Int) -> String {
        n.formatted(.number.locale(korean))
    }

    /// 본문 칸 위 글자 수 '1,234 / 5,000자'.  JS `length` 처럼 UTF-16 단위로 센다.
    public static func count(_ text: String, goal: Int) -> String {
        "\(number(text.utf16.count)) / \(number(goal))자"
    }

    /// 머리 위 작은 글자 '기 구간 · 3 / 12화'.
    public static func eyebrow(act: String?, n: Int, target: Int) -> String {
        "\(act.map { "\($0) 구간 · " } ?? "")\(n) / \(target)화"
    }

    /// 본문 칸 위 안내 (웹 본문 칸 머리). 부분 수정 도구는 앱에 아직 없어 그 말은 뺀다.
    public static func bodyHint(_ e: Episode) -> String {
        if status(e) == .draft { return "플롯을 확정하면 본문을 쓸 수 있어요" }
        return "본문을 직접 고친 뒤 저장할 수 있어요"
    }

    /// 화에 속한 기승전결 구간 (웹 `actOf`, 장편은 아크들의 구간).
    static func act(_ n: Int, in p: Project) -> Act? {
        let beats = p.meta?.form == .serial
            ? (p.storyArcs ?? []).sorted { $0.startEp < $1.startEp }.flatMap { $0.acts ?? [] }
            : (p.arc ?? [])
        return beats.first { $0.startEp <= n && n <= $0.endEp }
    }

    /// 인물 id → 이름. 후보 인물도 찾고, 없으면 id (웹 `charName`).
    static func name(_ id: String, in p: Project) -> String {
        if let c = p.characters?.first(where: { $0.id == id }) { return c.name.isEmpty ? id : c.name }
        if let c = p.castCandidates?.first(where: { $0.id == id }) { return c.name.isEmpty ? id : c.name }
        return id
    }

    /// 수정 · 판 시각: 오늘이면 시각만, 아니면 날짜 (웹 `editTime`).
    public static func when(_ iso: String?, now: Date = Date(), timeZone: TimeZone = .current) -> String {
        guard let iso, !iso.isEmpty else { return "" }
        let full = KoreanText.dateTime(iso, timeZone: timeZone)
        var c = Calendar(identifier: .gregorian)
        c.timeZone = timeZone
        let d = c.dateComponents([.year, .month, .day], from: now)
        let today = String(format: "%04d.%02d.%02d", d.year!, d.month!, d.day!)
        return full.hasPrefix(today) && full.count > 11 ? String(full.dropFirst(11)) : KoreanText.date(iso, timeZone: timeZone)
    }
}
