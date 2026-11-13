"""가려 읽기 묶음: 판(지시 · 규칙 · 모델)이 다른 글 여러 편을 섞어 두고 작가가 한 자리에서 점수를 매긴다.

묶음 하나가 <CANON_HOME>/.blind/<id>.json 하나다 (CANON_BLIND 로 경로 변경, 작품 밖). 작품(project.json)에는 쓰지 않는다.
묶음은 실험 스크립트나 명령줄(`canon blind import`)이 넣는다. 화면(#/blind)은 읽고 점수를 매기고 결과를 볼 뿐이다.
어느 글이 어느 판인지(열쇠)는 작가가 결과를 열기 전까지 화면에 보내지 않고, 결과를 연 뒤에는 점수를 고칠 수 없다.
같은 글을 두 번 넣어 두면 그 두 점수의 차를 이 회차의 흔들림으로 낸다 (2026-11-09: 같은 글이 하루 안에 3.5 → 2.3).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from . import store
from .schema import BlindItem, BlindKey, BlindMark, BlindSet

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
SCALE = 5  # 점수는 1 ~ SCALE
ITEMS = (2, 60)  # 묶음 하나의 글 수
TEXT_MAX = 40_000  # 글 하나의 글자 수
NOTE_MAX = 300  # 글마다 적는 한마디
TITLE_MAX = 80


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


def create(title: str, items: list[dict], key: list[dict] | None = None, note: str = "", source: str = "") -> BlindSet:
    """items: [{no?, text}] (읽을 차례 그대로), key: [{no, arm, piece?}]. 번호를 주지 않으면 01, 02 … 로 매긴다.
    열쇠가 없는 묶음도 받는다 (점수만 모으고, 결과에는 흔들림만 나온다)."""
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
                         source=source.strip()[:300], items=out, key=keys))


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


def score(bid: str, no: str, value: int, note: str = "") -> BlindSet:
    """글 하나의 점수(1 ~ SCALE, 0 은 지움)와 한마디를 적는다. 결과를 연 뒤에는 고칠 수 없다."""
    s = load(bid)
    if s.revealed_at:
        raise ValueError("결과를 연 묶음은 점수를 고칠 수 없어요")
    if not 0 <= int(value) <= SCALE:
        raise ValueError(f"점수는 1~{SCALE}점이에요")
    x = _item(s, no)
    x.score, x.note, x.at = int(value), note.strip()[:NOTE_MAX], _now() if value else ""
    return save(s)


def reveal(bid: str) -> BlindSet:
    """결과를 연다. 모든 글에 점수가 있어야 한다. 한 번 열면 닫지 못한다."""
    s = load(bid)
    left = [x.no for x in s.items if not x.score]
    if left:
        raise ValueError(f"아직 점수를 매기지 않은 글이 {len(left)}편 있어요")
    if not s.revealed_at:
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
             "marks": [m.model_dump() for m in x.marks]} for x in s.items]
    return {"arms": arms, "pairs": ps, "noise": noise, "rows": rows}


def summary(s: BlindSet) -> dict:
    return {"id": s.id, "title": s.title, "note": s.note, "created_at": s.created_at, "items": len(s.items),
            "scored": sum(1 for x in s.items if x.score), "revealed_at": s.revealed_at}


def view(s: BlindSet) -> dict:
    """화면 값. 결과를 열기 전에는 열쇠와 판 이름, 대목 묶음(pieces)을 싣지 않는다."""
    out = {**summary(s), "scale": SCALE, "source": s.source,
           "texts": [{"no": x.no, "text": x.text, "chars": len(x.text), "score": x.score, "note": x.note} for x in s.items],
           "has_key": bool(s.key), "result": None, "pieces": []}
    if s.revealed_at:
        out["result"] = result(s)
        out["pieces"] = pieces(s)
    return out
