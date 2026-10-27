import CanonAPI
import CanonCore
import CanonStore

/// 기승전결 네 칸 보드. 단편은 작품 전체 구조, 장편은 고른 아크의 구조 (웹 `actBoard`).
public struct PlotBoard: Equatable, Sendable {
    public struct Column: Equatable, Sendable {
        /// 구간 목록에서의 자리 (구간 고치기에 쓴다)
        public let index: Int
        public let act: Act
        public let count: Int
        /// 이 열에 둘 화 번호. 아직 플롯이 없으면 빈 칸으로 보인다 (60화까지)
        public let numbers: [Int]
        public let episodes: [Episode]
        /// 4화보다 짧은 작품에서 앞 구간과 함께 쓰는 화의 안내
        public let shared: String?
    }

    public let columns: [Column]
    /// 어느 구간에도 들지 않는 화. 구간 범위에 빈틈이 생겨도 사라지지 않게 따로 모은다
    public let loose: [Episode]

    public init(acts: [Act], episodes eps: [Episode]) {
        // 4화보다 짧은 작품은 이웃 구간이 한 화를 함께 쓴다. 그 화 카드는 앞 구간에만 둔다
        let owner = { (n: Int) in acts.firstIndex { $0.startEp <= n && n <= $0.endEp } }
        columns = acts.enumerated().map { i, a in
            let count = max(0, a.endEp - a.startEp + 1)
            let all = (0..<min(count, 60)).map { a.startEp + $0 }
            let nums = all.filter { owner($0) == i }
            let shared = all.filter { owner($0) != i }
            let note = shared.first.flatMap(owner).map { o in
                "\(shared.map { "\($0)화" }.joined(separator: ", "))는 \(acts[o].name.rawValue) 구간과 한 화에 함께 들어가요"
            }
            return Column(index: i, act: a, count: count, numbers: nums,
                          episodes: eps.filter { nums.contains($0.plot.number) }, shared: note)
        }
        loose = eps.filter { owner($0.plot.number) == nil }
    }
}

/// 화 플롯 편집기에 보일 것 (웹 `plotEditor` · `payoffPicker` · `castField`).
public struct PlotEditorInfo: Equatable, Sendable {
    public struct Payoff: Equatable, Sendable, Identifiable {
        public let id: String
        public let text: String
        public let detail: String
        public let on: Bool
        /// 이미 회수했거나 없는 복선이라 고를 수 없다
        public let fixed: Bool
    }

    public struct CastGroup: Equatable, Sendable {
        public let label: String
        public let characters: [Character]
    }

    public let number: Int
    public let status: EpisodeStatus
    /// 고칠 수 없다 (본문이 있거나 AI가 새로 만드는 중)
    public let locked: Bool
    /// 고칠 수 없는 까닭 안내
    public let lockNote: String?
    public let prev: Int?
    public let next: Int?
    /// 장편: '아크 3 제목 · 목표'
    public let arcNote: String?
    /// '기 구간 목표 · …'
    public let actNote: String?
    /// 1~3화이거나 이미 적은 화만 여는 장면 · 독자 질문 칸을 보인다
    public let showOpening: Bool
    public let showQuestion: Bool
    public let payoffs: [Payoff]
    /// 비중이 둘 이상이면 주역 · 조연 · 단역으로 나눈다. 하나뿐이면 이름 없는 묶음 하나
    public let castGroups: [CastGroup]
    /// AI 플롯이 데려온 새 인물 후보 (확정하면 함께 등록된다)
    public let candidates: [Character]
    /// 설정 없는 인물 id
    public let unknown: [String]

    public init(_ p: Project, episode e: Episode, busy: Bool, busyNote: String? = nil) {
        let n = e.plot.number
        number = n
        status = PlotRules.status(e)
        let hasText = status == .written || status == .finalized
        let locked = hasText || busy
        self.locked = locked
        lockNote = busy
            ? "AI가 이 화의 초안을 새로 만드는 중이라 끝날 때까지 고칠 수 없어요\(busyNote.map { " (\($0))" } ?? ""). 먼저 끝난 구간의 화는 지금 고칠 수 있어요."
            : hasText ? "본문이 있는 화라 플롯을 고칠 수 없어요." : nil
        let serial = p.meta?.form == .serial
        let arc = serial ? PlotRules.arc(of: n, p) : nil
        // 서랍을 닫지 않고 이웃 화로 옮겨 간다 (장편은 지금 아크 안에서)
        let nums = (p.episodes ?? []).map(\.plot.number).filter { x in arc.map { x >= $0.startEp && x <= $0.endEp } ?? true }
        prev = nums.filter { $0 < n }.last
        next = nums.first { $0 > n }
        arcNote = arc.map { "아크 \($0.number) \($0.title) · \($0.goal)" }
        actNote = PlotRules.act(of: n, p).map { "\($0.name.rawValue) 구간 목표 · \($0.goal)" }
        showOpening = n <= 3 || !(e.plot.opening ?? "").isEmpty
        showQuestion = n <= 3 || !(e.plot.readerQuestion ?? "").isEmpty

        let fs = p.foreshadows ?? []
        let cur = e.plot.foreshadowPayoff ?? []
        let open = fs.filter { ($0.status ?? .open) == .open }
        payoffs = open.map { f in
            Payoff(id: f.id, text: f.description, detail: "\(f.plantedEp)화에 심음\(f.dueEp.map { " · \($0)화 회수 예정" } ?? "")",
                   on: cur.contains(f.id), fixed: locked)
        } + cur.filter { id in !open.contains { $0.id == id } }.map { id in
            let f = fs.first { $0.id == id }
            return Payoff(id: id, text: f?.description ?? id, detail: f == nil ? "없는 복선 id" : "이미 회수함", on: true, fixed: true)
        }

        let cs = p.characters ?? []
        let groups = [(Character.TierPayload.main, "주역"), (.support, "조연"), (.minor, "단역")]
            .map { t, l in CastGroup(label: l, characters: cs.filter { ($0.tier ?? .main) == t }) }
            .filter { !$0.characters.isEmpty }
        castGroups = groups.count > 1 ? groups : [CastGroup(label: "", characters: cs)]
        let ids = e.plot.characters
        let candidates = (p.castCandidates ?? []).filter { ids.contains($0.id) }
        self.candidates = candidates
        unknown = ids.filter { id in !cs.contains { $0.id == id } && !candidates.contains { $0.id == id } }
    }
}

/// 화 카드에 보일 것 (웹 `epCard`).
public struct EpisodeCard: Equatable, Sendable, Identifiable {
    public let number: Int
    public let title: String
    public let summary: String
    public let status: EpisodeStatus
    /// AI가 이 화를 새로 만드는 중
    public let busy: Bool
    public var id: Int { number }

    public init(_ e: Episode, busy: Bool) {
        number = e.plot.number
        title = e.plot.title.isEmpty ? "제목 없음" : e.plot.title
        summary = e.plot.summary
        status = PlotRules.status(e)
        self.busy = busy
    }

    /// 읽어 주는 이름 (웹 `aria-label`).
    public var accessibilityLabel: String { "\(number)화 \(title) 플롯 열기" }
}
