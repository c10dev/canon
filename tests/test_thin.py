"""짧은 응답 거르기(canon/thin.py): 상태 변경안이 칸이 거의 빈 JSON 을 받으면 한 번 다시 부르고, 그래도 짧으면 알린다. 응답 형식의 required 도 본다.
실행: python -m pytest tests/test_thin.py"""
from canon import autorun, pipeline, thin
from canon.autorun import Policy
from canon.mock import MockLLM
from canon.schema import StateDelta, StateDeltaAI, StyleProfile

from .test_state_audit import _ready

LONG = "서윤은 등대 앞에 섰다. " * 200


class _Seq:
    """json 을 차례 목록에서 꺼내 돌려주고 부른 횟수와 프롬프트를 센다."""

    def __init__(self, outs):
        self.outs, self.prompts = list(outs), []

    def json(self, system, prompt, schema, hint=None):
        self.prompts.append(prompt)
        return self.outs.pop(0)


def _thin(n=3, warnings=None):
    return StateDelta(episode=n, summary="요약", warnings=warnings or [])


def _full(n=3):
    return StateDelta(episode=n, summary="요약", new_facts=["사실 하나"])


def _proj(text=LONG):
    p = _ready()
    p.episode(3).text = text
    return p


def test_state_retry_then_ok():
    s = _Seq([_thin(), _full()])
    d = pipeline.extract_state(s, _proj(), 3)
    assert len(s.prompts) == 2 and s.prompts[0] == s.prompts[1]
    assert not any(w.startswith(thin.THIN_MARK) for w in d.warnings)
    assert d.new_facts == ["사실 하나"]


def test_state_thin_twice_warns():
    s = _Seq([_thin(warnings=["모델 경고"]), _thin(warnings=["모델 경고"])])
    d = pipeline.extract_state(s, _proj(), 3)
    assert len(s.prompts) == 2
    assert d.warnings[-1] == thin.STATE_WARNING and "모델 경고" in d.warnings
    assert len(d.warn_to) == len(d.warnings)


def test_state_ok_first_call_once():
    s = _Seq([_full()])
    pipeline.extract_state(s, _proj(), 3)
    assert len(s.prompts) == 1


def test_state_short_text_no_retry():
    s = _Seq([_thin()])
    d = pipeline.extract_state(s, _proj("짧은 본문이다."), 3)
    assert len(s.prompts) == 1 and not any(w.startswith(thin.THIN_MARK) for w in d.warnings)


def test_autorun_thin_reason():
    d = _full()
    d.warnings = [thin.STATE_WARNING]
    out = autorun._warning_reasons(d, Policy())
    assert len(out) == 1 and "응답이 짧아" in out[0]
    out = autorun._warning_reasons(d, Policy(stop_on_warnings=True))
    assert len(out) == 1 and "경고 1개" not in out[0]
    p = _proj()
    assert any("응답이 짧아" in r for r in autorun.review_reasons(p, d, None, Policy()))


def test_schema_required_all_keys():
    for cls in (StateDeltaAI, StyleProfile):
        sch = cls.model_json_schema()
        assert sorted(sch["required"]) == sorted(sch["properties"])
    assert StyleProfile.model_validate({}).narration_pov == ""
    assert StateDeltaAI.model_validate({"episode": 1, "summary": "x"}).events == []


def test_mock_not_thin():
    llm = MockLLM()
    d = llm.json("s", "p", StateDeltaAI, hint={"episode": 3})
    assert not thin.state_thin(pipeline.to_delta(d, 3), LONG)
