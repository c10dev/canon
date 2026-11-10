"""설계도(canon/blueprint.py): 저장 검사 · 계획 칸 · 화 번호 옮기기. LLM 비용 없음 (mock)."""
import json
import typing

import pytest

from canon import blueprint, pipeline, renumber
from canon.schema import Blueprint, Character, ContactLadder, ContactRung, Milestone, Project, RelStage, StoryElement

from .test_convert import LLM, _short
from .test_insert import _short as _short_insert


def _proj() -> Project:
    p = Project()
    p.characters = [Character(id="a", name="아영", role="주인공", personality="", speech_style="", appearance="", goal="", backstory=""),
                    Character(id="j", name="지훈", role="상대", personality="", speech_style="", appearance="", goal="", backstory="")]
    p.elements = [StoryElement(id="el-1", kind="장소", name="4-2번 칸", description="지하철 칸"),
                  StoryElement(id="el-2", kind="예정 사건", name="단속", description="경찰 단속")]
    return p


def _ladder(*rungs: ContactRung) -> ContactLadder:
    return ContactLadder(a="a", b="j", rungs=list(rungs))


def test_old_project_reads_with_empty_blueprint():
    raw = json.loads(Project().model_dump_json())
    raw.pop("blueprint")
    p = Project.model_validate(raw)
    assert p.blueprint == Blueprint()
    blueprint.check(p)  # 빈 설계도는 통과


def test_stage_words_match_dynamics():
    stage_field = typing.get_args(Milestone.model_fields["stage"].annotation)
    assert set(stage_field) == {"", *typing.get_args(RelStage)}


def test_fill_ids_keeps_existing():
    p = _proj()
    p.blueprint.milestones = [Milestone(id="ms-1", source="a", target="j"), Milestone(source="j", target="a")]
    p.blueprint.ladders = [_ladder(ContactRung(label="스침"), ContactRung(id="cr-1", label="손"))]
    blueprint.check(p)
    assert [m.id for m in p.blueprint.milestones] == ["ms-1", "ms-2"]
    assert [r.id for r in p.blueprint.ladders[0].rungs] == ["cr-2", "cr-1"]
    blueprint.check(p)  # 다시 저장해도 그대로
    assert [r.id for r in p.blueprint.ladders[0].rungs] == ["cr-2", "cr-1"]


@pytest.mark.parametrize("change, match", [
    (lambda p: p.blueprint.milestones.append(Milestone(source="a", target="a")), "같은 인물끼리"),
    (lambda p: p.blueprint.milestones.append(Milestone(source="a", target="x")), "없는 인물"),
    (lambda p: p.blueprint.milestones.append(Milestone(source="a", target="j", from_ep=5)), "한쪽만"),
    (lambda p: p.blueprint.milestones.append(Milestone(source="a", target="j", from_ep=9, to_ep=5)), "앞이에요"),
    (lambda p: p.blueprint.ladders.extend([_ladder(), ContactLadder(a="j", b="a")]), "두 번"),
    (lambda p: p.blueprint.ladders.append(_ladder(ContactRung(parts=["tail"]))), "모르는 부위"),
    (lambda p: p.blueprint.ladders.append(_ladder(ContactRung(acts=["fly"]))), "모르는 동작"),
    (lambda p: p.blueprint.ladders.append(_ladder(ContactRung(places=["el-2"]))), "장소가 아니에요"),
    (lambda p: p.blueprint.ladders.append(_ladder(ContactRung(places=["el-9"]))), "없는 요소"),
    (lambda p: p.blueprint.ladders.append(_ladder(ContactRung(lead="x"))), "이 쌍에 없어요"),
    (lambda p: p.blueprint.ladders.append(_ladder(ContactRung(from_ep=10, to_ep=12), ContactRung(from_ep=4, to_ep=6))), "빨라요"),
    (lambda p: p.blueprint.milestones.extend([Milestone(id="z", source="a", target="j"), Milestone(id="z", source="j", target="a")]), "겹쳐요"),
])
def test_check_refuses(change, match):
    p = _proj()
    change(p)
    with pytest.raises(ValueError, match=match):
        blueprint.check(p)


def test_check_accepts_full_ladder():
    p = _proj()
    p.blueprint.ladders = [_ladder(ContactRung(label="스침", parts=["hand_l"], acts=["brush"], layer="옷 위", places=["el-1"], lead="j", from_ep=1, to_ep=3),
                                   ContactRung(label="정하지 않음"),  # 범위를 비운 칸은 차례 비교에서 빠진다
                                   ContactRung(label="허리", parts=["waist"], acts=["hold"], from_ep=3, to_ep=8))]
    blueprint.check(p)


def test_old_broken_reference_is_not_blocked():
    disk = _proj()
    disk.blueprint.milestones = [Milestone(source="a", target="gone")]
    p = disk.model_copy(deep=True)
    blueprint.check(p, disk)  # 다른 라우트가 지운 인물: 옛 데이터라 막지 않는다
    p.blueprint.milestones.append(Milestone(source="j", target="gone2"))
    with pytest.raises(ValueError, match="gone2"):
        blueprint.check(p, disk)


def test_planned_rung():
    lad = _ladder(ContactRung(id="r1", from_ep=1, to_ep=3), ContactRung(id="r2"), ContactRung(id="r3", from_ep=6, to_ep=9))
    assert blueprint.planned_rung(lad, 0) is None
    assert blueprint.planned_rung(lad, 5).id == "r1"
    assert blueprint.planned_rung(lad, 6).id == "r3"
    p = _proj()
    p.blueprint.ladders = [lad]
    assert blueprint.ladder(p, "j", "a") is lad and blueprint.ladder(p, "a", "x") is None


def _moved(rng: tuple[int, int], f, gone=0) -> tuple[int, int]:
    p = _proj()
    p.blueprint.milestones = [Milestone(source="a", target="j", from_ep=rng[0], to_ep=rng[1])]
    blueprint.move(p, f, gone)
    m = p.blueprint.milestones[0]
    return m.from_ep, m.to_ep


def test_move_range_edges():
    ins, rem = renumber.point_insert, renumber.point_remove
    assert _moved((5, 8), ins(5)) == (6, 9)  # 처음 화 앞에 넣으면 통째로 민다
    assert _moved((5, 8), ins(7)) == (5, 9)  # 범위 안에 넣으면 범위가 는다
    assert _moved((5, 8), ins(9)) == (5, 8)  # 뒤에 넣으면 그대로
    assert _moved((5, 8), rem(8), gone=8) == (5, 7)  # 끝 화를 빼면 범위가 준다
    assert _moved((5, 8), rem(5), gone=5) == (5, 7)  # 처음 화를 빼면 다음 화가 처음 화
    assert _moved((5, 5), rem(5), gone=5) == (5, 5)  # 한 화뿐이면 그 자리에 온 다음 화
    assert _moved((5, 8), rem(3), gone=3) == (4, 7)
    assert _moved((0, 0), ins(1)) == (0, 0)  # 정하지 않은 범위는 그대로


def test_insert_episode_moves_blueprint():
    p = _short_insert()
    p.blueprint.milestones = [Milestone(source=p.characters[0].id, target=p.characters[1].id, from_ep=7, to_ep=9)]
    notes = pipeline.insert_episode(p, 8)
    m = p.blueprint.milestones[0]
    assert (m.from_ep, m.to_ep) == (7, 10)
    assert "설계도 줄 1개" in " ".join(notes)


def test_rebuild_remaps_and_reports_lost():
    p = _short(written=8)
    a, b = p.characters[0].id, p.characters[1].id
    p.blueprint.milestones = [Milestone(source=a, target=b, from_ep=6, to_ep=12)]
    p.blueprint.ladders = [ContactLadder(a=a, b=b, rungs=[ContactRung(label="끝", from_ep=12, to_ep=12)])]
    prop = pipeline.propose_rebuild(LLM, p, 200)
    for x in prop.episodes:  # 12화를 버린다: 뒤에 쓰인 옛 화가 없어 옮길 곳이 없다
        if 12 in x.sources:
            x.sources, x.use = [], "new"
    _, notes = pipeline.apply_rebuild(p, prop)
    assert p.blueprint.milestones[0].from_ep == 0 and p.blueprint.ladders[0].rungs[0].from_ep == 0
    assert any("관계 이정표" in n for n in notes) and any("접촉 사다리 칸 '끝'" in n for n in notes)


def test_web_save_checks_blueprint(client):
    meta = {"title": "지하철", "genre": "성인", "logline": "", "target_episodes": 10}
    assert client.post("/api/projects", json={"name": "bp", "meta": meta}).status_code == 200
    p = client.post("/api/projects/bp/suggest/apply", json=client.post("/api/projects/bp/suggest").json()).json()
    a, b = p["characters"][0]["id"], p["characters"][1]["id"]
    p["blueprint"] = {"milestones": [{"source": a, "target": b, "from_ep": 2, "to_ep": 4, "stage": "경계", "label": "의심"}],
                      "ladders": [{"a": a, "b": b, "rungs": [{"label": "스침", "parts": ["hand_r"], "acts": ["brush"]}]}]}
    p = client.put("/api/projects/bp", json=p).json()
    assert p["blueprint"]["milestones"][0]["id"] == "ms-1" and p["blueprint"]["ladders"][0]["rungs"][0]["id"] == "cr-1"
    p["blueprint"]["ladders"][0]["rungs"][0]["parts"] = ["tail"]
    r = client.put("/api/projects/bp", json=p)
    assert r.status_code == 400 and "모르는 부위" in r.json()["detail"]


def test_warnings():
    from canon import dynamics
    p = _proj()
    assert blueprint.warnings(p) == []
    p.blueprint.milestones = [Milestone(source="a", target="j", from_ep=1, to_ep=2, stage="적대"),
                              Milestone(source="a", target="j", from_ep=3, to_ep=4, stage="신뢰"),  # 적대 → 신뢰 2칸, 1~4화 3화: 괜찮다
                              Milestone(source="j", target="a", from_ep=2, to_ep=3, stage="낯섦"),
                              Milestone(source="j", target="a", from_ep=3, to_ep=4, stage="적대"),  # 범위가 겹치고 단계가 다르다
                              Milestone(source="a", target="j", stage="화해")]  # 범위 없는 줄은 보지 않는다
    w = blueprint.warnings(p)
    assert len(w) == 1 and "겹쳐요" in w[0] and "지훈 → 아영" in w[0]
    ms = p.blueprint.milestones
    ms[0].to_ep, ms[1].from_ep, ms[1].to_ep = 1, 2, 3
    assert not any("아영 → 지훈" in x for x in blueprint.warnings(p))  # 2칸에 1~3화 2화: 괜찮다
    ms[1].to_ep = 2
    assert any("적대에서 신뢰까지 2칸인데 1화부터 2화까지 1화뿐이에요" in x for x in blueprint.warnings(p))
    # 지금 단계에서 다음 이정표까지
    q = _proj()
    q.ties = [dynamics.Tie(source="a", target="j", stage="적대")]
    q.blueprint.milestones = [Milestone(source="a", target="j", from_ep=1, to_ep=1, stage="신뢰")]
    assert blueprint.warnings(q) == ["관계 이정표 아영 → 지훈: 지금 적대에서 1화까지 신뢰에 닿으려면 2칸인데 1화 남았어요(한 화에 한 칸)."]
    q.ties[0].stage = "균열"
    assert blueprint.warnings(q) == []  # 균열 → 신뢰는 한 칸
