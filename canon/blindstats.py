"""가려 읽기 묶음의 쌍 비교 통계: 판 짝마다 승률 · 구간 · 비김 · 다시 물은 쌍의 일치 · 같은 조건 짝의 잡음 기준선.

읽기만 하고 저장하지 않는다. 결과에 판 이름이 실리므로 결과를 연 묶음에만 부른다(부르는 쪽이 확인한다).
묶음을 세는 방식은 blindset.duel_result 와 같다: 글자가 같은 두 글의 쌍은 한 묶음이고, 묶음의 첫 답만 센다.
"""
from __future__ import annotations

from typing import Sequence

from . import blindset, labstats
from .schema import BlindSet

N_MARKS = (37, 69)  # 승률 0.70 · 0.65 를 우연(0.5)과 가르는 데 드는 쌍 수 (이항 계산, 단측 α 0.05 · 검정력 0.8)


def _outcome(d: dict, text: dict[str, str], first: dict) -> str:
    """답 하나를 첫 답의 a 글 쪽에서 본 결과로 바꾼다: win / loss / tie."""
    if d["pick"] == blindset.TIE:
        return "tie"
    return "win" if text[d["pick"]] == text[first["a"]] else "loss"


def _groups(s: BlindSet) -> tuple[list[dict], int]:
    """(답이 있는 쌍 목록, 전체 쌍 수). 글자가 같은 두 글의 쌍끼리 한 묶음으로 모은다."""
    asked = blindset.duels(s)
    text = {x.no: x.text for x in s.items}
    by: dict[frozenset, list[dict]] = {}
    for d in asked:
        if d["pick"]:
            by.setdefault(frozenset((text[d["a"]], text[d["b"]])), []).append(d)
    return list(by.values()), len(asked)


def _row(group: list[dict], s: BlindSet, text: dict[str, str]) -> dict | None:
    """묶음 하나를 판 이름 차례(a < b)로 맞춘 한 줄로 바꾼다. 판 이름이 없거나 같으면 None."""
    arm = {k.no: k.arm for k in s.key}
    piece = {k.no: k.piece for k in s.key}
    d0 = group[0]
    x, y = d0["a"], d0["b"]
    if not arm.get(x) or not arm.get(y) or arm[x] == arm[y]:
        return None
    if arm[x] > arm[y]:
        x, y = y, x
    outs = [_outcome(d, text, d0) for d in group]
    if text[x] != text[d0["a"]]:  # 판 이름 차례로 바꾸면 이김과 짐이 뒤집힌다
        outs = [{"win": "loss", "loss": "win"}.get(o, o) for o in outs]
    return {"a": arm[x], "b": arm[y], "piece": piece.get(x, ""), "outs": outs}


def _pair_line(a: str, b: str, rows: list[dict], null: bool) -> dict:
    win = sum(r["outs"][0] == "win" for r in rows)
    loss = sum(r["outs"][0] == "loss" for r in rows)
    tie = sum(r["outs"][0] == "tie" for r in rows)
    n = win + loss
    lo, hi = labstats.wilson(win, n)
    return {"a": a, "b": b, "win": win, "loss": loss, "tie": tie, "n": n, "rate": win / n if n else None,
            "wilson": [lo, hi], "boot": _boot(rows), "p": labstats.sign_test(win, n),
            "tie_rate": tie / (n + tie) if n + tie else None, "null": null,
            "short_of": next((m for m in sorted(N_MARKS) if m > n), None)}


def _boot(rows: list[dict]) -> list[float] | None:
    """대목으로 묶은 부트스트랩 95% 구간. 대목이 둘 미만이면 None. 비김은 뺀다."""
    groups: dict[str, list[float]] = {}
    for r in rows:
        if r["outs"][0] != "tie":
            groups.setdefault(r["piece"], []).append(1.0 if r["outs"][0] == "win" else 0.0)
    if len(groups) < 2:
        return None
    dist = labstats.cluster_boot(groups, lambda xs: sum(xs) / len(xs) if xs else None)
    if not dist:
        return None
    lo, hi = labstats.interval(dist, 0.95)
    return [lo, hi]


def _arms(pairs: list[dict]) -> list[dict]:
    tally: dict[str, list[int]] = {}
    for p in pairs:
        if p["null"]:
            continue
        for arm, w, l in ((p["a"], p["win"], p["loss"]), (p["b"], p["loss"], p["win"])):
            t = tally.setdefault(arm, [0, 0, 0])
            t[0] += w
            t[1] += l
            t[2] += p["tie"]
    out = []
    for arm, (w, l, t) in tally.items():
        n = w + l
        lo, hi = labstats.wilson(w, n)
        out.append({"arm": arm, "win": w, "loss": l, "tie": t, "n": n, "rate": w / n if n else None,
                    "wilson": [lo, hi], "tie_rate": t / (n + t) if n + t else None})
    return sorted(out, key=lambda r: (r["rate"] is None, -(r["rate"] or 0), r["arm"]))


def _repeat(repeats: list[list[str]]) -> dict | None:
    of = sum(len(o) - 1 for o in repeats)
    if not of:
        return None
    same = sum(x == y for o in repeats for x, y in zip(o, o[1:]))
    return {"same": same, "of": of, "flip_rate": (of - same) / of, "flip_wilson": list(labstats.wilson(of - same, of))}


def _warnings(pairs: list[dict], null_pairs: Sequence[tuple[str, str]], skipped: int) -> list[str]:
    out = [f"{p['a']} 대 {p['b']} 는 {p['n']}쌍이라 {p['short_of']}쌍에 못 미쳐요" for p in pairs if not p["null"] and p["short_of"]]
    seen = {frozenset((p["a"], p["b"])) for p in pairs}
    for a, b in null_pairs:
        if frozenset((a, b)) not in seen:
            out.append(f"같은 조건으로 적은 {a} 대 {b} 는 답이 없어요")
    if skipped:
        out.append(f"판 이름이 없거나 같아 세지 않은 쌍이 {skipped}묶음 있어요")
    return out


def stats(s: BlindSet, null_pairs: Sequence[tuple[str, str]] = ()) -> dict:
    """쌍 비교 답의 통계. 판 이름을 담으므로 결과를 연 묶음에만 부른다(부르는 쪽이 확인한다)."""
    text = {x.no: x.text for x in s.items}
    groups, total = _groups(s)
    nulls = {frozenset(p) for p in null_pairs}
    by_pair: dict[tuple[str, str], list[dict]] = {}
    repeats: list[list[str]] = []
    skipped = 0
    for g in groups:
        row = _row(g, s, text)
        if row is None:
            skipped += 1
            repeats.append([_outcome(d, text, g[0]) for d in g])  # 판 이름이 없어도 다시 물은 쌍의 일치는 센다 (duel_result 와 같게)
            continue
        by_pair.setdefault((row["a"], row["b"]), []).append(row)
        repeats.append(row["outs"])
    pairs = [_pair_line(a, b, rows, frozenset((a, b)) in nulls) for (a, b), rows in by_pair.items()]
    pairs.sort(key=lambda p: (p["null"], -p["n"], p["a"], p["b"]))
    return {"id": s.id, "title": s.title, "mode": s.mode, "total": total, "answered": sum(len(g) for g in groups),
            "skipped": skipped, "pairs": pairs, "arms": _arms(pairs), "repeat": _repeat(repeats),
            "warnings": _warnings(pairs, null_pairs, skipped)}
