import CanonAPI
import CanonCore
import Observation

public typealias Project = Components.Schemas.Project

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

    /// 저장한다. `force` 는 다른 화면이 먼저 저장했어도 덮는다. 화면이 고친 칸을 서버가 지켰으면 false.
    @discardableResult
    public func save(merged: [String] = [], force: Bool = false) async -> Bool {
        guard let sent = project else { return false }
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
