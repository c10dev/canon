import CanonAPI
import CanonCore
import CanonStore
import Foundation

/// 작업지시서 화면의 표시 규칙. 웹 `app.js` 의 `viewBrief` · `briefTabFor` · `importCount` · `copyBrief` · `downloadBrief` ·
/// `importText` · `importJson` · `blockedBefore` · `orderNote` 와 같은 문구라 함께 고친다.
public enum BriefText {
    static func status(_ e: Episode) -> EpisodeStatus {
        EpisodeStatus(rawValue: e.status?.rawValue ?? "draft") ?? .draft
    }

    /// 고른 적 없는 화의 지시서: 본문이 있고 반영하지 않았으면 상태 승인 지시서 (웹 `briefTabFor`).
    public static func defaultKind(_ s: EpisodeStatus) -> BriefKind {
        s == .written ? .state : .episode
    }

    public static let description = "Claude, Gemini, ChatGPT 구독 앱에 붙여 넣을 지시서예요. API 생성과 똑같은 컨텍스트를 써요."

    /// 받은 본문을 저장할 수 있는 화: 플롯 확정 · 본문 작성 (초안은 확정부터, 끝난 화는 고치지 않는다).
    public static func canImportText(_ s: EpisodeStatus) -> Bool {
        s != .draft && s != .finalized
    }

    public static func textNote(_ s: EpisodeStatus) -> String? {
        switch s {
        case .draft: "플롯을 확정해야 본문을 저장할 수 있어요."
        case .finalized: "이미 끝난 화예요."
        default: nil
        }
    }

    public static let jsonNote = "본문이 작성된 화에서만 쓸 수 있어요."
    public static let draftWarning = "플롯이 아직 초안이에요. 확정 전 내용으로 지시서가 만들어져요."

    public static func stateBlocked(_ n: Int) -> String {
        "\(n)화 본문이 아직 없어 상태 승인 지시서를 만들 수 없어요. 본문을 먼저 저장하세요."
    }

    /// n화보다 앞인데 상태 반영이 끝나지 않은 화 (웹 `blockedBefore`, 서버 `pipeline.require_previous`).
    public static func blockedBefore(_ n: Int, in eps: [Episode]) -> [Int] {
        eps.filter { $0.plot.number < n && status($0) != .finalized }.map(\.plot.number)
    }

    /// 앞 화가 반영되지 않아 쓰지 못한다는 안내와, 그 화로 가는 단추 (웹 `orderNote`).
    public struct OrderNote: Equatable, Sendable {
        public let text: String
        public let button: String
        public let screen: Screen
    }

    public static func orderNote(_ blocked: [Int], in eps: [Episode]) -> OrderNote? {
        guard let first = blocked.first, let e = eps.first(where: { $0.plot.number == first }) else { return nil }
        let written = status(e) == .written
        return OrderNote(text: "이전 화(\(blocked.map(String.init).joined(separator: ", "))화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙이에요.",
                         button: "\(first)화 \(written ? "상태 승인으로" : "집필로")", screen: written ? .review : .write)
    }

    /// 붙여 넣은 본문 글자 수와 목표 분량 (웹 `importCount`). 목표의 70%보다 짧으면 잘렸는지 보라고 한다.
    /// 글자 수는 JS `length` 처럼 UTF-16 단위로 센다.
    public static func count(_ text: String, goal: Int) -> (text: String, short: Bool) {
        let len = text.trimmingCharacters(in: .whitespacesAndNewlines).utf16.count
        let short = len > 0 && goal > 0 && Double(len) < Double(goal) * 0.7
        return ("\(grouped(len)) / \(grouped(goal))자", short)
    }

    public static let shortWarning = "목표보다 많이 짧아요. 본문이 잘렸는지 확인하세요"

    /// 지시서 글자 수 ('12,345자').
    public static func length(_ text: String) -> String { "\(grouped(text.utf16.count))자" }

    static func grouped(_ n: Int) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.groupingSeparator = ","
        f.usesGroupingSeparator = true
        return f.string(from: NSNumber(value: n)) ?? String(n)
    }

    /// 내려받을 파일 이름 '작품-03-episode.md' (웹 `downloadBrief`).
    public static func filename(_ project: String, ep: Int, kind: BriefKind) -> String {
        "\(project)-\(String(format: "%02d", ep))-\(kind.rawValue).md"
    }

    public static let copied = "복사했어요. 채팅 앱에 붙여 넣으세요."
    public static let copyFailed = "복사하지 못했어요. 내용을 직접 선택해 복사하세요."
    public static let pasteText = "본문을 붙여 넣으세요"
    public static let pasteJSON = "JSON을 붙여 넣으세요"

    public static func replaceQuestion(_ n: Int) -> String { "\(n)화의 지금 본문을 바꿀까요?" }
    public static func savedText(_ n: Int) -> String { "\(n)화 본문으로 저장했어요" }
    public static func saveTextButton(_ n: Int) -> String { "\(n)화 본문으로 저장" }

    /// 확인한 변경안의 크기. 상태 승인 화면으로 넘기지 못할 때 보인다.
    public static func parsedSummary(_ d: StateDelta) -> String {
        let parts = [("인물 상태", d.characterUpdates?.count ?? 0), ("사건", d.events?.count ?? 0), ("관계", d.relationshipUpdates?.count ?? 0),
                     ("비밀", d.secretsAdded?.count ?? 0), ("새 사실", d.newFacts?.count ?? 0), ("새 복선", d.foreshadowPlanted?.count ?? 0),
                     ("회수한 복선", d.foreshadowResolved?.count ?? 0), ("새 인물", d.newCharacters?.count ?? 0), ("새 장소", d.newPlaces?.count ?? 0)]
            .filter { $0.1 > 0 }.map { "\($0.0) \($0.1)" }
        return "JSON을 확인했어요" + (parts.isEmpty ? "." : ": " + parts.joined(separator: " · "))
    }

    public static let noHandOff = "앱의 상태 승인 화면은 아직 이 변경안을 받지 못해요. 웹의 작업지시서 화면에서 같은 JSON을 가져오세요."

    /// 순서 안내 (웹 `viewBrief` 의 '순서').
    public static let steps = ["본문 작성 지시서 → 받은 본문 저장", "상태 승인 지시서 → 받은 JSON 가져오기", "상태 승인 화면에서 반영"]
}
