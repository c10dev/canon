/// 작품 화면 목록. 이름과 순서는 웹 사이드바(`app.js` 의 `sidebar`)와 같아 함께 고친다.
public enum Screen: String, CaseIterable, Sendable, Identifiable {
    // 작업 순서 (번호가 붙는다)
    case home, setup, style, arc, write, review
    // 작품 도구
    case cast, atlas, foreshadow, statwin, timeline, lines, causal, brief, auto
    // 본편과 분리
    case research, usage

    public var id: String { rawValue }

    public enum Group: Sendable { case steps, tools, separate }

    public var group: Group {
        switch self {
        case .home, .setup, .style, .arc, .write, .review: .steps
        case .research, .usage: .separate
        default: .tools
        }
    }

    /// 사이드바 앞 글자 (단계 번호나 기호).
    public var mark: String {
        switch self {
        case .home: "H"
        case .setup: "1"
        case .style: "2"
        case .arc: "3"
        case .write: "4"
        case .review: "5"
        case .cast: "人"
        case .atlas: "地"
        case .foreshadow: "伏"
        case .statwin: "#"
        case .timeline: "時"
        case .lines: "⑂"
        case .causal: "∴"
        case .brief: "✎"
        case .auto: "A"
        case .research: "R"
        case .usage: "$"
        }
    }

    /// 화면 이름. 장편이면 기획 단계 이름이 다르다.
    public func label(serial: Bool) -> String {
        switch self {
        case .home: "작품 홈"
        case .setup: "설정 도우미"
        case .style: "문체 레퍼런스"
        case .arc: serial ? "부 · 아크 · 플롯" : "기승전결 · 플롯"
        case .write: "집필"
        case .review: "상태 승인"
        case .cast: "인물 · 관계도"
        case .atlas: "지도"
        case .foreshadow: "복선 센터"
        case .statwin: "상태창 수치"
        case .timeline: "작품 속 시간"
        case .lines: "이야기 줄기"
        case .causal: "인과율"
        case .brief: "작업지시서 (API 없이)"
        case .auto: "자동 집필"
        case .research: "연구 · 모델 실험"
        case .usage: "사용량 · 비용"
        }
    }
}
