import CanonAPI
import CanonCore
import CanonStore
import Foundation
@testable import FeatureWrite
import Testing

final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: Project
    var saved = 0

    init(_ project: Project) { self.project = project }

    func load(_ name: String) async throws -> Project { project }

    func save(_ name: String, _ p: Project, merged: [String], force: Bool) async throws -> SaveResult {
        saved += 1
        project = p
        return SaveResult(project: p, kept: [])
    }
}

final class FakeJobs: JobServing, @unchecked Sendable {
    var list: [Job] = []
    var started: [JobRequest] = []

    func listJobs() async throws -> [Job] { list }
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        started.append(request)
        let j = Job(id: "j\(started.count)", project: project, kind: request.kind, ep: request.ep, label: "\(request.ep ?? 0)화 본문")
        list.append(j)
        return (j, false)
    }
    func stopJob(_ id: String) async throws -> Job { list.first { $0.id == id }! }
    func pending(_ project: String) async throws -> PendingList { PendingList() }
    func dropPending(_ project: String, key: String, failure: Bool) async throws {}
}

/// 서버 대신: 본문을 바꾸는 호출은 가짜 저장소의 작품을 고친다 (서버가 project.json 을 고치는 것처럼).
final class FakeWrite: WriteServing, @unchecked Sendable {
    let store: FakeStore
    var texts: [(Int, String)] = []
    var exported: [(eps: [Int], format: String, title: Bool, drafts: [Int: String])] = []
    var error: CanonError?

    init(_ store: FakeStore) { self.store = store }

    private func edit(_ n: Int, _ change: (inout Ep) -> Void) -> Project {
        let i = store.project.episodes!.firstIndex { $0.plot.number == n }!
        change(&store.project.episodes![i])
        return store.project
    }

    func saveText(_ project: String, ep n: Int, text: String) async throws -> Project {
        if let error { throw error }
        texts.append((n, text))
        return edit(n) { $0.text = text.trimmingCharacters(in: .whitespacesAndNewlines); $0.status = .written }
    }

    func rewriteInfo(_ project: String, ep: Int) async throws -> RewriteInfo {
        RewriteInfo(presets: [.init(id: "slow", label: "속도 늦추기")],
                    materials: [.init(id: "issues", label: "검수 결과", lines: ["- x"], note: "")], keepMax: 3)
    }

    func rewritePrompt(_ project: String, ep: Int, request: RewriteRequest) async throws -> String { "[시스템]\n…" }

    func adopt(_ project: String, ep n: Int) async throws -> Project {
        edit(n) { e in
            e.versions = (e.versions ?? []) + [TextVersion(id: "v1", text: e.text, kind: .previous)]
            e.text = e.candidate?.text
            e.candidate = nil
        }
    }

    func dropCandidate(_ project: String, ep n: Int) async throws -> Project {
        edit(n) { $0.candidate = nil }
    }

    func restore(_ project: String, ep n: Int, version: String) async throws -> Project {
        edit(n) { e in e.text = e.versions?.first { $0.id == version }?.text }
    }

    func formats() async throws -> [PublishFormat] {
        [.init(id: "blank", label: "문단 사이 빈 줄", hint: "")]
    }

    func export(_ project: String, episodes: [Int], format: String, title: Bool, drafts: [Int: String]) async throws -> ExportOut {
        exported.append((episodes, format, title, drafts))
        return ExportOut(text: "글", html: "<p>글</p>", episodes: episodes, filename: "x.txt")
    }
}

func project() -> Project {
    Project(meta: .init(title: "등대", targetEpisodes: 4, wordsPerEpisode: 5000),
            characters: [.init(id: "c1", name: "서연", role: "주인공")],
            episodes: [ep(1, .finalized, text: "1화 본문"), ep(2, .written, text: "2화 본문"), ep(3, .confirmed), ep(4, .draft)])
}

@MainActor
func make(_ p: Project = project(), name: String = UUID().uuidString) async -> (WriteModel, FakeStore, FakeJobs, FakeWrite) {
    let store = FakeStore(p)
    let doc = ProjectDocument(name: name, store: store)
    await doc.load()
    let jobs = FakeJobs()
    let center = JobCenter(service: jobs)
    await center.open(doc)
    let service = FakeWrite(store)
    return (WriteModel(document: doc, jobs: center, service: service, defaults: nil), store, jobs, service)
}

@MainActor
@Suite struct WriteModelTests {
    @Test func opensCurrentEpisode() async {
        let (m, _, _, _) = await make()
        #expect(m.number == 2)  // 반영이 끝나지 않은 첫 화
        #expect(m.previous == 1 && m.next == 3)
        m.picked = 9
        #expect(m.number == 2)  // 없는 화를 고르면 지금 화
    }

    @Test func savesTextThroughTextEndpoint() async {
        let (m, store, _, service) = await make()
        m.setDraft(2, "2화 본문 고침 ")
        #expect(m.unsaved(2))
        #expect(await m.saveText(2))
        #expect(service.texts.first?.1 == "2화 본문 고침 ")
        #expect(m.drafts[2] == nil)
        #expect(m.document.project?.episodes?[1].text == "2화 본문 고침")
        #expect(!m.document.dirty)
        #expect(m.notice?.text == "본문을 저장했어요")
        #expect(store.saved == 0)  // 작품 전체 저장은 하지 않는다
    }

    @Test func savingTextSavesProjectChangesFirst() async {
        let (m, store, _, _) = await make()
        m.document.edit { $0.facts = ["새 사실"] }
        m.setDraft(2, "새 본문")
        #expect(await m.saveText(2))
        #expect(store.saved == 1)
        #expect(m.document.project?.facts == ["새 사실"])
    }

    @Test func saveErrorKeepsDraft() async {
        let (m, _, _, service) = await make()
        service.error = .server(status: 400, message: "이전 화(2화)의 상태 반영이 끝나야 해요", code: nil)
        m.startManual(3)
        m.setDraft(3, "직접 쓴 3화")
        #expect(await m.saveText(3) == false)
        #expect(m.drafts[3] == "직접 쓴 3화")
        #expect(m.notice?.isError == true)
    }

    @Test func draftsSurviveLeavingTheScreen() async {
        let name = "초안-\(UUID().uuidString)"
        let (m, _, _, _) = await make(name: name)
        m.setDraft(2, "쓰던 글")
        let (again, _, _, _) = await make(name: name)
        #expect(again.drafts[2] == "쓰던 글")
    }

    @Test func draftEpisodeIsNotEditable() async {
        let (m, _, _, _) = await make()
        m.setDraft(4, "초안 화")
        #expect(m.drafts[4] == nil)
        #expect(m.text(4) == "")
    }

    @Test func writeIsBlockedUntilEarlierEpisodesAreFinalized() async {
        let (m, _, jobs, _) = await make()
        #expect(m.blocked(3) == [2])
        #expect(await m.write(3) == false)
        #expect(jobs.started.isEmpty)
        var p = project()
        p.episodes![1].status = .finalized
        let (ok, _, jobs2, _) = await make(p)
        #expect(await ok.write(3))
        #expect(jobs2.started.first == JobRequest(kind: "write", ep: 3))
        #expect(ok.writing(3))
    }

    @Test func checkStartsCheckJob() async {
        let (m, _, jobs, _) = await make()
        #expect(await m.check(2))
        #expect(jobs.started.first?.kind == "check")
        #expect(m.jobs.busyLabel("check", ep: 2) != nil)
    }

    @Test func rewriteSendsRequestAndSavesDraftFirst() async {
        let (m, _, jobs, service) = await make()
        await m.openRewrite(2)
        #expect(m.rewriteOpen)
        #expect(m.rewrite[2]?.materials == ["issues"])
        m.editRewrite(2) { $0.toggle(preset: "slow"); $0.feedback = "더 천천히" }
        m.addKeep(2, "살릴 문장")
        m.setDraft(2, "고친 2화")
        #expect(await m.submitRewrite(2))
        #expect(service.texts.first?.1 == "고친 2화")  // 고쳐 쓰기는 저장한 본문을 보낸다
        #expect(!m.rewriteOpen)
        let rw = jobs.started.first?.rewrite
        #expect(jobs.started.first?.kind == "write")
        #expect(rw?["feedback"] == .string("더 천천히"))
        #expect(rw?["keep"] == .array([.string("살릴 문장")]))
        #expect(rw?["materials"] == .array([.string("issues")]))
    }

    @Test func adoptDropAndRestore() async {
        var p = project()
        p.episodes![1].candidate = TextVersion(id: "v2", text: "새 판", request: RewriteRequest(feedback: "다시", presets: ["slow"]))
        let (m, store, _, _) = await make(p)
        await m.rewriteAgain(2)
        #expect(m.rewrite[2]?.feedback == "다시")
        await m.adopt(2)
        #expect(m.episode(2)?.text == "새 판")
        #expect(m.episode(2)?.candidate == nil)
        #expect(m.notice?.text == RewriteText.adopted)
        #expect(m.rewrite[2] == nil)
        #expect(m.canRestore(2))
        m.peek = "v1"
        await m.restore(2, version: "v1")
        #expect(m.episode(2)?.text == "2화 본문")
        #expect(m.peek == nil)
        store.project.episodes![1].candidate = TextVersion(id: "v3", text: "또 새 판")
        await m.document.reload()
        await m.dropCandidate(2)
        #expect(m.episode(2)?.candidate == nil)
        #expect(m.notice?.text == RewriteText.dropped)
        m.setDraft(2, "고치는 중")
        #expect(!m.canRestore(2))
    }

    @Test func exportUsesLiveDrafts() async {
        let (m, _, _, service) = await make()
        m.setDraft(2, "저장 안 한 2화")
        #expect(m.writtenNumbers == [1, 2])
        #expect(m.range.from == 1 && m.range.to == 2)
        let out = await m.export([1, 2, 3])
        #expect(out?.episodes == [1, 2])
        #expect(service.exported.first?.drafts == [2: "저장 안 한 2화"])
        #expect(service.exported.first?.format == "blank")
        #expect(await m.export([4]) == nil)
        #expect(m.notice?.text == "그 범위에 본문이 있는 화가 없어요")
        m.setRange(from: 9)
        #expect(m.range.from == 2)
    }

    @Test func copyPrefsAreRemembered() async {
        let defaults = UserDefaults(suiteName: "write-\(UUID().uuidString)")!
        let store = FakeStore(project())
        let doc = ProjectDocument(name: "등대", store: store)
        let center = JobCenter(service: FakeJobs())
        let m = WriteModel(document: doc, jobs: center, service: FakeWrite(store), defaults: defaults)
        m.format = "indent"
        m.withTitle = false
        let again = WriteModel(document: doc, jobs: center, service: FakeWrite(store), defaults: defaults)
        #expect(again.format == "indent")
        #expect(!again.withTitle)
    }
}
