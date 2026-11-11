"""능력 일정 제안과 함께 받는 스킬 도감 초안 (docs/blueprint/specs/13-ability-codex.md): 정리 · 더하기 · 프롬프트 · API. mock LLM."""
import pytest

from canon import blueprint, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Ability, AbilityCodexDraft, AbilityDraft, AbilityGrade

from .test_blueprint_ability import _grown
from .test_serial import _serial


def _row(**kw) -> AbilityDraft:
    return AbilityDraft(**{"character": "hero", "ability": "질주", "from_ep": 3, "to_ep": 3, **kw})


def test_clean_codex_keeps_only_new_names_of_kept_rows():
    p = _grown()
    p.abilities = [Ability(id="ab-1", name="빙결", aliases=["얼음 손"])]
    rows = [_row(), _row(ability="얼음 손", from_ep=4, to_ep=4)]
    codex = [AbilityCodexDraft(name="질주 Lv1", effect=" 빨리 달린다 ", grades=[AbilityGrade(grade="Lv2", effect="더 빨리"), AbilityGrade(grade=" ")]),
             AbilityCodexDraft(name="질 주", effect="같은 이름"),     # 띄어쓰기만 다른 같은 이름
             AbilityCodexDraft(name="얼음 손", effect="도감에 있는 다른 이름"),
             AbilityCodexDraft(name="비행", effect="남은 줄이 없는 능력"),
             AbilityCodexDraft(name=" ")]
    out = blueprint.clean_codex(p, codex, rows)
    assert [(c.name, c.effect, [g.grade for g in c.grades]) for c in out] == [("질주", "빨리 달린다", ["Lv2"])]


def test_clean_codex_takes_stat_name_from_status_window():
    p = _grown()
    stat, piece = next((s, x) for st in p.states for s, x in blueprint.abilities.list_pieces(p, {v.name: v.value for v in st.stats}))
    name = blueprint.abilities.split(piece)[0]
    out = blueprint.clean_codex(p, [AbilityCodexDraft(name=name, stat="엉뚱한 항목"), AbilityCodexDraft(name="질주", stat="스킬")],
                                [_row(ability=name), _row()])
    assert [(c.name, c.stat) for c in out] == [(name, stat), ("질주", "스킬")]  # 상태창에 있는 조각은 그 항목 이름, 없으면 AI 값


def test_apply_makes_ai_codex_entries_and_stays_atomic():
    p = _grown()
    p.abilities = [Ability(id="ab-1", name="빙결")]
    made = blueprint.apply_abilities(p, [_row()], [AbilityCodexDraft(name="질주", stat="스킬", effect="빨리 달린다", cost="숨이 찬다")])
    a = p.abilities[-1]
    assert made == [a.id] and (a.name, a.stat, a.effect, a.cost, a.source, a.created_ep) == ("질주", "스킬", "빨리 달린다", "숨이 찬다", "ai", 0)
    assert blueprint.ability_states(p)[0]["linked"] is True and not [t for _, t in blueprint.ability_warning_rows(p) if "도감에 없는" in t]
    assert blueprint.apply_abilities(p, [], [AbilityCodexDraft(name="질주", effect="그새 생긴 이름")]) == [] and p.abilities[-1].effect == "빨리 달린다"
    n = len(p.abilities)
    with pytest.raises(ValueError, match="두 줄"):
        blueprint.apply_abilities(p, [_row()], [AbilityCodexDraft(name="은신")])
    assert len(p.abilities) == n and len(p.blueprint.ability_plans) == 1  # 줄이 어긋나면 도감도 그대로


def test_prompts_ask_for_codex_and_mock_is_cleaned():
    p = _grown()
    assert "codex 에 도감 초안" in prompts.ability_extract_prompt(p, 1, 8, "hero")
    s = _serial()
    assert "codex 에 도감 초안" in prompts.ability_draft_prompt(s, s.parts[0].start_ep, s.parts[0].end_ep, s.characters[0].id)
    prop = pipeline.propose_abilities(MockLLM(), p, 0, "hero")
    assert [(c.name, [g.grade for g in c.grades]) for c in prop.codex] == [("은신", ["Lv2"])]  # 꼬리 떼기 · 같은 이름 · 줄 없는 능력 · 빈 등급을 정리
    p.abilities = [Ability(id="ab-1", name="은신")]
    assert pipeline.propose_abilities(MockLLM(), p, 0, "hero").codex == []  # 도감에 있으면 초안을 내지 않는다


def test_apply_api_takes_codex(client):
    from .test_web import _wait
    meta = {"title": "각성", "genre": "판타지", "logline": "", "target_episodes": 8}
    assert client.post("/api/projects", json={"name": "bpc", "meta": meta}).status_code == 200
    p = client.post("/api/projects/bpc/suggest/apply", json=client.post("/api/projects/bpc/suggest").json()).json()
    cid = p["characters"][0]["id"]
    res = _wait(client, client.post("/api/projects/bpc/jobs", json={"kind": "blueprint_ability_draft", "target": cid}).json()["id"])["result"]
    assert [c["name"] for c in res["codex"]] == ["은신"]
    out = client.post("/api/projects/bpc/blueprint/apply-abilities", json={"abilities": res["abilities"][:1], "codex": res["codex"]}).json()
    assert [(a["name"], a["source"]) for a in out["abilities"]] == [("은신", "ai")] and len(out["blueprint"]["ability_plans"]) == 1
    view = client.get("/api/projects/bpc/blueprint").json()
    assert view["plans"][0]["linked"] is True
    assert client.post("/api/projects/bpc/blueprint/apply-abilities", json={"abilities": res["abilities"][:1]}).status_code == 400
