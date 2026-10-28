import CanonAPI
import CanonCore
import CanonStore
import Foundation
@testable import FeatureWrite
import Testing

typealias Ep = Components.Schemas.Episode

func ep(_ n: Int, _ status: Ep.StatusPayload, text: String = "", issues: [ConsistencyIssue] = []) -> Ep {
    Ep(plot: .init(number: n, act: .기, title: "\(n)화 제목", summary: "요약", events: ["사건"], characters: ["c1", "모름"], emotionalShift: "", endingHook: ""),
       status: status, text: text, issues: issues)
}

/// 비교 결과를 웹 `textDiff` · `wordDiff` 의 HTML 모양으로 (`esc` 없이).
func html(_ pieces: [DiffPiece]) -> String {
    pieces.map { p in
        switch p.kind {
        case .same: p.text
        case .removed: "<del>\(p.text)</del>"
        case .added: "<ins>\(p.text)</ins>"
        }
    }.joined()
}

@Suite struct TextDiffTests {
    // 기대값은 웹 rewrite.js · passage.js 의 함수를 node 로 돌린 결과다
    static let cases = [
        ("그는 문을 열었다.", "그는 조용히 문을 열었다."),
        ("하나\n둘\n셋", "하나\n셋\n넷"),
        ("비가 왔다.\n\n그녀는 웃었다.", "비가 왔다.\n\n전혀 다른 문장이 여기에 들어간다."),
        ("가 나 다 라", "가 마 바 라"),
        ("첫 줄\n둘째 줄 그대로", "첫 줄 바뀜\n둘째 줄 그대로\n새 줄"),
    ]

    @Test func linesMatchWeb() {
        let expected: [(String, Int)] = [
            ("그는 <ins>조용히 </ins>문을 열었다.", 1),
            ("하나\n<del>둘</del>\n셋\n<ins>넷</ins>", 2),
            ("비가 왔다.\n\n<del>그녀는 웃었다.</del>\n<ins>전혀 다른 문장이 여기에 들어간다.</ins>", 1),
            ("가 <del>나 다</del><ins>마 바</ins> 라", 1),
            ("첫 줄<ins> 바뀜</ins>\n둘째 줄 그대로\n<ins>새 줄</ins>", 2),
        ]
        for ((a, b), (h, n)) in zip(Self.cases, expected) {
            let d = TextDiff.lines(a, b)
            #expect(html(d.pieces) == h)
            #expect(d.changes == n)
        }
    }

    @Test func wordsMatchWeb() {
        let expected = [
            "그는 <ins>조용히 </ins>문을 열었다.",
            "하나\n<del>둘\n</del>셋<ins>\n넷</ins>",
            "비가 왔다.\n\n<del>그녀는 웃었다</del><ins>전혀 다른 문장이 여기에 들어간다</ins>.",
            "가 <del>나 다</del><ins>마 바</ins> 라",
            "첫 줄<ins> 바뀜</ins>\n둘째 줄 그대로<ins>\n새 줄</ins>",
        ]
        for ((a, b), h) in zip(Self.cases, expected) {
            #expect(html(TextDiff.words(a, b)) == h)
        }
    }

    @Test func tokensMatchWeb() {
        #expect(TextDiff.tokens("“그래?” 그는, 말했다…  정말") == ["“", "그래", "?", "”", " ", "그는", ",", " ", "말했다", "…", "  ", "정말"])
    }

    @Test func sameTextHasNoChanges() {
        let d = TextDiff.lines("같다\n같다", "같다\n같다")
        #expect(d.changes == 0)
        #expect(RewriteText.changes(d.changes) == "바뀐 곳이 없어요")
        #expect(RewriteText.changes(3) == "바뀐 곳 3곳")
    }
}

@Suite struct WriteTextTests {
    @Test func orderRule() {
        let eps = [ep(1, .finalized), ep(2, .written, text: "본문"), ep(3, .confirmed), ep(4, .confirmed)]
        #expect(WriteText.blockedBefore(4, in: eps) == [2, 3])
        #expect(WriteText.blockedBefore(2, in: eps) == [])
        let note = WriteText.orderNote([2, 3], in: eps)
        #expect(note?.text == "이전 화(2, 3화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙이에요.")
        #expect(note?.button == "2화 상태 승인으로")
        #expect(note?.screen == .review)
        #expect(WriteText.orderNote([3], in: eps)?.button == "3화 집필로")
        #expect(WriteText.orderNote([], in: eps) == nil)
    }

    @Test func editableAndUnsaved() {
        #expect(!WriteText.editable(ep(1, .draft)))
        #expect(WriteText.editable(ep(1, .finalized)))
        #expect(!WriteText.unsaved(draft: nil, saved: "a"))
        #expect(!WriteText.unsaved(draft: " 본문\n", saved: "본문"))  // 서버는 앞뒤 공백을 지워 저장한다
        #expect(WriteText.unsaved(draft: "본문2", saved: "본문"))
        #expect(!WriteText.unsaved(draft: "", saved: ""))  // '직접 쓰기'로 빈 칸만 연 것은 세지 않는다
    }

    @Test func labels() {
        #expect(WriteText.count("가나다", goal: 5000) == "3 / 5,000자")
        #expect(WriteText.eyebrow(act: "기", n: 3, target: 12) == "기 구간 · 3 / 12화")
        #expect(WriteText.eyebrow(act: nil, n: 3, target: 12) == "3 / 12화")
        #expect(WriteText.clip("가나다라", 2) == "가나…")
        #expect(WriteText.clip("가나", 2) == "가나")
        #expect(WriteText.bodyHint(ep(1, .draft)) == "플롯을 확정하면 본문을 쓸 수 있어요")
    }

    @Test func names() {
        let p = Project(characters: [.init(id: "c1", name: "서연", role: "")], episodes: [])
        #expect(WriteText.name("c1", in: p) == "서연")
        #expect(WriteText.name("모름", in: p) == "모름")
    }

    @Test func editTime() {
        let tz = TimeZone(identifier: "Asia/Seoul")!
        let now = ISO8601DateFormatter().date(from: "2026-10-26T05:00:00Z")!  // 서울 14시
        #expect(WriteText.when("2026-10-26T13:05:00+09:00", now: now, timeZone: tz) == "13:05")
        #expect(WriteText.when("2026-10-20T13:05:00+09:00", now: now, timeZone: tz) == "2026.10.20")
        #expect(WriteText.when(nil, now: now, timeZone: tz) == "")
    }
}

@Suite struct RewriteTextTests {
    let info = RewriteInfo(presets: [.init(id: "slow", label: "속도 늦추기")],
                           materials: [.init(id: "issues", label: "검수 결과", lines: ["- [사실] x"], note: ""),
                                       .init(id: "hook", label: "흡입력 판정", lines: ["- y"], note: "판정한 뒤 본문이 바뀌었어요"),
                                       .init(id: "style", label: "문체 지표", lines: ["- z"], note: "")],
                           keepMax: 2)

    @Test func firstRequestTakesFreshIssuesAndHook() {
        let r = RewriteDraft(info: info)
        #expect(r.materials == ["issues"])  // 흡입력 판정은 오래돼서, 문체 지표는 처음부터 넣지 않는다
        #expect(r.mode == .fresh)
    }

    @Test func keepRules() {
        var r = RewriteDraft()
        #expect(r.add(keep: "문장 하나", max: 2) == nil)
        #expect(r.add(keep: "문장 하나", max: 2) == "이미 담은 부분이에요")
        #expect(r.add(keep: "문장 둘", max: 2) == nil)
        #expect(r.add(keep: "문장 셋", max: 2) == "살릴 부분은 2개까지예요. 하나를 빼고 담으세요")
    }

    @Test func requestRoundTrip() throws {
        var r = RewriteDraft(info: info)
        r.toggle(preset: "slow")
        r.feedback = String(repeating: "가", count: 70)
        r.mode = .revise
        let req = r.request
        #expect(req.materials == [.issues])
        #expect(RewriteText.requestBits(req, labels: ["slow": "속도 늦추기"]) == ["속도 늦추기", "고쳐 쓰기", String(repeating: "가", count: 60) + "…"])
        #expect(RewriteDraft(req) == r)
        let json = try #require(WriteModel.json(req))
        #expect(json["mode"] == .string("revise"))
        #expect(json["presets"] == .array([.string("slow")]))
    }

    @Test func versionLabels() {
        #expect(RewriteText.kind(TextVersion(id: "v1", kind: .rejected)) == "고르지 않은 새 판")
        #expect(RewriteText.kind(TextVersion(id: "v1")) == "바꾸기 전")
        #expect(RewriteText.side("새 판", "가나다") == "새 판 · 3자")
        #expect(RewriteText.materialCount([]) == "없음")
    }
}

@Suite struct PublishTextTests {
    @Test func rangeRules() {
        let r = PublishText.range([2, 3, 5], picked: (nil, nil))
        #expect(r.from == 2 && r.to == 5)
        #expect(PublishText.range([2, 3, 5], picked: (3, nil)).from == 3)
        #expect(PublishText.clamp(9, last: 5) == 5)
        #expect(PublishText.clamp(0, last: 5) == 1)
        #expect(PublishText.rangeError(from: 5, to: 2) == "시작 화가 끝 화보다 커요. 2~5화로 바꿔 보세요")
        #expect(PublishText.rangeError(from: 2, to: 5) == nil)
        #expect(PublishText.pick([2, 3, 5], from: 3, to: 5) == [3, 5])
    }

    @Test func copiedText() {
        #expect(PublishText.copied(ExportOut(text: "가나\n다\n", html: "", episodes: [1, 2, 3], filename: "")) == "1~3화 복사했어요 (5자, 3줄)")
        #expect(PublishText.copied(ExportOut(text: "가", html: "", episodes: [4], filename: "")) == "복사했어요 (1자, 1줄)")
        #expect(PublishText.filename("등대", from: 3, to: 3) == "등대-3화.txt")
        #expect(PublishText.filename("등대", from: 1, to: 5) == "등대-1-5화.txt")
        #expect(PublishText.titleToggle(3) == "맨 위에 '3화. 제목' 줄 넣기")
    }
}
