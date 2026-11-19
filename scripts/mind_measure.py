"""인물 심리 이어짐 측정 도구 (목표 character-mind-continuity 의 명세 1).

세 값을 잰다.
  값 1: 지문 1천 자당 생각 낱말(thought_per_1k)과 속생각 줄 몫(inner_line_share). LLM 없이 잰다.
  값 2: 앞 화(1~3화 앞)의 일에 기대어 마음을 적은 곳의 1만 자당 수. 모델이 라벨을 매긴다.
  값 3: 먼 화(10화 넘게 앞)의 일에 기대어 마음을 적은 곳의 1만 자당 수. 본문이 50화 아래인 글은 못 잰다.
이 스크립트는 store.save 를 부르지 않는다. 작품과 .refs 는 읽기만 하고 --out 경로에만 쓴다.
라벨은 본문 구절을 받지 않고 저장하지 않는다. 출력에는 글 키(R1~R3, C1~C3)만 찍는다.

실행 (작품과 .refs 를 임시 CANON_HOME 에 복사해 둔다):
  CANON_HOME=<임시 폴더> CANON_LLM=mock python scripts/mind_measure.py sample --refs 레퍼런스ID ... \\
      --projects 작품 ... --per 20 --seed 20261119 --min-ep 31 --out <out>/samples.json
  CANON_HOME=<임시 폴더> python scripts/mind_measure.py label --samples <out>/samples.json \\
      --model coralbricks:deepseek-v4.1-flash-value --repeat 5 --dry-run
  CANON_HOME=<임시 폴더> python scripts/mind_measure.py label --samples <out>/samples.json --model ... --out <out>/labels.json
  CANON_HOME=<임시 폴더> python scripts/mind_measure.py table --labels <out>/labels.json --out-md T.md --out-json T.json
"""
import argparse
import concurrent.futures as cf
import contextvars
import importlib.util
import json
import os
import random
import sys
import threading
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CANON_LLM", "mock")

from canon import llm as llm_mod  # noqa: E402
from canon import metrics, usage  # noqa: E402

SEED = 20261119
BOOT = 2000                 # 부트스트랩 반복
SHORT_ENDS = 50             # 본문이 이 화 수 아래이면 값 3 을 못 잼
SHORT_START = 4             # 그때는 4번째 화부터 모두 뽑는다
NEAR = (1, 3)               # 값 2 의 거리(화)
FAR = 10                    # 값 3 은 거리가 이 값을 넘는 것
AGREE_MIN = 24              # 값 1 이 가르려면 레퍼런스 쪽을 맞힌 쌍이 이 수 이상
AGREE_PAIRS = 37
CHARS_PER_TOKEN = 1.7
OUT_TOKENS = 600            # 호출당 출력 토큰 어림
PROMPT_CHARS = 900          # 지시문 글자 수 어림
SUMMARY_CHARS = 60          # 한 줄 요약 글자 수 어림
ERROR_LIMIT = 0.10
V1_NAMES = ("thought_per_1k", "inner_line_share")
RULES = (
    "판정 규칙 (값을 보기 전에 정했다)",
    f"- 값 1: 낱값 둘을 따로 판정한다. 판별 묶음 {AGREE_PAIRS}쌍 가운데 레퍼런스 쪽을 {AGREE_MIN}쌍 이상 맞힌 낱값만 가른다.",
    "- 값 2 · 3: canon 묶음의 95% 구간이 레퍼런스 묶음의 구간과 겹치지 않으면 가른다.",
    "- 글별: 그 canon 글의 구간이 레퍼런스 세 편의 구간 모두와 겹치지 않으면 가른다.",
)

SUMMARY_SYSTEM = ("너는 소설 편집자다. 주어진 한 화의 본문을 읽고 일어난 일을 한 문장(80자 안팎)으로 요약한다. "
                  "누가 무엇을 했고 무엇이 달라졌는지만 적는다.")
LABEL_MAX = 40
LABEL_SYSTEM = (
    "너는 소설 편집자다. 한 화의 본문과 앞 화들의 한 줄 요약(화 번호 포함)을 받는다. "
    "본문에서 인물의 감정 · 판단 · 태도 · 선택을 적은 곳을 모두 찾아 라벨을 매긴다. 본문 구절을 옮겨 적지 않는다.\n"
    "각 라벨의 칸:\n"
    "- kind: '마음'은 앞 화의 일에 기대어 지금의 감정 · 판단 · 태도 · 선택을 적은 곳이다. "
    "줄거리 정보만 전하는 곳은 '줄거리'다.\n"
    "- source_ep: 기대는 앞 화의 번호. 요약에서 찾아 적는다. 모르거나 이 화 안의 일이면 비운다.\n"
    "- who: 그 마음의 주인이 시점 인물 본인이면 '본인', 다른 인물이면 '남'.\n"
    "- at: 이 화 본문 안에서 그곳이 있는 글자 자리(대략).\n"
    f"라벨은 많아야 {LABEL_MAX}개만 적는다. {LABEL_MAX}개를 넘으면 앞 화에 기대는 곳('마음' 가운데 source_ep 가 있는 것)을 먼저 남긴다.\n"
    "없으면 빈 목록을 돌려준다."
)


class MindLabel(BaseModel):
    kind: Literal["마음", "줄거리"]
    source_ep: Optional[int] = None   # 기대는 앞 화 번호. 모르면 None
    who: Literal["본인", "남"]
    at: int = 0                       # 이 화 본문 안의 글자 자리(대략)


class MindLabels(BaseModel):
    items: list[MindLabel] = []


class EpSummary(BaseModel):
    line: str                         # 한 줄 요약 (--out 폴더에만 저장)


# ---------- 글 읽기 ----------

def _trail():
    path = Path(__file__).resolve().parent / "trail_measure.py"
    spec = importlib.util.spec_from_file_location("trail_measure", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_eps(kind: str, ident: str) -> list[tuple[int, str]]:
    """(화 번호, 본문) 목록. 레퍼런스는 전부, canon 은 본문이 있는 화 전부."""
    tm = _trail()
    if kind == "ref":
        return tm.ref_episodes(ident, 1, 10 ** 6)
    return tm.canon_episodes(ident, 1)


# ---------- 표본 ----------

def pick_eps(eps: list[tuple[int, str]], per: int, seed: int, key: str, min_ep: int) -> tuple[list[int], bool]:
    """본문이 있는 min_ep 번째 화부터 무작위 per 화(정렬된 화 번호). 본문 화가 50 아래면 4번째 화부터 모두, 두 번째 값 False(값 3 못 잼)."""
    rows = sorted(r for r in eps if r[1])
    nums = [n for n, _ in rows]
    if len(nums) < SHORT_ENDS:
        return nums[SHORT_START - 1:], False
    pool = nums[min_ep - 1:]
    got = random.Random(f"{seed}:{key}").sample(pool, min(per, len(pool)))
    return sorted(got), True


def _v1(text: str) -> dict:
    return {"thought_per_1k": metrics.thought_per_1k(text), "inner_line_share": metrics.inner_line_share(text)}


def sample_work(key: str, kind: str, eps: list[tuple[int, str]], per: int, seed: int, min_ep: int) -> dict:
    """한 글의 표본. 본문은 넣지 않는다: 화 번호 · 글자 수 · 값 1 의 두 낱값만."""
    nums, can3 = pick_eps(eps, per, seed, key, min_ep)
    texts = dict(eps)
    return {"kind": kind, "eps": nums, "can3": can3,
            "chars": {str(n): len(texts[n]) for n in nums},
            "v1": {str(n): _v1(texts[n]) for n in nums}}


def _keys(refs: list[str], projects: list[str]) -> list[tuple[str, str, str]]:
    return ([(f"R{i}", "ref", r) for i, r in enumerate(refs, 1)] +
            [(f"C{i}", "canon", p) for i, p in enumerate(projects, 1)])


def cmd_sample(a) -> None:
    keymap, works = {}, {}
    for key, kind, ident in _keys(a.refs or [], a.projects or []):
        works[key] = sample_work(key, kind, load_eps(kind, ident), a.per, a.seed, a.min_ep)
        keymap[key] = {"kind": kind, "ident": ident}
        w = works[key]
        print(f"{key} {kind} 표본 화 {len(w['eps'])}개 값 3 {'잴 수 있음' if w['can3'] else '못 잼'}")
    out = Path(a.out)
    _dump(out, {"seed": a.seed, "per": a.per, "min_ep": a.min_ep, "works": works})
    _dump(out.parent / "keymap.json", keymap)


# ---------- 모델 호출 ----------

def _retry(fn, retries: int):
    """fn() 이 예외로 끝나면 retries 번까지 다시 부른다. 끝내 실패하면 마지막 예외를 던진다."""
    for left in range(retries, -1, -1):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            if not left:
                raise


def _par(workers: int, fn, items: list) -> None:
    """items 마다 fn(item) 을 workers 개씩 함께 부른다. 스레드마다 contextvars 를 복사해 넘긴다."""
    with cf.ThreadPoolExecutor(max(1, workers)) as ex:
        futs = [ex.submit(contextvars.copy_context().run, fn, it) for it in items]
        for f in futs:
            f.result()


def _capped(llm, max_out: Optional[int], fn):
    """fn() 을 out_cap(max_out) 안에서 부른다. 끝난 이유가 잘림이면 OutputCut 을 던진다."""
    if max_out:
        with llm_mod.out_cap(max_out):
            res = fn()
    else:
        res = fn()
    if llm_mod.was_cut(llm):
        raise llm_mod.OutputCut("응답이 출력 상한에 걸려 끊겼어요")
    return res


def _summary_call(llm, n: int, text: str, max_out: Optional[int]) -> str:
    cap = min(max_out, 1000) if max_out else None
    return _capped(llm, cap, lambda: llm.json(SUMMARY_SYSTEM, f"{n}화 본문:\n{text}", EpSummary).line.strip())


class _PerThread:
    """스레드마다 factory() 로 만든 LLM 을 쓴다. 속성 읽기(json, last_finish 등)는 그 스레드의 객체로 간다."""

    def __init__(self, factory):
        self._factory = factory
        self._local = threading.local()

    def __getattr__(self, name):
        if name in ("_factory", "_local"):
            raise AttributeError(name)
        obj = getattr(self._local, "obj", None)
        if obj is None:
            obj = self._local.obj = self._factory()
        return getattr(obj, name)


def summarize(llm, eps: list[tuple[int, str]], cache: Path, upto: Optional[int] = None,
              workers: int = 1, retries: int = 0, stats: Optional[dict] = None,
              max_out: Optional[int] = None) -> dict[int, str]:
    """화마다 한 줄 요약. cache(JSON)에 있으면 다시 부르지 않는다. upto 가 있으면 그 번호 아래 화만.
    stats 를 주면 끝내 실패한 화는 빼고 stats["errors"] 에 센다. 없으면 예외를 그대로 던진다."""
    got = {int(k): v for k, v in (_read(cache) or {}).items()}
    todo = [(n, t) for n, t in sorted(eps) if not (upto is not None and n >= upto) and n not in got]
    lock = threading.Lock()

    def one(item) -> None:
        n, text = item
        try:
            line = _retry(lambda: _summary_call(llm, n, text, max_out), retries)
        except Exception:  # noqa: BLE001
            if stats is None:
                raise
            with lock:
                stats["errors"] = stats.get("errors", 0) + 1
            return
        with lock:
            got[n] = line
            _dump(cache, {str(k): v for k, v in got.items()})

    _par(workers, one, todo)
    return got


def _label_prompt(ep: int, text: str, summaries: dict[int, str]) -> str:
    prev = "\n".join(f"{n}화: {s}" for n, s in sorted(summaries.items()) if n < ep)
    return f"앞 화 요약:\n{prev or '(없음)'}\n\n{ep}화 본문:\n{text}"


def _clean(item: MindLabel, ep: int, size: int) -> dict:
    src = item.source_ep if item.source_ep is not None and 0 < item.source_ep < ep else None
    return {"ep": ep, "at": min(max(item.at, 0), size), "kind": item.kind, "source_ep": src, "who": item.who}


def label_ep(llm, ep: int, text: str, summaries: dict[int, str], max_out: Optional[int] = None) -> list[dict]:
    """한 화의 라벨. 돌려주는 dict 는 {"ep","at","kind","source_ep","who"} 뿐. 본문 구절을 넣지 않는다.
    max_out 이 있으면 그 토큰까지만 받는다. 응답이 잘리면 OutputCut."""
    got = _capped(llm, max_out, lambda: llm.json(LABEL_SYSTEM, _label_prompt(ep, text, summaries), MindLabels))
    return [_clean(it, ep, len(text)) for it in got.items]


def _try_label_err(llm, ep: int, text: str, summaries: dict[int, str], retries: int = 0,
                   max_out: Optional[int] = None):
    """(라벨 목록 또는 None, 실패한 예외 클래스 이름 또는 None)."""
    try:
        return _retry(lambda: label_ep(llm, ep, text, summaries, max_out), retries), None
    except Exception as e:  # noqa: BLE001 형식 오류 · 검증 실패는 세어서 보고한다
        return None, type(e).__name__


def _try_label(llm, ep: int, text: str, summaries: dict[int, str], retries: int = 0) -> Optional[list[dict]]:
    return _try_label_err(llm, ep, text, summaries, retries)[0]


def make_llm(model: str):
    from canon.llm import make_llm as build

    provider, _, name = model.partition(":")
    return build(provider, name)


def _label_tasks(w: dict, repeat: int, old: dict) -> tuple[list[tuple[int, str]], dict]:
    """(다시 불러야 할 (화, 칸) 목록, 이미 있는 값). 칸은 'labels' 나 'again'. old 는 --resume 으로 읽은 글의 화별 줄."""
    todo, kept = [], {}
    for i, n in enumerate(w["eps"]):
        for name in ("labels", "again") if i < repeat else ("labels",):
            prev = (old.get(str(n)) or {}).get(name)
            if prev is not None:
                kept[(n, name)] = prev
            else:
                todo.append((n, name))
    return todo, kept


def _label_work(llm, w: dict, eps: list[tuple[int, str]], key_dir: Path, key: str, repeat: int,
                workers: int = 1, retries: int = 0, old: Optional[dict] = None,
                max_out: Optional[int] = None) -> dict:
    texts = dict(eps)
    sstats: dict = {}
    summaries = summarize(llm, eps, key_dir / f"summaries-{key}.json", upto=max(w["eps"]) if w["eps"] else None,
                          workers=workers, retries=retries, stats=sstats, max_out=max_out)
    todo, kept = _label_tasks(w, repeat, old or {})
    got, errs, lock = dict(kept), {}, threading.Lock()
    total = len(todo) + len(kept)

    def one(task) -> None:
        n, name = task
        res, err = _try_label_err(llm, n, texts[n], summaries, retries, max_out)
        with lock:
            got[task] = res
            if err:
                errs[task] = err
            if len(got) % 20 == 0:
                print(f"{key} 라벨 {len(got)}/{total}", flush=True)

    _par(workers, one, todo)
    out = {"kind": w["kind"], "can3": w["can3"], "chars": w["chars"], "v1": w["v1"], "eps": {}}
    for n in w["eps"]:
        row = {"labels": got[(n, "labels")]}
        if (n, "labels") in errs:
            row["err"] = errs[(n, "labels")]
        if (n, "again") in got:
            row["again"] = got[(n, "again")]
            if (n, "again") in errs:
                row["again_err"] = errs[(n, "again")]
        out["eps"][str(n)] = row
    capped = sum(1 for n in w["eps"] if len(got[(n, "labels")] or []) >= LABEL_MAX)
    if capped:
        out["capped"] = capped
    if sstats.get("errors"):
        out["summary_errors"] = sstats["errors"]
    return out


def count_errors(labels: dict) -> tuple[int, int]:
    """(형식 오류 호출 수, 전체 호출 수)."""
    bad = total = 0
    for w in labels["works"].values():
        for row in w["eps"].values():
            for name in ("labels", "again"):
                if name in row:
                    total += 1
                    bad += row[name] is None
    return bad, total


def _snapshot(a, samples: dict, done: dict, prev: dict) -> dict:
    """샘플 차례대로 끝난 글(done)과 이전 값(prev)을 합친 labels 모양."""
    works = {k: done.get(k) or prev[k] for k in samples["works"] if k in done or k in prev}
    labels = {"model": a.model, "repeat": a.repeat, "works": works}
    labels["errors"], labels["calls"] = count_errors(labels)
    summary_errors = sum(w.get("summary_errors", 0) for w in works.values())
    if summary_errors:
        labels["summary_errors"] = summary_errors
    return labels


def cmd_label(a, llm=None) -> int:
    samples = _read(Path(a.samples))
    keymap = _read(Path(a.samples).parent / "keymap.json")
    loaded = {k: load_eps(keymap[k]["kind"], keymap[k]["ident"]) for k in samples["works"]}
    if a.dry_run:
        print(json.dumps(dry_run(samples, loaded, a.model, a.repeat), ensure_ascii=False, indent=1))
        return 0
    workers, retries = getattr(a, "workers", 1), getattr(a, "retries", 0)
    if getattr(a, "timeout", None):
        os.environ["CANON_LOCAL_TIMEOUT"] = str(a.timeout)
    llm = llm or _PerThread(lambda: make_llm(a.model))
    max_out = getattr(a, "max_out", 4000)
    out_dir = Path(a.out).parent
    prev = ((_read(Path(a.out)) or {}).get("works") or {}) if getattr(a, "resume", False) else {}
    done: dict = {}
    for k, w in samples["works"].items():
        old = (prev.get(k) or {}).get("eps") or {}
        done[k] = _label_work(llm, w, loaded[k], out_dir, k, a.repeat, workers, retries, old, max_out)
        _dump(Path(a.out), _snapshot(a, samples, done, prev))
    labels = _snapshot(a, samples, done, {})
    bad, total = labels["errors"], labels["calls"]
    _dump(Path(a.out), labels)
    print(f"호출 {total}번 형식 오류 {bad}번")
    if total and bad / total > ERROR_LIMIT:
        print(f"형식 오류가 {ERROR_LIMIT:.0%} 를 넘었어요. 멈추고 원인을 먼저 봐요")
        return 2
    return 0


# ---------- 어림 비용 ----------

def _price(model: str):
    name = model.partition(":")[2] or model
    p = usage.rate(name)
    if p is None:
        raise SystemExit("가격표에 없는 모델이에요")
    return p


def dry_run(samples: dict, loaded: dict, model: str, repeat: int) -> dict:
    """호출 수 · 글자 수 · 어림 비용. LLM 을 부르지 않는다."""
    calls = chars = 0
    for key, w in samples["works"].items():
        texts = dict(loaded[key])
        top = max(w["eps"]) if w["eps"] else 0
        need = [n for n in texts if n < top]
        calls += len(need)
        chars += sum(len(texts[n]) + PROMPT_CHARS for n in need)
        labelled = list(w["eps"]) + list(w["eps"][:repeat])
        calls += len(labelled)
        for n in labelled:
            before = sum(1 for m in texts if m < n)
            chars += len(texts[n]) + PROMPT_CHARS + before * SUMMARY_CHARS
    tin, tout = chars / CHARS_PER_TOKEN, calls * OUT_TOKENS
    return {"model": model, "calls": calls, "chars": chars, "cost_usd": round(usage.cost(_price(model), tin, tout), 4)}


# ---------- 표 ----------

def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _dump(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _dist(lab: dict, ep: int) -> Optional[int]:
    src = lab.get("source_ep")
    return None if src is None or src >= ep else ep - src


def ep_rows(w: dict) -> list[dict]:
    """화마다 (글자 수, 값 2 건수, 값 3 건수, 값 1 두 낱값). 첫 라벨만 쓴다. 형식 오류 화는 뺀다."""
    rows = []
    for key, row in w["eps"].items():
        if row["labels"] is None:
            continue
        ep = int(key)
        ds = [_dist(x, ep) for x in row["labels"] if x["kind"] == "마음"]
        rows.append({"chars": w["chars"][key], "c2": sum(d is not None and NEAR[0] <= d <= NEAR[1] for d in ds),
                     "c3": sum(d is not None and d > FAR for d in ds), **w["v1"][key]})
    return rows


def _per10k(rows: list[dict], field: str) -> Optional[float]:
    chars = sum(r["chars"] for r in rows)
    return sum(r[field] for r in rows) / chars * 10000 if chars else None


def _mean(rows: list[dict], field: str) -> Optional[float]:
    xs = [r[field] for r in rows if r.get(field) is not None]
    return sum(xs) / len(xs) if xs else None


def _boot(rows: list[dict], stat) -> Optional[list[float]]:
    """화 단위 부트스트랩 95% 구간(시드 고정)."""
    if not rows:
        return None
    rng = random.Random(SEED)
    vals = sorted(v for v in (stat([rng.choice(rows) for _ in rows]) for _ in range(BOOT)) if v is not None)
    if not vals:
        return None
    return [vals[int(0.025 * (len(vals) - 1))], vals[int(round(0.975 * (len(vals) - 1)))]]


def _stat_for(name: str):
    if name in ("c2", "c3"):
        return lambda rs: _per10k(rs, name)
    return lambda rs: _mean(rs, name)


def _cell(rows: list[dict], name: str) -> dict:
    stat = _stat_for(name)
    val = stat(rows)
    if val is None:
        return {"value": None, "ci": None}
    ci = _boot(rows, stat)
    return {"value": round(val, 4), "ci": [round(x, 4) for x in ci] if ci else None}


def _values(rows: list[dict], can3: bool) -> dict:
    out = {name: _cell(rows, name) for name in V1_NAMES}
    out["v2"] = _cell(rows, "c2")
    out["v3"] = _cell(rows, "c3") if can3 else {"value": None, "ci": None, "note": "못 잼"}
    return out


def _overlap(a: Optional[list], b: Optional[list]) -> bool:
    return not (a is None or b is None or a[1] < b[0] or b[1] < a[0])


def _splits(cells: dict[str, dict], kind_of: dict[str, str]) -> dict:
    """값 2 · 3 의 가름. 묶음은 canon 구간과 레퍼런스 구간이 겹치지 않으면, 글별은 레퍼런스 세 편 모두와 겹치지 않으면."""
    out = {}
    for v in ("v2", "v3"):
        ref = [k for k in cells if kind_of[k] == "ref" and cells[k][v]["ci"]]
        mine = [k for k in cells if kind_of[k] == "canon" and cells[k][v]["ci"]]
        out[v] = {k: bool(ref) and not any(_overlap(cells[k][v]["ci"], cells[r][v]["ci"]) for r in ref) for k in mine}
    return out


def jitter(labels: dict) -> dict:
    """같은 화를 다시 매긴 흔들림: 값 2 · 값 3 건수 차의 평균, 라벨 수 일치율, 형식 오류 수."""
    d2, d3, same, n = [], [], 0, 0
    for w in labels["works"].values():
        for key, row in w["eps"].items():
            if row.get("labels") is None or row.get("again") is None:
                continue
            ep = int(key)
            a, b = (_ep_counts(row[x], ep) for x in ("labels", "again"))
            d2.append(abs(a[0] - b[0]))
            d3.append(abs(a[1] - b[1]))
            same += len(row["labels"]) == len(row["again"])
            n += 1
    bad, total = count_errors(labels)
    lo, hi = _trail().wilson(same, n)
    return {"pairs": n, "v2_gap_mean": round(sum(d2) / n, 3) if n else None, "v3_gap_mean": round(sum(d3) / n, 3) if n else None,
            "count_agree": round(same / n, 3) if n else None, "count_agree_ci": [round(lo, 3), round(hi, 3)] if n else None,
            "errors": bad, "calls": total}


def _ep_counts(items: list[dict], ep: int) -> tuple[int, int]:
    ds = [_dist(x, ep) for x in items if x["kind"] == "마음"]
    return (sum(d is not None and NEAR[0] <= d <= NEAR[1] for d in ds), sum(d is not None and d > FAR for d in ds))


def _agree_rows(path: Optional[str]) -> dict:
    """metric_agree.py run 의 JSON 에서 낱값마다 레퍼런스 쪽을 맞힌 쌍 수를 읽는다."""
    if not path:
        return {}
    res = json.loads(Path(path).read_text(encoding="utf-8"))["results"]["all"].get("ident/truth", {})
    return {n: {"agree": m["agree"], "n": m["n"]} for n, m in res.get("metrics", {}).items() if n in V1_NAMES}


def _v1_verdicts(agree: dict) -> dict:
    out = {}
    for n in V1_NAMES:
        row = agree.get(n)
        out[n] = {"agree": None, "n": None, "verdict": "검증 값 없음"} if not row else {
            **row, "verdict": "가른다" if row["agree"] >= AGREE_MIN else "못 가른다"}
    return out


def table(labels: dict, agree: Optional[dict] = None) -> dict:
    """세 값 · 글별 · 묶음별 · 구간 · 흔들림. 키: works(글별), groups(ref · canon), splits, v1_verdicts, jitter."""
    rows = {k: ep_rows(w) for k, w in labels["works"].items()}
    kind_of = {k: w["kind"] for k, w in labels["works"].items()}
    works = {k: {"kind": kind_of[k], "eps": len(rows[k]), **_values(rows[k], labels["works"][k]["can3"])} for k in rows}
    groups = {}
    for kind in ("ref", "canon"):
        ks = [k for k in rows if kind_of[k] == kind]
        pooled = [r for k in ks for r in rows[k]]
        pooled3 = [r for k in ks if labels["works"][k]["can3"] for r in rows[k]]
        groups[kind] = {"eps": len(pooled), **_values(pooled, False), "v3_eps": len(pooled3)}
        if pooled3:
            groups[kind]["v3"] = _cell(pooled3, "c3")
    return {"works": works, "groups": groups, "splits": _splits(works, kind_of),
            "group_splits": {v: not _overlap(groups["ref"][v]["ci"], groups["canon"][v]["ci"]) and bool(groups["ref"][v]["ci"])
                             and bool(groups["canon"][v]["ci"]) for v in ("v2", "v3")},
            "v1_verdicts": _v1_verdicts(agree or {}), "jitter": jitter(labels)}


def _fmt(cell: dict) -> str:
    if cell.get("value") is None:
        return cell.get("note", "-")
    ci = cell.get("ci")
    return f"{cell['value']:.3f}" + (f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "")


def table_md(t: dict) -> str:
    head = ["# 심리 세 값 표", "", *RULES, ""]
    cols = ("thought_per_1k", "inner_line_share", "v2", "v3")
    lines = ["| 글 | 갈래 | 화 | " + " | ".join(cols) + " |", "|---|---|---|" + "---|" * len(cols)]
    for k, w in t["works"].items():
        lines.append(f"| {k} | {w['kind']} | {w['eps']} | " + " | ".join(_fmt(w[c]) for c in cols) + " |")
    for kind, g in t["groups"].items():
        lines.append(f"| 묶음 {kind} | {kind} | {g['eps']} | " + " | ".join(_fmt(g[c]) for c in cols) + " |")
    verdict = ["", "## 판정", ""]
    for n, v in t["v1_verdicts"].items():
        shown = f"{v['agree']}/{v['n']}" if v["n"] else "-"
        verdict.append(f"- 값 1 {n}: {v['verdict']} ({shown}쌍)")
    for v in ("v2", "v3"):
        verdict.append(f"- {v} 묶음: {'가른다' if t['group_splits'][v] else '못 가른다'}")
        verdict += [f"- {v} {k}: {'가른다' if s else '못 가른다'}" for k, s in t["splits"][v].items()]
    j = t["jitter"]
    tail = ["", "## 같은 화를 다시 매긴 흔들림", "",
            f"- 다시 매긴 화 {j['pairs']}개, 값 2 건수 차 평균 {j['v2_gap_mean']}, 값 3 건수 차 평균 {j['v3_gap_mean']}",
            f"- 라벨 수 일치율 {j['count_agree']} 구간 {j['count_agree_ci']}",
            f"- 형식 오류 {j['errors']}번 / 호출 {j['calls']}번", ""]
    return "\n".join(head + lines + verdict + tail)


def cmd_table(a) -> None:
    labels = _read(Path(a.labels))
    t = table(labels, _agree_rows(a.agree) if a.agree else None)
    Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_md).write_text(table_md(t), encoding="utf-8")
    _dump(Path(a.out_json), t)
    print(table_md(t))


# ---------- 명령줄 ----------

def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--refs", nargs="*", default=[])
    s.add_argument("--projects", nargs="*", default=[])
    s.add_argument("--per", type=int, default=20)
    s.add_argument("--seed", type=int, default=SEED)
    s.add_argument("--min-ep", type=int, default=31)
    s.add_argument("--out", required=True)
    lb = sub.add_parser("label")
    lb.add_argument("--samples", required=True)
    lb.add_argument("--model", default="coralbricks:deepseek-v4.1-flash-value")
    lb.add_argument("--repeat", type=int, default=5)
    lb.add_argument("--dry-run", action="store_true")
    lb.add_argument("--out")
    lb.add_argument("--workers", type=int, default=1)
    lb.add_argument("--retries", type=int, default=0)
    lb.add_argument("--max-out", type=int, default=4000)
    lb.add_argument("--timeout", type=float)
    lb.add_argument("--resume", action="store_true")
    t = sub.add_parser("table")
    t.add_argument("--labels", required=True)
    t.add_argument("--agree")
    t.add_argument("--out-md", required=True)
    t.add_argument("--out-json", required=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd == "sample":
        cmd_sample(a)
    elif a.cmd == "label":
        if not a.dry_run and not a.out:
            raise SystemExit("--out 이 필요해요")
        return cmd_label(a)
    else:
        cmd_table(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
