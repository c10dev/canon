import CanonCore
import FeatureProjects
import Testing

struct FakeListing: ProjectListing {
    var cards: [ProjectCard] = []
    var error: CanonError?

    func listProjects() async throws -> [ProjectCard] {
        if let error { throw error }
        return cards
    }
}

func card(openEp: Int = 4, status: String = "confirmed", finalized: Int = 3, planned: Int = 12, form: String = "short") -> ProjectCard {
    ProjectCard(name: "등대", title: "", genre: "", form: form, episodes: 12, finalized: finalized, planned: planned,
                openEp: openEp, openStatus: status, updatedAt: "")
}

@Suite struct ProjectCardTextTests {
    @Test func nextStep() {
        #expect(ProjectCardText.next(card()) == "4화 쓰기 대기")
        #expect(ProjectCardText.next(card(status: "written")) == "4화 상태 승인 대기")
        #expect(ProjectCardText.next(card(openEp: 0, finalized: 12)) == "완결")
        #expect(ProjectCardText.next(card(openEp: 0, finalized: 5, planned: 5)) == "6화부터 플롯 만들기")
        #expect(ProjectCardText.next(card(openEp: 0, finalized: 0, planned: 0)) == "플롯 없음")
    }

    @Test func lines() {
        #expect(ProjectCardText.title(card()) == "등대")
        #expect(ProjectCardText.summary(card(form: "serial")) == "장편 · 4화 쓰기 대기")
        #expect(ProjectCardText.detail(card()) == "장르 미정 · 폴더 등대")
        #expect(ProjectCardText.progress(card()) == "3 / 12화")
    }
}

@MainActor
@Suite struct ProjectsModelTests {
    @Test func loadsCards() async {
        let model = ProjectsModel(source: FakeListing(cards: [card()]))
        await model.load()
        #expect(model.cards.count == 1)
        #expect(model.error == nil)
        #expect(!model.loading)
    }

    @Test func showsOfflineMessage() async {
        let model = ProjectsModel(source: FakeListing(error: .offline))
        await model.load()
        #expect(model.error == CanonError.offline.errorDescription)
    }
}

/// 웹 `branchGroups` 와 같은 사례 (node 로 돌린 값).
@Suite struct ProjectGroupTests {
    func c(_ name: String, _ id: String = "", _ family: String = "", parent: String = "", from: Int = 0) -> ProjectCard {
        ProjectCard(name: name, title: "", genre: "", form: "short", episodes: 12, finalized: 3, planned: 12, openEp: 4,
                    openStatus: "confirmed", updatedAt: "",
                    branch: id.isEmpty ? nil : .init(id: id, family: family, parent: parent, fromEp: from, label: ""))
    }

    @Test func groupsFamilies() {
        let list = [c("b2", "i3", "F", parent: "i2", from: 7), c("solo"), c("main", "i1", "F"), c("b1", "i2", "F", parent: "i1", from: 5),
                    c("a0", "i4", "F", parent: "i1", from: 5), c("orphan", "o1", "G", parent: "x", from: 3), c("lone", "h1", "H"),
                    c("p", "p1", "K", parent: "z", from: 2), c("q", "q1", "K", parent: "z", from: 4)]
        let groups = ProjectGroup.make(list)
        #expect(groups.map(\.card.name) == ["main", "solo", "orphan", "lone", "p", "q"])
        #expect(groups[0].branches.map(\.card.name) == ["a0", "b1", "b2"])
        #expect(groups[0].branches.map(\.depth) == [0, 0, 1])
        #expect(groups[1...].allSatisfy { $0.branches.isEmpty })
    }

    @Test func branchLines() {
        let b = c("등대-b", "i2", "F", parent: "i1", from: 5)
        #expect(ProjectCardText.branchTitle(b) == "등대-b")
        #expect(ProjectCardText.branchDetail(b) == "5화부터 · 3 / 12화 · 4화 쓰기 대기")
        #expect(ProjectCardText.folder(b) == "폴더 등대-b")
        #expect(ProjectCardText.summary(c("등대"), branches: 2) == "단편 · 4화 쓰기 대기 · 갈래 2개")
        #expect(ProjectCardText.summary(c("등대"), branches: 0) == "단편 · 4화 쓰기 대기")
    }
}
