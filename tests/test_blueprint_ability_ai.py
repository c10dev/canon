"""능력 일정을 AI 로 짜기 · 지금 플롯에서 거꾸로 뽑기 (docs/blueprint/specs/12-ability-ai.md): 정리 · 더하기 · 프롬프트 · 작업 API. mock LLM."""
import pytest

from canon import blueprint, context, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Ability, AbilityDraft, AbilityGrade, AbilityPlan, BlueprintEvidence

from .test_blueprint_ability import _grown
from .test_serial import _plan_arc, _serial


def _row(**kw) -> AbilityDraft:
    return AbilityDraft(**{"character": "hero", "ability": "빙결", "from_ep": 3, "to_ep": 3, **kw})


def test_clean_splits_grade_then_drops_duplicates_and_outsiders():
    p = _grown()
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="hero", ability="빙결", grade="중급", from_ep=6, to_ep=7)]
    rows = [_row(ability="빙결 (초급)", evidence=[BlueprintEvidence(episode=3, quote="얼음이 맺힌다"), BlueprintEvidence(episode=40, quote="범위 밖"),
                                              BlueprintEvidence(episode=2, quote=" ")]),
            _row(ability="빙결", grade="초급"),            # 꼬리를 뗀 앞줄과 같은 줄
            _row(ability="빙 결", grade="(중급)", from_ep=6, to_ep=6),  # 이미 적은 줄과 같다
            _row(ability="빙결", grade="상급", from_ep=7, to_ep=30),  # 범위를 자른다
            _row(character="ally", ability="은신"),        # 고른 인물이 아니다
            _row(character="nobody", ability="은신"),
            _row(ability=" "), _row(ability="비행", from_ep=20, to_ep=21), _row(ability="질주", from_ep=0, to_ep=0)]
    out = blueprint.clean_abilities(p, rows, {"hero"}, 1, 8)
    assert [(x.ability, x.grade, x.from_ep, x.to_ep) for x in out] == [("빙결", "(초급)", 3, 3), ("빙결", "상급", 7, 8)]
    assert [e.quote for e in out[0].evidence] == ["얼음이 맺힌다"]
    both = blueprint.clean_abilities(p, [_row(character="ally", ability="은신", from_ep=2, to_ep=2), _row(ability="질주", from_ep=5, to_ep=5)], {"hero", "ally"}, 1, 8)
    assert [x.character for x in both] == [c.id for c in p.characters if c.id in ("hero", "ally")]  # 인물 목록 차례


def test_apply_adds_only_plans_and_is_atomic():
    p = _grown()
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="hero", ability="빙결", grade="중급", condition="작가가 적음", from_ep=6, to_ep=7)]
    log, stats = [r.model_dump() for r in p.stat_log], [s.model_dump() for s in p.states]
    blueprint.apply_abilities(p, [_row(grade="초급", condition="첫 각성")])
    plans = p.blueprint.ability_plans
    assert [(x.id, x.grade, x.condition) for x in plans] == [("ap-1", "중급", "작가가 적음"), ("ap-2", "초급", "첫 각성")]  # 이미 적은 줄은 그대로
    assert [r.model_dump() for r in p.stat_log] == log and [s.model_dump() for s in p.states] == stats  # 실제 기록은 건드리지 않는다
    assert blueprint.ability_states(p)[1]["got"] == 3 and blueprint.ability_states(p)[1]["state"] == "얻음"  # 이름으로 상태창 기록과 이어진다
    with pytest.raises(ValueError, match="두 줄"):
        blueprint.apply_abilities(p, [_row(ability="질주", from_ep=5, to_ep=5), _row(grade="(초급)")])
    assert len(p.blueprint.ability_plans) == 2  # 한 줄이 어긋나면 아무것도 더하지 않는다


def test_ai_block_lists_names_and_keeps_obtained_lines_within_budget():
    p = _grown()
    p.abilities = [Ability(id="ab-1", name="빙결", aliases=["얼음 손"], stat="특성", effect="닿은 것을 얼린다", grades=[AbilityGrade(grade="초급"), AbilityGrade(grade="중급")])]
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="hero", ability="빙결", grade="초급", from_ep=3, to_ep=3),
                                 AbilityPlan(id="ap-2", character="ally", ability="은신", from_ep=4, to_ep=5)]
    s = prompts.ability_ai_block(p, {"hero"})
    assert "- 빙결 (= 얼음 손) [특성] 등급: 초급 → 중급: 닿은 것을 얼린다" in s and "빙결(초급)" in s.split("[지금 상태창의 능력]")[1]
    assert "빙결 초급 (3화)" in s  # 이미 얻은 줄도 넣는다 (다시 제안하지 않게)
    assert "은신" not in s  # 다른 인물의 줄은 넣지 않는다
    p.abilities += [Ability(id=f"ab-{i}", name=f"기술{i}", effect="가" * 60) for i in range(2, 80)]
    budget = context.BUDGET["ability_ai"]
    long = prompts.ability_ai_block(p, {"hero"})
    assert len(long) < budget + 200 and "줄 생략)" in long and "빙결 초급 (3화)" in long  # 도감이 커도 예산 안이고, 이미 적은 줄이 먼저 남는다


def test_extract_and_draft_prompts():
    p = _grown()
    s = prompts.ability_extract_prompt(p, 1, 8, "hero")
    name = next(c.name for c in p.characters if c.id == "hero")
    assert f"{name}의 능력 일정을 거꾸로 뽑으세요" in s and "[화별 플롯]" in s and "한 글자도 바꾸지 않고" in s and "수치의 오르내림은 능력이 아니므로" in s
    assert p.episode(8).plot.title in s
    assert "1~8화 안" in s
    d = prompts.ability_draft_prompt(p, 1, 8, "hero")
    assert f"{name}의 능력 일정을 짜세요" in d and "10화 이하" in d and "[화별 플롯]" not in d and "[부 구성]\n없음" in d
    for kind, piece in (("blueprint_ability", "ability_extract_req"), ("blueprint_ability_draft", "ability_draft_req")):
        k = prompts.KINDS[kind]
        assert k.response == "AbilityProposal" and piece in k.pieces and getattr(prompts, k.request) and prompts.PIECES[piece].source == k.request
    assert "blueprint_ability" not in prompts.BRIEF_KINDS and "blueprint_ability_draft" not in prompts.BRIEF_KINDS  # 08 과 같이 작업지시서는 내지 않는다


def test_pipeline_extract_and_draft_with_mock():
    p = _grown()
    prop = pipeline.propose_abilities(MockLLM(), p, 0, "hero")
    assert [(x.ability, x.grade, x.from_ep, x.to_ep) for x in prop.abilities] == [("은신", "", 1, 1), ("은신", "Lv2", 4, 8)]  # 꼬리 떼기 · 같은 줄 · 다른 인물 · 범위 밖을 정리
    assert [e.episode for e in prop.abilities[0].evidence] == [1] and not p.blueprint.ability_plans  # 저장하지 않는다
    with pytest.raises(ValueError, match="인물을 골라"):
        pipeline.propose_abilities(MockLLM(), p, 0, "nobody")
    s = _serial()  # 부 구성만 있고 플롯은 없다
    cid, part = s.characters[0].id, s.parts[0]
    prop = pipeline.draft_abilities(MockLLM(), s, part.number, cid, "1부 끝에 은신 Lv2")
    assert prop.abilities and all(part.start_ep <= x.from_ep <= x.to_ep <= part.end_ep and x.character == cid for x in prop.abilities)
    assert part.goal in prompts.ability_draft_prompt(s, part.start_ep, part.end_ep, cid)
    with pytest.raises(ValueError, match="플롯이 있는 화가 없어요"):
        pipeline.propose_abilities(MockLLM(), s, 0, cid)
    arc = _plan_arc(s)
    prop = pipeline.propose_abilities(MockLLM(), s, arc.number, cid)
    assert all(arc.start_ep <= x.from_ep <= x.to_ep <= arc.end_ep for x in prop.abilities)  # 장편은 아크 하나


def test_job_pending_and_apply_api(client):
    from .test_web import _wait
    meta = {"title": "각성", "genre": "판타지", "logline": "", "target_episodes": 8}
    assert client.post("/api/projects", json={"name": "bpa", "meta": meta}).status_code == 200
    p = client.post("/api/projects/bpa/suggest/apply", json=client.post("/api/projects/bpa/suggest").json()).json()
    cid = p["characters"][0]["id"]
    job = client.post("/api/projects/bpa/jobs", json={"kind": "blueprint_ability_draft", "target": cid, "note": "천천히"}).json()
    done = _wait(client, job["id"])
    res = done["result"]
    assert done["status"] == "done" and res["mode"] == "draft" and res["character"] == cid and (res["start"], res["end"]) == (1, 8)
    pending = client.get("/api/projects/bpa/pending").json()["results"]
    assert any(k.startswith("blueprint_ability_draft:") and k.endswith(f":{cid}") for k in pending)  # 인물마다 따로 남는다
    assert client.get("/api/projects/bpa").json()["blueprint"]["ability_plans"] == []  # 고르기 전에는 저장하지 않는다
    bad = client.post("/api/projects/bpa/jobs", json={"kind": "blueprint_ability", "target": cid})
    assert bad.status_code == 400 and "플롯이 있는 화가 없어요" in bad.text
    assert client.post("/api/projects/bpa/jobs", json={"kind": "blueprint_ability_draft", "target": "nobody"}).status_code == 400
    out = client.post("/api/projects/bpa/blueprint/apply-abilities", json={"abilities": res["abilities"][:1]}).json()
    assert [(x["id"], x["ability"]) for x in out["blueprint"]["ability_plans"]] == [("ap-1", "은신")]
    again = client.post("/api/projects/bpa/blueprint/apply-abilities", json={"abilities": res["abilities"][:1]})
    assert again.status_code == 400 and "두 줄" in again.text
    assert len(client.get("/api/projects/bpa").json()["blueprint"]["ability_plans"]) == 1
