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
