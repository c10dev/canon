"""새 인물을 들일 때의 이름 점검 · 한 화 새 인물 수 경고(naming.new_cast_warnings, features.CLEAN)와
작품 홈의 시점 인물 서술 말투 빈칸 알림(home.js homeVoiceGap). 실행: python -m pytest tests"""
from canon import features, naming
from canon.schema import Character, StateDelta

from .jsvm import dump, episode, needs_node, run_js
from .test_storylines import _short


def _c(cid, name, **kw):
    return Character(id=cid, name=name, role=kw.pop("role", "조연"), tier=kw.pop("tier", "support"), **kw)


def _project():
    p = _short(8)
    p.world.name_style = "korea_modern"
    p.characters = [_c("hero", "강서윤", tier="main"), _c("ally", "한도현", tier="main"), _c("smith", "박만수")]
    p.cast_candidates = [_c("guest", "오지훈")]
    return p


def test_new_names_checked_against_cast_candidates_and_each_other():
    p = _project()
    warns = naming.new_cast_warnings(p, [
        _c("twin", "박만수"),      # 같은 이름
        _c("seo", "윤서윤"),       # 성을 뺀 이름이 같음
        _c("jihun", "최지훈"),     # 후보와 성을 뺀 이름이 같음
        _c("dohee", "이도희"),     # 한도현과 첫 글자가 같음 (성을 뗀 이름 '도희' · '도현')
    ])
    assert any("박만수" in w and "이름이 같아요" in w for w in warns)
    assert any("윤서윤" in w and "강서윤" in w and "성을 뺀 이름" in w for w in warns)
    assert any("최지훈" in w and "오지훈" in w for w in warns)
    assert any("이도희" in w and "한도현" in w and "첫 글자" in w for w in warns)
    assert any("새 인물이 4명" in w for w in warns)  # 상한(3)을 넘었다


def test_count_warning_and_skips():
    p = _project()
    five = [_c(f"x{i}", n) for i, n in enumerate(["문가람", "노을빛", "탁재희", "민소율", "구태오"])]
    warns = naming.new_cast_warnings(p, five)
    assert any("새 인물이 5명" in w for w in warns)
    assert not any("새 인물이" in w for w in naming.new_cast_warnings(p, five[:3]))  # 셋까지는 알리지 않는다
    # 이미 있는 id(반영해도 더하지 않음)와 이름 없는 인물은 보지 않는다
    assert naming.new_cast_warnings(p, [_c("smith", "박만수"), _c("nameless", "")]) == []
    # 후보가 같은 id 로 들어오면(후보 등록) 자기 자신과 견주지 않는다
    assert naming.new_cast_warnings(p, [_c("guest", "오지훈")]) == []


def test_clean_delta_adds_warnings():
    p = _project()
    d = StateDelta(episode=2, summary="", new_characters=[_c("twin", "박만수", speech_style="굵은 반말")])
    features.clean(p, d)
    assert [w for w in d.warnings if "박만수" in w] == ["새 인물 박만수가 이미 있는 인물과 이름이 같아요. 다른 사람이면 이름을 바꾸고, 같은 사람이면 새 인물에서 빼세요."]


@needs_node
def test_home_voice_gap_for_pov_character():
    p = _project()
    p.episodes = [episode(1, text="본문", status="finalized"), episode(2, status="confirmed", plot={"pov": "ally", "characters": ["hero", "ally"]})]
    for c in p.characters:
        c.speech_style = "말투"
    todos = run_js(["app.js", "home.js"], "homeTodos(data.p, '#/p/x')", {"p": dump(p)})
    got = [(t["label"], t["href"]) for t in todos if t["tag"] == "인물"]
    assert got == [("2화 시점 인물 한도현의 서술 말투가 비었어요", "#/p/x/cast/ally")]
    p.characters[1].narration_voice = "짧게 끊는 1인칭"
    assert not [t for t in run_js(["app.js", "home.js"], "homeTodos(data.p, '#/p/x')", {"p": dump(p)}) if t["tag"] == "인물"]
    # 화면은 povChar 로 물려받은 시점도 본다: 넘긴 함수가 고른 인물을 쓴다
    p.characters[1].narration_voice = ""
    js = "homeTodos(data.p, '#/p/x', () => data.p.characters[0]).filter((t) => t.tag === '인물').map((t) => t.label)"
    assert run_js(["app.js", "home.js"], js, {"p": dump(p)}) == ["2화 시점 인물 강서윤의 서술 말투가 비었어요"]
