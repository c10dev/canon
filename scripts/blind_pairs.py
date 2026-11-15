"""가려 읽기 묶음 만들기 (task 5: 원문 대 AI 판, 같은 화의 앞 약 2,000자 쌍 비교).

build: <CANON_HOME>/.revlab/*.json 의 원문 화와 AI 판(take)에서 같은 화의 앞부분을 잘라, `canon blind import` 로 넣을 수 있는
  묶음 폴더(set1, set2 …)와 본문 없는 summary.json 을 만든다. .revlab 과 .blind 는 읽기만 하고, 묶음을 .blind 에 넣지 않는다.
  LLM 도 네트워크도 쓰지 않는다. 값은 모두 모듈 맨 위 상수로 못 박았고 명령줄로 바꾸지 않는다.

실행 (서버의 Canon 작업 폴더. CANON_HOME 이 작품 폴더를 가리킨다):
  python scripts/blind_pairs.py build --out reports/blind-pairs [--exclude-blind <묶음id> ...]
  python -m canon blind import reports/blind-pairs/set1 --title "task 5 묶음 1"   # 사람이 넣는다
--out 폴더가 이미 있고 비어 있지 않으면 멈춘다. 시험은 tests/test_blind_pairs.py (지어낸 자료).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import blindset, revlab, store  # noqa: E402

SEED = 20261115
N_DUELS = 40          # 화 수 (화 하나에 duel 하나)
PER_SET = 20          # 묶음 하나의 화 수
REPEATS = 2           # 묶음마다 한 번 더 넣는 AI 판 수 (repeat duel)
CUT_MIN = 1_800       # 이 글자 수를 넘은 뒤 처음 나오는 빈 줄에서 끊는다
CUT_MAX = 2_400       # 그 빈 줄이 이 안에 없으면 CUT_MAX 뒤 첫 문장 끝에서 끊는다
SOURCE_ARM = "원문"
PILOT_PREFIX = 80     # 빼 둘 묶음의 원문 글에서 견줄 앞 글자 수 (공백을 하나로 줄인 뒤)

_HEAD_NO = re.compile(r"^\s*#*\s*(제\s*)?\d+\s*화")
_BLANK = re.compile(r"\n[ \t]*\n")
_SENT_END = re.compile(r"[.?!…][\"”’」』]?(?=\s|$)")


def _constants() -> dict:
    return {"SEED": SEED, "N_DUELS": N_DUELS, "PER_SET": PER_SET, "REPEATS": REPEATS, "CUT_MIN": CUT_MIN, "CUT_MAX": CUT_MAX,
            "SOURCE_ARM": SOURCE_ARM, "PILOT_PREFIX": PILOT_PREFIX}


def _sha(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()[:16]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_head(text: str, heads: tuple[str, ...] = ()) -> tuple[str, list[int]]:
    r"""글 첫머리의 머리 줄을 뺀다. (남은 글, 뺀 줄들의 글자 수).
    앞에서부터 빈 줄은 건너뛰고, 아래 중 하나인 줄을 뺀다. 처음으로 아닌 줄을 만나면 멈춘다.
    - 화 번호 줄: re.match(r"^\s*#*\s*(제\s*)?\d+\s*화", line) (앞의 마크다운 # 허용)
    - 제목 줄: line.strip() 에서 앞뒤의 '#', '*', 공백을 걷어낸 값이 heads 의 비지 않은 값 가운데 하나와 같은 줄
    짧은 줄이라는 까닭만으로는 빼지 않는다 (2026-11-15 실자료 시험: 원문이 짧은 첫 줄로 시작하는 화가 많아 원문 쪽만 깎였다).
    뺀 줄들 뒤의 앞 빈 줄도 지운다."""
    names = {h.strip() for h in heads if h and h.strip()}
    lines = text.split("\n")
    dropped: list[int] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if _HEAD_NO.match(line) or s.strip("#* \t") in names:
            dropped.append(len(s))
            i += 1
            continue
        break
    if not dropped:
        return text, []
    return "\n".join(lines[i:]).lstrip("\n"), dropped


def cut(text: str) -> str:
    """strip_head 를 거친 글을 자른다. CUT_MIN 자 이하면 그대로.
    CUT_MIN 위치 뒤 첫 빈 줄이 CUT_MAX 안이면 그 앞에서, 아니면 CUT_MAX 뒤 첫 문장 끝에서 자른다. 끝 공백은 지운다."""
    if len(text) <= CUT_MIN:
        return text
    m = _BLANK.search(text, CUT_MIN)
    if m and m.start() <= CUT_MAX:
        return text[:m.start()].rstrip()
    m = _SENT_END.search(text, CUT_MAX)
    return text[:m.end()].rstrip() if m else text.rstrip()


def pool(exclude_blind: list[str]) -> tuple[list[dict], dict]:
    """고를 수 있는 화 목록과 센 값. 화마다 take 하나를 (실험 id, 화 번호) 씨앗으로 고른다. exclude_blind 의 묶음에 원문이 든 화는 뺀다."""
    prefixes = []
    for bid in exclude_blind:
        s = blindset.load(bid)
        arm = {k.no: k.arm for k in s.key}
        for x in s.items:
            if arm.get(x.no) == SOURCE_ARM and _squash(x.text)[:PILOT_PREFIX]:
                prefixes.append(_squash(x.text)[:PILOT_PREFIX])
    out: list[dict] = []
    ids = revlab.ids()
    eligible = excluded = 0
    for lid in ids:
        lab = revlab.load(lid)
        for ep in lab.episodes:
            if not ep.text.strip():
                continue
            takes = sorted((t for t in ep.takes if not t.stopped and t.text.strip()), key=lambda t: t.no)
            if not takes:
                continue
            eligible += 1
            flat = _squash(ep.text)
            if any(p in flat for p in prefixes):
                excluded += 1
                continue
            take = random.Random(f"{SEED}:{lab.id}:{ep.number}").choice(takes)
            out.append({"lab": lab.id, "episode": ep.number, "piece": f"L{lab.id}-E{ep.number}",
                        "prior_read": any(t.blind.picked for t in ep.takes), "model": take.model or take.provider or "AI",
                        "source": ep.text, "ai": take.text, "heads": (ep.head, lab.title)})
    return out, {"labs": len(ids), "episodes": eligible, "excluded": excluded, "prior_read": sum(e["prior_read"] for e in out)}


def select(eps: list[dict]) -> list[dict]:
    """prior_read 가 거짓인 화를 섞어 앞에, 참인 화를 섞어 뒤에 두고 앞 N_DUELS 개."""
    rnd = random.Random(SEED)
    fresh = [e for e in eps if not e["prior_read"]]
    seen = [e for e in eps if e["prior_read"]]
    rnd.shuffle(fresh)
    rnd.shuffle(seen)
    return (fresh + seen)[:N_DUELS]


def _duel_count(items: list[dict]) -> int:
    """canon.blindset.duel_pairs 와 같은 규칙: 같은 piece 안에서 글자가 다른 두 글의 쌍 수 (DUEL_MAX 로 자르기 전)."""
    groups: dict[str, list[str]] = {}
    for x in items:
        groups.setdefault(x["piece"], []).append(x["text"])
    return sum(1 for g in groups.values() for i, a in enumerate(g) for b in g[i + 1:] if a != b)


def _order(items: list[dict], rnd: random.Random) -> bool:
    """읽을 차례를 섞는다. 같은 piece 의 두 글이 이웃하면 1,000번까지 다시 섞는다. 이웃이 남았으면 True."""
    left = True
    for _ in range(1_001):
        rnd.shuffle(items)
        left = any(a["piece"] == b["piece"] for a, b in zip(items, items[1:]))
        if not left:
            break
    return left


def build(out: Path, exclude_blind: list[str]) -> dict:
    """묶음 폴더 set1, set2 … 와 summary.json 을 쓰고 summary 를 돌려준다. summary 에는 본문 문장을 싣지 않는다."""
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"--out 폴더가 비어 있지 않아요: {out}")
    eps, counts = pool(exclude_blind)
    chosen = select(eps)
    out.mkdir(parents=True, exist_ok=True)
    sets, episodes = [], []
    for k, start in enumerate(range(0, len(chosen), PER_SET), 1):
        group = chosen[start:start + PER_SET]
        rnd = random.Random(f"{SEED}:set{k}")
        items: list[dict] = []
        for e in group:
            src, sdrop = strip_head(e["source"], e["heads"])
            ai, adrop = strip_head(e["ai"], e["heads"])
            src, ai = cut(src), cut(ai)
            items.append({"arm": SOURCE_ARM, "piece": e["piece"], "text": src})
            items.append({"arm": e["model"], "piece": e["piece"], "text": ai})
            episodes.append({"piece": e["piece"], "lab": e["lab"], "episode": e["episode"], "set": f"set{k}",
                             "prior_read": e["prior_read"], "model": e["model"], "source_chars": len(src), "ai_chars": len(ai),
                             "source_head_dropped": sdrop, "ai_head_dropped": adrop, "source_sha256": _sha(src), "ai_sha256": _sha(ai)})
        repeats = rnd.sample(group, min(REPEATS, len(group)))
        for e in repeats:
            twin = next(x for x in items if x["piece"] == e["piece"] and x["arm"] != SOURCE_ARM)
            items.append(dict(twin))
        left = _order(items, rnd)
        folder = out / f"set{k}"
        folder.mkdir()
        for no, x in enumerate(items, 1):
            x["no"] = f"{no:02d}"
            (folder / f"{x['no']}.txt").write_text(x["text"], encoding="utf-8")
        key = json.dumps([{"no": x["no"], "arm": x["arm"], "piece": x["piece"]} for x in items], ensure_ascii=False, indent=2)
        (folder / "blind_key.json").write_text(key, encoding="utf-8")
        sets.append({"folder": f"set{k}", "items": len(items), "duels": _duel_count(items), "repeats": len(repeats),
                     "adjacent_left": left, "key_sha256": _sha(key)})
    summary = {"seed": SEED, "constants": _constants(), "pool": counts, "selected": len(chosen), "sets": sets, "episodes": episodes}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="원문 대 AI 판 가려 읽기 묶음 만들기")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="묶음 폴더와 summary.json 을 만들어요")
    b.add_argument("--out", required=True, help="새 폴더 (비어 있지 않으면 멈춰요)")
    b.add_argument("--exclude-blind", action="append", default=[], metavar="ID", help="원문 글이 든 화를 뺄 묶음 id (여러 번)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    s = build(out, args.exclude_blind)
    print(f"읽은 곳: {store.ROOT}")
    print(f"화 {s['selected']}편을 골랐어요. 고를 수 있는 화 {s['pool']['episodes']}편 중 뺀 화 {s['pool']['excluded']}편, "
          f"실험 {s['pool']['labs']}개, 이전에 읽은 화 {s['pool']['prior_read']}편")
    for i, x in enumerate(s["sets"], 1):
        print(f"{x['folder']}: 글 {x['items']}편, 쌍 비교 {x['duels']}개, 같은 글 {x['repeats']}편, 이웃 남음 {x['adjacent_left']}")
        print(f'python -m canon blind import {out}/{x["folder"]} --title "task 5 묶음 {i}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
