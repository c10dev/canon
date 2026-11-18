"""검수가 화 플롯의 이어받기 결정(EpisodePlot.carry)을 본문과 견준다 (docs/trail 일감 4-1)."""
import os
import tempfile

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from canon import context, prompts  # noqa: E402
from canon.schema import Character, Episode, EpisodePlot, Meta, Project  # noqa: E402

FILLER = ["바람이 불었다. ", "파도가 쳤다. ", "갈매기가 울었다. ", "안개가 짙었다. ", "종이 울렸다. "]
OLD = "\n\n".join("서윤은 등대 계단에서 거절당한 날을 떠올렸다. " * (i == 1) + FILLER[i - 1] * 20 for i in range(1, 6))


def _plot(n: int, carry=None) -> EpisodePlot:
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=["a"],
                       emotional_shift="", ending_hook="", carry=carry or [])


def _project(carry=None) -> Project:
    texts = {1: OLD, 2: "파도가 거셌다.", 3: "비가 왔다.", 4: "안개가 끼었다.", 5: "해가 났다.", 6: "서윤은 등대에 올랐다."}
    p = Project(meta=Meta(title="t", form="serial", target_episodes=6),
                characters=[Character(id="a", name="서윤", role="주인공", tier="main")],
                episodes=[Episode(plot=_plot(n, carry if n == 6 else None), status="finalized" if n < 6 else "written", text=t)
                          for n, t in texts.items()])
    p.settings.check_motion = False
    return p


def test_no_carry_has_no_trace():
    p = _project()
    assert prompts.carry_check_block(p, 6) == ""
    assert prompts.carry_check_rule(p, 6) == ""
    assert "이어받기 결정" not in prompts.check_prompt(p, 6)


def test_carry_block_and_rule():
    p = _project(["서윤 | 1화 | 거절당한 날을 다시 떠올림"])
    assert "# 6화의 이어받기 결정" in prompts.check_material(p, 6)
    assert "- 서윤 | 1화 | 거절당한 날을 다시 떠올림" in prompts.check_material(p, 6)
    assert "# Carry-over decisions of episode 6" in prompts.check_material(p, 6, lang="en")
    assert "- 이어받기 결정: [6화의 이어받기 결정]" in prompts.check_prompt(p, 6)


def test_old_episode_passages_are_added_within_budget(monkeypatch):
    p = _project(["서윤 | 1화 | 거절당한 날을 다시 떠올림"])
    monkeypatch.setitem(context.BUDGET, "check_recall", 1_200)
    monkeypatch.setattr(context, "CARRY_RECALL", 700)
    found = dict(prompts.check_recall(p, 6)[1])
    assert 1 in found
    assert sum(len(x) for paras in found.values() for x in paras) <= 1_200
    assert sum(len(x) for x in found[1]) <= 1_200


def test_carry_pulls_a_passage_the_plain_search_misses():
    bell = (FILLER[4] * 20).strip()  # 1화 다섯째 단락. 6화 본문 · 플롯과 겹치는 글이 없다
    base = dict(prompts.check_recall(_project(), 6)[1])
    assert bell not in base.get(1, [])
    found = dict(prompts.check_recall(_project(["서윤 | 1화 | 종이 울렸다"]), 6)[1])
    assert bell in found[1]
    assert found[1] == sorted(found[1], key=OLD.find)  # 결정 단락과 일반 찾기 단락을 합쳐도 본문 차례


def test_recent_or_zero_episode_changes_nothing():
    base = prompts.check_recall(_project(), 6)
    assert prompts.check_recall(_project(["서윤 | 4화 | 안개"]), 6)[1] == base[1]
    assert prompts.check_recall(_project(["서윤 | 거절당한 날"]), 6)[1] == base[1]
    assert prompts.check_recall(_project(["서윤 | 9화 | 없는 화"]), 6)[1] == base[1]


def test_block_lines_for_zero_episode_and_unknown_character():
    p = _project(["서윤 | 거절당한 날", "zz | 2화 | 뜻"])
    block = prompts.carry_check_block(p, 6)
    assert "\n- 서윤 | 거절당한 날" in block
    assert "\n- zz | 2화 | 뜻" in block
