import Foundation

/// 새 작품 마법사의 규칙: 필수 칸 여섯 개를 여섯 걸음으로 묻는다.
/// 웹 `setup.js` 의 `WIZ_STEPS` · `WIZ_REQ` · `setupReqs` · `wizFirstGap` · `wizStepState` · `WORLD_KINDS` · `ERAS` · `WORLD_REC` ·
/// `worldKindOf` · `withWorldKind` · `worldRecs` 와 같은 규칙이라 함께 고친다.
public enum SetupWizard {
    /// 걸음 이름 (웹 `WIZ_STEPS`).
    public static let steps = ["제목 · 장르", "로그라인", "세계", "인물", "관계", "마무리"]
    /// 마무리 걸음 번호.
    public static let finish = 5
    /// 필수 칸과 그 칸을 묻는 걸음 (웹 `WIZ_REQ`). 순서는 `reqs` 와 같다.
    public static let required: [(label: String, step: Int)] = [
        ("제목", 0), ("장르", 0), ("로그라인", 1), ("세계 배경", 2), ("인물 2명 이상", 3), ("관계 1개", 4),
    ]

    /// 필수 칸을 보는 데 쓰는 작품 값. 생성 타입에 기대지 않으려고 필요한 값만 받는다.
    public struct Input: Equatable, Sendable {
        public struct Person: Equatable, Sendable {
            public var id: String
            public var name: String
            public init(id: String, name: String) {
                self.id = id
                self.name = name
            }
        }

        public struct Pair: Equatable, Sendable {
            public var a: String
            public var b: String
            public var type: String
            public init(a: String, b: String, type: String = "") {
                self.a = a
                self.b = b
                self.type = type
            }
        }

        public var title: String
        public var genres: [String]
        public var logline: String
        public var setting: String
        public var characters: [Person]
        public var relationships: [Pair]

        public init(title: String = "", genres: [String] = [], logline: String = "", setting: String = "",
                    characters: [Person] = [], relationships: [Pair] = []) {
            self.title = title
            self.genres = genres
            self.logline = logline
            self.setting = setting
            self.characters = characters
            self.relationships = relationships
        }
    }

    /// 걸음 막대 한 칸의 상태 (웹 `wizStepState` 의 'done' · 'miss' · '').
    public enum StepState: String, Equatable, Sendable {
        /// 그 걸음의 필수를 다 채움
        case done
        /// 들렀는데 빈 필수가 남음
        case miss
        /// 아직
        case none = ""
    }

    private static func blank(_ s: String) -> Bool { s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    /// 이름이 있는 인물 수.
    public static func named(_ p: Input) -> Int { p.characters.filter { !blank($0.name) }.count }

    /// 필수 칸 여섯 개를 채웠나: 제목, 장르, 로그라인, 배경, 이름 있는 인물 둘, 서로 다른 두 인물의 관계 하나 (웹 `setupReqs`).
    public static func reqs(_ p: Input) -> [Bool] {
        let ids = Set(p.characters.map(\.id))
        return [
            !blank(p.title),
            !p.genres.isEmpty,
            !blank(p.logline),
            !blank(p.setting),
            named(p) >= 2,
            p.relationships.contains { $0.a != $0.b && ids.contains($0.a) && ids.contains($0.b) },
        ]
    }

    /// 필수를 다 채웠나.
    public static func complete(_ p: Input) -> Bool { reqs(p).allSatisfy { $0 } }

    /// 필수 칸이 빈 첫 걸음. 다 채웠으면 마무리 걸음 (웹 `wizFirstGap`).
    public static func firstGap(_ p: Input) -> Int {
        guard let k = reqs(p).firstIndex(of: false) else { return finish }
        return required[k].step
    }

    /// 걸음 `i` 의 상태. `seen` 은 들른 걸음 번호 (웹 `wizStepState`). 마무리 걸음은 필수 여섯 개를 모두 본다.
    public static func stepState(_ p: Input, _ i: Int, seen: [Int]) -> StepState {
        let r = reqs(p)
        let need = i == finish ? r : r.indices.filter { required[$0].step == i }.map { r[$0] }
        if need.allSatisfy({ $0 }) { return .done }
        return seen.contains(i) ? .miss : .none
    }

    /// 빈 필수 칸 이름 (마무리 걸음의 '남은 필수 칸').
    public static func gaps(_ p: Input) -> [String] {
        zip(required, reqs(p)).filter { !$0.1 }.map(\.0.label)
    }

    /// 마무리 걸음의 필수 칸 값 (웹 `wizFinish` 의 `vals`). 장르 이름은 `genreName` 이 고른다.
    public static func summary(_ p: Input, genreName: (String) -> String) -> [String] {
        let name = { (id: String) in p.characters.first { $0.id == id }.flatMap { $0.name.isEmpty ? nil : $0.name } ?? id }
        return [
            p.title,
            p.genres.map(genreName).joined(separator: ", "),
            p.logline,
            p.setting,
            p.characters.filter { !blank($0.name) }.map(\.name).joined(separator: ", "),
            p.relationships.filter { $0.a != $0.b }
                .map { "\(name($0.a)) ↔ \(name($0.b))\($0.type.isEmpty ? "" : " · " + $0.type)" }
                .joined(separator: " / "),
        ]
    }

    // MARK: 세계 종류 · 시대

    /// 세계 종류: 고르면 배경 칸 맨 앞에 첫 문장이 들어간다. 뒤에 쓴 글은 그대로 둔다 (웹 `WORLD_KINDS`).
    public static let worldKinds: [(label: String, sentence: String)] = [
        ("현대 한국", "지금의 한국."),
        ("현대 판타지", "지금의 한국에 게이트와 각성자가 나타난 세계."),
        ("서양풍 제국", "귀족과 황실이 다스리는 서양풍 제국."),
        ("중세 판타지 왕국", "검과 마법이 있는 중세풍 왕국."),
        ("동양 무협", "문파와 강호가 얽힌 무림."),
        ("궁중 사극", "왕실과 궁궐을 중심으로 한 옛 한국."),
        ("학원 · 아카데미", "능력자를 길러 내는 학원."),
        ("근미래 도시", "기술이 조금 앞선 가까운 미래의 도시."),
        ("디스토피아", "무너진 질서 위에 세워진 통제 사회."),
        ("우주 SF", "여러 행성을 오가는 우주 시대."),
        ("현대 해외", "지금의 해외 도시."),
    ]

    /// 시대: 고르면 `world.era` 에 이 말이 그대로 들어간다 (웹 `ERAS`).
    public static let eras = ["현대", "근미래", "먼 미래", "근대 · 개화기", "조선", "고려 이전", "중세풍", "근세풍", "고대풍", "시대를 정하지 않음"]

    /// 장르 id(서버 `genres.CATALOG`)마다 앞에 둘 세계 종류 · 시대 (웹 `WORLD_REC`).
    public static let worldRec: [String: (kinds: [String], eras: [String])] = [
        "romance": (["현대 한국"], ["현대"]),
        "drama": (["현대 한국"], ["현대"]),
        "office": (["현대 한국"], ["현대"]),
        "healing": (["현대 한국"], ["현대"]),
        "sports": (["현대 한국"], ["현대"]),
        "romance_fantasy": (["서양풍 제국", "중세 판타지 왕국"], ["중세풍", "근세풍"]),
        "fantasy": (["중세 판타지 왕국", "서양풍 제국"], ["중세풍"]),
        "light_novel": (["중세 판타지 왕국", "학원 · 아카데미"], ["중세풍", "현대"]),
        "modern_fantasy": (["현대 판타지"], ["현대"]),
        "martial_arts": (["동양 무협"], ["고대풍"]),
        "alt_history": (["궁중 사극"], ["조선", "근대 · 개화기"]),
        "sf": (["우주 SF", "근미래 도시", "디스토피아"], ["근미래", "먼 미래"]),
        "academy": (["학원 · 아카데미"], []),
        "mystery": (["현대 한국"], ["현대", "근대 · 개화기"]),
        "thriller": (["현대 한국", "근미래 도시"], ["현대"]),
        "horror": (["현대 한국"], ["현대"]),
    ]

    /// 배경 글이 세계 종류 문장으로 시작하면 그 종류 이름, 아니면 빈 글 (웹 `worldKindOf`).
    public static func worldKind(of setting: String) -> String {
        worldKinds.first { setting.hasPrefix($0.sentence) }?.label ?? ""
    }

    /// 세계 종류를 고른 뒤의 배경 글: 앞의 종류 문장만 바꾸고 뒤 글은 남긴다.
    /// 고른 종류를 다시 고르면 종류 문장만 뺀다 (웹 `withWorldKind`).
    public static func withWorldKind(_ setting: String, _ label: String) -> String {
        let now = worldKind(of: setting)
        let cur = worldKinds.first { $0.label == now }
        let rest = (cur.map { String(setting.dropFirst($0.sentence.count)) } ?? setting).trimmingCharacters(in: .whitespacesAndNewlines)
        guard let pick = worldKinds.first(where: { $0.label == label }), cur?.label != label else { return rest }
        return pick.sentence + (rest.isEmpty ? "" : " " + rest)
    }

    /// 고른 장르 순서대로 모은 추천. `eras` 가 거짓이면 세계 종류, 참이면 시대 (웹 `worldRecs` 의 k 0 · 1).
    public static func worldRecs(_ genres: [String], eras: Bool) -> [String] {
        var out: [String] = []
        for g in genres {
            guard let r = worldRec[g] else { continue }
            for x in eras ? r.eras : r.kinds where !out.contains(x) { out.append(x) }
        }
        return out
    }

    /// 시대 칩을 누른 뒤의 시대: 고른 시대를 다시 누르면 비운다 (웹 `wizEra`).
    public static func withEra(_ era: String, _ label: String) -> String { era == label ? "" : label }

    /// 인물 걸음의 역할 예시 (웹 `WIZ_ROLES`).
    public static let roles = ["주인공", "상대역", "조력자", "라이벌", "악역"]

    /// 필수 칸 수 글 '필수 n/6' (웹 `wizMeter`).
    public static func meter(_ p: Input) -> String { "필수 \(reqs(p).filter { $0 }.count)/\(required.count)" }

    /// 걸음 막대 한 칸의 읽어 주는 글 (웹 `wizStepper` 의 `aria-label`).
    public static func stepLabel(_ i: Int, _ state: StepState) -> String {
        let word = state == .done ? ", 채움" : state == .miss ? ", 빈 필수 칸 있음" : ""
        return "\(i + 1). \(steps[i])\(word)"
    }
}
