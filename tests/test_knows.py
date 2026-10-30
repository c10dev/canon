"""아는 정보(canon/knows.py): 알게 된 화 표시, 상태 변경안이 따라 적은 표시 떼기, 아크 요약 뒤 접기 제안 · 적용 · 되돌리기 ·
반영 취소와의 관계, 웹 라우트. 실행: python -m pytest tests"""
import re
from pathlib import Path

import pytest

from canon import context, features, knows, pipeline, prompts
from canon.mock_knows import MOCK_FOLD
from canon.schema import CharacterState, KnowsFold, KnowsFoldSet, StateDelta

from .test_serial import LLM, _plan_arc, _serial
from .test_web import client  # noqa: F401  (pytest fixture)

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"


def _project(per_ep=3):
    """1~12화를 반영한 장편. 서윤은 화마다 아는 정보가 per_ep 개씩 는다 (12화면 36개)."""
    p = _serial()
    a = _plan_arc(p)
    for n in range(a.start_ep, a.end_ep + 1):
        e = p.episode(n)
        e.text, e.status = f"{n}화 본문", "written"
        upd = CharacterState(character_id="hero", knows=[f"{n}화에 안 것 {i}" for i in range(per_ep)])
        pipeline.apply_delta(p, StateDelta(episode=n, summary=f"{n}화 요약", character_updates=[upd]))
    return p, a


def test_learned_and_prompt_tags():
    p, a = _project()
    assert knows.learned(p)["hero"]["5화에 안 것 1"] == 5
    s = p.state_of("hero")
    view = knows.view(p, s, s.knows[-2:])
    assert view == [f"({a.end_ep}화) {a.end_ep}화에 안 것 1", f"({a.end_ep}화) {a.end_ep}화에 안 것 2"]
    states, cut = prompts.state_view(p, [s], a.end_ep + 1, "")
    assert cut == len(s.knows) - context.KNOWS_KEEP and states[0].knows[-1].startswith(f"({a.end_ep}화) ")
    assert s.knows[-1] == f"{a.end_ep}화에 안 것 2"  # 저장된 상태는 그대로


def test_clean_strips_tags():
    p, a = _project()
    d = StateDelta(episode=a.end_ep, summary="", character_updates=[
        CharacterState(character_id="hero", knows=["(3화) 등대 열쇠는 둘이다", "(12화까지 요약) 접은 줄", "새로 안 것", "(요약) 다른 줄"])])
    features.clean(p, d)
    assert d.character_updates[0].knows == ["등대 열쇠는 둘이다", "접은 줄", "새로 안 것", "다른 줄"]


def test_targets_need_summary_and_enough_old_lines():
    p, a = _project()
    with pytest.raises(ValueError, match="요약"):
        knows.targets(p, a.number)
    a.summary = "아크 요약"
    got = knows.targets(p, a.number)
    assert list(got) == ["hero"]
    assert len(got["hero"]) == 3 * 12 - context.KNOWS_RECENT  # 맨 뒤 KNOWS_RECENT 개는 프롬프트에 늘 들어가 접지 않는다
    q, b = _project(per_ep=1)  # 12개뿐이면 접지 않아도 다 들어간다
    b.summary = "요약"
    assert knows.targets(q, b.number) == {}


def test_fold_apply_prompt_undo():
    p, a = _project()
    a.summary = "아크 요약"
    fs = pipeline.fold_knows(LLM, p, a.number)
    assert [(f.character_id, f.lines) for f in fs.folds] == [("hero", [MOCK_FOLD, f"hero는 아크 {a.number}의 비밀을 안다"])]  # 화 표시를 뗐다
    before = list(p.state_of("hero").knows)
    recs = knows.apply_fold(p, a.number, fs)
    s = p.state_of("hero")
    assert len(recs) == 1 and len(s.knows) == context.KNOWS_RECENT and s.knows == before[-context.KNOWS_RECENT:]
    assert s.knows_folded == fs.folds[0].lines
    states, cut = prompts.state_view(p, [s], a.end_ep + 1, "")
    assert cut == 0 and states[0].knows[0] == f"({a.end_ep}화까지 요약) {MOCK_FOLD}"
    assert "knows_folded" not in prompts.dump(states)  # 프롬프트 직렬화는 접은 줄 칸을 따로 보이지 않는다
    assert knows.undo_fold(p, a.number) == 1
    assert p.state_of("hero").knows == before and p.state_of("hero").knows_folded == [] and p.knows_folds == []
    with pytest.raises(ValueError):
        knows.undo_fold(p, a.number)


def test_clean_fold_limits_and_skips():
    p, a = _project()
    a.summary = "요약"
    fs = KnowsFoldSet(folds=[KnowsFold(character_id="ally", lines=["접을 것이 없는 인물"]),
                             KnowsFold(character_id="hero", lines=[" 가 ", "가", "", *[f"줄 {i}" for i in range(12)], "나" * 300])])
    out = knows.clean_fold(p, a.number, fs)
    assert [f.character_id for f in out.folds] == ["hero"]
    assert out.folds[0].lines[:2] == ["가", "줄 0"] and len(out.folds[0].lines) == knows.FOLD_LINES


def test_revert_before_fold_drops_record():
    p, a = _project()
    a.summary = "요약"
    knows.apply_fold(p, a.number, KnowsFoldSet(folds=[KnowsFold(character_id="hero", lines=["접은 줄"])]))
    pipeline.revert(p, a.end_ep - 1)  # 스냅샷은 접기 전 상태다
    assert p.state_of("hero").knows_folded == [] and p.knows_folds == []


def test_js_keep_matches_context():
    src = (STATIC / "knows.js").read_text(encoding="utf-8")
    assert int(re.search(r"const KNOWS_KEEP = (\d+);", src).group(1)) == context.KNOWS_KEEP


def test_web_fold_routes(client):  # noqa: F811
    from canon import store as st

    p, a = _project()
    a.summary = "요약"
    st.save("kf", p)
    body = {"folds": [{"character_id": "hero", "lines": ["접은 줄 하나", "접은 줄 둘"]}]}
    out = client.post(f"/api/projects/kf/knows-fold/{a.number}", json=body).json()
    hero = next(s for s in out["states"] if s["character_id"] == "hero")
    assert hero["knows_folded"] == ["접은 줄 하나", "접은 줄 둘"] and out["knows_folds"][0]["arc"] == a.number
    out = client.delete(f"/api/projects/kf/knows-fold/{a.number}").json()
    assert out["knows_folds"] == []
    assert client.post(f"/api/projects/kf/knows-fold/{a.number}", json={"folds": []}).status_code == 400
