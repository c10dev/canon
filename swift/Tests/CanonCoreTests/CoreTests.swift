import CanonCore
import Foundation
import Testing

@Suite struct ServerConfigTests {
    @Test func parsesAddresses() {
        #expect(ServerConfig.parse(" 127.0.0.1:8000/ ")?.baseURL.absoluteString == "http://127.0.0.1:8000")
        #expect(ServerConfig.parse("https://canon.tail1234.ts.net")?.baseURL.absoluteString == "https://canon.tail1234.ts.net")
        #expect(ServerConfig.parse("") == nil)
        #expect(ServerConfig.parse("ftp://x") == nil)
    }

    @Test func clientIDLooksLikeWeb() {
        let id = ClientIdentity.make(now: Date(timeIntervalSince1970: 1_800_000_000))
        #expect(id.count == 8 + String(Int64(1_800_000_000_000), radix: 36).count)
        #expect(id.allSatisfy { $0.isLowercase || $0.isNumber })
    }
}

@Suite struct ErrorTests {
    @Test func readsDetailText() {
        let e = CanonError.from(status: 409, body: Data(#"{"detail":"다른 탭이나 기기에서 이 작품을 먼저 저장했어요"}"#.utf8))
        #expect(e.isConflict)
        #expect(e.errorDescription == "다른 탭이나 기기에서 이 작품을 먼저 저장했어요")
    }

    @Test func readsValidationList() {
        let body = #"{"detail":[{"loc":["body","meta","title"],"msg":"Field required"}]}"#
        #expect(CanonError.from(status: 422, body: Data(body.utf8)).errorDescription == "입력 형식이 맞지 않아요 (칸: meta.title): Field required")
    }

    @Test func fallsBackToStatus() {
        #expect(CanonError.from(status: 500, body: Data("oops".utf8)).errorDescription == "요청 실패 (500)")
        #expect(CanonError.offline.status == 0)
    }
}

@Suite struct KoreanTextTests {
    @Test func josa() {
        #expect(KoreanText.josa("설정 제안", "이", "가") == "이")
        #expect(KoreanText.josa("3화 본문", "이", "가") == "이")
        #expect(KoreanText.josa("부 구성", "은", "는") == "은")
        #expect(KoreanText.josa("아크 2", "이", "가") == "가")
        #expect(KoreanText.josa("아크 3", "이", "가") == "이")
        #expect(KoreanText.josa("AI", "이", "가") == "이(가)")
        #expect(KoreanText.josa(" ", "이", "가") == "")
    }

    @Test func episodeRange() {
        #expect(KoreanText.episodeRange(3, 3) == "3화")
        #expect(KoreanText.episodeRange(1, 12) == "1~12화")
    }

    @Test func dates() {
        let seoul = TimeZone(identifier: "Asia/Seoul")!
        let iso = "2026-10-26T05:04:03.123456+00:00"  // Python isoformat
        #expect(KoreanText.date(iso, timeZone: seoul) == "2026.10.26")
        #expect(KoreanText.dateTime(iso, timeZone: seoul) == "2026.10.26 14:04")
        #expect(KoreanText.date("모름") == "모름")
    }

    @Test func statusLabels() {
        #expect(EpisodeStatus.written.label == "본문 작성됨")
        #expect(EpisodeStatus.written.waiting == "상태 승인 대기")
    }
}

@Suite struct APIPathTests {
    @Test func encodesProjectName() {
        #expect(APIPath.project("등대 1") == "/api/projects/%EB%93%B1%EB%8C%80%201")
        #expect(APIPath.project("a/b", "jobs") == "/api/projects/a%2Fb/jobs")
    }
}

@Suite struct JobTrackerTests {
    func job(_ id: String, _ status: Job.Status = .running, done: Int = 0, project: String = "등대") -> Job {
        Job(id: id, project: project, kind: "write", ep: 3, label: "3화 본문", total: 1, done: done, status: status)
    }

    @Test func oldFinishedJobsStayQuiet() {
        var t = JobTracker()
        #expect(t.received([job("a", .done)]).isEmpty)
        #expect(t.jobs.isEmpty)
        #expect(t.pollInterval == nil)
    }

    @Test func reportsProgressAndFinish() {
        var t = JobTracker()
        #expect(t.received([job("a")]) == [.progressed(job("a"))])
        #expect(t.pollInterval == .milliseconds(1500))
        #expect(t.received([job("a")]).isEmpty)
        #expect(t.received([job("a", done: 1)]) == [.progressed(job("a", done: 1))])
        #expect(t.received([job("a", .done, done: 1)]) == [.finished(job("a", .done, done: 1))])
        #expect(t.received([job("a", .done, done: 1)]).isEmpty)
        t.dismiss("a")
        #expect(t.jobs.isEmpty)
    }

    @Test func reportsJobsLostToRestart() {
        var t = JobTracker()
        _ = t.received([job("a"), job("b")])
        t.failed()
        #expect(t.pollInterval == .seconds(4))
        #expect(t.received([job("b")]) == [.lost([job("a")])])
        #expect(!t.offline)
    }

    @Test func noticeText() {
        // 이 작품의 작업은 작업마다 정한 문구 (웹 JOB_DONE_MSG), 목록에 없는 작업은 '<이름>이 끝났어요'
        #expect(JobText.notice(.finished(job("a", .done)), currentProject: "등대")?.text == JobText.done(job("a", .done)))
        var write = job("a", .done)
        write.kind = "write"
        write.ep = 3
        #expect(JobText.done(write) == "3화 본문을 저장했어요.")
        write.result = .object(["candidate": .object(["text": .string("새 판")])])
        #expect(JobText.done(write) == "3화 새 판이 나왔어요. 지금 판과 비교해 고르세요.")
        write.result = .object(["candidate": .null])
        #expect(JobText.done(write) == "3화 본문을 저장했어요.")
        var other = job("a", .done)
        other.kind = "hook"
        #expect(JobText.done(other) == "3화 본문이 끝났어요")
        #expect(JobText.notice(.finished(job("a", .done)), currentProject: nil)?.text == "등대 · 3화 본문이 끝났어요. 그 작품을 열면 결과가 보여요")
        var failed = job("a", .error)
        failed.error = "키가 없어요"
        #expect(JobText.notice(.finished(failed), currentProject: "등대")! == ("3화 본문 실패: 키가 없어요", true))
        #expect(JobText.notice(.finished(job("a", .cancelled)), currentProject: "등대") == nil)
    }
}

@Suite struct ScreenTests {
    @Test func sidebarMatchesWeb() {
        #expect(Screen.allCases.filter { $0.group == .steps }.map { $0.label(serial: false) }
            == ["작품 홈", "설정 도우미", "문체 레퍼런스", "기승전결 · 플롯", "집필", "검수", "상태 승인"])
        #expect(Screen.arc.label(serial: true) == "부 · 아크 · 플롯")
        #expect(Screen.allCases.filter { $0.group == .autoRun } == [.auto])
        #expect(Screen.allCases.filter { $0.group == .tools }.map { $0.label(serial: false) }
            == ["인물 · 관계도", "지도", "복선 센터", "상태창 수치", "스킬 도감", "작품 속 시간", "이야기 줄기", "인과율", "갈래 비교", "작업지시서 (API 없이)"])
        #expect(Screen.allCases.count == 20)
    }
}

/// 새 작품 마법사. 기대값은 웹 `tests/test_setup_wizard_js.py` 와 같은 사례.
@Suite struct SetupWizardTests {
    typealias W = SetupWizard

    static func full() -> W.Input {
        W.Input(title: "소금 정원의 계약", genres: ["romance_fantasy"], logline: "서윤이 염전을 되찾으려 한다.", setting: "북방 왕국",
                characters: [.init(id: "hero", name: "서윤"), .init(id: "char2", name: "이헌")],
                relationships: [.init(a: "hero", b: "char2", type: "계약 부부")])
    }

    @Test func reqsFollowEachField() {
        var oneName = Self.full()
        oneName.characters[1].name = "  "
        var selfRel = Self.full()
        selfRel.relationships = [.init(a: "hero", b: "hero")]
        var ghostRel = Self.full()
        ghostRel.relationships = [.init(a: "hero", b: "gone")]
        #expect(W.reqs(W.Input()) == Array(repeating: false, count: 6))
        #expect(W.reqs(Self.full()) == Array(repeating: true, count: 6))
        #expect(W.reqs(oneName) == [true, true, true, true, false, true])
        #expect(W.reqs(selfRel) == [true, true, true, true, true, false])
        #expect(W.reqs(ghostRel) == [true, true, true, true, true, false])
        #expect(W.gaps(selfRel) == ["관계 1개"])
        #expect(W.meter(oneName) == "필수 5/6")
    }

    @Test func firstGapAndStepState() {
        var noWorld = Self.full()
        noWorld.setting = ""
        #expect(W.firstGap(W.Input()) == 0)
        #expect(W.firstGap(noWorld) == 2)
        #expect(W.firstGap(Self.full()) == 5)
        // 세계를 비웠다: 들른 세계 걸음은 주황, 들르지 않은 마무리는 아직
        #expect((0...5).map { W.stepState(noWorld, $0, seen: [0, 1, 2]).rawValue } == ["done", "done", "miss", "done", "done", ""])
        // 빈 작품: 지금 걸음(0)도 들른 걸음이라 주황, 나머지는 아직
        #expect((0...5).map { W.stepState(W.Input(), $0, seen: [0]).rawValue } == ["miss", "", "", "", "", ""])
        #expect(W.stepLabel(2, .miss) == "3. 세계, 빈 필수 칸 있음")
        #expect(W.stepLabel(0, .done) == "1. 제목 · 장르, 채움")
    }

    @Test func worldKindKeepsWrittenText() {
        let a = W.withWorldKind("", "서양풍 제국")
        let b = W.withWorldKind(a + " 북쪽 끝에 염전이 있다.", "중세 판타지 왕국")
        let c = W.withWorldKind(b, "중세 판타지 왕국")
        let d = W.withWorldKind("직접 쓴 배경.", "현대 한국")
        #expect([a, W.worldKind(of: a), b, W.worldKind(of: b), c, W.worldKind(of: c), d, W.worldKind(of: "아무 글")] == [
            "귀족과 황실이 다스리는 서양풍 제국.", "서양풍 제국",
            "검과 마법이 있는 중세풍 왕국. 북쪽 끝에 염전이 있다.", "중세 판타지 왕국",
            "북쪽 끝에 염전이 있다.", "",
            "지금의 한국. 직접 쓴 배경.", "",
        ])
        #expect(W.withEra("중세풍", "중세풍") == "")
        #expect(W.withEra("", "조선") == "조선")
    }

    @Test func worldRecsFollowGenreOrder() {
        #expect(W.worldRecs(["romance_fantasy", "fantasy"], eras: false) == ["서양풍 제국", "중세 판타지 왕국"])
        #expect(W.worldRecs(["romance_fantasy", "fantasy"], eras: true) == ["중세풍", "근세풍"])
        #expect(W.worldRecs(["bl"], eras: false) == [])
        #expect(W.worldRecs([], eras: true) == [])
    }

    @Test func recsNameRealChoices() {
        let kinds = Set(W.worldKinds.map(\.label))
        #expect(W.worldRec.values.flatMap(\.kinds).filter { !kinds.contains($0) } == [])
        #expect(W.worldRec.values.flatMap(\.eras).filter { !W.eras.contains($0) } == [])
        #expect(W.required.count == W.reqs(W.Input()).count)
    }

    @Test func summaryNamesPeople() {
        var p = Self.full()
        p.relationships.append(.init(a: "hero", b: "hero"))
        p.relationships.append(.init(a: "char2", b: "gone"))
        #expect(W.summary(p) { $0 == "romance_fantasy" ? "로맨스 판타지" : $0 } == [
            "소금 정원의 계약", "로맨스 판타지", "서윤이 염전을 되찾으려 한다.", "북방 왕국", "서윤, 이헌", "서윤 ↔ 이헌 · 계약 부부 / 이헌 ↔ gone",
        ])
    }
}
