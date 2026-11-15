"""인물 표지 화면 (static/cast.js, docs/webnovel/specs/10-marks.md): castMarkFound 가 서버 charmarks.found 와 같은 답을 내는지,
표지 카드는 표지가 없으면 그리지 않는지, 거두기는 반영한 화에서만 뜨는지, 처음 고르는 인물. node 가 있을 때만 돈다."""
from canon import charmarks
from canon.schema import Character, CharMark, Project

from .jsvm import dump, episode, needs_node, run_js
from .test_primary_count_js import FILES

TEXT = "바람이 불었다. 서윤은\n등대 앞에  섰다.\n\n\"됐어, 내가 할게.\""
QUOTES = ["서윤은 등대 앞에 섰다.", "서윤은\n등대 앞에  섰다.", "  됐어, 내가 할게.  ", "서윤은등대", "없는 구절", "", "   "]


def _project() -> Project:
    p = Project()
    p.characters = [Character(id="hero", name="한서윤", role="주인공"), Character(id="ally", name="도현", role="조연")]
    p.episodes = [episode(1, text=TEXT, status="finalized", plot={"characters": ["ally"]}), episode(2, text="본문", status="written")]
    return p


@needs_node
def test_found_matches_server():
    p = _project()
    want = [charmarks.found(p, CharMark(id="m", episode=1, quote=q)) for q in QUOTES]
    assert want == [True, True, True, False, False, False, False]
    got = run_js(FILES, "data.qs.map((q) => castMarkFound(data.text, q))", {"qs": QUOTES, "text": TEXT})
    assert got == want


@needs_node
def test_card_and_tool_rules():
    p = _project()
    p.characters[0].marks = [CharMark(id="m1", kind="말버릇", text="말끝을 흐린다", episode=1, quote="서윤은 등대 앞에 섰다."),
                             CharMark(id="m2", kind="외모", text="흉터", episode=1, quote="지운 구절")]
    got = run_js(FILES, """(() => { S.project = data.p; S.name = 'x';
      return { empty: castMarksCard(S.project.characters[1]), card: castMarksCard(S.project.characters[0]),
        able: [castMarkable(ep(1)), castMarkable(ep(2))],
        who: [castMarkWho(S.project, 1, '서윤은 웃었다. 도현이 봤다.'), castMarkWho(S.project, 1, '도현이 서윤을'), castMarkWho(S.project, 1, '바람'), castMarkWho(S.project, 2, '바람')],
        tool: castMarkToolHtml({ n: 1, text: '서윤은', who: 'hero', kind: '외모', note: '' }) }; })()""", {"p": dump(p)})
    assert got["empty"] == ""
    assert got["card"].count('class="csh-mark"') == 2 and got["card"].count("본문에서 못 찾음") == 1
    assert "표지 2" in got["card"] and "AI에 넣지 않음" in got["card"]
    assert got["able"] == [True, False]
    assert got["who"] == ["hero", "ally", "ally", "hero"]
    assert 'aria-pressed="true" data-action="castMarkKind" data-arg="외모"' in got["tool"] and 'data-action="castMarkTake"' in got["tool"]
    assert got["tool"].count("btn small primary") == 1
