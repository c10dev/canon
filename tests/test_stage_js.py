"""장면 연출 화면(static/stage.js)이 서버 stage.place · state_at · is_sexual 과 같은 값을 내는지, 화면이 그려지는지.
node 가 있을 때만 돈다."""
import re

import pytest

from canon import stage
from canon.schema import Character, Meta, Project, StageBeat, StageBody, StageContact, StageScene, StageSpot

from .jsvm import STATIC, dump, episode, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def _scenes(room):
    a = {x.name: x.id for x in room.anchors}
    sp = lambda ref, rel: StageSpot(ref=ref, rel=rel)  # noqa: E731
    one = StageScene(id="s1", cast=["h", "d", "m", "x"], start=[
        StageBody(who="h", at=sp(a["침대"], "on"), facing="#" + a["책상"]),
        StageBody(who="d", at=sp(a["침대"], "on"), facing="@h"),
        StageBody(who="m", at=sp(a["침대"], "on")),
        StageBody(who="x", at=sp("@h", "left")),
    ], beats=[
        StageBeat(bodies=[StageBody(who="h", at=sp(a["문"], "front"), facing="ne")]),
        StageBeat(bodies=[StageBody(who="d", at=sp("@x", "back")), StageBody(who="m", at=sp(a["책상"], "left"), facing="sw")]),
        StageBeat(bodies=[StageBody(who="x", at=sp(a["의자"], "beside")), StageBody(who="h", at=sp("@m", "right"))]),
        StageBeat(bodies=[StageBody(who="d", at=sp("@h", "across")), StageBody(who="m", at=sp(a["문"], "against")),
                          StageBody(who="x", at=sp(a["책상"], "across"))]),
        StageBeat(bodies=[StageBody(who="h", at=sp("@d", "against"))]),
        # 기준 인물(d)이 나(h)를 향하는데 내 자리를 아직 모른다: 앞 박자의 내 자리 쪽이 d 의 앞
        StageBeat(bodies=[StageBody(who="d", at=sp(a["침대"], "right"), facing="@h"), StageBody(who="h", at=sp("@d", "front"))]),
    ])
    loop = StageScene(id="s2", cast=["p", "q"], start=[StageBody(who="p", at=sp("@q", "front")), StageBody(who="q", at=sp("@p", "back"))])
    return [one, loop]


@needs_node
@pytest.mark.parametrize("template", ["bedroom", "living", "classroom", "car"])
def test_layout_matches_server(template):
    room = stage.make_room(template, "r")
    if template != "bedroom":  # 침실 이름을 쓰는 장면이라 다른 틀에는 같은 이름 기준점을 붙인다
        for name, kind in (("침대", "bed"), ("책상", "desk"), ("문", "door"), ("의자", "chair")):
            if all(x.name != name for x in room.anchors):
                room.anchors.append(stage.make_room("bedroom", "b").anchors[[x.name for x in stage.make_room("bedroom", "b").anchors].index(name)])
                room.anchors[-1].id = f"x{len(room.anchors)}"
    scenes = _scenes(room)
    want = [[{w: list(xy) for w, xy in pos.items()} for pos in stage.layouts(room, s)] for s in scenes]
    got = run_js(FILES, """data.scenes.map((s) => stageLayouts(data.room, s))""",
                 {"room": dump(room), "scenes": [dump(s) for s in scenes]})
    for gs, ws in zip(got, want):
        for g, w in zip(gs, ws):
            assert set(g) == set(w)
            for who in w:
                assert g[who] == pytest.approx(w[who], abs=1e-9), who


@needs_node
def test_snap_and_sexual_match_server():
    room = stage.make_room("bedroom", "r")
    bed = next(a for a in room.anchors if a.name == "침대")
    x, y = stage._anchor_point(bed, "right")
    combos = [[p, a] for p in stage.PARTS for a in stage.ACTS]
    got = run_js(FILES, """({ snap: stageSnap(data.room, data.x + 0.05, data.y - 0.05), none: stageSnap({ anchors: [] }, 1, 1),
      sexual: data.combos.map(([part, act]) => stageSexual({ part, act }, data.vocab)) })""",
                 {"room": dump(room), "x": x, "y": y, "combos": combos, "vocab": stage.vocab()})
    assert got["snap"] == {"ref": bed.id, "rel": "right"} and got["none"] is None
    assert got["sexual"] == [stage.is_sexual(StageContact(id="c", by="right", to="h", part=p, act=a)) for p, a in combos]


@needs_node
def test_views_render():
    p = Project(meta=Meta(title="t", target_episodes=2), characters=[
        Character(id="h", name="하린", role="주인공", age="16"), Character(id="d", name="도윤", role="조연", age="29")],
        episodes=[episode(1, plot={"title": "첫 화", "events": ["도윤이 찾아온다", "하린이 붙잡는다"], "characters": ["h", "d"]})])
    e = p.episodes[0]
    room = stage.new_room(p, "bedroom", "하린의 방")
    scene = stage.new_scene(p, e, 1, room)
    scene.beats = [StageBeat(quote="도윤이 손목을 잡았다.", bodies=[StageBody(who="d", contacts=[StageContact(id="c1", by="right", to="h", part="wrist_l", act="hold")])])]
    view = stage.view(p, 1)
    got = run_js(FILES, """(() => {
      S.project = data.p; S.name = 't'; S.route = ['p', 't', 'stage', '1', '2'];
      S.stg = { n: 1, ev: 2, view: data.view, sid: null, scene: null, room: null, dirty: false, beat: 1, who: '', mode: 'people', check: null,
        form: { by: 'right', to: '', part: '', act: 'hold' }, pick: { room: '', template: 'bedroom', name: '' }, playing: null };
      stgPick();
      const main = viewStage(1);
      const plan = stgPlanSvg(stgTarget(1).pos, stgTarget(1).ang, 1);
      const flag = (contact) => { S.stg.check = { ...S.stg.check, violations: [{ beat: 1, cause: 1, who: 'd', rule: 'reach', text: '', contact }] };
        return stgPlanSvg(stgTarget(1).pos, stgTarget(1).ang, 1); };
      const other = flag('c9'), own = flag('c1');
      S.stg.check = { ...S.stg.check, violations: [] };
      S.stg.who = 'h';
      const minorCard = stgPersonCard();
      S.stg.mode = 'room';
      const room = viewStage(1);
      S.stg.ev = 1; stgPick();
      const fresh = viewStage(1);
      const nav = navItems().tools.find((x) => x[0] === 'stage');
      return { main, plan, other, own, minorCard, room, fresh, nav, plot: eventsField(ep(1), 'episodes.0.plot', false) };
    })()""", {"p": dump(p), "view": view})
    assert "장면 연출" in got["main"] and "도윤이 손목을 잡았다." in got["main"] and "규칙 검수" not in got["main"]  # 문 앞에 0.5m 간격으로 서서 닿는다
    assert 'data-stg-who="d"' in got["plan"] and "stg-contact" in got["plan"]
    # 지적이 있는 접촉 선만 빨갛다: 사람은 지적이 있으면 빨갛고, 선은 지적의 접촉 id 가 같아야 빨갛다
    assert "stg-contact bad" not in got["other"] and "stg-person bad" in got["other"] and "stg-contact bad" in got["own"]
    part_sel = re.search(r'data-stg-form="part">(.*?)</select>', got["minorCard"]).group(1)
    assert "미성년 인물이 있어" in got["minorCard"] and "애무하다" not in got["minorCard"] and "가슴" not in part_sel and "왼 손목" in part_sel
    assert "방 고치기" in got["room"] and "data-stg-anchor-name" in got["room"]
    assert "아직 연출이 없어요" in got["fresh"] and "하린의 방" in got["fresh"]
    assert got["nav"][3] == "장면 연출" and got["nav"][4] is True
    assert "/stage/1/2" in got["plot"] and "/stage/1/1" in got["plot"]
