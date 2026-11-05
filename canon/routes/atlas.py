"""지도 (canon/atlas.py) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

import json
import re
import zlib
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel
from .. import atlas, pipeline, store
from ..llm import get_llm
from ..maps import travel
from ..schema import MapPin, MapSpec, NewPlace, Project
from ..web import (  # web 의 공용 도우미
    _json_view,
    _load,
    _map_dir,
    _save,
)

router = APIRouter()

@router.get("/api/projects/{name}/atlas")
def atlas_view(name: str, request: Request) -> dict:
    """지도 화면: 장소와 자리, 화별 인물 자리, 장소와 맞지 않은 위치 글. 마을 데이터가 있으면 길 따라 걸은 경로도.
    작품과 지도 폴더(map/)가 그대로면 기억한 결과를 보낸다 (_json_view)."""
    def build() -> bytes:
        p = _load(name)
        layout = atlas.load_layout(_map_dir(name), p)
        atlas.fill_old_spots(p, _map_dir(name), layout)  # 옛 핀의 건물 한 줄은 응답에만 싣는다. 저장은 다음 쓰기 · 검수 작업 때
        s = atlas.summary(p, layout)
        out = {**s, "travel": travel.view(p, s["frames"], s["places"]), "gen": atlas.gen_info(p)}
        return json.dumps(jsonable_encoder(out), ensure_ascii=False, separators=(",", ":")).encode()
    d = _map_dir(name)
    sig = f"-{zlib.crc32(repr([(f.name, f.stat().st_mtime_ns) for f in sorted(d.iterdir())]).encode()):x}" if d.is_dir() else ""
    return _json_view(request, name, "atlas", build, sig)


@router.post("/api/projects/{name}/atlas/generate/preview")
def atlas_generate_preview(name: str, body: MapSpec) -> dict:
    """지도 만들기 미리보기: 마을과 장소 자리 제안을 돌려준다. 저장하지 않는다."""
    return atlas.generate(_load(name), body)


@router.post("/api/projects/{name}/atlas/generate/suggest")
def atlas_generate_suggest(name: str, body: MapSpec) -> dict:
    """지도 만들기 설정 AI 제안 (크기 · 길 · 물 · 밭 · 숲, 장소마다 종류 · 놓기, 까닭). 저장하지 않는다."""
    return pipeline.suggest_map(get_llm("plan"), _load(name), body)


class GenerateIn(BaseModel):
    spec: MapSpec
    pins: list[str] = []  # 생성기가 고른 자리에 놓을 (이미 놓았으면 옮길) 장소 키


@router.post("/api/projects/{name}/atlas/generate")
def atlas_generate(name: str, body: GenerateIn) -> Project:
    """지도 만들기 적용: 같은 입력으로 마을을 다시 만들어 map/ 에 저장하고, 고른 장소만 새 자리에 놓는다."""
    p = _load(name)
    old = atlas.apply_generated(_map_dir(name), p, body.spec, body.pins)
    out = _save(name, p)
    _drop_map_file(name, old)
    return out


class TitleIn(BaseModel):
    title: str


@router.put("/api/projects/{name}/atlas/title")
def atlas_title(name: str, body: TitleIn) -> Project:
    """지도 위 마을 이름. 비우면 '마을 가운데' 종류의 장소 이름을 쓴다."""
    p = _load(name)
    atlas.set_title(p, body.title)
    return _save(name, p)


@router.get("/api/projects/{name}/atlas/name-ideas")
def atlas_name_ideas(name: str) -> dict:
    """새 장소 이름 후보 (작품 이름 스타일). 저장하지 않는다."""
    return {"names": atlas.name_ideas(_load(name))}


class PlaceAddIn(BaseModel):
    name: str
    x: float
    y: float
    kind: str = ""  # 종류 한 단어 (설명 앞에 붙는다)


@router.post("/api/projects/{name}/atlas/places")
def atlas_place_add(name: str, body: PlaceAddIn) -> dict:
    """지도에서 고른 자리를 새 장소(인과율 '장소')로 등록하고 놓는다. 돌려주는 것: {key, project}."""
    p = _load(name)
    key = atlas.add_place(p, body.name, body.x, body.y, body.kind)
    atlas.fill_spots(p, atlas.load_layout(_map_dir(name), p))
    return {"key": key, "project": _save(name, p)}


@router.get("/api/projects/{name}/atlas/find-spots")
def atlas_find_spots(name: str) -> dict:
    """이름으로 자리 찾기: 장소 이름과 같은 이름의 건물 · 입점한 곳 · 표지 (atlas.find_spots). 저장하지 않는다."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    return {"spots": atlas.find_spots(p, layout) if layout else []}


class PinsIn(BaseModel):
    pins: list[MapPin]


@router.put("/api/projects/{name}/atlas/pins")
def atlas_pins(name: str, body: PinsIn) -> Project:
    """장소 자리를 통째로 저장한다 (놓기, 끌어 옮기기, 지도에서 빼기)."""
    p = _load(name)
    atlas.set_pins(p, body.pins)
    atlas.prune(p)
    atlas.fill_spots(p, atlas.load_layout(_map_dir(name), p))
    return _save(name, p)


class LinkIn(BaseModel):
    text: str
    place: str | None = None  # None 이면 잇기를 지운다, "" 이면 지도에 그리지 않는 위치


@router.put("/api/projects/{name}/atlas/links")
def atlas_link(name: str, body: LinkIn) -> Project:
    """장소 이름과 맞지 않은 인물 위치 글을 장소에 잇는다."""
    p = _load(name)
    atlas.set_link(p, body.text, body.place)
    return _save(name, p)


class SortIn(BaseModel):
    texts: list[str] | None = None  # 이 위치 글만 정리 (비우면 맞지 않은 글 모두)


@router.post("/api/projects/{name}/atlas/sort")
def atlas_sort(name: str, body: SortIn) -> dict:
    """장소와 맞지 않은 위치 글을 AI 가 장소에 맞춘 제안. 저장하지 않는다."""
    return pipeline.sort_places(get_llm("state"), _load(name), body.texts)


class SortPlace(NewPlace):
    first_ep: int = 0


class SortPick(BaseModel):
    text: str
    place: str = ""  # 장소 키
    new_place: str = ""  # 함께 등록할 새 장소 이름. 둘 다 비면 지도에 그리지 않음


class SortApplyIn(BaseModel):
    new_places: list[SortPlace] = []
    picks: list[SortPick]


@router.post("/api/projects/{name}/atlas/sort/apply")
def atlas_sort_apply(name: str, body: SortApplyIn) -> dict:
    """고른 위치 글을 한 번에 잇고, 고른 글이 쓰는 새 장소는 인과율 '장소'로 등록한다."""
    p = _load(name)
    done = atlas.apply_sort(p, [(NewPlace(**x.model_dump(exclude={"first_ep"})), x.first_ep) for x in body.new_places],
                            [(x.text, x.place, x.new_place) for x in body.picks])
    return {**done, "project": _save(name, p)}


class MapImageIn(BaseModel):
    data: str  # data:image/png;base64,...
    aspect: float  # 그림 가로 / 세로




def _drop_map_file(name: str, fname: str) -> None:
    """map/ 안의 옛 그림 · 마을 파일을 지운다 (atlas.drop_old_file)."""
    atlas.drop_old_file(_map_dir(name), fname)


@router.put("/api/projects/{name}/atlas/image")
def atlas_image_set(name: str, body: MapImageIn) -> Project:
    """지도 배경 그림을 올린다. 작품 폴더의 map/ 에 파일로 두고 project.json 에는 이름만 적는다."""
    import base64
    import time

    m = re.match(r"data:([\w/+.-]+);base64,(.*)$", body.data, re.S)
    if not m or m.group(1) not in atlas.IMAGE_TYPES:
        raise ValueError("PNG, JPG, WEBP, GIF 그림만 올릴 수 있어요")
    raw = base64.b64decode(m.group(2), validate=False)
    if len(raw) > atlas.IMAGE_LIMIT:
        raise ValueError(f"그림이 너무 커요. {atlas.IMAGE_LIMIT // (1024 * 1024)}MB 이하로 올리세요")
    if not 0.1 <= body.aspect <= 10:
        raise ValueError("그림 비율을 읽지 못했어요")
    p = _load(name)
    d = _map_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    fname = f"map-{int(time.time())}.{atlas.IMAGE_TYPES[m.group(1)]}"
    store.write_atomic(d / fname, raw)
    old = p.atlas.image
    p.atlas.image, p.atlas.aspect = fname, round(body.aspect, 4)
    out = _save(name, p)
    if old != fname:
        _drop_map_file(name, old)
    return out


@router.delete("/api/projects/{name}/atlas/image")
def atlas_image_drop(name: str) -> Project:
    """배경 그림을 지우고 빈 캔버스로 돌아간다. 장소 자리는 그대로 둔다."""
    p = _load(name)
    old, p.atlas.image = p.atlas.image, ""
    out = _save(name, p)
    _drop_map_file(name, old)
    return out


@router.get("/api/projects/{name}/atlas/image")
def atlas_image_get(name: str) -> FileResponse:
    p = _load(name)
    path = _map_dir(name) / p.atlas.image if p.atlas.image else None
    if path is None or not path.is_file() or path.parent != _map_dir(name):
        raise HTTPException(404, "지도 그림이 없어요")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


class LayoutIn(BaseModel):
    data: str  # Watabou 생성기가 내보낸 JSON 글, 또는 OpenStreetMap .osm (XML) · GeoJSON 글


@router.put("/api/projects/{name}/atlas/layout")
def atlas_layout_set(name: str, body: LayoutIn) -> Project:
    """마을 · 도시 데이터를 올린다. 그릴 모양으로 바꿔(atlas.parse_upload: Watabou JSON 또는 OpenStreetMap) map/ 에 둔다.
    마을 데이터가 있으면 지도는 배경 그림 대신 마을을 그리고 비율도 마을을 따른다."""
    import time

    if len(body.data.encode("utf-8")) > atlas.LAYOUT_LIMIT:
        raise ValueError(f"파일이 너무 커요. {atlas.LAYOUT_LIMIT // (1024 * 1024)}MB 이하로 올리세요")
    layout = atlas.parse_upload(body.data)
    p = _load(name)
    d = _map_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    fname = f"layout-{int(time.time())}.json"
    atlas.enrich(p, layout, fname)
    store.write_atomic(d / fname, json.dumps(layout, ensure_ascii=False))
    old = p.atlas.layout
    p.atlas.layout, p.atlas.spec, p.atlas.buildings, p.atlas.layout_size, p.atlas.fill = fname, None, [], [layout["w"], layout["h"]], None
    atlas.fill_spots(p, layout)
    out = _save(name, p)
    if old != fname:
        _drop_map_file(name, old)
    return out


@router.delete("/api/projects/{name}/atlas/layout")
def atlas_layout_drop(name: str) -> Project:
    """마을 데이터를 지운다. 장소 자리는 그대로 둔다."""
    p = _load(name)
    old, p.atlas.layout, p.atlas.spec, p.atlas.buildings, p.atlas.layout_size, p.atlas.fill = p.atlas.layout, "", None, [], [], None
    atlas.fill_spots(p, None)
    out = _save(name, p)
    _drop_map_file(name, old)
    return out


class FillIn(BaseModel):
    mode: str = "preview"  # preview 미리보기 | apply 적용 | clear 지은 건물 지우기
    seed: int = 1


@router.post("/api/projects/{name}/atlas/layout/fill")
def atlas_layout_fill(name: str, body: FillIn) -> dict:
    """OpenStreetMap 지도의 빈 블록 채우기 (canon/maps/fill.py). preview 는 저장하지 않고 채울 블록 · 지을 건물을 돌려준다.
    apply 는 지도 파일을 다시 쓰고(지은 건물은 끝에 붙여 OSM 건물 번호를 지킨다) clear 는 지은 건물을 지운다."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    if layout is None:
        raise HTTPException(404, "마을 데이터가 없어요")
    if body.mode == "preview":
        return atlas.fill_preview(layout, body.seed)
    if body.mode == "apply":
        done = atlas.apply_fill(_map_dir(name), p, layout, body.seed)
        return {**done, "project": _save(name, p)}
    if body.mode == "clear":
        n = atlas.clear_fill(_map_dir(name), p, layout)
        return {"removed": n, "project": _save(name, p)}
    raise ValueError(f"모르는 동작이에요: {body.mode}")


@router.get("/api/projects/{name}/atlas/layout")
def atlas_layout_get(name: str) -> dict:
    """그릴 모양으로 바꾼 마을 데이터 (길 · 건물 · 물 · 밭 · 나무)."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    if layout is None:
        raise HTTPException(404, "마을 데이터가 없어요")
    return layout


class BuildingIn(BaseModel):
    use: str = ""
    name: str = ""
    note: str = ""
    residents: list[str] = []


@router.get("/api/projects/{name}/atlas/buildings/{i}")
def atlas_building(name: str, i: int) -> dict:
    """건물 하나: 쓰임 · 층수 · 사는 사람 · 주소 · 간판과 작가가 고친 값 (곁채면 본채 정보)."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    if layout is None:
        raise HTTPException(404, "마을 데이터가 없어요")
    try:
        return atlas.building(p, layout, i)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


@router.put("/api/projects/{name}/atlas/buildings/{i}")
def atlas_building_set(name: str, i: int, body: BuildingIn) -> Project:
    """작가가 건물을 고친다 (쓰임 · 이름 · 메모 · 사는 인물). 모두 비우면 생성기 값으로 돌아간다."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    if layout is None:
        raise HTTPException(404, "마을 데이터가 없어요")
    try:
        atlas.set_building(p, layout, i, body.use, body.name, body.note, body.residents)
        atlas.fill_spots(p, layout)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    return _save(name, p)


class TravelIn(BaseModel):
    enabled: bool = True
    mode: str = "horse"
    kmh: float = 0
    day_km: float = 0
    span_km: float = 0


@router.put("/api/projects/{name}/atlas/travel")
def atlas_travel(name: str, body: TravelIn) -> Project:
    """이동 시간 검사 설정: 켜기, 가장 빠른 탈것, 직접 정한 빠르기, 지도 가로 km (canon/maps/travel.py)."""
    p = _load(name)
    travel.set_setting(p, body.enabled, body.mode, body.kmh, body.day_km, body.span_km)
    return _save(name, p)


class TravelOkIn(BaseModel):
    cid: str
    episode: int
    ok: bool = True


@router.put("/api/projects/{name}/atlas/travel/ok")
def atlas_travel_ok(name: str, body: TravelOkIn) -> Project:
    """이동 하나를 '괜찮아요'(순간 이동 등)로 두거나 되돌린다. 그 이동은 경고에서 빠진다."""
    p = _load(name)
    travel.accept(p, body.cid, body.episode, body.ok)
    return _save(name, p)


class MetersIn(BaseModel):
    meters: float


@router.put("/api/projects/{name}/atlas/meters")
def atlas_meters(name: str, body: MetersIn) -> Project:
    """마을 데이터 1단위가 몇 m 인지 (거리 · 걷는 시간)."""
    p = _load(name)
    atlas.set_meters(p, body.meters)
    return _save(name, p)


EXPORTS = (
    "BuildingIn",
    "FillIn",
    "GenerateIn",
    "LayoutIn",
    "LinkIn",
    "MapImageIn",
    "MetersIn",
    "PinsIn",
    "PlaceAddIn",
    "SortApplyIn",
    "SortIn",
    "SortPick",
    "SortPlace",
    "TitleIn",
    "TravelIn",
    "TravelOkIn",
    "_drop_map_file",
    "atlas_building",
    "atlas_building_set",
    "atlas_find_spots",
    "atlas_generate",
    "atlas_generate_preview",
    "atlas_generate_suggest",
    "atlas_image_drop",
    "atlas_image_get",
    "atlas_image_set",
    "atlas_layout_drop",
    "atlas_layout_fill",
    "atlas_layout_get",
    "atlas_layout_set",
    "atlas_link",
    "atlas_meters",
    "atlas_name_ideas",
    "atlas_pins",
    "atlas_place_add",
    "atlas_sort",
    "atlas_sort_apply",
    "atlas_title",
    "atlas_travel",
    "atlas_travel_ok",
    "atlas_view",
)
