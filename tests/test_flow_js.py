"""한 화 흐름(static/flow.js)의 단계 띠 글과 상태 승인(static/review.js)의 경고 붙이기 · 근거 밑줄. node 가 있을 때만 돈다."""
from canon import findings
from canon.schema import ConsistencyIssue, Meta, Project, StateDelta, StoryEvent

from .jsvm import dump, episode, needs_node, run_js

TEXT = "서윤은 등대 앞에 섰다. 도현이 손전등을 건넸다.\n둘은 계단을 올랐다."


def issue(q: str) -> ConsistencyIssue:
    return ConsistencyIssue(type="말투", description="말투가 달라요", source_quote="설정", current_quote=q)


@needs_node
def test_flow_steps_follow_episode_state():
    fresh = episode(1, status="confirmed")
    written = episode(2, status="written", text=TEXT)
    checked = episode(3, status="written", text=TEXT)
    findings.merge(checked, [issue("서윤은 등대 앞에 섰다.")], "2026-10-30T10:00:00", "b")
    clean = episode(4, status="written", text=TEXT)
    findings.merge(clean, [], "2026-10-30T10:00:00", "b")
    done = episode(5, status="finalized", text=TEXT)
    got = run_js(["app.js", "home.js", "flow.js"], """data.map(([e, run]) => flowSteps(e, run).map((s) => [s.key, s.num, s.done, s.warn, s.off, s.sub]))""",
                 [[dump(fresh), {}], [dump(written), {"checking": True, "stating": True}], [dump(checked), {"delta": {"picked": 4, "total": 5}}],
                  [dump(clean), {}], [dump(done), {}]])
    fresh_s, written_s, checked_s, clean_s, done_s = got
    assert fresh_s == [["write", 4, False, False, False, "본문 없음"], ["check", 5, False, False, True, "본문을 쓴 뒤"],
                       ["review", 6, False, False, True, "본문을 쓴 뒤"]]
    assert written_s[1][5] == "검수하는 중" and written_s[2][5] == "변경안 만드는 중"  # 검수하기가 둘을 함께 돌린다
    assert checked_s[1][2:4] == [False, True] and checked_s[1][5] == "열린 지적 1" and checked_s[2][5] == "4/5 고름"
    assert clean_s[1][2] is True and clean_s[1][5] == "어긋난 곳 없음" and clean_s[2][5] == "변경안 없음"
    assert done_s[2][2] is True and done_s[2][5] == "반영 완료"


@needs_node
def test_warnings_attach_to_named_characters():
    got = run_js(["app.js", "review.js"], """rvWarnSplit(data, ['서윤', '도', '서윤이'])""",
                 ["서윤 상태창: 본문은 «HP 3»인데 반영하면 HP가 5예요.", "서윤이 너무 빨리 옮겨 갔어요: 등대 → 시장.",
                  "도현의 말투가 설정과 달라요.", "플롯의 사건 하나가 본문에 없어요."])
    # 긴 이름이 먼저 맞고, 한 글자 이름에는 붙이지 않는다. 인물 이름으로 시작하지 않는 경고는 '본문 점검'
    assert got == {"by": {"0": [0], "2": [1]}, "rest": [2, 3]}


@needs_node
def test_review_underlines_sources_on_review_stage_only():
    e = episode(1, status="written", text=TEXT)
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[e])
    d = StateDelta(episode=1, summary="s", events=[
        StoryEvent(episode=1, actor="a", target="b", kind="도움", intensity=2, quote="도현이 손전등을 건넸다."),
        StoryEvent(episode=1, actor="b", target="a", kind="공동경험", intensity=1, quote="본문에 없는 문장."),
    ])
    files = ["app.js", "home.js", "review.js"]
    got = run_js(files, """(() => {
      S.project = data.p; S.name = 't'; S.deltas[1] = data.d;
      S.route = ['p', 't', 'review', '1'];
      S.rvQuote = { n: 1, q: '도현이 손전등을 건넸다.' };
      const on = rvRanges(1, data.p.episodes[0].text);
      S.route = ['p', 't', 'write', '1'];
      return [on, rvRanges(1, data.p.episodes[0].text)];
    })()""", {"p": dump(p), "d": dump(d)})
    on, off = got
    assert [(r["a"], r["b"], r["kind"], r["key"]) for r in on] == [(TEXT.index("도현"), TEXT.index("도현") + len("도현이 손전등을 건넸다."), "src sel", "r:e0")]
    assert off == []  # 다른 단계의 본문에는 근거 밑줄이 없다
