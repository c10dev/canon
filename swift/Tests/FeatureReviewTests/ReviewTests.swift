import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureReview
import Foundation
import Testing

/// 작품을 JSON 으로 만든다 (생성 타입의 init 은 칸이 많다).
func project(_ json: String) -> FeatureReview.Project {
    try! JSONDecoder().decode(FeatureReview.Project.self, from: Data(json.utf8))
}

func delta(_ json: String) -> StateDelta {
    try! JSONDecoder().decode(StateDelta.self, from: Data(json.utf8))
}

func plot(_ n: Int) -> String {
    #"{"number":\#(n),"act":"기","title":"\#(n)화 제목","summary":"","events":[],"characters":[],"emotional_shift":"","ending_hook":""}"#
}

/// 도현 · 서윤과 열린 복선 하나, 1화 반영 끝 · 2화 본문 있음 · 3화 플롯 확정.
let sample = project(#"""
{"characters":[{"id":"dh","name":"도현","role":"주인공"},{"id":"sy","name":"서윤","role":"조연"}],
 "cast_candidates":[{"id":"ma","name":"마담","role":"단역"}],
 "states":[{"character_id":"dh","emotional_state":"불안","location":"등대","knows":["편지"],"stats":[{"name":"HP","value":"10"},{"name":"등급","value":"B급"}]}],
 "relationships":[{"a":"dh","b":"sy","type":"동료","description":"오랜 친구"}],
 "foreshadows":[{"id":"fs-1","description":"낡은 열쇠","planted_ep":1}],
 "secrets":[{"id":"sec-1","owner":"dh","content":"편지를 숨김"}],
 "facts":["등대는 북쪽에 있다"],
 "snapshots":[{"episode":0},{"episode":1}],
 "history":[{"episode":1,"summary":"1화 요약","new_facts":["등대는 북쪽에 있다"],"new_characters":[{"id":"ma","name":"마담","role":"단역"}]}],
 "elements":[{"id":"el-1","name":"항구 시장","found_in":"본문","found_ep":2},{"id":"el-2","name":"성당","found_in":"","found_ep":0}],
 "episodes":[{"plot":\#(plot(1)),"status":"finalized","text":"1화 본문","summary":"1화 요약"},
             {"plot":\#(plot(2)),"status":"written","text":"2화 본문"},
             {"plot":\#(plot(3)),"status":"confirmed"}]}
"""#)

let sampleDelta = delta(#"""
{"episode":2,"summary":"2화 요약",
 "character_updates":[{"character_id":"dh","emotional_state":"안도","location":"등대","knows":["편지","열쇠"],"stats":[{"name":"HP","value":"+3"},{"name":"등급","value":"+1"},{"name":"MP","value":""}]},
                      {"character_id":"ghost","emotional_state":"?"}],
 "events":[{"episode":2,"actor":"dh","target":"sy","kind":"도움","intensity":3,"witnesses":["ma"],"reveals_secret":"sec-2"}],
 "secrets_added":[{"id":"sec-2","owner":"sy","content":"이름이 가짜다","hidden_from":["dh"]}],
 "relationship_updates":[{"a":"sy","b":"dh","type":"연인"}],
 "new_facts":["등대는 북쪽에 있다","등대지기는 떠났다"],
 "foreshadow_planted":[{"id":"fs-2","description":"푸른 병","planted_ep":2}],
 "foreshadow_resolved":["fs-1","fs-9"],
 "foreshadow_clues":[{"foreshadow":"fs-1","kind":"payoff","quote":"열쇠가 맞았다"},{"foreshadow":"fs-2","quote":"푸른 병이 놓였다"},{"foreshadow":"fs-1","quote":"열쇠를 만졌다"}],
 "new_characters":[{"id":"bo","name":"보라","role":"상인","tier":"minor"}],
 "new_places":[{"name":"항구 시장","kind":"시장","aliases":["장터"]}],
 "warnings":["말투가 어긋남"]}
"""#)

@Suite struct ReviewTextTests {
    /// 웹 `setDelta`: 설정에도 새 인물에도 없는 인물 상태와 모르는 복선 회수는 빼 둔다.
    @Test func defaultPicksSkipUnknown() {
        let picks = ReviewText.defaultPicks(sampleDelta, project: sample)
        #expect(picks == ["c0", "e0", "s0", "r0", "f0", "f1", "p0", "x0", "n0", "l0", "q0", "q1", "q2"])
        #expect(ReviewText.total(sampleDelta) == 15)
    }

    /// 웹 `pickedDelta`: 고른 것만, 요약 · 경고는 그대로.
    @Test func pickedKeepsOnlyChecked() {
        let out = ReviewText.picked(sampleDelta, ["c1", "f1", "q2"])
        #expect(out.characterUpdates?.map(\.characterId) == ["ghost"])
        #expect(out.newFacts == ["등대지기는 떠났다"])
        #expect(out.foreshadowClues?.map(\.quote) == ["열쇠를 만졌다"])
        #expect(out.events == [] && out.newPlaces == [] && out.foreshadowResolved == [])
        #expect(out.summary == "2화 요약" && out.warnings == ["말투가 어긋남"])
    }

    /// 웹 `applyDelta` 의 묻는 말.
    @Test func applyAsksWhenEmptyWarnedOrStale() {
        let none = ReviewText.picked(sampleDelta, ["q0"])
        let why = ReviewText.applyReasons(none, textChanged: true)
        #expect(ReviewText.applyQuestion(why, ep: 2)
            == "고른 항목이 0건이에요. 요약만 저장하고 경고 1건이 남아 있어요. 변경안을 만든 뒤 본문을 고쳤어요. 2화를 마칠까요? 반영하면 반영 취소로만 돌아갈 수 있어요.")
        var clean = ReviewText.picked(sampleDelta, ["f0"])
        clean.warnings = []
        #expect(ReviewText.applyReasons(clean, textChanged: false).isEmpty)
    }

    @Test func namesAndRows() {
        #expect(ReviewText.name("dh", sample) == "도현")
        #expect(ReviewText.name("ma", sample) == "마담")
        #expect(ReviewText.name("zz", sample) == "zz")
        #expect(ReviewText.secret("sec-2", sampleDelta, sample) == "이름이 가짜다")
        #expect(ReviewText.intensity(3) == "결정적" && ReviewText.intensity(nil) == "보통")
        let u = sampleDelta.characterUpdates![0]
        let cur = sample.states![0]
        // 같은 값(위치 등대)은 지금 값을 보이지 않는다
        #expect(ReviewText.stateRows(u, current: cur).map { "\($0.label):\($0.before ?? "-")>\($0.after)" } == ["감정:불안>안도", "위치:->등대"])
        #expect(ReviewText.newKnows(u, current: cur) == ["열쇠"])
        #expect(ReviewText.unknown("ghost", sampleDelta, sample))
        #expect(!ReviewText.unknown("bo", sampleDelta, sample))
    }

    /// 웹 `swDeltaRows`: 숫자면 계산하고 적은 값을 괄호로, 숫자가 아니면 적은 그대로, 빈 값은 지움.
    @Test func statRows() {
        let rows = ReviewText.statRows(sampleDelta.characterUpdates![0], current: sample.states![0])
        #expect(rows == [
            .init(name: "HP", before: "10", after: "13", raw: "+3"),
            .init(name: "등급", before: "B급", after: "+1", raw: nil),
            .init(name: "MP", before: nil, after: nil, raw: nil),
        ])
    }

    /// 서버 `tests/test_statwin.py` 의 `test_resolve` 와 같은 사례.
    @Test func resolveMatchesServer() {
        #expect(ReviewText.resolve("10", "+3") == "13")
        #expect(ReviewText.resolve("1,200", "-200") == "1000")
        #expect(ReviewText.resolve("1.5", "+0.25") == "1.75")
        #expect(ReviewText.resolve("B급", "+1") == "+1")
        #expect(ReviewText.resolve("3", "A급") == "A급")
    }

    /// 웹 `fsClueRows`: 회수 문장, 이번에 심은 복선의 문장, 열린 복선을 다시 떠올린 문장.
    @Test func clueRows() {
        let rows = ReviewText.clueRows(sampleDelta, sample)
        #expect(rows.map(\.note) == ["회수한 문장", "심은 문장", "다시 떠올린 문장"])
        #expect(rows.map(\.label) == ["낡은 열쇠", "푸른 병", "낡은 열쇠"])
        #expect(rows[0].payoff && !rows[1].payoff)
    }

    @Test func placeDetail() {
        #expect(ReviewText.placeDetail(sampleDelta.newPlaces![0]) == "시장 · 다른 이름: 장터")
    }

    /// 웹 `relationLines`: 줄 앞 쌍으로 지금 값과 맞춘다.
    @Test func relationLinesComparePairs() throws {
        let rel = try JSONDecoder().decode(RelationPreview.self, from: Data(#"""
        {"words":"도현 → 서윤: 따뜻하다. 신뢰: 믿는다. 단계: 호감\n서윤 → 도현: 덤덤하다. 단계: 낯섦\n도현 ↔ 서윤 (연인) 긴장: 낮음 (2/10)",
         "numbers":"","show_numbers":false,
         "before":{"words":"도현 → 서윤: 덤덤하다. 단계: 낯섦\n서윤 → 도현: 덤덤하다. 단계: 낯섦","numbers":"","show_numbers":false}}
        """#.utf8))
        let out = ReviewText.relationLines(rel, numbers: false)
        #expect(out.head == "반영하면 2줄이 바뀌어요. 바뀌는 줄 아래에 지금 값을 함께 보여요.")
        #expect(out.lines.map(\.changed) == [true, false, true])
        #expect(out.lines[0].was == "도현 → 서윤: 덤덤하다. 단계: 낯섦")
        #expect(out.lines[2].was == nil)
        #expect(ReviewText.relationLines(rel, numbers: true).head == "관계가 없어요. 설정 도우미에서 관계를 추가하세요.")
    }

    @Test func rangeText() {
        #expect(ReviewText.rangeText([1, 2, 3, 5, 7, 8]) == "1~3, 5, 7~8")
        #expect(ReviewText.rangeText([]) == "")
    }

    /// 웹 `restate.js`: 이미 있는 사실 · 복선은 빼고, 고른 것만 보낸다.
    @Test func restate() {
        var fin = sample.episodes![0]
        #expect(!ReviewText.editedAfterFinal(fin))
        fin.finalText = "1화 처음 본문"
        #expect(ReviewText.editedAfterFinal(fin))
        #expect(ReviewText.laterWritten(1, sample) == [2])
        let it = ReviewText.restateItems(sampleDelta, sample)
        #expect(it == .init(facts: [1], plants: [0], places: [0]))
        #expect(ReviewText.restatePicks(sampleDelta, sample) == ["sum", "f1", "p0", "l0"])
        let body = ReviewText.restateBody(sampleDelta, ["f1"])
        #expect(body.summary == "" && body.newFacts == ["등대지기는 떠났다"] && body.foreshadowPlanted == [] && body.newPlaces == [])
        #expect(ReviewText.restateDone(2, body: body) == "2화 새 사실 1건을 반영했어요")
        #expect(ReviewText.restateDone(2, body: ReviewText.restateBody(sampleDelta, [])) == "2화 반영 뒤 고침 표시를 지웠어요")
        #expect(ReviewText.restateSkipped(sampleDelta) == ["인물 상태 2건", "관계 사건 1건", "관계 유형 1건", "새 비밀 1건", "복선 회수 2건", "새 인물 1건"])
    }

    /// 웹 `revertFrom` 의 묻는 말.
    @Test func revertQuestion() {
        #expect(ReviewText.revertQuestion(1, sample)
            == "1화의 상태 반영을 취소할까요? 1화 시작 전 상태로 돌아가고, 본문은 남아 상태 승인을 다시 하게 돼요. 그 반영이 더한 인물(마담)도 빠져요. 본문에서 등록한 장소(항구 시장)도 빠져요. 아직 안 쓴 화 플롯에 나오거나 직접 고친 장소는 남아요.")
        #expect(ReviewText.revertDone(1, fin: ReviewText.finalized(from: 1, sample)) == "1화의 반영을 취소했어요. 1화 변경안을 다시 골라 적용하세요")
    }
}

// MARK: 화면 상태

final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: FeatureReview.Project
    var loads = 0
    var saved = 0
    init(_ p: FeatureReview.Project) { project = p }
    func load(_ name: String) async throws -> FeatureReview.Project { loads += 1; return project }
    func save(_ name: String, _ p: FeatureReview.Project, merged: [String], force: Bool) async throws -> SaveResult {
        saved += 1
        project = p
        return SaveResult(project: p, kept: [])
    }
}

final class FakeJobs: JobServing, @unchecked Sendable {
    var pendingList = PendingList()
    var started: [JobRequest] = []
    var dropped: [String] = []
    func listJobs() async throws -> [Job] { [] }
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        started.append(request)
        return (Job(id: "j", project: project, kind: request.kind, ep: request.ep, label: "상태 변경안"), false)
    }
    func stopJob(_ id: String) async throws -> Job { Job(id: id, project: "", kind: "", label: "") }
    func pending(_ project: String) async throws -> PendingList { pendingList }
    func dropPending(_ project: String, key: String, failure: Bool) async throws { dropped.append(key) }
}

final class FakeReview: ReviewService, @unchecked Sendable {
    let store: FakeStore
    var applied: [(Int, StateDelta)] = []
    var restated: [(Int, StateDelta)] = []
    var kept: [Int] = []
    var reverted: [Int] = []
    var error: CanonError?
    init(_ store: FakeStore) { self.store = store }

    func apply(_ project: String, ep: Int, delta: StateDelta) async throws {
        if let error { throw error }
        applied.append((ep, delta))
        store.project.episodes?[ep - 1].status = .finalized
    }
    func restate(_ project: String, ep: Int, delta: StateDelta) async throws { restated.append((ep, delta)) }
    func keepState(_ project: String, ep: Int) async throws { kept.append(ep) }
    func revert(_ project: String, after: Int) async throws {
        reverted.append(after)
        store.project.episodes?[after].status = .written
    }
    func preview(_ project: String, ep: Int, delta: StateDelta) async throws -> RelationPreview {
        .init(words: "\(delta.events?.count ?? 0)", numbers: "", showNumbers: false, before: .init(words: "", numbers: "", showNumbers: false))
    }
    func setShowNumbers(_ project: String, _ show: Bool) async throws {}
}

func pendingState(_ d: StateDelta, id: String = "s1", base: String?) throws -> PendingList {
    let value = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(d))
    return PendingList(results: ["state:2": PendingResult(key: "state:2", id: id, kind: "state", ep: 2, label: "2화 상태 변경안", result: value, base: base)])
}

@MainActor
@Suite struct ReviewModelTests {
    func make(base: String? = "2화 본문") async throws -> (ReviewModel, FakeStore, FakeJobs, FakeReview) {
        let store = FakeStore(sample)
        let doc = ProjectDocument(name: "등대", store: store)
        let jobs = FakeJobs()
        jobs.pendingList = try pendingState(sampleDelta, base: base)
        let center = JobCenter(service: jobs)
        await center.open(doc)
        let review = FakeReview(store)
        let model = ReviewModel(document: doc, jobs: center, service: review)
        await model.start()
        return (model, store, jobs, review)
    }

    @Test func opensWrittenEpisodeWithProposal() async throws {
        let (model, _, _, _) = try await make()
        #expect(model.ep == 2)
        #expect(model.draft?.summary == "2화 요약")
        #expect(model.pickedCount == 13 && model.total == 15)
        #expect(!model.textChanged && !model.edited)
        await model.refreshPreview()
        #expect(model.preview?.words == "1")
    }

    @Test func warnsWhenTextChangedAfterProposal() async throws {
        let (model, _, _, _) = try await make(base: "고치기 전 2화")
        #expect(model.textChanged)
        #expect(model.applyReasons.contains("변경안을 만든 뒤 본문을 고쳤어요."))
    }

    @Test func appliesOnlyPickedEditsThenDropsAndReloads() async throws {
        let (model, store, jobs, review) = try await make()
        model.toggle("e0")
        model.edit { $0.newFacts?[1] = "등대지기는 남쪽으로 떠났다"; $0.summary = "고친 요약" }
        #expect(model.edited)
        let loads = store.loads
        #expect(await model.apply())
        let sent = try #require(review.applied.first)
        #expect(sent.0 == 2)
        #expect(sent.1.events == [])
        #expect(sent.1.newFacts == ["등대는 북쪽에 있다", "등대지기는 남쪽으로 떠났다"])
        #expect(sent.1.summary == "고친 요약")
        #expect(sent.1.characterUpdates?.map(\.characterId) == ["dh"])
        #expect(jobs.dropped == ["state:2"])
        #expect(store.loads > loads)
        #expect(model.draft == nil)
        #expect(model.episode?.status == .finalized)
        #expect(model.notice?.text == "2화를 마쳤어요")
        #expect(model.nextWrite == 3)
    }

    @Test func applyFailureKeepsProposal() async throws {
        let (model, _, jobs, review) = try await make()
        review.error = .server(status: 400, message: "1화가 반영되지 않았어요", code: nil)
        #expect(await model.apply() == false)
        #expect(model.draft != nil && jobs.dropped.isEmpty)
        #expect(model.notice?.isError == true)
    }

    @Test func extractStartsStateJob() async throws {
        let (model, _, jobs, _) = try await make()
        await model.extract()
        #expect(jobs.started == [JobRequest(kind: "state", ep: 2)])
    }

    @Test func discardDropsResult() async throws {
        let (model, _, jobs, _) = try await make()
        await model.discard()
        #expect(model.draft == nil && jobs.dropped == ["state:2"])
    }

    @Test func revertBringsBackHistory() async throws {
        let (model, _, _, review) = try await make()
        model.select(1)
        #expect(model.canRevert)
        #expect(model.history?.summary == "1화 요약")
        #expect(await model.revert())
        #expect(review.reverted == [0])
        #expect(model.fromHistory && model.draft?.summary == "1화 요약")
        #expect(model.notice?.text == "1화의 반영을 취소했어요. 1화 변경안을 다시 골라 적용하세요")
    }

    @Test func restateSendsPickedOnly() async throws {
        let store = FakeStore(sample)
        store.project.episodes?[1].status = .finalized
        store.project.episodes?[1].finalText = "고치기 전 2화"
        let doc = ProjectDocument(name: "등대", store: store)
        let jobs = FakeJobs()
        jobs.pendingList = try pendingState(sampleDelta, base: nil)
        let center = JobCenter(service: jobs)
        await center.open(doc)
        let review = FakeReview(store)
        let model = ReviewModel(document: doc, jobs: center, service: review, ep: 2)
        await model.start()
        #expect(ReviewText.editedAfterFinal(model.episode))
        #expect(model.restatePicks == ["sum", "f1", "p0", "l0"])
        model.toggleRestate("sum")
        model.toggleRestate("p0")
        #expect(await model.applyRestate())
        let body = try #require(review.restated.first?.1)
        #expect(body.summary == "" && body.newFacts == ["등대지기는 떠났다"] && body.foreshadowPlanted == [] && body.newPlaces?.count == 1)
        #expect(model.notice?.text == "2화 새 사실 1건, 새 장소 1곳을 반영했어요")
        #expect(jobs.dropped == ["state:2"])
    }

    @Test func keepStateClearsMark() async throws {
        let (model, _, _, review) = try await make()
        model.select(1)
        #expect(await model.keepState())
        #expect(review.kept == [1])
        #expect(model.notice?.text == "1화 상태는 그대로 둘게요")
    }

    @Test func savesUnsavedChangesFirst() async throws {
        let (model, store, _, review) = try await make()
        model.document.edit { $0.facts = ["새 사실"] }
        #expect(await model.apply())
        #expect(store.saved == 1 && review.applied.count == 1)
    }
}
