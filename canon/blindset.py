"""가려 읽기 묶음: 판(지시 · 규칙 · 모델)이 다른 글 여러 편을 섞어 두고 작가가 한 자리에서 점수를 매긴다.

묶음 하나가 <CANON_HOME>/.blind/<id>.json 하나다 (CANON_BLIND 로 경로 변경, 작품 밖). 작품(project.json)에는 쓰지 않는다.
묶음은 실험 스크립트나 명령줄(`canon blind import`)이 넣는다. 화면(#/blind)은 읽고 점수를 매기고 결과를 볼 뿐이다.
어느 글이 어느 판인지(열쇠)는 작가가 결과를 열기 전까지 화면에 보내지 않고, 결과를 연 뒤에는 점수를 고칠 수 없다.
같은 글을 두 번 넣어 두면 그 두 점수의 차를 이 회차의 흔들림으로 낸다 (2026-11-09: 같은 글이 하루 안에 3.5 → 2.3).
느낌 점수만으로는 판이 갈리지 않아 (2026-11-13: 11편이 모두 2~3점) 결과를 열기 전에 두 가지를 더 받는다:
글마다 기준 항목 체크(CRITERIA), 그리고 같은 대목의 글 두 편을 나란히 놓고 고르는 쌍 비교(duel). 둘 다 안 해도 결과는 열 수 있다.
"""
from __future__ import annotations

import json
import os
import functools
import random
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import store
from .schema import BlindDuel, BlindItem, BlindKey, BlindMark, BlindSet

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
SCALE = 5  # 점수는 1 ~ SCALE
ITEMS = (2, 60)  # 묶음 하나의 글 수
TEXT_MAX = 40_000  # 글 하나의 글자 수
NOTE_MAX = 300  # 글마다 적는 한마디
TITLE_MAX = 80
# 기준 항목: 작가가 2점 · 3점 글에서 그은 문장 30개를 묶은 다섯 갈래 (2026-11-13, 작가 확인). 한 작품의 다섯 글에서 나온 것이라 고쳐 쓸 것으로 본다.
# 그래서 묶음마다 그때의 항목을 적어 둔다 (BlindSet.criteria). 여기를 고쳐도 이미 체크한 묶음의 결과는 그대로다.
CRITERIA = (
    "인물 말투가 바뀜",
    "설정을 끼워 넣음",
    "지어낸 티 나는 대사",
    "속셈을 그대로 말함",
    "토막 난 속말 · 속어",
)
CRITERIA_MAX = (8, 30)  # 묶음 하나의 항목 수, 항목 하나의 글자 수
DUEL_MAX = 30  # 쌍 비교로 묻는 쌍 수 (넘으면 섞은 차례의 앞쪽만)
TIE = "="  # 쌍 비교의 '비슷함'


_LOCK = threading.RLock()


def _locked(fn):
    """읽고 고쳐 쓰는 함수를 한 번에 하나만 돌린다. 화면이 항목 체크와 점수를 잇달아 보내면 두 요청이 같은 파일을 읽고 서로 덮는다."""
    @functools.wraps(fn)
    def run(*a, **kw):
        with _LOCK:
            return fn(*a, **kw)
    return run


def root() -> Path:
    return Path(os.environ.get("CANON_BLIND") or store.ROOT / ".blind")


def _path(bid: str) -> Path:
    if not ID_RE.match(bid):
        raise KeyError(f"가려 읽기 묶음에 없는 항목이에요: {bid}")
    return root() / f"{bid}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load(bid: str) -> BlindSet:
    path = _path(bid)
    if not path.exists():
        raise KeyError(f"가려 읽기 묶음에 없는 항목이에요: {bid}")
    return BlindSet.model_validate_json(path.read_text(encoding="utf-8"))


def save(s: BlindSet) -> BlindSet:
    s.created_at = s.created_at or _now()
    path = _path(s.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    store.write_atomic(path, s.model_dump_json(indent=2))
    return s


def sets() -> list[BlindSet]:
    d = root()
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json"):
        try:
            out.append(BlindSet.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(out, key=lambda s: s.created_at, reverse=True)


def delete(bid: str) -> None:
    path = _path(bid)
    if not path.exists():
        raise KeyError(f"가려 읽기 묶음에 없는 항목이에요: {bid}")
    path.unlink()


def create(title: str, items: list[dict], key: list[dict] | None = None, note: str = "", source: str = "",
           criteria: list[str] | None = None) -> BlindSet:
    """items: [{no?, text}] (읽을 차례 그대로), key: [{no, arm, piece?}]. 번호를 주지 않으면 01, 02 … 로 매긴다.
    열쇠가 없는 묶음도 받는다 (점수만 모으고, 결과에는 흔들림만 나온다). criteria 를 안 주면 CRITERIA 를 적어 둔다."""
    many, long = CRITERIA_MAX
    crit = list(dict.fromkeys(str(c).strip()[:long] for c in (criteria or CRITERIA) if str(c).strip()))
    if len(crit) > many:
        raise ValueError(f"기준 항목은 {many}개까지 둘 수 있어요 (지금 {len(crit)}개)")
    lo, hi = ITEMS
    if not lo <= len(items) <= hi:
        raise ValueError(f"글은 {lo}~{hi}편이어야 해요 (지금 {len(items)}편)")
    out, seen = [], set()
    for i, x in enumerate(items, 1):
        no = str(x.get("no") or f"{i:02d}").strip()
        text = str(x.get("text") or "").strip()
        if not text:
            raise ValueError(f"{no}번 글이 비어 있어요")
        if len(text) > TEXT_MAX:
            raise ValueError(f"{no}번 글이 너무 길어요 ({len(text):,}자). {TEXT_MAX:,}자까지 넣을 수 있어요")
        if no in seen:
            raise ValueError(f"번호가 겹쳐요: {no}")
        seen.add(no)
        out.append(BlindItem(no=no, text=text))
    keys = []
    for k in key or []:
        no = str(k.get("no") or "").strip()
        if no not in seen:
            raise ValueError(f"열쇠에 없는 번호가 있어요: {no}")
        keys.append(BlindKey(no=no, arm=str(k.get("arm") or "").strip(), piece=str(k.get("piece") or "").strip()))
    if keys and {k.no for k in keys} != seen:
        raise ValueError("열쇠가 모든 글을 덮지 않아요")
    return save(BlindSet(id=uuid.uuid4().hex[:12], title=title.strip()[:TITLE_MAX] or "가려 읽기 묶음", note=note.strip()[:NOTE_MAX * 2],
                         source=source.strip()[:300], items=out, key=keys, criteria=crit))


def import_folder(folder: str, title: str = "", note: str = "") -> BlindSet:
    """실험 스크립트가 만든 폴더를 묶음으로 넣는다: 숫자 이름의 txt (01.txt …)가 글이고, 열쇠는 그 폴더나 윗 폴더의 blind_key.json.
    열쇠 꼴은 {번호: {arm, passage 또는 piece}} 또는 [{no, arm, piece}]. 폴더의 파일은 바꾸지 않는다."""
    d = Path(folder).expanduser()
    files = sorted(f for f in d.glob("*.txt") if re.fullmatch(r"\d+", f.stem))
    if not files:
        raise ValueError(f"숫자 이름의 txt 파일이 없어요: {d}")
    items = [{"no": f.stem, "text": f.read_text(encoding="utf-8")} for f in files]
    key: list[dict] = []
    for kf in (d / "blind_key.json", d.parent / "blind_key.json"):
        if kf.exists():
            raw = json.loads(kf.read_text(encoding="utf-8"))
            rows = [{"no": no, **v} for no, v in raw.items()] if isinstance(raw, dict) else list(raw)
            key = [{"no": str(r.get("no")), "arm": r.get("arm", ""), "piece": r.get("piece") or r.get("passage") or ""} for r in rows]
            break
    return create(title or d.parent.name or d.name, items, key, note, str(d))


def _item(s: BlindSet, no: str) -> BlindItem:
    for x in s.items:
        if x.no == no:
            return x
    raise KeyError(f"이 묶음에 없는 글이에요: {no}")


def criteria(s: BlindSet) -> list[str]:
    """이 묶음의 기준 항목. 항목을 적어 두지 않은 옛 묶음은 결과를 열기 전이면 CRITERIA, 연 뒤면 없다 (체크한 적이 없는 묶음이다)."""
    return list(s.criteria) or ([] if s.revealed_at else list(CRITERIA))


@_locked
def score(bid: str, no: str, value: int, note: str = "", flags: list[str] | None = None) -> BlindSet:
    """글 하나의 점수(1 ~ SCALE, 0 은 지움)와 한마디, 체크한 기준 항목을 적는다. 결과를 연 뒤에는 고칠 수 없다.
    flags 가 None 이면 체크는 그대로 둔다 (점수만 보내는 호출이 체크를 지우지 않게). 체크는 점수가 없어도 남는다 (점수를 누르면 다음 글로 넘어가서)."""
    s = load(bid)
    if s.revealed_at:
        raise ValueError("결과를 연 묶음은 점수를 고칠 수 없어요")
    if not 0 <= int(value) <= SCALE:
        raise ValueError(f"점수는 1~{SCALE}점이에요")
    x = _item(s, no)
    if flags is not None:
        crit = criteria(s)
        bad = [f for f in flags if f not in crit]
        if bad:
            raise ValueError(f"이 묶음에 없는 기준 항목이에요: {bad[0]}")
        s.criteria = crit  # 옛 묶음은 처음 체크할 때 그때의 항목을 적어 둔다
        x.flags = [c for c in crit if c in flags]
    x.score, x.note, x.at = int(value), note.strip()[:NOTE_MAX], _now() if value else ""
    return save(s)


@_locked
def flag(bid: str, no: str, label: str, on: bool = True) -> BlindSet:
    """기준 항목 하나를 체크하거나(on) 지운다. 점수와 한마디는 건드리지 않는다.
    화면은 이 함수만 쓴다: 목록을 통째로 보내면 잇달아 누른 두 체크 가운데 앞의 것이 빠진다."""
    s = load(bid)
    if s.revealed_at:
        raise ValueError("결과를 연 묶음은 점수를 고칠 수 없어요")
    x = _item(s, no)
    crit = criteria(s)
    if label not in crit:
        raise ValueError(f"이 묶음에 없는 기준 항목이에요: {label}")
    s.criteria = crit
    x.flags = [c for c in crit if (c in x.flags and c != label) or (on and c == label)]
    return save(s)


def duel_pairs(s: BlindSet) -> list[tuple[str, str]]:
    """쌍 비교로 물을 쌍 [(왼쪽 번호, 오른쪽 번호)]: 같은 대목의 글 가운데 글자가 다른 두 편씩 모두.
    차례와 좌우는 묶음 id 로 섞어 요청마다 같고, 판 차례와 상관없다 (글은 읽을 차례로 훑는다). 대목 이름이 없는 글과 열쇠 없는 묶음은 묻지 않는다.
    같은 글이 두 번 들어 있으면 그 글이 낀 쌍도 두 번 나온다. 그 두 답이 같은지가 쌍 비교의 흔들림이다."""
    piece = {k.no: k.piece for k in s.key}
    groups: dict[str, list[BlindItem]] = {}
    for x in s.items:
        if piece.get(x.no):
            groups.setdefault(piece[x.no], []).append(x)
    out = [(a.no, b.no) for g in groups.values() for i, a in enumerate(g) for b in g[i + 1:] if a.text != b.text]
    rnd = random.Random(s.id)
    rnd.shuffle(out)
    return [(b, a) if rnd.random() < 0.5 else (a, b) for a, b in out[:DUEL_MAX]]


def duels(s: BlindSet) -> list[dict]:
    """물을 쌍과 지금까지의 답 [{a, b, pick}]. 판 이름과 대목 이름은 싣지 않는다."""
    got = {frozenset((d.a, d.b)): d.pick for d in s.duels}
    return [{"a": a, "b": b, "pick": got.get(frozenset((a, b)), "")} for a, b in duel_pairs(s)]


@_locked
def duel(bid: str, a: str, b: str, pick: str) -> BlindSet:
    """쌍 하나의 답을 적는다: 나은 글의 번호, TIE(비슷함), '' (지움). 글을 모두 매긴 뒤, 결과를 열기 전에만 한다."""
    s = load(bid)
    if s.revealed_at:
        raise ValueError("결과를 연 묶음은 쌍 비교를 고칠 수 없어요")
    if any(not x.score for x in s.items):
        raise ValueError("글을 모두 매긴 뒤에 쌍 비교를 할 수 있어요")
    pair = next(((x, y) for x, y in duel_pairs(s) if {x, y} == {a, b}), None)
    if not pair:
        raise KeyError(f"이 묶음에 없는 쌍이에요: {a} · {b}")
    if pick not in (a, b, TIE, ""):
        raise ValueError("두 글 가운데 하나나 '비슷해요'를 골라 주세요")
    s.duels = [d for d in s.duels if {d.a, d.b} != {a, b}]
    if pick:
        s.duels.append(BlindDuel(a=pair[0], b=pair[1], pick=pick, at=_now()))
    return save(s)


@_locked
def reveal(bid: str) -> BlindSet:
    """결과를 연다. 모든 글에 점수가 있어야 한다. 한 번 열면 닫지 못한다."""
    s = load(bid)
    left = [x.no for x in s.items if not x.score]
    if left:
        raise ValueError(f"아직 점수를 매기지 않은 글이 {len(left)}편 있어요")
    if not s.revealed_at:
        s.criteria = criteria(s)
        s.revealed_at = _now()
        save(s)
    return s


# 문장 끝: 마침표 · 물음표 · 느낌표 · 말줄임표와 그 뒤 닫는 따옴표 · 괄호. 그 뒤가 빈칸이거나 줄 끝일 때만 끊는다 (3.5 같은 숫자는 끊지 않는다)
_SENT = re.compile(r""".+?(?:[.!?…]+["”’'」』)\]]*(?=\s|$)|$)""")


def sentences(text: str) -> list[list[str]]:
    """글을 문단마다 문장 목록으로 나눈다 (긋기의 단위). 빈 줄이 문단을, 줄바꿈과 문장 끝 부호가 문장을 끊는다.
    화면은 이 목록을 그대로 그리고 문장 차례(문단을 넘겨 0 부터 이어 센 수)로 긋는다. 나누는 곳이 여기 한 곳이라 서버와 화면이 어긋나지 않는다."""
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        sents = [x.strip() for line in para.split("\n") for x in _SENT.findall(line.strip()) if x.strip()]
        if sents:
            out.append(sents)
    return out


@_locked
def mark(bid: str, no: str, idx: int, on: bool = True) -> BlindSet:
    """결과를 연 묶음에서 거슬린 문장 하나를 긋거나(on) 지운다. 점수와 달리 결과를 연 뒤에만 한다 (판을 모르고 매긴 점수를 지키려고).
    글자가 같은 글이 또 있으면 그 글에도 같이 긋는다 (화면은 같은 글을 한 번만 보인다)."""
    s = load(bid)
    if not s.revealed_at:
        raise ValueError("결과를 연 뒤에 문장을 그을 수 있어요")
    x = _item(s, no)
    flat = [t for para in sentences(x.text) for t in para]
    if not 0 <= int(idx) < len(flat):
        raise ValueError(f"이 글에 없는 문장이에요: {idx}")
    for y in s.items:
        if y.text != x.text:
            continue
        rest = [m for m in y.marks if m.idx != int(idx)]
        y.marks = sorted(rest + ([BlindMark(idx=int(idx), text=flat[int(idx)])] if on else []), key=lambda m: m.idx)
    return save(s)


def pieces(s: BlindSet) -> list[dict]:
    """결과를 연 묶음을 대목마다 묶는다: [{piece, spread, texts: [{nos, scores, paras, marks}]}]. 긋기 화면이 같은 대목의 글을 나란히 놓는다.
    글자가 같은 글은 하나로 합치고(nos 에 번호 둘), 점수가 낮은 글부터 놓는다. 점수 차(spread)가 큰 대목이 앞이다.
    판 이름은 싣지 않는다: 어느 규칙이 쓴 글인지 알면 긋는 문장이 그쪽으로 쏠린다. 결과를 열기 전에는 빈 목록이다 (대목이 곧 열쇠다)."""
    if not s.revealed_at or not s.key:
        return []
    piece = {k.no: k.piece for k in s.key}
    groups: dict[str, dict[str, dict]] = {}
    for x in s.items:
        t = groups.setdefault(piece.get(x.no, ""), {}).setdefault(x.text, {"nos": [], "scores": [], "paras": sentences(x.text),
                                                                           "marks": [m.idx for m in x.marks]})
        t["nos"].append(x.no)
        t["scores"].append(x.score)
    out = []
    for name, by_text in groups.items():
        texts = sorted(by_text.values(), key=lambda t: sum(t["scores"]) / len(t["scores"]))
        means = [sum(t["scores"]) / len(t["scores"]) for t in texts]
        out.append({"piece": name, "spread": round(max(means) - min(means), 2), "texts": texts})
    return sorted(out, key=lambda g: -g["spread"])


def pairs(s: BlindSet) -> list[dict]:
    """같은 글이 두 번 들어 있는 짝 [{a, b, diff}] (글자가 같은 글끼리, 읽는 차례대로)."""
    by: dict[str, list[BlindItem]] = {}
    for x in s.items:
        by.setdefault(x.text, []).append(x)
    out = []
    for group in by.values():
        for a, b in zip(group, group[1:]):
            out.append({"a": a.no, "b": b.no, "diff": abs(a.score - b.score) if a.score and b.score else None})
    return out


def result(s: BlindSet) -> dict:
    """판마다 평균과, 같은 글 짝으로 잰 흔들림. 같은 글 두 편은 평균 하나로 쳐서 그 판을 두 번 세지 않는다.
    close 는 가장 높은 판과의 평균 차가 흔들림 안인 판들이다 (차이가 흔들림보다 작으면 어느 쪽이 낫다고 말할 수 없다)."""
    arm = {k.no: k for k in s.key}
    ps = pairs(s)
    diffs = [p["diff"] for p in ps if p["diff"] is not None]
    noise = round(sum(diffs) / len(diffs), 2) if diffs else None
    texts: dict[tuple[str, str], list[int]] = {}
    for x in s.items:
        if x.score and x.no in arm:
            texts.setdefault((arm[x.no].arm, x.text), []).append(x.score)
    by_arm: dict[str, list[float]] = {}
    for (a, _), scores in texts.items():
        by_arm.setdefault(a, []).append(sum(scores) / len(scores))
    arms = sorted(({"arm": a, "mean": round(sum(v) / len(v), 2), "texts": len(v), "low": min(v), "high": max(v)} for a, v in by_arm.items()),
                  key=lambda r: -r["mean"])
    top = arms[0]["mean"] if arms else 0
    for r in arms:
        r["close"] = noise is not None and top - r["mean"] <= noise
    rows = [{"no": x.no, "score": x.score, "note": x.note, "arm": arm[x.no].arm if x.no in arm else "", "piece": arm[x.no].piece if x.no in arm else "",
             "marks": [m.model_dump() for m in x.marks], "flags": list(x.flags)} for x in s.items]
    return {"arms": arms, "pairs": ps, "noise": noise, "rows": rows, "flags": flag_result(s), "duel": duel_result(s)}


def flag_result(s: BlindSet) -> dict:
    """기준 항목마다 판별로 체크한 글 수. 같은 글 두 편은 글 하나로 치고 체크는 그 평균이다 (한 편만 체크했으면 0.5).
    diff 는 같은 글 두 편에서 체크가 엇갈린 항목 수의 합 (항목 체크의 흔들림), 같은 글 짝이 없으면 None."""
    arm = {k.no: k.arm for k in s.key}
    crit = criteria(s)
    by_text: dict[tuple[str, str], list[BlindItem]] = {}
    for x in s.items:
        by_text.setdefault((arm.get(x.no, ""), x.text), []).append(x)
    names = [r for r in dict.fromkeys(a for a, _ in by_text) if r]
    rows = []
    for c in crit:
        counts = []
        for a in names:
            groups = [g for (name, _), g in by_text.items() if name == a]
            counts.append({"arm": a, "n": round(sum(sum(c in x.flags for x in g) / len(g) for g in groups), 2), "texts": len(groups)})
        rows.append({"label": c, "counts": counts, "total": sum(c in x.flags for x in s.items)})
    same: dict[str, list[BlindItem]] = {}
    for x in s.items:
        same.setdefault(x.text, []).append(x)
    twins = [(a, b) for g in same.values() for a, b in zip(g, g[1:])]
    return {"criteria": crit, "arms": names, "rows": rows, "checked": sum(len(x.flags) for x in s.items),
            "diff": sum(len(set(a.flags) ^ set(b.flags)) for a, b in twins) if twins else None}


def duel_result(s: BlindSet) -> dict:
    """쌍 비교의 판별 결과. 글자가 같은 두 글의 쌍(같은 글이 두 번 들어 있어 두 번 물은 쌍)은 한 번으로 치고 그 답의 평균을 쓴다.
    rate 는 이긴 몫(이김 1, 비김 0.5)의 평균, pairs 는 답한 쌍 수(겹친 쌍은 하나). repeat 는 두 번 물은 쌍 가운데 답이 같았던 수다."""
    arm = {k.no: k.arm for k in s.key}
    text = {x.no: x.text for x in s.items}
    asked = duels(s)
    by: dict[frozenset, list[dict]] = {}
    for d in asked:
        if d["pick"]:
            by.setdefault(frozenset((text[d["a"]], text[d["b"]])), []).append(d)
    share: dict[str, list[float]] = {}
    tally: dict[str, list[int]] = {}
    same = of = 0
    for group in by.values():
        d0 = group[0]
        a, b = arm.get(d0["a"], ""), arm.get(d0["b"], "")
        won = [1.0 if d["pick"] != TIE and text[d["pick"]] == text[d0["a"]] else 0.5 if d["pick"] == TIE else 0.0 for d in group]
        for x, y in zip(won, won[1:]):
            of += 1
            same += x == y
        if not a or not b or a == b:
            continue
        mean = sum(won) / len(won)
        share.setdefault(a, []).append(mean)
        share.setdefault(b, []).append(1 - mean)
        for w in won:
            tally.setdefault(a, [0, 0, 0])[0 if w == 1 else 1 if w == 0.5 else 2] += 1
            tally.setdefault(b, [0, 0, 0])[2 if w == 1 else 1 if w == 0.5 else 0] += 1
    arms = sorted(({"arm": a, "rate": round(sum(v) / len(v), 2), "pairs": len(v), "win": tally[a][0], "tie": tally[a][1], "loss": tally[a][2]}
                   for a, v in share.items()), key=lambda r: -r["rate"])
    return {"total": len(asked), "answered": sum(1 for d in asked if d["pick"]), "arms": arms, "repeat": {"same": same, "of": of} if of else None}


def summary(s: BlindSet) -> dict:
    return {"id": s.id, "title": s.title, "note": s.note, "created_at": s.created_at, "items": len(s.items),
            "scored": sum(1 for x in s.items if x.score), "revealed_at": s.revealed_at}


def view(s: BlindSet) -> dict:
    """화면 값. 결과를 열기 전에는 판 이름과 대목 이름, 대목 묶음(pieces)을 싣지 않는다.
    쌍 비교의 쌍(duels)은 글을 모두 매긴 뒤부터 번호 둘로만 싣는다: 어느 두 글이 같은 대목인지는 글을 읽으면 아는 것이고, 판은 드러나지 않는다."""
    done = all(x.score for x in s.items)
    out = {**summary(s), "scale": SCALE, "source": s.source, "criteria": criteria(s),
           "texts": [{"no": x.no, "text": x.text, "chars": len(x.text), "score": x.score, "note": x.note, "flags": list(x.flags)} for x in s.items],
           "has_key": bool(s.key), "result": None, "pieces": [], "duels": duels(s) if done else []}
    if s.revealed_at:
        out["result"] = result(s)
        out["pieces"] = pieces(s)
    return out
