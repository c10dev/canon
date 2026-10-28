import CanonAPI
import CanonCore
import CanonStore
import Foundation

public typealias Finding = Components.Schemas.Finding
public typealias CheckRound = Components.Schemas.CheckRound
public typealias StyleDrift = Components.Schemas.StyleDrift

/// 검수 화면 문구와 표시 규칙. 웹 `check.js` 의 `FINDING_STATUS` · `FINDING_FLAG` · `findingFlag` · `findingMarks` ·
/// `chkSelected` · `srcLabel` · `chkStrip` 와 같은 규칙이라 함께 고친다.
public enum CheckText {
    /// 지적 처리 상태 (서버 `schema.FINDING_STATUS`).
    public enum Status: String, CaseIterable, Sendable {
        case open, fixed, kept, wrong

        public var label: String {
            switch self {
            case .open: "열림"
            case .fixed: "고침"
            case .kept: "그대로 둠"
            case .wrong: "잘못 짚음"
            }
        }
    }

    /// 지적 목록 거르기 (웹 `S.chkFilter`).
    public enum Filter: String, CaseIterable, Sendable {
        case open, fixed, kept, wrong, all

        public var label: String { self == .all ? "모두" : Status(rawValue: rawValue)!.label }
    }

    /// 지적 옆 표시.
    public enum Flag: String, Sendable {
        case changed, miss, gone, again

        public var label: String {
            switch self {
            case .changed: "문장 바뀜"
            case .miss: "이번 회차에서 안 짚음"
            case .gone: "다시 검수에서 사라짐"
            case .again: "다시 나옴 · 결정 그대로"
            }
        }
    }

    public static func status(_ f: Finding) -> Status { Status(rawValue: f.status?.rawValue ?? "open") ?? .open }

    /// 지적 옆 표시. `findings.merge` 가 남긴 칸(first · last · closed_by)과 지금 본문으로 센다.
    public static func flag(_ e: Episode, _ f: Finding, text: String) -> Flag? {
        let last = e.rounds?.last?.no ?? (f.last ?? 1)
        let quote = f.currentQuote.trimmingCharacters(in: .whitespacesAndNewlines)
        switch status(f) {
        case .open:
            if !quote.isEmpty && !text.contains(quote) { return .changed }
            return (f.last ?? 1) < last ? .miss : nil
        case .fixed:
            return f.closedBy == .recheck ? .gone : nil
        case .kept, .wrong:
            return (f.last ?? 1) == last && (f.first ?? 1) < last ? .again : nil
        }
    }

    /// 지금 고른 지적: 고른 적이 있으면 그것, 없으면 첫 열린 지적, 그도 없으면 첫 지적.
    public static func selected(_ e: Episode, chosen: String?) -> String? {
        let list = e.findings ?? []
        if let chosen, list.contains(where: { $0.id == chosen }) { return chosen }
        return (list.first { status($0) == .open } ?? list.first)?.id
    }

    /// 본문 밑줄: 열린 지적과 고른 지적의 문장. 문장마다 처음 나온 곳 하나.
    public struct Mark: Equatable, Sendable {
        public let id: String
        public let range: Range<String.Index>
        public let selected: Bool
    }

    public static func marks(_ e: Episode, text: String, selected: String?) -> [Mark] {
        (e.findings ?? []).compactMap { f in
            let q = f.currentQuote.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let id = f.id, !q.isEmpty, status(f) == .open || id == selected, let r = text.range(of: q) else { return nil }
            return Mark(id: id, range: r, selected: id == selected)
        }
    }

    public static func list(_ e: Episode, _ filter: Filter) -> [Finding] {
        (e.findings ?? []).filter { filter == .all || status($0).rawValue == filter.rawValue }
    }

    public static func count(_ e: Episode, _ filter: Filter) -> Int { list(e, filter).count }

    /// 근거가 나온 곳.
    public static func source(_ n: Int, _ f: Finding) -> String {
        let s = f.sourceEpisode ?? 0
        return s == 0 ? "설정 · 확정 사실" : s == n ? "이번 화 앞 문장" : "\(s)화"
    }

    /// 회차 띠 한 칸: '2회차 · 10:21 · 짚은 3 · 새로 1 · 결정 그대로 1 · 채팅 앱'.
    public static func round(_ r: CheckRound, now: Date = Date(), timeZone: TimeZone = .current) -> String {
        let at = when(r.at, now: now, timeZone: timeZone)
        let from = ["chat": " · 채팅 앱", "auto": " · 자동 집필"][r.source?.rawValue ?? ""] ?? ""
        return "\(r.no)회차\(at.isEmpty ? "" : " · \(at)") · 짚은 \(r.found ?? 0)"
            + (r.no > 1 ? " · 새로 \(r.added ?? 0)" : "")
            + ((r.keptAgain ?? 0) > 0 ? " · 결정 그대로 \(r.keptAgain!)" : "")
            + from + (r.widen == true ? " · 넓혀 찾기" : "")
    }

    /// 마지막 회차 뒤에 본문을 고쳤다는 알림.
    public static func staleNote(_ e: Episode) -> String? {
        guard e.checkState.stale, let r = e.rounds?.last else { return nil }
        return "\(r.no)회차 뒤에 본문을 고쳤어요. 고친 문장의 지적은 '문장 바뀜'으로 보여요. 고친 곳이 다른 곳과 어긋나지 않는지 보려면 다시 검수하세요."
    }

    /// 검수 단추 글자 (웹 `viewCheck` 의 `jobBtn('check', n, …)`).
    public static func checkLabel(_ e: Episode) -> String {
        e.rounds?.last.map { "다시 검수 · \($0.no + 1)회차" } ?? "검수하기"
    }

    /// 상태 승인으로 가는 단추 글자.
    public static func reviewLabel(_ e: Episode) -> String {
        let open = e.checkState.open
        return "상태 승인으로" + (open > 0 ? " · 열린 지적 \(open)" : "")
    }

    public static func empty(_ filter: Filter) -> String {
        filter == .open ? "열린 지적이 없어요. 상태 승인으로 넘어가도 돼요." : "이 상태의 지적이 없어요."
    }

    public static let notChecked = "아직 검수하지 않았어요. 앞선 본문 · 설정 · 확정 사실과 어긋나는 곳을 근거 문장과 함께 찾아요."
    public static let styleNote = "AI 없이 저장한 본문을 레퍼런스 기준과 견줘요. 계산값이라 처리 상태는 두지 않아요."
    public static let noStyleWarning = "기준을 넘은 문체 지표가 없어요."
    public static let recheckClosed = "다시 검수에서 문장이 사라져 고침으로 바꿨어요."
    public static let notFound = "지금 본문에서 찾을 수 없어요. 이미 고쳤을 수 있어요."

    /// 메모 칸 안내.
    public static func notePrompt(_ s: Status) -> String { "왜 \(s.label)인지 적어 두면 다시 나와도 바로 알아볼 수 있어요" }

    /// 시각: 오늘이면 시각만, 아니면 날짜 (웹 `passage.js` 의 `editTime`, `FeatureWrite.WriteText.when` 과 같다).
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
