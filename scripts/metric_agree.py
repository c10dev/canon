"""벤치마크 6단계 지표 검증: 문체 지표가 짝마다 고른 쪽이 작가의 선택(판별 묶음은 정답도)과 얼마나 맞는지 잰다.

결과를 연 가려 읽기 묶음(나란히 읽기 side, 판별 ident)의 짝마다, 미리 방향을 정한 지표가 고른 쪽을 작가가 고른 쪽과 견준다.
일치율 · Wilson 구간 · 작품 묶음 부트스트랩 구간 · 기준선(우연 · 길이 · 다수결) 대비 McNemar p 를 찍는다.

실행 (Canon 작업 폴더. CANON_HOME 이 묶음과 레퍼런스 원고를 가리킨다. 저장 폴더를 읽기만 하고 LLM 도 네트워크도 쓰지 않는다):
  python scripts/metric_agree.py groups SET_ID [SET_ID ...] [--refs RID ...]
  python scripts/metric_agree.py run SET_ID [SET_ID ...] [--refs RID ...] [--held W2 ...] [--json] [--out FILE]
  python scripts/metric_agree.py pairs PAIRS.json [PAIRS.json ...] [--json] [--out FILE]
pairs 는 blind_scene_pairs.py pairs 가 쓴 짝 파일을 바로 잰다. 첫 파일이 기준 판이다.
groups 는 작품 묶음별 짝 수만 찍는다. 지표 값을 보기 전에 --held 로 보류할 묶음을 고르는 데 쓴다.
판별 묶음은 차이의 크기(쪽별 중앙값 · 사분위 · 짝 안 차이 · 레퍼런스 쪽 가운데 50% 범위 안에 든 비율)도 찍는다.
값은 모두 모듈 맨 위 상수로 못 박았고 명령줄로 바꾸지 않는다.
출력에 판 이름 · 대목 이름 · 원고 id · 글 본문을 찍지 않는다. 작품 묶음은 W1, W2 … 라벨로만 찍는다.
시험은 tests/test_metric_agree.py (지어낸 글과 지어낸 묶음).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import blindset, blindstats, labstats, metrics, refs  # noqa: E402

SEED = 20261117
BOOT = 2000                      # labstats.cluster_boot 반복
WINDOW = 30                      # 원고 찾기: 공백을 뺀 글의 30자 창
PROBES = 5                       # 글 하나에서 고르게 뽑는 창 수
MIN_HITS = 3                     # 창 다섯 중 셋 이상이 한 원고의 한 화에 들면 그 화로 본다
# 지표 이름 -> 방향. "low" 는 값이 작은 쪽을, "high" 는 큰 쪽을 '레퍼런스다운 쪽 = 나은 쪽'으로 고른다.
# 방향은 결과를 보기 전에 정했다: 근거는 metrics.EMOTION_WORDS · BODY_WORDS 주석, 문체 거리는 작을수록 기준 원고에 가깝다.
METRICS = {"body_per_1k": "low", "emotion_per_1k": "high", "style_distance": "low"}
MODES = ("side", "ident")
LENGTH_NOTE = "판별 묶음은 길이를 ±3%로 맞췄어요. 길이 기준선은 정보가 거의 없어요"
MAJORITY_NOTE = "정답 판을 늘 고르는 규칙은 정답을 쓰므로 뜻이 없어서 내지 않아요"
DIFFER_MIN = 0.3                 # 작가가 틀린 짝이 n 의 이 몫 미만이면 두 과녁이 거의 갈리지 않는다는 경고
UNVERIFIED = ("emotion_per_1k",)
UNVERIFIED_NOTE = "6단계 검증에서 정답 쪽을 우연보다 낫게 고르지 못한 지표예요. 크기는 참고로만 봐요"


@dataclass
class Unit:
    set_id: str
    mode: str            # "side" | "ident"
    a_text: str          # 쌍의 a 글
    b_text: str          # 쌍의 b 글
    a_arm: str           # 내부에서만 씀. 출력 금지
    b_arm: str
    pick_a: bool         # 작가가 a 를 골랐나
    truth_a: bool | None # ident: 정답(레퍼런스)이 a 인가. side: None
    group: str = ""      # 작품 묶음 키. 출력에는 라벨 W1.. 만
    values: dict = field(default_factory=dict)  # 지표 이름 -> (a 값, b 값). 내부에서만 씀. 출력 금지


# ---------- 묶음 받기 ----------

def load_sets(ids: list[str]) -> list:
    sets = []
    for sid in ids:
        try:
            s = blindset.load(sid)
        except KeyError as e:
            raise SystemExit(str(e)) from None
        if not s.revealed_at:
            raise SystemExit("결과를 열지 않은 묶음은 잴 수 없어요")
        if s.mode not in MODES:
            raise SystemExit("나란히 읽기나 판별 묶음만 잴 수 있어요")
        sets.append(s)
    seen: list[set[str]] = []
    for s in sets:
        texts = {x.text.strip() for x in s.items}
        if any(texts & other for other in seen):
            raise SystemExit("본문이 같은 글을 함께 가진 묶음 둘은 같이 잴 수 없어요")
        seen.append(texts)
    return sets


def _unit(s, d: dict, text: dict, arm: dict, piece: dict) -> Unit | None:
    a, b = d["a"], d["b"]
    if d["pick"] not in (a, b):
        return None
    truth = None
    if s.mode == "ident":
        is_ans = (arm.get(a) == s.answer_arm, arm.get(b) == s.answer_arm)
        if is_ans[0] == is_ans[1]:
            return None
        truth = is_ans[0]
    return Unit(s.id, s.mode, text[a], text[b], arm.get(a, ""), arm.get(b, ""), d["pick"] == a, truth, f"{s.id}:{piece.get(a, '')}")


def units_of(s) -> tuple[list[Unit], int, int]:
    """(짝 목록, 무승부 수, 뺀 수). 묶음마다 첫 답만 쓴다."""
    groups, _ = blindstats._groups(s)
    text = {x.no: x.text for x in s.items}
    arm = {k.no: k.arm for k in s.key}
    piece = {k.no: k.piece for k in s.key}
    units, ties, skipped = [], 0, 0
    for g in groups:
        d = g[0]
        if s.mode == "side" and d["pick"] == blindset.TIE:
            ties += 1
            continue
        u = _unit(s, d, text, arm, piece)
        if u is None:
            skipped += 1
        else:
            units.append(u)
    return units, ties, skipped


# ---------- 작품 묶음 ----------

def _flat(text: str) -> str:
    return re.sub(r"\s+", "", text)


def locate(text: str, flats: dict[str, dict[int, str]]) -> tuple[str, int] | None:
    """글이 어느 원고의 어느 화에서 왔는지. 창 PROBES 곳 가운데 MIN_HITS 이상 든 (rid, 화)가 정확히 하나일 때만 돌려준다."""
    flat = _flat(text)
    if len(flat) < WINDOW:
        return None
    hits: Counter = Counter()
    span = len(flat) - WINDOW
    for i in range(PROBES):
        win = flat[span * i // (PROBES - 1):][:WINDOW]
        for rid, eps in flats.items():
            for ep, body in eps.items():
                if win in body:
                    hits[(rid, ep)] += 1
    full = [k for k, v in hits.items() if v >= MIN_HITS]
    return full[0] if len(full) == 1 else None


def _ref_flats(rids: list[str]) -> dict[str, dict[int, str]]:
    out = {}
    for rid in rids:
        t = refs.texts(rid)
        if t is None:
            raise SystemExit("레퍼런스 원고를 찾을 수 없어요")
        out[rid] = {ep: _flat(body) for ep, body in t.items()}
    return out


def assign_groups(units: list[Unit], rids: list[str]) -> tuple[dict[str, str], dict[str, set[int]]]:
    """짝마다 묶음 키를 정한다. (키 -> 라벨 W1.., 원고 id -> 글이 나온 화 집합)을 돌려준다."""
    found: dict[str, set[int]] = {}
    flats = _ref_flats(rids) if rids else {}
    for u in units:
        locs = [x for x in (locate(u.a_text, flats), locate(u.b_text, flats)) if x] if flats else []
        if len({rid for rid, _ in locs}) > 1:
            raise SystemExit("짝의 두 글이 서로 다른 원고에서 나왔어요")
        if locs:
            u.group = locs[0][0]
            for rid, ep in locs:
                found.setdefault(rid, set()).add(ep)
    keys = sorted({u.group for u in units}, key=lambda k: hashlib.sha256((str(SEED) + k).encode()).hexdigest())
    return {k: f"W{i + 1}" for i, k in enumerate(keys)}, found


def reference_eps(texts: dict[int, str], skip: set[int]) -> list[int]:
    """문체 거리 기준값에 쓰는 화 차례: 글이 나온 화를 뺀 모든 화."""
    return [ep for ep in sorted(texts) if ep not in skip]


def reference_metrics(found: dict[str, set[int]]) -> dict[str, metrics.StyleMetrics]:
    out = {}
    for rid, skip in found.items():
        texts = refs.texts(rid) or {}
        out[rid] = metrics.measure("\n\n".join(texts[ep] for ep in reference_eps(texts, skip)))
    return out


# ---------- 지표 재기 ----------

def choose(va: float | None, vb: float | None, direction: str) -> str:
    """'a' | 'b' | 'equal' | 'missing'."""
    if va is None or vb is None:
        return "missing"
    if va == vb:
        return "equal"
    return "a" if (va < vb) == (direction == "low") else "b"


def unit_values(u: Unit, bases: dict[str, metrics.StyleMetrics]) -> dict[str, tuple[float | None, float | None]]:
    """지표마다 (a 글 값, b 글 값). style_distance 는 그 작품 묶음의 기준값이 없으면 (None, None)."""
    out = {}
    for name in METRICS:
        if name == "style_distance":
            base = bases.get(u.group)
            out[name] = (metrics.style_distance(base, u.a_text), metrics.style_distance(base, u.b_text)) if base else (None, None)
        else:
            fn = getattr(metrics, name)
            out[name] = (fn(u.a_text), fn(u.b_text))
    return out


def measure_unit(u: Unit, bases: dict[str, metrics.StyleMetrics]) -> dict[str, str]:
    vals = unit_values(u, bases)
    return {name: choose(*vals[name], direction) for name, direction in METRICS.items()}


def _quart(xs: list[float]) -> dict:
    return {"median": round(labstats.percentile(xs, 0.5), 4), "q1": round(labstats.percentile(xs, 0.25), 4),
            "q3": round(labstats.percentile(xs, 0.75), 4)}


def gap_sizes(pairs: list[tuple[float | None, float | None]]) -> dict | None:
    """pairs 는 짝마다 (정답 쪽 값, 다른 쪽 값). 둘 중 하나라도 None 인 짝은 뺀다. 남은 짝이 0이면 None."""
    ok = [(r, o) for r, o in pairs if r is not None and o is not None]
    if not ok:
        return None
    ref, other = _quart([r for r, _ in ok]), _quart([o for _, o in ok])
    inside = sum(ref["q1"] <= o <= ref["q3"] for _, o in ok)
    return {"n": len(ok), "ref": ref, "other": other,
            "diff_median": round(labstats.percentile([o - r for r, o in ok], 0.5), 4),
            "in_ref_iqr": inside, "in_ref_iqr_rate": round(inside / len(ok), 4)}


def sizes_for(units: list[Unit]) -> dict[str, dict | None]:
    """판별 짝만. 지표마다 gap_sizes. 정답 쪽 = truth_a 면 a 값, 아니면 b 값."""
    ident = [u for u in units if u.truth_a is not None]
    out: dict[str, dict | None] = {}
    for name in METRICS:
        pairs = []
        for u in ident:
            va, vb = u.values[name]
            pairs.append((va, vb) if u.truth_a else (vb, va))
        res = gap_sizes(pairs)
        if res is not None and name in UNVERIFIED:
            res["note"] = UNVERIFIED_NOTE
        out[name] = res
    return out


# ---------- 기준선 ----------

def target_a(u: Unit, target: str) -> bool | None:
    return u.pick_a if target == "author" else u.truth_a


Rule = Callable[[Unit], "bool | None"]  # 규칙이 고른 쪽이 a 인가. 고르지 못하면 None(불일치)


def _hit(rule: Rule, u: Unit, target: str) -> bool:
    side = rule(u)
    return side is not None and side == target_a(u, target)


def _length_rule(longer: bool) -> Rule:
    def rule(u: Unit) -> bool | None:
        la, lb = len(u.a_text.strip()), len(u.b_text.strip())
        return None if la == lb else (la > lb) == longer
    return rule


def _arm_majority(dev: list[Unit]) -> Rule:
    wins: Counter = Counter()
    seen: set = set()
    for u in dev:
        seen.add(frozenset((u.a_arm, u.b_arm)))
        wins[u.a_arm if u.pick_a else u.b_arm] += 1

    def rule(u: Unit) -> bool | None:
        if u.a_arm == u.b_arm or frozenset((u.a_arm, u.b_arm)) not in seen:
            return None
        best = max(sorted((u.a_arm, u.b_arm)), key=lambda x: wins[x])
        return u.a_arm == best
    return rule


def baselines_for(dev: list[Unit], mode: str, target: str) -> dict:
    """개발 짝으로 정한 기준선 규칙. {'length': (이름, 규칙), 'majority': (이름, 규칙) | None}."""
    longer = sum(_hit(_length_rule(True), u, target) for u in dev)
    shorter = sum(_hit(_length_rule(False), u, target) for u in dev)
    is_longer = longer > shorter
    out: dict = {"length": ("longer" if is_longer else "shorter", _length_rule(is_longer))}
    if mode == "side":
        out["majority"] = ("arm_majority", _arm_majority(dev))
    elif target == "author":
        left = sum(u.pick_a for u in dev)
        use_a = left >= len(dev) - left
        out["majority"] = ("always_a" if use_a else "always_b", lambda u, use_a=use_a: use_a)
    else:
        out["majority"] = None
    return out


# ---------- 통계 ----------

def mcnemar(flags: list[tuple[bool, bool]]) -> dict:
    """flags 는 짝마다 (지표 일치, 기준선 일치). 지표만 맞음 b, 기준선만 맞음 c."""
    b = sum(m and not r for m, r in flags)
    c = sum(r and not m for m, r in flags)
    return {"baseline_agree": sum(r for _, r in flags), "b": b, "c": c, "p": labstats.sign_test(b, b + c) if b + c else 1.0}


def _boot95(by_group: dict[str, list[int]]) -> list[float] | None:
    if len(by_group) < 2:
        return None
    dist = labstats.cluster_boot(by_group, lambda xs: sum(xs) / len(xs) if xs else None, n=BOOT, seed=SEED)
    if not dist:
        return None
    return [round(labstats.percentile(dist, q), 4) for q in (0.025, 0.975)]


def agreement(used: list[tuple[Unit, bool]]) -> dict:
    n, k = len(used), sum(ok for _, ok in used)
    by_group: dict[str, list[int]] = {}
    for u, ok in used:
        by_group.setdefault(u.group, []).append(int(ok))
    lo, hi = labstats.wilson(k, n)
    return {"n": n, "agree": k, "rate": round(k / n, 4) if n else None, "wilson95": [round(lo, 4), round(hi, 4)] if n else None,
            "boot95": _boot95(by_group), "p_chance": labstats.sign_test(k, n)}


def _versus(used: list[tuple[Unit, bool]], rule: tuple[str, Rule] | None, target: str) -> dict | None:
    if rule is None:
        return None
    flags = [(ok, _hit(rule[1], u, target)) for u, ok in used]
    return {"rule": rule[0], **mcnemar(flags)}


def summarize(rows: list[tuple[Unit, dict[str, str]]], target: str, rules: dict) -> dict:
    out = {}
    for name in METRICS:
        used = [(u, (c[name] == "a") == target_a(u, target)) for u, c in rows if c[name] in ("a", "b")]
        stat = agreement(used)
        stat["missing"] = sum(c[name] == "missing" for _, c in rows)
        stat["equal"] = sum(c[name] == "equal" for _, c in rows)
        stat["vs_length"] = _versus(used, rules["length"], target)
        stat["vs_majority"] = _versus(used, rules["majority"], target)
        if rules["majority"] is None:
            stat["vs_majority_note"] = MAJORITY_NOTE
        out[name] = stat
    return out


# ---------- 범위 · 결과 ----------

def _entry(rows: list, dev: list[Unit], mode: str, target: str, warnings: list[str], scope: str) -> dict:
    mine = [(u, c) for u, c in rows if u.mode == mode]
    rules = baselines_for([u for u in dev if u.mode == mode], mode, target)
    entry = {"mode": mode, "target": target, "n_units": len(mine), "metrics": summarize(mine, target, rules)}
    if mode == "ident":
        entry["length_note"] = LENGTH_NOTE
        differ = sum(u.pick_a != u.truth_a for u, _ in mine)
        entry["author_vs_truth_differ"] = differ
        if target == "truth":
            entry["sizes"] = sizes_for([u for u, _ in mine])
        if target == "author" and mine and differ < DIFFER_MIN * len(mine):
            warnings.append(f"{scope}: 작가가 정답과 다르게 고른 짝이 {len(mine)}쌍 중 {differ}쌍뿐이라 두 과녁이 거의 갈리지 않아요")
    return entry


def _scope(rows: list, dev: list[Unit], scope: str, warnings: list[str]) -> dict:
    out = {}
    for mode, targets in (("side", ("author",)), ("ident", ("truth", "author"))):
        if not any(u.mode == mode for u, _ in rows):
            continue
        for target in targets:
            out[f"{mode}/{target}"] = _entry(rows, dev, mode, target, warnings, scope)
    n_groups = len({u.group for u, _ in rows})
    if n_groups < 3:
        warnings.append(f"{scope}: 작품 묶음이 {n_groups}개뿐이라 구간이 좁게 나와요")
    return out


def _scopes(rows: list, held_keys: set[str], held: list[str], warnings: list[str]) -> dict:
    if not held:
        warnings.append("기준선 규칙을 같은 짝에서 정해 기준선이 유리해요")
        return {"all": (rows, [u for u, _ in rows])}
    dev_rows = [(u, c) for u, c in rows if u.group not in held_keys]
    dev = [u for u, _ in dev_rows]
    return {"all": (rows, dev), "dev": (dev_rows, dev), "held": ([(u, c) for u, c in rows if u.group in held_keys], dev)}


def run(ids: list[str], rids: list[str], held: list[str]) -> dict:
    parts = [(s, *units_of(s)) for s in load_sets(ids)]
    units = [u for _, us, _, _ in parts for u in us]
    labels, found = assign_groups(units, rids)
    if any(h not in labels.values() for h in held):
        raise SystemExit("없는 작품 묶음 라벨이에요")
    bases = reference_metrics(found)
    rows = []
    for u in units:
        u.values = unit_values(u, bases)
        rows.append((u, {name: choose(*u.values[name], d) for name, d in METRICS.items()}))
    warnings: list[str] = []
    scopes = _scopes(rows, {k for k, v in labels.items() if v in held}, held, warnings)
    counts = Counter(u.group for u in units)
    return {
        "sets": [{"id": s.id, "mode": s.mode, "units": len(us), "ties": ties, "skipped": skipped} for s, us, ties, skipped in parts],
        "groups": {labels[k]: counts[k] for k in sorted(counts, key=lambda k: int(labels[k][1:]))},
        "metrics": dict(METRICS),
        "split": "held" if held else "none",
        "warnings": warnings,
        "results": {name: _scope(r, d, name, warnings) for name, (r, d) in scopes.items()},
    }


def group_counts(ids: list[str], rids: list[str]) -> list[tuple[str, int]]:
    units = [u for s in load_sets(ids) for u in units_of(s)[0]]
    labels, _ = assign_groups(units, rids)
    counts = Counter(labels[u.group] for u in units)
    return sorted(counts.items(), key=lambda kv: int(kv[0][1:]))


# ---------- 출력 ----------

def _fmt(x) -> str:
    return "-" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))


def _line(name: str, st: dict) -> str:
    vl, vm = st["vs_length"], st["vs_majority"]
    ci = st["boot95"] or st["wilson95"]
    span = f"{_fmt(ci[0])}~{_fmt(ci[1])}" if ci else "-"
    return (f"  {name:<15} n={st['n']:<3} 일치={st['agree']:<3} 일치율={_fmt(st['rate'])} 구간={span} "
            f"p우연={_fmt(st['p_chance'])} p길이={_fmt(vl['p'] if vl else None)} p다수결={_fmt(vm['p'] if vm else None)} "
            f"없음={st['missing']} 같음={st['equal']}")


def _size_lines(sizes: dict) -> list[str]:
    lines, noted = [], False
    for name, sz in sizes.items():
        if sz is None:
            lines.append(f"  크기 {name} -")
            continue
        r, o = sz["ref"], sz["other"]
        mark = " (참고)" if "note" in sz else ""
        noted = noted or bool(mark)
        lines.append(f"  크기 {name:<15} n={sz['n']} 정답쪽 {_fmt(r['median'])} ({_fmt(r['q1'])}~{_fmt(r['q3'])}) "
                     f"다른쪽 {_fmt(o['median'])} ({_fmt(o['q1'])}~{_fmt(o['q3'])}) "
                     f"짝차 {_fmt(sz['diff_median'])} 범위안 {sz['in_ref_iqr']}/{sz['n']}{mark}")
    if noted:
        lines.append(f"  {UNVERIFIED_NOTE}")
    return lines


def render(res: dict) -> str:
    lines = ["묶음: " + ", ".join(f"{s['id']}({s['mode']}) 짝 {s['units']} 무승부 {s['ties']} 뺌 {s['skipped']}" for s in res["sets"])]
    lines.append("작품 묶음: " + ", ".join(f"{k} {v}" for k, v in res["groups"].items()))
    lines.append("지표 방향: " + ", ".join(f"{k} {v}" for k, v in res["metrics"].items()))
    lines.append(f"분할: {res['split']}")
    for scope, entries in res["results"].items():
        for key, e in entries.items():
            lines.append(f"[{scope}] {key} (짝 {e['n_units']})")
            lines.extend(_line(name, st) for name, st in e["metrics"].items())
            if "length_note" in e:
                lines.append(f"  {e['length_note']}. 작가가 정답과 다른 짝 {e['author_vs_truth_differ']}")
            if "sizes" in e:
                lines.extend(_size_lines(e["sizes"]))
    lines.extend(f"경고: {w}" for w in res["warnings"])
    return "\n".join(lines)


# ---------- 짝 파일 ----------

PAIR_KEYS = ("ref", "base", "rid", "order")


def load_pair_file(path: str) -> list[dict]:
    """짝 목록을 읽는다. 목록이 아니거나 'ref' · 'base' · 'rid' · 'order' 가 빠진 항목이 있으면 멈춘다."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit("짝 파일 형식이 아니에요") from None
    if not isinstance(data, list) or any(not isinstance(p, dict) or any(k not in p for k in PAIR_KEYS) for p in data):
        raise SystemExit("짝 파일 형식이 아니에요")
    return data


def pair_values(pair: dict, bases: dict[str, metrics.StyleMetrics]) -> dict[str, tuple[float | None, float | None]]:
    """지표마다 (ref 글 값, base 글 값). style_distance 는 그 원고의 기준값이 없으면 (None, None)."""
    out = {}
    for name in METRICS:
        if name == "style_distance":
            base = bases.get(pair["rid"])
            out[name] = (metrics.style_distance(base, pair["ref"]), metrics.style_distance(base, pair["base"])) if base else (None, None)
        else:
            fn = getattr(metrics, name)
            out[name] = (fn(pair["ref"]), fn(pair["base"]))
    return out


def _pair_bases(pairs: list[dict]) -> dict[str, metrics.StyleMetrics]:
    """원고마다 문체 거리 기준값. ref 글이 나온 화를 빼고 나머지 화 전체를 잰다. 원고를 못 찾으면 기준값 없이 둔다."""
    flats: dict[str, dict[int, str]] = {}
    for rid in sorted({p["rid"] for p in pairs}):
        t = refs.texts(rid)
        if t is not None:
            flats[rid] = {ep: _flat(body) for ep, body in t.items()}
    found: dict[str, set[int]] = {rid: set() for rid in flats}
    for p in pairs:
        loc = locate(p["ref"], {p["rid"]: flats[p["rid"]]}) if p["rid"] in flats else None
        if loc:
            found[loc[0]].add(loc[1])
    return reference_metrics(found)


def _median(xs: list[float]) -> float | None:
    return round(labstats.percentile(xs, 0.5), 4) if xs else None


def file_summary(pairs: list[dict], bases) -> dict:
    ratios = [len(p["base"].strip()) / len(p["ref"].strip()) for p in pairs if p["ref"].strip()]
    vals = [pair_values(p, bases) for p in pairs]
    sizes: dict[str, dict | None] = {}
    for name in METRICS:
        res = gap_sizes([v[name] for v in vals])
        if res is not None and name in UNVERIFIED:
            res["note"] = UNVERIFIED_NOTE
        sizes[name] = res
    return {"n": len(pairs), "length_ratio_median": _median(ratios), "sizes": sizes}


def _tally(rows: list[tuple[float | None, float | None]], direction: str) -> dict:
    """rows 는 공통 대목마다 (첫 파일 base 값, 이 파일 base 값)."""
    out = {"better": 0, "worse": 0, "equal": 0, "missing": 0}
    for first, cand in rows:
        c = choose(cand, first, direction)
        out[{"a": "better", "b": "worse"}.get(c, c)] += 1
    ok = [(f, c) for f, c in rows if f is not None and c is not None]
    out["base_median"] = _median([f for f, _ in ok])
    out["cand_median"] = _median([c for _, c in ok])
    return out


def compare_files(per_file: list[dict[tuple, dict]]) -> list[dict]:
    """두 번째 파일부터 첫 파일과 같은 대목끼리 견준다. 방향은 METRICS 를 따른다."""
    first = per_file[0]
    out = []
    for other in per_file[1:]:
        keys = [k for k in first if k in other]
        entry: dict = {"common": len(keys)}
        for name, direction in METRICS.items():
            entry[name] = _tally([(first[k][name][1], other[k][name][1]) for k in keys], direction)
        out.append(entry)
    return out


def _dedupe(pairs: list[dict]) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for p in pairs:
        out.setdefault((p["rid"], p["order"]), p)
    return out


def _group_labels(rids: list[str]) -> dict[str, str]:
    keys = sorted(set(rids), key=lambda k: hashlib.sha256((str(SEED) + k).encode()).hexdigest())
    return {k: f"W{i + 1}" for i, k in enumerate(keys)}


def run_pairs(files: list[str]) -> dict:
    loaded = [list(_dedupe(load_pair_file(f)).values()) for f in files]
    bases = _pair_bases([p for pairs in loaded for p in pairs])
    summaries = [file_summary(pairs, bases) for pairs in loaded]
    per_file = [{(p["rid"], p["order"]): pair_values(p, bases) for p in pairs} for pairs in loaded]
    labels = _group_labels([p["rid"] for p in loaded[0]])
    counts = Counter(labels[p["rid"]] for p in loaded[0])
    cmp_ = compare_files(per_file)
    return {
        "files": [{"label": f"F{i + 1}", "path": f, **sm} for i, (f, sm) in enumerate(zip(files, summaries))],
        "groups": {k: counts[k] for k in sorted(counts, key=lambda k: int(k[1:]))},
        "compare": [{"label": f"F{i + 2}", **c} for i, c in enumerate(cmp_)],
        "metrics": dict(METRICS),
    }


def render_pairs(res: dict) -> str:
    lines = ["작품 묶음: " + ", ".join(f"{k} {v}" for k, v in res["groups"].items())]
    lines.append("지표 방향: " + ", ".join(f"{k} {v}" for k, v in res["metrics"].items()))
    for f in res["files"]:
        lines.append(f"{f['label']} {f['path']} 짝 {f['n']} 길이비 중앙 {_fmt(f['length_ratio_median'])}")
        lines.extend(_size_lines(f["sizes"]))
    for c in res["compare"]:
        lines.append(f"{c['label']} 대 F1 공통 대목 {c['common']}")
        for name in res["metrics"]:
            t = c[name]
            lines.append(f"  {c['label']} 대 F1 {name} 나음 {t['better']} 나쁨 {t['worse']} 같음 {t['equal']} 없음 {t['missing']} "
                         f"중앙 {_fmt(t['base_median'])} -> {_fmt(t['cand_median'])}")
    return "\n".join(lines)


def _main_pairs(a) -> int:
    res = run_pairs(a.files)
    dump = json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(dump + "\n", encoding="utf-8")
    print(dump if a.json else render_pairs(res))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("groups", "run"):
        p = sub.add_parser(name)
        p.add_argument("sets", nargs="+")
        p.add_argument("--refs", nargs="*", default=[])
        if name == "run":
            p.add_argument("--held", nargs="*", default=[])
            p.add_argument("--json", action="store_true")
            p.add_argument("--out")
    pp = sub.add_parser("pairs")
    pp.add_argument("files", nargs="+")
    pp.add_argument("--json", action="store_true")
    pp.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "pairs":
        return _main_pairs(a)
    if a.cmd == "groups":
        for label, n in group_counts(a.sets, a.refs):
            print(label, n)
        return 0
    res = run(a.sets, a.refs, a.held)
    dump = json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(dump + "\n", encoding="utf-8")
    print(dump if a.json else render(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
