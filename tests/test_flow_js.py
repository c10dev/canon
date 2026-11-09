"""한 화 흐름(static/flow.js)의 단계 띠 글과 상태 승인(static/review.js)의 경고 붙이기 · 근거 밑줄. node 가 있을 때만 돈다."""
import re

from canon import findings
from canon.schema import ConsistencyIssue, Meta, Project, StateDelta, StoryEvent

from .jsvm import STATIC, dump, episode, needs_node, run_js

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
def test_flow_steps_flag_stale_delta():
    """변경안을 만든 뒤 본문을 고쳤으면 상태 승인 칸이 볼 것 남음으로 알린다. 반영이 끝난 화는 알리지 않는다."""
    written = episode(1, status="written", text=TEXT)
    done = episode(2, status="finalized", text=TEXT)
    got = run_js(["app.js", "home.js", "flow.js"], """data.map(([e, run]) => flowSteps(e, run)[2]).map((s) => [s.warn, s.sub])""",
                 [[dump(written), {"delta": {"picked": 2, "total": 3}, "stale": True}],
                  [dump(written), {"delta": {"picked": 2, "total": 3}, "stale": False}],
                  [dump(written), {"stale": True}], [dump(done), {"delta": {"picked": 1, "total": 1}, "stale": True}]])
    assert got == [[True, "본문 고침"], [False, "2/3 고름"], [False, "변경안 없음"], [False, "반영 완료"]]


@needs_node
def test_warnings_attach_to_named_characters():
    got = run_js(["app.js", "review.js"], """rvWarnSplit(data, ['서윤', '도', '서윤이'])""",
                 ["서윤 상태창: 본문은 «HP 3»인데 반영하면 HP가 5예요.", "서윤이 너무 빨리 옮겨 갔어요: 등대 → 시장.",
                  "도현의 말투가 설정과 달라요.", "플롯의 사건 하나가 본문에 없어요."])
    # 긴 이름이 먼저 맞고, 한 글자 이름에는 붙이지 않는다. 인물 이름으로 시작하지 않는 경고는 '본문 점검'
    assert got == {"by": {"0": [0], "2": [1]}, "rest": [2, 3], "audit": []}


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


@needs_node
def test_one_episode_screen_opens_stage_panel():
    """집필 · 검수 · 상태 승인 세 주소가 같은 한 화 화면(write.js viewEpisode)을 그리고, 주소의 단계가 오른쪽 칸만 정한다."""
    written = episode(1, status="written", text=TEXT)
    findings.merge(written, [issue("서윤은 등대 앞에 섰다.")], "2026-10-30T10:00:00", "b")
    blank = episode(2, status="confirmed")
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[written, blank])
    d = StateDelta(episode=1, summary="s", events=[
        StoryEvent(episode=1, actor="a", target="b", kind="도움", intensity=2, quote="도현이 손전등을 건넸다."),
    ])
    files = re.findall(r'src="/static/([a-z0-9]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
    got = run_js(files, """(() => {
      S.project = data.p; S.name = 't';
      const view = (page, n) => { S.route = ['p', 't', page, String(n)]; return ({ write: viewWrite, check: viewCheck, review: viewReview })[page](n); };
      const out = { write: view('write', 1), check: view('check', 1) };
      S.deltas[1] = data.d;
      out.review = view('review', 1);
      out.blank = view('check', 2);
      return out;
    })()""", {"p": dump(p), "d": dump(d)})
    for html in got.values():
        assert 'class="card w-body' in html and 'class="flow-bar"' in html  # 같은 본문 칸과 단계 띠
    assert "ep-cols" not in got["write"]  # 집필은 칸 없이 본문만
    assert 'class="ep-cols ep-check"' in got["check"] and 'class="c-side"' in got["check"]
    assert "<textarea" in got["check"]  # 검수 칸의 본문은 고칠 수 있다
    assert 'class="ep-cols ep-review"' in got["review"] and 'class="rv-panel"' in got["review"]
    # 상태 승인 칸도 고치는 본문이고, 근거 밑줄을 그릴 칸(hl-wrap)을 깐다. 밑줄 글은 그린 뒤 marks.js syncMarks 가 채운다
    assert "<textarea" in got["review"] and 'class="hl-wrap"' in got["review"]
    assert len(re.findall(r'class="btn primary"', got["review"].split("</header>")[0])) <= 1  # 머리 주 버튼은 하나까지
    assert got["review"].count('data-action="applyDelta"') == 1  # 반영 버튼은 머리(넓은 폭)나 아래 반영 바(좁은 폭) 한 곳
    assert "ep-cols" not in got["blank"] and "본문을 쓰고 저장한 뒤 검수해요" in got["blank"]  # 본문이 없으면 칸을 열지 않고 알린다


@needs_node
def test_flow_switch_is_same_episode_only():
    """같은 작품 같은 화에서 칸만 바꾼 이동만 칸 전환이다 (app.js flowSwitch: 스크롤 자리를 지키고 포커스를 단계 띠에 둔다)."""
    got = run_js(["app.js"], """data.map(([a, b]) => flowSwitch(a, b))""", [
        ["#/p/t/check/3", "#/p/t/review/3"], ["#/p/t/write/3", "#/p/t/check/3"],
        ["#/p/t/check/3", "#/p/t/check/3"], ["#/p/t/check/3", "#/p/t/review/4"],
        ["#/p/t/check/3", "#/p/u/review/3"], ["#/p/t/cast", "#/p/t/write/3"], ["#/p/t/write", "#/p/t/check"],
    ])
    assert got == [True, True, False, False, False, False, False]
