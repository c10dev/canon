import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

/// 이야기 줄기 화면 (웹 `viewLines` 와 그 동작). 줄기 고치기와 화 붙이기는 연 작품(`ProjectDocument`)을 고치고 저장 띠로 저장한다.
/// AI 제안은 작업 `storyline` 의 결과(`jobs.results["storyline:"]`)를 제안으로 두고, 사용자가 고친 뒤 고른 화와 함께 적용한다.
@MainActor
@Observable
public final class LinesModel {
    /// 되묻는 물음. 화면은 `button` 을 누르면 `run` 을 부른다.
    public struct Ask: Identifiable {
        public let id = UUID()
        public let message: String
        public let button: String
        public let destructive: Bool
        public let run: @MainActor () async -> Void
    }

    /// AI 제안 (웹 `S.lineDraft`). 화마다 고른 것 (기본은 모두 고름).
    public struct Draft: Equatable, Sendable {
        public var proposal: StorylineProposal
        /// 끈 화. 열쇠는 'main:7', 'thread:8'
        public var unpicked: Set<String> = []

        public init(_ proposal: StorylineProposal) { self.proposal = proposal }

        public func picked(_ role: LineRules.Role, _ n: Int) -> Bool { !unpicked.contains("\(role.rawValue):\(n)") }

        public mutating func pick(_ role: LineRules.Role, _ n: Int, _ on: Bool) {
            if on { unpicked.remove("\(role.rawValue):\(n)") } else { unpicked.insert("\(role.rawValue):\(n)") }
        }

        public var episodes: [Int] { (proposal.episodes ?? []).filter { picked(.main, $0) } }
        public var threads: [Int] { (proposal.threads ?? []).filter { picked(.thread, $0) } }
    }

    public static let jobKind = "storyline"

    public let document: ProjectDocument
    public let jobs: JobCenter
    let service: any LinesService

    /// 고른 줄기 id (웹 `S.lineSel`)
    public var selection: String?
    public var draft: Draft?
    /// AI에게 바라는 것과 종류 (웹 `S.lineForm`). 종류가 nil 이면 AI가 고른다
    public var note = ""
    public var aiKind: StorylineKind?
    public var zoom: LineMapLayout.Zoom = .fit
    /// 붙일 화 번호 칸 (웹 `#line-tag-eps`)
    public var tagText = ""
    public var ask: Ask?
    public private(set) var notice: (text: String, isError: Bool)?
    public private(set) var busy = false
    private var adopted: Set<String> = []

    public init(document: ProjectDocument, jobs: JobCenter, service: any LinesService) {
        self.document = document
        self.jobs = jobs
        self.service = service
    }

    public var project: Project? { document.project }
    public var lines: [Storyline] { project.map(LineRules.lines) ?? [] }
    public func dismissNotice() { notice = nil }

    /// 고른 줄기. 고른 것이 없어졌으면 첫 줄기 (웹 `viewLines` 첫 줄).
    public var selected: Storyline? {
        if let id = selection, let s = lines.first(where: { $0.id == id }) { return s }
        return lines.first
    }

    public func select(_ id: String) {
        selection = id
        tagText = ""
    }

    // MARK: 줄기 고치기

    /// 고른 줄기를 고친다. 저장 띠로 저장한다.
    public func edit(_ change: (inout Storyline) -> Void) {
        guard let id = selected?.id else { return }
        document.edit { p in
            guard let i = p.storylines?.firstIndex(where: { $0.id == id }) else { return }
            change(&p.storylines![i])
        }
    }

    /// 빈 줄기를 더하고 고른다 (웹 `lineNew`).
    public func newLine() {
        guard let p = project else { return }
        let s = LineRules.blank(p)
        document.edit { $0.storylines = ($0.storylines ?? []) + [s] }
        select(s.id)
    }

    public func toggleFocus(_ character: String) {
        edit { s in
            var f = s.focus ?? []
            if f.contains(character) { f.removeAll { $0 == character } } else { f.append(character) }
            s.focus = f
        }
    }

    /// 지우기: 묻고, 저장하지 않은 변경을 먼저 저장한 뒤 서버가 지우고 붙은 화를 메인으로 돌린다 (웹 `lineDelete`).
    public func delete() {
        guard let s = selected else { return }
        ask = Ask(message: LineRules.deleteQuestion(s), button: "지우기", destructive: true) { [weak self] in
            guard let self else { return }
            if await self.mutate({ try await self.service.remove(s.id) }) { self.selection = nil }
        }
    }

    // MARK: 화 붙이기

    /// 칸에 적은 화를 고른 줄기에 붙인다 (웹 `lineTag`). 플롯이 없는 화가 있으면 붙이지 않는다.
    public func tag(_ role: LineRules.Role) {
        guard let s = selected, let p = project else { return }
        let eps = LineRules.parseEpisodes(tagText)
        if eps.isEmpty { notice = ("붙일 화 번호를 적으세요", true); return }
        let have = Set((p.episodes ?? []).map(\.plot.number))
        let missing = eps.filter { !have.contains($0) }
        if !missing.isEmpty {
            notice = ("플롯이 없는 화예요: \(missing.map(String.init).joined(separator: ", "))화", true)
            return
        }
        document.edit { p in
            for i in (p.episodes ?? []).indices where eps.contains(p.episodes![i].plot.number) {
                LineRules.tag(&p.episodes![i].plot, s.id, role)
            }
        }
        tagText = ""
    }

    /// n화를 고른 줄기에서 뺀다 (웹 `lineUntag`).
    public func untag(_ n: Int) {
        guard let id = selected?.id else { return }
        document.edit { p in
            guard let i = p.episodes?.firstIndex(where: { $0.plot.number == n }) else { return }
            LineRules.untag(&p.episodes![i].plot, id)
        }
    }

    // MARK: AI 제안

    /// 끝난 작업 결과를 제안으로 받아 둔다 (웹 `applyJobResult` 의 storyline). 같은 결과를 두 번 받지 않는다.
    public func syncResults() {
        guard let r = jobs.results[Job.key(Self.jobKind, nil)], !adopted.contains(r.id),
              let v = try? r.result.decode(StorylineProposal.self) else { return }
        adopted.insert(r.id)
        draft = Draft(v)
    }

    public var busyLabel: String? { jobs.busyLabel(Self.jobKind) }

    /// 이 화면에서 볼 만한 지난 실패.
    public var failure: PendingFailure? { jobs.failures[Job.key(Self.jobKind, nil)] }

    /// AI 제안 받기 (웹 `lineSuggest`). 저장하지 않은 변경은 `JobCenter.start` 가 먼저 저장한다.
    public func suggest() async {
        var r = JobRequest(kind: Self.jobKind)
        r.note = note.trimmingCharacters(in: .whitespacesAndNewlines)
        r.lineKind = aiKind?.rawValue ?? ""
        if document.dirty {
            ask = Ask(message: "저장하지 않은 변경이 있어요. 저장하고 작업을 시작할까요?", button: "저장하고 시작", destructive: false) { [weak self] in
                await self?.jobs.start(r)
            }
            return
        }
        await jobs.start(r)
    }

    public func retry() async {
        guard let f = failure else { return }
        await jobs.dismissFailure(f.key)
        await suggest()
    }

    public func dismissFailure() async {
        guard let f = failure else { return }
        await jobs.dismissFailure(f.key)
    }

    public func editDraft(_ change: (inout Storyline) -> Void) {
        guard draft != nil else { return }
        change(&draft!.proposal.storyline)
    }

    /// 버리기: 묻고, 서버의 검토 대기에서도 지운다 (웹 `lineDrop`).
    public func dropDraft() {
        ask = Ask(message: "AI 이야기 줄기 제안을 버릴까요? 되살릴 수 없어서, 다시 보려면 AI에게 다시 받아야 해요.", button: "버리기", destructive: true) { [weak self] in
            self?.draft = nil
            await self?.jobs.drop(Self.jobKind)
        }
    }

    /// 고른 화와 함께 줄기를 더한다 (웹 `lineApply`). 플롯 내용은 바꾸지 않는다.
    public func applyDraft() async {
        guard let d = draft else { return }
        if (d.proposal.storyline.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            notice = ("줄기 이름을 적으세요", true)
            return
        }
        if await mutate({ try await self.service.apply(d.proposal, episodes: d.episodes, threads: d.threads) }) {
            selection = lines.last?.id
            draft = nil
            await jobs.drop(Self.jobKind)
            notice = ("줄기를 더했어요. 기승전결 · 플롯 화면에서 그 화들을 다듬으세요.", false)
        }
    }

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
