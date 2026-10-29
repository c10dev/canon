"""장면 연출 AI 방 제안: 초안이 방에 없는 장소를 기준점으로 더하자고 하면 코드가 자리를 정하고(place_anchors), 적용하면 방에 더하며
(공용 방이면 복사한 장면 전용 방), 적용 취소는 방도 되돌린다. 2026-10-29 15화 사건 1(캠핑카 운전석 · 창밖 · 정비차 짐칸)을 mock 으로.
실행: python -m pytest tests"""
import time

import pytest

from canon import pipeline, stage
from canon.mock import MockLLM
from canon.schema import (BoardScene, Character, DraftAnchor, DraftBeat, DraftBody, Meta, Project, StageDraft, StageRoom, Storyboard)

from .jsvm import episode
from .test_web import client  # noqa: F401  (pytest fixture)

EVENT = "예은이 정비차 배터리가 죽었다며 점프를 부탁한다. 건우는 차 안 충전 슬롯으로 연결하되 예은을 차에 타지 못하게 한다."


def _project(room_place: str = "") -> Project:
    p = Project(meta=Meta(title="캠핑카", target_episodes=20), characters=[
        Character(id="hero", name="최건우", role="주인공", age="29"),
        Character(id="char2", name="이예은", role="조연", age="27"),
    ], episodes=[episode(15, plot={"title": "점프", "events": [EVENT, "약도를 그려 준다"], "characters": ["hero", "char2"]})])
    if room_place:  # 사용자가 만든 공용 빈 방 (지도 장소에 묶임)
        p.rooms.append(stage.make_room("empty", "r1", "초소 철문 앞", room_place))
    return p


def _draft() -> StageDraft:
    """Gemini 가 낼 법한 초안: 운전석 · 운전석 창 · 정비차 짐칸을 더하고 박자 자리에 그 이름을 쓴다."""
    b = DraftBody
    return StageDraft(cast=["최건우", "이예은"], new_anchors=[
        DraftAnchor(name="운전석", kind="seat"),
        DraftAnchor(name="운전석 창", kind="window", near="운전석", rel="left"),
        DraftAnchor(name="정비차 짐칸", kind="other", near="운전석 창", rel="front"),
        DraftAnchor(name="운전석", kind="seat"),  # 같은 이름은 한 번만
    ], start=[
        b(name="최건우", at_ref="운전석", at_rel="on", posture="chair", facing="이예은", left="빈손", right="빈손"),
        b(name="이예은", at_ref="운전석 창", at_rel="front", posture="stand", facing="최건우", left="빈손", right="긴 렌치"),
    ], beats=[
        DraftBeat(note="예은이 정비차 쪽으로 돌아선다", bodies=[b(name="이예은", posture="walk", facing="정비차 짐칸")]),
        DraftBeat(note="짐칸 공구함에서 점프 스타터를 꺼낸다", bodies=[b(name="이예은", at_ref="정비차 짐칸", at_rel="front", posture="stand", right="점프 스타터")]),
        DraftBeat(note="운전석 창가로 돌아온다", bodies=[b(name="이예은", posture="walk", facing="최건우")]),
        DraftBeat(note="창 밖에 선다", bodies=[b(name="이예은", at_ref="운전석 창", at_rel="front", posture="stand")]),
        DraftBeat(note="창틈으로 스타터를 넘긴다", bodies=[b(name="이예은", right="빈손"), b(name="최건우", left="점프 스타터")]),
    ])


class Scripted(MockLLM):
    def json(self, system, prompt, schema, hint=None):
        if schema is StageDraft:
            self.prompt = prompt
            return _draft()
        return super().json(system, prompt, schema, hint)


def _a(room: StageRoom, name: str):
    return next(a for a in room.anchors if a.name == name)


def test_place_anchors_beside_and_grow():
    room = stage.make_room("empty", "r1")
    grown, adds, dx, dy = stage.place_anchors(room, _draft().new_anchors)
    assert [x.anchor.name for x in adds] == ["운전석", "운전석 창", "정비차 짐칸"] and room.anchors[0].x == 1.6  # 원래 방은 그대로
    seat, win, truck = (_a(grown, n) for n in ("운전석", "운전석 창", "정비차 짐칸"))
    assert seat.sit and seat.kind == "seat" and win.kind == "window" and truck.kind == "other"
    assert win.x + win.w == pytest.approx(seat.x) and win.rot == 90  # 운전석 왼쪽(앞에서 본)에 맞붙고 앞쪽이 바깥(창밖)이다
    assert truck.x + truck.w + stage.ANCHOR_GAP == pytest.approx(win.x) and truck.rot == 270  # 창 앞(바깥)으로 사람 설 틈을 두고 창을 본다
    assert all(not stage._hits(a, [b for b in grown.anchors if b.id != a.id], 0) for a in grown.anchors)
    # 방 밖으로 나가 왼쪽으로 넓혔고 옛 문도 같이 옮겼다. 더한 기준점 둘레 여백이 방 안이다
    assert dx > 0 and grown.w > room.w and _a(grown, "문").x == pytest.approx(1.6 + dx)
    assert all(a.x >= stage.ROOM_PAD - 1e-9 and a.x + a.w <= grown.w - stage.ROOM_PAD + 1e-9 for a in (seat, win, truck))
    assert [x.where for x in adds] == ["빈 자리", "운전석 왼쪽", "운전석 창 앞"]
    assert stage._clear(truck, [b for b in grown.anchors if b.id != truck.id], None)  # 앞자리끼리도 겹치지 않는다
    # 모르는 종류는 기타, 모르는 near 는 빈 자리
    g2, a2, _, _ = stage.place_anchors(room, [DraftAnchor(name="나무", kind="tree", near="없는 곳", rel="left")])
    assert a2[0].anchor.kind == "other" and a2[0].where == "빈 자리" and not stage._hits(a2[0].anchor, room.anchors, 0.5)


def _judge(p, scene):
    room = stage.room_of(p, scene)
    return [f"{v.beat} {v.rule} {v.text}" for v in stage.judge_all(scene, room, p)]


def test_fresh_draft_apply_moves_and_undo():
    p = _project()
    llm = Scripted()
    prop = pipeline.draft_stage(llm, p, 15, 0, fresh="empty")
    assert "new_anchors" in llm.prompt and "창밖에 선 사람은 그 창 front" in llm.prompt  # 초안 프롬프트가 기준점 제안을 시킨다
    assert prop.room is not None and prop.grown is None and len(prop.adds) == 3  # 새 빈 방에 이미 더해져 있다
    assert any("넓혀요" in x for x in prop.notes)
    s = pipeline.apply_stage(p, prop)
    room = stage.room_of(p, s)
    assert s.room_made == room.id and {"운전석", "운전석 창", "정비차 짐칸", "문"} == {a.name for a in room.anchors}
    lay = stage.layouts(room, s)
    win, truck = _a(room, "운전석 창"), _a(room, "정비차 짐칸")
    near = lambda xy, a: abs(xy[0] - (a.x + a.w / 2)) + abs(xy[1] - (a.y + a.h / 2)) < 1.0  # noqa: E731
    assert near(lay[0]["char2"], win) and near(lay[2]["char2"], truck) and near(lay[4]["char2"], win)  # 정비차에 다녀온다
    assert lay[0]["char2"] == lay[4]["char2"] and all(xy == lay[0]["hero"] for xy in (L["hero"] for L in lay))
    assert _judge(p, s) == []  # 2D · 3D 헛지적 0
    assert pipeline.undo_stage(p, 15, s.id) is None and p.rooms == []  # 적용 취소는 만든 방도 뺀다


def test_shared_room_copies_by_default_and_undo_restores():
    p = _project("청운 비행장 후문")
    stage.new_scene(p, p.episode(15), 0, p.rooms[0])  # 사용자가 이 방으로 장면을 만든 뒤 초안을 받았다
    prop = pipeline.draft_stage(Scripted(), p, 15, 0)
    assert prop.room is None and prop.grown is not None and prop.grown.id == "r1" and len(prop.adds) == 3
    assert stage.room_shared(p, "r1", 15, 0, "plan")  # 지도 장소에 묶인 방
    s = pipeline.apply_stage(p, prop)
    shared, copy = p.rooms
    assert [a.name for a in shared.anchors] == ["문"] and copy.place == "" and copy.name == "초소 철문 앞 · 15화 사건 1"
    assert s.room == copy.id == s.room_made and _judge(p, s) == []
    back = pipeline.undo_stage(p, 15, s.id)
    assert [r.id for r in p.rooms] == ["r1"] and back.room == "r1"
    # 공용 방에 바로 더하기: 방이 바뀌고, 적용 취소가 적용 전 모습으로 되돌린다
    prop = pipeline.draft_stage(Scripted(), p, 15, 0)
    s = pipeline.apply_stage(p, prop, shared=True)
    assert len(p.rooms) == 1 and len(p.rooms[0].anchors) == 4 and s.room == "r1" and s.room_prev.anchors[0].name == "문"
    pipeline.undo_stage(p, 15, s.id)
    assert p.rooms[0].model_dump() == stage.make_room("empty", "r1", "초소 철문 앞", "청운 비행장 후문").model_dump()


def test_apply_merges_author_room_edits_and_remaps_ids():
    p = _project()
    room = stage.new_room(p, "empty", "초소 철문 앞")  # 장면 전용 방 (장소 없음, 다른 장면 없음)
    stage.new_scene(p, p.episode(15), 0, room)
    prop = pipeline.draft_stage(Scripted(), p, 15, 0)
    assert not stage.room_shared(p, room.id, 15, 0, "plan") and prop.grown is not None
    # 받은 뒤 작가가 기준점을 하나 더했다: 같은 id 가 생겨 적용할 때 새 id 로 바꾼다
    taken = prop.adds[0].anchor.id
    p.rooms[0].anchors.append(stage.make_room("bedroom", "x").anchors[0].model_copy(update={"id": taken, "name": "침대"}))
    s = pipeline.apply_stage(p, prop)
    r = p.rooms[0]
    assert {"문", "침대", "운전석", "운전석 창", "정비차 짐칸"} == {a.name for a in r.anchors} and len({a.id for a in r.anchors}) == 5
    seat = _a(r, "운전석")
    assert seat.id != taken and s.start[0].at.ref == seat.id  # 장면 자리도 바뀐 id 로
    assert s.room_prev is not None and s.room_made == ""
    back = pipeline.undo_stage(p, 15, s.id)
    assert back is not None and [a.name for a in p.rooms[0].anchors] == ["문", "침대"]


def test_extract_ignores_anchor_suggestions():
    p = _project()
    p.episode(15).text = "예은이 창을 두드렸다."
    prop = pipeline.draft_stage(Scripted(), p, 15, 0, fresh="empty")
    pipeline.apply_stage(p, prop)
    llm = Scripted()
    text = pipeline.extract_stage(llm, p, 15, 0)
    assert text.adds == [] and text.grown is None and "new_anchors 는 빈 목록" in llm.prompt


def test_board_room_name_for_fresh_room():
    p = _project()
    ep = p.episode(15)
    ep.storyboard = Storyboard(scenes=[BoardScene(place="청운 비행장 후문", spot="캠핑카 운전석과 보닛 앞", events=[1], present=["hero", "char2"])])
    prop = pipeline.draft_stage(Scripted(), p, 15, 0, fresh="empty")
    assert prop.room.name == "캠핑카 운전석과 보닛 앞"


def test_spacing_beside_seated_has_no_3d_overlap():
    """옆 간격 0.55m(stage._person_point)에서 앉기 · 쪼그림 · 무릎 · 눕기 계열 옆 사람의 3D 몸 겹침이 없다 (간격을 넓히지 않은 근거)."""
    from canon.schema import StageAnchor, StageBody, StageScene, StageSpot
    from canon.stage3d import judge as j3
    p = _project()
    room = stage.make_room("empty", "r9")
    room.w = room.h = 8
    room.anchors = [StageAnchor(id="s", name="자리", kind="seat", x=3.65, y=3.65, w=0.7, h=0.7, rot=270, sit=True)]
    bad = []
    for pa in ("chair", "floor", "squat", "kneel", "lie", "side", "prone"):
        for pb in ("stand", "chair", "squat", "kneel", "floor"):
            for rel in ("left", "right", "front", "back"):
                for fa in ("@char2", "e", "s", ""):
                    sc = StageScene(id="x", cast=["hero", "char2"], room="r9", start=[
                        StageBody(who="hero", at=StageSpot(ref="s", rel="on" if pa == "chair" else "front"), posture=pa, facing=fa, left="", right=""),
                        StageBody(who="char2", at=StageSpot(ref="@hero", rel=rel), posture=pb, facing="@hero", left="", right="")])
                    bad += [(pa, pb, rel, fa) for v in j3.judge3d(sc, room, p) if v.rule == "body_overlap"]
    assert bad == []


def test_web_fresh_draft_job_and_apply(client):
    from canon import jobs, store

    p = _project("청운 비행장 후문")
    store.save("ra", p)
    assert client.post("/api/projects/ra/jobs", json={"kind": "stage_draft", "ep": 15, "event": 1, "stage_room": "empty"}).status_code == 200
    for _ in range(200):
        if not any(j.status == "running" for j in jobs.listing("ra")):
            break
        time.sleep(0.02)
    v = client.get("/api/projects/ra/stage/15").json()
    prop = v["proposals"][0]
    assert prop["room"]["template"] == "empty" and [x["anchor"]["name"] for x in prop["adds"]] == ["탁자"] and prop["room_shared"] is False
    assert prop["violations"] == [] and v["vocab"]["kinds"]["table"] == "탁자"
    v = client.post("/api/projects/ra/stage/15/apply", json={"event": 1, "role": "plan"}).json()
    room = next(r for r in v["rooms"] if r["id"] == v["scenes"][0]["scene"]["room"])
    assert {a["name"] for a in room["anchors"]} == {"문", "탁자"} and v["scenes"][0]["scene"]["room_made"] == room["id"]
    v = client.post(f"/api/projects/ra/stage/15/{v['made']}/undo").json()
    assert v["scenes"] == [] and [r["id"] for r in v["rooms"]] == ["r1"]  # 만든 방도 빠지고 공용 방은 그대로
    # 공용 방으로 장면을 만든 뒤 초안: 비교 화면에 공용 방 표시, 바로 더하기를 고르면 공용 방이 바뀐다
    client.post("/api/projects/ra/stage/15", json={"event": 1, "room": "r1"})
    client.post("/api/projects/ra/jobs", json={"kind": "stage_draft", "ep": 15, "event": 1})
    for _ in range(200):
        if not any(j.status == "running" for j in jobs.listing("ra")):
            break
        time.sleep(0.02)
    prop = client.get("/api/projects/ra/stage/15").json()["proposals"][0]
    assert prop["room_shared"] is True and prop["grown"]["id"] == "r1"
    v = client.post("/api/projects/ra/stage/15/apply", json={"event": 1, "role": "plan", "shared": True}).json()
    assert [r["id"] for r in v["rooms"]] == ["r1"] and len(v["rooms"][0]["anchors"]) == 2


def test_seat_and_windows_go_inside_vehicle():
    """15화 실측(2026-10-29): '운전석 near 캠핑카'가 차 밖 곁에, 창 둘이 운전석 앞뒤에 놓였다.
    차에 붙는 자리는 차 안 앞쪽 왼쪽, 그 곁의 창은 차 양 옆면에 붙고 창 앞은 바깥이다. 3D 는 그 차의 운전 칸을 비운다."""
    from canon.schema import StageBody, StageContact, StageScene, StageSpot
    from canon.stage3d import furniture
    p = _project()
    room = stage.make_room("empty", "r1")
    room, adds, _, _ = stage.place_anchors(room, [
        DraftAnchor(name="캠핑카", kind="vehicle", near="문", rel="back"),
        DraftAnchor(name="운전석", kind="seat", near="캠핑카", rel="right"),
        DraftAnchor(name="운전석 창", kind="window", near="운전석", rel="right"),
        DraftAnchor(name="조수석 창", kind="window", near="운전석", rel="left"),
        DraftAnchor(name="정비차", kind="vehicle", near="캠핑카", rel="left")])
    a = {x.name: x for x in room.anchors}
    car, seat, win, win2 = a["캠핑카"], a["운전석"], a["운전석 창"], a["조수석 창"]
    assert [x.where for x in adds][1:4] == ["캠핑카 안", "캠핑카 옆면", "캠핑카 옆면"]
    assert stage.container(seat, room.anchors) is car and stage.container(win, room.anchors) is car
    # 차 앞이 위(rot 180)라 안에서 앞을 보고 왼쪽은 x 가 작은 쪽: 운전석과 운전석 창이 왼쪽 옆면, 조수석 창은 오른쪽 옆면
    assert seat.x + seat.w / 2 < car.x + car.w / 2 and win.x == car.x and win2.x + win2.w == pytest.approx(car.x + car.w)
    assert win.rot == 90 and win2.rot == 270 and seat.rot == car.rot
    # 운전 칸을 비운 차는 자리를 품은 차뿐이다
    assert len(furniture.shape(car, room).boxes) == 5 and furniture.shape(a["정비차"], room) == furniture.KINDS["vehicle"]
    # 운전석에 앉은 건우와 창밖의 예은: 창 너머로 손을 잡아도 2D · 3D 지적이 없다
    sc = StageScene(id="x", cast=["hero", "char2"], room=room.id, start=[
        StageBody(who="hero", at=StageSpot(ref=seat.id, rel="on"), posture="chair", facing="@char2", left="", right=""),
        StageBody(who="char2", at=StageSpot(ref=win.id, rel="front"), posture="stand", facing="@hero", left="", right="", contacts=[
            StageContact(id="c1", by="right", to="hero", part="hand_l", act="hold")])])
    assert stage.judge_all(sc, room, p) == []
