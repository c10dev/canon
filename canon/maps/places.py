"""지도의 장소: 장소 목록, 자리(pins), 위치 글 잇기(links), 화별 인물 자리(frames), 위치 글 정리. LLM 을 부르지 않는다.

장소는 따로 정의하지 않는다. 설정의 장소 칸(world.locations)과 인과율 '장소' 요소가 장소이고,
지도(Project.atlas)는 그 위에 자리(pins), 배경 그림, 위치 글 잇기(links)만 더한다.
인물 위치는 상태 변경안이 적은 CharacterState.location 글을 화별 상태(cast.walk)에서 읽어 장소 이름과 맞춘다.
'하르덴에서 벨라 항구로 가는 길'처럼 두 곳이 나오면 뒤에 나온 곳을 지금 자리로, 앞의 곳을 거쳐 온 곳으로 본다.
"""
from __future__ import annotations

from typing import Optional

from .. import cast, elements, naming
from ..schema import MapPin, NewPlace, PlaceLink, PlaceSort, Project
from . import kinds as placekinds


SORT_CHUNK = 60  # AI 정리 한 번에 보낼 위치 글 수


def places(p: Project) -> list[dict]:
    """지도에 놓을 수 있는 장소. 인과율 장소 요소 먼저, 그다음 요소와 겹치지 않는 설정 장소 칸.
    known_from 은 독자가 이 장소를 아는 화(0 이면 처음부터): 생긴 화, 처음 나온 화, 드러나는 화 중 가장 늦은 것."""
    out, seen = [], set()
    for el in p.elements:
        if el.kind != "장소" or not el.name.strip():
            continue
        seen |= {naming.place_key(t) for t in [el.name, *el.aliases] if t.strip()}
        out.append({"key": el.id, "name": el.name.strip(), "aliases": [a for a in el.aliases if a.strip()],
                    "description": el.description, "since_ep": el.since_ep, "found_ep": el.found_ep,
                    "reveal_ep": el.reveal_ep, "known_from": max(el.since_ep, el.found_ep, el.reveal_ep, 0), "source": "요소"})
    for raw in p.world.locations:
        name = naming.place_base(raw)
        k = naming.place_key(name)
        if not k or k in seen:
            continue
        seen.add(k)
        desc = raw.strip()[len(name):].strip().lstrip(":：-–—,").strip()
        out.append({"key": "w:" + name, "name": name, "aliases": [], "description": desc, "since_ep": 0,
                    "found_ep": 0, "reveal_ep": 0, "known_from": 0, "source": "설정"})
    return out


def match(p: Project, text: str, pls: Optional[list[dict]] = None) -> list[str]:
    """위치 글에 나오는 장소 키를 글 순서대로. 작가가 이어 둔 글(atlas.links)이 먼저다.
    띄어쓰기는 무시하고, 다른 장소 이름 안에 든 짧은 이름(하르덴 왕궁 안의 하르덴)은 뺀다."""
    t = text.strip()
    if not t:
        return []
    link = next((ln for ln in p.atlas.links if ln.text.strip() == t), None)
    if link is not None:
        return [link.place] if link.place else []
    key = naming.place_key(t)
    hits = []
    for pl in pls if pls is not None else places(p):
        for term in [pl["name"], *pl["aliases"]]:
            k = naming.place_key(term)
            i = key.find(k) if len(k) >= 2 else -1
            if i >= 0:
                hits.append((i, i + len(k), pl["key"]))
    inner = lambda h: any(o[0] <= h[0] and h[1] <= o[1] and o[1] - o[0] > h[1] - h[0] for o in hits)  # noqa: E731
    out: list[str] = []
    for _, _, pk in sorted(h for h in hits if not inner(h)):
        if pk not in out:
            out.append(pk)
    return out


def mentions(text: str, pls: list[dict]) -> list[str]:
    """본문이나 플롯 글에 이름이 나오는 장소 키."""
    return [pl["key"] for pl in pls if any(len(term.strip()) >= 2 and term.strip() in text for term in [pl["name"], *pl["aliases"]])]


def frames(p: Project, pls: Optional[list[dict]] = None) -> list[dict]:
    """화별 인물 자리. 0 은 1화 시작 전, n 은 n화 반영 뒤 (인물 · 관계도 화면과 같은 시점).
    rows: 인물마다 위치 글, 맞춘 장소(place), 거쳐 온 곳(via), 앞 시점과 장소가 바뀌었는지(moved).
    mentioned: n화 본문(없으면 플롯)에 이름이 나온 장소."""
    pls = pls if pls is not None else places(p)
    out, prev = [], {}
    for n, sim in cast.walk(p):
        rows = []
        for s in sim.states:
            loc = s.location.strip()
            keys = match(p, loc, pls)
            at = keys[-1] if keys else ""
            before = prev.get(s.character_id, "")
            rows.append({"cid": s.character_id, "location": loc, "place": at, "via": keys[:-1],
                         "moved": bool(at and before and before != at)})
            if at:
                prev[s.character_id] = at
        e = p.episode(n) if n else None
        text = (e.text or "\n".join([e.plot.title, e.plot.summary, *e.plot.events])) if e else ""
        out.append({"episode": n, "rows": rows, "mentioned": mentions(text, pls) if text else []})
    return out


def unmatched(p: Project, fs: list[dict]) -> list[dict]:
    """어느 장소와도 맞지 않은 위치 글 (작가가 '그리지 않음'으로 이은 글은 뺀다). 처음 나온 화 순."""
    linked = {ln.text.strip() for ln in p.atlas.links}
    seen: dict[str, dict] = {}
    for f in fs:
        for r in f["rows"]:
            if not r["location"] or r["place"] or r["location"] in linked:
                continue
            x = seen.setdefault(r["location"], {"text": r["location"], "episodes": [], "characters": []})
            if f["episode"] not in x["episodes"]:
                x["episodes"].append(f["episode"])
            if r["cid"] not in x["characters"]:
                x["characters"].append(r["cid"])
    return list(seen.values())


def place_kinds(p: Project, era: str, pls: Optional[list[dict]] = None) -> dict[str, str]:
    """장소 키 → 그 시대의 종류 id (지도 핀 기호). 작가가 지도 만들기에서 고른 종류(MapSpec.places)를 to_era 로 읽고,
    비면 이름 · 설명에서 찾는다. gen_places 와 같은 차례지만 시대를 지도 만들기 입력이 아니라 지금 지도에서 받는다."""
    mine = {x.key: x.kind for x in (p.atlas.spec.places if p.atlas.spec else [])}
    return {pl["key"]: placekinds.to_era(mine.get(pl["key"], ""), era) or placekinds.classify(pl["name"], pl["description"], era)[0]
            for pl in (places(p) if pls is None else pls)}


# ---------- 지도에서 장소 더하기 ----------

def add_place(p: Project, name: str, x: float, y: float, kind: str = "") -> str:
    """지도에서 고른 자리(건물 등)를 새 장소로 등록하고 그 자리에 놓는다. 인과율 '장소' 요소가 된다 (작가가 더한 요소).
    돌려주는 것: 새 장소 키."""
    n = " ".join(name.split())
    if not n:
        raise ValueError("장소 이름을 적어 주세요")
    pls = places(p)
    if place_by_name(n, pls):
        raise ValueError(f"이미 있는 장소예요: {n}")
    if not elements.add_places(p, [NewPlace(name=n, kind=kind.strip(), description="지도에서 더한 곳")], 0, ""):
        raise ValueError(f"비슷한 이름의 장소가 이미 있어요: {n}")
    key = place_by_name(n, places(p))
    set_pins(p, [*p.atlas.pins, MapPin(place=key, x=x, y=y)])
    return key


def name_ideas(p: Project, n: int = 6) -> list[str]:
    """새 장소 이름 후보 (작품 이름 스타일, 이미 있는 장소 이름은 뺀다). LLM 을 부르지 않는다."""
    have = {pl["name"] for pl in places(p)}
    return [c.name for c in naming.generate_places(naming.resolve_style(p), n, exclude=have)]


# ---------- 작가가 고치기 ----------

def _clamp(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def set_pins(p: Project, pins: list[MapPin]) -> None:
    """장소 자리를 통째로 바꾼다. 없는 장소와 겹친 자리는 뺀다 (뒤에 온 것이 이긴다)."""
    keys = {pl["key"] for pl in places(p)}
    out: dict[str, MapPin] = {}
    for pin in pins:
        if pin.place in keys:
            out[pin.place] = MapPin(place=pin.place, x=_clamp(pin.x), y=_clamp(pin.y))
    p.atlas.pins = list(out.values())


def set_link(p: Project, text: str, place: Optional[str]) -> None:
    """위치 글 하나를 장소에 잇는다. place 가 None 이면 잇기를 지우고, 빈 문자열이면 '지도에 그리지 않음'."""
    t = text.strip()
    if not t:
        raise ValueError("위치 글이 비어 있어요")
    if place and place not in {pl["key"] for pl in places(p)}:
        raise ValueError(f"장소를 찾지 못했어요: {place}")
    p.atlas.links = [ln for ln in p.atlas.links if ln.text.strip() != t]
    if place is not None:
        p.atlas.links.append(PlaceLink(text=t, place=place))


def prune(p: Project) -> None:
    """지워진 장소의 자리와 잇기를 정리한다 (지도 화면을 저장할 때)."""
    keys = {pl["key"] for pl in places(p)}
    p.atlas.pins = [pin for pin in p.atlas.pins if pin.place in keys]
    p.atlas.links = [ln for ln in p.atlas.links if not ln.place or ln.place in keys]


# ---------- 맞지 않은 위치 글 한 번에 정리 (AI 제안은 pipeline.sort_places) ----------

def place_by_name(name: str, pls: list[dict]) -> str:
    """이름이나 다른 이름이 같은(띄어쓰기 무시) 장소 키. 없으면 빈 문자열."""
    k = naming.place_key(name.strip())
    if len(k) < 2:
        return ""
    return next((pl["key"] for pl in pls if any(naming.place_key(t) == k for t in [pl["name"], *pl["aliases"]])), "")


def clean_sort(p: Project, items: list[dict], outs: list[PlaceSort]) -> dict:
    """AI 제안을 화면에 보일 모양으로. 장소 이름은 키로 바꾸고, 이미 있는 이름의 새 장소는 그 장소로 돌린다.
    rows: 위치 글마다 {text, characters, episodes, place(키), new_place(이름), skip, note}.
    new_places: 실제로 쓰인 새 장소만, first_ep(그 장소로 이은 위치 글이 처음 나온 화)를 붙여서."""
    pls = places(p)
    guesses = {g.text.strip(): g for s in outs for g in s.matches}
    new: dict[str, NewPlace] = {}
    for s in outs:
        for x in s.new_places:
            k = naming.place_key(x.name.strip())
            if len(k) >= 2 and k not in new and not place_by_name(x.name, pls):
                new[k] = x.model_copy(update={"name": x.name.strip(), "description": x.description.strip(), "kind": x.kind.strip()})
    rows, first = [], {}
    for it in items:
        g = guesses.get(it["text"])
        place = place_by_name(g.place, pls) if g and g.place.strip() else ""
        newp = ""
        if not place and g and g.new_place.strip():
            place = place_by_name(g.new_place, pls)
            k = naming.place_key(g.new_place.strip())
            if not place and len(k) >= 2:
                new.setdefault(k, NewPlace(name=g.new_place.strip()))  # new_places 에 빠뜨린 이름
                newp = new[k].name
                eps = [n for n in it["episodes"] if n] or [0]
                first[k] = min(first.get(k, eps[0]), *eps)
        rows.append({**it, "place": place, "new_place": newp, "skip": bool(g and g.skip and not place and not newp),
                     "note": g.note.strip() if g else ""})
    return {"rows": rows, "new_places": [{**x.model_dump(), "first_ep": first[k]} for k, x in new.items() if k in first]}


def apply_sort(p: Project, new_places: list[tuple[NewPlace, int]], picks: list[tuple[str, str, str]]) -> dict:
    """작가가 고른 정리를 적용한다. new_places: (새 장소, 처음 나온 화). 고른 위치 글이 쓰는 것만 '장소' 요소로 등록한다.
    picks: (위치 글, 장소 키, 새 장소 이름). 장소 키와 새 장소 이름이 모두 비면 '지도에 그리지 않음'."""
    wanted = {naming.place_key(nw) for _, _, nw in picks if nw.strip()}
    added = []
    for x, n in new_places:
        if naming.place_key(x.name) in wanted:
            added += elements.add_places(p, [x], max(0, n), "본문")
    pls = places(p)
    keys = {pl["key"] for pl in pls}
    linked = 0
    for text, place, nw in picks:
        if nw.strip():
            place = place_by_name(nw, pls)
            if not place:
                raise ValueError(f"새 장소를 찾지 못했어요: {nw}")
        elif place and place not in keys:
            raise ValueError(f"장소를 찾지 못했어요: {place}")
        t = text.strip()
        if not t:
            continue
        p.atlas.links = [ln for ln in p.atlas.links if ln.text.strip() != t]
        p.atlas.links.append(PlaceLink(text=t, place=place))
        linked += 1
    return {"added": added, "linked": linked}
