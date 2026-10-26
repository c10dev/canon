import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureHome
import Testing

typealias Ep = Components.Schemas.Episode

func ep(_ n: Int, _ status: Ep.StatusPayload, auto: Bool = false) -> Ep {
    Ep(plot: .init(number: n, act: .기, title: "\(n)화 제목", summary: "", events: [], characters: [], emotionalShift: "", endingHook: ""),
       status: status, auto: auto)
}

func short(_ eps: [Ep], arc: Bool = true) -> Project {
    let acts: [Components.Schemas.Act] = arc ? [
        .init(name: .기, startEp: 1, endEp: 1, goal: ""), .init(name: .승, startEp: 1, endEp: 2, goal: ""),
        .init(name: .전, startEp: 3, endEp: 3, goal: ""), .init(name: .결, startEp: 4, endEp: 4, goal: ""),
    ] : []
    return Project(meta: .init(title: "", genre: "미스터리", adult: true, targetEpisodes: 4, wordsPerEpisode: 5000),
                   characters: [.init(id: "c1", name: "서연", role: "주인공")], arc: acts, episodes: eps,
                   states: [.init(characterId: "c1", emotionalState: "불안", location: "등대")],
                   facts: (1...10).map { "사실 \($0)" },
                   foreshadows: [.init(id: "fs-1", description: "열쇠", plantedEp: 1), .init(id: "fs-2", description: "편지", plantedEp: 2, status: .resolved)])
}

@Suite struct HomeSummaryTests {
    @Test func header() {
        let s = HomeSummary(short([ep(1, .finalized), ep(2, .written)]), name: "lighthouse")
        #expect(s.title == "lighthouse")
        #expect(s.subtitle == "미스터리 · 성인 · 전 4화 · 화당 5,000자")
    }

    @Test func nextStepFollowsCurrentEpisode() {
        #expect(HomeSummary(short([ep(1, .finalized), ep(2, .written)]), name: "x").next == .init(label: "2화 상태 승인", screen: .review))
        #expect(HomeSummary(short([ep(1, .finalized), ep(2, .confirmed)]), name: "x").next == .init(label: "2화 쓰기", screen: .write))
        #expect(HomeSummary(short([ep(1, .draft)]), name: "x").next == .init(label: "1화 플롯 확정", screen: .arc))
        #expect(HomeSummary(short([ep(1, .finalized)]), name: "x").next == .init(label: "완결 원고 보기", screen: .write))
        #expect(HomeSummary(short([], arc: false), name: "x").next == .init(label: "기승전결 · 플롯 만들기", screen: .arc))
        var none = short([])
        none.characters = []
        #expect(HomeSummary(none, name: "x").next == .init(label: "설정 시작", screen: .setup))
    }

    @Test func stages() {
        let s = HomeSummary(short([ep(1, .finalized), ep(2, .written), ep(3, .confirmed), ep(4, .draft)]), name: "x")
        #expect(s.stages.map(\.state) == [.done, .notStarted, .done, .doing, .doing, .doing])
        #expect(s.stages.map(\.detail) == ["인물 1 · 관계 0", "선택 사항", "4구간", "3 / 4화", "2 / 4화", "1 / 4화"])
        #expect(s.stages.map(\.state.label).first == "완료")
    }

    @Test func cells() {
        let s = HomeSummary(short([ep(1, .finalized, auto: true), ep(2, .written), ep(3, .confirmed), ep(4, .draft)]), name: "x")
        #expect(s.cells.map(\.label) == ["자동 반영", "작성됨", "확정", "초안"])
        #expect(s.cells.map(\.screen) == [.write, .review, .write, .arc])
        #expect(s.cells.map(\.current) == [false, true, false, false])
        #expect(s.cells[1].accessibilityLabel == "2화 작성됨 · 지금 화 · 2화 제목")
        #expect(s.cells.map(\.act) == ["기", "승", "전", "결"])  // 2화는 기(1~1화)가 아니라 승(1~2화), 웹 actOf 처럼 처음 맞는 구간
        #expect(s.bands.map(\.title) == ["기·승", "전", "결"])
        #expect(s.notes == ["2화 본문이 작성됐어요. 상태 변경안을 승인해야 다음 화를 쓸 수 있어요."])
    }

    @Test func cards() {
        let s = HomeSummary(short([ep(1, .finalized)]), name: "x")
        #expect(s.statesBasis == "1화 기준")
        #expect(s.characters == [.init(name: "서연", role: "주인공", lines: ["감정: 불안", "위치: 등대"])])
        #expect(s.openClues.map(\.id) == ["fs-1"])
        #expect(s.facts.first == "사실 3")
        #expect(s.factCount == 10)
    }

    @Test func serialShowsCurrentPartOnly() {
        let eps = (1...8).map { ep($0, $0 <= 5 ? .finalized : .confirmed) }
        let p = Project(meta: .init(targetEpisodes: 100, form: .serial), characters: [.init(id: "c", name: "가", role: "")],
                        parts: [.init(number: 1, title: "시작", startEp: 1, endEp: 5, goal: ""), .init(number: 2, title: "전환", startEp: 6, endEp: 100, goal: "")],
                        storyArcs: [.init(number: 1, title: "첫 아크", startEp: 1, endEp: 5, goal: "", acts: [.init(name: .기, startEp: 1, endEp: 5, goal: "")]),
                                    .init(number: 2, title: "둘째", startEp: 6, endEp: 8, goal: "", acts: [.init(name: .기, startEp: 6, endEp: 8, goal: "")])],
                        episodes: eps)
        let s = HomeSummary(p, name: "x")
        #expect(s.cells.map(\.number) == [6, 7, 8])
        #expect(s.partNote == "2부 전환 (6~100화)만 보여요. 전체는 부 · 아크에서 보세요.")
        #expect(s.bands.map(\.title) == ["아크 2"])
        #expect(s.recap == "아크 1 요약")
        #expect(s.stages[2].detail == "아크 2개 · 8화까지 · 요약 필요 2개")
        #expect(s.next == .init(label: "6화 쓰기", screen: .write))
    }
}
