import CanonAPI
import CanonCore
import CanonStore
import Foundation

typealias Act = Components.Schemas.Act

/// 작품 홈에 보일 것. 웹 `viewHome` · `nextStep` · `currentEp` 와 같은 규칙이라 함께 고친다.
/// 자동 집필 상태(`nextStep` 의 자동 집필 줄)와 관계 카드는 아직 빠져 있다.
public struct HomeSummary: Equatable, Sendable {
    public struct Stage: Equatable, Sendable {
        public enum State: Equatable, Sendable {
            case done, doing, notStarted
            /// 단계 칸 위 글자.
            public var label: String {
                switch self {
                case .done: "완료"
                case .doing: "진행 중"
                case .notStarted: "시작 전"
                }
            }
        }
        public let state: State
        public let title: String
        public let detail: String
        public let screen: Screen
    }

    public struct Cell: Equatable, Sendable {
        public let number: Int
        public let status: EpisodeStatus
        /// 칸 아래 글자: 초안 · 확정 · 작성됨 · 반영 완료 · 자동 반영
        public let label: String
        public let current: Bool
        public let title: String
        /// 단편의 기승전결 구간 (기 · 승 · 전 · 결)
        public let act: String?
        public let screen: Screen

        /// 읽어 주는 이름: '3화 작성됨 · 지금 화 · 제목'
        public var accessibilityLabel: String {
            "\(number)화 \(label)\(current ? " · 지금 화" : "")\(title.isEmpty ? "" : " · \(title)")"
        }
    }

    /// 다음 할 일 단추.
    public struct Next: Equatable, Sendable {
        public let label: String
        public let screen: Screen
    }

    public struct Band: Equatable, Sendable {
        public let title: String
        public let range: String
    }

    public struct CharacterLine: Equatable, Sendable {
        public let name: String
        public let role: String
        /// [(감정, …), (목표, …), (위치, …)] 중 값이 있는 것. 비면 '아직 변화 없음'
        public let lines: [String]
    }

    public struct Clue: Equatable, Sendable {
        public let id: String
        public let plantedEp: Int
        public let description: String
    }

    public let subtitle: String
    public let title: String
    public let logline: String
    public let serial: Bool
    public let next: Next
    /// 장편: 끝났는데 요약이 없는 아크 · 부를 요약하는 단추 글자 ('아크 3 요약', '2부 요약')
    public let recap: String?
    public let stages: [Stage]
    public let bands: [Band]
    public let cells: [Cell]
    /// 장편은 지금 부만 칸으로 보인다는 안내
    public let partNote: String?
    public let notes: [String]
    public let statesBasis: String
    public let characters: [CharacterLine]
    public let openClues: [Clue]
    public let facts: [String]
    public let factCount: Int
    /// 반영한 화 수. 하나라도 있으면 '갈래 만들기'를 보인다.
    public let finalized: Int


    public init(_ p: Project, name: String) {
        let m = p.meta
        let eps = p.episodes ?? []
        let target = m?.targetEpisodes ?? 0
        let serial = m?.form == .serial
        let arcs = (p.storyArcs ?? []).sorted { $0.startEp < $1.startEp }
        let count = { (s: EpisodeStatus) in eps.filter { Self.status($0) == s }.count }
        let confirmed = eps.count - count(.draft)
        let written = count(.written) + count(.finalized)
        let fin = count(.finalized)
        let samples = p.style?.samplePassages?.count ?? 0
        let hasStyle = !(p.style?.narrationPov ?? "").isEmpty || samples > 0
        let planned = arcs.map(\.endEp).max() ?? 0
        let cur = Self.currentEp(eps)
        let finished = { (s: Int, e: Int) in (s...max(s, e)).allSatisfy { n in eps.first { $0.plot.number == n }.map { Self.status($0) == .finalized } ?? false } }

        self.serial = serial
        finalized = fin
        title = (m?.title ?? "").isEmpty ? name : m!.title!
        logline = m?.logline ?? ""
        let words = (m?.wordsPerEpisode ?? 0).formatted(.number.locale(Locale(identifier: "ko_KR")))
        subtitle = "\((m?.genre ?? "").isEmpty ? "장르 미정" : m!.genre!)\(m?.adult == true ? " · 성인" : "") · 전 \(target)화 · 화당 \(words)자"

        // 장편: 끝났는데 요약이 없는 아크 · 부 (pipeline.pending_recaps 와 같은 규칙)
        let parts = p.parts ?? []
        let summed = serial ? parts.filter { !($0.summary ?? "").isEmpty } : []
        let recapArcs = serial ? arcs.filter { a in (a.summary ?? "").isEmpty && finished(a.startEp, a.endEp) && !summed.contains { $0.startEp <= a.startEp && a.startEp <= $0.endEp } } : []
        let recapParts = serial ? parts.filter { ($0.summary ?? "").isEmpty && finished($0.startEp, $0.endEp) } : []
        let recapN = recapArcs.count + recapParts.count
        recap = recapArcs.first.map { "아크 \($0.number) 요약" } ?? recapParts.first.map { "\($0.number)부 요약" }

        func state(_ ok: Bool, _ partial: Bool = false) -> Stage.State { ok ? .done : partial ? .doing : .notStarted }
        let chars = p.characters?.count ?? 0
        stages = [
            Stage(state: state(chars > 0), title: "1 설정", detail: "인물 \(chars) · 관계 \(p.relationships?.count ?? 0)", screen: .setup),
            Stage(state: state(hasStyle), title: "2 문체", detail: hasStyle ? "대표 문단 \(samples)개" : "선택 사항", screen: .style),
            serial
                ? Stage(state: state(planned >= target, !arcs.isEmpty), title: "3 부 · 아크",
                        detail: arcs.isEmpty ? "없음" : "아크 \(arcs.count)개 · \(planned)화까지\(recapN > 0 ? " · 요약 필요 \(recapN)개" : "")", screen: .arc)
                : Stage(state: state((p.arc ?? []).count == 4), title: "3 기승전결", detail: (p.arc ?? []).isEmpty ? "없음" : "4구간", screen: .arc),
            Stage(state: state(!eps.isEmpty && confirmed == target, confirmed > 0), title: "3 플롯 확정", detail: "\(confirmed) / \(target)화", screen: .arc),
            Stage(state: state(written == target, written > 0), title: "4 집필", detail: "\(written) / \(target)화", screen: .write),
            Stage(state: state(fin == target, fin > 0), title: "5 상태 승인", detail: "\(fin) / \(target)화", screen: .review),
        ]
        next = Self.nextStep(p, current: cur, planned: planned)

        // 장편은 지금 쓰는 부(없으면 지금 화 앞뒤 30화)만 칸으로 보인다
        let curPart = serial ? parts.first { $0.startEp <= cur && cur <= $0.endEp } : nil
        let shown = !serial ? eps
            : curPart.map { pt in eps.filter { $0.plot.number >= pt.startEp && $0.plot.number <= pt.endEp } }
            ?? eps.filter { abs($0.plot.number - cur) <= 30 }
        partNote = curPart.map { "\($0.number)부 \($0.title) (\($0.startEp)~\($0.endEp)화)만 보여요. 전체는 부 · 아크에서 보세요." }
        let acts = p.arc ?? []
        bands = serial
            ? arcs.filter { a in shown.contains { $0.plot.number >= a.startEp && $0.plot.number <= a.endEp } }
                .map { Band(title: "아크 \($0.number)", range: "\($0.startEp)~\($0.endEp)화 \($0.title)") }
            : Self.actGroups(acts).map { Band(title: $0.names.joined(separator: "·"), range: KoreanText.episodeRange($0.start, $0.end)) }
        cells = shown.map { e in
            let n = e.plot.number
            let s = Self.status(e)
            return Cell(number: n, status: s, label: e.auto == true ? "자동 반영" : s.label.replacingOccurrences(of: "플롯 ", with: "").replacingOccurrences(of: "본문 ", with: ""),
                        current: n == cur && s != .finalized, title: e.plot.title,
                        act: serial ? nil : acts.first { $0.startEp <= n && n <= $0.endEp }?.name.rawValue,
                        screen: s == .draft ? .arc : s == .written ? .review : .write)
        }

        var notes: [String] = []
        if let last = p.history?.last, let w = last.warnings, !w.isEmpty {
            notes.append("\(last.episode)화 반영 때 검수 경고: \(w.joined(separator: " / "))")
        }
        if eps.contains(where: { Self.status($0) == .written }) {
            notes.append("\(cur)화 본문이 작성됐어요. 상태 변경안을 승인해야 다음 화를 쓸 수 있어요.")
        }
        self.notes = notes

        statesBasis = fin > 0 ? "\(fin)화 기준" : "시작 시점"
        characters = (p.characters ?? []).map { c in
            let s = p.states?.first { $0.characterId == c.id }
            let lines = [("감정", s?.emotionalState), ("목표", s?.currentGoal), ("위치", s?.location), ("차림", s?.attire)]
                .compactMap { k, v in (v ?? "").isEmpty ? nil : "\(k): \(v!)" }
            return CharacterLine(name: c.name, role: c.role, lines: lines)
        }
        openClues = (p.foreshadows ?? []).filter { ($0.status ?? .open) == .open }
            .map { Clue(id: $0.id, plantedEp: $0.plantedEp, description: $0.description) }
        let facts = p.facts ?? []
        self.facts = Array(facts.suffix(8))
        factCount = facts.count
    }

    static func status(_ e: Episode) -> EpisodeStatus {
        EpisodeStatus(rawValue: e.status?.rawValue ?? "draft") ?? .draft
    }

    /// 지금 작업해야 할 화: 반영이 끝나지 않은 첫 화 (웹 `currentEp`).
    static func currentEp(_ eps: [Episode]) -> Int {
        guard let last = eps.last else { return 1 }
        return eps.first { status($0) != .finalized }?.plot.number ?? last.plot.number
    }

    /// 화를 함께 쓰는 구간을 한 묶음으로 (웹 `actGroups`, `web._plot_ranges` 와 같다).
    static func actGroups(_ acts: [Act]) -> [(names: [String], start: Int, end: Int)] {
        var out: [(names: [String], start: Int, end: Int)] = []
        for a in acts {
            if let g = out.last, a.startEp <= g.end {
                out[out.count - 1] = (g.names + [a.name.rawValue], g.start, max(g.end, a.endEp))
            } else {
                out.append(([a.name.rawValue], a.startEp, a.endEp))
            }
        }
        return out
    }

    /// 다음 할 일과 그 화면 (웹 `nextStep`, 자동 집필 줄은 빠짐).
    static func nextStep(_ p: Project, current: Int, planned: Int) -> Next {
        let eps = p.episodes ?? []
        if (p.characters ?? []).isEmpty { return Next(label: "설정 시작", screen: .setup) }
        let serial = p.meta?.form == .serial
        if serial {
            let open = eps.first { status($0) != .finalized }
            if open == nil && planned < (p.meta?.targetEpisodes ?? 0) { return Next(label: "다음 아크 기획 (\(planned + 1)화부터)", screen: .arc) }
            if eps.isEmpty { return Next(label: "부 · 아크 기획", screen: .arc) }
        }
        let beats = serial ? (p.storyArcs ?? []).flatMap { $0.acts ?? [] } : (p.arc ?? [])
        if beats.isEmpty || eps.isEmpty { return Next(label: "기승전결 · 플롯 만들기", screen: .arc) }
        guard let e = eps.first(where: { $0.plot.number == current }) else { return Next(label: "기승전결 · 플롯 만들기", screen: .arc) }
        let n = e.plot.number
        switch status(e) {
        case .draft: return Next(label: "\(n)화 플롯 확정", screen: .arc)
        case .confirmed: return Next(label: "\(n)화 쓰기", screen: .write)
        case .written: return Next(label: "\(n)화 상태 승인", screen: .review)
        case .finalized: return Next(label: "완결 원고 보기", screen: .write)
        }
    }
}
