import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureStyle
import Foundation
import Testing

@Suite struct StyleTextTests {
    @Test func blank() {
        #expect(StyleText.blank(nil))
        #expect(StyleText.blank(StyleProfile(narrationPov: "  ", dos: [])))
        #expect(!StyleText.blank(StyleProfile(tense: "과거형")))
        #expect(!StyleText.blank(StyleProfile(devices: [StyleDevice(name: "")])))
    }

    @Test func changeWho() {
        let base = StyleLink(state: "changed", name: "담백체", version: 3, applied: 2, baseKnown: true)
        let diff = Components.Schemas.StyleFieldDiff(key: "dos", label: "지킬 것")
        var l = base
        l.mine = [diff]
        l.theirs = [diff]
        #expect(StyleText.changeWho(l) == "이 작품도 고쳤고, 라이브러리도 2번 → 3번 버전으로 바뀌었어요")
        l.mine = []
        #expect(StyleText.changeWho(l) == "라이브러리가 2번 → 3번 버전으로 바뀌었어요. 이 작품은 그대로예요")
        #expect(StyleText.pullLabel(l) == "라이브러리 최신 버전 가져오기")
        l.theirs = []
        l.mine = [diff]
        #expect(StyleText.changeWho(l) == "이 작품에서 고쳤어요. 라이브러리는 가져온 버전 그대로예요")
        #expect(StyleText.pullLabel(l) == "라이브러리 버전으로 되돌리기")
        #expect(StyleText.diffLines(l) == ["이 작품에서 고친 칸: 지킬 것", "올리기는 작품 쪽을 라이브러리 새 버전으로, 가져오기 · 되돌리기는 라이브러리 쪽을 작품에 가져와요."])
        l.baseKnown = false
        #expect(StyleText.changeWho(l) == "이 작품은 2번 버전, 라이브러리는 3번 버전이에요")
        #expect(StyleText.pullLabel(l) == "라이브러리 최신 버전 가져오기")
        l.version = 2
        #expect(StyleText.changeWho(l) == "이 작품에서 고쳤거나 라이브러리가 바뀌었어요")
    }

    @Test func status() {
        #expect(StyleText.status(nil, blank: true) == .none(blank: true))
        #expect(StyleText.status(StyleLink(state: "missing", id: "x"), blank: false).text == "가져온 라이브러리 항목이 지워졌어요. 작품에 복사된 문체는 그대로 써요.")
        #expect(StyleText.status(StyleLink(state: "same", name: "담백체", version: 4), blank: false).text == "라이브러리와 같음 · 담백체 · 4번 버전")
    }

    @Test func questions() {
        let linked = StyleLink(state: "same", name: "담백체")
        #expect(StyleText.analyzeQuestion(StyleProfile(), link: nil) == nil)
        #expect(StyleText.analyzeQuestion(StyleProfile(samplePassages: ["문단"]), link: nil)?.hasPrefix("분석 결과로 지금 스타일 프로필을 바꿀까요?") == true)
        #expect(StyleText.analyzeQuestion(StyleProfile(), link: linked)?.hasSuffix("라이브러리 '담백체' 연결도 끊겨요. 라이브러리 항목은 그대로예요.") == true)
        #expect(StyleText.useQuestion("담백체", link: linked) == "'담백체' 문체를 이 작품에 적용할까요? 지금 작품의 스타일 프로필은 바뀌어요.")
        #expect(StyleText.useQuestion("담백체", link: nil).contains("되돌릴 수 없어요"))
        #expect(StyleText.keepNote(sample: "", link: nil) == "이 화면에 붙여 넣은 원문이 없어 원문 없이 저장돼요.")
        #expect(StyleText.pullQuestion(StyleLink(state: "changed", name: "담백체", version: 3, baseKnown: true)) == "이 작품의 문체를 라이브러리 '담백체' 3번 버전으로 바꿀까요?")
        let push = StyleText.pushNote(StyleLink(state: "changed", name: "담백체", version: 3, theirs: [.init(key: "dos", label: "지킬 것")]),
                                      usedBy: ["등대", "바다"], project: "등대")
        #expect(push.contains("다른 작품(바다)은 다시 적용하기 전까지 바뀌지 않아요."))
        #expect(push.hasSuffix("라이브러리 3번 버전에서 바뀐 칸(지킬 것)은 이 작품 값으로 덮여요."))
    }

    /// 웹 `baselineRows` 와 같은 반올림 (JS `toFixed` · `Math.round`).
    @Test func baseline() {
        let b = StyleMetrics(sentenceLenMean: 23.45, sentenceLenCv: 0.555, paragraphLenMean: 80.5, dialogueRatio: 0.125, mattr: 0.7, commaSentenceRatio: 0.333)
        #expect(StyleText.baselineRows(b).map(\.1) == ["23.4자", "0.56", "81자", "13%", "–", "0.70", "33%"])  // node: (23.45).toFixed(1) == "23.4"
        #expect(StyleText.baselineRows(b).map(\.0) == ["문장 평균 길이", "문장 길이 변화폭", "문단 평균 길이", "대사 비율", "과거형 비율", "어휘 다양도", "쉼표 문장 비율"])
    }
}

// MARK: 모델

final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: Project
    var saves = 0
    init(_ project: Project) { self.project = project }
    func load(_ name: String) async throws -> Project { project }
    func save(_ name: String, _ p: Project, merged: [String], force: Bool) async throws -> SaveResult {
        saves += 1
        project = p
        return SaveResult(project: p, kept: [])
    }
}

final class FakeStyle: StyleService, @unchecked Sendable {
    let store: FakeStore
    var link = StyleLink(state: "same", id: "s1", name: "담백체", version: 2, applied: 2)
    var kept: [Components.Schemas.StyleKeep] = []
    init(_ store: FakeStore) { self.store = store }

    func analyze(_ project: String, _ text: String) async throws -> StyleProfile { StyleProfile(narrationPov: "1인칭", samplePassages: ["문단"]) }
    func measure(_ text: String) async throws -> StyleMetrics { StyleMetrics(chars: text.count) }
    func link(_ project: String) async throws -> StyleLink { link }
    func library() async throws -> [StyleSummary] {
        [StyleSummary(id: "s1", name: "담백체", source: "", notes: "", narrationPov: "", tense: "", passages: 0, rules: 0, banned: 0, markers: 0,
                      devices: 0, sampleChars: 0, createdAt: "", updatedAt: "", version: 2, usedBy: ["등대"])]
    }
    func apply(_ project: String, styleID: String) async throws {
        store.project.style = StyleProfile(tense: "과거형")
        store.project.styleId = styleID
    }
    func keep(_ project: String, _ body: Components.Schemas.StyleKeep) async throws -> StyleSummary {
        kept.append(body)
        return try await library()[0]
    }
}

@MainActor
func makeStyle(_ p: Project) async -> (StyleModel, FakeStore, FakeStyle) {
    let store = FakeStore(p)
    let doc = ProjectDocument(name: "등대", store: store)
    let service = FakeStyle(store)
    let model = StyleModel(document: doc, service: service)
    await model.load()
    return (model, store, service)
}

@MainActor
@Suite struct StyleModelTests {
    @Test func analyzeNeedsLongSample() async {
        let (m, _, _) = await makeStyle(Project(meta: .init(title: "등대")))
        m.sample = "짧다"
        await m.analyze()
        #expect(m.notice?.text == "예시 원문을 200자 이상 넣어 주세요")
        #expect(m.project?.style == nil)
    }

    @Test func analyzeReplacesProfileAndUnlinks() async {
        let (m, _, _) = await makeStyle(Project(meta: .init(title: "등대"), styleId: "s1", styleVersion: 2))
        #expect(m.analyzeQuestion?.contains("라이브러리 '담백체' 연결도 끊겨요") == true)
        m.sample = String(repeating: "가", count: 200)
        await m.analyze()
        #expect(m.profile?.narrationPov == "1인칭")
        #expect(m.project?.styleBaseline?.chars == 200)
        #expect(m.project?.styleId == "")
        #expect(m.project?.styleVersion == 0)
        #expect(m.link?.state == "none")
        #expect(m.document.dirty)  // 저장은 사용자가 한다
    }

    @Test func useSavesFirstThenReloads() async {
        let (m, store, _) = await makeStyle(Project(meta: .init(title: "등대")))
        m.editStyle { $0.dos = ["짧게"] }
        await m.use("s1")
        #expect(store.saves == 1)
        #expect(m.profile?.tense == "과거형")
        #expect(!m.document.dirty)
        #expect(m.notice?.text == "라이브러리 문체를 적용했어요")
        await m.use("")
        #expect(m.notice?.text == "적용할 문체를 고르세요")
    }

    @Test func keepAndPush() async {
        let (m, _, service) = await makeStyle(Project(meta: .init(title: "등대")))
        #expect(!m.canKeep)
        #expect(m.defaultKeepName == "등대 문체")
        m.editStyle { $0.tense = "과거형" }
        #expect(m.canKeep)
        m.sample = "원문"
        await m.keep(as: " 담백체 ")
        #expect(service.kept.first?.name == "담백체")
        #expect(service.kept.first?.sample == "원문")
        #expect(m.notice?.text == "라이브러리에 '담백체' 로 저장했어요")
        await m.push(note: "메모")
        #expect(service.kept.last?.update == true)
        #expect(service.kept.last?.note == "메모")
        #expect(m.notice?.text == "라이브러리 '담백체' 을 2번 버전으로 올렸어요")
    }

    @Test func listEdits() async {
        let (m, _, _) = await makeStyle(Project(meta: .init(title: "등대")))
        m.addMarker()
        m.addDevice()
        m.addPassage()
        m.addPassage()
        m.removePassage(0)
        #expect(m.profile?.markers?.count == 1)
        #expect(m.profile?.devices?.first?.every == 0)
        #expect(m.profile?.samplePassages == [""])
        m.removeMarker(0)
        m.removeDevice(0)
        #expect(m.profile?.markers == [])
        #expect(m.profile?.devices == [])
    }
}
