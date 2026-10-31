"""지도 화면 한 번에 필요한 계산값(summary)과 명령줄 출력(describe). 장소 · 길 · 지도 데이터 · 지도 만들기를 모은다. LLM 을 부르지 않는다."""
from __future__ import annotations

from typing import Optional

from ..schema import Project
from . import kinds as placekinds
from .buildings import building_counts
from .gen import citygen, moderngen
from .layout import layout_info
from .makers import map_era, village_title
from .places import frames, place_kinds, places, unmatched
from .routes import add_routes, road_graph


def summary(p: Project, layout: Optional[dict] = None) -> dict:
    """지도 화면 한 번에 필요한 계산값. layout(read_layout 결과)을 주면 옮겨 간 인물에 길 따라 걸은 경로를 붙인다.
    이동 시간 검사 칸(travel.view)은 web.atlas_view 가 places · frames 로 붙인다 (atlas 는 travel 을 가져오지 않는다)."""
    pls = places(p)
    pins = {pin.place: [pin.x, pin.y] for pin in p.atlas.pins}
    spots = {pin.place: pin.spot for pin in p.atlas.pins}
    kinds = place_kinds(p, map_era(p, layout), pls)
    for pl in pls:
        pl["pin"] = pins.get(pl["key"])
        pl["spot"] = spots.get(pl["key"], "")  # 놓인 건물 한 줄 (MapPin.spot)
        pl["kind"] = kinds[pl["key"]]  # 지금 지도 시대의 종류 (핀 기호 static/atlas-icons.js)
        pl["kind_label"] = placekinds.label(pl["kind"])
    fs = frames(p, pls)
    if layout:
        add_routes(fs, pins, road_graph(layout), p.atlas.meters)
        if not p.atlas.layout_size:  # 이 칸이 생기기 전에 올린 마을 데이터 (저장은 다음에 지도를 고칠 때)
            p.atlas.layout_size = [layout["w"], layout["h"]]
    aspect = round(layout["w"] / layout["h"], 4) if layout else p.atlas.aspect  # 마을 데이터가 있으면 마을을 그린다
    return {"places": pls, "frames": fs, "unmatched": unmatched(p, fs), "image": p.atlas.image,
            "aspect": aspect, "links": [ln.model_dump() for ln in p.atlas.links],
            "layout": layout_info(p, layout) if layout else None, "title": village_title(p, layout) if layout else None}


# ---------- 명령줄 ----------

def describe(p: Project, layout: Optional[dict] = None) -> str:
    """명령줄 `map <작품>`: 장소(지도에 놓았는지), 인물별 옮겨 다닌 길, 장소와 맞지 않은 위치 글.
    마을 데이터를 주면 옮긴 화마다 길 따라 걸은 거리 · 시간도."""
    s = summary(p, layout)
    pls = {pl["key"]: pl for pl in s["places"]}
    if not pls:
        return "장소가 아직 없어요. 설정의 장소 칸이나 인과율 '장소'에 더하면 지도에 놓을 수 있어요."
    lines = []
    if s["layout"]:
        lo = s["layout"]
        made = f" (지도 만들기, 시드 {p.atlas.spec.seed})" if p.atlas.spec else ""
        what = {citygen.GENERATOR: "도시", moderngen.GENERATOR: "현대 동네"}.get(lo["generator"], "마을")
        lines.append(f"{what} 데이터{made}: 길 {lo['roads']}개 · 다리 {lo['bridges']}개 · 건물 {lo['buildings']}채 · "
                     f"약 {lo['width_m']}×{lo['height_m']}m")
        uses = building_counts(p, layout)
        if uses:
            lines.append("건물 쓰임: " + " · ".join(f"{label} {n}" for label, n in uses[:12]) + (" 등" if len(uses) > 12 else ""))
        lines.append("")
    lines.append("장소")
    for pl in s["places"]:
        when = f" · {pl['known_from']}화부터 독자가 앎" if pl["known_from"] else ""
        lines.append(f"  {pl['name']} ({pl['source']}){when}{'' if pl['pin'] else ' · 지도에 아직 안 놓음'}")
    name = {c.id: c.name or c.id for c in p.characters}
    walks: dict[str, list[str]] = {}
    lastat: dict[str, str] = {}
    for f in s["frames"]:
        for r in f["rows"]:
            path = walks.setdefault(r["cid"], [])
            here = pls[r["place"]]["name"] if r["place"] else (f"'{r['location']}'" if r["location"] else "")
            if here and here != lastat.get(r["cid"]):
                lastat[r["cid"]] = here
                walk = f" (길 따라 {r['route']['meters']}m · 약 {r['route']['minutes']}분)" if r.get("route") else ""
                path.append(f"{f['episode'] or '시작'}{'화' if f['episode'] else ''} {here}{walk}")
    if walks:
        lines.append("\n인물이 있던 곳 (반영한 화 기준, 바뀐 화만)")
        for cid, path in walks.items():
            if path:
                lines.append(f"  {name.get(cid, cid)}: " + " → ".join(path))
    if s["unmatched"]:
        lines.append("\n장소와 맞지 않은 위치 글 (웹 지도 화면에서 장소에 이을 수 있어요)")
        for u in s["unmatched"]:
            lines.append(f"  '{u['text']}' · {', '.join(name.get(c, c) for c in u['characters'])} · {', '.join(f'{n}화' if n else '시작' for n in u['episodes'])}")
    return "\n".join(lines)
