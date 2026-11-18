"""화 플롯의 이어받기 결정 칸 `EpisodePlot.carry` (docs/trail 일감 3)."""
import json

from canon import llm, prompts
from canon.schema import CarryOver, EpisodePlot, Project


def _plot(**kw):
    base = dict(number=2, act="전", title="t", summary="s", events=["a"], characters=["c1"],
                emotional_shift="x", ending_hook="h")
    base.update(kw)
    return EpisodePlot(**base)


def test_empty_carry_has_no_key():
    p = _plot()
    assert "carry" not in p.model_dump()
    assert '"carry"' not in p.model_dump_json()
    assert '"carry"' not in llm.dump(p)


def test_old_plot_dict_reads_empty_carry():
    d = json.loads(_plot().model_dump_json())
    assert "carry" not in d
    assert EpisodePlot.model_validate(d).carry == []


def test_text_lines():
    p = _plot(carry=["서하은 | 7화 | 동정을 노린 연기였다고 다시 읽음"])
    assert p.carry == [CarryOver(character="서하은", episode=7, meaning="동정을 노린 연기였다고 다시 읽음")]
    assert _plot(carry=["서하은 | 뜻"]).carry == [CarryOver(character="서하은", episode=0, meaning="뜻")]
    assert _plot(carry=["서하은 | 6~7화 | 뜻"]).carry[0].episode == 6
    assert _plot(carry=["서하은 | 화 | 뜻"]).carry[0].episode == 0
    assert _plot(carry=["서하은 | 7화 | ", "", {"character": "a", "meaning": " "}]).carry == []
    assert len(_plot(carry=["a | 1화 | x", "b | 2화 | y", "c | 3화 | z"]).carry) == 2
    kept = _plot(carry=[{"character": "a", "episode": 3, "meaning": "m"}, CarryOver(character="b", meaning="n")])
    assert [c.character for c in kept.carry] == ["a", "b"]


def test_response_schema():
    schema = EpisodePlot.model_json_schema()
    assert "carry" in schema["properties"]
    assert set(schema["$defs"]["CarryOver"]["properties"]) == {"character", "episode", "meaning"}


def test_write_plot_hides_episode():
    plot = _plot(carry=["서하은 | 7화 | 동정을 노린 연기"])
    text = llm.dump(prompts.write_plot(plot))
    assert "동정을 노린 연기" in text
    assert '"episode"' not in text
    assert plot.carry[0].episode == 7


def test_project_round_trip():
    p = Project.model_validate({"meta": {"title": "t"}})
    p.episodes = []
    from canon.schema import Episode
    p.episodes.append(Episode(plot=_plot(carry=["서하은 | 7화 | 뜻"])))
    back = Project.model_validate_json(p.model_dump_json())
    assert back.episodes[0].plot.carry == p.episodes[0].plot.carry
    assert back.episodes[0].plot.carry[0].episode == 7
