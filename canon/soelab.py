"""쇠맛 실험실(soelab): 쇠맛 지표(metrics.py)가 사람 글과 AI 글을, 그리고 작가의 판정을 가르는지 잰다. LLM 호출 없음.

작품(project.json)에는 아무것도 넣지 않고 <CANON_HOME>/.soelab/ 에 둔다 (역설계 실험처럼 작품 밖).
- pieces/<id>.json: 정규화한 조각 원문 사본과 출처. id 는 정규화 원문 sha1 앞 12자라 같은 글은 한 번만 들어간다.
- queue.json: 가려 읽기 대기열과 다시 읽기 예정 조각. 모을 때 시드로 정하고, 정한 자리는 뒤에 모아도 바꾸지 않는다.
- labels.jsonl: 판정 기록. 덧붙이기만 하고 지우기는 removed 줄.
- reports/<id>.json: 보고서 사본 (입력 해시, 시드, METRICS_VERSION, 숫자).
모든 쓰기는 .lock 에 fcntl.flock 을 잡는다 (명령줄과 웹 서버가 함께 써도 섞이지 않게).

지표 값은 저장하지 않고 부를 때마다 다시 잰다(features). 지표 로직이 바뀌면 metrics.METRICS_VERSION 이 바뀌고, 옛 값과 섞이지 않는다.
가린 조각(hidden_ids: 판정 대기 중이거나 다시 읽기 예정인 조각)의 출처 · 원천 · 묶음 · 지표 값은 보고서의 조각별 줄 · 화면 값 · 내보내기에 싣지 않는다.
설계는 DESIGN.md '쇠맛 실험실'.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import html
import json
import os
import random
import re
import threading
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Iterator, Optional

from . import labstats, metrics, publish, revlab, statwin, store, usage
from .schema import Project, SoeLabel, SoePiece, SoeSource, SoeSpan

JOBS = ".soelab"            # 작업 목록의 project 자리 (PR3 이후). 작품 폴더는 점으로 시작하지 않는다
CHUNK = metrics.STYLE_CHUNK  # 조각 길이 목표 (가장 가까운 문장 끝에서 자름)
MIN_CHUNK = 1000            # 이보다 짧은 끝 조각은 받지 않는다
HANGUL_MIN = 0.7            # 글자 중 한글이 이보다 적으면 받지 않는다
CAP = 20                    # 원천 하나 · 출처 한쪽에서 받는 조각 수 (기본)
FIRST = 40                  # 1차 가려 읽기 (명세 4.7: 묶음마다 한 조각)
GOAL = 90                   # 가려 읽기 목표
REDO_EVERY = 3              # 대기열 세 자리마다 하나를 다시 읽기로 (1/3)
REDO_DAYS = 7               # 첫 판정 뒤 이만큼 지나야 다시 읽을 수 있다
BATCH = 10                  # '이번 10개'
SEED = 7
SIDE_GROUPS = 8             # 가르는 힘을 내려면 한쪽에 묶음이 이만큼 넘게
SIDE_PIECES = 10            # 그리고 조각이 이만큼
FULL_GROUPS = 20            # 묶음이 모두 이보다 적으면 '맞아요' 대신 '약해요'까지
AUTHOR_MIN = 20             # 작가 판정 기준 가르는 힘은 판정이 이만큼부터

# (id, 화면 이름, AI 쪽 방향, 잰 곳). 방향 +1 은 '많으면 AI', None 은 양쪽(관찰한 쪽으로 보이고 '반대 방향'은 없다)
METRICS: list[tuple[str, str, Optional[int], str]] = [
    ("ai_patterns", "쇠맛 패턴 (1,000자당)", 1, "모든 조각"),
    ("cliches", "상투 표현 (1,000자당)", 1, "모든 조각"),
    ("comma_sentence_ratio", "쉼표 문장 비율", 1, "모든 조각"),
    ("short_ending_ratio", "짧은 끝 문장 비율", 1, "모든 조각"),
    ("pronoun_per_1k", "대명사 (1,000자당)", 1, "모든 조각"),
    ("sentence_len_mean", "문장 평균 길이", None, "모든 조각"),
    ("sentence_len_cv", "문장 길이 변화폭", None, "모든 조각"),
    ("paragraph_len_mean", "문단 평균 길이", None, "모든 조각"),
    ("dialogue_ratio", "대사 비율", None, "모든 조각"),
    ("past_tense_ratio", "과거형 비율", None, "모든 조각"),
    ("mattr", "어휘 다양도", None, "모든 조각"),
    ("repeated_per_1k", "반복 구 (1,000자당)", 1, "모든 조각"),
    ("style_distance", "문체 거리", 1, "기준 원문이 있는 작품 화"),
    ("copied_per_1k", "예시 옮김 (1,000자당)", 1, "예시 문단이 있는 작품 화"),
]
METRIC_IDS = [m[0] for m in METRICS]
MEASURED = {"comma_sentence_ratio", "short_ending_ratio", "pronoun_per_1k", "sentence_len_mean", "sentence_len_cv",
            "paragraph_len_mean", "dialogue_ratio", "past_tense_ratio", "mattr"}  # StyleMetrics 칸 그대로
DIR_TEXT = {1: "많으면 AI", -1: "적으면 AI", None: "정하지 않음"}
CHIP = dict(labstats.VERDICTS, few="표본 부족", tbd="아직 모름", na="잴 수 없음")


# ---------- 저장과 잠금 ----------

def _dir() -> Path:
    return store.ROOT / ".soelab"


_tlock = threading.RLock()
_depth = threading.local()


@contextlib.contextmanager
def _lock() -> Iterator[None]:
    """.soelab/.lock 에 프로세스 사이 잠금. 한 스레드 안에서는 다시 잡아도 된다."""
    with _tlock:
        d = getattr(_depth, "n", 0)
        fd = None
        if d == 0:
            _dir().mkdir(parents=True, exist_ok=True)
            fd = os.open(_dir() / ".lock", os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX)
        _depth.n = d + 1
        try:
            yield
        finally:
            _depth.n = d
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


def save_json(path: Path, data) -> Path:
    """잠금을 잡고 tmp 파일에 쓴 뒤 바꿔 넣는다."""
    with _lock():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return path


def _labels_path() -> Path:
    return _dir() / "labels.jsonl"


def append_label(label: SoeLabel) -> SoeLabel:
    """판정 한 줄을 덧붙인다: 잠금을 잡고 O_APPEND 로 연 파일에 os.write 한 번."""
    line = (label.model_dump_json() + "\n").encode("utf-8")
    with _lock():
        fd = os.open(_labels_path(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    return label


def _piece_path(pid: str) -> Path:
    return _dir() / "pieces" / f"{pid}.json"


def load_pieces() -> list[SoePiece]:
    d = _dir() / "pieces"
    if not d.exists():
        return []
    return sorted((SoePiece.model_validate_json(x.read_text(encoding="utf-8")) for x in d.glob("*.json")), key=lambda p: (p.added, p.id))


def load_queue() -> dict:
    path = _dir() / "queue.json"
    q = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"seed": SEED, "order": [], "redo": [], "carry": [], "doubled": False, **q}


def load_labels() -> list[SoeLabel]:
    """판정 기록 (지운 것은 빼고 쓴 차례로). 깨진 줄은 건너뛴다."""
    path = _labels_path()
    if not path.exists():
        return []
    rows: dict[str, SoeLabel] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            lb = SoeLabel.model_validate_json(line)
        except ValueError:
            continue
        if lb.removed:
            rows.pop(lb.id, None)
        else:
            rows[lb.id] = lb
    return list(rows.values())


# ---------- 정규화 (명세 3.2) ----------

_BRACKET = re.compile(r"^\s*[\[【<〈].*[\]】>〉]\s*$")  # 상태창 머리 · 대괄호 시스템 글 한 줄
_TAG = re.compile(r"</?[A-Za-z][^>\n]*>")
_DQ = re.compile(r"[“”„‟「」『』＂]")
_SQ = re.compile(r"[‘’‚‛]")
_ELLIPSIS = re.compile(r"\.{3,}|…+|⋯+|‥+")
_DASH = re.compile(r"—+|―+|─+|–|(?<!-)-{2,}(?!-)")


def normalize(text: str, project: Optional[Project] = None) -> str:
    """가려 읽기에서 형식이 출처를 알려 주지 않게 모든 원천에 같은 규칙을 쓴다.
    화 제목 · 'n화' 머리 줄, 상태창(project 의 서식으로 찾은 줄과 괄호 한 줄), HTML · 마크다운 흔적을 지우고,
    따옴표 · 말줄임표 · 줄표를 한 모양(" ' … —)으로, 문단은 빈 줄 하나로, 문단 안 줄바꿈은 빈칸으로 맞춘다."""
    t = revlab._norm(text)
    t = html.unescape(_TAG.sub("", t))
    drop: set[str] = set()
    if project is not None and statwin.enabled(project):
        with contextlib.suppress(Exception):
            drop = {raw for win in statwin.read_windows(project, t) for _, _, raw in win["rows"]}
    keep = []
    for ln in t.split("\n"):
        s = ln.strip()
        if (len(s) <= revlab.HEAD_MAX and revlab.HEAD_RE.match(s)) or _BRACKET.match(s) or (s and s in drop):
            continue  # 줄을 통째로 뺀다 (빈 줄로 바꾸면 빈 줄 없는 글의 문단 나누기가 달라진다)
        keep.append(ln)
    t = "\n".join(keep)
    t = _SQ.sub("'", _DQ.sub('"', t))
    t = _DASH.sub("—", _ELLIPSIS.sub("…", t))
    return "\n\n".join(" ".join(lines) for lines in publish.paragraphs(t))


def chunks(text: str) -> list[str]:
    """정규화한 글을 2,000자에 가장 가까운 문장 끝에서 자른다. 1,000자 아래 끝 조각은 버린다."""
    ends = [e for _, e in metrics.sentence_spans(text)]
    out, start = [], 0
    while True:
        rest = [e for e in ends if e > start]
        if not rest:
            break
        cut = min(rest, key=lambda e: (abs(e - (start + CHUNK)), e))
        part = text[start:cut].strip()
        if len(part) >= MIN_CHUNK:
            out.append(part)
        start = cut
    return out


def piece_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _pieces(text: str, project: Optional[Project] = None, *, short_ok: bool = False, **kw) -> list[SoePiece]:
    """글 하나 → 조각들. 한글이 적은 글은 받지 않는다. kw 는 SoePiece 칸 (source 는 SoeSource 칸 dict)."""
    t = normalize(text, project)
    if not t or metrics.hangul_ratio(t) < HANGUL_MIN:
        return []
    parts = [t] if short_ok else chunks(t)
    src = kw.pop("source")
    today = date.today().isoformat()
    return [SoePiece(id=piece_id(x), text=x, chars=len(x), added=today, source=SoeSource(**src, chunk=k), **kw)
            for k, x in enumerate(parts)]


def _spread(cands: list[SoePiece]) -> list[SoePiece]:
    """묶음을 먼저 넓히는 차례: 묶음마다 첫 조각, 그다음 둘째 조각 … (원천 상한에 걸려도 묶음이 고루 남게)."""
    by: dict[str, list[SoePiece]] = defaultdict(list)
    for p in cands:
        by[p.group].append(p)
    out, k = [], 0
    while len(out) < len(cands):
        out += [ps[k] for ps in by.values() if k < len(ps)]
        k += 1
    return out


def source_key(p: SoePiece) -> str:
    """원천별 상한의 단위: 원천 하나(실험 · 작품 · 말뭉치 · 붙여 넣은 글)."""
    s = p.source
    name = {"revlab": str(s.lab), "episode": s.project, "edit": s.project, "trial": s.project,
            "research": s.path.split("/")[0] if s.path else "", "paste": s.path}[s.kind]
    return f"{s.kind}:{name}"


# ---------- 모으기 ----------

def model_key(backend: str, model: str) -> str:
    return f"{backend or 'unknown'}:{model or 'default'}"


def _backend_of(model: str) -> str:
    m = model.lower()
    return "gemini" if m.startswith("gemini") else "claude" if m.startswith("claude") else "mock" if m == "mock" else ""


def write_models(project: str) -> dict[int, str]:
    """작품 화마다 사용량 기록(usage.jsonl)의 마지막 성공한 쓰기(stage write) 호출 모델. 본문에는 모델이 적혀 있지 않아 짐작이다."""
    out: dict[int, str] = {}
    for r in usage.read():
        if r.get("project") == project and r.get("stage") == "write" and r.get("ok") and isinstance(r.get("episode"), int):
            out[r["episode"]] = model_key(r.get("backend", ""), r.get("model", ""))
    return out


def collect_revlab(lab_id: int) -> list[SoePiece]:
    """역설계 실험: 원문은 사람 글, 되돌려 쓴 글(take · take_style)은 AI 글. 같은 화는 같은 묶음이고 되쓰기는 원문과 짝."""
    lab = revlab.load(lab_id)
    out: list[SoePiece] = []
    for e in lab.episodes:
        group = f"revlab{lab.id}:{e.number}"
        base = dict(group=group, genre="webnovel")
        orig = _pieces(e.text, origin="human", source=dict(kind="revlab", lab=lab.id, episode=e.number, take="text"), **base)
        out += orig
        for take_name in ("take", "take_style"):
            tk = getattr(e, take_name)
            if not tk or not tk.text:
                continue
            ai = _pieces(tk.text, origin="ai", model=model_key(_backend_of(tk.model), tk.model) if tk.model else "",
                         model_source="record" if tk.model else "unknown",
                         source=dict(kind="revlab", lab=lab.id, episode=e.number, take=take_name), **base)
            for k, p in enumerate(ai):
                p.pair_of = orig[min(k, len(orig) - 1)].id if orig else ""
            out += ai
    return out


def _has_style(p: Project) -> bool:
    return bool(p.style_baseline and (p.style_baseline.style_centroid or (p.style and p.style.sample_passages)))


def collect_episodes(project: str, first: int = 1, last: int = 0) -> list[SoePiece]:
    """작품 화(본문이 있는 화)는 AI 글. 모델은 사용량 기록에서 짐작한다(model_source usage)."""
    p = store.load_view(project)
    models = write_models(project)
    out: list[SoePiece] = []
    for e in p.episodes:
        n = e.plot.number
        if not e.text.strip() or n < first or (last and n > last):
            continue
        m = models.get(n, "")
        out += _pieces(e.text, p, origin="ai", group=f"{project}:{n}", genre="webnovel", model=m,
                       model_source="usage" if m else "unknown", baseline=project if _has_style(p) else "",
                       source=dict(kind="episode", project=project, episode=n))
    return out


def collect_edits(project: str) -> list[SoePiece]:
    """수정 기록 '쇠맛 줄이기'(preset less_ai)의 고치기 전 · 뒤. 짧아도 받고, 판정 대기열과 가르는 힘에는 넣지 않는다(보기만)."""
    p = store.load_view(project)
    out: list[SoePiece] = []
    for e in p.episodes:
        for ed in e.edits:
            if ed.preset != "less_ai" or ed.undone or not ed.before.strip() or not ed.after.strip():
                continue
            kw = dict(origin="edited", group=f"{project}:{e.plot.number}", genre="webnovel", short_ok=True)
            before = _pieces(ed.before, p, source=dict(kind="edit", project=project, episode=e.plot.number, edit=ed.id, take="before"), **kw)
            after = _pieces(ed.after, p, source=dict(kind="edit", project=project, episode=e.plot.number, edit=ed.id, take="after"), **kw)
            if before and after and before[0].id != after[0].id:
                after[0].pair_of = before[0].id
                out += before + after
    return out


def collect_research(path: str, known: bool = False, genre: str = "literary") -> list[SoePiece]:
    """연구 말뭉치 폴더(작가/작품.txt)의 글은 사람 글. 작품 하나가 묶음 하나다. 폴더에서 읽기만 한다."""
    root = Path(path).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"말뭉치 폴더가 없어요: {path}")
    out: list[SoePiece] = []
    for f in sorted(root.rglob("*.txt")):
        rel = f.relative_to(root).as_posix()
        out += _pieces(f.read_text(encoding="utf-8", errors="replace"), origin="human", group=f"research:{f.relative_to(root).with_suffix('').as_posix()}",
                       genre=genre, known=known, source=dict(kind="research", path=f"{root.name}/{rel}"))
    return out


def collect_paste(text: str, title: str, origin: str = "human", model: str = "", known: bool = False,
                  genre: str = "webnovel") -> list[SoePiece]:
    """붙여 넣은 글: 역설계 실험과 같은 규칙으로 화를 나누고 화마다 묶음 하나. 모델은 작가가 고른 값(model_source author)."""
    title = title.strip()
    if not title:
        raise ValueError("붙여 넣은 글의 이름을 적어 주세요")
    if origin not in ("human", "ai", "unknown"):
        raise ValueError("출처는 human · ai · unknown 가운데 하나예요")
    s = revlab.split(text)
    out: list[SoePiece] = []
    for k, e in enumerate(s["episodes"]):
        n = s["first"] + k
        out += _pieces(e["text"], origin=origin, group=f"paste:{title}:{n}", genre=genre, known=known,
                       model=model if origin != "human" else "", model_source="author" if model and origin != "human" else "unknown",
                       source=dict(kind="paste", path=title, episode=n))
    return out


def add(cands: list[SoePiece], cap: int = CAP, seed: int = SEED) -> dict:
    """모은 조각을 저장하고 대기열을 늘린다. 같은 글(같은 id)은 한 번만, 원천 하나 · 출처 한쪽마다 cap 개까지."""
    with _lock():
        have = {p.id: p for p in load_pieces()}
        used = Counter((source_key(p), p.origin) for p in have.values())
        added, dup, capped = [], 0, 0
        for p in _spread(cands):
            if p.id in have:
                dup += 1
                continue
            k = (source_key(p), p.origin)
            if used[k] >= cap:
                capped += 1
                continue
            used[k] += 1
            have[p.id] = p
            added.append(p)
            save_json(_piece_path(p.id), p.model_dump())
        q = extend_queue(load_queue(), list(have.values()), seed, set(_firsts(load_labels())))
        save_json(_dir() / "queue.json", q)
    return {"added": len(added), "dup": dup, "capped": capped, "by_origin": dict(Counter(p.origin for p in added))}


# ---------- 대기열과 판정 ----------

def eligible(p: SoePiece) -> bool:
    """가려 읽기에 넣을 조각: 사람 글이나 AI 글이고, 작가가 읽은 글이 아니고, 고친 글이 아니다."""
    return p.origin in ("human", "ai") and not p.known and p.source.kind != "edit"


def extend_queue(q: dict, pieces: list[SoePiece], seed: int = SEED, judged: frozenset[str] | set[str] = frozenset()) -> dict:
    """대기열에 새 조각을 넣고 판정하지 않은 자리를 다시 짠다. 판정한 조각의 자리와 다시 읽기 예정은 바꾸지 않는다.

    - 다시 읽기: 새로 들어온 조각을 시드로 섞어 세 개씩 묶고 묶음마다 하나를 고른다(1/3). 남은 한두 개는 carry 로 다음에 묶는다.
      그래서 다시 읽기는 모을 때 정해지고, 뒤에 더 모아도 바뀌지 않는다.
    - 차례(판정하지 않은 자리): 처음 FIRST 자리는 묶음마다 한 조각(모자라면 두 조각, doubled), 사람 · AI 를 번갈아,
      다시 읽기 예정 조각을 세 자리에 하나꼴로(세 자리 안 어디인지는 시드로 섞음), 앞 조각과 다른 모델을 먼저. 사람 글을 먼저 모으고 AI 글을 뒤에 모아도 섞인다."""
    q = {"carry": [], **q, "order": list(q["order"]), "redo": list(q["redo"])}
    seed = q.get("seed", seed)
    by_id = {p.id: p for p in pieces}
    old = [x for x in q["order"] if x in by_id]
    new = sorted((p.id for p in pieces if eligible(p) and p.id not in set(old)))
    random.Random(f"{seed}:{len(old)}").shuffle(new)
    redo = [x for x in q["redo"] if x in by_id]
    pend = [x for x in q["carry"] if x in by_id] + new
    while len(pend) >= REDO_EVERY:
        tri, pend = pend[:REDO_EVERY], pend[REDO_EVERY:]
        redo.append(random.Random(f"{seed}:redo:{tri[0]}").choice(tri))
    q["carry"], q["redo"] = pend, redo
    redo_set = set(redo)

    order = [x for x in old if x in judged]
    rest = [x for x in old if x not in judged] + new
    rank = {x: i for i, x in enumerate(rest)}
    first_groups = Counter(by_id[x].group for x in order[:FIRST])
    all_groups = Counter(by_id[x].group for x in order)
    sides = Counter(by_id[x].origin for x in order)
    redos = sum(x in redo_set for x in order)
    while rest:
        in_first = len(order) < FIRST
        pool = rest
        if in_first:
            pool = [x for x in rest if first_groups[by_id[x].group] < 1] or [x for x in rest if first_groups[by_id[x].group] < 2] or rest
        last = by_id[order[-1]] if order else None
        want = min(("human", "ai"), key=lambda o: sides[o])
        k = len(order)  # 세 자리마다 다시 읽기 자리 하나. 자리는 시드로 섞는다(늘 1 · 4 · 7번째면 이번 10개 정답 카드에서 차례가 드러난다)
        want_redo = k % REDO_EVERY == random.Random(f"{seed}:slot:{k // REDO_EVERY}").randrange(REDO_EVERY) and redos < (k + REDO_EVERY) // REDO_EVERY
        pick = min(pool, key=lambda x: (all_groups[by_id[x].group], by_id[x].origin != want, (x in redo_set) != want_redo,
                                        bool(last and by_id[x].model and by_id[x].model == last.model), rank[x]))
        rest.remove(pick)
        order.append(pick)
        if in_first:
            first_groups[by_id[pick].group] += 1
        all_groups[by_id[pick].group] += 1
        sides[by_id[pick].origin] += 1
        redos += pick in redo_set
    q["order"] = order
    q["doubled"] = any(c > 1 for c in Counter(by_id[x].group for x in order[:FIRST]).values())
    return q


def _firsts(labels: list[SoeLabel]) -> dict[str, SoeLabel]:
    """조각마다 첫 판정 (재판정이 아닌 첫 줄)."""
    out: dict[str, SoeLabel] = {}
    for lb in labels:
        if lb.kind == "piece" and not lb.redo_of and lb.piece not in out:
            out[lb.piece] = lb
    return out


def _redos(labels: list[SoeLabel]) -> dict[str, SoeLabel]:
    out: dict[str, SoeLabel] = {}
    for lb in labels:
        if lb.kind == "piece" and lb.redo_of and lb.piece not in out:
            out[lb.piece] = lb
    return out


def hidden_ids(q: Optional[dict] = None, labels: Optional[list[SoeLabel]] = None) -> set[str]:
    """가린 조각: 대기열에 있고 아직 판정하지 않은 조각 + 다시 읽기 예정이고 아직 재판정하지 않은 조각."""
    q = q or load_queue()
    labels = load_labels() if labels is None else labels
    done, redone = _firsts(labels), _redos(labels)
    return {x for x in q["order"] if x not in done} | {x for x in q["redo"] if x not in redone}


def open_batch(q: Optional[dict] = None, labels: Optional[list[SoeLabel]] = None) -> set[str]:
    """아직 끝나지 않은 '이번 10개'에서 판정한 조각. 10개를 채우거나 대기열이 바닥나야 끝난다. 끝나기 전에는 정답을 보이지 않는다."""
    q = q or load_queue()
    labels = load_labels() if labels is None else labels
    firsts = list(_firsts(labels).values())
    k = len(firsts) % BATCH
    if not k or not any(x not in {lb.piece for lb in firsts} for x in q["order"]):
        return set()
    return {lb.piece for lb in firsts[-k:]}


def masked_ids(q: Optional[dict] = None, labels: Optional[list[SoeLabel]] = None) -> set[str]:
    """화면 응답에서 출처 · 원천 · 묶음 · 모델 · 지표 값을 빼는 조각: 가린 조각(hidden_ids) + 끝나지 않은 '이번 10개'의 조각."""
    q = q or load_queue()
    labels = load_labels() if labels is None else labels
    return hidden_ids(q, labels) | open_batch(q, labels)


def corpus_key(pieces: list[SoePiece]) -> str:
    """말뭉치 지문: 조각 id 들과 지표 판. 바뀌면 보고서를 다시 채점해야 한다."""
    return hashlib.sha1(json.dumps([metrics.METRICS_VERSION, sorted(p.id for p in pieces)]).encode()).hexdigest()[:12]


def labels_key(labels: list[SoeLabel]) -> str:
    """판정 지문: 보고서에 들어간 판정 id 들."""
    return hashlib.sha1(json.dumps(sorted(lb.id for lb in labels)).encode()).hexdigest()[:12]


def next_piece() -> str:
    """판정할 다음 조각 id. 다 읽었으면 빈 값."""
    done = _firsts(load_labels())
    return next((x for x in load_queue()["order"] if x not in done), "")


def _day(at: str) -> date:
    return datetime.fromisoformat(at).date()


def redo_open(pid: str, labels: Optional[list[SoeLabel]] = None) -> Optional[date]:
    """그 조각을 다시 읽을 수 있는 날 (첫 판정 + 7일). 첫 판정 전이면 None."""
    first = _firsts(load_labels() if labels is None else labels).get(pid)
    return _day(first.at) + timedelta(days=REDO_DAYS) if first else None


def redo_due(today: Optional[date] = None) -> list[str]:
    """지금 다시 읽을 수 있는 조각 (다시 읽기 예정 · 첫 판정 7일 뒤 · 아직 재판정 전). 차례는 섞는다."""
    today = today or date.today()
    labels = load_labels()
    redone = _redos(labels)
    out = [x for x in load_queue()["redo"] if x not in redone and (d := redo_open(x, labels)) and d <= today]
    random.Random(f"{SEED}:due:{today.isoformat()}").shuffle(out)
    return out


def _new_label(pid: str, verdict: str, spans, clean: bool, seconds: int, now: Optional[datetime], **kw) -> SoeLabel:
    if verdict not in ("ai", "human", "unsure"):
        raise ValueError("판정은 ai · human · unsure 가운데 하나예요")
    now = now or datetime.now().astimezone()
    return SoeLabel(id=hashlib.sha1(f"{pid}:{now.isoformat()}:{os.getpid()}:{threading.get_ident()}".encode()).hexdigest()[:12],
                    at=now.isoformat(timespec="seconds"), piece=pid, verdict=verdict,
                    spans=[x if isinstance(x, SoeSpan) else SoeSpan(**x) for x in (spans or [])], clean=clean,
                    metrics_version=metrics.METRICS_VERSION, seconds=seconds, **kw)


def judge(pid: str, verdict: str, spans=None, clean: bool = False, seconds: int = 0, now: Optional[datetime] = None) -> SoeLabel:
    """가려 읽기 첫 판정. 대기열에 있고 아직 판정하지 않은 조각만. '이번 10개'는 판정 차례로 정한다."""
    with _lock():
        q, labels = load_queue(), load_labels()
        firsts = _firsts(labels)
        if pid not in q["order"]:
            raise ValueError("판정 대기열에 없는 조각이에요")
        if pid in firsts:
            raise ValueError("이미 판정한 조각이에요")
        return append_label(_new_label(pid, verdict, spans, clean, seconds, now, batch=f"b{len(firsts) // BATCH + 1}"))


def redo(pid: str, verdict: str, spans=None, clean: bool = False, seconds: int = 0, now: Optional[datetime] = None) -> SoeLabel:
    """다시 읽기(재판정). 다시 읽기 예정 조각만, 첫 판정 7일 뒤부터."""
    with _lock():
        q, labels = load_queue(), load_labels()
        if pid not in q["redo"]:
            raise ValueError("다시 읽기 예정이 아닌 조각이에요")
        if pid in _redos(labels):
            raise ValueError("이미 다시 읽은 조각이에요")
        first = _firsts(labels).get(pid)
        if not first:
            raise ValueError("아직 첫 판정을 하지 않은 조각이에요")
        opens = _day(first.at) + timedelta(days=REDO_DAYS)
        today = (now or datetime.now().astimezone()).date()
        if today < opens:
            raise ValueError(f"{opens.month}월 {opens.day}일부터 다시 읽을 수 있어요")
        return append_label(_new_label(pid, verdict, spans, clean, seconds, now, redo_of=first.id))


def remove_label(label_id: str) -> None:
    """판정 지우기: removed 가 참인 같은 id 줄을 덧붙인다."""
    append_label(SoeLabel(id=label_id, at=datetime.now().astimezone().isoformat(timespec="seconds"), removed=True))


# ---------- 채점 (저장하지 않고 다시 잼) ----------

_cache: dict[tuple[str, str], dict[str, Optional[float]]] = {}
_proj_cache: dict[str, Optional[Project]] = {}


def _project(name: str) -> Optional[Project]:
    if name not in _proj_cache:
        try:
            _proj_cache[name] = store.load_view(name)
        except (FileNotFoundError, ValueError, OSError):
            _proj_cache[name] = None
    return _proj_cache[name]


def features(p: SoePiece) -> dict[str, Optional[float]]:
    """조각의 지표 값 {지표 id: 값}. 잴 수 없으면 None. 열쇠 (METRICS_VERSION, 조각 id) 로 메모리에만 둔다."""
    key = (metrics.METRICS_VERSION, p.id)
    if key in _cache:
        return _cache[key]
    m = metrics.measure(p.text)
    r = metrics.rates_per_1k(p.text)
    out: dict[str, Optional[float]] = {k: getattr(m, k) for k in MEASURED}
    out["ai_patterns"] = r.get("ai_patterns")
    out["cliches"] = r.get("cliches")
    out["repeated_per_1k"] = round(len(m.repeated_phrases) * 1000 / m.chars, 3) if m.chars else None
    out["style_distance"] = out["copied_per_1k"] = None
    proj = _project(p.baseline) if p.baseline else None
    if proj is not None and p.source.kind in ("episode", "trial"):
        if proj.style_baseline:
            out["style_distance"] = metrics.style_distance(proj.style_baseline, p.text)
        passages = proj.style.sample_passages if proj.style else []
        if passages:
            out["copied_per_1k"] = round(len(metrics.copied_sentences(p.text, passages)) * 1000 / m.chars, 3)
    _cache[key] = out
    return out


# ---------- 보고서 ----------

def _paired(pieces: list[SoePiece]) -> set[str]:
    """짝이 있는 조각 (가르는 힘에서 뺀다. 짝은 같은 방향 비율로 따로 잰다)."""
    out = {p.id for p in pieces if p.pair_of}
    return out | {p.pair_of for p in pieces if p.pair_of}


def _by_group(rows: list[tuple[SoePiece, float]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for p, v in rows:
        out[p.group].append(v)
    return dict(out)


def _rnd(x: Optional[float], k: int = 3) -> Optional[float]:
    return None if x is None or x != x else round(x, k)


def separation(pos: list[tuple[SoePiece, float]], neg: list[tuple[SoePiece, float]], direction: Optional[int],
               weights: list[dict[str, int]], level: float = labstats.SIM_LEVEL, total_groups: int = 0) -> dict:
    """가르는 힘 한 칸: pos(AI 쪽) 가 neg(사람 쪽) 보다 그 방향으로 클 확률과 묶음 부트스트랩 범위, 칩.
    방향이 없는 지표는 관찰한 쪽으로 보인다(dir). 한쪽에 묶음 8개 · 조각 10개가 안 되면 칩 few."""
    pg, ng = _by_group(pos), _by_group(neg)
    out = {"ai_pieces": len(pos), "human_pieces": len(neg), "ai_groups": len(pg), "human_groups": len(ng)}
    v = labstats.auroc([x for _, x in pos], [x for _, x in neg])
    if v is None:
        return {**out, "value": None, "chip": "na"}  # 한쪽에 잰 값이 없음 (작품 화에만 있는 지표 등)
    dist = labstats.auroc_boot(pg, ng, weights=weights)
    lo95, hi95 = labstats.interval(dist, labstats.SHOW_LEVEL)
    lo, hi = labstats.interval(dist, level)
    d = direction or (1 if v >= 0.5 else -1)
    if d < 0:
        v, lo95, hi95, lo, hi = 1 - v, 1 - hi95, 1 - lo95, 1 - hi, 1 - lo
        dist = [1 - x for x in dist]
    p = 2 * min(sum(x <= 0.5 for x in dist), sum(x >= 0.5 for x in dist)) / len(dist) if dist else 1.0
    chip = labstats.verdict(lo, hi, v)
    if direction is None and chip == "reverse":
        chip = "none"
    if min(len(pg), len(ng)) < SIDE_GROUPS or min(len(pos), len(neg)) < SIDE_PIECES:
        chip = "few"
    elif chip == "yes" and total_groups and total_groups < FULL_GROUPS:
        chip = "weak"
    return {**out, "value": _rnd(v), "dir": d, "ci95": [_rnd(lo95), _rnd(hi95)], "ci": [_rnd(lo), _rnd(hi)],
            "level": level, "p": min(1.0, p), "chip": chip}


def _model_split(rows: list[dict]) -> bool:
    """한 모델에서 '맞아요'인데 다른 모델에서 '근거 없음'이나 '반대 방향'이면 '모델마다 달라요'."""
    chips = {r["chip"] for r in rows if r["chip"] != "few"}
    return "yes" in chips and bool(chips & {"none", "reverse"})


def _redo_pairs(labels: list[SoeLabel]) -> list[tuple[str, str]]:
    firsts = {lb.id: lb for lb in labels if lb.kind == "piece" and not lb.redo_of}
    return [(firsts[lb.redo_of].verdict, lb.verdict) for lb in _redos(labels).values() if lb.redo_of in firsts]


def consistency(labels: list[SoeLabel], seed: int = SEED, n_boot: int = labstats.BOOT) -> dict:
    """판정 일관성 (Cohen κ, 재판정 짝). 30개 아래면 미리보기, 하한이 0.3 아래면 결론 보류."""
    pairs = _redo_pairs(labels)
    k = labstats.kappa([a for a, _ in pairs], [b for _, b in pairs])
    lo, hi = labstats.kappa_boot(pairs, n_boot, seed)
    hold = len(pairs) < labstats.KAPPA_MIN or not (lo == lo and lo >= labstats.KAPPA_HOLD)
    return {"pairs": len(pairs), "kappa": _rnd(k), "ci95": [_rnd(lo), _rnd(hi)], "preview": len(pairs) < labstats.KAPPA_MIN,
            "hold": hold, "hold_below": labstats.KAPPA_HOLD}


def _sent_of(spans: list[tuple[int, int]], at: int) -> int:
    """글자 자리 at 이 든 문장 번호. 문장 사이 빈칸이면(정규식이 앞 빈칸부터 잡을 때) 다음 문장."""
    return next((i for i, (a, b) in enumerate(spans) if at < b), -1)


def pattern_table(pieces: dict[str, SoePiece], labels: list[SoeLabel]) -> list[dict]:
    """패턴 혼동표 (Q3): 문장 단위로 정규식 적중과 작가 표시를 맞춘다. 표시가 있거나 '표시할 곳 없음'인 판정만 센다.
    정밀도 = 정규식이 잡은 문장 가운데 작가도 표시한 문장, 재현율 = 작가가 그 갈래로 표시한 문장 가운데 정규식도 잡은 문장."""
    names = [n for n, _, _ in metrics.AI_PATTERNS] + ["cliche"]
    hits: dict[str, set] = defaultdict(set)
    marked_any: set = set()
    marked: dict[str, set] = defaultdict(set)
    other = 0
    for pid, lb in _firsts(labels).items():
        p = pieces.get(pid)
        if p is None or not (lb.clean or lb.spans):
            continue
        sents = metrics.sentence_spans(p.text)
        for s in metrics.pattern_spans(p.text):
            hits[s.name if s.kind == "pattern" else "cliche"].add((pid, _sent_of(sents, s.start)))
        for sp in lb.spans:
            other += sp.kind == "other"
            for i, (a, b) in enumerate(sents):
                if sp.start < b and sp.end > a:
                    marked_any.add((pid, i))
                    marked[sp.kind].add((pid, i))
    out = []
    for n in names:
        h, m = hits[n], marked[n]
        both, found = len(h & marked_any), len(m & h)
        out.append({"pattern": n, "hits": len(h), "marked_too": both, "precision": _rnd(both / len(h)) if h else None,
                    "precision_ci": [_rnd(x) for x in labstats.wilson(both, len(h))], "marked": len(m), "found": found,
                    "recall": _rnd(found / len(m)) if m else None, "recall_ci": [_rnd(x) for x in labstats.wilson(found, len(m))],
                    "few": len(h) < 5})
    return out + [{"pattern": "other", "marked": other}]


def report(seed: int = SEED, n_boot: int = labstats.BOOT, save: bool = True) -> dict:
    """첫 판별력 보고서. LLM 호출 없음. 출처 기준(Q1) · revlab 짝 · 작가 판정 기준(Q2) · 패턴(Q3) · 판정 일관성(Q4) ·
    모델별 참고 칸 · 고친 글 · 같은 것을 재는 지표. 가린 조각(masked_ids)은 조각별 줄에 싣지 않는다(모은 숫자에는 들어간다).
    아직 끝나지 않은 '이번 10개'의 판정은 작가 판정 기준 · 패턴 · 판정 일관성에도 넣지 않는다(판정 중에 다시 채점해도 정답이 새지 않게)."""
    _proj_cache.clear()
    pieces = load_pieces()
    by_id = {p.id: p for p in pieces}
    q = load_queue()
    all_labels = load_labels()
    hidden = hidden_ids(q, all_labels)
    opened = open_batch(q, all_labels)
    masked = hidden | opened
    labels = [lb for lb in all_labels if lb.piece not in opened]
    feats = {p.id: features(p) for p in pieces}
    paired = _paired(pieces)
    free = [p for p in pieces if p.id not in paired and p.origin in ("human", "ai")]
    groups = sorted({p.group for p in free})
    weights = labstats.boot_weights(groups, n_boot, seed)
    models = sorted({p.model or "unknown" for p in free if p.origin == "ai"})
    humans = [p for p in free if p.origin == "human"]
    genres = sorted({p.genre for p in humans})

    firsts = _firsts(labels)
    judged = [(by_id[k], lb.verdict) for k, lb in firsts.items() if k in by_id and lb.verdict in ("ai", "human")]
    a_groups = sorted({p.group for p, _ in judged})
    a_weights = labstats.boot_weights(a_groups, n_boot, seed + 1)
    cons = consistency(labels, seed, n_boot)
    first_round = len(firsts) <= FIRST

    rows = []
    for mid, label, direction, where in METRICS:
        def vals(ps):
            return [(p, feats[p.id][mid]) for p in ps if feats[p.id][mid] is not None]
        ai = vals([p for p in free if p.origin == "ai"])
        hu = vals(humans)
        src = separation(ai, hu, direction, weights, total_groups=len(groups))
        d = src.get("dir") or direction  # 양쪽 지표는 출처 기준에서 관찰한 쪽. 그것도 없으면 칸마다 관찰한 쪽
        by_model = []
        for m in models:
            r = separation(vals([p for p in free if p.origin == "ai" and (p.model or "unknown") == m]), hu, d, weights,
                           level=labstats.SHOW_LEVEL)
            by_model.append({"model": m, **{k: r.get(k) for k in ("value", "ci95", "chip", "ai_pieces", "ai_groups")}})
        by_genre = []
        if len(genres) > 1:
            for g in genres:
                r = separation(ai, vals([p for p in humans if p.genre == g]), d, weights, level=labstats.SHOW_LEVEL)
                by_genre.append({"genre": g, **{k: r.get(k) for k in ("value", "ci95", "chip", "human_pieces", "human_groups")}})
        pair = _pair_rows(pieces, feats, mid, d or 1)
        author = None
        if len(judged) >= AUTHOR_MIN:
            jv = [(p, feats[p.id][mid], v) for p, v in judged if feats[p.id][mid] is not None]
            author = separation([(p, x) for p, x, v in jv if v == "ai"], [(p, x) for p, x, v in jv if v == "human"], d,
                                a_weights, total_groups=len(a_groups))
            if author["chip"] == "none" and first_round:
                author["chip"] = "tbd"
            if cons["hold"]:
                author["held"] = True
        rows.append({"id": mid, "label": label, "where": where, "direction": DIR_TEXT[d], "source": src, "by_model": by_model,
                     "model_split": _model_split(by_model), "by_genre": by_genre, "pairs": pair, "author": author})
    holm = labstats.holm([r["source"].get("p", 1.0) for r in rows])
    for r, p in zip(rows, holm):
        r["source"]["p_holm"] = _rnd(p, 4)

    notes = []
    if len(groups) < FULL_GROUPS:
        notes.append("묶음이 적어 범위가 실제보다 좁게 나올 수 있어요")
    if humans and genres == ["literary"]:
        notes.append("사람 쪽이 근대 소설뿐이라 시대와 갈래 차이를 재고 있을 수 있어요")
    if len(models) == 1:
        notes.append("모델이 하나뿐이라 결과가 그 모델 글 기준이에요")
    if q.get("doubled"):
        notes.append("같은 화에서 2조각씩이라 1차 결과가 약할 수 있어요")

    rep = {
        "made": datetime.now().astimezone().isoformat(timespec="seconds"),
        "metrics_version": metrics.METRICS_VERSION, "seed": seed, "boot": n_boot,
        "input": hashlib.sha1(json.dumps([sorted(by_id), sorted(lb.id for lb in labels), q["order"], q["redo"]]).encode()).hexdigest()[:12],
        "corpus": corpus_key(pieces), "labeled": labels_key(labels),
        "counts": {"pieces": len(pieces), "groups": len(groups), "free": len(free),
                   "paired": sum(p.id in paired and p.source.kind == "revlab" for p in pieces),
                   "by_origin": dict(Counter(p.origin for p in pieces)),
                   "by_model": dict(Counter(p.model or "unknown" for p in pieces if p.origin == "ai")),
                   "by_source": dict(Counter(p.source.kind for p in pieces)),
                   "queue": len(q["order"]), "redo": len(q["redo"]), "judged": len(firsts), "hidden": len(hidden)},
        "notes": notes, "first_round": first_round, "consistency": cons, "metrics": rows,
        "same": _same_pairs(free, feats), "patterns": pattern_table(by_id, labels), "edits": _edit_rows(pieces, feats),
        "pieces": [{"id": p.id, "origin": p.origin, "model": p.model, "group": p.group, "source": p.source.kind,
                    "chars": p.chars, "values": feats[p.id]} for p in pieces if p.id not in masked],
    }
    rep["id"] = f"{date.today().isoformat()}-{rep['input'][:6]}-s{seed}"
    if save:
        save_json(_dir() / "reports" / f"{rep['id']}.json", rep)
    return rep


def _pair_rows(pieces: list[SoePiece], feats: dict, mid: str, d: int) -> dict:
    """revlab 짝 같은 방향 비율: 화와 되쓰기 종류마다 (되쓰기 평균 − 원문 평균) 이 AI 쪽 방향인지."""
    sides: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: {"human": [], "ai": []})
    for p in pieces:
        v = feats[p.id][mid]
        if p.source.kind != "revlab" or v is None:
            continue
        if p.origin == "human":
            for take in ("take", "take_style"):
                sides[(p.group, take)]["human"].append(v)
        elif p.origin == "ai":
            sides[(p.group, p.source.take)]["ai"].append(v)
    diffs = [d * (mean(s["ai"]) - mean(s["human"])) for s in sides.values() if s["ai"] and s["human"]]
    r = labstats.pair_agree(diffs)
    return {**{k: _rnd(v) if isinstance(v, float) else v for k, v in r.items()}, "same_side": r["n"] > 0 and r["lo"] > 0.5}


def _same_pairs(pieces: list[SoePiece], feats: dict) -> list[dict]:
    """같은 것을 재는 지표 (Spearman ρ > 0.8)."""
    out = []
    for i, a in enumerate(METRIC_IDS):
        for b in METRIC_IDS[i + 1:]:
            xs = [(feats[p.id][a], feats[p.id][b]) for p in pieces if feats[p.id][a] is not None and feats[p.id][b] is not None]
            rho = labstats.spearman([x for x, _ in xs], [y for _, y in xs])
            if rho is not None and rho > 0.8:
                out.append({"a": a, "b": b, "rho": _rnd(rho), "n": len(xs)})
    return out


def _edit_rows(pieces: list[SoePiece], feats: dict) -> list[dict]:
    """'쇠맛 줄이기'로 고친 글에서 지표가 사람 쪽으로 움직였는지 (지표가 못 보는 차이). 보기만 한다."""
    by_id = {p.id: p for p in pieces}
    pairs = [(by_id[p.pair_of], p) for p in pieces if p.source.kind == "edit" and p.pair_of in by_id]
    out = []
    for mid, label, direction, _ in METRICS:
        if direction is None:
            continue
        moves = Counter()
        for b, a in pairs:
            x, y = feats[b.id][mid], feats[a.id][mid]
            if x is not None and y is not None:
                moves["less" if y < x else "more" if y > x else "same"] += 1
        if moves:
            out.append({"id": mid, "label": label, "pairs": sum(moves.values()), **moves})
    return out


# ---------- 보기 · 내보내기 ----------

def view() -> dict:
    """말뭉치와 판정 진행 (가린 조각의 출처 · 지표는 싣지 않는다). 명령줄 collect 와 화면(PR3)이 쓴다."""
    pieces = load_pieces()
    q, labels = load_queue(), load_labels()
    hidden = hidden_ids(q, labels)
    firsts = _firsts(labels)
    side_groups = {o: len({p.group for p in pieces if p.origin == o and eligible(p)}) for o in ("human", "ai")}
    return {
        "pieces": len(pieces), "hidden": len(hidden),
        "by_origin": dict(Counter(p.origin for p in pieces)),  # 모은 수는 실어도 된다 (조각별 출처는 싣지 않음)
        "groups": len({p.group for p in pieces}),
        "ai_models": dict(Counter(p.model or "unknown" for p in pieces if p.origin == "ai")),
        "known": sum(p.known for p in pieces), "eligible_groups": side_groups,
        "queue": len(q["order"]), "first": min(len(q["order"]), FIRST), "doubled": q.get("doubled", False),
        "redo": len(q["redo"]), "judged": len(firsts), "redone": len(_redos(labels)),
        "metrics_version": metrics.METRICS_VERSION,
    }


def export(include_hidden: bool = False) -> dict:
    """지표와 판정만 내보낸다. 원문 · 표시한 글(quote) · 메모는 넣지 않는다. 가린 조각은 기본으로 뺀다."""
    pieces = load_pieces()
    labels = load_labels()
    hidden = set() if include_hidden else masked_ids(None, labels)
    keep = [p for p in pieces if p.id not in hidden]
    ids = {p.id for p in keep}
    return {
        "metrics_version": metrics.METRICS_VERSION, "made": datetime.now().astimezone().isoformat(timespec="seconds"),
        "left_out": len(pieces) - len(keep),
        "pieces": [{"id": p.id, "origin": p.origin, "model": p.model, "model_source": p.model_source, "group": p.group,
                    "genre": p.genre, "source": p.source.kind, "known": p.known, "pair_of": p.pair_of if p.pair_of in ids else "",
                    "chars": p.chars, "values": features(p)} for p in keep],
        "labels": [{"id": lb.id, "at": lb.at, "kind": lb.kind, "piece": lb.piece, "verdict": lb.verdict, "clean": lb.clean,
                    "batch": lb.batch, "redo_of": lb.redo_of, "metrics_version": lb.metrics_version, "seconds": lb.seconds,
                    "spans": [{"start": s.start, "end": s.end, "kind": s.kind} for s in lb.spans]}
                   for lb in labels if lb.piece in ids],
    }


def describe(rep: dict) -> str:
    """보고서를 명령줄 글로."""
    c = rep["counts"]
    o = c["by_origin"]
    lines = [f"지표 버전 {rep['metrics_version']} · 조각 {c['pieces']} (사람 {o.get('human', 0)} · AI {o.get('ai', 0)} · 고친 글 {o.get('edited', 0)}) · "
             f"묶음 {c['groups']} · 시드 {rep['seed']} · 부트스트랩 {rep['boot']}번",
             f"짝 없는 조각 {c['free']}개로 가르는 힘을 쟀어요. 짝(역설계 원문 ↔ 되쓰기) {c['paired']}개는 같은 방향 비율로 따로 봐요."]
    if c["by_model"]:
        lines.append("AI 글 모델: " + ", ".join(f"{m} {n}" for m, n in sorted(c["by_model"].items())))
    lines += [f"! {n}" for n in rep["notes"]]
    lines.append("")
    lines.append("지표 · 방향 · 출처 기준 가르는 힘 [95% 범위] · 칩 · 짝 같은 방향")

    def cell(s):
        if s is None:
            return "–"
        if s.get("value") is None:
            return f"– ({CHIP[s['chip']]})"
        return f"{s['value']:.2f} [{s['ci95'][0]:.2f}–{s['ci95'][1]:.2f}] {CHIP[s['chip']]}"
    for r in rep["metrics"]:
        pr = r["pairs"]
        pair = f"{pr['agree']}/{pr['n']}" + (" 같은 쪽" if pr["same_side"] else "") if pr["n"] else "–"
        split = " · 모델마다 달라요" if r["model_split"] else ""
        lines.append(f"  {r['label']} · {r['direction']} · {cell(r['source'])}{split} · 짝 {pair}")
        for m in r["by_model"]:
            if len(r["by_model"]) > 1:  # 모델별 칸은 칩 없이 95% 범위만 (표본 부족만 적는다)
                note = "표본 부족" if m["chip"] == "few" else "참고"
                val = f"{m['value']:.2f} [{m['ci95'][0]:.2f}–{m['ci95'][1]:.2f}]" if m.get("value") is not None else "–"
                lines.append(f"      사람 대 {m['model']}: {val} {note}")
    cons = rep["consistency"]
    lines.append("")
    lines.append(f"판정 {c['judged']}개 · 다시 읽기 {cons['pairs']}개" + (
        f" · 판정 일관성 {cons['kappa']} [{cons['ci95'][0]}–{cons['ci95'][1]}]" if cons["kappa"] is not None else "")
        + (" · 보류" if cons["hold"] else ""))
    if not c["judged"]:
        lines.append(f"작가 판정 기준 가르는 힘은 판정 {AUTHOR_MIN}개부터 보여요.")
    if rep["same"]:
        lines.append("같은 것을 재는 지표: " + ", ".join(f"{s['a']} ~ {s['b']} (ρ {s['rho']})" for s in rep["same"]))
    return "\n".join(lines)


# ---------- 화면 값 (static/soelab.js, 웹 /api/soelab/...) ----------
# 가린 조각(masked_ids)의 출처 · 원천 · 묶음 · 모델 · 지표 값 · 정규식 밑줄은 어느 응답에도 싣지 않는다.
# 정답은 '이번 10개'가 끝난 뒤에만(batch_reveal), 다시 읽기 예정 조각은 재판정 뒤에만 보인다.

ROUND_GOALS = (FIRST, 60, GOAL)   # 1차 40 → 두 번째 보고 60 → 목표 90
REDO_HELD = 45                    # 판정 일관성이 보류되면 재판정을 이만큼으로 늘린다 (명세 4.6)
CHECK_PER = 20                    # 패턴 확인: 패턴마다 이만큼까지
CHECK_KINDS = [n for n, _, _ in metrics.AI_PATTERNS] + ["cliche"]
KIND_LABELS = {"부정 후 재정의": "부정 후 재정의", "셋씩 나열": "셋씩 나열", "감정 이름 서술": "감정 이름", "번역투": "번역투",
               "서식 흔적": "서식 흔적", "cliche": "상투 표현", "copy": "옮김", "other": "기타"}
SPAN_KINDS = list(KIND_LABELS)    # 문장 표시 갈래 8 (화면 차례)
SECONDS_MAX = 3600                # 판정 하나에 센 시간의 상한 (자리를 비운 시간을 크게 세지 않게)
METRIC_DEFS = {
    "ai_patterns": "정규식 다섯 갈래(부정 후 재정의 · 셋씩 나열 · 감정 이름 · 번역투 · 서식 흔적)가 1,000자에 몇 번 걸리는지예요. 한 화 상한은 쓰지 않아요.",
    "cliches": "자주 보이는 상투 표현(DEFAULT_CLICHES)이 1,000자에 몇 번 나오는지예요.",
    "comma_sentence_ratio": "쉼표가 들어간 문장의 몫이에요.",
    "short_ending_ratio": "짧은 문장으로 끝나는 문단의 몫이에요.",
    "pronoun_per_1k": "'그는 · 그녀가' 같은 대명사가 1,000자에 몇 번 나오는지예요.",
    "sentence_len_mean": "문장 하나의 평균 글자 수예요.",
    "sentence_len_cv": "문장 길이가 얼마나 들쭉날쭉한지예요(표준편차 ÷ 평균). 낮을수록 리듬이 단조로워요.",
    "paragraph_len_mean": "문단 하나의 평균 글자 수예요.",
    "dialogue_ratio": "따옴표 안 글자의 몫이에요.",
    "past_tense_ratio": "'~다'로 끝나는 서술 문장 가운데 과거형의 몫이에요.",
    "mattr": "100낱말 창으로 잰 어휘 다양도예요. 원래 이름은 MATTR이에요.",
    "repeated_per_1k": "되풀이된 구가 1,000자에 몇 개인지예요.",
    "style_distance": "작품 기준 원문과 문체가 얼마나 먼지예요. 기준 원문이 있는 작품 화에서만 재요.",
    "copied_per_1k": "작품 예시 문단과 12자 넘게 똑같이 이어지는 문장이 1,000자에 몇 개인지예요.",
}


def threshold_text(mid: str) -> str:
    """지금 경고 기준 (metrics.py 의 값을 그대로 글로)."""
    if mid in metrics.THRESHOLDS:
        _, limit, rel = metrics.THRESHOLDS[mid]
        sign = "+" if mid in metrics.UPPER_ONLY else "±"
        return f"기준 {sign}{limit:.0%}" if rel else f"기준 {sign}{limit:g}"
    return {"ai_patterns": "화당 상한", "cliches": "1번부터", "repeated_per_1k": "1개부터",
            "style_distance": f"> {metrics.STYLE_DISTANCE_WARN:g}", "copied_per_1k": f"{metrics.COPY_SPAN}자"}.get(mid, "–")


def model_label(model: str) -> str:
    """'claude:claude-code-default' → 'Claude'. 모르면 '모름'."""
    b = (model or "").split(":")[0]
    return {"claude": "Claude", "gemini": "Gemini", "other": "그 밖", "mock": "mock", "": "모름", "unknown": "모름"}.get(b, b)


def source_label(p: SoePiece) -> str:
    """원천 한 줄 이름 (점 그림 줄 · 조각 목록)."""
    s = p.source
    if s.kind == "revlab":
        return "역설계 원문" if s.take == "text" else "역설계 되쓰기"
    if s.kind == "research":
        return "근대 소설" if p.genre == "literary" else "연구 말뭉치"
    return {"episode": "작품 화", "edit": "수정 기록", "paste": "붙여 넣은 글", "trial": "조건 실험"}[s.kind]


def _state_path() -> Path:
    return _dir() / "state.json"


def load_state() -> dict:
    """가려 읽기 진행 상태: goal(이번 목표 40 · 60 · 90), stopped('여기서 멈추기'), seen(정답 카드를 넘긴 '이번 10개' 번호)."""
    path = _state_path()
    st = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"goal": FIRST, "stopped": False, "seen": 0, **st}


def set_state(**kw) -> dict:
    with _lock():
        st = load_state()
        if "goal" in kw and kw["goal"] not in ROUND_GOALS:
            raise ValueError(f"목표는 {' · '.join(map(str, ROUND_GOALS))} 가운데 하나예요")
        st.update({k: v for k, v in kw.items() if k in ("goal", "stopped", "seen")})
        save_json(_state_path(), st)
    return st


def _report_files() -> list[Path]:
    d = _dir() / "reports"
    return sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime) if d.exists() else []


def latest_report() -> Optional[dict]:
    files = _report_files()
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def report_summary(rep: Optional[dict]) -> Optional[dict]:
    """화면에 보낼 보고서: 조각별 줄을 빼고 지금 경고 기준 글을 붙인다."""
    if not rep:
        return None
    out = {k: v for k, v in rep.items() if k != "pieces"}
    out["metrics"] = [{**r, "threshold": threshold_text(r["id"])} for r in rep["metrics"]]
    return out


def reports() -> list[dict]:
    """기록 화면: 보고서 목록 (새것부터)."""
    out = []
    for f in reversed(_report_files()):
        r = json.loads(f.read_text(encoding="utf-8"))
        c = r.get("counts", {})
        out.append({"id": r.get("id", f.stem), "made": r.get("made", ""), "metrics_version": r.get("metrics_version", ""),
                    "pieces": c.get("pieces", 0), "groups": c.get("groups", 0), "judged": c.get("judged", 0),
                    "redone": r.get("consistency", {}).get("pairs", 0), "seed": r.get("seed", SEED), "boot": r.get("boot", 0)})
    return out


def _today_count(firsts: dict[str, SoeLabel], today: date) -> int:
    return sum(_day(lb.at) == today for lb in firsts.values())


def redo_state(q: dict, labels: list[SoeLabel], goal: int, held: bool, today: date) -> dict:
    """다시 읽기 진행: 목표(이번 목표 안의 다시 읽기 예정 조각, 보류면 45개까지), 한 수, 지금 열린 수, 다음에 열리는 날."""
    firsts, redone = _firsts(labels), _redos(labels)
    planned = [x for x in q["order"][:goal] if x in set(q["redo"])]
    target = REDO_HELD if held else len(planned)
    judged_redo = [x for x in q["redo"] if x in firsts]
    waiting = [x for x in judged_redo if x not in redone]
    opens = sorted(_day(firsts[x].at) + timedelta(days=REDO_DAYS) for x in waiting)
    due = [x for x, d in zip(waiting, [_day(firsts[x].at) + timedelta(days=REDO_DAYS) for x in waiting]) if d <= today]
    later = [d for d in opens if d > today]
    return {"target": target, "done": len(redone), "due": len(due), "waiting": len(waiting), "short": max(0, target - len(judged_redo)),
            "opens": later[0].isoformat() if later else "", "first_open": opens[0].isoformat() if opens else ""}


def screen(today: Optional[date] = None) -> dict:
    """실험실 화면 값 (목차 · 개요 · 진행 막대 · 다음 할 일). 가린 조각에서 나온 값은 싣지 않는다."""
    today = today or date.today()
    pieces = load_pieces()
    q, labels = load_queue(), load_labels()
    firsts = _firsts(labels)
    st = load_state()
    rep = latest_report()
    opened = open_batch(q, labels)
    used = [lb for lb in labels if lb.piece not in opened]
    stale = "none" if not rep else "corpus" if rep.get("corpus") != corpus_key(pieces) or rep.get("metrics_version") != metrics.METRICS_VERSION \
        else "labels" if rep.get("labeled") != labels_key(used) else ""
    cons = (rep or {}).get("consistency") or {}
    held = bool(cons and cons.get("hold") and not cons.get("preview"))
    n = len(firsts)
    done_batches = n // BATCH if not opened else (n - len(opened)) // BATCH
    left = sum(x not in firsts for x in q["order"])
    checks = check_progress(pieces, labels, masked_ids(q, labels))
    marked = [lb for lb in firsts.values() if lb.clean or lb.spans]
    return {
        **view(), "today": today.isoformat(), "judged_today": _today_count(firsts, today), "batch_size": BATCH,
        "goals": list(ROUND_GOALS), "goal": st["goal"], "stopped": st["stopped"], "seen": st["seen"],
        "queue_left": left, "in_batch": len(opened), "batches": done_batches,
        "ended": done_batches if done_batches > st["seen"] and not opened else 0,
        "marked": len(marked), "clean": sum(lb.clean for lb in firsts.values()),
        "verdicts": dict(Counter(lb.verdict for lb in firsts.values())),  # 작가 판정만 센 수 (정답 없음)
        "seconds_mean": round(mean([lb.seconds for lb in firsts.values() if lb.seconds]), 1) if any(lb.seconds for lb in firsts.values()) else 0,
        "redo_state": redo_state(q, labels, st["goal"], held, today), "held": held,
        "report": report_summary(rep), "stale": stale,
        "check": {"done": sum(c["done"] for c in checks), "total": sum(c["total"] for c in checks)},
        "chips": {k: v for k, v in CHIP.items()}, "kinds": [[k, KIND_LABELS[k]] for k in SPAN_KINDS],
        "metric_ids": [[m[0], m[1]] for m in METRICS],
    }


# ----- 판정 (가려 읽기 · 다시 읽기) -----

def _clean_spans(p: SoePiece, spans) -> list[SoeSpan]:
    """화면이 보낸 문장 표시를 조각 글에 맞춘다. 글은 서버가 잘라 quote 로 넣는다(화면 값을 믿지 않는다)."""
    out = []
    for x in spans or []:
        x = x if isinstance(x, dict) else x.model_dump()
        a, b = int(x.get("start", 0)), int(x.get("end", 0))
        kind = x.get("kind", "other")
        if kind not in KIND_LABELS:
            raise ValueError(f"모르는 갈래예요: {kind}")
        if not 0 <= a < b <= len(p.text):
            raise ValueError("표시한 곳이 글 밖이에요")
        out.append(SoeSpan(start=a, end=b, quote=p.text[a:b], kind=kind, note=str(x.get("note", ""))[:200]))
    return sorted(out, key=lambda s: s.start)


def _blind_piece(p: SoePiece) -> dict:
    """판정할 조각: 글과 id 와 글자 수만 (출처 · 원천 · 묶음 · 모델 · 지표 값 · 정규식 밑줄 없음)."""
    return {"id": p.id, "text": p.text, "chars": p.chars}


def judge_view(today: Optional[date] = None) -> dict:
    """가려 읽기 화면: 다음 조각(글만)과 진행. 끝난 '이번 10개'의 정답 카드를 넘기기 전이면 piece 는 비고 ended 에 번호."""
    sc = screen(today)
    pid = next_piece()
    piece = None
    goal_hit = sc["judged"] >= sc["goal"] and sc["judged"] % BATCH == 0
    if pid and not sc["ended"] and not sc["stopped"] and not (goal_hit and not sc["in_batch"]):
        piece = _blind_piece({p.id: p for p in load_pieces()}[pid])
    return {"screen": sc, "piece": piece}


def save_judge(pid: str, verdict: str, spans=None, clean: bool = False, seconds: int = 0, redo_too: bool = False,
               now: Optional[datetime] = None) -> dict:
    """판정 하나를 저장한다. '이번 10개'를 마치면 보고서를 다시 채점한다(AI 없음)."""
    by_id = {p.id: p for p in load_pieces()}
    if pid not in by_id:
        raise ValueError("없는 조각이에요")
    sp = _clean_spans(by_id[pid], spans)
    secs = max(0, min(int(seconds or 0), SECONDS_MAX))
    if redo_too:
        lb = redo(pid, verdict, sp, clean, secs, now)
    else:
        lb = judge(pid, verdict, sp, clean, secs, now)
    finished = not redo_too and not open_batch()  # 10개를 채웠거나 대기열이 바닥났다
    if finished or (redo_too and not redo_due((now or datetime.now().astimezone()).date())):
        report()
    return {"label": lb.id, "finished": bool(finished)}


def batch_reveal(k: int) -> dict:
    """끝난 '이번 10개'(번호 k)의 정답: 조각마다 내 판정 · 출처 · 모델 · 같은지 · 정규식 적중과 내 표시(문장 단위).
    끝나지 않았으면 막는다. 다시 읽기 예정이고 아직 재판정 전인 조각은 정답을 빼고 '재판정 뒤에 보여요'."""
    q, labels = load_queue(), load_labels()
    firsts = list(_firsts(labels).values())
    rows_lb = firsts[(k - 1) * BATCH:k * BATCH]
    if k < 1 or not rows_lb:
        raise ValueError("그런 '이번 10개'가 없어요")
    opened = open_batch(q, labels)
    if any(lb.piece in opened for lb in rows_lb):
        raise ValueError("이번 10개를 마치면 정답을 보여 드려요")
    hidden = hidden_ids(q, labels)
    by_id = {p.id: p for p in load_pieces()}
    rows, same, comparable = [], 0, 0
    tot = Counter()
    for i, lb in enumerate(rows_lb, 1):
        p = by_id.get(lb.piece)
        if p is None:
            continue
        mine = {"i": i, "id": p.id, "verdict": lb.verdict, "clean": lb.clean, "marks": len(lb.spans), "seconds": lb.seconds}
        if p.id in hidden:
            rows.append({**mine, "hidden": True})
            tot["hidden"] += 1
            continue
        sents = metrics.sentence_spans(p.text)
        rx = metrics.pattern_spans(p.text)
        hit_s = {_sent_of(sents, s.start) for s in rx}
        mark_s = {i2 for sp in lb.spans for i2, (a, b) in enumerate(sents) if sp.start < b and sp.end > a}
        match = None
        if lb.verdict in ("ai", "human") and p.origin in ("ai", "human"):
            match = lb.verdict == p.origin
            comparable += 1
            same += match
        tot[p.origin] += 1
        if p.origin == "ai":
            tot["model:" + model_label(p.model)] += 1
        tot["both"] += len(hit_s & mark_s)
        tot["rx_only"] += len(hit_s - mark_s)
        tot["mine_only"] += len(mark_s - hit_s)
        rows.append({**mine, "hidden": False, "origin": p.origin, "model": model_label(p.model) if p.origin == "ai" else "",
                     "source": source_label(p), "match": match, "hits": len(hit_s), "marked": len(mark_s),
                     "both": len(hit_s & mark_s), "text": p.text,
                     "rx": [{"start": s.start, "end": s.end, "name": KIND_LABELS.get(s.name if s.kind == "pattern" else "cliche", s.name)} for s in rx],
                     "spans": [{"start": s.start, "end": s.end, "kind": s.kind, "note": s.note} for s in lb.spans]})
    return {"k": k, "rows": rows, "same": same, "comparable": comparable,
            "unsure": sum(lb.verdict == "unsure" for lb in rows_lb), "seconds": sum(lb.seconds for lb in rows_lb),
            "counts": dict(tot), "at": rows_lb[-1].at}


def redo_view(today: Optional[date] = None) -> dict:
    """다시 읽기 화면: 열린 조각 하나(글만)와 진행. 열린 것이 없으면 다음에 열리는 날."""
    today = today or date.today()
    sc = screen(today)
    due = redo_due(today)
    piece = _blind_piece({p.id: p for p in load_pieces()}[due[0]]) if due else None
    return {"screen": sc, "piece": piece}


# ----- 말뭉치 -----

def sources() -> dict:
    """모으기 카드의 원천 후보: 역설계 실험 · 본문이 있는 작품 · 연구 말뭉치 폴더."""
    labs = []
    for x in revlab.listing():
        try:
            lab = revlab.load(x["id"])
        except (FileNotFoundError, ValueError):
            continue
        takes = sum(bool(e.take and e.take.text) + bool(e.take_style and e.take_style.text) for e in lab.episodes)
        models = sorted({model_label(model_key(_backend_of(t.model), t.model)) for e in lab.episodes for t in (e.take, e.take_style) if t and t.text and t.model})
        labs.append({"id": lab.id, "title": lab.title or f"실험 {lab.id}", "episodes": len(lab.episodes), "takes": takes, "models": models})
    projects = []
    if store.ROOT.exists():
        for d in sorted(store.ROOT.iterdir()):
            if d.name.startswith((".", "_")) or not (d / "project.json").exists():
                continue
            try:
                p = store.load_view(d.name)
            except (ValueError, OSError):
                continue
            nums = [e.plot.number for e in p.episodes if e.text.strip()]
            edits = sum(1 for e in p.episodes for ed in e.edits if ed.preset == "less_ai" and not ed.undone)
            if nums or edits:
                models = sorted({model_label(m) for m in write_models(d.name).values()})
                projects.append({"name": d.name, "title": p.meta.title or d.name, "written": len(nums), "first": min(nums, default=0),
                                 "last": max(nums, default=0), "edits": edits, "models": models})
    research = store.ROOT / "_style_research" / "corpus"
    return {"labs": labs, "projects": projects, "cap": CAP,
            "research": {"path": str(research), "exists": research.is_dir(),
                         "files": len(list(research.rglob("*.txt"))) if research.is_dir() else 0},
            "models": [["claude", "Claude"], ["gemini", "Gemini"], ["other", "그 밖"], ["", "모름"]]}


def gather(srcs: list[dict]) -> list[SoePiece]:
    """모으기 카드에서 고른 원천들 → 조각 후보. 원천마다 '읽은 적 있는 작품'(known) 체크를 따른다."""
    out: list[SoePiece] = []
    for s in srcs:
        kind, known = s.get("kind"), bool(s.get("known"))
        if kind == "revlab":
            ps = collect_revlab(int(s["lab"]))
        elif kind == "episode":
            ps = collect_episodes(s["project"], int(s.get("first") or 1), int(s.get("last") or 0))
        elif kind == "edit":
            ps = collect_edits(s["project"])
        elif kind == "research":
            ps = collect_research(s.get("path") or str(store.ROOT / "_style_research" / "corpus"), known, s.get("genre") or "literary")
        elif kind == "paste":
            backend = s.get("model") or ""
            origin = s.get("origin") or "human"
            ps = collect_paste(s.get("text", ""), s.get("title", ""), origin, model_key(backend, "") if backend and origin != "human" else "",
                               known, s.get("genre") or "webnovel")
        else:
            raise ValueError(f"모르는 원천이에요: {kind}")
        for p in ps:
            p.known = p.known or known
        out += ps
    return out


def plan_add(cands: list[SoePiece], cap: int = CAP) -> dict:
    """add 를 저장하지 않고 미리 센다: 새 조각 수(출처 · 모델별), 이미 있는 글, 상한에 걸린 수, 대기열에 들어갈 수."""
    have = {p.id: p for p in load_pieces()}
    used = Counter((source_key(p), p.origin) for p in have.values())
    new: list[SoePiece] = []
    dup = capped = 0
    seen = set(have)
    for p in _spread(cands):
        if p.id in seen:
            dup += 1
            continue
        k = (source_key(p), p.origin)
        if used[k] >= cap:
            capped += 1
            continue
        used[k] += 1
        seen.add(p.id)
        new.append(p)
    allp = list(have.values()) + new
    elig = [p for p in allp if eligible(p)]
    side = {o: len({p.group for p in elig if p.origin == o}) for o in ("human", "ai")}
    models = Counter(model_label(p.model) for p in allp if p.origin == "ai")
    ai_groups = defaultdict(set)
    for p in allp:
        if p.origin == "ai":
            ai_groups[model_label(p.model)].add(p.group)
    humans = [p for p in allp if p.origin == "human"]
    return {"new": len(new), "dup": dup, "capped": capped, "by_origin": dict(Counter(p.origin for p in new)),
            "queue": sum(eligible(p) for p in new), "groups": side, "first_need": FIRST // 2,
            "models": {m: len(g) for m, g in ai_groups.items()}, "model_pieces": dict(models),
            "literary_only": bool(humans) and all(p.genre == "literary" for p in humans)}


def collect(srcs: list[dict], cap: int = CAP) -> dict:
    """모으고 보고서를 다시 채점한다 (AI 없음)."""
    out = add(gather(srcs), cap=cap)
    if out["added"]:
        report()
    return out


def pieces_view() -> dict:
    """조각 목록. 가린 조각은 출처 · 원천 · 묶음 · 모델 칸을 빼고 어느 쪽에서 가렸는지(judge · redo)만."""
    pieces = load_pieces()
    q, labels = load_queue(), load_labels()
    opened = open_batch(q, labels)  # 끝나지 않은 이번 10개에서는 다시 읽기로 뽑혔는지도 알리지 않는다
    hidden_redo = {x for x in q["redo"] if x in _firsts(labels) and x not in _redos(labels) and x not in opened}
    masked = masked_ids(q, labels)
    nlab = Counter(lb.piece for lb in labels if lb.kind == "piece")
    rows = []
    for k, p in enumerate(pieces, 1):
        row = {"n": k, "id": p.id, "chars": p.chars, "labels": nlab[p.id], "known": p.known, "paste": p.source.kind == "paste"}
        if p.id in masked:
            row["hidden"] = "redo" if p.id in hidden_redo else "judge"
        else:
            row.update(origin=p.origin, source=source_label(p), group=p.group, model=model_label(p.model) if p.origin == "ai" else "",
                       model_source=p.model_source if p.origin == "ai" else "")
        rows.append(row)
    groups = {o: len({p.group for p in pieces if p.origin == o}) for o in ("human", "ai")}
    by_src = Counter((source_key(p), p.origin) for p in pieces)
    srcs = [{"key": k, "origin": o, "n": n, "capped": n >= CAP} for (k, o), n in sorted(by_src.items())]
    return {"rows": rows, "groups": groups, "group_total": len({p.group for p in pieces}), "sources": srcs, "cap": CAP,
            "hidden": len(masked)}


def remove_piece(pid: str) -> None:
    """붙여 넣은 조각 빼기. 판정한 조각은 뺄 수 없다(판정 기록이 그 글을 가리킨다)."""
    with _lock():
        by_id = {p.id: p for p in load_pieces()}
        p = by_id.get(pid)
        if p is None:
            raise ValueError("없는 조각이에요")
        if p.source.kind != "paste":
            raise ValueError("붙여 넣은 글만 뺄 수 있어요")
        if any(lb.piece == pid for lb in load_labels()):
            raise ValueError("판정한 조각은 뺄 수 없어요")
        _piece_path(pid).unlink()
        q = load_queue()
        q["order"] = [x for x in q["order"] if x != pid]
        q["redo"] = [x for x in q["redo"] if x != pid]
        q["carry"] = [x for x in q.get("carry", []) if x != pid]
        save_json(_dir() / "queue.json", q)


def set_origin(pid: str, origin: str, model: str = "") -> SoePiece:
    """붙여 넣은 조각의 출처 고치기. 가린 조각은 고치는 칸을 보이지 않으니(출처가 드러나서) 여기서도 막는다."""
    if origin not in ("human", "ai", "unknown"):
        raise ValueError("출처는 human · ai · unknown 가운데 하나예요")
    with _lock():
        by_id = {p.id: p for p in load_pieces()}
        p = by_id.get(pid)
        if p is None or p.source.kind != "paste":
            raise ValueError("붙여 넣은 글만 출처를 고칠 수 있어요")
        if pid in masked_ids():
            raise ValueError("판정 뒤에 출처를 고칠 수 있어요")
        p.origin = origin
        p.model = model_key(model, "") if model and origin == "ai" else ""
        p.model_source = "author" if p.model else "unknown"
        save_json(_piece_path(pid), p.model_dump())
        save_json(_dir() / "queue.json", extend_queue(load_queue(), list(by_id.values()), judged=set(_firsts(load_labels()))))
    return p


def piece_view(pid: str) -> dict:
    """조각 하나 (읽기 전용). 가린 조각은 글만 주고, 아니면 출처와 정규식 적중 자리도 준다."""
    by_id = {p.id: p for p in load_pieces()}
    p = by_id.get(pid)
    if p is None:
        raise ValueError("없는 조각이에요")
    if pid in masked_ids():
        return {**_blind_piece(p), "hidden": True}
    rx = metrics.pattern_spans(p.text)
    return {**_blind_piece(p), "hidden": False, "origin": p.origin, "source": source_label(p), "group": p.group,
            "model": model_label(p.model) if p.origin == "ai" else "", "values": features(p),
            "rx": [{"start": s.start, "end": s.end, "name": KIND_LABELS.get(s.name if s.kind == "pattern" else "cliche", s.name)} for s in rx]}


# ----- 지표 하나 -----

def metric_view(mid: str) -> dict:
    """지표 하나: 정의 · 잰 곳 · 지금 기준, 최근 보고서의 칸, 보이는 조각의 점 그림 · 가르는 힘 곡선 · 끝 조각 5개씩.
    점 그림 · 곡선 · 끝 조각은 가린 조각을 빼고 그린다(조각별 값이라서)."""
    meta = next((m for m in METRICS if m[0] == mid), None)
    if meta is None:
        raise ValueError(f"모르는 지표예요: {mid}")
    _, label, direction, where = meta
    rep = report_summary(latest_report())
    row = next((r for r in rep["metrics"] if r["id"] == mid), None) if rep else None
    pieces = load_pieces()
    masked = masked_ids()
    paired = _paired(pieces)
    vis = [p for p in pieces if p.id not in masked and p.origin in ("human", "ai")]
    pts, rows = [], {}
    for p in vis:
        v = features(p)[mid]
        if v is None:
            continue
        key = f"human:{source_label(p)}" if p.origin == "human" else f"ai:{model_label(p.model)}"
        rows.setdefault(key, {"key": key, "side": p.origin, "label": f"사람 · {source_label(p)}" if p.origin == "human" else f"AI · {model_label(p.model)}"})
        pts.append({"id": p.id, "v": round(v, 4), "row": key, "paired": p.id in paired})
    d = (row or {}).get("source", {}).get("dir") or direction or 1
    ai = [x["v"] * d for x in pts if x["row"].startswith("ai:") and not x["paired"]]
    hu = [x["v"] * d for x in pts if x["row"].startswith("human:") and not x["paired"]]
    roc = [[round(a, 4), round(b, 4)] for a, b in labstats.roc_points(ai, hu)]
    order = sorted(pts, key=lambda x: x["v"] * d)
    pick = lambda xs: [{"id": x["id"], "v": x["v"], "row": rows[x["row"]]["label"]} for x in xs]
    line = metrics.STYLE_DISTANCE_WARN if mid == "style_distance" else None
    return {"id": mid, "label": label, "where": where, "direction": row["direction"] if row else DIR_TEXT[direction],
            "def": METRIC_DEFS.get(mid, ""), "threshold": threshold_text(mid), "row": row,
            "rows": sorted(rows.values(), key=lambda r: (r["side"] != "human", r["label"])), "points": pts, "roc": roc,
            "top": pick(order[::-1][:5]), "bottom": pick(order[:5]), "line": line, "left_out": len(masked),
            "metrics_version": metrics.METRICS_VERSION}


# ----- 패턴 확인 · 패턴 혼동표 -----

def _hit_labels(labels: list[SoeLabel]) -> dict[str, SoeLabel]:
    out: dict[str, SoeLabel] = {}
    for lb in labels:
        if lb.kind == "hit":
            out[lb.hit] = lb
    return out


def check_items(pieces: list[SoePiece], masked: set[str]) -> dict[str, list[dict]]:
    """패턴 확인할 문장: 가리지 않은 조각에서 정규식이 잡은 문장, 패턴마다 문장 하나씩(같은 문장 두 번 없음), 시드로 섞어 CHECK_PER 개."""
    out: dict[str, list[dict]] = {k: [] for k in CHECK_KINDS}
    for p in pieces:
        if p.id in masked or p.origin == "edited":
            continue
        sents = metrics.sentence_spans(p.text)
        seen = set()
        for s in metrics.pattern_spans(p.text):
            kind = s.name if s.kind == "pattern" else "cliche"
            i = _sent_of(sents, s.start)
            if i < 0 or (kind, i) in seen:
                continue
            seen.add((kind, i))
            out[kind].append({"hit": f"{p.id}-{i}-{CHECK_KINDS.index(kind)}", "kind": kind, "piece": p.id, "i": i})
    for k, xs in out.items():
        xs.sort(key=lambda x: hashlib.sha1(f"{SEED}:{x['hit']}".encode()).hexdigest())
        out[k] = xs[:CHECK_PER]
    return out


def check_progress(pieces: list[SoePiece], labels: list[SoeLabel], masked: set[str]) -> list[dict]:
    done = _hit_labels(labels)
    return [{"kind": k, "label": KIND_LABELS[k], "total": len(xs), "done": sum(x["hit"] in done for x in xs)}
            for k, xs in check_items(pieces, masked).items()]


def _check_card(item: dict, p: SoePiece, done: dict[str, SoeLabel]) -> dict:
    sents = metrics.sentence_spans(p.text)
    a, b = sents[item["i"]]
    marks = [{"start": s.start - a, "end": min(s.end, b) - a} for s in metrics.pattern_spans(p.text)
             if (s.name if s.kind == "pattern" else "cliche") == item["kind"] and a <= s.start < b]
    prev = p.text[sents[item["i"] - 1][0]:sents[item["i"] - 1][1]] if item["i"] > 0 else ""
    nxt = p.text[sents[item["i"] + 1][0]:sents[item["i"] + 1][1]] if item["i"] + 1 < len(sents) else ""
    lb = done.get(item["hit"])
    return {"hit": item["hit"], "kind": item["kind"], "label": KIND_LABELS[item["kind"]], "piece": p.id,
            "origin": p.origin, "source": source_label(p), "model": model_label(p.model) if p.origin == "ai" else "",
            "sentence": p.text[a:b], "prev": prev, "next": nxt, "marks": marks, "rated": lb.hit_ok if lb else ""}


def check_view(kind: str = "", hit: str = "") -> dict:
    """패턴 확인 화면: 패턴별 진행과 다음 문장(kind 를 주면 그 패턴에서, hit 를 주면 그 문장). 출처를 가리지 않는다(가린 조각은 처음부터 뺀다)."""
    pieces = load_pieces()
    labels = load_labels()
    masked = masked_ids(None, labels)
    items = check_items(pieces, masked)
    done = _hit_labels(labels)
    by_id = {p.id: p for p in pieces}
    prog = [{"kind": k, "label": KIND_LABELS[k], "total": len(xs), "done": sum(x["hit"] in done for x in xs)} for k, xs in items.items()]
    card = None
    flat = [x for k in CHECK_KINDS for x in items[k]]
    if hit:
        card = next((x for x in flat if x["hit"] == hit), None)
        if card is None:
            raise ValueError("패턴 확인할 문장이 아니에요")
    else:
        pool = items.get(kind) if kind in items else flat
        card = next((x for x in pool if x["hit"] not in done), None) or (next((x for x in flat if x["hit"] not in done), None) if kind else None)
    return {"progress": prog, "done": sum(c["done"] for c in prog), "total": sum(c["total"] for c in prog),
            "card": _check_card(card, by_id[card["piece"]], done) if card else None, "kind": kind}


def save_check(hit: str, ok: str, now: Optional[datetime] = None) -> dict:
    """패턴 확인 하나를 매긴다 (yes 글티 맞아요 · no 아니에요 · skip 모르겠어요). 같은 문장을 다시 매기면 앞 것을 지운다."""
    if ok not in ("yes", "no", "skip"):
        raise ValueError("매기기는 yes · no · skip 가운데 하나예요")
    with _lock():
        labels = load_labels()
        items = {x["hit"]: x for xs in check_items(load_pieces(), masked_ids(None, labels)).values() for x in xs}
        if hit not in items:
            raise ValueError("패턴 확인할 문장이 아니에요")
        old = _hit_labels(labels).get(hit)
        if old:
            remove_label(old.id)
        now = now or datetime.now().astimezone()
        lb = SoeLabel(id=hashlib.sha1(f"hit:{hit}:{now.isoformat()}:{os.getpid()}".encode()).hexdigest()[:12],
                      at=now.isoformat(timespec="seconds"), kind="hit", piece=items[hit]["piece"], hit=hit, hit_ok=ok,
                      blind=False, metrics_version=metrics.METRICS_VERSION)
        append_label(lb)
    return {"label": lb.id}


def patterns_view() -> dict:
    """패턴 혼동표: 정밀도는 패턴 확인(글티 맞아요 ÷ 맞아요 + 아니에요), 재현율은 가려 읽기의 문장 표시로.
    문장 목록은 가리지 않은 조각에서만: 패턴 확인 '맞아요' → 같음, '아니에요' → 오탐 후보, 내가 그 갈래로 표시했는데 정규식이 못 잡은 문장 → 놓침."""
    pieces = load_pieces()
    by_id = {p.id: p for p in pieces}
    q, labels = load_queue(), load_labels()
    masked = masked_ids(q, labels)
    opened = open_batch(q, labels)
    used = [lb for lb in labels if lb.piece not in opened]
    blind = {r["pattern"]: r for r in pattern_table(by_id, used)}
    checks = _hit_labels(labels)
    items = check_items(pieces, masked)
    firsts = _firsts(used)
    rows = []
    for k in CHECK_KINDS:
        kid = CHECK_KINDS.index(k)
        rated = [lb for h, lb in checks.items() if h.endswith(f"-{kid}") and lb.hit_ok in ("yes", "no")]
        yes = sum(lb.hit_ok == "yes" for lb in rated)
        sents = []
        for lb in rated:
            p = by_id.get(lb.piece)
            if p is None or p.id in masked:
                continue
            i = int(lb.hit.split("-")[1])
            ss = metrics.sentence_spans(p.text)
            if i < len(ss):
                sents.append({"kind": "same" if lb.hit_ok == "yes" else "fp", "text": p.text[ss[i][0]:ss[i][1]], "piece": p.id})
        for pid, lb in firsts.items():
            p = by_id.get(pid)
            if p is None or pid in masked:
                continue
            ss = metrics.sentence_spans(p.text)
            hits = {_sent_of(ss, s.start) for s in metrics.pattern_spans(p.text) if (s.name if s.kind == "pattern" else "cliche") == k}
            for sp in lb.spans:  # 놓침은 혼동표의 재현율처럼 문장 단위: 내가 이 갈래로 표시했는데 정규식이 못 잡은 문장
                if sp.kind != k:
                    continue
                for i in [i for i, (a, b) in enumerate(ss) if sp.start < b and sp.end > a and i not in hits]:
                    sents.append({"kind": "miss", "text": p.text[ss[i][0]:ss[i][1]], "piece": pid, "note": sp.note})
        b = blind.get(k, {})
        rows.append({"kind": k, "label": KIND_LABELS[k], "checked": len(rated), "yes": yes,
                     "precision": _rnd(yes / len(rated)) if rated else None, "precision_ci": [_rnd(x) for x in labstats.wilson(yes, len(rated))],
                     "few": len(rated) < 5, "marked": b.get("marked", 0), "found": b.get("found", 0), "missed": b.get("marked", 0) - b.get("found", 0),
                     "recall": b.get("recall"), "recall_ci": b.get("recall_ci"), "recall_few": b.get("marked", 0) < 5,
                     "left": sum(x["hit"] not in checks for x in items[k]), "sentences": sents})
    others = [{"text": sp.quote, "note": sp.note, "piece": pid} for pid, lb in firsts.items() if pid not in masked for sp in lb.spans if sp.kind == "other"]
    done = [lb for pid, lb in firsts.items() if lb.clean or lb.spans]
    return {"rows": rows, "others": others, "marked_pieces": len(done), "clean": sum(lb.clean for lb in done),
            "sentences": sum(len(metrics.sentence_spans(by_id[lb.piece].text)) for lb in done if lb.piece in by_id),
            "check_left": sum(r["left"] for r in rows), "metrics_version": metrics.METRICS_VERSION}
