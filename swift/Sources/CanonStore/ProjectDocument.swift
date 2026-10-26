import CanonAPI
import CanonCore
import Observation

public typealias Project = Components.Schemas.Project
public typealias Episode = Components.Schemas.Episode

/// 작품 전체를 받고 저장하는 곳. 시험에서는 가짜로 바꾼다.
public protocol ProjectStoring: Sendable {
    func load(_ name: String) async throws -> Project
    func save(_ name: String, _ project: Project, merged: [String], force: Bool) async throws -> SaveResult
}

extension ProjectLoader: ProjectStoring {}

/// 열어 둔 작품 하나. 웹의 `S.project` · `S.dirty` · `S.conflict` · `save()` 와 같다.
/// 화면은 이것을 함께 쓰고, 고친 화면은 `edit` 로 고친 뒤 `save` 한다.
@MainActor
@Observable
public final class ProjectDocument {
    public let name: String
    public private(set) var project: Project?
    /// 저장하지 않은 변경이 있다.
    public private(set) var dirty = false
    /// 다른 탭이나 기기가 먼저 저장했다 (409). 다시 불러오기와 덮어쓰기 중에 고른다.
    public private(set) var conflict = false
    public private(set) var busy = false
    public private(set) var error: String?
    /// 저장 뒤 알림 (저장했어요, 서버 것으로 둔 칸).
    public private(set) var notice: (text: String, isError: Bool)?
    /// 작업 id → 이 화면이 결과를 받아 온 단계 수 (웹 `S.jobsMerged`). 저장할 때 도는 작업만 `<id>:<done>` 으로 알린다.
    public private(set) var mergedSteps: [String: Int] = [:]
    /// 지금 도는 작업 id. `JobCenter` 가 작업 목록을 받을 때마다 맞춘다.
    public var runningJobs: Set<String> = []
    private let store: any ProjectStoring
    /// 마지막으로 받은 작품. 서버가 지킨 칸을 이 화면이 고쳤는지 본다 (웹 `projectBase`).
    private var base: Project?

    public init(name: String, store: any ProjectStoring) {
        self.name = name
        self.store = store
    }

    public var serial: Bool { project?.meta?.form == .serial }

    /// 서버에서 받는다. 저장하지 않은 변경이 있으면 받지 않는다 (`reload` 는 버리고 받는다).
    public func load() async {
        if dirty { return }
        await fetch()
    }

    /// 저장하지 않은 변경을 버리고 다시 받는다.
    public func reload() async {
        dirty = false
        conflict = false
        await fetch()
    }

    public func edit(_ change: (inout Project) -> Void) {
        guard var p = project else { return }
        change(&p)
        project = p
        dirty = true
    }

    /// 저장할 때 서버에 알릴 '받아 온 작업 단계' (웹 `save` 의 `merged`).
    public var mergedArgument: [String] {
        mergedSteps.filter { runningJobs.contains($0.key) }.sorted { $0.key < $1.key }.map { "\($0.key):\($0.value)" }
    }

    /// 작업이 이 단계까지 쓴 결과를 받아 왔다.
    public func noteMerged(_ jobID: String, done: Int) {
        mergedSteps[jobID] = done
    }

    /// 작업이 project.json 에 쓴 화만 받아 온다 (웹 `mergeEpisodes`). `mine(화면 화, 서버 화)` 가 true 인 화와 새로 생긴 화.
    /// 저장하지 않은 변경이 없으면 작품을 통째로 바꾼다. 저장하지 않은 변경이 있을 때 서버 것으로 바꾼 화 번호를 돌려준다.
    @discardableResult
    public func merge(_ mine: (Episode, Episode) -> Bool) async -> [Int] {
        guard project != nil, let fresh = try? await store.load(name) else { return [] }
        guard dirty, var local = project else {
            project = fresh
            base = fresh
            return []
        }
        var byNumber = Dictionary(uniqueKeysWithValues: (local.episodes ?? []).map { ($0.plot.number, $0) })
        var baseEps = Dictionary(uniqueKeysWithValues: (base?.episodes ?? []).map { ($0.plot.number, $0) })
        var changed: [Int] = []
        for e in fresh.episodes ?? [] {
            let n = e.plot.number
            if let cur = byNumber[n], !mine(cur, e) { continue }
            if byNumber[n] != nil { changed.append(n) }
            byNumber[n] = e
            baseEps[n] = e
        }
        local.episodes = byNumber.keys.sorted().map { byNumber[$0]! }
        project = local
        base?.episodes = baseEps.keys.sorted().map { baseEps[$0]! }
        return changed
    }

    /// 저장한다. `force` 는 다른 화면이 먼저 저장했어도 덮는다. 화면이 고친 칸을 서버가 지켰으면 false.
    /// `merged` 를 주지 않으면 `mergedArgument` 를 보낸다.
    @discardableResult
    public func save(merged: [String]? = nil, force: Bool = false) async -> Bool {
        guard let sent = project else { return false }
        let merged = merged ?? mergedArgument
        busy = true
        defer { busy = false }
        do {
            let result = try await store.save(name, sent, merged: merged, force: force)
            project = result.project
            dirty = false
            conflict = false
            error = nil
            let old = base
            base = result.project
            let dropped = SaveText.dropped(result.kept) { Self.edited($0, sent: sent, base: old) }
            if let text = dropped {
                notice = (text, true)
            } else {
                notice = (SaveText.keptCharacters(result.kept) ?? SaveText.saved, false)
            }
            return dropped == nil
        } catch {
            conflict = (error as? CanonError)?.isConflict == true
            self.error = CanonError.message(error)
            return false
        }
    }

    public func dismissNotice() { notice = nil }

    private func fetch() async {
        busy = true
        defer { busy = false }
        do {
            let p = try await store.load(name)
            project = p
            base = p
            error = nil
        } catch {
            self.error = CanonError.message(error)
        }
    }

    /// 서버가 지킨 칸을 이 화면이 고쳤나. 처음 받은 작품을 모르면 고쳤다고 본다 (웹 `edited`).
    static func edited(_ k: KeptField, sent: Project, base: Project?) -> Bool {
        guard let base else { return true }
        if k.field == "relationships" { return sent.relationships != base.relationships }
        let plot = { (p: Project) in p.episodes?.first { $0.plot.number == k.ep }?.plot }
        return plot(sent) != plot(base)
    }
}
