"""장면 연출 3D 연결 (docs/stage/3d/specs/07-wire.md): stage.check · 검수 지적에 3D 판정이 섞이는지, 시험 장면의 판정.

시험 장면은 tests/stage3d_scenes/*.json. 이름이 ok_ 로 시작하면 말이 되는 장면(3D 지적 0), bad_ 는 일부러 어긋난 장면이고
expect 에 [박자, 규칙, 인물] 을 적는다. 자리의 ref 는 기준점 이름이나 '@인물'. 실제 자세 12 · 틀 7 모듈로 돈다. LLM 호출 없음.
"""
import json
from pathlib import Path

import pytest

from canon import stage
from canon import stage3d as s3
from canon.schema import Character, Episode, EpisodePlot, Meta, Project, StageScene
from canon.stage3d import judge as j3

SCENES = sorted(Path(__file__).with_name("stage3d_scenes").glob("*.json"))
NAMES = {"h": "하린", "d": "도윤"}


def project() -> Project:
    return Project(meta=Meta(title="연출"), characters=[Character(id=k, name=v, role="주인공") for k, v in NAMES.items()])


def load(path: Path) -> tuple[StageScene, object, dict]:
    raw = json.loads(path.read_text())
    room = stage.make_room(raw["template"], "r1")
    ids = {a.name: a.id for a in room.anchors}

    def fix(bodies):
        for x in bodies:
            if "at" in x and not x["at"]["ref"].startswith("@"):
                x["at"]["ref"] = ids[x["at"]["ref"]]
            if x.get("facing", "").startswith("#"):
                x["facing"] = "#" + ids[x["facing"][1:]]
        return bodies

    cast = list(dict.fromkeys(x["who"] for x in raw["start"]))
    sc = StageScene.model_validate({"id": "s1", "room": "r1", "cast": cast, "role": "text", "start": fix(raw["start"]),
                                    "beats": [{**bt, "bodies": fix(bt["bodies"])} for bt in raw["beats"]]})
    return sc, room, raw


@pytest.mark.parametrize("path", SCENES, ids=[p.stem for p in SCENES])
def test_scene(path):
    sc, room, raw = load(path)
    p = project()
    got = sorted([v.beat, v.rule, v.who] for v in j3.judge3d(sc, room, p))
    assert got == sorted(raw["expect"]), [v.text for v in j3.judge3d(sc, room, p)]
    assert path.stem.startswith("ok_") == (raw["expect"] == [])


def test_scene_set_size():
    ok = [p for p in SCENES if p.stem.startswith("ok_")]
    bad = [p for p in SCENES if p.stem.startswith("bad_")]
    assert len(ok) + len(bad) == len(SCENES) and len(ok) >= 5 and len(bad) >= 5
    rules = {r for p in bad for _, r, _ in json.loads(p.read_text())["expect"]}
    assert rules == set(j3.RULES3D)  # 규칙마다 어긋난 장면이 하나 이상


def test_ready_is_complete():
    assert s3.ready() and s3.complete()


def _bad_floor():
    return load(Path(__file__).with_name("stage3d_scenes") / "bad_reach_floor.json")


def test_check_mixes_3d(monkeypatch):
    sc, room, _ = _bad_floor()
    p = project()
    ep = Episode(plot=EpisodePlot(number=1, act="기", title="t", summary="", events=["사건"], characters=["h", "d"], emotional_shift="", ending_hook=""), stage=[sc])
    rules = [v["rule"] for v in stage.check(p, ep, sc, room)["violations"]]
    assert rules == ["reach3d"]
    monkeypatch.setattr(s3, "complete", lambda: False)  # 등록부가 덜 차면 2D 만
    assert stage.check(p, ep, sc, room)["violations"] == []


def test_vocab_rules():
    v = stage.vocab()
    assert set(v["rules"]) == set(stage.RULES) | set(j3.RULES3D)
    assert v["rules3d"] == sorted(j3.RULES3D)


def test_2d_reach_not_repeated_in_3d():
    sc, room, _ = load(Path(__file__).with_name("stage3d_scenes") / "ok_stand_hold_wrist.json")
    sc.beats[0].bodies[0].contacts[0].to = "h"
    far = sc.model_copy(deep=True)
    far.beats[0].bodies.insert(0, far.beats[0].bodies[0].model_copy(update={"at": None, "contacts": []}))
    far.beats[0].bodies[0] = far.beats[0].bodies[0].model_copy(update={"who": "h", "at": stage.StageSpot(ref=room.anchors[0].id, rel="front")})
    far.start[0] = far.start[0].model_copy(update={"at": stage.StageSpot(ref=room.anchors[0].id, rel="front")})
    # 하린을 문 앞, 도윤을 방 반대쪽에 두면 2D reach 가 짚고, 3D reach3d 는 같은 접촉을 다시 짚지 않는다
    far.start[1] = far.start[1].model_copy(update={"at": stage.StageSpot(ref="@h", rel="front")})
    far.beats[0].bodies[1] = far.beats[0].bodies[1].model_copy(update={"at": None})
    flat = stage.judge(far, room, project())
    both = stage.judge_all(far, room, project())
    assert all(v.rule != "reach3d" for v in both)
    assert [v.rule for v in both if v.rule in stage.RULES] == [v.rule for v in flat]


def test_issues_carry_3d_text():
    sc, room, _ = _bad_floor()
    p = project()
    p.rooms = [room]
    text = "1박자"
    issues = stage.to_issues(sc, room, p, 1, text, 0)
    assert len(issues) == 1 and issues[0].description.startswith("높이: ") and issues[0].severity == "low" and issues[0].origin == "rule"
