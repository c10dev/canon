@testable import FeatureSetup
import Testing

/// 서버 `tests/test_logline.py` 와 같은 사례. 셋(Python · 웹 · Swift)이 같은 규칙이라 함께 고친다.
@Suite struct LoglineTests {
    @Test func compose() {
        let p = LoglineParts(who: "사진관을 하는 서윤", why: "오빠의 실종 소식에 돌아와", goal: "오빠의 마지막 열흘을 되짚는다",
                             block: "도현은 무언가를 숨긴다", stake: "진실을 알면 가족을 잃는다")
        #expect(Logline.compose(p) == "사진관을 하는 서윤이 오빠의 실종 소식에 돌아와 오빠의 마지막 열흘을 되짚는다. 하지만 도현은 무언가를 숨긴다. 진실을 알면 가족을 잃는다.")
        #expect(Logline.checks(p).allSatisfy { $0.ok })
        #expect(Logline.compose(LoglineParts(who: "서진", goal: "등대를 지킨다.")) == "서진이 등대를 지킨다.")
        #expect(Logline.compose(LoglineParts(block: "모두가 숨긴다")) == "모두가 숨긴다.")
        #expect(Logline.compose(LoglineParts()) == "")
        #expect(Logline.compose(nil) == "")
        // 숫자는 읽는 소리로: 손님2(이) → 가
        #expect(Logline.compose(LoglineParts(who: "손님2", goal: "온다")) == "손님2가 온다.")
        #expect(Logline.compose(LoglineParts(who: "K", goal: "온다")) == "K이(가) 온다.")
    }

    @Test func checksFlagMissing() {
        #expect(Logline.checks(LoglineParts(who: "서윤", goal: "행복")).map(\.ok) == [false, false, false, false, false])
        #expect(Logline.checks(LoglineParts()).map(\.text) == [
            "주인공에게 이름 말고 특징이 있다", "이야기를 시작하게 만드는 일이 있다", "목표가 눈에 보이는 행동이다 ('~한다'로 끝남)",
            "목표를 막는 사람이나 힘이 있다", "길이가 40~150자 사이다",
        ])
    }

    @Test func toneText() {
        #expect(Tone.text(ToneDials(dark: 3, serious: 4, slow: 4)) == "조금 어둡고 진지하고 호흡이 느리다")
        #expect(Tone.text(ToneDials(dark: 1, serious: 2)) == "밝고 조금 가볍다")
        #expect(Tone.text(ToneDials()) == "")
        #expect(Tone.text(ToneDials(dark: 5)) == "")
    }

    /// 칸을 고치면 칸으로 합친 문장을 따라가고, 직접 고친 문장은 남긴다 (웹 `updateLogline(prev)`).
    @Test func setFollowsPartsUntilManual() {
        var m = Meta()
        Logline.set(.who, "서진", in: &m)
        #expect(m.logline == "서진이")
        Logline.set(.goal, "등대를 지킨다", in: &m)
        #expect(m.logline == "서진이 등대를 지킨다.")
        #expect(!Logline.isManual(m))
        m.logline = "직접 쓴 문장"
        #expect(Logline.isManual(m))
        Logline.set(.block, "폭풍이 온다", in: &m)
        #expect(m.logline == "직접 쓴 문장")
        Logline.rebuild(&m)
        #expect(m.logline == "서진이 등대를 지킨다. 하지만 폭풍이 온다.")
        #expect(Logline.lengthNote(m) == "\(m.logline!.unicodeScalars.count)자 · 점검은 참고용이에요")
    }

    /// 예시로 채우면 직접 고친 문장도 칸 내용으로 바꾼다 (웹 `useExample`).
    @Test func fillReplacesManualSentence() {
        var m = Meta(logline: "옛 한 문장")
        #expect(Logline.isLegacy(m))
        Logline.fill(LoglineParts(who: "서진", goal: "등대를 지킨다"), in: &m)
        #expect(m.logline == "서진이 등대를 지킨다.")
        #expect(!Logline.isLegacy(m))
    }

    /// 다이얼을 다시 누르면 끄고, 직접 쓴 톤 문장은 덮지 않는다 (웹 `setDial` · `toneBox`).
    @Test func dialsKeepWrittenTone() {
        var m = Meta()
        Tone.set(.dark, 3, in: &m)
        #expect(m.tone == "조금 어둡다")
        Tone.set(.slow, 4, in: &m)
        #expect(m.tone == "조금 어둡고 호흡이 느리다")
        Tone.set(.slow, 4, in: &m)
        #expect(m.toneDials?.slow == 0)
        #expect(m.tone == "조금 어둡다")
        m.tone = "서늘하다"
        Tone.set(.serious, 4, in: &m)
        #expect(m.tone == "서늘하다")
        #expect(Tone.offer(m) == "조금 어둡고 진지하다")
        #expect(ToneDial.serious.now(m.toneDials) == "진지하다")
    }
}
