import CanonAPI
import CanonCore
import CanonStore

public typealias Act = Components.Schemas.Act
public typealias StoryArc = Components.Schemas.StoryArc
public typealias Part = Components.Schemas.Part
public typealias SeriesPlan = Components.Schemas.SeriesPlan
public typealias ArcProposal = Components.Schemas.ArcProposal
public typealias ArcPlan = Components.Schemas.ArcPlan
public typealias Recap = Components.Schemas.Recap
public typealias Character = Components.Schemas.Character
public typealias Foreshadow = Components.Schemas.Foreshadow

/// 기승전결 · 플롯 화면이 직접 계산하는 규칙. 웹 `app.js` · `insert.js` 와 같은 규칙이라 함께 고친다 (README '웹과 같은 규칙').
public enum PlotRules {
    /// 구간 이름 순서 (웹 `ACTS`).
    public static let actNames: [Act.NamePayload] = [.기, .승, .전, .결]

    static func status(_ e: Episode) -> EpisodeStatus {
        EpisodeStatus(rawValue: e.status?.rawValue ?? "draft") ?? .draft
    }

    /// start~total 화를 weights 비율로 기승전결 네 구간에 나눈다 (웹 `actRanges`, 서버 `pipeline.act_ranges`). 나눌 화가 없으면 nil.
    public static func actRanges(total: Int, start: Int, weights: [Double]? = nil) -> [(Int, Int)]? {
        let size = total - start + 1
        if size < 1 { return nil }
        if size < 4 {
            let idx = [1: [0, 0, 0, 0], 2: [0, 0, 1, 1], 3: [0, 1, 2, 2]][size]!
            return idx.map { (start + $0, start + $0) }
        }
        let w = (weights ?? [0.18, 0.38, 0.26, 0.18]).map { max($0, 0.01) }
        let sum = w.reduce(0, +)
        let raw = w.map { $0 / sum * Double(size) }
        var lens = raw.map { max(1, Int($0.rounded(.down))) }
        // 처음 나온 가장 큰 값 (JS reduce, Python max 와 같다)
        func argmax(_ f: (Int) -> Double) -> Int { (0..<4).reduce(0) { f($1) > f($0) ? $1 : $0 } }
        while lens.reduce(0, +) < size { lens[argmax { raw[$0] - Double(lens[$0]) }] += 1 }
        while lens.reduce(0, +) > size { lens[argmax { Double(lens[$0]) }] -= 1 }
        var a = start
        return lens.map { n in
            defer { a += n }
            return (a, a + n - 1)
        }
    }

    /// 아크 끝 화를 바꾼다. 결 구간만 늘이거나 줄여 맞으면 그렇게 하고, 결이 시작 화보다 앞으로 오면 구간 길이 비율대로 다시 나눈다
    /// (웹 `fitActs`, 서버 `clean_arc` · `fit_arc` 와 같은 결과).
    public static func setArcEnd(_ arc: inout StoryArc, _ end: Int) {
        arc.endEp = end
        guard var acts = arc.acts, end >= arc.startEp else { return }
        let order = acts.indices.sorted { actNames.firstIndex(of: acts[$0].name)! < actNames.firstIndex(of: acts[$1].name)! }
        guard let last = order.last else { return }
        if end >= acts[last].startEp {
            acts[last].endEp = end
        } else if let r = actRanges(total: end, start: arc.startEp, weights: order.map { Double(max(1, acts[$0].endEp - acts[$0].startEp + 1)) }) {
            for (k, i) in order.enumerated() where k < r.count { (acts[i].startEp, acts[i].endEp) = r[k] }
        }
        arc.acts = acts
    }

    /// [1,2,3,5,7,8] → '1~3, 5, 7~8' (웹 `rangeText`).
    public static func rangeText(_ nums: [Int]) -> String {
        var out: [String] = []
        var i = 0
        while i < nums.count {
            var j = i
            while j + 1 < nums.count && nums[j + 1] == nums[j] + 1 { j += 1 }
            out.append(i == j ? "\(nums[i])" : "\(nums[i])~\(nums[j])")
            i = j + 1
        }
        return out.joined(separator: ", ")
    }

    /// 구간 범위가 start~end 화를 빈틈 · 겹침 없이 덮는지. 문제를 문장으로 돌려준다 (웹 `actCoverage`, 서버 `validate_arc` 가 저장을 막는 경우).
    public static func coverage(_ acts: [Act], start: Int, end: Int) -> [String] {
        var out: [String] = []
        let short = end - start + 1 < 4  // 4화보다 짧으면 이웃 구간이 한 화를 함께 써도 된다
        var hits: [Int: Int] = [:]
        for a in acts {
            var n = a.startEp
            while n <= a.endEp && n - a.startEp < 2000 { hits[n, default: 0] += 1; n += 1 }
        }
        var gap: [Int] = []
        var twice: [Int] = []
        if start <= end {
            for n in start...end {
                if hits[n] == nil { gap.append(n) } else if hits[n]! > 1 && !short { twice.append(n) }
            }
        }
        let beyond = hits.keys.filter { $0 < start || $0 > end }.sorted()
        if !gap.isEmpty { out.append("어느 구간에도 들지 않는 화: \(rangeText(gap))화") }
        if !twice.isEmpty { out.append("두 구간에 겹친 화: \(rangeText(twice))화") }
        if !beyond.isEmpty { out.append("범위(\(start)~\(end)화) 밖: \(rangeText(beyond))화") }
        return out
    }

    /// 화마다 소속 구간을 정하는 기승전결 목록. 단편은 작품 전체 구조, 장편은 아크들의 구간 (웹 `beats`).
    static func beats(_ p: Project) -> [Act] {
        guard p.meta?.form == .serial else { return p.arc ?? [] }
        return arcs(p).flatMap { $0.acts ?? [] }
    }

    /// 아크를 시작 화 순으로.
    public static func arcs(_ p: Project) -> [StoryArc] {
        (p.storyArcs ?? []).sorted { $0.startEp < $1.startEp }
    }

    static func act(of n: Int, _ p: Project) -> Act? { beats(p).first { $0.startEp <= n && n <= $0.endEp } }
    static func arc(of n: Int, _ p: Project) -> StoryArc? { (p.storyArcs ?? []).first { $0.startEp <= n && n <= $0.endEp } }
    /// 장편에서 아크를 기획해 둔 마지막 화 (웹 `plannedUntil`).
    static func plannedUntil(_ p: Project) -> Int { (p.storyArcs ?? []).map(\.endEp).max() ?? 0 }

    /// 지금 작업해야 할 화: 반영이 끝나지 않은 첫 화 (웹 `currentEp`).
    static func currentEp(_ eps: [Episode]) -> Int {
        guard let last = eps.last else { return 1 }
        return eps.first { status($0) != .finalized }?.plot.number ?? last.plot.number
    }

    /// start~end 화 중 플롯 초안 작업이 새로 만들 화가 있다: 없는 화나 초안 (웹 `needsDraft`, 서버 `web._plot_ranges`).
    static func needsDraft(_ eps: [Episode], _ start: Int, _ end: Int) -> Bool {
        guard start <= end else { return false }
        return (start...end).contains { n in eps.first { $0.plot.number == n }.map { status($0) == .draft } ?? true }
    }

    /// 초안을 다시 만들면 사라지는 손본 초안을 알리는 물음. 바뀔 초안이 없으면 nil (웹 `confirmRedraft`).
    static func redraftQuestion(_ eps: [Episode]) -> String? {
        let nums = eps.filter { status($0) == .draft }.map(\.plot.number)
        guard !nums.isEmpty else { return nil }
        return "초안 \(nums.count)화(\(rangeText(nums))화)를 AI 새 초안으로 바꿔요. 손본 내용도 사라져요. 지키려면 먼저 그 화를 확정하세요. 계속할까요?"
    }

    /// 확정해 둔 다음 쓸 화. 장편은 그 아크 안의 화일 때만 (웹 `writeNextBtn`).
    static func writeNext(_ p: Project, arc: StoryArc? = nil) -> Int? {
        let eps = p.episodes ?? []
        let n = currentEp(eps)
        guard let e = eps.first(where: { $0.plot.number == n }), status(e) == .confirmed else { return nil }
        if let arc, n < arc.startEp || n > arc.endEp { return nil }
        return n
    }

    // MARK: 장편: 부 · 아크

    /// 그 범위의 화가 모두 반영됐다 (웹 `arcFinished`).
    static func finished(_ p: Project, _ start: Int, _ end: Int) -> Bool {
        guard start <= end else { return true }
        let eps = p.episodes ?? []
        return (start...end).allSatisfy { n in eps.first { $0.plot.number == n }.map { status($0) == .finalized } ?? false }
    }

    public struct Progress: Equatable, Sendable {
        public let count: Int
        public let plotted: Int
        public let done: Int
        public let drafts: Int
    }

    /// 아크의 화 수, 플롯이 있는 화, 반영한 화, 초안 (웹 `arcProgress`).
    static func progress(_ p: Project, _ a: StoryArc) -> Progress {
        let inArc = (p.episodes ?? []).filter { $0.plot.number >= a.startEp && $0.plot.number <= a.endEp }
        return Progress(count: a.endEp - a.startEp + 1, plotted: inArc.count,
                        done: inArc.filter { status($0) == .finalized }.count, drafts: inArc.filter { status($0) == .draft }.count)
    }

    /// 요약이 있는 부에 든 아크. 부 요약이 대신 들어가 따로 요약할 필요가 없다.
    static func inSummedPart(_ p: Project, _ a: StoryArc) -> Bool {
        (p.parts ?? []).contains { !($0.summary ?? "").isEmpty && $0.startEp <= a.startEp && a.startEp <= $0.endEp }
    }

    /// 요약이 필요한 끝난 아크와 부 (웹 `viewSerial` 의 `pending` · `partsPending`, 서버 `pipeline.pending_recaps`).
    static func pendingRecaps(_ p: Project) -> (arcs: [StoryArc], parts: [Part]) {
        let arcs = arcs(p).filter { ($0.summary ?? "").isEmpty && finished(p, $0.startEp, $0.endEp) && !inSummedPart(p, $0) }
        let parts = (p.parts ?? []).filter { ($0.summary ?? "").isEmpty && finished(p, $0.startEp, $0.endEp) }
        return (arcs, parts)
    }

    /// 아크 칩의 상태와 글자 (웹 `arcChip`).
    static func arcChip(_ p: Project, _ a: StoryArc) -> (status: EpisodeStatus?, label: String) {
        let g = progress(p, a)
        let summary = !(a.summary ?? "").isEmpty
        let folded = g.done == g.count && !summary && inSummedPart(p, a)
        if g.done == g.count {
            return (summary || folded ? .finalized : .written, summary ? "완료" : folded ? "부 요약에 포함" : "요약 필요")
        }
        if g.plotted == 0 { return (nil, "플롯 전") }
        return (g.drafts > 0 ? .draft : .confirmed, "반영 \(g.done)/\(g.count)")
    }

    /// 아크 줄: 끝났고 요약도 있는 앞쪽 아크가 셋보다 많으면 한 칩으로 접는다. 고른 아크는 늘 보인다 (웹 `railChips`).
    /// 접은 아크 수와 보일 아크. 접지 않으면 `folded` 가 nil.
    static func rail(_ p: Project, selected: Int?, all: Bool) -> (folded: (first: Int, last: Int, count: Int)?, shown: [StoryArc]) {
        let arcs = arcs(p)
        var k = 0
        while k < arcs.count && !(arcs[k].summary ?? "").isEmpty && finished(p, arcs[k].startEp, arcs[k].endEp) { k += 1 }
        if all || k <= 3 { return (nil, arcs) }
        let head = arcs[..<k]
        return ((arcs[0].number, arcs[k - 1].number, head.filter { $0.number != selected }.count),
                head.filter { $0.number == selected } + arcs[k...])
    }

    /// 부 구성 제안을 반영하면 사라질 부 요약: 요약이 있는데 같은 범위의 부가 제안에 없다 (웹 `lostPartSummaries`, 서버 `pipeline.apply_series`).
    static func lostPartSummaries(_ p: Project, _ draft: SeriesPlan) -> [Part] {
        let keep = Set(draft.parts.map { "\($0.startEp)-\($0.endEp)" })
        return (p.parts ?? []).filter { !($0.summary ?? "").isEmpty && !keep.contains("\($0.startEp)-\($0.endEp)") }
    }

    // MARK: 화 끼워 넣기 · 빼기 (insert.js)

    /// 번호를 옮길 수 없는 마지막 화: 본문이 있거나 상태를 반영한 화 (웹 `lastFixed`, 서버 `renumber.last_fixed`).
    static func lastFixed(_ p: Project) -> Int {
        var n = 0
        for e in p.episodes ?? [] {
            let s = status(e)
            if !(e.text ?? "").isEmpty || s == .written || s == .finalized || e.candidate != nil { n = max(n, e.plot.number) }
        }
        for x in (p.history ?? []).map(\.episode) + (p.snapshots ?? []).map(\.episode) + (p.events ?? []).map(\.episode) { n = max(n, x) }
        return n
    }

    /// 그 화 플롯 편집기에서 보일 넣기 · 빼기 자리 (웹 `insertBlock`). 안 쓴 화는 앞에 넣기 · 빼기, 마지막 화는 뒤에 넣기.
    static func insertSlots(_ p: Project, _ n: Int) -> (before: Bool, after: Bool) {
        let free = lastFixed(p) + 1
        let lastPlotted = (p.episodes ?? []).map(\.plot.number).max() ?? 0
        return (n >= free, n == lastPlotted && n + 1 >= free)
    }

    /// 새 화 넣기 양식의 안내 (웹 `insertForm`).
    static func insertNote(_ p: Project, at: Int) -> String {
        let moved = (p.episodes ?? []).map(\.plot.number).filter { $0 >= at }
        guard let first = moved.first, let last = moved.last else { return "마지막 화 뒤에 붙여요. 마지막 구간이 한 화 늘어나요. 총 화수가 1 늘어요." }
        return "지금 \(first)~\(last)화가 \(first + 1)~\(last + 1)화로 밀려요. 플롯과 확정 상태는 그대로이고, 구간 · 아크 범위와 복선 · 인과율 요소 · 이야기 줄기의 화 번호도 함께 옮겨요. 총 화수가 1 늘어요."
    }
}
