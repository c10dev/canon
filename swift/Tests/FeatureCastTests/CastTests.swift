import CanonCore
import FeatureCast
import Foundation
import Testing

// 서버 응답 모양 그대로 (snake_case). 1화 시작 전 · 1화 반영 뒤 두 시점, 인물 셋.
let projectJSON = """
{"meta": {"title": "등대", "target_episodes": 12, "form": "short"},
 "characters": [
  {"id": "ally", "name": "서윤", "role": "조력자", "tier": "support"},
  {"id": "hero", "name": "도현", "role": "주인공", "tier": "main"},
  {"id": "inn", "name": "여관 주인", "role": "단역", "tier": "minor", "first_ep": 2}],
 "arc": [{"name": "기", "start_ep": 1, "end_ep": 3, "goal": "시작"}, {"name": "승", "start_ep": 4, "end_ep": 6, "goal": "갈등"}],
 "episodes": [
  {"plot": {"number": 1, "act": "기", "title": "다리 위에서", "summary": "", "events": [], "characters": ["hero", "ally"], "emotional_shift": "", "ending_hook": "", "pov": "hero"}, "status": "finalized"},
  {"plot": {"number": 2, "act": "기", "title": "여관", "summary": "", "events": [], "characters": ["hero", "inn"], "emotional_shift": "", "ending_hook": ""}, "status": "confirmed"}],
 "events": [
  {"episode": 1, "actor": "hero", "target": "ally", "kind": "도움", "intensity": 3, "quote": "손을 내밀었다"},
  {"episode": 1, "actor": "ally", "target": "hero", "kind": "거절", "intensity": 1}],
 "settings": {"show_numbers": false}}
"""

func tie(_ s: String, _ t: String, _ w: Double, _ word: String, trust: Double = 0.5, fam: Double = 0) -> String {
    """
    {"source": "\(s)", "target": "\(t)", "stage": "낯섦", "warmth": \(w), "trust": \(trust), "evidence": 0.0, "grievance": 0.0,
     "status": 0.0, "familiarity": \(fam), "warmth_word": "\(word)", "trust_word": "의심하고 있다"}
    """
}

let castJSON = """
{"frames": [
  {"episode": 0, "ties": [\(tie("ally", "hero", 0.0, "무덤덤하다")), \(tie("hero", "ally", 0.1, "무덤덤하다"))],
   "pairs": [{"a": "hero", "b": "ally", "type": "동료", "description": "", "goal_conflict": 0.0, "tension": 1.0, "tension_word": "낮음"}],
   "triads": [], "secrets": [], "states": [{"character_id": "hero", "emotional_state": "불안", "knows": []}]},
  {"episode": 1, "ties": [\(tie("ally", "hero", -0.25, "반감이 있다", trust: 0.42, fam: 0.1)), \(tie("hero", "ally", 0.62, "깊이 아낀다", trust: 0.71, fam: 0.1))],
   "pairs": [{"a": "hero", "b": "ally", "type": "동료", "description": "", "goal_conflict": 0.0, "tension": 5.25, "tension_word": "높음"}],
   "triads": [["hero", "ally", "inn"]], "secrets": [{"id": "s1", "owner": "ally", "content": "편지를 숨겼다", "hidden_from": ["hero"]}],
   "states": [{"character_id": "hero", "emotional_state": "결심", "current_goal": "등대로", "knows": ["편지"]}]}],
 "appearances": {"hero": [{"n": 1, "status": "finalized", "pov": true}, {"n": 2, "status": "confirmed", "pov": false}],
                 "ally": [{"n": 1, "status": "finalized", "pov": false}], "inn": [{"n": 2, "status": "confirmed", "pov": false}]},
 "timelines": {"hero": [{"n": 1, "title": "다리 위에서", "appears": true, "pov": true,
                         "changes": {"emotional_state": "결심", "knows": ["편지"]},
                         "events": [{"episode": 1, "actor": "hero", "target": "ally", "kind": "도움", "intensity": 3}],
                         "secrets": [], "new": false}],
               "ally": [], "inn": []}}
"""

func decode<T: Decodable>(_ s: String) -> T {
    try! JSONDecoder().decode(T.self, from: Data(s.utf8))
}

struct FakeSource: CastSource {
    var error: CanonError?

    func project(_ name: String) async throws -> CastProject {
        if let error { throw error }
        return decode(projectJSON)
    }

    func cast(_ name: String) async throws -> CastSummary {
        if let error { throw error }
        return decode(castJSON)
    }
}

final class MemoryStore: CastLayoutStore {
    var saved: [String: [String: CastPoint]] = [:]

    func load(_ project: String) -> [String: CastPoint] { saved[project] ?? [:] }
    func save(_ project: String, _ positions: [String: CastPoint]) { saved[project] = positions }
}

@Suite struct CastTextTests {
    /// 경계는 dynamics.warmth_word 와 같다: 값이 경계보다 작으면 그 구간.
    @Test func warmthBands() {
        #expect(WarmthBand.of(-0.61).word == "적대한다")
        #expect(WarmthBand.of(-0.6).word == "반감이 있다")
        #expect(WarmthBand.of(-0.2).word == "무덤덤하다")
        #expect(WarmthBand.of(0.19).word == "무덤덤하다")
        #expect(WarmthBand.of(0.2).word == "호감이 있다")
        #expect(WarmthBand.of(0.6).word == "깊이 아낀다")
        #expect(WarmthBand.of(1).hex == 0x1C5CAB)
    }

    @Test func serverWordsMatchBands() {
        let cast: CastSummary = decode(castJSON)
        for t in cast.frames.flatMap(\.ties) {
            #expect(WarmthBand.of(t.warmth).word == t.warmthWord)
        }
    }

    @Test func tieAndTension() {
        let cast: CastSummary = decode(castJSON)
        let t = cast.frames[1].ties[1]
        #expect(CastText.tie(t, numbers: false) == "깊이 아낀다, 의심하고 있다 · 단계 낯섦")
        #expect(CastText.tie(t, numbers: true) == "온기 +0.62 · 신뢰 0.71 (증거 0.0) · 원한 0.00 · 서열 +0.00 · 친숙 0.10 · 단계 낯섦")
        #expect(CastText.tie(cast.frames[1].ties[0], numbers: true).hasPrefix("온기 -0.25 · 신뢰 0.42"))
        #expect(CastText.tie(nil, numbers: false) == "아직 관계가 없어요")
        #expect(CastText.tension(cast.frames[1].pairs[0], numbers: false) == "긴장 높음")
        #expect(CastText.tension(cast.frames[1].pairs[0], numbers: true) == "긴장 5.3/10")
        // JS toFixed 와 같다: (-0).toFixed(2) '0.00', (-0.001).toFixed(2) '-0.00', (5.25).toFixed(1) '5.3', (0.285).toFixed(2) '0.28'
        #expect(CastText.fixed(-0.0, 2) == "0.00")
        #expect(CastText.fixed(-0.001, 2) == "-0.00")
        #expect(CastText.fixed(5.25, 1) == "5.3")
        #expect(CastText.fixed(-5.25, 1) == "-5.3")
        #expect(CastText.fixed(0.285, 2) == "0.28")
        #expect(CastText.fixed(0.125, 2) == "0.13")
        #expect(CastText.tensionHex("낮음") == nil)
        #expect(CastText.tensionHex("매우 높음") == 0xB42318)
    }

    @Test func labels() {
        #expect(CastText.frameLabel(0, title: "무시") == "1화 시작 전")
        #expect(CastText.frameLabel(3, title: "다리 위에서") == "3화 반영 뒤 · 다리 위에서")
        #expect(CastText.frameLabel(3, title: nil) == "3화 반영 뒤")
        let cast: CastSummary = decode(castJSON)
        let apps = cast.appearances.additionalProperties["hero"]!
        #expect(CastText.appearance(apps, firstEp: 0) == "플롯 등장 2화 (1~2화) · 시점 인물 1화")
        #expect(CastText.appearance([], firstEp: 2) == "플롯에 나오는 화가 아직 없어요 · 2화에 처음 등장")
        #expect(CastText.intensity(3) == "결정적")
        #expect(CastText.intensity(nil) == "보통")
    }

    @Test func timelineRows() {
        let cast: CastSummary = decode(castJSON)
        let row = cast.timelines.additionalProperties["hero"]![0]
        let bits = CastText.changes(row)
        #expect(bits.map(\.label) == ["감정", "알게 됨"])
        #expect(bits.map(\.text) == ["결심", "편지"])
        let e = row.events[0]
        let name = { (id: String) in id == "hero" ? "도현" : "서윤" }
        #expect(CastText.event(e, name: name) == "도현 → 서윤 · 도움 결정적")
        #expect(CastText.event(e, name: name, viewer: "inn") == "도현 → 서윤 · 도움 결정적 (목격)")
        #expect(CastText.isGood(e))
    }

    @Test func windows() {
        #expect(CastText.chartWindow(count: 10, at: 3, all: false) == 0...9)
        #expect(CastText.chartWindow(count: 100, at: 50, all: false) == 35...65)
        #expect(CastText.chartWindow(count: 100, at: 99, all: false) == 69...99)
        #expect(CastText.chartWindow(count: 100, at: 2, all: false) == 0...30)
        #expect(CastText.chartWindow(count: 100, at: 50, all: true) == 0...99)
        #expect(CastText.stripStep(40) == 14 && CastText.stripStep(41) == 6 && CastText.stripStep(300) == 3)
        #expect(CastText.tableStep(20) == 18 && CastText.tickEvery(8) == 5 && CastText.tickEvery(6) == 10)
    }

    @Test func shownTimeline() {
        let rows: [CastTimelineRow] = (1...50).map {
            CastTimelineRow(n: $0, title: "", appears: true, pov: false, changes: .init(), events: [], secrets: [], new: false)
        }
        #expect(CastText.shownTimeline(rows, at: 20, all: false).map(\.n) == Array(10...30))
        #expect(CastText.shownTimeline(rows, at: 0, all: false).map(\.n) == Array(21...50))
        #expect(CastText.shownTimeline(rows, at: 20, all: true).count == 50)
    }

    @Test func tableOrderAndBands() {
        let p: CastProject = decode(projectJSON)
        let cast: CastSummary = decode(castJSON)
        let order = CastText.tableOrder(p.characters!) { cast.appearances.additionalProperties[$0] ?? [] }
        #expect(order.map(\.id) == ["hero", "ally", "inn"])
        #expect(CastText.bands(p, serial: false) == [.init(start: 1, end: 3, label: "기", tone: 1), .init(start: 4, end: 6, label: "승", tone: 2)])
        #expect(CastText.status("written") == "본문 작성됨")
    }
}

@MainActor
@Suite struct CastModelTests {
    func loaded(_ store: MemoryStore = MemoryStore()) async -> CastModel {
        let m = CastModel(name: "등대", source: FakeSource(), store: store)
        await m.load()
        return m
    }

    @Test func loadPicksLastFrameAndMain() async {
        let m = await loaded()
        #expect(m.error == nil)
        #expect(m.frameIndex == 1)
        #expect(m.selection == .character("hero"))
        #expect(m.label(m.frame) == "1화 반영 뒤 · 다리 위에서")
        #expect(m.totalEpisodes == 12)
        #expect(m.name("inn") == "여관 주인")
        #expect(m.name("ghost") == "ghost")
        #expect(m.partners("hero") == ["ally"])
        #expect(m.events("hero", "ally").count == 2)
    }

    @Test func offline() async {
        let m = CastModel(name: "등대", source: FakeSource(error: .offline), store: MemoryStore())
        await m.load()
        #expect(m.error == CanonError.offline.errorDescription)
    }

    @Test func stepsAndPresence() async {
        let m = await loaded()
        m.step(-5)
        #expect(m.frameIndex == 0)
        #expect(m.playLabel == "여기서 재생")
        let inn = m.character("inn")!
        #expect(!m.present(inn))
        m.go(9)
        #expect(m.frameIndex == 1)
        #expect(m.playLabel == "처음부터 재생")
    }

    @Test func playRunsToEnd() async throws {
        let m = await loaded()
        m.playInterval = .milliseconds(10)
        m.togglePlay()
        #expect(m.frameIndex == 0)
        #expect(m.playLabel == "멈춤")
        for _ in 0..<100 where m.playing { try await Task.sleep(for: .milliseconds(10)) }
        #expect(!m.playing)
        #expect(m.frameIndex == 1)
    }

    @Test func minorHiddenUnlessPicked() async {
        let m = await loaded()
        m.showMinor = false
        #expect(m.shownCharacters.map(\.id) == ["ally", "hero"])
        m.pick(.character("inn"))
        #expect(m.shownCharacters.map(\.id) == ["ally", "hero", "inn"])
    }

    @Test func layoutStaysInsideAndSaves() async {
        let store = MemoryStore()
        let m = await loaded(store)
        let pos = m.layout()
        #expect(pos.count == 3)
        for p in pos.values {
            #expect((70...690).contains(p.x) && (40...490).contains(p.y))
        }
        #expect(m.layout() == pos)  // 결정적
        m.move("hero", to: CastPoint(x: 5, y: 900))
        #expect(m.layout()["hero"] == CastPoint(x: 30, y: 510))
        m.endMove()
        #expect(store.saved["등대"]?["hero"] == CastPoint(x: 30, y: 510))
        let again = await loaded(store)
        #expect(again.layout()["hero"] == CastPoint(x: 30, y: 510))
        again.resetPositions()
        #expect(again.layout() == pos)
        #expect(store.saved["등대"] == [:])
    }

    @Test func sceneAndHits() async {
        let m = await loaded()
        let s = m.scene()
        #expect(s.edges.count == 2)
        #expect(s.tensions.count == 1)  // 높음만 그린다
        #expect(s.edges.first { $0.source == "hero" }!.band == 4)
        let hero = s.nodes.first { $0.id == "hero" }!
        #expect(CastHit.find(hero.at, model: s) == .character("hero"))
        #expect(CastHit.node(CastPoint(x: hero.at.x + 21, y: hero.at.y), model: s) == "hero")
        let mid = s.edges[0].curve.point(0.3)
        #expect(CastHit.find(mid, model: s) == .pair("ally", "hero"))
        #expect(CastHit.find(CastPoint(x: -100, y: -100), model: s) == nil)
    }

    @Test func pickKeepsSelectionOnReload() async {
        let m = await loaded()
        m.pick(.pairOf("hero", "ally"))
        #expect(m.selection == .pair("ally", "hero"))
        await m.load()
        #expect(m.selection == .pair("ally", "hero"))
        m.open("inn")
        #expect(m.tab == .graph && m.selection == .character("inn"))
    }
}
