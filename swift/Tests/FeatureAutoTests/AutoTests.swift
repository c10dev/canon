import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureAuto
import Foundation
import Testing

func decode<T: Decodable>(_ json: String, as: T.Type = T.self) -> T {
    try! JSONDecoder().decode(T.self, from: Data(json.utf8))
}

func plot(_ n: Int) -> String {
    #"{"number":\#(n),"act":"기","title":"\#(n)화 제목","summary":"","events":[],"characters":[],"emotional_shift":"","ending_hook":""}"#
}

/// 6화 작품: 1 · 2화 반영 끝(2화는 자동), 3화 본문 있음, 4화 확정, 5화 초안.
let sample: FeatureAuto.Project = decode(#"""
{"meta":{"title":"등대","target_episodes":6},
 "characters":[{"id":"dh","name":"도현","role":"주인공"}],
 "history":[{"episode":2,"summary":"2화 요약","new_characters":[{"id":"ma","name":"마담","role":"단역"}]}],
 "elements":[{"id":"el-1","name":"항구 시장","found_in":"본문","found_ep":2}],
 "snapshots":[{"episode":0},{"episode":1},{"episode":2}],
 "episodes":[{"plot":\#(plot(1)),"status":"finalized","text":"1화 본문"},
             {"plot":\#(plot(2)),"status":"finalized","text":"2화 본문","auto":true,"issues":[{"type":"말투","description":"x","source_quote":"a","current_quote":"b"}],"checked_at":"2026-10-28T10:00:00","findings":[{"id":"f1","type":"말투","description":"x","source_quote":"a","current_quote":"b","status":"open"}]},
             {"plot":\#(plot(3)),"status":"written","text":"3화 본문"},
             {"plot":\#(plot(4)),"status":"confirmed"},
             {"plot":\#(plot(5)),"status":"draft"}]}
"""#)

let policyJSON = #"{"check":true,"max_issues":0,"max_shift":0.3,"stop_on_stage":false,"stop_on_warnings":false,"confirm_plots":false,"review_every":0,"hand_pick_opening":true}"#

func runJSON(status: String = "review", ep: String = "3", step: String = "review", pending: Bool = true, pendingText: String = "3화 본문",
             halt: String = "review", reasons: String = #"["검수에서 어긋난 곳 1개 (말투)"]"#, batches: String = "{}", restarts: Int = 0,
             log: String = "[]", policy: String = policyJSON, started: String = "2026-10-26T01:00:00+00:00") -> String {
    #"""
    {"target":5,"batch":false,"policy":\#(policy),"status":"\#(status)","ep":\#(ep),"step":"\#(step)","reasons":\#(reasons),
     "halt":"\#(halt)","restarts":\#(restarts),"pending":\#(pending ? #"{"episode":3,"summary":"3화 요약"}"# : "null"),
     "pending_text":"\#(pendingText)","batches":\#(batches),"applied":[2],"tokens_in":12345,"tokens_out":6789,"cost":0.123,
     "started":"\#(started)","updated":"2026-10-26T01:05:00+00:00","log":\#(log)}
    """#
}

func state(_ run: String?, active: Bool = false, stages: String = #"["write","check","state"]"#) -> AutoState {
    decode(#"{"run":\#(run ?? "null"),"active":\#(active),"batch_stages":\#(stages),"policy_defaults":\#(policyJSON)}"#)
}

func estimateJSON(episodes: Int = 3, from: String = "3", missing: String = "[6]", drafts: String = "[5]", rounds: Int = 0,
                  cost: String = "0.42", measured: Bool = false, unpriced: String = "[]", stages: String = #"{"write":"gemini","check":"local","state":"gemini"}"#) -> AutoEstimate {
    decode(#"""
    {"episodes":\#(episodes),"from":\#(from),"to":6,"missing":\#(missing),"drafts":\#(drafts),"calls":{"write":2,"check":3,"state":3},
     "tokens_in":123456,"tokens_out":7890,"cost":\#(cost),"batch":\#(rounds > 0),"batch_rounds":\#(rounds),"seconds_min":540,
     "seconds_max":7200,"seconds_worst":90000,"batch_avg_seconds":\#(rounds > 0 ? "1500" : "null"),"measured":\#(measured),
     "model":"gemini-4-argon","unpriced":\#(unpriced),"stages":\#(stages)}
    """#)
}

@Suite struct AutoTextTests {
    /// 기대값은 node 로 돌린 웹 `autoDuration` · `autoCost` · `toLocaleString` 결과.
    @Test func durationCostNumberMatchWeb() {
        let cases: [(Double?, String)] = [(nil, ""), (0, "0초"), (0.4, "1초"), (1.6, "2초"), (59, "59초"), (60, "1분"), (89, "1분"), (90, "2분"),
                                          (3599, "60분"), (3600, "1.0시간"), (5400, "1.5시간"), (86399, "24.0시간"), (172799, "48.0시간"), (172800, "2일"), (259200, "3일")]
        for (s, want) in cases { #expect(AutoText.duration(s) == want) }
        let costs: [(Double?, String)] = [(nil, "가격 모름"), (0, "$0"), (0.004, "$0.01 미만"), (0.01, "$0.01"), (1.234, "$1.23"), (12.5, "$12.50")]
        for (c, want) in costs { #expect(AutoText.cost(c) == want) }
        #expect(AutoText.number(1234567) == "1,234,567" && AutoText.number(999) == "999" && AutoText.number(1000) == "1,000")
        #expect(AutoText.rangeText([1, 2, 3, 5, 7, 8]) == "1~3, 5, 7~8")
    }

    @Test func statusAndStep() {
        #expect(AutoText.status(.review).label == "검토 대기" && AutoText.status(.error).label == "오류로 멈춤")
        let r: AutoRun = decode(runJSON(status: "running", step: "write", batches: #"{"write:3":"b1"}"#))
        #expect(AutoText.stepLine(r, active: true) == "3화 본문 쓰는 중 · 배치 결과 기다리는 중")
        #expect(AutoText.stepLine(r, active: false) == "")
        let first: AutoRun = decode(runJSON(status: "running", ep: "null", step: ""))
        #expect(AutoText.stepLine(first, active: true) == "첫 화를 준비하는 중")
        let odd: AutoRun = decode(runJSON(status: "running", step: "plan"))
        #expect(AutoText.stepLine(odd, active: true) == "3화 plan")
    }

    @Test func progressLine() {
        let r: AutoRun = decode(runJSON(restarts: 2))
        #expect(AutoText.doneCount(sample, target: r.target) == 2)
        #expect(AutoText.progressLine(r, done: 2) == "2 / 5화 반영 완료 · 이번 실행에서 자동 반영 1화 · 토큰 입력 12,345 / 출력 6,789 · 비용 약 $0.12 · 서버 재시작 2번")
    }

    /// 새로 시작 칸: 플롯이 있는 마지막 화까지, 정책은 지난 실행 것, 없으면 서버 기본값 (앱이 기본값을 정하지 않는다).
    @Test func defaultsComeFromServer() {
        let none = AutoText.defaults(sample, state(nil))
        #expect(none.target == 5 && !none.batch && none.policy == state(nil).policyDefaults)
        let custom = #"{"check":false,"max_issues":2,"max_shift":0.45,"stop_on_stage":true,"stop_on_warnings":true,"confirm_plots":true,"review_every":3,"hand_pick_opening":false}"#
        let last = AutoText.defaults(sample, state(runJSON(policy: custom)))
        #expect(last.policy.maxIssues == 2 && last.policy.check == false && last.policy.reviewEvery == 3)
        let empty: FeatureAuto.Project = decode(#"{"meta":{"target_episodes":12}}"#)
        #expect(AutoText.defaults(empty, nil).target == 12)
    }

    @Test func estimateTexts() {
        let e = estimateJSON()
        #expect(AutoText.estimateLine(e) == "3~6화 3화 남음 · 호출 본문 2 · 검수 3 · 상태 3 · 토큰 입력 약 123,456 / 출력 약 7,890")
        #expect(AutoText.estimateTime(e) == ("약 9분", ""))
        let b = estimateJSON(rounds: 4)
        #expect(AutoText.estimateTime(b) == ("9분~2.0시간", "배치 4번 기다림. 길면 한 번에 24시간까지 걸릴 수 있어요 (지난 평균 25분)"))
        #expect(AutoText.estimateWarnings(e) == [
            "플롯이 없는 화(6화)에서 멈춰요. 먼저 플롯을 만드세요.",
            "플롯이 초안인 5화에서 멈춰요. 추정은 끝까지 쓴다고 보고 셌어요. 확정하거나 '초안 플롯도 자동으로 확정하고 쓰기'를 켜세요.",
        ])
        #expect(AutoText.estimateNotes(estimateJSON(unpriced: #"["gemini-x"]"#)) == [
            "검수 단계는 로컬 모델이라 비용이 없고 배치도 쓰지 않아요.",
            "처음이라 화당 목표 분량으로 추정했어요. 가격은 사용량 · 비용 화면의 가격표(gemini-4-argon 기준)로 계산한 추정치이고, 생각(thinking) 토큰이 많으면 더 나올 수 있어요. 가격표에 없는 모델(gemini-x)이 있어 비용을 몰라요.",
        ])
        let done = estimateJSON(episodes: 0, from: "null", missing: "[]", drafts: "[]")
        #expect(AutoText.nothingLeft(done) && !AutoText.nothingLeft(e))
        #expect(AutoText.nothingLeftNote(done) == "6화까지 남은 화가 없어요. 더 쓰려면 위에서 목표 화를 늘리세요.")
        #expect(AutoText.estimateLine(done) == "6화까지 남은 화가 없어요")
    }

    @Test func startQuestion() {
        #expect(AutoText.startQuestion(6, estimateJSON(rounds: 4, cost: "null")) == """
        6화까지 자동으로 써요.
        남은 화 3화 (3~6화)
        예상 시간 9분~2.0시간 (배치는 한 번에 최대 24시간까지 걸릴 수 있어요)
        예상 비용 알 수 없어요 (가격표에 없는 모델)
        정해 둔 멈춤 조건에 걸리지 않은 화는 검토 없이 상태를 반영해요.
        시작할까요?
        """)
        #expect(AutoText.startQuestion(6, nil) == "6화까지 자동으로 써요.\n정해 둔 멈춤 조건에 걸리지 않은 화는 검토 없이 상태를 반영해요.\n시작할까요?")
    }

    @Test func haltLinksAndNotes() {
        let review: AutoRun = decode(runJSON())
        #expect(AutoText.haltLink(review, sample)! == ("3화 본문 읽기", .write))
        let issues: AutoRun = decode(runJSON(ep: "2"))
        #expect(AutoText.haltLink(issues, sample)! == ("2화 검수 결과 보기", .check))
        #expect(AutoText.haltLink(decode(runJSON(halt: "plot_draft")), sample)! == ("3화 플롯 확정하러 가기", .arc))
        #expect(AutoText.haltLink(decode(runJSON(halt: "plot_missing")), sample)! == ("3화 플롯 만들러 가기", .arc))
        #expect(AutoText.haltLink(decode(runJSON(halt: "every")), sample)! == ("3화 읽으러 가기", .write))
        #expect(AutoText.haltLink(decode(runJSON(halt: "changed")), sample)! == ("3화 집필 화면 보기", .write))
        #expect(AutoText.haltLink(decode(runJSON(halt: "error")), sample) == nil)
        #expect(AutoText.runPolicyNote(review) == "바꾼 정책은 다음 판정부터 적용돼요. 지금 검토를 기다리는 3화 변경안은 그대로 남아요.")
        #expect(AutoText.runPolicyNote(decode(runJSON(status: "paused"))) == "바꾼 정책은 다음 판정부터 적용돼요. 검토 대기와 기다리던 배치는 그대로예요.")
        let key: AutoRun = decode(runJSON(status: "error", reasons: #"["Gemini API 키가 없어요"]"#))
        #expect(AutoText.needsSettings(key))
        #expect(!AutoText.needsSettings(decode(runJSON(status: "error", reasons: #"["형식이 맞지 않아요"]"#))))
        #expect(!AutoText.needsSettings(decode(runJSON(status: "paused", reasons: #"["HTTP 429"]"#))))
        #expect(AutoText.paused(batch: true) == "멈추는 중이에요. 기다리던 배치는 취소하지 않아, 이어 가면 결과를 받아 와요.")
        #expect(AutoText.paused(batch: false) == "지금 단계가 끝나면 멈춰요.")
    }

    /// 변경안을 만든 뒤 본문을 고쳤으면 그대로 반영을 막는다 (앞뒤 공백은 보지 않는다).
    @Test func pendingStale() {
        #expect(!AutoText.pendingStale(decode(runJSON(pendingText: "3화 본문\\n")), sample))
        #expect(AutoText.pendingStale(decode(runJSON(pendingText: "고치기 전")), sample))
        #expect(!AutoText.pendingStale(decode(runJSON(pending: false, pendingText: "고치기 전")), sample))
        #expect(AutoText.reviewDone(decode(runJSON(pending: false))) && !AutoText.reviewDone(decode(runJSON())))
    }

    @Test func appliedAndRevert() {
        let log = #"""
        [{"at":"2026-10-26T01:00:00+00:00","ep":2,"step":"write","level":"warn","message":"문체: 반복 구","tokens_in":0,"tokens_out":0,"seconds":0,"batch":false},
         {"at":"2026-10-26T01:00:01+00:00","ep":2,"step":"write","level":"warn","message":"초반: 늦은 사건","tokens_in":0,"tokens_out":0,"seconds":0,"batch":false},
         {"at":"2026-10-26T01:00:02+00:00","ep":2,"step":"write","level":"info","message":"문체: 괜찮아요","tokens_in":0,"tokens_out":0,"seconds":0,"batch":false},
         {"at":"2026-10-26T01:00:03+00:00","ep":3,"step":"write","level":"warn","message":"검수 실패","tokens_in":0,"tokens_out":0,"seconds":0,"batch":false}]
        """#
        let r: AutoRun = decode(runJSON(log: log))
        #expect(AutoText.styleWarnings(r.log) == [2: 2])
        #expect(AutoText.revertQuestion(2, sample) == "2화의 상태 반영을 취소할까요? 1화 반영 직후 상태로 돌아가고, 본문은 남아 상태 승인을 다시 하게 돼요. 그 반영이 더한 인물(마담)도 빠져요. 본문에서 등록한 장소(항구 시장)도 빠져요. 아직 안 쓴 화 플롯에 나오거나 직접 고친 장소는 남아요.")
        #expect(AutoText.revertDone(2, fin: [2]) == "2화의 반영을 취소했어요. 2화 변경안을 다시 골라 적용하세요")
    }

    @Test func logTime() {
        let utc = TimeZone(identifier: "UTC")!
        let now = ISO8601DateFormatter().date(from: "2026-10-26T09:00:00Z")!
        #expect(AutoText.logTime("2026-10-26T01:02:03+00:00", now: now, timeZone: utc) == "01:02:03")
        #expect(AutoText.logTime("2026-10-25T23:59:59+00:00", now: now, timeZone: utc) == "2026.10.25 23:59:59")
        #expect(AutoText.logTime("모름", now: now, timeZone: utc) == "모름")
        let e: AutoLog = decode(#"{"at":"x","step":"write","level":"info","message":"m","tokens_in":1200,"tokens_out":0,"seconds":0,"batch":false}"#)
        #expect(AutoText.logTokens(e) == "1,200 / 0")
    }

    /// 같은 초 안의 변화도 알아챈다 (`updated` 만 보지 않는다).
    @Test func signature() {
        let a: AutoRun = decode(runJSON(status: "running"))
        let b: AutoRun = decode(runJSON(status: "paused"))
        #expect(AutoText.signature(a) != AutoText.signature(b))
        #expect(AutoText.signature(nil) == "")
    }
}

// MARK: 화면 상태

final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: FeatureAuto.Project
    var loads = 0
    init(_ p: FeatureAuto.Project) { project = p }
    func load(_ name: String) async throws -> FeatureAuto.Project { loads += 1; return project }
    func save(_ name: String, _ p: FeatureAuto.Project, merged: [String], force: Bool) async throws -> SaveResult {
        project = p
        return SaveResult(project: p, kept: [])
    }
}

final class FakeJobs: JobServing, @unchecked Sendable {
    var pendingList = PendingList()
    var pendingCalls = 0
    func listJobs() async throws -> [Job] { [] }
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        (Job(id: "j", project: project, kind: request.kind, ep: request.ep, label: ""), false)
    }
    func stopJob(_ id: String) async throws -> Job { Job(id: id, project: "", kind: "", label: "") }
    func pending(_ project: String) async throws -> PendingList { pendingCalls += 1; return pendingList }
    func dropPending(_ project: String, key: String, failure: Bool) async throws {}
}

final class FakeAuto: AutoService, @unchecked Sendable {
    var current: AutoState
    var offline = false
    var calls: [String] = []
    var estimates: [(Int, Bool, Policy)] = []
    var jobs: FakeJobs?
    init(_ s: AutoState) { current = s }

    func status(_ project: String) async throws -> AutoState {
        if offline { throw CanonError.offline }
        return current
    }
    /// 배치 끔 · 켬 추정은 동시에 부른다.
    private let lock = NSLock()
    func estimate(_ project: String, target: Int, batch: Bool, policy: Policy) async throws -> AutoEstimate {
        lock.withLock { estimates.append((target, batch, policy)) }
        return estimateJSON(rounds: batch ? 4 : 0)
    }
    func start(_ project: String, target: Int, batch: Bool, policy: Policy) async throws -> AutoState {
        calls.append("start \(target) \(batch) \(policy.maxIssues ?? -1)")
        current = state(runJSON(status: "running", ep: "null", step: "", pending: false, reasons: "[]"), active: true)
        return current
    }
    func request(_ project: String, _ what: String) async throws -> AutoState { calls.append(what); return current }
    func resume(_ project: String, approve: Bool, rewrite: Bool) async throws -> AutoState {
        calls.append("resume \(approve) \(rewrite)")
        return current
    }
    func setBatch(_ project: String, _ on: Bool) async throws -> AutoState { calls.append("batch \(on)"); return current }
    func setPolicy(_ project: String, _ policy: Policy) async throws -> AutoState {
        calls.append("policy \(policy.reviewEvery ?? -1)")
        current = state(runJSON(policy: #"{"check":true,"max_issues":0,"max_shift":0.3,"stop_on_stage":false,"stop_on_warnings":false,"confirm_plots":false,"review_every":2,"hand_pick_opening":true}"#))
        return current
    }
    func sendToReview(_ project: String) async throws -> AutoState {
        calls.append("review")
        let value = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"episode":3,"summary":"3화 요약"}"#.utf8))
        jobs?.pendingList = PendingList(results: ["state:3": PendingResult(key: "state:3", id: "auto:x:3", kind: "state", ep: 3, label: "3화 상태 변경안", result: value, base: "3화 본문")])
        return current
    }
    func revert(_ project: String, after: Int) async throws { calls.append("revert \(after)") }
}

@MainActor
@Suite struct AutoModelTests {
    func make(_ s: AutoState) async -> (AutoModel, FakeAuto, FakeJobs, FakeStore) {
        let store = FakeStore(sample)
        let doc = ProjectDocument(name: "등대", store: store)
        let jobs = FakeJobs()
        let center = JobCenter(service: jobs)
        await center.open(doc)
        let auto = FakeAuto(s)
        auto.jobs = jobs
        let model = AutoModel(document: doc, jobs: center, service: auto)
        await model.start()
        return (model, auto, jobs, store)
    }

    @Test func startsWithServerDefaultsAndEstimatesBoth() async {
        let (model, auto, _, _) = await make(state(nil))
        #expect(model.form == AutoForm(target: 5, batch: false, policy: state(nil).policyDefaults))
        #expect(model.canStart && model.ended)
        #expect(Set(auto.estimates.map(\.1)) == [false, true])
        #expect(model.pickedEstimate?.batchRounds == 0)
        model.form?.batch = true
        #expect(model.pickedEstimate?.batchRounds == 4)
        await model.begin()
        #expect(auto.calls == ["start 5 true 0"])
        #expect(model.active && model.notice?.text == AutoText.started && !model.canStart)
    }

    @Test func reviewGoesToStateApproval() async {
        let (model, auto, jobs, _) = await make(state(runJSON()))
        #expect(!model.canStart && !model.ended && model.canEditRunPolicy)
        #expect(model.jobs.results["state:3"] == nil)
        #expect(await model.sendToReview())
        #expect(auto.calls == ["review"] && jobs.pendingCalls == 2)
        #expect(model.jobs.results["state:3"]?.base == "3화 본문")
    }

    @Test func runPolicyEditing() async {
        let (model, auto, _, _) = await make(state(runJSON(status: "paused")))
        #expect(!model.runPolicyChanged)
        model.runPolicy?.reviewEvery = 2
        #expect(model.runPolicyChanged)
        await model.applyRunPolicy()
        #expect(auto.calls == ["policy 2"] && !model.runPolicyChanged && model.notice?.text == AutoText.policyChanged)
    }

    /// 연결이 끊기면 '진행 중'으로 두지 않고, 다시 붙으면 알린다. 서버 재시작도 한 번 알린다.
    @Test func offlineAndRestart() async {
        let (model, auto, _, store) = await make(state(runJSON(status: "running", pending: false), active: true))
        #expect(model.active)
        auto.offline = true
        await model.refresh()
        #expect(model.offline && !model.active)
        auto.offline = false
        auto.current = state(runJSON(status: "running", step: "write", pending: false, restarts: 1), active: true)
        let loads = store.loads
        await model.refresh()
        #expect(!model.offline && model.notice?.text == AutoText.restarted)
        #expect(store.loads == loads + 1)  // 단계가 바뀌어 작품을 다시 받았다
        await model.refresh()
        #expect(store.loads == loads + 1)  // 바뀐 것이 없으면 받지 않는다
    }

    @Test func pauseStopResumeBatchRevert() async {
        let (model, auto, _, _) = await make(state(runJSON()))
        await model.resume(approve: true)
        await model.setBatch(true)
        #expect(model.form?.batch == true && model.notice?.text == AutoText.batchChanged(true))
        await model.pause()
        await model.stop()
        await model.revert(from: 2)
        #expect(auto.calls == ["resume true false", "batch true", "pause", "stop", "revert 1"])
        #expect(model.notice?.text == "2화의 반영을 취소했어요. 2화 변경안을 다시 골라 적용하세요")
    }

    /// 끝난 실행은 배치를 서버에 보내지 않고 새로 시작 칸만 바꾼다.
    @Test func batchOnEndedRunOnlyChangesForm() async {
        let (model, auto, _, _) = await make(state(runJSON(status: "done", ep: "5", pending: false, reasons: "[]")))
        #expect(model.batchLocked && model.canStart)
        await model.setBatch(true)
        #expect(auto.calls.isEmpty && model.form?.batch == true)
    }

    @Test func logIsNewestFirstAndLimited() async {
        let rows = (1...35).map { #"{"at":"2026-10-26T01:00:00+00:00","step":"write","level":"info","message":"줄 \#($0)","tokens_in":0,"tokens_out":0,"seconds":0,"batch":false}"# }
        let (model, _, _, _) = await make(state(runJSON(log: "[" + rows.joined(separator: ",") + "]")))
        #expect(model.shownLog.count == 30 && model.shownLog.first?.message == "줄 35" && model.hiddenLog == 5)
        model.logAll = true
        #expect(model.shownLog.count == 35 && model.hiddenLog == 0)
        #expect(model.autoApplied.map(\.plot.number) == [2])
    }
}
