import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Testing

/// 작업 목록과 결과를 흉내 낸다.
final class FakeJobs: JobServing, @unchecked Sendable {
    var list: [Job] = []
    var pendingList = PendingList()
    var started: [JobRequest] = []
    var dropped: [(String, Bool)] = []

    func listJobs() async throws -> [Job] { list }
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        started.append(request)
        let j = Job(id: "j\(started.count)", project: project, kind: request.kind, ep: request.ep, label: "\(request.ep ?? 0)화 본문")
        list.append(j)
        return (j, false)
    }
    func stopJob(_ id: String) async throws -> Job { list.first { $0.id == id }! }
    func pending(_ project: String) async throws -> PendingList { pendingList }
    func dropPending(_ project: String, key: String, failure: Bool) async throws { dropped.append((key, failure)) }
}

func job(_ id: String, _ kind: String, ep: Int? = nil, status: Job.Status = .running, done: Int = 0, pending: [Int] = [], result: JSONValue? = nil) -> Job {
    Job(id: id, project: "등대", kind: kind, ep: ep, label: "작업", total: 2, done: done, status: status, pending: pending, result: result)
}

@MainActor
@Suite struct JobCenterTests {
    @Test func startSavesFirstAndAnnounces() async {
        let store = FakeStore(project())
        let doc = ProjectDocument(name: "등대", store: store)
        await doc.load()
        doc.edit { $0.facts = ["새 사실"] }
        let jobs = FakeJobs()
        let center = JobCenter(service: jobs)
        await center.open(doc)
        #expect(await center.start(JobRequest(kind: "write", ep: 2)))
        #expect(store.saved.count == 1)
        #expect(jobs.started.first?.kind == "write")
        #expect(center.notice?.text == "2화 본문을 시작했어요. 끝나면 알려 드릴게요. 그동안 다른 작업을 해도 돼요.")
        #expect(center.running("write", ep: 2) != nil)
        #expect(center.busyLabel("write", ep: 2) == "2화 본문 만드는 중…")
    }

    @Test func finishedWriteMergesThatEpisodeOnly() async {
        let store = FakeStore(project())
        let doc = ProjectDocument(name: "등대", store: store)
        await doc.load()
        let jobs = FakeJobs()
        let center = JobCenter(service: jobs)
        await center.open(doc)
        jobs.list = [job("w", "write", ep: 2)]
        await center.refresh()
        doc.edit { $0.episodes?[0].plot.title = "고치던 1화" }
        store.project.episodes?[0].plot.title = "서버 1화"
        store.project.episodes?[1].text = "새 본문"
        jobs.list = [job("w", "write", ep: 2, status: .done, done: 1)]
        await center.refresh()
        #expect(doc.project?.episodes?[0].plot.title == "고치던 1화")
        #expect(doc.project?.episodes?[1].text == "새 본문")
        #expect(doc.dirty)
        #expect(center.notice?.text == "2화 본문을 저장했어요.")
    }

    @Test func keepsProposalUntilDropped() async {
        let doc = ProjectDocument(name: "등대", store: FakeStore(project()))
        let jobs = FakeJobs()
        let center = JobCenter(service: jobs)
        await center.open(doc)
        jobs.list = [job("s", "state", ep: 2)]
        await center.refresh()
        jobs.list = [job("s", "state", ep: 2, status: .done, done: 1, result: .object(["episode": .number(2), "summary": .string("요약")]))]
        await center.refresh()
        let r = center.results["state:2"]
        #expect(r?.result["summary"] == .string("요약"))
        let delta = try? r?.result.decode(Components.Schemas.StateDelta.self)
        #expect(delta?.episode == 2)
        await center.drop("state", ep: 2)
        #expect(center.results["state:2"] == nil)
        #expect(jobs.dropped.first?.0 == "state:2")
    }

    @Test func failureIsKeptAndOpenLoadsPending() async {
        let jobs = FakeJobs()
        jobs.pendingList = PendingList(failures: ["arc:": PendingFailure(key: "arc:", kind: "arc", ep: nil, label: "기승전결", error: "키가 없어요")])
        let center = JobCenter(service: jobs)
        await center.open(ProjectDocument(name: "등대", store: FakeStore(project())))
        #expect(center.failures["arc:"]?.error == "키가 없어요")
        jobs.list = [job("p", "plots")]
        await center.refresh()
        jobs.list = [job("p", "plots", status: .error)]
        await center.refresh()
        #expect(center.failures["plots:"] != nil)
        #expect(center.notice?.isError == true)
    }

    @Test func plotsTellSaveWhatWasMerged() async {
        let store = FakeStore(project())
        let doc = ProjectDocument(name: "등대", store: store)
        await doc.load()
        let jobs = FakeJobs()
        let center = JobCenter(service: jobs)
        await center.open(doc)
        jobs.list = [job("p", "plots", pending: [1, 2])]
        await center.refresh()
        jobs.list = [job("p", "plots", done: 1, pending: [2])]
        await center.refresh()
        #expect(center.owns(2))
        #expect(!center.owns(1))
        #expect(doc.mergedArgument == ["p:1"])
    }
}

@Suite struct JSONValueTests {
    @Test func roundTripsIntegers() throws {
        let v = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"a":[1,2.5,true,null,"x"]}"#.utf8))
        let text = String(decoding: try JSONEncoder().encode(v), as: UTF8.self)
        #expect(text == #"{"a":[1,2.5,true,null,"x"]}"#)
        #expect(v["a"] != nil)
    }
}

@MainActor
@Suite struct NoticeLifetimeTests {
    // 웹 toast 처럼 알림은 잠시 뒤 사라지고, 오류는 닫을 때까지 남는다
    @Test func plainNoticeFadesErrorStays() async throws {
        let jobs = FakeJobs()
        let center = JobCenter(service: jobs)
        center.noticeLifetime = .milliseconds(20)
        await center.open(ProjectDocument(name: "등대", store: FakeStore(project())))
        #expect(await center.start(JobRequest(kind: "write", ep: 2)))
        #expect(center.notice != nil)
        try await Task.sleep(for: .milliseconds(200))
        #expect(center.notice == nil)
        jobs.list = [job("p", "plots")]
        await center.refresh()
        jobs.list = [job("p", "plots", status: .error)]
        await center.refresh()
        try await Task.sleep(for: .milliseconds(200))
        #expect(center.notice?.isError == true)
    }
}

@MainActor
@Suite struct OfferTests {
    // 작업지시서로 받은 변경안은 작업 결과처럼 검토 대기에 놓이고, 적용하면 같은 방법으로 지운다
    @Test func offeredProposalWaitsForReview() async {
        let jobs = FakeJobs()
        let center = JobCenter(service: jobs)
        await center.open(ProjectDocument(name: "등대", store: FakeStore(project())))
        let delta = JSONValue.object(["episode": .number(2), "summary": .string("채팅 앱 요약")])
        center.offer(PendingResult(key: "state:2", id: "chat:2", kind: "state", ep: 2, label: "2화 상태 변경안", result: delta, base: "본문"))
        let d = try? center.results["state:2"]?.result.decode(Components.Schemas.StateDelta.self)
        #expect(d?.summary == "채팅 앱 요약")
        #expect(center.results["state:2"]?.base == "본문")
        await center.drop("state", ep: 2)
        #expect(center.results.isEmpty)
    }
}
