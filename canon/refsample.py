"""레퍼런스 원고의 문체 표본 흩기: 고른 화가 예산을 넘으면 앞부분만 자르지 않고 범위 전체에서 조각을 고루 뽑는다.

AI 를 부르지 않는다. 화 카드(canon/refdigest.py)가 있으면 화의 성격으로, 없으면 저장된 대사 비율로 화를 고른다.
설계는 docs/refs/README.md 9-3 (일감 8).
"""
from __future__ import annotations

import re

from . import metrics

ZONES = 3  # 고른 범위를 나누는 구간 수 (앞 · 가운데 · 뒤)
PER_ZONE = 3  # 구간마다 고르는 화 수
PARTS = (("head", 0.3), ("talk", 0.2), ("narr", 0.2), ("tail", 0.3))  # 화 하나의 예산을 나누는 몫: 첫머리 · 대사 많은 덩어리 · 서술 많은 덩어리 · 끝
PART_NAMES = {"all": "전체", "head": "첫머리", "talk": "대사 덩어리", "narr": "서술 덩어리", "tail": "끝"}
PIECE_MIN = 200  # 이보다 짧은 조각은 뽑지 않는다
ZONE_MIN = 10_000  # 구간 하나가 이보다 짧으면 구간별 표지 빈도를 내지 않는다 (1,000자당 횟수가 화 한두 개에 흔들린다)
SEP = "\n\n***\n\n"  # 조각 사이. 웹소설의 장면 전환 기호라 문체 분석이 본문으로 읽지 않는다


def _paras(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _talk(text: str) -> float:
    return sum(len(m) for m in metrics._QUOTE.findall(text)) / len(text) if text else 0.0


def _trim(text: str, quota: int, tail: bool = False) -> str:
    """quota 자 안으로. 문장이나 줄 끝에서 자른다 (tail 이면 끝 쪽을 남긴다)."""
    if len(text) <= quota:
        return text
    if tail:
        cut = text[-quota:]
        m = re.search(r"[.!?…\"”」]\s|\n", cut)
        return cut[m.end():].strip() if m and m.end() < len(cut) * 0.5 else cut.strip()
    cut = text[:quota]
    ends = [m.end() for m in re.finditer(r"[.!?…\"”」](?=\s)|\n", cut)]
    return cut[:ends[-1]].strip() if ends and ends[-1] > quota * 0.5 else cut.strip()


def _even(text: str, tail: bool = False) -> str:
    """큰따옴표가 짝이 맞게 한다. 따옴표 하나가 남으면 metrics 의 대사 재기(_QUOTE)가 그 뒤 글 전체에서 대사와 서술을 뒤바꿔 센다.
    문장 가운데에서 잘린 조각은 남은 따옴표 쪽을 잘라 내고(앞에서 자른 글은 마지막 여는 따옴표부터, 끝을 남긴 글은 첫 닫는 따옴표까지),
    그래도 안 맞으면 따옴표 수가 홀수인 문단을 뺀다. 글자를 고치지는 않는다."""
    if text.count('"') % 2 == 0:
        return text
    cut = text[text.index('"') + 1:].lstrip() if tail else text[:text.rindex('"')].rstrip()
    if cut.count('"') % 2 == 0 and len(cut) >= len(text) * 0.5:
        return cut
    return "\n\n".join(p for p in _paras(text) if p.count('"') % 2 == 0)


def _take(paras: list[str], quota: int, tail: bool = False) -> tuple[str, int]:
    """앞(또는 끝)에서 문단을 quota 자까지 모은다. (글, 쓴 문단 수)."""
    got: list[str] = []
    used = 0
    for p in (reversed(paras) if tail else paras):
        if got and used + len(p) > quota:
            break
        got.append(p)
        used += len(p)
        if used >= quota:
            break
    body = "\n\n".join(reversed(got) if tail else got)
    return _even(_trim(body, quota, tail), tail), len(got)


def _window(paras: list[str], quota: int, want_talk: bool, taken: set[int]) -> tuple[str, set[int]]:
    """이어진 문단 묶음(quota 자까지) 가운데 대사 몫이 가장 큰(또는 가장 작은) 것. taken 문단과 겹치지 않는다."""
    best, best_ix, best_score = "", set(), None
    for i in range(len(paras)):
        if i in taken:
            continue
        j, body = i, ""
        while j < len(paras) and j not in taken and len(body) + len(paras[j]) <= quota:
            body = f"{body}\n\n{paras[j]}" if body else paras[j]
            j += 1
        if len(body) < PIECE_MIN or body.count('"') % 2:
            continue
        score = _talk(body) if want_talk else -_talk(body)
        if best_score is None or score > best_score:
            best, best_ix, best_score = body, set(range(i, j)), score
    return best, best_ix


def pieces_of(text: str, quota: int) -> list[dict]:
    """화 하나에서 quota 자 안으로 뽑은 조각 [{part, text, at}]. 화가 quota 보다 짧으면 통째로."""
    if len(text) <= quota:
        return [{"part": "all", "text": _even(text), "at": 0}]
    paras = _paras(text)
    share = dict(PARTS)
    head, n_head = _take(paras, int(quota * share["head"]))
    tail, n_tail = _take(paras, int(quota * share["tail"]), tail=True)
    taken = set(range(n_head)) | set(range(len(paras) - n_tail, len(paras)))
    talk, ix = _window(paras, int(quota * share["talk"]), True, taken)
    narr, ix2 = _window(paras, int(quota * share["narr"]), False, taken | ix)
    out = [{"part": "head", "text": head, "at": 0}]
    if talk:
        out.append({"part": "talk", "text": talk, "at": min(ix)})
    if narr:
        out.append({"part": "narr", "text": narr, "at": min(ix2)})
    out.append({"part": "tail", "text": tail, "at": len(paras)})
    return sorted((p for p in out if p["text"]), key=lambda p: p["at"])


def _zones(items: list[dict]) -> list[list[dict]]:
    n = min(ZONES, len(items))
    return [items[len(items) * i // n: len(items) * (i + 1) // n] for i in range(n)]


def pick_episodes(zone: list[dict]) -> list[dict]:
    """구간에서 PER_ZONE 화까지: 화 카드의 성격이 있으면 흔한 성격부터 성격마다 하나(구간을 셋으로 나눈 자리에 가까운 화),
    남는 자리는 대사 비율이 가장 낮은 화 · 가운데인 화 · 가장 높은 화 차례로 채운다."""
    if len(zone) <= PER_ZONE:
        return list(zone)
    mid = (len(zone) - 1) / 2
    near = sorted(range(len(zone)), key=lambda i: abs(i - mid))
    chosen: list[int] = []
    kinds: dict[str, int] = {}
    for e in zone:
        if e.get("kind"):
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    for k, kind in enumerate(sorted(kinds, key=lambda x: -kinds[x])):
        if len(chosen) >= PER_ZONE:
            break
        # 고른 화가 구간 한가운데에 몰리지 않게, k 번째 성격은 구간의 k 번째 자리에 가까운 화에서 찾는다
        spot = (len(zone) - 1) * (k + 0.5) / PER_ZONE
        chosen.append(min((i for i in range(len(zone)) if zone[i].get("kind") == kind and i not in chosen), key=lambda i: abs(i - spot)))
    by_talk = sorted(range(len(zone)), key=lambda i: zone[i].get("dialogue", 0.0))
    for i in (by_talk[0], by_talk[len(by_talk) // 2], by_talk[-1], *near):
        if len(chosen) >= PER_ZONE:
            break
        if i not in chosen:
            chosen.append(i)
    return [zone[i] for i in sorted(chosen)]


def spread(chosen: list[dict], budget: int) -> dict:
    """chosen: [{order, label, text, kind?, dialogue?}] (원고 차례). 합이 budget 을 넘으면 구간마다 화를 골라 조각을 뽑는다.
    돌려주는 값: {text 보낼 글, pieces [{order, label, part, chars}], spread 흩어 뽑았는지, chars 고른 화의 글자 수, episodes 조각을 뽑은 화 수}."""
    total = sum(len(c["text"]) for c in chosen) + 2 * max(0, len(chosen) - 1)
    if total <= budget:
        return {"text": "\n\n".join(c["text"] for c in chosen).strip(), "spread": False, "chars": total, "episodes": len(chosen),
                "pieces": [{"order": c["order"], "label": c.get("label", ""), "part": "all", "chars": len(c["text"])} for c in chosen]}
    picked = [e for z in _zones(chosen) for e in pick_episodes(z)]
    quota = max(PIECE_MIN * 2, (budget - len(SEP) * len(picked) * len(PARTS)) // len(picked))
    parts: list[str] = []
    meta: list[dict] = []
    for e in picked:
        for p in pieces_of(e["text"], quota):
            parts.append(p["text"])
            meta.append({"order": e["order"], "label": e.get("label", ""), "part": p["part"], "chars": len(p["text"])})
    text = SEP.join(parts)
    while len(text) > budget and len(parts) > 1:  # 어림이 넘쳤으면 끝 조각부터 뺀다
        parts.pop()
        meta.pop()
        text = SEP.join(parts)
    return {"text": text[:budget].strip(), "spread": True, "chars": total, "episodes": len(picked), "pieces": meta}


def zone_rates(texts: list[str], markers: list[str]) -> list[dict]:
    """표지마다 구간별 빈도 [{text, rates, counts}]. texts 는 원고 차례의 화 글, 구간은 spread 와 같게 화 수로 ZONES 등분한다.
    AI 없이 센다 (metrics.marker_count). 화가 ZONES 보다 적거나 ZONE_MIN 자보다 짧은 구간이 있으면 빈 목록."""
    if len(texts) < ZONES:
        return []
    zones = ["\n\n".join(z) for z in _zones(texts)]
    if min(len(z) for z in zones) < ZONE_MIN:
        return []
    out = []
    for m in dict.fromkeys(markers):
        counts = [metrics.marker_count(z, m) for z in zones]
        out.append({"text": m, "counts": counts, "rates": [round(c * 1000 / len(z), 4) for c, z in zip(counts, zones)]})  # 화면은 소수 둘째 자리까지 보이고, 견줄 때는 반올림 전 값에 가깝게 쓴다
    return out
