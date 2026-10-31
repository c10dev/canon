"""지도 프롬프트 블록: 쓰기 · 검수 프롬프트에 넣는 지도 글. 줄 데이터는 travel(이동 거리) · atlas(장소가 놓인 건물)가 내고,
여기서 글로 바꾸고 예산(context.BUDGET["travel"] · ["spots"])에 맞춰 줄인다. prompts.py 가 부른다. LLM 을 부르지 않는다.
"""
from __future__ import annotations

from .. import context
from ..schema import Project
from . import travel
from .spots import episode_spots


def travel_block(p: Project, n: int, budget: int = 0) -> str:
    """n화를 쓰거나 검수할 때 넣는 이동 거리: 이번 화 인물의 지금 장소에서 플롯에 나온 장소까지 거리와 걸리는 시간.
    대중교통이고 지하철이 빠르면 '지하철로 약 n분 (역 → 역 n정거장, 서둘러도 n분)'. 꺼졌거나 축척을 모르거나 넣을 줄이 없으면 빈 문자열. 예산(context.BUDGET["travel"])을 넘으면 먼 것부터 뺀다."""
    moves = travel.episode_moves(p, n)
    if not moves:
        return ""
    budget = budget or context.BUDGET["travel"]
    label = travel.speed(p)[0]
    keep, size, cut = [], 0, 0
    for m in moves:
        r = m.get("rail")
        how = (f"지하철로 약 {travel.fmt_h(m['normal'])} ({r['path']} {r['stops']}정거장"
               + (f", 갈아타기 {r['transfers']}번" if r["transfers"] else "") + f", 서둘러도 {travel.fmt_h(m['fast'])})") if r else \
            f"{label} 보통 {travel.fmt_h(m['normal'])} (서둘러도 {travel.fmt_h(m['fast'])})"
        text = f"- {m['who']}: {m['src']} → {m['dst']} 약 {travel.fmt_km(m['km'])}, {how}"
        if size + len(text) > budget and keep:
            cut += 1
            continue
        keep.append(text)
        size += len(text) + 1
    rail = ", 지하철은 역까지 걷기 · 기다림 · 갈아타기 포함" if any(m.get("rail") for m in moves) else ""
    head = f"지도 기준 거리와 걸리는 시간 (길 굽음 포함 어림{rail}{f', 먼 것 {cut}개 생략' if cut else ''}):"
    tail = "- 인물이 이보다 짧은 시간에 닿으면 본문에서 탈것이나 지난 시간을 밝힙니다."
    return "\n".join([head, *keep, tail])


def travel_check_rule(p: Project, n: int) -> str:
    if not travel_block(p, n):
        return ""
    return ("\n- 이동: 위 '이동 거리'보다 짧은 작품 속 시간에 인물이 먼 장소에 닿았는데 본문에 그 까닭(빠른 탈것, 순간 이동 등)이 없는지 봅니다. "
            "근거가 거리 줄이면 source_episode 는 0, source_quote 는 그 줄입니다.")


def spot_block(p: Project, n: int, budget: int = 0) -> str:
    """n화를 쓰거나 검수할 때 넣는 장소의 건물: 플롯에 이름이 나온 장소 가운데 건물 한 줄(MapPin.spot)이 있는 것.
    예산(context.BUDGET["spots"])을 넘으면 뒤에 나온 장소부터 빼고 뺀 수를 적는다. 넣을 줄이 없으면 빈 글."""
    spots = episode_spots(p, n)
    budget = budget or context.BUDGET["spots"]
    keep, size, cut = [], 0, 0
    for name, spot in spots:
        row = f"- {name}: {spot}"
        if size + len(row) > budget and keep:
            cut += 1
            continue
        keep.append(row)
        size += len(row) + 1
    if not keep:
        return ""
    return "\n".join([*keep, *([f"- (장소 {cut}곳 생략)"] if cut else []),
                      "- 본문의 층수 · 가게 · 주소가 위와 맞게 씁니다. 다르게 쓸 까닭이 있으면 본문에서 밝힙니다."])
