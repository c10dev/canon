"""장면 연출 3D 보기(static/stage3d.js): three.js 없이도 읽히는지, 순수 함수(s3Frame · s3Mix · s3Pull · s3Flags · s3Cams),
평면도 칸 머리의 '평면도 | 3D' 전환이 그려지는지. 관절 좌표는 가짜 등록부로 서버 stage3d.frames 가 낸 값을 쓴다. node 가 있을 때만 돈다."""
import pytest

from canon import stage, stage3d
from canon.schema import Character, Meta, Project, StageBeat, StageBody, StageContact, StageSpot
from canon.stage3d import fake

from .jsvm import dump, episode, needs_node, run_js
from .test_stage_js import FILES

FILES3 = FILES + ["stage3d-load.js", "stage3d.js"]


def _project(act="hold"):
    p = Project(meta=Meta(title="t", target_episodes=1), characters=[
        Character(id="h", name="하린", role="주인공", age="27"), Character(id="d", name="도윤", role="조연", age="29")],
        episodes=[episode(1, plot={"title": "첫 화", "events": ["만난다"], "characters": ["h", "d"]})])
    room = stage.new_room(p, "bedroom", "하린의 방")
    scene = stage.new_scene(p, p.episodes[0], 0, room)
    scene.beats = [StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref="@h", rel="across"), facing="@h", contacts=[
        StageContact(id="c1", by="both" if act in ("hug", "embrace") else "right", to="h",
                     part="back" if act in ("hug", "embrace") else "wrist_l", act=act)])])]
    return p, room, scene


def _frames(scene, room):
    return stage3d.frames(scene, room, postures=fake.POSTURES, rooms=fake.ROOMS).to_dict()


@needs_node
def test_loads_without_three_and_toggle():
    p, room, scene = _project()
    view = stage.view(p, 1)
    got = run_js(FILES3, """(() => {
      S.project = data.p; S.name = 't'; S.route = ['p', 't', 'stage', '1', '1'];
      S.stg = { n: 1, ev: 1, view: data.view, sid: null, scene: null, room: null, dirty: false, beat: 1, who: '', mode: 'people', check: null,
        form: { by: 'right', to: '', part: '', act: 'hold' }, pick: { room: '', template: 'bedroom', name: '' }, playing: null };
      stgPick();
      const plan = viewStage(1);
      S.stgView = '3d';
      const three = viewStage(1);
      return { plan, three, act: typeof actions.stgView, load: typeof load3d, mount: typeof s3Mount };
    })()""", {"p": dump(p), "view": view})
    assert 'data-action="stgView" data-arg="3d"' in got["plan"] and 'aria-pressed="true" data-action="stgView" data-arg="plan"' in got["plan"]
    assert 'id="stg-plan"' in got["plan"] and 'id="stg-3d"' not in got["plan"]
    assert 'id="stg-3d"' in got["three"] and 'id="stg-plan"' not in got["three"]
    assert "비스듬히" in got["three"] and "문에서" in got["three"] and 'aria-live="polite"' in got["three"]
    assert got["act"] == "function" and got["load"] == "function" and got["mount"] == "function"


@needs_node
def test_frame_mix_flags():
    p, room, scene = _project()
    fr = _frames(scene, room)
    got = run_js(FILES3, """(() => {
      const [a, b] = data.fr.beats;
      const caps = s3Frame(b.bodies.d.joints);
      const head = caps.find((c) => c.seg === 'head');
      const mid = s3Mix(a, b, 0.5);
      return {
        n: caps.length, segs: caps.map((c) => c.seg), head: [head.a, head.b, head.r], none: s3Frame(null).length,
        start: s3Mix(a, b, 0).bodies.d.joints, end: s3Mix(a, b, 1).bodies.d.joints, mid: mid.bodies.d.joints.pelvis,
        midPts: mid.contacts.map((c) => c.points.length),
        flagWho: s3Flags([{ beat: 1, who: 'd', rule: 'reach' }, { beat: 2, who: 'h', rule: 'reach' }], 1, b.contacts),
        flagOne: s3Flags([{ beat: 1, who: 'd', rule: 'reach', contact: 'c9' }], 1, b.contacts),
        flagNone: s3Flags([], 1, b.contacts),
        cams: s3Cams(data.room),
      };
    })()""", {"fr": fr, "room": dump(room)})
    assert got["n"] == 17 and "torso" in got["segs"] and "foot_r" in got["segs"] and got["none"] == 0
    assert got["head"][0] == got["head"][1] and got["head"][2] == pytest.approx(0.11)
    a, b = fr["beats"]
    assert got["start"] == a["bodies"]["d"]["joints"] and got["end"] == b["bodies"]["d"]["joints"]
    pa, pb = a["bodies"]["d"]["joints"]["pelvis"], b["bodies"]["d"]["joints"]["pelvis"]
    assert got["mid"] == pytest.approx([(x + y) / 2 for x, y in zip(pa, pb)])
    assert got["midPts"] == [len(c["points"]) for c in b["contacts"]]
    assert got["flagWho"] == {"who": ["d"], "contacts": ["c1"]}
    assert got["flagOne"] == {"who": ["d"], "contacts": ["c9"]}  # contact 가 있으면 그 선만
    assert got["flagNone"] == {"who": [], "contacts": []}
    # 카메라는 three.js 좌표 (x, 높이, 평면 y): 위에서는 방 가운데 위
    top = got["cams"]["top"]
    assert top["at"] == pytest.approx([room.w / 2, 0, room.h / 2]) and top["pos"][1] > 3
    door = next(x for x in room.anchors if x.kind == "door")
    assert got["cams"]["door"]["pos"][1] == pytest.approx(1.6)
    assert abs(got["cams"]["door"]["pos"][0] - (door.x + door.w / 2)) <= 0.6 + 1e-9


@needs_node
@pytest.mark.parametrize("act,close", [("hug", 0.34), ("embrace", 0.3), ("hold", None)])
def test_pull_only_hugs(act, close):
    p, room, scene = _project(act)
    fr = _frames(scene, room)
    # 서버 배치는 두 사람을 이미 가깝게 둔다. 그림 붙이기를 보려고 안긴 사람을 1m 옆으로 뗀다 (목표 점도 함께)
    b1 = fr["beats"][1]
    b1["bodies"]["h"]["joints"] = {j: [v[0] + 1.0, v[1], v[2]] for j, v in b1["bodies"]["h"]["joints"].items()}
    for c in b1["contacts"]:
        c["points"] = [[v[0] + (1.0 if i % 2 else 0.0), v[1], v[2]] for i, v in enumerate(c["points"])]
    got = run_js(FILES3, """(() => {
      const b = data.fr.beats[1];
      const r = s3Pull(b, { c1: data.act });
      const j = r.beat.bodies;
      const c = r.beat.contacts[0];
      return { pulled: r.pulled, d: j.d.joints.pelvis, h: j.h.joints.pelvis, hand: c.hands.map((s) => j[c.who].joints['hand_' + s]),
               pts: c.points, same: r.beat === b, orig: b.bodies.d.joints.pelvis };
    })()""", {"fr": fr, "act": act})
    if close is None:
        assert not got["pulled"] and got["same"]
        return
    d, h = got["d"], got["h"]
    orig = fr["beats"][1]["bodies"]
    assert got["pulled"] and orig["d"]["joints"]["pelvis"] == got["orig"]  # 서버 값은 바꾸지 않는다
    assert ((d[0] - h[0]) ** 2 + (d[1] - h[1]) ** 2) ** 0.5 == pytest.approx(close)
    assert d[2] == orig["d"]["joints"]["pelvis"][2]  # 높이는 그대로
    # 감는 손은 안긴 사람과 함께 옮겨 손끝 → 목표 틈이 같다
    raw = b1["contacts"][0]["points"]
    for i in range(0, len(raw), 2):
        before = [raw[i + 1][k] - raw[i][k] for k in range(3)]
        after = [got["pts"][i + 1][k] - got["pts"][i][k] for k in range(3)]
        assert after == pytest.approx(before, abs=1e-9)
