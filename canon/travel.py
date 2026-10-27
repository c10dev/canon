"""이동 시간 검사: 인물이 옮겨 간 거리(지도)와 그동안 지난 작품 속 시간(timeline)을 견줘 너무 빠른 이동을 찾는다.

거리: 두 장소의 지도 자리(MapPin) 사이 곧은 거리에 길 굽음(DETOUR)을 곱한다. 지도의 실제 크기는 마을 데이터가 있으면
그 크기 × 축척(Atlas.layout_size, meters), 없으면 작가가 적은 지도 가로 km(Atlas.span_km). 모르면 검사하지 않는다.
상태 변경안을 정리할 때(pipeline.clean_delta)는 작품 폴더를 모르므로 길 데이터(atlas.route)는 쓰지 않는다.

시간: 화가 끝난 시점(Episode.time)의 날수와 시간대에서 가장 넉넉한 창을 잡는다. 떠난 쪽은 시간대의 이른 끝,
닿은 쪽은 늦은 끝, 모르는 시간대는 하루 전체, 모르는 날수는 그 앞(떠난 쪽) · 그 뒤(닿은 쪽)에서 아는 화로 넓힌다.
그래서 '빠르다'는 판정은 기록을 가장 너그럽게 읽어도 못 가는 경우만 낸다.

빠르기: 이 세계에서 인물이 쓰는 가장 빠른 탈것(TravelSetting.mode, MODES). 보통 걸음(하루 day_km, 밤에는 쉰다)으로
못 가면 '빠듯해요', 밤낮 없이 서둘러도(BURST_H 시간 전력 뒤 하루 push_km) 못 가면 '너무 빨라요'.
빠르기 기본값은 어림이다 (DESIGN.md). LLM 을 부르지 않는다.

화면은 canon/static/atlas.js 의 '이동 시간 검사' 칸, 명령줄은 `map <작품> travel`.
"""
from __future__ import annotations

import math
import re
from typing import Optional

from . import atlas, context, logline
from .schema import Episode, Project, StateDelta, StoryTime

# id → (말, 보통 빠르기 km/시, 보통 하루 km, 서두른 하루 km). 어림값. 작가가 TravelSetting.kmh · day_km 로 바꾼다
MODES = {
    "walk": ("걸어서", 5.0, 30.0, 60.0),
    "horse": ("말로", 10.0, 50.0, 150.0),
    "carriage": ("마차로", 6.0, 40.0, 80.0),
    "ship": ("배로", 8.0, 120.0, 200.0),
    "car": ("차로", 60.0, 500.0, 1200.0),
}
MODE_NAMES = {"walk": "도보", "horse": "말", "carriage": "마차", "ship": "배", "car": "자동차"}
DETOUR = 1.3  # 곧은 거리 → 실제로 가는 길 (길 데이터를 쓰지 않을 때)
BURST_H = 4.0  # 처음 몇 시간은 보통보다 1.5배 빠르게 갈 수 있다
OK, TIGHT, FAST = "ok", "tight", "fast"

# 시간대 글 → (이른 시각, 늦은 시각). 0 시 = 그날 시작. 밤은 다음 날 새벽 3시(27)까지 그날로 본다. 긴 말부터 찾는다
PARTS = [("한밤", 22, 27), ("자정", 23, 25), ("새벽", 2, 7), ("아침", 5, 10), ("오전", 6, 12), ("점심", 11, 14), ("정오", 11, 13),
         ("해질녘", 16, 20), ("저녁", 16, 22), ("오후", 12, 19), ("낮", 9, 17), ("밤", 18, 27)]
_HOUR = re.compile(r"(\d{1,2})\s*시")


def enabled(p: Project) -> bool:
    return p.atlas.travel.enabled


def speed(p: Project) -> tuple[str, float, float, float]:
    """(말, 보통 km/시, 보통 하루 km, 서두른 하루 km). 작가가 정한 값이 있으면 그 값 (서두른 하루는 보통의 2배)."""
    t = p.atlas.travel
    label, kmh, day, push = MODES.get(t.mode, MODES["horse"])
    if t.kmh > 0:
        kmh = t.kmh
    if t.day_km > 0:
        day, push = t.day_km, t.day_km * 2
    return label, kmh, day, max(push, day)


def need(p: Project, km: float) -> tuple[float, float]:
    """km 를 가는 데 드는 (보통 시간, 가장 서두른 시간). 보통은 하루에 day_km 를 가고 밤에 쉰다."""
    _, kmh, day, push = speed(p)
    full = math.floor(km / day)
    rest = km - full * day
    normal = full * 24 + rest / kmh if rest > 1e-9 or not full else (full - 1) * 24 + day / kmh
    peak = kmh * 1.5
    fast = km / peak if km <= peak * BURST_H else BURST_H + (km - peak * BURST_H) / push * 24
    return normal, fast


def hours(part: str) -> tuple[float, float]:
    """시간대 글의 (이른 시각, 늦은 시각). '오후 3시쯤'은 14~16, 오전 · 오후가 없는 '3시'는 3~16, 모르면 0~24."""
    t = part.strip()
    m = _HOUR.search(t)
    if m:
        h = int(m.group(1)) % 24
        if "밤" in t and (h == 12 or h <= 4):  # 밤 12시, 한밤 2시는 그날 밤 (다음 날 새벽)
            h += 12 if h == 12 else 24
        elif h < 12 and (any(w in t for w in ("오후", "저녁")) or ("밤" in t and h >= 5) or ("낮" in t and h <= 6)):
            h += 12
        elif h <= 12 and not any(w in t for w in ("오전", "아침", "새벽", "낮", "정오")):
            return max(0.0, h - 1.0), h + 13.0  # 오전인지 오후인지 모른다
        return max(0.0, h - 1.0), h + 1.0
    for word, lo, hi in PARTS:
        if word in t:
            return float(lo), float(hi)
    return 0.0, 24.0


def _start(p: Project, k: int) -> float:
    """k화가 끝난 때(0 이면 1화 시작)를 1일째 0시부터 센 시간. 가장 이른 쪽으로 (모르면 그 앞에서 아는 화)."""
    for e in sorted(p.episodes, key=lambda x: -x.plot.number):
        if e.plot.number <= k and e.time.day > 0:
            return (e.time.day - 1) * 24 + hours(e.time.part)[0]
    return 0.0


def _end(p: Project, n: int, t: Optional[StoryTime] = None) -> Optional[float]:
    """n화가 끝난 때. 가장 늦은 쪽으로 (t 를 주면 그 시점, 모르면 그 뒤에서 아는 화). 날수를 모르면 None."""
    if t is not None:
        return (t.day - 1) * 24 + hours(t.part)[1] if t.day > 0 else None
    for e in sorted(p.episodes, key=lambda x: x.plot.number):
        if e.plot.number >= n and e.time.day > 0:
            return (e.time.day - 1) * 24 + hours(e.time.part)[1]
    return None


def window(p: Project, k: int, n: int, t: Optional[StoryTime] = None) -> Optional[float]:
    """k화 끝에서 n화 끝까지 가장 넉넉하게 잡은 시간. 모르거나 시간이 거꾸로 가면(회상 등) None."""
    end = _end(p, n, t)
    if end is None:
        return None
    gap = end - _start(p, k)
    return gap if gap >= 0 else None


# ---------- 거리 ----------

def scale(p: Project) -> Optional[tuple[float, float]]:
    """지도 가로 · 세로 km. 마을 데이터가 있으면 그 크기 × 축척, 없으면 작가가 적은 가로와 지도 비율. 모르면 None."""
    a = p.atlas
    if a.layout and len(a.layout_size) == 2 and min(a.layout_size) > 0:
        return a.layout_size[0] * a.meters / 1000, a.layout_size[1] * a.meters / 1000
    if a.span_km > 0 and a.aspect > 0:
        return a.span_km, a.span_km / a.aspect
    return None


def km(p: Project, stops: list[str], pins: Optional[dict] = None) -> Optional[float]:
    """장소 키를 차례로 지나는 거리 (곧은 거리 × DETOUR). 어느 장소라도 지도에 안 놓였거나 축척을 모르면 None."""
    sc = scale(p)
    pins = pins if pins is not None else {pin.place: (pin.x, pin.y) for pin in p.atlas.pins}
    if sc is None or not all(k in pins for k in stops):
        return None
    w, h = sc
    return sum(math.hypot((pins[a][0] - pins[b][0]) * w, (pins[a][1] - pins[b][1]) * h) for a, b in zip(stops, stops[1:])) * DETOUR


def fmt_km(x: float) -> str:
    return f"{round(x * 1000)}m" if x < 1 else f"{x:.1f}km" if x < 10 else f"{round(x):,}km"


def fmt_h(x: float) -> str:
    """'40분', '5시간', '2일 반', '약 12일'."""
    if x < 1:
        return f"{max(1, round(x * 60))}분"
    if x < 24:
        return f"{round(x)}시간"
    d = round(x / 12) / 2
    if d >= 10:
        return f"약 {round(d)}일"
    return f"{int(d)}일" + (" 반" if d % 1 else "")


def judge(p: Project, dist: float, gap: Optional[float]) -> dict:
    normal, fast = need(p, dist)
    level = OK if gap is None or normal <= gap else TIGHT if fast <= gap else FAST
    return {"km": round(dist, 3), "normal": round(normal, 2), "fast": round(fast, 2),
            "gap": None if gap is None else round(gap, 2), "level": level}


# ---------- 반영한 화의 이동 (지도 화면 · 명령줄) ----------

def moves(p: Project, fs: Optional[list[dict]] = None, pls: Optional[list[dict]] = None) -> list[dict]:
    """반영한 화마다 장소를 옮긴 인물의 이동. 거리를 모르면 빼고, 시간을 모르면 level ok · gap None.
    항목: cid, episode(닿은 화), since(떠난 장소에 있던 마지막 화), stops(장소 키), km, normal, fast, gap, level, accepted."""
    pls = pls if pls is not None else atlas.places(p)
    fs = fs if fs is not None else atlas.frames(p, pls)
    pins = {pin.place: (pin.x, pin.y) for pin in p.atlas.pins}
    ok = set(p.atlas.travel.ok)
    out, last = [], {}
    for f in fs:
        for r in f["rows"]:
            at = r["place"]
            if not at:
                continue
            before = last.get(r["cid"])
            last[r["cid"]] = (at, f["episode"])
            if not (r["moved"] and before):
                continue
            stops = [before[0], *[k for k in r["via"] if k != before[0]], at]
            dist = km(p, stops, pins)
            if dist is None:
                continue
            row = judge(p, dist, window(p, before[1], f["episode"]))
            out.append({"cid": r["cid"], "episode": f["episode"], "since": before[1], "stops": stops, **row,
                        "accepted": f"{r['cid']}:{f['episode']}" in ok})
    return out


def names(p: Project) -> dict[str, str]:
    return {c.id: c.name or c.id for c in p.characters}


def path_text(p: Project, m: dict, place_names: dict[str, str]) -> str:
    """'흑송촌 → 왕도 약 340km를 2일 안에 (말로 보통 7일, 서둘러도 2일 반)'."""
    path = " → ".join(place_names.get(k, k) for k in m["stops"])
    gap = f"를 {fmt_h(m['gap'])} 안에" if m["gap"] is not None else ""
    return f"{path} 약 {fmt_km(m['km'])}{gap} ({speed(p)[0]} 보통 {fmt_h(m['normal'])}, 서둘러도 {fmt_h(m['fast'])})"



def view(p: Project, fs: Optional[list[dict]] = None, pls: Optional[list[dict]] = None) -> dict:
    """지도 화면의 '이동 시간 검사' 칸: 설정, 축척을 아는지, 걸린 이동(빠듯함 · 너무 빠름), 시간을 몰라 못 본 이동 수."""
    t = p.atlas.travel
    sc = scale(p)
    pls = pls if pls is not None else atlas.places(p)
    ms = moves(p, fs, pls) if t.enabled else []
    pnames, who = {pl["key"]: pl["name"] for pl in pls}, names(p)
    hit = [{**m, "who": who.get(m["cid"], m["cid"]), "text": path_text(p, m, pnames)} for m in ms if m["level"] != OK]
    return {"enabled": t.enabled, "mode": t.mode, "kmh": t.kmh, "day_km": t.day_km, "span_km": p.atlas.span_km,
            "scale": [round(sc[0], 3), round(sc[1], 3)] if sc else None, "from_layout": bool(sc and p.atlas.layout and p.atlas.layout_size),
            "scale_text": f"{fmt_km(sc[0])} × {fmt_km(sc[1])}" if sc else "",
            "speed": list(speed(p)), "modes": [{"id": k, "label": MODE_NAMES[k], "kmh": v[1], "day_km": v[2]} for k, v in MODES.items()],
            "moves": hit, "checked": sum(m["gap"] is not None for m in ms), "unknown": sum(m["gap"] is None for m in ms)}


def set_setting(p: Project, enabled: bool, mode: str, kmh: float, day_km: float, span_km: float) -> None:
    if mode not in MODES:
        raise ValueError(f"모르는 탈것이에요: {mode}")
    if not (0 <= kmh <= 2000 and 0 <= day_km <= 20000):
        raise ValueError("빠르기는 0~2000km/시, 하루 거리는 0~20000km 사이로 정하세요")
    if not 0 <= span_km <= 100000:
        raise ValueError("지도 가로는 0~100000km 사이로 정하세요")
    t = p.atlas.travel
    t.enabled, t.mode, t.kmh, t.day_km = enabled, mode, float(kmh), float(day_km)
    p.atlas.span_km = float(span_km)


def accept(p: Project, cid: str, n: int, ok: bool = True) -> None:
    """작가가 이 이동을 '괜찮아요'(순간 이동, 기록 밖의 탈것 등)로 두거나 되돌린다."""
    key = f"{cid}:{n}"
    lst = [x for x in p.atlas.travel.ok if x != key]
    p.atlas.travel.ok = [*lst, key] if ok else lst


# ---------- 상태 변경안 경고 (pipeline.clean_delta) ----------

def _last_places(p: Project, n: int, pls: list[dict]) -> dict[str, tuple[str, int]]:
    """n화 전까지 반영한 화에서 인물마다 마지막으로 맞춘 장소와 그 화."""
    last: dict[str, tuple[str, int]] = {}
    for f in atlas.frames(p, pls):
        if f["episode"] >= n:
            break
        for r in f["rows"]:
            if r["place"]:
                last[r["cid"]] = (r["place"], f["episode"])
    return last


def delta_warnings(p: Project, d: StateDelta) -> list[str]:
    """상태 변경안대로 반영하면 서둘러도 못 갈 만큼 빨리 옮겨 간 인물. 꺼졌거나 축척 · 시점을 모르면 빈 목록."""
    if not enabled(p) or scale(p) is None or d.time.day <= 0:
        return []
    pls = atlas.places(p)
    last = _last_places(p, d.episode, pls)
    pnames = {pl["key"]: pl["name"] for pl in pls}
    ok = set(p.atlas.travel.ok)
    out = []
    for u in d.character_updates:
        keys = atlas.match(p, u.location.strip(), pls) if u.location.strip() else []
        before = last.get(u.character_id)
        if not keys or not before or before[0] == keys[-1] or f"{u.character_id}:{d.episode}" in ok:
            continue
        stops = [before[0], *[k for k in keys[:-1] if k != before[0]], keys[-1]]
        dist = km(p, stops)
        if dist is None:
            continue
        m = {"cid": u.character_id, "stops": stops, **judge(p, dist, window(p, before[1], d.episode, d.time))}
        if m["level"] == FAST:
            who = names(p).get(u.character_id, u.character_id)
            out.append(f"{who}{logline.josa(who, '이', '가')} 너무 빨리 옮겨 갔어요: {path_text(p, m, pnames)}. "
                       "작품 속 시간이나 위치가 맞는지 보세요 (순간 이동 같은 설정이면 반영한 뒤 지도 화면의 이동 시간 검사에서 '괜찮아요'로 둘 수 있어요)")
    return out


# ---------- 프롬프트 (쓰기 · 검수) ----------

def episode_block(p: Project, n: int, budget: int = 0) -> str:
    """n화를 쓰거나 검수할 때 넣는 이동 거리: 이번 화 인물의 지금 장소에서 플롯에 나온 장소까지 거리와 걸리는 시간.
    꺼졌거나 축척을 모르거나 넣을 줄이 없으면 빈 문자열. 예산(context.BUDGET["travel"])을 넘으면 먼 것부터 뺀다."""
    if not enabled(p) or scale(p) is None:
        return ""
    budget = budget or context.BUDGET["travel"]
    ep = next((e for e in p.episodes if e.plot.number == n), None)
    if ep is None:
        return ""
    pls = atlas.places(p)
    pnames = {pl["key"]: pl["name"] for pl in pls}
    targets = atlas.mentions(_plot_text(ep), pls)
    if not targets:
        return ""
    last = _last_places(p, n, pls)
    cast_ids = ep.plot.characters or list(last)
    who = names(p)
    label = speed(p)[0]
    rows = []
    for cid in cast_ids:
        here = last.get(cid)
        if not here:
            continue
        for to in targets:
            dist = km(p, [here[0], to]) if to != here[0] else None
            if dist is None:
                continue
            normal, fast = need(p, dist)
            rows.append((dist, f"- {who.get(cid, cid)}: {pnames.get(here[0], here[0])} → {pnames.get(to, to)} 약 {fmt_km(dist)}, "
                               f"{label} 보통 {fmt_h(normal)} (서둘러도 {fmt_h(fast)})"))
    if not rows:
        return ""
    rows.sort(key=lambda x: x[0])
    keep, size, cut = [], 0, 0
    for _, text in rows:
        if size + len(text) > budget and keep:
            cut += 1
            continue
        keep.append(text)
        size += len(text) + 1
    head = f"지도 기준 거리와 걸리는 시간 (길 굽음 포함 어림{f', 먼 것 {cut}개 생략' if cut else ''}):"
    tail = "- 인물이 이보다 짧은 시간에 닿으면 본문에서 탈것이나 지난 시간을 밝힙니다."
    return "\n".join([head, *keep, tail])


def check_rule(p: Project, n: int) -> str:
    if not episode_block(p, n):
        return ""
    return ("\n- 이동: 위 '이동 거리'보다 짧은 작품 속 시간에 인물이 먼 장소에 닿았는데 본문에 그 까닭(빠른 탈것, 순간 이동 등)이 없는지 봅니다. "
            "근거가 거리 줄이면 source_episode 는 0, source_quote 는 그 줄입니다.")


def _plot_text(e: Episode) -> str:
    return "\n".join([e.plot.title, e.plot.summary, *e.plot.events])


def describe(p: Project, fs: Optional[list[dict]] = None) -> str:
    """명령줄 출력."""
    v = view(p, fs)
    label, kmh, day, _ = speed(p)
    head = f"이동 시간 검사 ({'켜짐' if v['enabled'] else '꺼짐'}) · 가장 빠른 탈것: {MODE_NAMES.get(v['mode'], v['mode'])} (시속 {kmh:g}km, 하루 {day:g}km)"
    if not v["enabled"]:
        return head
    if not v["scale"]:
        return head + "\n지도 크기를 몰라 거리를 셀 수 없어요. `map <작품> travel --span <지도 가로 km>` 로 정하세요"
    lines = [head, f"지도 크기: 약 {fmt_km(v['scale'][0])} × {fmt_km(v['scale'][1])}" + (" (마을 데이터 축척)" if v["from_layout"] else "")]
    if not v["moves"]:
        lines.append(f"걸린 이동이 없어요 (본 이동 {v['checked']}개" + (f", 시점 기록이 없어 못 본 이동 {v['unknown']}개" if v["unknown"] else "") + ")")
    for m in v["moves"]:
        tag = "너무 빨라요" if m["level"] == FAST else "빠듯해요"
        lines.append(f"  {m['since']}~{m['episode']}화 [{tag}{' · 괜찮아요로 둠' if m['accepted'] else ''}] {m['who']}: {m['text']}")
    return "\n".join(lines)
