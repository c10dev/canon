"""상태 변경안 누락 검사(Settings.state_audit, audit 단계): 기본 꺼짐, '[누락 의심]' 경고로만 붙음, 본문에 없는 인용은 버림,
최대 6개, 실패해도 변경안은 그대로, 자동 집필 정책은 따로 셈. 실행: python -m pytest tests"""
from canon import autorun, pipeline, settings, store, web
from canon.mock import MockLLM
from canon.schema import AuditItem, AuditReport, StateDelta

from .jsvm import needs_node, run_js
from .test_storylines import _short
from .test_timeline import LLM, _play


def _ready():
    p = _play(_short(8), 1, 2)
    pipeline.confirm_plot(p, 3)
    p.episode(3).text, p.episode(3).status = pipeline.write_episode(LLM, p, 3), "written"
    return p


class _Spy:
    def __init__(self, items=None, fail=False):
        self.items, self.fail, self.calls = items or [], fail, 0

    def json(self, system, prompt, schema, hint=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("응답 없음")
        assert schema is AuditReport and "[받은 상태 변경안]" in prompt and "[3화 본문]" in prompt
        return AuditReport(items=self.items)


def test_audit_is_off_by_default():
    p = _ready()
    spy = _Spy()
    d = pipeline.extract_state(LLM, p, 3, audit=spy)
    assert spy.calls == 0 and not any(w.startswith(pipeline.AUDIT_MARK) for w in d.warnings)


def test_audit_adds_warnings_only():
    p = _ready()
    p.settings.state_audit = True
    plain = pipeline.extract_state(LLM, p.model_copy(deep=True, update={"settings": p.settings.model_copy(update={"state_audit": False})}), 3)
    d = pipeline.extract_state(LLM, p, 3, audit=MockLLM())
    first = "바람이 불었다. 서윤은 등대 앞에 섰다."  # mock 본문 앞 두 문장
    audits = [w for w in d.warnings if w.startswith(pipeline.AUDIT_MARK)]
    assert audits == [f"[누락 의심] 장소 이동: 인물이 다른 곳으로 옮겼는데 위치가 그대로예요 «{first}»"]  # 본문에 없는 인용은 버린다
    assert len(d.warn_to) == len(d.warnings) and d.warn_to[-1] == ""
    assert d.model_dump(exclude={"warnings", "warn_to"}) == plain.model_dump(exclude={"warnings", "warn_to"})  # 변경안 칸은 그대로


def test_audit_caps_and_survives_failure():
    p = _ready()
    p.settings.state_audit = True
    text = p.episode(3).text
    q = " ".join(text.split()[:5])
    items = [AuditItem(kind="소지품", missing=f"물건 {i}을 얻었어요", quote=f"«{q}»") for i in range(8)]
    items.append(AuditItem(kind="약속", missing="같은 것", quote=q))
    d = pipeline.extract_state(LLM, p, 3, audit=_Spy(items))
    assert len([w for w in d.warnings if w.startswith(pipeline.AUDIT_MARK)]) == pipeline.AUDIT_MAX
    d = pipeline.extract_state(LLM, p, 3, audit=_Spy(fail=True))
    assert not any(w.startswith(pipeline.AUDIT_MARK) for w in d.warnings) and d.summary


def test_policy_counts_audit_separately():
    p = _ready()
    pol = autorun.Policy(hand_pick_opening=False, max_shift=0)
    d = StateDelta(episode=3, summary="3화", warnings=["[누락 의심] 부상: 손을 다쳤어요 «x»"])
    assert autorun.review_reasons(p, d, None, pol.model_copy(update={"stop_on_warnings": True})) == []
    reasons = autorun.review_reasons(p, d, None, pol.model_copy(update={"stop_on_audit": True}))
    assert reasons == ["상태 변경안 누락 의심 1개: 부상: 손을 다쳤어요 «x»"]
    d.warnings.append("플롯 사건 누락: 등대에 오른다")
    assert autorun.review_reasons(p, d, None, pol.model_copy(update={"stop_on_warnings": True})) == ["상태 변경안 경고 1개: 플롯 사건 누락: 등대에 오른다"]


def test_audit_stage_follows_state():
    assert "audit" in settings.STAGES and settings.STAGE_PARENT["audit"] == "state"


def test_state_audit_endpoint(client):
    store.save("lh", _short(8))
    r = client.put("/api/projects/lh/state-audit", json={"on": True})
    assert r.status_code == 200 and r.json()["settings"]["state_audit"] is True


def test_audit_uses_audit_stage_and_drops_short_quotes(monkeypatch):
    import canon.llm
    p = _ready()
    p.settings.state_audit = True
    asked = []
    spy = _Spy([AuditItem(kind="부상", missing="손을 다쳤어요", quote="서윤은")])
    monkeypatch.setattr(canon.llm, "get_llm", lambda stage=None: asked.append(stage) or spy)
    d = pipeline.extract_state(LLM, p, 3)
    assert asked == ["audit"] and spy.calls == 1
    assert not any(w.startswith(pipeline.AUDIT_MARK) for w in d.warnings)  # 짧은 인용은 근거가 못 된다


def test_revert_kept_drops_old_audit_warnings():
    p = _ready()
    d = StateDelta(episode=3, summary="3화", warnings=["플롯 사건 누락", "[누락 의심] 부상: 손을 다쳤어요 «x»"], warn_to=["", ""])
    pipeline.apply_delta(p, d)
    res = StateDelta.model_validate(web._revert_kept(p, 2)["state:3"]["result"])
    assert res.warnings == ["플롯 사건 누락"] and res.warn_to == [""]


def test_estimate_counts_audit_call():
    p = _ready()
    off = autorun.estimate(p, 4, False, autorun.Policy(check=False))
    p.settings.state_audit = True
    on = autorun.estimate(p, 4, False, autorun.Policy(check=False))
    assert on["calls"]["state"] == 2 * off["calls"]["state"]


@needs_node
def test_review_groups_audit_warnings():
    got = run_js(["app.js", "review.js"], "rvWarnSplit(data, ['서윤'])", ["[누락 의심] 부상: 손을 다쳤어요 «x»", "서윤 상태창: x", "플롯 누락"])
    assert got == {"by": {"0": [1]}, "rest": [2], "audit": [0]}
