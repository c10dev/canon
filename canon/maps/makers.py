"""지도 만들기: 생성기 등록(MAKERS: 마을 gen.towngen · 도시 gen.citygen · 현대 동네 gen.moderngen), 장소 표(gen_places),
미리보기(generate) · 적용(apply_generated), 지도 시대(map_era), 마을 이름 · 인구(village_title), 빈 블록 채우기(fill) 미리보기 · 적용 · 지우기.
LLM 을 부르지 않는다."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .. import naming
from ..schema import MapFill, MapPin, MapSpec, Project
from . import buildings as bldgs
from . import fill, geom
from . import kinds as placekinds
from .gen import citygen, moderngen, towngen
from .layout import enrich
from .places import places, set_pins
from .sources import osm
from .spots import fill_spots


def map_era(p: Project, layout: Optional[dict] = None) -> str:
    """지금 지도의 장소 종류 시대 (placekinds.ERAS). 지도 데이터가 OpenStreetMap · 현대 동네면 modern, 다른 지도 데이터면 old.
    지도 데이터가 없으면(배경 그림 · 모눈) 지도 만들기 입력의 시대, 그것도 없으면 작품 이름 스타일이 현대일 때 modern."""
    if layout:
        return "modern" if layout.get("generator") in (osm.GENERATOR, moderngen.GENERATOR) else "old"
    if p.atlas.spec:
        return placekinds.era_of(p.atlas.spec.kind)
    return "modern" if naming.resolve_style(p) in MODERN_STYLES else "old"


# ---------- 마을 이름 · 인구 ----------

POP_PER_HOUSE = 5.5  # 집 한 채에 사는 사람 (어림. Watabou 마을의 인구 표시와 비슷한 규모)
CITY_POP_PER_HOUSE = 8.0  # 도시 집은 층이 높고 세 든 사람이 많다 (어림)


def village_title(p: Project, layout: dict) -> dict:
    """지도 위 제목: 작가가 정한 이름, 없으면 '마을 가운데'(현대 동네는 '역') 종류 장소 이름. 인구는 집 수 × 집 한 채에 사는 사람을 10 단위로
    (도시 생성기가 만든 지도는 CITY_POP_PER_HOUSE). kind: 이름 칸에 쓸 말 (마을 · 도시 · 동네), unit: 수를 세는 말 (집 · 건물).
    OpenStreetMap 지도와 현대 동네 생성기 지도는 건물을 세고, 인구는 주거 건물에서 어림한 사람 수만 쓴다 (canon/maps/buildings.py)."""
    name = p.atlas.title
    if not name:
        era = placekinds.era_of(p.atlas.spec.kind if p.atlas.spec else "village")
        center = {"center", placekinds.to_era("center", era)}  # 현대 동네는 역
        name = next((x["name"] for x in gen_places(p, p.atlas.spec) if x["kind"] in center and x["put"]), "")
    houses = layout.get("houses") or len(layout.get("numbers") or layout.get("buildings") or [])
    city = layout.get("generator") == citygen.GENERATOR
    real = layout.get("generator") in (osm.GENERATOR, moderngen.GENERATOR)
    per = CITY_POP_PER_HOUSE if city else POP_PER_HOUSE
    people = sum(b.get("people", 0) for b in layout.get("blds") or [])  # 건물마다 센 사람이 있으면 그 합
    return {"title": name, "custom": bool(p.atlas.title), "houses": houses, "population": int(round(people if real else people or houses * per, -1)),
            "kind": "도시" if city else "동네" if real else "마을", "unit": "건물" if real else "집"}


def set_title(p: Project, title: str) -> None:
    t = " ".join(title.split())
    if len(t) > 40:
        raise ValueError("지도 이름은 40자까지 적을 수 있어요")
    p.atlas.title = t


# ---------- 지도 만들기 (마을 생성기 gen/towngen.py, 도시 생성기 gen/citygen.py, 현대 동네 생성기 gen/moderngen.py) ----------

MODERN_STYLES = ("korea_modern", "japan", "sf")  # 건물 고치기 칸에 현대 쓰임을 보이는 이름 스타일
MAKERS = {"village": ("마을", towngen, towngen.village), "city": ("도시", citygen, citygen.city),
          "modern": ("현대 동네", moderngen, moderngen.neighborhood)}
# MapSpec.kind → (화면 이름, 생성기 모듈(OPTIONS · VERSION · ZONES), 만드는 함수). 왕국은 다음 단계


def _maker(kind: str):
    if kind not in MAKERS:
        raise ValueError(f"아직 만들 수 없는 지도예요: {kind}. 마을 · 도시 · 현대 동네 가운데 고르세요")
    return MAKERS[kind]


def gen_places(p: Project, spec: Optional[MapSpec] = None) -> list[dict]:
    """지도 만들기의 장소 표. 장소마다 종류(작가가 고친 값, 없으면 이름 · 설명에서 찾은 값)와 이 지도에 놓을지.
    종류는 지도 종류(spec.kind, 없으면 마을)의 시대 id 다: 저장된 값은 placekinds.to_era 로 옮기고, 대응이 없으면 찾은 값.
    found_in: 시대마다 이름 · 설명에서 찾은 종류 (화면이 지도 종류를 바꿀 때 쓴다)."""
    era = placekinds.era_of(spec.kind if spec else "village")
    mine = {x.key: x for x in (spec.places if spec else [])}
    out = []
    for pl in places(p):
        found_in = {e: placekinds.classify(pl["name"], pl["description"], e) for e in placekinds.ERAS}
        found, word = found_in[era]
        m = mine.get(pl["key"])
        kind = (placekinds.to_era(m.kind, era) if m else "") or found
        put = m.put if m and m.put is not None else placekinds.default_put(kind)
        out.append({"key": pl["key"], "name": pl["name"], "kind": kind, "found": found, "word": word, "put": put,
                    "found_in": {e: k for e, (k, _) in found_in.items()}})
    return out


def default_spec(p: Project) -> MapSpec:
    """지도 만들기 입력. 만든 적이 있으면 그 입력, 없으면 기본값에 물만 장소를 보고 정한다 (등대 · 어시장이면 바다)."""
    if p.atlas.spec:
        return p.atlas.spec
    return MapSpec(water=placekinds.water_for(gen_places(p)))


def gen_info(p: Project) -> dict:
    """지도 화면의 '지도 만들기' 칸: 지금 입력(만든 적 없으면 기본값), 장소 표, 종류 이름.
    maps: 만들 수 있는 지도 [{id, label}], options · version: 지도 종류(MapSpec.kind)마다 설정 칸과 생성기 버전,
    kinds: 지도 종류마다 고를 수 있는 장소 종류 [{id, label}] (placekinds.kinds_for), eras: 지도 종류 → 시대,
    kind_to: 시대마다 모든 종류 id → 그 시대 id (placekinds.to_era, 대응이 없으면 ''),
    wards: 도시 구역 · 현대 동네 슈퍼블록 종류 이름 (지도에 구역 이름을 쓴다), uses: 건물 쓰임 id → [작품 스타일에 맞는 이름, 묶음],
    modern: 현대 쓰임 id (건물 고치기 칸은 실제 지도 · 현대 동네 지도이거나 modern_style 일 때만 보인다), modern_style: 작품 이름 스타일이 현대인가."""
    spec = default_spec(p)
    style = naming.resolve_style(p)
    return {"spec": spec.model_dump(), "made": p.atlas.spec is not None, "places": gen_places(p, spec),
            "maps": [{"id": k, "label": m[0]} for k, m in MAKERS.items()],
            "options": {k: m[1].OPTIONS for k, m in MAKERS.items()},
            "kinds": {k: [{"id": x.id, "label": x.label} for x in placekinds.kinds_for(k)] for k in MAKERS},
            "eras": {k: placekinds.era_of(k) for k in MAKERS},
            "kind_to": {e: {x.id: placekinds.to_era(x.id, e) for x in placekinds.KINDS} for e in placekinds.ERAS},
            "version": {k: m[1].VERSION for k, m in MAKERS.items()}, "wards": {k: v for m in MAKERS.values() for k, v in m[1].ZONES.items()},
            "uses": {u: [bldgs.label(u, style), grp] for u, (_, grp) in bldgs.USES.items()},
            "modern": list(bldgs.MODERN), "modern_style": style in MODERN_STYLES}


def _blocked(lo: dict, xy: tuple[float, float]) -> bool:
    """0~1 자리가 새 마을의 건물 · 물 위인가 (옛 핀이 어색해지는 곳). 바다 속 섬(land)은 물이 아니다."""
    has = lambda key: any(geom.inside(xy, [tuple(q) for q in poly]) for poly in lo.get(key, []))  # noqa: E731
    if has("buildings") or (has("water") and not has("land")):
        return True
    q = (xy[0] * lo["w"], xy[1] * lo["h"])
    return any(geom.seg_dist(q, (a[0] * lo["w"], a[1] * lo["h"]), (b[0] * lo["w"], b[1] * lo["h"])) <= rv["width"] / 2
               for rv in lo.get("rivers", []) for a, b in zip(rv["points"], rv["points"][1:]))


def generate(p: Project, spec: MapSpec) -> dict:
    """미리보기 (저장하지 않음). spec.kind 로 마을 · 도시 · 현대 동네 생성기를 고른다.
    layout: read_layout 과 같은 모양의 지도, pins: 생성기가 고른 장소 자리
    (had: 이미 지도에 놓은 장소), missing: 놓지 못한 장소와 까닭, blocked: 새 마을에서 건물 · 물 위에 놓이는 옛 자리."""
    put = [x for x in gen_places(p, spec) if x["put"]]
    lo = enrich(p, _maker(spec.kind)[2](spec, put), spec.seed)
    pins = {pin.place: (pin.x, pin.y) for pin in p.atlas.pins}
    spots = {s["key"] for s in lo["spots"]}
    names = {pl["key"]: pl["name"] for pl in places(p)}
    return {"layout": lo,
            "pins": [{"place": s["key"], "name": s["name"], "kind": s["kind"], "x": s["x"], "y": s["y"], "had": s["key"] in pins}
                     for s in lo["spots"]],
            "missing": lo["missing"],
            "blocked": [{"place": k, "name": names.get(k, k)} for k, xy in pins.items() if k not in spots and _blocked(lo, xy)],
            "title": village_title(p, lo),
            "info": {"houses": lo["houses"], "buildings": len(lo["buildings"]), "roads": sum(r["kind"] == "road" for r in lo["roads"]),
                     "bridges": sum(r["kind"] == "bridge" for r in lo["roads"]), "width_m": round(lo["w"]), "height_m": round(lo["h"]),
                     "wards": len(lo.get("wards", [])), "gates": len(lo.get("gates", []))}}


def apply_generated(folder: Path, p: Project, spec: MapSpec, take: list[str]) -> str:
    """미리 본 마을을 적용한다: 같은 입력으로 다시 만들어 map/ 에 저장하고, 입력 · 축척(1단위 = 1m)을 적고,
    take 에 든 장소만 생성기가 고른 자리로 놓는다 (나머지 핀은 그대로). 돌려주는 것: 저장 뒤 지울 옛 파일 이름."""
    out = generate(p, spec)
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"gen-{spec.kind}-{spec.seed}.json"
    (folder / fname).write_text(json.dumps(out["layout"], ensure_ascii=False), encoding="utf-8")
    old = p.atlas.layout
    if old != fname:
        p.atlas.buildings = []  # 건물 번호가 바뀌므로 고친 건물도 비운다
    p.atlas.layout, p.atlas.meters, p.atlas.fill = fname, 1.0, None
    p.atlas.layout_size = [out["layout"]["w"], out["layout"]["h"]]
    p.atlas.spec = spec.model_copy(update={"version": _maker(spec.kind)[1].VERSION})
    chosen = set(take)
    keep = [pin for pin in p.atlas.pins if pin.place not in chosen]
    set_pins(p, keep + [MapPin(place=s["place"], x=s["x"], y=s["y"]) for s in out["pins"] if s["place"] in chosen])
    fill_spots(p, out["layout"])
    return old if old and old != fname else ""


# ---------- 빈 블록 채우기 (OpenStreetMap 지도, canon/maps/fill.py) ----------

def fill_preview(layout: dict, seed: int) -> dict:
    """빈 블록 채우기 미리보기 (저장하지 않음): {seed, blocks, buildings, empty, areas, added, had(지금 지은 건물 수)}.
    areas · added 는 채울 블록과 지을 건물 다각형 (0~1)."""
    _, st = fill.fill(layout, seed)
    return {"seed": seed, **st, "had": fill.made_count(layout)}


def made_count(layout: dict) -> int:
    """빈 블록에 지은 건물 수."""
    return fill.made_count(layout)


def apply_fill(folder: Path, p: Project, layout: dict, seed: int) -> dict:
    """빈 블록을 채워 지도 파일을 다시 쓴다. 지은 건물은 건물 끝에 붙어 OSM 건물 번호와 고친 건물은 그대로다
    (전에 지은 건물을 고친 기록만 지운다). 돌려주는 것: {seed, blocks, buildings, empty}."""
    out, st = fill.fill(layout, seed)
    _write_fill(folder, p, out, fill.base_count(layout))
    p.atlas.fill = MapFill(seed=seed, rule="villa")
    return {"seed": seed, **{k: st[k] for k in ("blocks", "buildings", "empty")}}


def clear_fill(folder: Path, p: Project, layout: dict) -> int:
    """지은 건물을 지워 지도 파일을 다시 쓴다. 돌려주는 것: 지운 건물 수."""
    n = fill.made_count(layout)
    _write_fill(folder, p, fill.clear(layout), fill.base_count(layout))
    p.atlas.fill = None
    return n


def _write_fill(folder: Path, p: Project, lo: dict, base: int) -> None:
    enrich(p, lo, p.atlas.layout)  # 올릴 때와 같은 시드 (파일 이름)
    (folder / p.atlas.layout).write_text(json.dumps(lo, ensure_ascii=False), encoding="utf-8")
    p.atlas.buildings = [x for x in p.atlas.buildings if x.i < base]
    fill_spots(p, lo)
