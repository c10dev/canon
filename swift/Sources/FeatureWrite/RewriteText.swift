import CanonAPI
import CanonCore

/// 다시 생성 패널에서 고르는 중인 요청 (서버 `RewriteRequest`). 웹 `S.rw[n]`.
public struct RewriteDraft: Equatable, Sendable {
    public var feedback = ""
    public var presets: [String] = []
    public var materials: [String] = []
    public var mode: Mode = .fresh
    public var keep: [String] = []

    public enum Mode: String, CaseIterable, Sendable {
        case fresh, revise

        /// 방식 단추 글자와 설명 (웹 `RW_MODES`).
        public var label: String {
            switch self {
            case .fresh: "처음부터 새로"
            case .revise: "지난 판 고쳐 쓰기"
            }
        }

        public var help: String {
            switch self {
            case .fresh: "지난 판은 보내지 않고 같은 플롯으로 새로 써요. 전개를 크게 바꾸고 싶을 때."
            case .revise: "지난 판 전문을 함께 보내 흐름과 좋은 문장은 살리고 고쳐요. 대체로 괜찮고 몇 군데만 아쉬울 때."
            }
        }
    }

    public init() {}

    /// 처음 열 때의 요청: 검수 결과와 흡입력 판정은 넣을 것이 있고 오래되지 않았으면 넣는다 (웹 `rwReq`).
    public init(info: RewriteInfo) {
        materials = info.materials.filter { ["issues", "hook"].contains($0.id) && !$0.lines.isEmpty && $0.note.isEmpty }.map(\.id)
    }

    /// 새 판을 만든 요청으로 다시 고치기 (웹 `rwAgain`).
    public init(_ r: RewriteRequest) {
        feedback = r.feedback ?? ""
        presets = r.presets ?? []
        materials = (r.materials ?? []).map(\.rawValue)
        mode = Mode(rawValue: r.mode?.rawValue ?? "fresh") ?? .fresh
        keep = r.keep ?? []
    }

    /// 서버로 보낼 모양. 모르는 재료 id 는 뺀다.
    public var request: RewriteRequest {
        RewriteRequest(feedback: feedback, presets: presets,
                       materials: materials.compactMap { RewriteRequest.MaterialsPayloadPayload(rawValue: $0) },
                       mode: mode == .revise ? .revise : .fresh, keep: keep)
    }

    public mutating func toggle(preset id: String) {
        if presets.contains(id) { presets.removeAll { $0 == id } } else { presets.append(id) }
    }

    public mutating func toggle(material id: String) {
        if materials.contains(id) { materials.removeAll { $0 == id } } else { materials.append(id) }
    }

    /// 살릴 부분을 담는다. 못 담으면 이유 (웹 `selKeep`).
    public mutating func add(keep text: String, max: Int) -> String? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        if keep.contains(t) { return "이미 담은 부분이에요" }
        if keep.count >= max { return "살릴 부분은 \(max)개까지예요. 하나를 빼고 담으세요" }
        keep.append(t)
        return nil
    }
}

/// 다시 생성 · 새 판 · 이전 판 문구. 웹 `rewrite.js` 와 같다.
public enum RewriteText {
    /// 이전 판 종류 (웹 `RW_KIND`).
    public static func kind(_ v: TextVersion) -> String {
        switch v.kind ?? .previous {
        case .previous: "바꾸기 전"
        case .rejected: "고르지 않은 새 판"
        }
    }

    /// 요청을 짧게: 빠른 요청 이름, '고쳐 쓰기', 피드백 앞 60자 (웹 `rwReqLabel`). `labels` 는 빠른 요청 id → 이름.
    public static func requestBits(_ r: RewriteRequest?, labels: [String: String]) -> [String] {
        guard let r else { return [] }
        var bits = (r.presets ?? []).map { labels[$0] ?? $0 }
        if r.mode == .revise { bits.append("고쳐 쓰기") }
        if let f = r.feedback, !f.isEmpty { bits.append(WriteText.clip(f, 60)) }
        return bits
    }

    /// 재료 줄 오른쪽 글자: '없음' 또는 '3개'.
    public static func materialCount(_ lines: [String]) -> String {
        lines.isEmpty ? "없음" : "\(lines.count)개"
    }

    public static let panelHelp = "무엇이 아쉬웠는지 알려 주면 새 판에 반영해요. 지금 본문은 그대로 두고, 새 판이 오면 비교해서 골라요."
    public static let keepHelp = "마음에 드는 문장이나 장면을 본문에서 골라 복사한 뒤 '살릴 부분 담기'를 누르면 담겨요. 새 판에 거의 그대로 들어가요."
    public static let compareHelp = "바꾸면 지금 판은 아래 '이전 판'에 남아 되돌릴 수 있어요(화마다 최근 6개, 고르지 않은 판부터 지워요). 검수 결과는 새 판 기준으로 다시 하세요."
    public static let adopted = "새 판으로 바꿨어요. 지금까지의 본문은 아래 '이전 판'에 남았어요."
    public static let dropped = "새 판을 고르지 않았어요. 버린 판도 '이전 판'에 남아요 (6개가 넘으면 고르지 않은 판부터 지워요)."
    public static let restored = "되돌렸어요. 검수 결과는 이 판 기준으로 다시 하세요."
    public static let restoreAsk = "지금 본문을 이전 판에 남기고 이 판으로 되돌릴까요?"

    /// 새 판 비교 칸 머리 '지금 판 · 1,234자'.
    public static func side(_ title: String, _ text: String) -> String {
        "\(title) · \(WriteText.number(text.utf16.count))자"
    }

    /// 바뀐 곳 비교 머리 (웹 `diffBox`).
    public static func changes(_ n: Int) -> String {
        n > 0 ? "바뀐 곳 \(n)곳" : "바뀐 곳이 없어요"
    }

    /// 이전 판 목록 머리 설명. `blocked` 는 저장하지 않은 본문이 있어 복원을 막았다.
    public static func versionsHelp(_ count: Int, blocked: Bool) -> String {
        "\(count)개 · 다시 생성으로 바꾸기 전 본문과 고르지 않은 새 판. 최근 6개까지 남고, 넘치면 고르지 않은 판부터 지워요\(blocked ? " (저장하지 않은 본문이 있으면 먼저 저장하세요)" : "")"
    }
}
