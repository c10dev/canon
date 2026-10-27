"""플롯 화면 시점 배지(static/plot.js)의 povChar · charInText · modeIn 이 prompts.pov_character · char_in_text · mode_in 과 같은지.
node 가 있을 때만 돈다."""
import pytest

from canon import prompts
from canon.schema import Act, Character, Project, StoryArc

from .jsvm import dump, episode, needs_node, run_js

CHARS = [Character(id="c1", name="서윤", role="여주인공"), Character(id="c2", name="강서윤", role="조연"),
         Character(id="c3", name="도현", role="남주"), Character(id="c4", name="윤", role="악역"),
         Character(id="c5", name="도", role="단역")]  # 같은 자리에서 시작하는 짧은 이름은 진다
TEXTS = ["", "서윤 1인칭", "강서윤 시점, 도현 등장", "도현과 서윤", "c4 3인칭 제한", "윤의 3인칭 전지", "아무도 없음", "주인공 1인칭"]


def _projects() -> list[Project]:
    acts = [Act(name="기", start_ep=1, end_ep=3, goal="", pov="도현 1인칭"), Act(name="승", start_ep=4, end_ep=6, goal=""),
            Act(name="전", start_ep=7, end_ep=8, goal="", pov="3인칭 전지"), Act(name="결", start_ep=9, end_ep=10, goal="")]
    eps = [episode(n) for n in range(1, 11)]
    eps[0].plot.pov = "c1"
    eps[1].plot.pov_mode = "3인칭 제한"  # 방식만 → 구간 인물
    eps[4].plot.pov_mode = "3인칭 전지"
    eps[5].plot.pov_mode = "1인칭"  # 방식만 → 작품 기본
    eps[6].plot.pov = "c2"  # 전지 구간이어도 화에 정한 인물
    eps[8].plot.pov = "없는 인물"
    out = []
    for base in ["", "주인공 1인칭", "강서윤 3인칭", "3인칭 전지"]:
        p = Project(characters=CHARS, arc=acts, episodes=eps)
        p.style.narration_pov = base
        out.append(p)
    q = out[1].model_copy(deep=True)
    q.meta.form = "serial"
    q.story_arcs = [StoryArc(number=1, title="", start_ep=1, end_ep=10, goal="", pov="윤 1인칭",
                             acts=[a.model_copy(update={"pov": ""}) for a in acts])]
    out.append(q)
    return out


@needs_node
def test_char_in_text_and_mode_in_match_server():
    p = Project(characters=CHARS)
    got = run_js(["app.js", "plot.js"], "S.project = data.p; data.t.map((t) => [(charInText(t) || {}).id || null, modeIn(t)])",
                 {"p": dump(p), "t": TEXTS})
    assert got == [[getattr(prompts.char_in_text(p, t), "id", None), prompts.mode_in(t)] for t in TEXTS]


@needs_node
def test_pov_char_matches_server():
    ps = _projects()
    got = run_js(["app.js", "plot.js"], "data.map((p) => { S.project = p; return [...Array(12).keys()].map((n) => (povChar(n).c || {}).id || null); })",
                 [dump(p) for p in ps])
    for p, ids in zip(ps, got):
        want = [prompts.pov_character(p, n) for n in range(12)]
        assert ids == [c.id if c else None for c in want], p.style.narration_pov
    assert len({x for row in got for x in row}) == 5  # c1~c4 와 없음을 모두 지난다


@needs_node
@pytest.mark.xfail(strict=True, reason="어긋남: 화에 적은 시점 인물을 prompts.pov_character 는 id 나 이름으로 찾고 povChar 는 id 로만 찾는다")
def test_pov_char_by_name_matches_server():
    p = Project(characters=CHARS, episodes=[episode(1, plot={"pov": "도현"})])
    got = run_js(["app.js", "plot.js"], "S.project = data; (povChar(1).c || {}).id || null", dump(p))
    assert got == prompts.pov_character(p, 1).id
