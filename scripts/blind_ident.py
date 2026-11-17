"""판별 묶음 만들기: 레퍼런스 대목과 canon 글의 짝 목록 -> 'canon blind import --ident ref' 로 넣을 폴더.

짝 목록(JSON 배열, 원소 하나가 쌍 하나)은 scripts/blind_scene_pairs.py pairs 가 쓴다. 키: ref · base (필수), names · rid · work · order (선택).
이름은 바꾸지 않는다(MASK_NAMES). 같은 자르개(둘째 문단 시작 ~ 마지막 문단 앞의 문장 끝)로 모양을 맞추고, 길이를 TOL 안으로 맞춘다.
이미 읽은 묶음(--exclude-set)과 글이 겹치는 쌍은 뺀다. LLM 도 네트워크도 쓰지 않는다. 값은 모두 모듈 맨 위 상수로 못 박았고 명령줄로 바꾸지 않는다.

실행 (Canon 작업 폴더. CANON_HOME 이 레퍼런스 원고와 묶음을 가리킨다):
  python scripts/blind_ident.py check --pairs A.json [--pairs B.json ...] [--project 작품 ...] [--exclude-set 묶음id ...] [--max-pairs 20]
  python scripts/blind_ident.py build --pairs A.json [...] --out 폴더
  python -m canon blind import 폴더/set1 --ident ref --title "판별 묶음"   # 사람이 넣는다
check 는 아무 파일도 쓰지 않고 요약 JSON 만 찍는다. build 는 --out 폴더가 있고 비어 있지 않으면 멈춘다.
찍는 글에는 본문 · 인물 이름 · 원고 이름을 싣지 않는다. 시험은 tests/test_blind_ident_script.py (지어낸 원고).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import blindset, refdigest, refs, store  # noqa: E402

SEED = 20261116
TOL = 0.03          # 두 글 길이 차 상한: abs(a - b) <= TOL * max(a, b)
MIN_CHARS = 900     # 자른 글이 이보다 짧으면 쓰지 않는다
REPEATS = 3         # 한 번 더 넣는 글 수 (같은 쌍을 다시 묻는 반복 문항)
OVERLAP = 30        # 이미 읽은 묶음과 공백을 뺀 글자가 이만큼 이어서 같으면 겹침
PROBE_STEP = 10     # 겹침을 찾을 때 OVERLAP 자 창을 옮기는 간격
ARMS = ("ref", "base")  # 판 이름. 정답 판은 "ref"
MASK_NAMES = False  # 인물 이름을 대체 이름으로 바꾸지 않는다 (2026-11-17 작가 결정). True 면 이름 원천이 없는 쌍을 빼고 이름을 가린다
SYLLABLES_OPEN = "랴뎌쥬휴슈묘쿠뷔튜퓨켸쵸뮤쇼햐겨셔쟈뉴쿄"  # 받침 없음
SYLLABLES_L = "랄뎔쥘휼슐묠쿨뷜튤퓰켈쵤뮬숄햘겔셜쟐뉼똘"  # ㄹ 받침
SYLLABLES_CLOSED = "쿤뎅쟁휜슌묭뷘튼풍켄쵼뮨숑행룬겸쥰닝랑뎀"  # 그 밖의 받침

_SENT_END = re.compile(r"[.?!…][\"”’」』]?(?=\s|$)")
_PARA = re.compile(r"\n\s*")


def _constants() -> dict:
    return {"SEED": SEED, "TOL": TOL, "MIN_CHARS": MIN_CHARS, "REPEATS": REPEATS, "OVERLAP": OVERLAP, "PROBE_STEP": PROBE_STEP}


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _hangul(c: str) -> bool:
    return "가" <= c <= "힣"


# ---------- 1. 이름 모으기 ----------

def _book_for(pair: dict):
    rid = pair.get("rid")
    if rid:
        try:
            return refs.load(rid)
        except KeyError:
            return None
    work = pair.get("work")
    if not work:
        return None
    for b in refs.entries():
        if work in (_sha(b.id)[:6], _sha(b.name)[:6]):
            return b
    return None


def ref_cast(pair: dict) -> list[str] | None:
    """레퍼런스 대목이 든 화의 화 카드 등장인물. 원고 · 화 · 화 카드를 하나라도 못 찾으면 None."""
    b = _book_for(pair)
    if b is None:
        return None
    needle = _flat(pair["ref"])[:200]
    if not needle:
        return None
    try:
        cards = {x.basis: x.digest.cast for x in refdigest.load(b.id).items}
    except (KeyError, ValueError):
        return None
    for t in refdigest._texts(b):
        if needle in _flat(t["text"]):
            cast = cards.get(t["basis"])
            return None if cast is None else list(cast)
    return None


def project_names(projects: list[str]) -> list[str]:
    """작품의 인물 이름과 다른 이름. 읽기만 한다."""
    out: list[str] = []
    for name in projects:
        for c in store.load(name).characters:
            out += [c.name, *c.aliases]
    return out


def _widen(raw: list[str]) -> list[str]:
    out: list[str] = []
    for n in raw:
        n = (n or "").strip()
        if len(n) < 2:
            continue
        out.append(n)
        if len(n) == 3 and all(_hangul(c) for c in n):
            out.append(n[1:])
    return list(dict.fromkeys(out))


def names_for(pair: dict, project: list[str]) -> tuple[list[str], str]:
    """(가릴 이름 목록, 이름 원천 상태). 상태는 pair · cast · none."""
    own = [str(x) for x in pair.get("names") or []]
    cast = ref_cast(pair)
    state = "pair" if own else "cast" if cast is not None else "none"
    return _widen([*own, *(cast or []), *project]), state


# ---------- 2. 이름 가리기 ----------

def _coda(c: str) -> int:
    """받침 갈래: 0 없음 · 1 ㄹ · 2 그 밖. 한글이 아니면 없음."""
    if not _hangul(c):
        return 0
    k = (ord(c) - 0xAC00) % 28
    return 0 if k == 0 else 1 if k == 8 else 2


def _syl(rng: random.Random, coda: int) -> str:
    return rng.choice((SYLLABLES_OPEN, SYLLABLES_L, SYLLABLES_CLOSED)[coda])


def _fresh_name(name: str, rng: random.Random, taken: set[str], avoid: str, tail: str = "") -> str:
    """name 과 글자 수 · 끝 받침 갈래가 같은 대체 이름. tail 이 있으면 그 글이 뒤 2글자다."""
    last = _coda(name[-1])
    for _ in range(500):
        if tail:
            cand = _syl(rng, rng.choice((0, 1, 2))) + tail
        else:
            cand = "".join(_syl(rng, rng.choice((0, 1, 2))) for _ in name[:-1]) + _syl(rng, last)
        if cand not in taken and cand not in avoid and _coda(cand[-1]) == last:
            return cand
    raise SystemExit("대체 이름을 고르지 못했어요")


def substitutes(names: list[str], rng: random.Random, avoid: str = "") -> dict[str, str]:
    """이름마다 대체 이름. 글자 수와 끝 글자 받침 갈래가 같다. 3글자 이름과 그 뒤 2글자 이름은 같은 관계로 맞춘다.
    avoid 는 이미 글에 있는 낱말을 찾을 글이다. 거기 든 대체 이름은 다시 뽑는다."""
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for n in sorted(names, key=lambda x: (len(x) == 3 and all(_hangul(c) for c in x), len(x))):
        tail = mapping.get(n[1:]) if len(n) == 3 and all(_hangul(c) for c in n) else ""
        mapping[n] = _fresh_name(n, rng, taken, avoid, tail or "")
        taken.add(mapping[n])
    return mapping


def mask(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """(가린 글, 바꾼 수). 긴 이름부터, 한 번 훑어 바꾼다."""
    if not mapping:
        return text, 0
    pat = re.compile("|".join(re.escape(n) for n in sorted(mapping, key=lambda n: (-len(n), n))))
    count = 0

    def swap(m: re.Match) -> str:
        nonlocal count
        count += 1
        return mapping[m.group(0)]

    return pat.sub(swap, text), count


# ---------- 3. 모양 맞추기 + 길이 맞추기 ----------

def _bounds(text: str) -> tuple[int, int, list[int]] | None:
    """(시작, 마지막 문단 시작, 끝 후보들). 시작은 둘째 문단 첫 글자. 끝은 시작 뒤 마지막 문단 앞의 문장 끝이다."""
    t = text.rstrip()
    lead = len(t) - len(t.lstrip())
    starts = [m.end() for m in _PARA.finditer(t, lead)]
    if len(starts) < 2:
        return None
    start, last = starts[0], starts[-1]
    ends = [m.end() for m in _SENT_END.finditer(t, start) if m.end() < last]
    return (start, last, ends) if ends else None


def fit_spans(ref: str, base: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """두 글의 (시작, 끝) 자리. 둘 다 MIN_CHARS 이상이고 길이 차가 TOL 이내인 짝 가운데 짧은 쪽이 가장 긴 짝."""
    a, b = _bounds(ref), _bounds(base)
    if a is None or b is None:
        return None
    best = None
    for er in a[2]:
        lr = len(ref[a[0]:er].strip())
        if lr < MIN_CHARS:
            continue
        for eb in b[2]:
            lb = len(base[b[0]:eb].strip())
            if lb < MIN_CHARS or abs(lr - lb) > TOL * max(lr, lb):
                continue
            score = (min(lr, lb), -abs(lr - lb))
            if best is None or score > best[0]:
                best = (score, (a[0], er), (b[0], eb))
    return None if best is None else (best[1], best[2])


def fit(ref: str, base: str) -> tuple[str, str] | None:
    got = fit_spans(ref, base)
    if got is None:
        return None
    (rs, re_), (bs, be) = got
    return ref[rs:re_].strip(), base[bs:be].strip()


# ---------- 4. 검증 ----------

def _seen_texts(exclude: list[str]) -> list[str]:
    return [_flat(x.text) for sid in exclude for x in blindset.load(sid).items]


def overlaps(cut: str, seen: list[str]) -> bool:
    flat = _flat(cut)
    return any(flat[i:i + OVERLAP] in s for i in range(0, len(flat) - OVERLAP + 1, PROBE_STEP) for s in seen)


def _check_cut(ref: str, base: str, names: list[str], seen: list[str], spans, raw: tuple[str, str]) -> str:
    """떨어지는 이유 (통과면 빈 글)."""
    if any(n in ref or n in base for n in names):
        return "name_left"
    lr, lb = len(ref), len(base)
    if abs(lr - lb) > TOL * max(lr, lb):
        raise AssertionError("길이 차가 TOL 을 넘었어요")
    (rs, re_), (bs, be) = spans
    if overlaps(raw[0][rs:re_], seen):
        return "ref_seen"
    if overlaps(raw[1][bs:be], seen):
        return "base_seen"
    return ""


def _mask_pair(i: int, pair: dict, project: list[str], row: dict) -> tuple[str, str, list[str]] | None:
    """이름을 가린 (ref, base, 이름 목록). 이름 원천이 없으면 None. MASK_NAMES 가 False 면 원래 글."""
    ref, base = pair["ref"], pair["base"]
    if not MASK_NAMES:
        row["names"], row["masked"], row["ref_names_from"] = 0, 0, "off"
        return ref, base, []
    names, row["ref_names_from"] = names_for(pair, project)
    row["names"] = len(names)
    if row["ref_names_from"] == "none":
        return None
    mapping = substitutes(names, random.Random(f"{SEED}:{i}"), avoid=ref + "\n" + base)
    mref, a = mask(ref, mapping)
    mbase, b = mask(base, mapping)
    row["masked"] = a + b
    return mref, mbase, names


def _one(i: int, pair: dict, project: list[str], seen: list[str]) -> dict:
    row = {"i": i, "ok": False, "reason": "", "ref_chars": None, "base_chars": None, "names": 0, "masked": 0, "ref_names_from": "none"}
    got = _mask_pair(i, pair, project, row)
    if got is None:
        row["reason"] = "no_ref_names"
        return row
    mref, mbase, names = got
    ref, base = pair["ref"], pair["base"]
    spans = fit_spans(mref, mbase)
    if spans is None:
        row["reason"] = "no_fit"
        return row
    (rs, re_), (bs, be) = spans
    cut_r, cut_b = mref[rs:re_].strip(), mbase[bs:be].strip()
    row["ref_chars"], row["base_chars"] = len(cut_r), len(cut_b)
    row["reason"] = _check_cut(cut_r, cut_b, names, seen, spans, (ref, base))
    row["ok"] = not row["reason"]
    row["cut"] = (cut_r, cut_b)
    return row


# ---------- 짝 목록 읽기 · 요약 ----------

def read_pairs(files: list[Path]) -> list[tuple[int, dict]]:
    """[(몇 번째 파일(1부터), 쌍)]. ref · base 가 없는 쌍은 멈춘다."""
    out: list[tuple[int, dict]] = []
    for k, f in enumerate(files, 1):
        raw = json.loads(Path(f).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise SystemExit(f"짝 목록 {k}번 파일이 배열이 아니에요")
        for n, p in enumerate(raw, 1):
            if not isinstance(p, dict) or not str(p.get("ref") or "").strip() or not str(p.get("base") or "").strip():
                raise SystemExit(f"짝 목록 {k}번 파일의 {n}번째 쌍에 ref · base 가 없어요")
            out.append((k, p))
    return out


def evaluate(files: list[Path], projects: list[str], exclude: list[str], max_pairs: int) -> tuple[dict, list[tuple[str, str]]]:
    """(요약, 쓸 쌍들의 (ref, base) 자른 글). 아무것도 쓰지 않는다."""
    pairs = read_pairs(files)
    project = project_names(projects)
    seen = _seen_texts(exclude)
    rows, cuts = [], []
    for i, (k, p) in enumerate(pairs, 1):
        row = _one(i, p, project, seen)
        row["file"] = k
        cut = row.pop("cut", None)
        if row["ok"] and cut:
            cuts.append(cut)
        rows.append(row)
    ok = len([r for r in rows if r["ok"]])
    used = cuts[:max_pairs]
    dropped = {r: len([x for x in rows if x["reason"] == r]) for r in ("no_ref_names", "no_fit", "name_left", "ref_seen", "base_seen")}
    sizes = [len(t) for c in used for t in c]
    diffs = [abs(len(a) - len(b)) / max(len(a), len(b)) for a, b in used]
    summary = {
        "constants": _constants(), "pairs_in": len(pairs), "pairs_ok": ok, "pairs_used": len(used), "dropped": dropped,
        "rows": [{k: r[k] for k in ("i", "file", "ok", "reason", "ref_chars", "base_chars", "names", "masked", "ref_names_from")} for r in rows],
        "chars": {"min": min(sizes), "median": statistics.median_low(sizes), "max": max(sizes)} if sizes else None,
        "len_diff_max": round(max(diffs), 4) if diffs else None, "items": None, "repeats": None, "key_sha256": None,
    }
    return summary, used


def check(files: list[Path], projects: list[str] | None = None, exclude: list[str] | None = None, max_pairs: int = 20) -> dict:
    return evaluate(files, projects or [], exclude or [], max_pairs)[0]


# ---------- 묶음 만들기 ----------

def _order(items: list[dict], rnd: random.Random) -> None:
    """읽을 차례를 섞는다. 같은 piece 의 두 글이 이웃하지 않을 때까지 1,000번까지 다시 섞고, 못 하면 멈춘다."""
    for _ in range(1_000):
        rnd.shuffle(items)
        if not any(a["piece"] == b["piece"] for a, b in zip(items, items[1:])):
            return
    raise SystemExit("같은 대목의 글이 이웃하지 않게 섞지 못했어요")


def _items(used: list[tuple[str, str]]) -> tuple[list[dict], int]:
    rnd = random.Random(SEED)
    rows = [[{"arm": ARMS[0], "piece": f"P{k:02d}", "text": r}, {"arm": ARMS[1], "piece": f"P{k:02d}", "text": b}] for k, (r, b) in enumerate(used, 1)]
    items = [x for row in rows for x in row]
    repeats = rnd.sample(range(len(rows)), min(REPEATS, len(rows)))
    for i in repeats:
        items.append(dict(rnd.choice(rows[i])))
    if len(items) > blindset.ITEMS[1]:
        raise SystemExit(f"글이 {len(items)}편이라 묶음 하나({blindset.ITEMS[1]}편)에 안 들어가요")
    _order(items, rnd)
    return items, len(repeats)


def build(out: Path, files: list[Path], projects: list[str] | None = None, exclude: list[str] | None = None, max_pairs: int = 20) -> dict:
    """out/set1/NN.txt, out/set1/blind_key.json, out/summary.json 을 쓰고 요약을 돌려준다."""
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"--out 폴더가 비어 있지 않아요: {out}")
    summary, used = evaluate(files, projects or [], exclude or [], max_pairs)
    if not used:
        raise SystemExit("쓸 수 있는 쌍이 없어요")
    items, repeats = _items(used)
    folder = out / "set1"
    folder.mkdir(parents=True, exist_ok=True)
    for no, x in enumerate(items, 1):
        x["no"] = f"{no:02d}"
        (folder / f"{x['no']}.txt").write_text(x["text"], encoding="utf-8")
    key = json.dumps([{"no": x["no"], "arm": x["arm"], "piece": x["piece"]} for x in items], ensure_ascii=False, indent=2)
    (folder / "blind_key.json").write_text(key, encoding="utf-8")
    summary.update({"items": len(items), "repeats": repeats, "key_sha256": _sha(key)})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="판별 묶음 만들기 (레퍼런스 대목과 canon 글의 짝)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("check", "쓸 수 있는 쌍을 세어 요약만 찍어요"), ("build", "묶음 폴더와 summary.json 을 만들어요")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--pairs", action="append", required=True, type=Path, metavar="파일", help="짝 목록 JSON (여러 번)")
        s.add_argument("--project", action="append", default=[], metavar="작품", help="이름을 더 가릴 작품 (MASK_NAMES 가 True 일 때만 써요, 여러 번)")
        s.add_argument("--exclude-set", action="append", default=[], metavar="묶음id", help="이미 읽은 묶음 (여러 번)")
        s.add_argument("--max-pairs", type=int, default=20)
        if name == "build":
            s.add_argument("--out", required=True, type=Path, help="새 폴더 (비어 있지 않으면 멈춰요)")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        print(json.dumps(check(a.pairs, a.project, a.exclude_set, a.max_pairs), ensure_ascii=False, indent=2))
        return 0
    s = build(a.out, a.pairs, a.project, a.exclude_set, a.max_pairs)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print(f'python -m canon blind import {a.out / "set1"} --ident {ARMS[0]} --title "판별 묶음"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
