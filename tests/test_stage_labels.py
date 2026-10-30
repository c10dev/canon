"""장면 연출 이름표 겹침 (static/stage.js stageLabelPlace, docs/stage/specs/11-labels.md). node 가 있을 때만 돈다."""
import re

from .jsvm import STATIC, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def _overlap(a, b):
    return a["cx"] - a["w"] / 2 < b["cx"] + b["w"] / 2 and b["cx"] - b["w"] / 2 < a["cx"] + a["w"] / 2 \
        and a["cy"] - a["h"] / 2 < b["cy"] + b["h"] / 2 and b["cy"] - b["h"] / 2 < a["cy"] + a["h"] / 2


def _place(items, **opts):
    return run_js(FILES, "stageLabelPlace(data.items, data.opts)", {"items": items, "opts": opts})


def _person(i, x, y, text="하린 · 의자에 앉기", short="하린"):
    return {"id": f"p:{i}", "x": x, "y": y, "text": text, "short": short, "fs": 12, "kind": "ring", "r": 18}


@needs_node
def test_close_people_do_not_overlap_and_first_keeps_below():
    items = [_person("h", 200, 200), _person("d", 230, 200, "도윤 · 걷기", "도윤"), _person("m", 215, 170, "미아 · 서기", "미아")]
    taken = [[p["x"] - 18, p["y"] - 18, p["x"] + 18, p["y"] + 18] for p in items]
    got = _place(items, taken=taken, bounds=[0, 0, 500, 400])
    boxes = list(got.values())
    assert all(not _overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])
    # 이름표는 인물 원을 덮지 않는다
    for t in boxes:
        for x0, y0, x1, y1 in taken:
            assert not (t["cx"] - t["w"] / 2 < x1 and x0 < t["cx"] + t["w"] / 2 and t["cy"] - t["h"] / 2 < y1 and y0 < t["cy"] + t["h"] / 2)
    first = got["p:h"]
    assert first["cx"] == 200 and first["cy"] > 200 and not first["leader"]  # 비어 있으면 아래 첫 자리


@needs_node
def test_previous_spot_wins_while_free():
    items = [_person("h", 200, 200)]
    got = run_js(FILES, """(() => {
      const prev = { 'p:h': { k: 1, short: false } };
      const a = stageLabelPlace(data.items, { bounds: [0, 0, 500, 400], prev });
      return [a['p:h'], prev['p:h']];
    })()""", {"items": items})
    assert got[0]["cy"] < 200  # 앞 프레임의 위 자리를 지킨다
    assert got[1] == {"k": 1, "short": False}


@needs_node
def test_short_text_then_hidden_pin():
    # 좁은 띠: 긴 글은 들어가지 않고 이름만 들어간다. 기준점 이름은 자리가 없으면 숨는다
    person = _person("h", 100, 30, "하린 · 아주 긴 자세 이름으로 앉기", "하린")
    pin = {"id": "a:bed", "x": 100, "y": 30, "text": "침대", "fs": 12, "kind": "pin"}
    got = _place([person, pin], taken=[[82, 12, 118, 48]], bounds=[60, 0, 140, 80])
    assert got["p:h"]["text"] == "하린" and not got["p:h"]["hidden"]
    assert got["a:bed"]["hidden"]


@needs_node
def test_far_spot_draws_leader():
    # 가까운 여덟 자리를 모두 막으면 먼 고리에 놓고 지시선을 긋는다
    p = _person("h", 250, 200, "하린", "하린")
    taken = [[150, 150, 350, 250]]
    got = _place([p], taken=taken, bounds=[0, 0, 500, 400])
    assert got["p:h"]["leader"] and not _overlap(got["p:h"], {"cx": 250, "cy": 200, "w": 200, "h": 100})


@needs_node
def test_plan_svg_labels_do_not_overlap():
    # 평면도: 한 자리에 선 세 사람 + 기준점 이름이 서로 겹치지 않는다 (글자 폭 어림으로 잰 상자)
    from canon import stage
    from canon.schema import Character, Meta, Project, StageBody, StageScene, StageSpot

    from .jsvm import dump
    room = stage.make_room("bedroom", "r1", "방")
    bed = next(a.id for a in room.anchors if a.name == "침대")
    p = Project(meta=Meta(title="t"), characters=[Character(id=w, name=n, role="조연", age="30") for w, n in (("h", "하린"), ("d", "도윤"), ("m", "미아"))])
    sc = StageScene(id="s1", room="r1", cast=["h", "d", "m"], start=[
        StageBody(who=w, at=StageSpot(ref=bed, rel="front"), posture="stand") for w in ("h", "d", "m")])
    got = run_js(FILES, """(() => {
      S.project = data.p; S.stg = { scene: data.sc, room: data.room, beat: 0, mode: 'people', role: 'plan', who: 'h', check: null, view: { vocab: data.vocab } };
      const t = stgTarget(0), svg = stgPlanSvg(t.pos, t.ang, 0);
      return [...svg.matchAll(/<text(?: class="label")? x="([\\d.]+)" y="([\\d.]+)" text-anchor="middle">([^<]+)<\\/text>/g)].map((m) => [+m[1], +m[2], m[3]]);
    })()""", {"p": dump(p), "sc": dump(sc), "room": dump(room), "vocab": stage.vocab()})
    assert len([g for g in got if "·" in g[2] or g[2] in ("하린", "도윤", "미아")]) == 3
    boxes = [{"cx": x, "cy": y - 4, "w": sum(12 if ord(c) > 0x2E80 else 7.2 for c in t), "h": 15} for x, y, t in got]
    assert all(not _overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])
