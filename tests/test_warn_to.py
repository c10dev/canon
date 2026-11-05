"""상태 변경안 경고의 대상 인물(StateDelta.warn_to): features.clean 이 warnings 와 같은 차례로 채우고, 상태 승인 화면(review.js rvWarnSplit)이 그 인물 줄에 붙인다."""
from canon import features, pipeline
from canon.schema import CharacterState, StateDelta

from .jsvm import needs_node, run_js
from .test_storylines import _short
from .test_timeline import _play


def test_warn_to_not_in_ai_schema_and_old_delta_loads():
    assert "warn_to" not in StateDelta.model_json_schema()["properties"]
    d = StateDelta.model_validate({"episode": 1, "summary": "s", "warnings": ["옛 경고"]})
    assert d.warn_to == []


def test_clean_keeps_warn_to_aligned(monkeypatch):
    def direct(p, d):  # charlog.clean_delta 처럼 d.warnings 에 바로 붙이는 훅
        d.warnings.append("바로 붙인 경고")

    def mixed(p, d):
        return ["글만", ("서윤 상태창: 맞지 않아요", "hero"), ("AI 경고", "hero"), "글만"]

    monkeypatch.setattr(features, "CLEAN", (direct, mixed))
    d = StateDelta(episode=1, summary="s", warnings=["AI 경고"])
    features.clean(None, d)
    # AI 경고와 바로 붙인 경고는 대상이 없고, 이미 있는 글이나 겹친 글은 다시 붙이지 않는다
    assert d.warnings == ["AI 경고", "바로 붙인 경고", "글만", "서윤 상태창: 맞지 않아요"]
    assert d.warn_to == ["", "", "", "hero"]
    features.clean(None, d)  # 다시 정리해도 차례가 그대로다
    assert len(d.warn_to) == len(d.warnings) and d.warn_to[3] == "hero"


def test_attire_warning_targets_character():
    p = _play(_short(8), 1, 2)
    d = StateDelta(episode=3, summary="3화", warnings=["플롯의 사건 하나가 본문에 없어요."],
                   character_updates=[CharacterState(character_id="hero", attire="젖은 코트, 검은 가방")])
    pipeline.clean_delta(p, d)
    k = next(i for i, w in enumerate(d.warnings) if "검은 가방" in w)
    assert len(d.warn_to) == len(d.warnings)
    assert d.warn_to[k] == "hero" and d.warn_to[0] == ""


@needs_node
def test_warn_split_uses_warn_to_then_names():
    got = run_js(["app.js", "review.js"], """rvWarnSplit(data.w, data.names, data.to, data.ids)""", {
        "w": ["관계 상태창: 이름과 상관없이 대상으로 붙어요.", "서윤 상태창: 본문은 «HP 3»", "새 인물 민재의 말투가 비었어요.", "플롯 사건 누락"],
        "names": ["서윤", "도현"], "ids": ["hero", "rival"],
        "to": ["rival", "", "minjae"]})  # 짧은 warn_to 의 모자란 칸, 줄이 없는 인물은 이름 맞추기로 돌아간다
    assert got == {"by": {"1": [0], "0": [1]}, "rest": [2, 3]}
    # warn_to 가 없는 예전 변경안은 이름 맞추기만 쓴다
    assert run_js(["app.js", "review.js"], """rvWarnSplit(data, ['서윤'])""", ["서윤 상태창: x", "y"]) == {"by": {"0": [0]}, "rest": [1]}
