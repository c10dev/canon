"""가려 읽기 묶음 만들기 (task 6: 레퍼런스 원고끼리, 서로 다른 대목을 나란히 견줘 읽기).

build: <CANON_HOME>/.refs 의 원고에서 화마다 대목 하나(화의 30% 지점 뒤 첫 빈 줄부터 약 900~1,300자)를 잘라, 판(원고 하나. --same 으로 묶은
  원고들은 한 판) 끼리 round robin 으로 짝을 짓고, 'canon blind import --side' 로 넣을 수 있는 묶음 폴더 set1 과 본문 없는 summary.json 을
  만든다. 역설계 실험(.revlab)에 넘긴 화와 글이 겹치는 화는 뺀다. .refs 와 .revlab 은 읽기만 하고, 묶음을 .blind 에 넣지 않는다.
  LLM 도 네트워크도 쓰지 않는다. 값은 모두 모듈 맨 위 상수로 못 박았고 명령줄로 바꾸지 않는다.

실행 (서버의 Canon 작업 폴더. CANON_HOME 이 작품 폴더를 가리킨다):
  python scripts/blind_refs.py build --out reports/blind-refs [--same RID RID ...]...
  python -m canon blind import reports/blind-refs/set1 --side --title "task 6 묶음 1"   # 사람이 넣는다
--out 폴더가 이미 있고 비어 있지 않으면 멈춘다. 시험은 tests/test_blind_refs.py (지어낸 원고).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import blindset, refs, revlab  # noqa: E402

SEED = 20261115
ROUNDS = 2            # round robin 바퀴 수
DROP_LAST = 2         # 마지막 바퀴에서 seed 로 빼는, 판이 겹치지 않는 짝 수
REPEATS = 3           # 한 번 더 넣는 글 수 (repeat duel)
MIN_EP_CHARS = 3_000  # 이보다 짧은 화는 고르지 않는다
START_FRAC = 0.3      # 화의 이 지점 뒤 첫 빈 줄에서 대목을 시작한다
CUT_MIN = 900         # 시작에서 이 글자 수를 넘은 뒤 첫 빈 줄에서 끊는다
CUT_MAX = 1_300       # 그 빈 줄이 이 안에 없으면 CUT_MAX 뒤 첫 문장 끝에서 끊는다
PROBE = 200           # 역설계 실험에 넘긴 화를 가릴 때 견줄 글자 수

_BLANK = re.compile(r"\n[ \t]*\n")
_SENT_END = re.compile(r"[.?!…][\"”’」』]?(?=\s|$)")


def _constants() -> dict:
    return {"SEED": SEED, "ROUNDS": ROUNDS, "DROP_LAST": DROP_LAST, "REPEATS": REPEATS, "MIN_EP_CHARS": MIN_EP_CHARS,
            "START_FRAC": START_FRAC, "CUT_MIN": CUT_MIN, "CUT_MAX": CUT_MAX, "PROBE": PROBE}


def _sha(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()[:16]


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", text)


def passage(text: str) -> str | None:
    """화 글에서 대목 하나. 시작: len(text)*START_FRAC 위치 뒤 처음 나오는 빈 줄(공백만 있는 줄 포함) 다음의 첫 글자.
    끝: 시작에서 CUT_MIN 자를 넘은 뒤 처음 나오는 빈 줄 앞. 그 빈 줄이 시작에서 CUT_MAX 자 안에 없으면 CUT_MAX 뒤 첫 문장 끝까지.
    앞뒤 공백은 지운다. 시작 빈 줄이 없거나 남은 글이 CUT_MIN 미만이면 None."""
    m = _BLANK.search(text, int(len(text) * START_FRAC))
    if not m:
        return None
    start = m.end()
    while start < len(text) and text[start].isspace():
        start += 1
    if len(text) - start < CUT_MIN:
        return None
    b = _BLANK.search(text, start + CUT_MIN)
    if b and b.start() - start <= CUT_MAX:
        return text[start:b.start()].strip()
    s = _SENT_END.search(text, start + CUT_MAX)
    return text[start:s.end() if s else len(text)].strip()


def sent_to_revlab() -> tuple[set[tuple[str, int]], list[str]]:
    """역설계 실험에 넘긴 화. (RevSource 의 (ref, order) 집합, 출처 없는 실험 화들의 공백을 지운 글 목록)."""
    sources: set[tuple[str, int]] = set()
    plain: list[str] = []
    for lid in revlab.ids():
        for ep in revlab.load(lid).episodes:
            if ep.source:
                sources.add((ep.source.ref, ep.source.order))
            elif ep.text.strip():
                plain.append(_flat(ep.text))
    return sources, plain


def pool(groups: list[list[str]]) -> tuple[dict[str, list[dict]], dict]:
    """판마다 고를 수 있는 화. 판 = refs.entries() 의 원고 하나, 단 groups 의 한 묶음은 한 판이다 (판 이름은 묶음 첫 원고의 name).
    뺀 화: MIN_EP_CHARS 미만 · 역설계 실험에 넘긴 화(출처 일치, 또는 가운데 PROBE 자가 출처 없는 실험 화에 들어 있음) · passage 가 None.
    돌려줌: ({판 이름: [{"rid", "order", "text"(대목), "chars"}]},
             {판 이름 해시: {"episodes"(고를 수 있는 화), "dropped_short", "dropped_revlab", "dropped_cut"}})."""
    books = {b.id: b for b in refs.entries()}
    seen: set[str] = set()
    for g in groups:
        for rid in g:
            if rid not in books:
                raise SystemExit(f"없는 레퍼런스 원고예요: {rid}")
            if rid in seen:
                raise SystemExit(f"같은 원고를 두 번 묶을 수 없어요: {rid}")
            seen.add(rid)
    units = [list(g) for g in groups if g] + [[rid] for rid in sorted(books, key=lambda r: (books[r].name, r)) if rid not in seen]
    sent, plain = sent_to_revlab()
    arms: dict[str, list[dict]] = {}
    counts: dict[str, dict] = {}
    for unit in units:
        name = books[unit[0]].name
        if name in arms:
            raise SystemExit("판 이름이 겹쳐요. 이름이 같은 원고는 --same 으로 묶거나 이름을 바꿔 주세요")
        rows: list[dict] = []
        c = {"episodes": 0, "dropped_short": 0, "dropped_revlab": 0, "dropped_cut": 0}
        for rid in unit:
            for order, text in sorted((refs.texts(rid) or {}).items()):
                if len(text) < MIN_EP_CHARS:
                    c["dropped_short"] += 1
                    continue
                flat = _flat(text)
                mid = flat[len(flat) // 2:len(flat) // 2 + PROBE]
                if (rid, order) in sent or (mid and any(mid in p for p in plain)):
                    c["dropped_revlab"] += 1
                    continue
                cut = passage(text)
                if cut is None:
                    c["dropped_cut"] += 1
                    continue
                rows.append({"rid": rid, "order": order, "text": cut, "chars": len(cut)})
        c["episodes"] = len(rows)
        arms[name] = rows
        counts[_sha(name)] = c
    return arms, counts


def schedule(arms: list[str]) -> list[tuple[str, str]]:
    """판 짝 목록. itertools.combinations(sorted(arms), 2) 를 ROUNDS 번. 마지막 바퀴에서 판이 서로 겹치지 않는 짝 DROP_LAST 개를
    random.Random(SEED) 로 골라 뺀다. 6판이면 15*2-2 = 28."""
    one = list(itertools.combinations(sorted(arms), 2))
    last = list(one)
    random.Random(SEED).shuffle(last)
    gone: list[tuple[str, str]] = []
    for p in last:
        if len(gone) < DROP_LAST and all(not set(p) & set(q) for q in gone):
            gone.append(p)
    if len(gone) < DROP_LAST:
        raise SystemExit(f"판이 {len(arms)}개라서 겹치지 않는 짝 {DROP_LAST}개를 뺄 수 없어요")
    return one * (ROUNDS - 1) + [p for p in one if p not in gone]


def _order(items: list[dict], rnd: random.Random) -> None:
    """읽을 차례를 섞는다. 같은 piece 의 두 글이 이웃하지 않을 때까지 1,000번까지 다시 섞고, 못 하면 멈춘다."""
    for _ in range(1_000):
        rnd.shuffle(items)
        if not any(a["piece"] == b["piece"] for a, b in zip(items, items[1:])):
            return
    raise SystemExit("같은 대목의 글이 이웃하지 않게 섞지 못했어요")


def build(out: Path, groups: list[list[str]]) -> dict:
    """out/set1/NN.txt, out/set1/blind_key.json, out/summary.json 을 쓰고 summary 를 돌려준다. summary 에는 본문 · 판 이름 · 원고 이름 · rid 를 싣지 않는다."""
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"--out 폴더가 비어 있지 않아요: {out}")
    arms, counts = pool(groups)
    pairs = schedule(list(arms))
    need: dict[str, int] = {}
    for a, b in pairs:
        need[a] = need.get(a, 0) + 1
        need[b] = need.get(b, 0) + 1
    for name, n in need.items():
        if len(arms[name]) < n:
            raise SystemExit(f"화가 모자라요: 판 {_sha(name)} 은 {n}편이 필요한데 {len(arms[name])}편뿐이에요")
    rnd = random.Random(SEED)
    left = {name: list(arms[name]) for name in sorted(arms)}
    for name in left:
        rnd.shuffle(left[name])
    items: list[dict] = []
    used: dict[str, list[int]] = {name: [] for name in arms}
    rows: list[list[dict]] = []
    for k, (a, b) in enumerate(pairs, 1):
        row = []
        for name in (a, b):
            ep = left[name].pop()
            used[name].append(ep["chars"])
            row.append({"arm": name, "piece": f"P{k:02d}", "text": ep["text"]})
        rows.append(row)
        items += row
    repeats = rnd.sample(range(len(rows)), min(REPEATS, len(rows)))
    for i in repeats:
        items.append(dict(rnd.choice(rows[i])))
    if len(items) > blindset.ITEMS[1]:
        raise SystemExit(f"글이 {len(items)}편이라 묶음 하나({blindset.ITEMS[1]}편)에 안 들어가요")
    _order(items, rnd)
    folder = out / "set1"
    folder.mkdir(parents=True, exist_ok=True)
    for no, x in enumerate(items, 1):
        x["no"] = f"{no:02d}"
        (folder / f"{x['no']}.txt").write_text(x["text"], encoding="utf-8")
    key = json.dumps([{"no": x["no"], "arm": x["arm"], "piece": x["piece"]} for x in items], ensure_ascii=False, indent=2)
    (folder / "blind_key.json").write_text(key, encoding="utf-8")
    per_arm = {}
    for name in sorted(arms):
        c = counts[_sha(name)]
        ch = used[name]
        per_arm[_sha(name)] = {"duels": need.get(name, 0), "episodes": c["episodes"],
                               "dropped": c["dropped_short"] + c["dropped_revlab"] + c["dropped_cut"], **{k: v for k, v in c.items() if k != "episodes"},
                               "passage_chars": {"min": min(ch), "median": statistics.median_low(ch), "max": max(ch)} if ch else None}
    summary = {"constants": _constants(), "arms": len(arms), "pairs": len(pairs), "items": len(items), "repeats": len(repeats),
               "per_arm": per_arm, "key_sha256": _sha(key)}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="레퍼런스 원고끼리 나란히 읽기 묶음 만들기")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="묶음 폴더와 summary.json 을 만들어요")
    b.add_argument("--out", required=True, help="새 폴더 (비어 있지 않으면 멈춰요)")
    b.add_argument("--same", nargs="+", action="append", default=[], metavar="RID", help="한 판으로 칠 원고 묶음 (여러 번)")
    args = ap.parse_args(argv)
    s = build(Path(args.out), args.same)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
