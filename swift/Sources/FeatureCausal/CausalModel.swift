import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

/// 인과율 화면이 서버에 보내는 것. 시험에서는 가짜로 바꾼다.
public protocol CausalService: Sendable {
    /// 요소마다 관련 화 지도 (`GET .../elements/links`).
    func links(_ project: String) async throws -> [String: [ElementLink]]
    /// 고른 부분만 적용한다 (`POST .../elements/{id}/impact/apply`).
    func apply(_ project: String, element: String, _ body: Components.Schemas.ImpactApply) async throws -> Project
    /// 분석을 버린다 (`.../impact/dismiss`).
    func dismiss(_ project: String, element: String) async throws -> Project
    /// 버린 분석을 다시 연다 (`.../impact/reopen`).
    func reopen(_ project: String, element: String) async throws -> Project
    /// 저장된 작품 (분석 결과만 받아 올 때).
    func load(_ project: String) async throws -> Project
}

/// 인과율 화면 상태 (웹 `viewCausal`). 요소는 작가 입력이라 연 작품(`ProjectDocument`)을 고치고 작품 저장으로 저장한다.
/// 영향 분석은 작업(`impact`)이 서버의 요소에 붙이므로, 작업이 끝나면 분석만 받아 온다 (웹 `mergeImpacts`).
@MainActor
@Observable
public final class CausalModel {
    public let document: ProjectDocument
    public let jobs: JobCenter
    /// 고른 요소 id.
    public private(set) var selected: String?
    /// 종류 거르기. nil 이면 전부.
    public var kindFilter: StoryElement.KindPayload?
    public private(set) var links: [String: [ElementLink]] = [:]
    /// 체크 ('요소:분석시각:ep:3' → 적용할지, `CausalText.pickID`).
    public private(set) var picks: [String: Bool] = [:]
    /// 방금 지운 요소. 되살릴 수 있다.
    public private(set) var gone: StoryElement?
    public private(set) var busy = false
    public private(set) var notice: (text: String, isError: Bool)?
    private let service: any CausalService
    /// 이미 받아 온 끝난 분석 작업 id.
    private var mergedJobs: Set<String> = []

    public init(document: ProjectDocument, jobs: JobCenter, service: any CausalService, selected: String? = nil) {
        self.document = document
        self.jobs = jobs
        self.service = service
        self.selected = selected
    }

    public var project: Project? { document.project }
    public var elements: [StoryElement] { project?.elements ?? [] }
    public var element: StoryElement? { elements.first { $0.id == selected } }
    public var lastWritten: Int { project.map(CausalText.lastWritten) ?? 0 }

    /// 목록에 보일 요소 (종류 거르기).
    public var shown: [StoryElement] { elements.filter { kindFilter == nil || $0.kind ?? .기타 == kindFilter } }

    /// 거르기 단추: 종류가 둘 이상일 때만, 작품에 있는 종류만 순서대로 (웹 `causalList`).
    public var filterKinds: [StoryElement.KindPayload] {
        let have = Set(elements.map { $0.kind ?? .기타 })
        return have.count > 1 ? CausalText.kinds.filter(have.contains) : []
    }

    public var names: [String: String] {
        Dictionary((project?.characters ?? []).map { ($0.id, $0.name) }, uniquingKeysWith: { a, _ in a })
    }

    public var lineNames: [String: String] {
        Dictionary((project?.storylines ?? []).map { ($0.id, ($0.title ?? "").isEmpty ? $0.id : $0.title!) }, uniquingKeysWith: { a, _ in a })
    }

    /// 분석 버튼 글자. 분석이 돌면 nil 이 아닌 진행 글자 (웹 `jobFor('impact')`: 요소를 가리지 않는다).
    public var analyzing: String? {
        if let j = jobs.running("impact") { return "\(j.label) 중…" }
        return jobs.busyLabel("impact")
    }

    /// 작업 목록이 바뀔 때마다 화면이 부른다. 이 작품의 분석이 새로 끝났으면 분석을 받아 온다.
    public var impactJobsKey: [String] {
        jobs.jobs.filter { $0.kind == "impact" && $0.project == document.name }.map { "\($0.id):\($0.status.rawValue)" }
    }

    /// 관련 화 지도를 다시 받을 때: 요소가 더해지거나 빠질 때, 저장하거나 다시 불러와 저장된 작품이 바뀔 때.
    public var linksKey: String {
        "\(elements.map(\.id))|\(document.dirty)|\(document.busy)"
    }

    public func start() async {
        mergedJobs = Set(jobs.jobs.filter { $0.kind == "impact" && !$0.isRunning }.map(\.id))
        await mergeImpacts()
        fixSelection()
    }

    /// 고른 요소가 없거나 사라졌으면 첫 요소를 고른다.
    public func fixSelection() {
        if let s = selected, elements.contains(where: { $0.id == s }) { return }
        selected = elements.first?.id
        initPicks()
    }

    public func select(_ id: String) {
        selected = id
        initPicks()
    }

    public func dismissNotice() { notice = nil }

    // MARK: 요소 고치기

    /// 새 요소를 더한다. 바로 저장하지 않는다 (웹 `causalNew`).
    public func add() {
        let id = CausalText.newID(elements)
        let el = CausalText.blank(id: id, kind: kindFilter ?? .기타)
        document.edit { p in p.elements = (p.elements ?? []) + [el] }
        selected = id
    }

    /// 고른 요소를 고친다.
    public func edit(_ change: (inout StoryElement) -> Void) {
        guard let id = selected else { return }
        document.edit { p in
            guard let i = p.elements?.firstIndex(where: { $0.id == id }) else { return }
            change(&p.elements![i])
        }
    }

    public func setSince(start: Bool) {
        guard let el = element else { return }
        let n = CausalText.since(start: start, el, lastWritten: lastWritten)
        edit { $0.sinceEp = n }
    }

    public func toggleCharacter(_ cid: String) {
        edit { el in
            var cs = el.characters ?? []
            if let i = cs.firstIndex(of: cid) { cs.remove(at: i) } else { cs.append(cid) }
            el.characters = cs
        }
    }

    /// 지운다. 바로 저장한다 (웹 `causalDelete`). 저장하지 못하면 되살릴 것을 남기지 않는다.
    public func delete() async {
        guard let el = element else { return }
        document.edit { p in p.elements = (p.elements ?? []).filter { $0.id != el.id } }
        selected = nil
        await run {
            try await self.saveFirst()
            self.gone = el
            await self.loadLinks()
        }
        fixSelection()
    }

    public func restore() async {
        guard let el = gone else { return }
        document.edit { p in p.elements = (p.elements ?? []) + [el] }
        selected = el.id
        gone = nil
        await run {
            try await self.saveFirst()
            await self.loadLinks()
            self.notice = (CausalText.restored(el), false)
        }
    }

    // MARK: 영향 분석

    /// 분석을 시작한다. 저장하지 않은 변경은 `JobCenter.start` 가 먼저 저장한다 (서버는 저장된 요소를 본다).
    public func analyze() async {
        guard let el = element else { return }
        guard !(el.name ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !(el.description ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            notice = (CausalText.needNameAndDescription, true)
            return
        }
        var req = JobRequest(kind: "impact")
        req.element = el.id
        await jobs.start(req)
    }

    /// 작업 목록이 바뀌었다. 이 작품의 분석이 새로 끝났으면 받아 온다.
    public func jobsChanged() async {
        let finished = jobs.jobs.filter { $0.kind == "impact" && $0.project == document.name && $0.status == .done && !mergedJobs.contains($0.id) }
        guard !finished.isEmpty else { return }
        mergedJobs.formUnion(finished.map(\.id))
        await mergeImpacts()
    }

    /// 서버에 쓴 분석만 받아 온다. 저장하지 않은 요소 편집은 그대로 둔다 (웹 `mergeImpacts`).
    public func mergeImpacts() async {
        if !document.dirty {
            await document.load()
        } else if let fresh = try? await service.load(document.name) {
            let by = Dictionary((fresh.elements ?? []).map { ($0.id, $0.impact) }, uniquingKeysWith: { a, _ in a })
            document.edit { p in
                for i in (p.elements ?? []).indices {
                    if let imp = by[p.elements![i].id] { p.elements![i].impact = imp }
                }
            }
        }
        await loadLinks()
        initPicks()
    }

    public func loadLinks() async {
        if let l = try? await service.links(document.name) { links = l }
    }

    /// 처음 보는 분석의 체크를 놓는다. 이미 놓은 체크는 그대로 (웹 `initCausalPicks`).
    func initPicks() {
        guard let el = element, el.impact != nil, el.impact?.outcome ?? ._empty_ == ._empty_, let p = project else { return }
        for (k, v) in CausalText.defaultPicks(el, project: p) where picks[k] == nil { picks[k] = v }
    }

    public func isPicked(_ part: String) -> Bool {
        guard let el = element else { return false }
        return picks[CausalText.pickID(el, part)] == true
    }

    public func setPicked(_ part: String, _ on: Bool) {
        guard let el = element else { return }
        picks[CausalText.pickID(el, part)] = on
    }

    /// 고른 부분만 적용한다 (웹 `causalApply`).
    public func apply() async {
        guard let el = element, let p = project else { return }
        let body = CausalText.picked(el, picks: picks, project: p)
        guard !CausalText.isEmpty(body) else {
            notice = (CausalText.pickSomething, true)
            return
        }
        await change { try await self.service.apply(self.document.name, element: el.id, body) }
        if let imp = element?.impact, imp.outcome == .applied { notice = (CausalText.applied(imp), false) }
    }

    public func dismiss() async {
        guard let el = element else { return }
        await change { try await self.service.dismiss(self.document.name, element: el.id) }
    }

    public func reopen() async {
        guard let el = element else { return }
        await change { try await self.service.reopen(self.document.name, element: el.id) }
        initPicks()
    }

    /// 저장하지 않은 변경을 먼저 저장하고 보낸 뒤, 서버가 저장한 작품을 받는다.
    private func change(_ send: @escaping () async throws -> Project) async {
        await run {
            if self.document.dirty { try await self.saveFirst() }
            _ = try await send()
            await self.document.load()
            await self.loadLinks()
        }
    }

    /// 연 작품을 저장한다. 저장하지 못하면 (409 등) 저장 띠의 문구로 멈춘다. 서버가 지킨 칸이 있어도 저장은 됐다.
    private func saveFirst() async throws {
        if await document.save() || !document.dirty { return }
        throw CanonError.server(status: 0, message: document.error ?? "저장하지 못했어요", code: nil)
    }

    private func run(_ body: @escaping () async throws -> Void) async {
        busy = true
        defer { busy = false }
        do {
            try await body()
        } catch {
            notice = (CanonError.message(error), true)
        }
    }
}
