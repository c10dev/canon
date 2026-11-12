"""작품 전체 짜기(docs/blueprint/specs/11-whole.md 의 11b): 쌍 고르기 · 프롬프트 · mock 짜기 · 정리 · 한 번에 더하기 · 몰림 · 맞물림 · 작업 API. LLM 비용 없음 (mock)."""
import pytest

from canon import blueprint, context, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import (AbilityDraft, AbilityPlan, BlueprintPlanSet, Character, ContactLadder, ContactRung, Milestone, MilestoneDraft, PairDraft, Part,
                          Project, Relationship, RungDraft, SpotDraft)


def _harem(serial: bool = False) -> Project:
    p = Project()
    p.meta.title, p.meta.target_episodes = "비밀 계정", 40
    p.characters = [Character(id=x, name=n, role="") for x, n in (("d", "도준"), ("y", "윤서"), ("s", "수빈"), ("r", "예린"))]
    p.relationships = [Relationship(a="d", b="y", type="동기"), Relationship(a="d", b="s", type="후배", destination="연인"), Relationship(a="y", b="s", type="친구")]
    if serial:
        p.meta.form = "serial"
        p.parts = [Part(number=1, title="1부", start_ep=1, end_ep=20, goal="윤서 먼저, 수빈 다음", arc_ideas=["1~10 윤서", "11~20 수빈"]),
                   Part(number=2, title="2부", start_ep=21, end_ep=40, goal="예린")]
    return p


def test_whole_pairs_default_and_picks():
    p = _harem()
    assert blueprint.whole_pairs(p) == [("d", "y"), ("d", "s"), ("y", "s")]
    assert blueprint.whole_pairs(p, ["s~d", "d~r", "d~d", "x~d", "d~s"]) == [("d", "s"), ("d", "r")]  # 관계 차례 a · b 를 지키고, 관계 밖 쌍도 받는다


def test_stage_before_and_have_lines():
    p = _harem(serial=True)
    p.blueprint.milestones = [Milestone(id="ms-1", source="y", target="d", from_ep=3, to_ep=5, stage="호감"),
                              Milestone(id="ms-2", source="y", target="d", from_ep=15, to_ep=20, stage="신뢰"),
                              Milestone(id="ms-3", source="y", target="d", from_ep=18, to_ep=22, stage="균열")]  # 범위 끝이 21화 뒤
    assert blueprint.stage_before(p, "y", "d", 20) == "신뢰" and blueprint.stage_before(p, "d", "y", 20) == ""
    lines = blueprint.whole_have_lines(p, [("d", "y")], 21, 40)
    assert lines[0] == "- 윤서 → 도준: 20화까지 계획상 신뢰" and any("균열" in x for x in lines)


def test_prompt_has_all_pairs_rules_and_budget(monkeypatch):
    p = _harem(serial=True)
    p.blueprint.milestones = [Milestone(id=f"ms-{i}", source="d", target="y", from_ep=i, to_ep=i, stage="호감", label="가" * 80) for i in range(1, 15)]
    text = prompts.blueprint_whole_prompt(p, 1, 20, blueprint.whole_pairs(p))
    assert "d~y" in text and "d~s" in text and "s~y" in text and "가 닿을 곳(작가가 정한 방향): 연인" in text
    assert "spotlight 를 먼저" in text and "엇갈려 둡니다" in text and "20자 안팎의 새 말" in text and "1~10 윤서" in text
    assert '"name": "예린"' not in text  # 고른 쌍의 인물만
    monkeypatch.setitem(context.BUDGET, "blueprint_whole", 300)
    assert "줄 생략)" in prompts.blueprint_whole_prompt(p, 1, 20, blueprint.whole_pairs(p))
    assert "blueprint_whole_req" in prompts.PIECES and prompts.KINDS["blueprint_whole"].response == "BlueprintPlanSet"


def test_mock_draft_cleans_merges_and_crowds():
    p = _harem(serial=True)
    prop = pipeline.draft_whole(MockLLM(), p, 1, ["d~y", "d~s"], "윤서 먼저")
    assert [(x.a, x.b) for x in prop.pairs] == [("d", "y"), ("d", "s")]
    first = prop.pairs[0]
    assert len(first.milestones) == 2 and [r.label for r in first.rungs][0].startswith("같은 쌍")  # 두 번째 항목의 칸을 합쳤다 (1화라 맨 앞)
    assert all(m.source in "dys" and m.target in "dys" for x in prop.pairs for m in x.milestones)  # 고르지 않은 쌍은 뺐다
    assert [(sp.from_ep, sp.to_ep, sp.focus) for sp in prop.spotlight] == [(1, 10, ["d~y"]), (11, 20, ["d~s"])]
    assert [(a.character, a.ability, a.grade) for a in prop.abilities] == [("d", "마스터 어드민", "1단계")]
    assert blueprint.proposal_crowd(p, prop) == []  # mock 은 엇갈려 놓는다


def test_chunks_of_five_see_earlier_chunk(monkeypatch):
    p = _harem()
    p.characters += [Character(id=f"h{i}", name=f"히로인{i}", role="") for i in range(5)]
    p.relationships += [Relationship(a="d", b=f"h{i}", type="") for i in range(5)]
    asks = []
    real = prompts.blueprint_whole_prompt
    monkeypatch.setattr(prompts, "blueprint_whole_prompt", lambda q, s, e, pairs, others=(): asks.append((pairs, real(q, s, e, pairs, others))) or asks[-1][1])
    prop = pipeline.draft_whole(MockLLM(), p, 0)
    assert [len(x[0]) for x in asks] == [5, 3] and len(prop.pairs) == 8
    assert "마음이 기운다" in asks[1][1].split("[이미 적은 설계도]")[1].split("[스킬 도감]")[0]  # 앞 묶음 제안을 이미 적은 줄로 받았다
    assert not p.blueprint.milestones  # 사본에만 더했다


def test_clean_set_drops_out_of_range_and_unknown():
    p = _harem()
    prop = BlueprintPlanSet(spotlight=[SpotDraft(from_ep=35, to_ep=60, focus=["y~d", "d~r"])],
                            pairs=[PairDraft(a="y", b="d", milestones=[MilestoneDraft(source="d", target="y", from_ep=50, to_ep=60, label="범위 밖")])],
                            abilities=[AbilityDraft(character="r", ability="해금", from_ep=1, to_ep=2), AbilityDraft(character="d", ability="해금 2단계", from_ep=1, to_ep=2)])
    out = blueprint.clean_set(p, prop, [("d", "y")], 1, 40)
    assert [(x.a, x.b, x.milestones) for x in out.pairs] == [("d", "y", [])]
    assert [(sp.from_ep, sp.to_ep, sp.focus) for sp in out.spotlight] == [(35, 40, ["d~y"])]
    assert [(a.character, a.ability, a.grade) for a in out.abilities] == [("d", "해금", "2단계")]  # 고른 쌍 밖 인물 빼기, 등급 꼬리 떼기


def test_apply_set_is_atomic():
    p = _harem()
    good = PairDraft(a="d", b="y", milestones=[MilestoneDraft(source="d", target="y", from_ep=1, to_ep=3, stage="호감", label="끌린다")],
                     rungs=[RungDraft(label="손", layer="맨살", from_ep=2, to_ep=2)])
    bad = PairDraft(a="d", b="s", milestones=[MilestoneDraft(source="d", target="s", from_ep=9, to_ep=3, label="거꾸로 범위")])
    with pytest.raises(ValueError):
        blueprint.apply_set(p, [good, bad], [])
    assert p.blueprint.milestones == [] and p.blueprint.ladders == []
    blueprint.apply_set(p, [good], [AbilityDraft(character="d", ability="해금", grade="1단계", from_ep=1, to_ep=2)])
    assert [m.id for m in p.blueprint.milestones] == ["ms-1"] and p.blueprint.ladders[0].rungs[0].id == "cr-1" and p.blueprint.ability_plans[0].id == "ap-1"


def test_proposal_crowd_and_mesh_only_with_new_lines():
    p = _harem()
    p.blueprint.milestones = [Milestone(id="ms-1", source="y", target="d", from_ep=5, to_ep=8, stage="호감"),
                              Milestone(id="ms-2", source="s", target="d", from_ep=6, to_ep=6, stage="호감", label="해금 뒤 고백")]  # 이미 적은 줄끼리 몰림
    p.blueprint.ladders = [ContactLadder(a="d", b="y", rungs=[ContactRung(id="cr-1", label="손", layer="맨살", from_ep=3, to_ep=3)])]
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="d", ability="해금", grade="1단계", from_ep=10, to_ep=12)]  # 이미 적은 줄끼리 맞물림 어긋남
    empty = BlueprintPlanSet(pairs=[], abilities=[])
    assert blueprint.proposal_crowd(p, empty) == [] and blueprint.proposal_mesh(p, empty) == []
    prop = BlueprintPlanSet(pairs=[PairDraft(a="d", b="r", milestones=[MilestoneDraft(source="r", target="d", from_ep=8, to_ep=9, stage="호감", label="해금 보고 반함")],
                                             rungs=[RungDraft(label="입맞춤", layer="맨살", from_ep=3, to_ep=4)])], abilities=[])
    crowd = blueprint.proposal_crowd(p, prop)
    assert {frozenset((x, y)) for x, y, _ in crowd} == {frozenset(("d~r", "d~y"))} and len(crowd) == 2  # 호감(윤서) · 맨살. 수빈 ↔ 윤서 이미 적은 줄끼리 몰림은 빼고, 예린 ↔ 수빈 호감은 범위가 안 겹친다
    mesh = blueprint.proposal_mesh(p, prop)
    assert mesh == [("d~r", "예린 → 도준 '해금 보고 반함'(8화~)에 능력 '해금' 이름이 나오는데 능력 일정은 10~12화에 얻어요.")]


def test_job_and_apply_set_api(client):
    from canon import store

    from .test_web import _wait
    meta = {"title": "하렘", "genre": "로맨스", "logline": "", "target_episodes": 30}
    assert client.post("/api/projects", json={"name": "bpw", "meta": meta}).status_code == 200
    client.post("/api/projects/bpw/suggest/apply", json=client.post("/api/projects/bpw/suggest").json())
    q = store.load("bpw")
    q.characters.append(Character(id="s", name="수빈", role=""))
    q.relationships.append(Relationship(a=q.characters[0].id, b="s", type="후배"))
    store.save("bpw", q)
    keys = [blueprint.pair_key(r.a, r.b) for r in q.relationships]
    job = client.post("/api/projects/bpw/jobs", json={"kind": "blueprint_whole", "target": "@whole", "note": "엇갈려", "pairs": keys}).json()
    res = _wait(client, job["id"])["result"]
    assert res["mode"] == "whole" and res["picked"] == keys and len(res["pairs"]) == len(keys) and res["crowd"] == []
    assert any(f["new"] for f in res["firsts"]) and res["abilities"][0]["ability"] == "마스터 어드민" and [c["name"] for c in res["codex"]] == ["마스터 어드민"]
    assert "blueprint_whole" in client.get("/api/projects/bpw/pending").json()["results"].__repr__()
    body = {"pairs": [{"a": x["a"], "b": x["b"], "milestones": x["milestones"][:1], "rungs": []} for x in res["pairs"]], "abilities": res["abilities"], "codex": res["codex"]}
    out = client.post("/api/projects/bpw/blueprint/apply-set", json=body).json()
    assert len(out["blueprint"]["milestones"]) == len(keys) and len(out["blueprint"]["ability_plans"]) == 1
    assert [(a["name"], a["source"]) for a in out["abilities"]] == [("마스터 어드민", "ai")]  # 도감 초안도 같은 사본에 만든다 (13 과 같다)
    again = client.post("/api/projects/bpw/blueprint/apply-set", json={"pairs": [], "abilities": res["abilities"]})
    assert again.status_code == 400  # 같은 능력 줄이 두 줄 → 아무것도 바꾸지 않는다
    assert client.post("/api/projects/bpw/jobs", json={"kind": "blueprint_whole", "target": "@whole", "pairs": ["x~y"]}).status_code == 400


def test_whole_uses_its_own_out_cap(monkeypatch):
    from canon import llm as llm_mod
    seen = []
    real = MockLLM.json

    def spy(self, *a, **k):
        seen.append(llm_mod._out_cap.get())
        return real(self, *a, **k)
    monkeypatch.setattr(MockLLM, "json", spy)
    pipeline.draft_whole(MockLLM(), _harem(), 0)
    assert seen == [pipeline.WHOLE_OUT_TOKENS] and pipeline.WHOLE_OUT_TOKENS > pipeline.BLUEPRINT_OUT_TOKENS  # 쌍 여럿의 응답과 생각이 08 의 한도를 넘는다


def test_pair_prompts_share_stage_and_id_rules():
    """쌍 설계도 요청 셋(거꾸로 뽑기 · 짜기 · 전체 짜기)이 단계 말 줄과 id 줄을 한 곳(_bp_stage_rule · _bp_id_rule)에서 받는다."""
    import typing

    from canon.schema import RelStage
    from .test_blueprint import _ep_project
    p, h = _ep_project(), _harem(serial=True)
    stage = prompts._bp_stage_rule()
    assert stage.startswith("stage 는 " + " · ".join(typing.get_args(RelStage)) + " 가운데")
    texts = {"extract": prompts.blueprint_extract_prompt(p, 1, 8, "hero", "ally"), "draft": prompts.blueprint_draft_prompt(p, 1, 8, "hero", "ally"),
             "whole": prompts.blueprint_whole_prompt(h, 1, 20, blueprint.whole_pairs(h))}
    assert all(f"\n- {stage}" in t for t in texts.values())
    assert prompts._bp_id_rule("이끈") in texts["extract"] and all(prompts._bp_id_rule("이끄는") in texts[k] for k in ("draft", "whole"))
