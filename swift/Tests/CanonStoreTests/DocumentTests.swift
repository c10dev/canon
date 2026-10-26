import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Testing

/// 받기 · 저장을 흉내 낸다. 저장할 때 받은 작품과 인자를 적어 둔다.
final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: Project
    var saveError: CanonError?
    var kept: [KeptField] = []
    var saved: [(Project, [String], Bool)] = []

    init(_ project: Project) { self.project = project }

    func load(_ name: String) async throws -> Project { project }

    func save(_ name: String, _ p: Project, merged: [String], force: Bool) async throws -> SaveResult {
        saved.append((p, merged, force))
        if let saveError, !force { throw saveError }
        var out = p
        out.editRev = (p.editRev ?? 0) + 1
        project = out
        return SaveResult(project: out, kept: kept)
    }
}

func project(plots: [Int] = [1, 2]) -> Project {
    let eps = plots.map { n in
        Components.Schemas.Episode(plot: .init(number: n, act: .기, title: "\(n)화", summary: "", events: [], characters: [], emotionalShift: "", endingHook: ""))
    }
    return Project(meta: .init(title: "등대", targetEpisodes: 12), episodes: eps, editRev: 3)
}

@MainActor
@Suite struct DocumentTests {
    @Test func editsAndSaves() async {
        let store = FakeStore(project())
        let doc = ProjectDocument(name: "등대", store: store)
        await doc.load()
        doc.edit { $0.meta?.title = "등대지기" }
        #expect(doc.dirty)
        #expect(await doc.save())
        #expect(!doc.dirty)
        #expect(store.saved.first?.0.meta?.title == "등대지기")
        #expect(doc.project?.editRev == 4)
        #expect(doc.notice?.text == "저장했어요")
    }

    @Test func conflictOffersReloadOrForce() async {
        let store = FakeStore(project())
        store.saveError = .server(status: 409, message: "다른 탭이나 기기에서 이 작품을 먼저 저장했어요.", code: nil)
        let doc = ProjectDocument(name: "등대", store: store)
        await doc.load()
        doc.edit { $0.facts = ["등대는 꺼져 있다"] }
        #expect(await doc.save() == false)
        #expect(doc.conflict)
        #expect(doc.dirty)
        #expect(await doc.save(force: true))
        #expect(store.saved.last?.2 == true)
        #expect(!doc.conflict)
    }

    @Test func loadKeepsUnsavedChanges() async {
        let store = FakeStore(project())
        let doc = ProjectDocument(name: "등대", store: store)
        await doc.load()
        doc.edit { $0.facts = ["새 사실"] }
        await doc.load()
        #expect(doc.project?.facts == ["새 사실"])
        await doc.reload()
        #expect(doc.project?.facts == nil)
        #expect(!doc.dirty)
    }

    @Test func warnsOnlyWhenKeptFieldWasEdited() async {
        let store = FakeStore(project())
        store.kept = [KeptField(field: "plot", ep: 2), KeptField(field: "plot", ep: 1)]
        let doc = ProjectDocument(name: "등대", store: store)
        await doc.load()
        doc.edit { $0.episodes?[1].plot.title = "고친 2화" }
        #expect(await doc.save() == false)
        #expect(doc.notice?.text == "작업이나 반영된 진행과 겹쳐 이 부분은 저장하지 않고 서버에 있는 것으로 두었어요: 2화 플롯")
        #expect(doc.notice?.isError == true)
    }
}

@Suite struct KeptFieldTests {
    @Test func readsHeader() {
        let json = #"[{"field":"plot","ep":3},{"field":"character","name":"서연"}]"#
        let header = json.addingPercentEncoding(withAllowedCharacters: .alphanumerics)!
        let kept = KeptField.parse(header: header)
        #expect(kept == [KeptField(field: "plot", ep: 3), KeptField(field: "character", name: "서연")])
        #expect(SaveText.keptCharacters(kept) == "이 화면이 모르는 사이 반영으로 더해진 인물(서연)은 지우지 않고 남겼어요")
        #expect(SaveText.dropped([KeptField(field: "relationships")]) { _ in true }?.hasSuffix(": 관계") == true)
        #expect(KeptField.parse(header: nil).isEmpty)
    }
}
