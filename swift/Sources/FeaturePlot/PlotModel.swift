import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

public typealias EpisodePlot = Components.Schemas.EpisodePlot

/// 기승전결 · 플롯 화면 (장편은 부 · 아크 · 플롯). 웹 `viewArc` · `viewSerial` · `insert.js` 와 그 동작.
/// 작품은 `ProjectDocument` 를 다른 화면과 함께 쓰고, AI 작업은 `JobCenter` 로 시작하고 결과를 받는다.
/// AI 결과는 제안으로만 두고, 사용자가 고르거나 고친 것만 적용한다.
@MainActor
@Observable
public final class PlotModel {
    /// 오른쪽 편집 칸에 연 것.
    public enum Panel: Equatable, Sendable {
        case episode(Int)
        /// 구간 목록의 자리. 장편은 고른 아크의 구간
        case act(Int)
        /// 장편: 고른 아크 고치기
        case arc
        case part(Int)
    }

    /// 장편 아크 줄에서 고른 것.
    public enum ArcPick: Hashable, Sendable {
        case arc(Int)
        case next
    }

    /// 되묻는 물음. 화면은 `button` 을 누르면 `run` 을 부른다.
    public struct Ask: Identifiable {
        public let id = UUID()
        public let message: String
        public let button: String
        public let destructive: Bool
        public let run: @MainActor () async -> Void
    }

    /// 새 화 넣기 양식 (웹 `S.insForm`).
    public struct InsertForm: Equatable, Sendable {
        public var at: Int
        public var title = ""
        public var summary = ""
        public var storyline = ""
        /// 넣은 뒤 AI가 앞뒤 화에 맞춰 플롯 채우기
        public var ai = true
    }

    /// 아크 · 부 요약 제안 (웹 `S.recapDrafts`). 열쇠는 'arc3', 'part2'.
    public struct RecapDraft: Equatable, Sendable {
        /// "arc" 나 "part"
        public let kind: String
        public let number: Int
        public var summary: String
    }

    public let document: ProjectDocument
    public let jobs: JobCenter
    let service: any PlotService

    public var panel: Panel?
    public var arcPick: ArcPick?
    /// 장편: 접은 앞쪽 아크를 펼쳤다
    public var railAll = false
    /// 구조 · 부 구성 · 초안을 다시 받을 때 함께 보낼 한 줄 요청 (웹 `S.planNote`)
    public var planNote = ""
    /// 구조 제안 (적용 전). 지금 구조와 나란히 보이고 고르면 바뀐다
    public var arcProposal: [Act]?
    public var seriesDraft: SeriesPlan?
    public var arcDraft: ArcProposal?
    public var recapDrafts: [String: RecapDraft] = [:]
    /// 다음 아크 기획: 길이(0 이면 AI가 정함)와 바라는 것
    public var arcLength = 0
    public var arcNote = ""
    public var insForm: InsertForm?
    public var ask: Ask?
    public private(set) var notice: (text: String, isError: Bool)?
    public private(set) var busy = false
    /// 제안으로 받아 둔 작업 결과 id
    private var adopted: Set<String> = []
    private var synced = false

    public init(document: ProjectDocument, jobs: JobCenter, service: any PlotService) {
        self.document = document
        self.jobs = jobs
        self.service = service
    }

    public var project: Project? { document.project }
    public var serial: Bool { document.serial }
    public func dismissNotice() { notice = nil }

    // MARK: 고른 것

    /// 장편에서 보일 아크. 고르지 않았으면 지금 화의 아크, 없으면 마지막 아크, 없으면 다음 아크 (웹 `viewSerial`).
    public var selectedArc: ArcPick {
        guard let p = project else { return .next }
        let arcs = PlotRules.arcs(p)
        if let pick = arcPick, pick == .next || arcs.contains(where: { .arc($0.number) == pick }) { return pick }
        if let cur = PlotRules.arc(of: PlotRules.currentEp(p.episodes ?? []), p) { return .arc(cur.number) }
        return arcs.last.map { .arc($0.number) } ?? .next
    }

    public var currentArc: StoryArc? {
        guard case let .arc(n) = selectedArc else { return nil }
        return project?.storyArcs?.first { $0.number == n }
    }

    /// 지금 화면의 구간 목록: 단편은 작품 구조, 장편은 고른 아크의 구간.
    public var acts: [Act] {
        serial ? currentArc?.acts ?? [] : project?.arc ?? []
    }

    public func select(_ panel: Panel?) { self.panel = panel }

    public func pickArc(_ pick: ArcPick) {
        arcPick = pick
        panel = nil
    }

    /// 열린 화 · 구간이 사라졌으면 닫는다 (웹 `viewArc` 첫 줄).
    public func tidy() {
        guard let p = project else { return }
        switch panel {
        case let .episode(n) where !(p.episodes ?? []).contains(where: { $0.plot.number == n }): panel = nil
        case let .act(i) where !acts.indices.contains(i): panel = nil
        case let .part(n) where !(p.parts ?? []).contains(where: { $0.number == n }): panel = nil
        case .arc where currentArc == nil: panel = nil
        default: break
        }
    }

    // MARK: 작업 결과

    /// 끝난 작업 결과를 제안으로 받아 둔다 (웹 `applyJobResult` · `loadPending`). 작품을 열 때 되살린 결과는 고른 화 · 아크를 옮기지 않는다.
    public func syncResults() {
        let move = synced
        synced = true
        for r in jobs.results.values.sorted(by: { $0.key < $1.key }) where !adopted.contains(r.id) {
            switch r.kind {
            case "arc":
                guard let v = try? r.result.decode(ArcPlan.self) else { continue }
                arcProposal = v.acts
            case "series":
                guard let v = try? r.result.decode(SeriesPlan.self) else { continue }
                seriesDraft = v
            case "nextarc":
                guard let v = try? r.result.decode(ArcProposal.self) else { continue }
                arcDraft = v
                if move { pickArc(.next) }
            case "recap_arc", "recap_part":
                guard let ep = r.ep, let v = try? r.result.decode(Recap.self) else { continue }
                let kind = String(r.kind.dropFirst("recap_".count))
                recapDrafts[kind + "\(ep)"] = RecapDraft(kind: kind, number: ep, summary: v.summary)
                if move { if kind == "arc" { pickArc(.arc(ep)) } else { panel = .part(ep) } }
            default:
                continue
            }
            adopted.insert(r.id)
        }
    }

    /// 이 화면에서 볼 만한 지난 실패 (웹 `failStrip` 의 'arc' 화면).
    public var failures: [PendingFailure] {
        let kinds: Set<String> = ["arc", "plots", "plot_one", "series", "nextarc", "recap_arc", "recap_part"]
        return jobs.failures.values.filter { kinds.contains($0.kind) }.sorted { $0.key < $1.key }
    }

    /// 실패한 작업을 다시 시작한다 (요청 글은 지금 칸의 것).
    public func retry(_ f: PendingFailure) async {
        await jobs.dismissFailure(f.key)
        var r = JobRequest(kind: f.kind, ep: f.ep)
        if ["arc", "series", "plots"].contains(f.kind) { r.note = planNote }
        if f.kind == "nextarc" { r.length = arcLength; r.note = arcNote }
        await start(r)
    }

    // MARK: 작업 시작

    /// 작업을 시작한다. 저장하지 않은 변경이 있으면 먼저 묻는다 (웹 `startJob`).
    public func start(_ request: JobRequest, asked: Bool = false) async {
        if document.dirty && !asked {
            ask = Ask(message: "저장하지 않은 변경이 있어요. 저장하고 작업을 시작할까요?", button: "저장하고 시작", destructive: false) { [weak self] in
                await self?.start(request, asked: true)
            }
            return
        }
        await jobs.start(request)
    }

    /// 묻고 나서 작업을 시작한다. 저장하지 않은 변경이 있으면 같은 물음에 덧붙인다.
    private func askThenStart(_ message: String, button: String, _ request: JobRequest) {
        let tail = document.dirty ? " 저장하지 않은 변경도 먼저 저장해요." : ""
        ask = Ask(message: message + tail, button: button, destructive: false) { [weak self] in
            await self?.start(request, asked: true)
        }
    }

    private func noted(_ kind: String, ep: Int? = nil) -> JobRequest {
        var r = JobRequest(kind: kind, ep: ep)
        r.note = planNote.trimmingCharacters(in: .whitespacesAndNewlines)
        return r
    }

    /// 구조 제안 받기. 도착하면 지금 구조와 비교하는 카드로 보인다 (웹 `planArc`).
    public func planArc() async { await start(noted("arc")) }

    /// 화별 플롯 초안. 장편은 그 아크만. 확정하지 않은 초안이 바뀌면 먼저 묻는다 (웹 `draftPlots` · `draftArcPlots`).
    public func draftPlots(arc: Int? = nil) async {
        guard let p = project else { return }
        let a = arc.flatMap { n in p.storyArcs?.first { $0.number == n } }
        let eps = (p.episodes ?? []).filter { e in a.map { e.plot.number >= $0.startEp && e.plot.number <= $0.endEp } ?? true }
        let request = noted("plots", ep: arc)
        if let q = PlotRules.redraftQuestion(eps) {
            askThenStart(q, button: "초안 다시 만들기", request)
        } else {
            await start(request)
        }
    }

    /// 초안 화 하나를 앞뒤 화에 맞춰 AI로 채운다 (웹 `insDraft`).
    public func draftOne(_ n: Int) async { await start(JobRequest(kind: "plot_one", ep: n)) }

    public func planSeries() async {
        if !(project?.parts ?? []).isEmpty {
            askThenStart("지금 부 구성을 AI 제안으로 바꿀까요? 적용 전에 확인할 수 있어요.", button: "제안 받기", noted("series"))
        } else {
            await start(noted("series"))
        }
    }

    public func planNextArc() async {
        var r = JobRequest(kind: "nextarc")
        r.length = max(0, arcLength)
        r.note = arcNote.trimmingCharacters(in: .whitespacesAndNewlines)
        await start(r)
    }

    /// kind 는 "arc" 나 "part". 고치던 요약 제안이 있으면 먼저 묻는다.
    public func recap(_ kind: String, _ number: Int) async {
        let request = JobRequest(kind: "recap_" + kind, ep: number)
        if recapDrafts[kind + "\(number)"] != nil {
            let what = kind == "arc" ? "아크 \(number)" : "\(number)부"
            askThenStart("\(what) 요약 제안이 아직 있어요. 고친 내용을 버리고 새로 받을까요?", button: "새로 받기", request)
        } else {
            await start(request)
        }
    }

    /// 플롯 초안 작업이 아직 만들지 않은 화 (웹 `jobOwns`).
    public func owns(_ n: Int) -> Bool { jobs.owns(n) }

    /// 이 작품에서 도는 AI 작업이 있다. 화 번호를 옮기는 일은 그동안 막는다 (웹 `projectBusy`).
    public var projectBusy: Bool { jobs.jobs.contains { $0.isRunning && $0.project == document.name } }

    // MARK: 제안 적용 · 버리기

    private static func dropQuestion(_ what: String) -> String {
        "\(what)을 버릴까요? 되살릴 수 없어서, 다시 보려면 AI에게 다시 받아야 해요."
    }

    public func useArcProposal() async {
        guard let acts = arcProposal else { return }
        document.edit { $0.arc = acts }
        arcProposal = nil
        notice = ("구조를 바꿨어요. 저장하면 반영돼요", false)
        await jobs.drop("arc")
    }

    public func dropArcProposal() {
        ask = Ask(message: Self.dropQuestion("AI 구조 제안"), button: "버리기", destructive: true) { [weak self] in
            self?.arcProposal = nil
            await self?.jobs.drop("arc")
        }
    }

    /// AI 없이 총 화수를 기승전결 네 구간으로 나눈다 (웹 `splitArc`).
    public func splitArc() {
        guard let total = project?.meta?.targetEpisodes, let r = PlotRules.actRanges(total: total, start: 1) else {
            notice = ("총 화수를 먼저 정하세요", true)
            return
        }
        document.edit { p in
            p.arc = zip(PlotRules.actNames, r).map { Act(name: $0, startEp: $1.0, endEp: $1.1, goal: "", keyTurn: "", pov: "") }
        }
        panel = .act(0)
        notice = ("네 구간으로 나눴어요. 구간마다 목표를 적고 저장하세요", false)
    }

    public func dropSeries() {
        ask = Ask(message: Self.dropQuestion("AI 부 구성 제안"), button: "버리기", destructive: true) { [weak self] in
            self?.seriesDraft = nil
            await self?.jobs.drop("series")
        }
    }

    /// 부 구성 적용. 범위가 바뀌어 사라질 부 요약이 있으면 먼저 묻는다 (웹 `applySeries`).
    public func applySeries(asked: Bool = false) async {
        guard let draft = seriesDraft, let p = project else { return }
        let lost = PlotRules.lostPartSummaries(p, draft)
        if !lost.isEmpty && !asked {
            ask = Ask(message: "범위가 바뀌어 저장된 \(lost.map { "\($0.number)부" }.joined(separator: ", ")) 요약이 사라져요. 반영할까요?",
                      button: "반영", destructive: true) { [weak self] in await self?.applySeries(asked: true) }
            return
        }
        let had = !(p.storyArcs ?? []).isEmpty
        if await mutate({ try await self.service.applySeries(draft) }) {
            seriesDraft = nil
            await jobs.drop("series")
            notice = (had ? "부 구성을 바꿨어요. 아크와 반영한 화는 그대로예요." : "부 구성을 적용했어요. 이제 첫 아크를 기획하세요.", false)
        }
    }

    public func dropArc() {
        ask = Ask(message: Self.dropQuestion("AI 다음 아크 제안"), button: "버리기", destructive: true) { [weak self] in
            self?.arcDraft = nil
            await self?.jobs.drop("nextarc")
        }
    }

    public func applyArc() async {
        guard let draft = arcDraft else { return }
        if await mutate({ try await self.service.applyArc(draft) }) {
            arcPick = .arc(draft.arc.number)
            arcDraft = nil
            arcLength = 0
            arcNote = ""
            await jobs.drop("nextarc")
            notice = ("아크를 적용했어요. 화별 플롯 초안을 만드세요.", false)
        }
    }

    /// 다음 아크 제안의 끝 화를 바꾼다. 결 구간이 따라간다.
    public func setDraftEnd(_ end: Int) {
        guard arcDraft != nil else { return }
        PlotRules.setArcEnd(&arcDraft!.arc, end)
    }

    public func removeLastArc() {
        ask = Ask(message: "마지막 아크와 그 아크의 플롯 초안을 지울까요? 다시 기획할 수 있어요.", button: "지우기", destructive: true) { [weak self] in
            guard let self else { return }
            if await self.mutate({ try await self.service.removeLastArc() }) { self.arcPick = .next }
        }
    }

    public func dropRecap(_ key: String) {
        guard let r = recapDrafts[key] else { return }
        ask = Ask(message: Self.dropQuestion("AI 요약 제안"), button: "버리기", destructive: true) { [weak self] in
            self?.recapDrafts[key] = nil
            await self?.jobs.drop("recap_" + r.kind, ep: r.number)
        }
    }

    public func applyRecap(_ key: String) async {
        guard let r = recapDrafts[key] else { return }
        if await mutate({ try await self.service.applyRecap(kind: r.kind, number: r.number, summary: r.summary) }) {
            recapDrafts[key] = nil
            await jobs.drop("recap_" + r.kind, ep: r.number)
            notice = ("요약을 저장했어요. 앞으로 이 구간 대신 요약이 프롬프트에 들어가요.", false)
        }
    }

    // MARK: 확정

    public func confirm(_ n: Int) async {
        let before = project?.characters ?? []
        if await mutate({ try await self.service.confirm(n) }) { castAdded(before) }
    }

    public func unconfirm(_ n: Int) async {
        await mutate { try await self.service.unconfirm(n) }
    }

    /// 초안을 모두 확정한다. 장편은 그 아크 안만 (웹 `confirmAll`).
    public func confirmAll(arc: Int? = nil) {
        guard let p = project else { return }
        let a = arc.flatMap { n in p.storyArcs?.first { $0.number == n } }
        let drafts = (p.episodes ?? []).filter { e in
            PlotRules.status(e) == .draft && (a.map { e.plot.number >= $0.startEp && e.plot.number <= $0.endEp } ?? true)
        }.map(\.plot.number)
        if drafts.isEmpty { notice = ("확정할 초안이 없어요", false); return }
        if jobs.running("plots") != nil { notice = ("플롯 초안을 만드는 중이에요. 끝난 뒤에 확정하세요", true); return }
        ask = Ask(message: "초안 \(drafts.count)화를 모두 확정할까요?", button: "모두 확정", destructive: false) { [weak self] in
            guard let self else { return }
            let before = self.project?.characters ?? []
            if await self.mutate({ for n in drafts { try await self.service.confirm(n) } }) { self.castAdded(before) }
        }
    }

    /// 화를 확정하면 그 화에 나오는 새 인물 후보도 등록된다 (웹 `castAddedToast`).
    private func castAdded(_ before: [Character]) {
        let added = (project?.characters ?? []).filter { c in !before.contains { $0.id == c.id } }
        if !added.isEmpty { notice = ("새 인물도 등록했어요: \(added.map { $0.name.isEmpty ? $0.id : $0.name }.joined(separator: ", "))", false) }
    }

    // MARK: 화 끼워 넣기 · 빼기

    public func openInsert(at: Int) { insForm = InsertForm(at: at) }

    public func submitInsert() async {
        guard let f = insForm else { return }
        var notes: [String] = []
        let ok = await mutate {
            notes = try await self.service.insert(at: f.at, title: f.title, summary: f.summary, storyline: f.storyline)
        }
        guard ok else { return }
        insForm = nil
        panel = .episode(f.at)
        notice = (notes.joined(separator: " "), false)
        if f.ai { await start(JobRequest(kind: "plot_one", ep: f.at)) }
    }

    public func removeEpisode(_ n: Int) {
        let title = project?.episodes?.first { $0.plot.number == n }?.plot.title ?? ""
        ask = Ask(message: "\(n)화 '\(title.isEmpty ? "제목 없음" : title)' 플롯을 빼고 뒤 화를 한 칸씩 당길까요? 뺀 화의 플롯은 되돌릴 수 없어요.",
                  button: "\(n)화 빼기", destructive: true) { [weak self] in
            guard let self else { return }
            var notes: [String] = []
            if await self.mutate({ notes = try await self.service.remove(n) }) {
                self.panel = nil
                self.notice = (notes.joined(separator: " "), false)
            }
        }
    }

    // MARK: 고치기

    public func editPlot(_ n: Int, _ change: (inout EpisodePlot) -> Void) {
        document.edit { p in
            guard let i = p.episodes?.firstIndex(where: { $0.plot.number == n }) else { return }
            change(&p.episodes![i].plot)
        }
    }

    /// 구간 고치기. 장편은 고른 아크의 구간.
    public func editAct(_ i: Int, _ change: (inout Act) -> Void) {
        let arcNumber = serial ? currentArc?.number : nil
        document.edit { p in
            if let n = arcNumber {
                guard let k = p.storyArcs?.firstIndex(where: { $0.number == n }), p.storyArcs![k].acts?.indices.contains(i) == true else { return }
                change(&p.storyArcs![k].acts![i])
            } else {
                guard p.arc?.indices.contains(i) == true else { return }
                change(&p.arc![i])
            }
        }
    }

    public func editArc(_ number: Int, _ change: (inout StoryArc) -> Void) {
        document.edit { p in
            guard let k = p.storyArcs?.firstIndex(where: { $0.number == number }) else { return }
            change(&p.storyArcs![k])
        }
    }

    public func editPart(_ number: Int, _ change: (inout Part) -> Void) {
        document.edit { p in
            guard let k = p.parts?.firstIndex(where: { $0.number == number }) else { return }
            change(&p.parts![k])
        }
    }

    /// 회수할 복선 고르기 (웹 `payoffPicker`).
    public func togglePayoff(_ n: Int, _ id: String, _ on: Bool) {
        editPlot(n) { plot in
            var list = plot.foreshadowPayoff ?? []
            list.removeAll { $0 == id }
            if on { list.append(id) }
            plot.foreshadowPayoff = list
        }
    }

    public func toggleArcPayoff(_ number: Int, _ id: String, _ on: Bool) {
        editArc(number) { a in
            var list = a.payoffs ?? []
            list.removeAll { $0 == id }
            if on { list.append(id) }
            a.payoffs = list
        }
    }

    public func toggleCast(_ n: Int, _ id: String, _ on: Bool) {
        editPlot(n) { plot in
            plot.characters.removeAll { $0 == id }
            if on { plot.characters.append(id) }
        }
    }

    // MARK: 서버에 시키기

    /// 저장하지 않은 변경을 먼저 저장하고(웹 `saveIfDirty`) 서버에 시킨 뒤 작품을 다시 받는다.
    @discardableResult
    private func mutate(_ op: @escaping () async throws -> Void) async -> Bool {
        busy = true
        defer { busy = false }
        if document.dirty {
            await document.save()
            if document.dirty { return false }
        }
        do {
            try await op()
        } catch {
            notice = (CanonError.message(error), true)
            await document.load()
            return false
        }
        await document.load()
        return true
    }
}
