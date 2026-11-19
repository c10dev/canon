"""인물 심리 이어짐 원인 가르기 도구 (목표 character-mind-continuity 의 명세 2).

심리 값(가까운 화 · 먼 화 이어받기)이 레퍼런스와 갈린 까닭을 세 갈래로 가른다.
  재료 없음: 요청 글에 앞 화의 일에 기댄 마음 줄(재료)이 모자란다.
  있는데 안 씀: 재료는 있는데 본문 라벨이 그 재료에 기대지 않는다.
  줄이 막음: 요청의 한 줄(감정 이름 금지)을 빼거나 한 줄을 더하면 값이 바뀐다.
이 스크립트는 store.save 를 부르지 않는다. 작품과 .refs 는 읽기만 하고 --out 경로에만 쓴다.
출력에는 글 키(C1, C2, ...)만 찍는다. 작품 이름 · 제목 · 인물 이름 · 본문 · 요청 구절을 넣지 않는다.
LLM 호출은 material 과 ablate 만 한다(유료). 둘 다 --dry-run 으로 어림 비용부터 본다.

실행 (작품과 .refs 를 임시 CANON_HOME 에 복사해 둔다):
  CANON_HOME=<임시 폴더> CANON_LLM=mock python scripts/mind_cause.py scan --projects 작품 ... \\
      --out <out>/scan.json --samples-out <out>/samples/samples.json
  CANON_HOME=<임시 폴더> python scripts/mind_cause.py material --projects 작품 ... --repeat 5 --dry-run
  CANON_HOME=<임시 폴더> python scripts/mind_cause.py material --projects 작품 ... --out <out>/material.json
  python scripts/mind_measure.py label --samples <out>/samples/samples.json --out <out>/labels.json ...
  python scripts/mind_cause.py use --material <out>/material.json --labels <out>/labels.json --out-md U.md --out-json U.json
  CANON_HOME=<임시 폴더> python scripts/mind_cause.py ablate --project 작품 --arms B1 B2 S M --dry-run
  python scripts/mind_cause.py table --scan <out>/scan.json --use U.json --ablate <out>/ablate --out-md C.md --out-json C.json
"""
import argparse
import importlib.util
import json
import os
import random
import re
import statistics
import sys
import threading
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CANON_LLM", "mock")

from canon import llm as llm_mod  # noqa: E402
from canon import metrics, pipeline, prompts, settings, store, usage  # noqa: E402


_MODS: dict = {}


def _load(name: str):
    """scripts/<name>.py 를 importlib 로 한 번만 불러 온다(모듈 전역 캐시)."""
    if name not in _MODS:
        path = Path(__file__).resolve().parent / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODS[name] = mod
    return _MODS[name]


class _Lazy:
    """scripts/<이름>.py 를 처음 쓸 때 한 번만 불러 온다."""

    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_load(self._name), attr)


mm = _Lazy("mind_measure")
tm = _Lazy("trail_measure")
cm = _Lazy("context_measure")

SEED = 20261119
MIN_EP = 4                       # 대상 화는 snapshot_eps 가운데 4화 이상
NEAR = (1, 3)
FAR = 10                         # 4~10 은 '가운데'
FLASH_MODEL = "coralbricks:deepseek-v4.1-flash"
WRITE_MODEL = "stage"            # 단계 설정의 쓰기 모델 (llm.get_llm("write"))
CHARS_PER_TOKEN = 1.7
MATERIAL_OUT_TOKENS = 800        # material 호출당 출력 토큰 어림
WRITE_OUT_TOKENS = 20000         # 쓰기 호출당 출력(생각 포함) 어림 상한
MATERIAL_MAX = 60                # 재료 항목이 이 수 이상이면 그 화는 실패(err "Capped")
ERROR_LIMIT = 0.10
POV_LINE = "다른 인물의 속마음은 행동과 대사로만"
M_LINE = "시점 인물이 지금 느끼고 판단하고 고르는 것을, 위 자료에 있는 앞 화의 일에 기대어 지문과 속생각으로 적습니다."
ABLATE_RANGE = (69, 88)
ABLATE_EPS = 4
ARMS = ("B1", "B2", "S", "M")    # X 는 늘 함께 낸다(저장된 본문, 새 호출 없음)
ALL_ARMS = ARMS + ("P", "T")     # --arms 로 고를 수 있는 판
P_SENTENCE = "다른 인물의 속마음은 행동과 대사로만 드러냅니다."
T_LINE = "시점 인물이 지금 무엇을 생각하고 판단하는지, 지문과 속생각으로 적습니다."
ABLATE_BUDGET = 4.0
BUCKET_OF = {"v2": "near", "v3": "far"}

MATERIAL_SYSTEM = (
    "너는 소설 편집자다. 소설 한 화를 쓰라는 요청 글 전체를 받는다. 요청 글은 '# 제목' 줄로 블록이 나뉜다.\n"
    "찾을 것(재료): 요청 글 안에서, 인물이 앞 화의 일을 두고 느낀 것 · 판단한 것 · 정한 것 · 상대를 보는 눈을 적은 줄.\n"
    "넣지 않는 것: 일어난 일만 적은 줄, 늘 그런 성격 · 말투 설정, 이번 화에 할 일만 적은 지시.\n"
    "항목마다 그 줄이 든 블록의 제목을 block 에, 그 줄이 기대는 앞 화 번호를 source_ep 에 적는다. 화 번호를 요청 글에서 찾지 못하면 source_ep 는 null.\n"
    "kind: 느낌 · 판단이면 '마음', 다른 인물을 보는 눈이면 '보는 눈', 정한 것 · 고른 것이면 '결정'.\n"
    "요청 글의 구절은 옮겨 적지 않는다. 없으면 빈 목록을 돌려준다."
)


class MaterialItem(BaseModel):
    block: str
    source_ep: Optional[int] = None
    kind: Literal["마음", "보는 눈", "결정"]


class MaterialItems(BaseModel):
    items: list[MaterialItem] = []      # dict 필드 없음 (tests/test_schema_nodict.py 규칙)


class EmptyText(Exception):
    """쓰기 호출이 빈 글을 돌려줬다."""


# ---------- 글 키 · 블록 이름 ----------

def work_keys(projects: list[str], keymap_path: Optional[str]) -> dict[str, str]:
    """작품 이름 → 글 키. keymap_path(mind_measure sample 이 쓴 keymap.json)가 있으면 kind == "canon" 줄의 ident → 키를 쓴다.
    없거나 거기 없는 작품은 --projects 차례로 C1, C2, ... (이미 쓴 키는 건너뛴다)."""
    keymap = _read(Path(keymap_path)) if keymap_path else None
    known = {v["ident"]: k for k, v in (keymap or {}).items() if v.get("kind") == "canon"}
    used = set(keymap or {})
    out: dict[str, str] = {}
    for name in projects:
        if name in known:
            out[name] = known[name]
    used |= set(out.values())
    i = 0
    for name in projects:
        if name in out:
            continue
        i += 1
        while f"C{i}" in used:
            i += 1
        out[name] = f"C{i}"
        used.add(out[name])
    return out


def block_name(head: str) -> str:
    """cm.sections 의 제목 → 안정된 이름. ' (' 와 ':' 앞까지 자르고 숫자 덩어리는 'N' 으로 바꾼다."""
    cut = head
    for sep in (" (", ":"):
        cut = cut.split(sep, 1)[0]
    return re.sub(r"\d+", "N", cut.strip())


def blocks_of(prompt: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for head, body in cm.sections(prompt).items():
        name = block_name(head)
        out[name] = out.get(name, 0) + len(body)
    return out


def _read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None


def _dump(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _median(vals: list):
    return statistics.median(vals) if vals else None


# ---------- scan ----------

def target_eps(p) -> list[int]:
    return [n for n in tm.snapshot_eps(p) if n >= MIN_EP]


def _build(p, n: int):
    """(q, 요청 글). 스냅샷이 없으면 None."""
    if not cm.exact_ok(p, n):
        return None
    q = cm.rebuild(p, n, "exact")
    return q, prompts.episode_prompt(q, n)


def _fact_dist(prompt: str, n: int) -> dict[str, int]:
    out = {"1-3": 0, "4-10": 0, "10+": 0}
    for head, body in cm.sections(prompt).items():
        if block_name(head) != "확정된 사실":
            continue
        for line in body.split("\n"):
            m = re.match(r"^- \((\d+)화\) ", line)
            d = n - int(m.group(1)) if m else 0
            if d >= 1:
                out["1-3" if d <= 3 else "4-10" if d <= 10 else "10+"] += 1
    return out


def _emo_lens(q, prompt: str) -> list[int]:
    lens = []
    for c in q.characters:
        if c.name and c.name in prompt:
            lens += [len(s.emotional_state.strip()) for s in q.states
                     if s.character_id == c.id and s.emotional_state.strip()]
    return lens


def scan_ep(p, n: int) -> Optional[dict]:
    got = _build(p, n)
    if got is None:
        return None
    q, prompt = got
    blocks = blocks_of(prompt)
    lens = _emo_lens(q, prompt)
    return {"prompt_chars": len(prompt), "blocks": blocks,
            "carry": len(q.episode(n).plot.carry), "trails": len(q.trails),
            "facts": _fact_dist(prompt, n), "emo_chars": len(lens), "emo_len_median": _median(lens),
            "tail_chars": sum(v for k, v in blocks.items() if k.startswith("직전 화")),
            "shift_line": int(prompts.WRITE_SHIFT_LINE in prompt), "pov_line": int(POV_LINE in prompt)}


def _scan_work(p) -> dict:
    snaps = tm.snapshot_eps(p)
    eps, unknown = {}, []
    for n in target_eps(p):
        row = scan_ep(p, n)
        if row is None:
            unknown.append(n)
        else:
            eps[str(n)] = row
    return {"snapshot_eps": len(snaps), "targets": len(eps), "unknown": unknown, "eps": eps}


def _samples_work(name: str, scanned: dict) -> dict:
    body = tm.canon_episodes(name, 1)
    texts = dict(body)
    eps = [int(n) for n in scanned["eps"]]
    return {"kind": "canon", "eps": eps, "can3": len(body) >= mm.SHORT_ENDS,
            "chars": {str(n): len(texts[n]) for n in eps}, "v1": {str(n): mm._v1(texts[n]) for n in eps}}


def _write_samples(path: Path, works: dict, keys: dict[str, str]) -> None:
    keymap = {keys[name]: {"kind": "canon", "ident": name} for name in works}
    old = _read(path.parent / "keymap.json")
    if old is not None and old != keymap:
        raise SystemExit("그 폴더의 keymap.json 이 달라요. 새 폴더를 주세요")
    _dump(path, {"seed": SEED, "per": 0, "min_ep": MIN_EP, "works": {keys[n]: w for n, w in works.items()}})
    _dump(path.parent / "keymap.json", keymap)


def cmd_scan(a) -> None:
    keys = work_keys(a.projects, a.keymap)
    works, samples = {}, {}
    for name in a.projects:
        w = _scan_work(store.load(name))
        works[keys[name]] = w
        if a.samples_out:
            samples[name] = _samples_work(name, w)
        print(f"{keys[name]} 대상 화 {w['targets']} 모름 {len(w['unknown'])}")
    _dump(Path(a.out), {"works": works})
    if a.samples_out:
        _write_samples(Path(a.samples_out), samples, keys)


# ---------- material ----------

def material_ep(llm, n: int, prompt: str, max_out: Optional[int]) -> list[dict]:
    """한 화의 재료. 돌려주는 dict: {"block", "source_ep", "kind"}. 구절은 받지도 저장하지도 않는다."""
    got = mm._capped(llm, max_out, lambda: llm.json(MATERIAL_SYSTEM, f"{n}화 쓰기 요청:\n{prompt}", MaterialItems))
    out = []
    for it in got.items:
        src = it.source_ep if it.source_ep is not None and 0 < it.source_ep < n else None
        out.append({"block": block_name(it.block), "source_ep": src, "kind": it.kind})
    return out


def _try_material(llm, n: int, prompt: str, retries: int, max_out: Optional[int]):
    """(재료 목록 또는 None, 실패한 예외 클래스 이름 또는 None)."""
    try:
        res = mm._retry(lambda: material_ep(llm, n, prompt, max_out), retries)
    except Exception as e:  # noqa: BLE001 형식 오류 · 잘림은 세어서 보고한다
        return None, type(e).__name__
    if len(res) >= MATERIAL_MAX:
        return None, "Capped"
    return res, None


def material_dry_run(prompts_by_key: dict[str, dict[int, str]], model: str, repeat: int) -> dict:
    """호출 수 · 글자 수 · 어림 비용. LLM 을 부르지 않는다."""
    calls = chars = 0
    extra = len(MATERIAL_SYSTEM)
    for by_ep in prompts_by_key.values():
        ns = sorted(by_ep)
        calls += len(ns) + min(repeat, len(ns))
        chars += sum(len(by_ep[n]) + extra for n in ns) + sum(len(by_ep[n]) + extra for n in ns[:repeat])
    tin, tout = chars / CHARS_PER_TOKEN, calls * MATERIAL_OUT_TOKENS
    return {"model": model, "calls": calls, "chars": chars, "cost_usd": round(usage.cost(mm._price(model), tin, tout), 4)}


def _prompts_for(p) -> tuple[dict[int, str], list[int]]:
    by_ep, unknown = {}, []
    for n in target_eps(p):
        got = _build(p, n)
        if got is None:
            unknown.append(n)
        else:
            by_ep[n] = got[1]
    return by_ep, unknown


def _material_tasks(ns: list[int], repeat: int, old: dict) -> tuple[list[tuple[int, str]], dict]:
    todo, kept = [], {}
    for i, n in enumerate(ns):
        for name in ("items", "again") if i < repeat else ("items",):
            prev = (old.get(str(n)) or {}).get(name)
            if prev is not None:
                kept[(n, name)] = prev
            else:
                todo.append((n, name))
    return todo, kept


def _material_work(llm, by_ep: dict[int, str], unknown: list[int], a, old: dict, key: str) -> dict:
    ns = sorted(by_ep)
    todo, kept = _material_tasks(ns, a.repeat, old)
    got, errs, lock = dict(kept), {}, threading.Lock()

    def one(task) -> None:
        n, name = task
        res, err = _try_material(llm, n, by_ep[n], a.retries, a.max_out)
        with lock:
            got[task] = res
            if err:
                errs[task] = err
            if len(got) % 20 == 0:
                print(f"{key} 재료 {len(got)}/{len(todo) + len(kept)}", flush=True)

    mm._par(a.workers, one, todo)
    eps = {}
    for n in ns:
        row = {"items": got[(n, "items")]}
        if (n, "items") in errs:
            row["err"] = errs[(n, "items")]
        if (n, "again") in got:
            row["again"] = got[(n, "again")]
            if (n, "again") in errs:
                row["again_err"] = errs[(n, "again")]
        eps[str(n)] = row
    return {"unknown": unknown, "eps": eps}


def _count_material(works: dict) -> tuple[int, int]:
    bad = total = 0
    for w in works.values():
        for row in w["eps"].values():
            for name in ("items", "again"):
                if name in row:
                    total += 1
                    bad += row[name] is None
    return bad, total


def _material_doc(a, works: dict) -> dict:
    bad, total = _count_material(works)
    return {"model": a.model, "repeat": a.repeat, "errors": bad, "calls": total, "works": works}


def cmd_material(a, llm=None) -> int:
    keys = work_keys(a.projects, a.keymap)
    loaded = {keys[name]: _prompts_for(store.load(name)) for name in a.projects}
    if a.dry_run:
        print(json.dumps(material_dry_run({k: v[0] for k, v in loaded.items()}, a.model, a.repeat), ensure_ascii=False, indent=1))
        return 0
    if a.timeout:
        os.environ["CANON_LOCAL_TIMEOUT"] = str(a.timeout)
    llm = llm or mm._PerThread(lambda: mm.make_llm(a.model))
    prev = ((_read(Path(a.out)) or {}).get("works") or {}) if a.resume else {}
    works: dict = {}
    for key, (by_ep, unknown) in loaded.items():
        old = (prev.get(key) or {}).get("eps") or {}
        works[key] = _material_work(llm, by_ep, unknown, a, old, key)
        _dump(Path(a.out), _material_doc(a, {**prev, **works}))
    doc = _material_doc(a, works)
    _dump(Path(a.out), doc)
    print(f"호출 {doc['calls']}번 형식 오류 {doc['errors']}번")
    if doc["calls"] and doc["errors"] / doc["calls"] > ERROR_LIMIT:
        print(f"형식 오류가 {ERROR_LIMIT:.0%} 를 넘었어요. 멈추고 원인을 먼저 봐요")
        return 2
    return 0


# ---------- use ----------

LIMIT_LINE = "재료와 본문 라벨은 화 번호(1화 안쪽)로만 맞춘다. 내용은 견주지 않는다."


def bucket(d: Optional[int]) -> str:
    if d is None or d < 1:
        return "unknown"
    return "near" if d <= NEAR[1] else "mid" if d <= FAR else "far"


def _dist_of(n: int, src: Optional[int]) -> Optional[int]:
    return None if src is None or src >= n else n - src


def _counts(n: int, items: list[dict]) -> dict[str, int]:
    out = {"near": 0, "mid": 0, "far": 0, "unknown": 0}
    for it in items:
        out[bucket(_dist_of(n, it.get("source_ep")))] += 1
    return out


def _close(src: int, others: list[int]) -> bool:
    return any(abs(o - src) <= 1 for o in others)


def match_ep(n: int, items: list[dict], labels: list[dict]) -> dict:
    """재료와 본문 '마음' 라벨을 화 번호(1화 안쪽)로 맞춘다. 내용은 견주지 않는다."""
    mind = [x for x in labels if x.get("kind") == "마음" and x.get("source_ep") is not None]
    msrc = [m["source_ep"] for m in items if m.get("source_ep") is not None]
    lsrc = [x["source_ep"] for x in mind]
    mat = _counts(n, items)
    used = _counts(n, [m for m in items if m.get("source_ep") is not None and _close(m["source_ep"], lsrc)])
    body = _counts(n, mind)
    grounded = _counts(n, [x for x in mind if _close(x["source_ep"], msrc)])
    blocks: dict[str, int] = {}
    for m in items:
        blocks[m["block"]] = blocks.get(m["block"], 0) + 1
    used.pop("unknown")
    return {"mat": mat, "used": used, "body": {k: body[k] for k in ("near", "far")},
            "grounded": {k: grounded[k] for k in ("near", "far")}, "blocks": blocks}


def _quart(vals: list) -> tuple:
    if not vals:
        return None, None, None
    med = statistics.median(vals)
    if len(vals) < 2:
        return med, med, med
    q = statistics.quantiles(vals, n=4)
    return med, q[0], q[2]


def expected_of(rows: list[dict], m1: Optional[dict], b: str) -> Optional[float]:
    """레퍼런스 한 화의 기대 건수의 화별 중앙값: 화마다 ref_low × chars / 10000. 값이 없으면 None."""
    if not m1 or not rows:
        return None
    v = "v2" if b == "near" else "v3"
    vals = [(w.get(v) or {}).get("value") for w in m1.get("works", {}).values() if w.get("kind") == "ref"]
    vals = [x for x in vals if x is not None]
    if not vals:
        return None
    return round(statistics.median(min(vals) * r["chars"] / 10000 for r in rows), 3)


def _ratio(a: int, b: int) -> Optional[float]:
    return round(a / b, 3) if b else None


def _cell(eps: list[dict], b: str, m1: Optional[dict]) -> dict:
    med, q1, q3 = _quart([d["m"]["mat"][b] for d in eps])
    grounded = _ratio(sum(d["m"]["grounded"][b] for d in eps), sum(d["m"]["body"][b] for d in eps))
    return {"median": med, "q1": q1, "q3": q3,
            "used_ratio": _ratio(sum(d["m"]["used"][b] for d in eps), sum(d["m"]["mat"][b] for d in eps)),
            "grounded": grounded, "ungrounded": None if grounded is None else round(1 - grounded, 3),
            "expected": expected_of([{"chars": d["chars"]} for d in eps], m1, b)}


def _jitter(eps: list[dict], b: str) -> Optional[float]:
    gaps = [abs(d["m"]["mat"][b] - d["again"][b]) for d in eps if d.get("again") is not None]
    return round(sum(gaps) / len(gaps), 3) if gaps else None


def _usable(material: dict, labels: dict) -> tuple[dict, dict]:
    """({키: [화 자료]}, {키: 쓰지 못한 화 수}). 두 칸(items, labels)이 모두 None 이 아닌 화만 쓴다."""
    got, missing = {}, {}
    for key, mw in material["works"].items():
        lw = labels["works"].get(key)
        if lw is None:
            continue
        got[key], missing[key] = [], 0
        for ep in sorted(set(mw["eps"]) | set(lw["eps"]), key=int):
            mrow, lrow = mw["eps"].get(ep) or {}, lw["eps"].get(ep) or {}
            if mrow.get("items") is None or lrow.get("labels") is None:
                missing[key] += 1
                continue
            n = int(ep)
            again = mrow.get("again")
            got[key].append({"key": key, "ep": n, "chars": lw["chars"][ep], "m": match_ep(n, mrow["items"], lrow["labels"]),
                             "again": None if again is None else _counts(n, again)})
    return got, missing


def _all_cells(eps: list[dict], m1: Optional[dict]) -> dict:
    total = sum(sum(d["m"]["mat"].values()) for d in eps)
    unknown = sum(d["m"]["mat"]["unknown"] for d in eps)
    return {"v2": _cell(eps, "near", m1), "v3": _cell(eps, "far", m1),
            "unknown_share": _ratio(unknown, total),
            "jitter": {"v2": _jitter(eps, "near"), "v3": _jitter(eps, "far")}}


def use_table(material: dict, labels: dict, m1: Optional[dict]) -> dict:
    got, missing = _usable(material, labels)
    everything = [d for eps in got.values() for d in eps]
    works = {}
    for key, eps in got.items():
        cells = _all_cells(eps, m1)
        works[key] = {"eps": len(eps), "missing": missing[key], "v2": cells["v2"], "v3": cells["v3"]}
    rows = [{"key": d["key"], "ep": d["ep"], "chars": d["chars"], "near": d["m"]["mat"]["near"],
             "far": d["m"]["mat"]["far"], "unknown": d["m"]["mat"]["unknown"]} for d in everything]
    return {"limit": LIMIT_LINE, "works": works, "all": {"eps": len(everything), **_all_cells(everything, m1)}, "rows": rows}


def _num(x) -> str:
    return "-" if x is None else f"{x:.3f}" if isinstance(x, float) else str(x)


def _cell_line(label: str, c: dict) -> str:
    cols = ("median", "q1", "q3", "used_ratio", "grounded", "ungrounded", "expected")
    return f"| {label} | " + " | ".join(_num(c[k]) for k in cols) + " |"


def use_md(u: dict) -> str:
    head = ["# 재료 쓰임 표", "", u["limit"], "",
            "| 글 · 값 | 중앙값 | q1 | q3 | 쓴 재료 비율 | 근거 있음 | 근거 없음 | 기대 건수 |",
            "|---|---|---|---|---|---|---|---|"]
    lines = []
    for key, w in u["works"].items():
        for v in ("v2", "v3"):
            lines.append(_cell_line(f"{key} {v} (화 {w['eps']}, 못 씀 {w['missing']})", w[v]))
    a = u["all"]
    for v in ("v2", "v3"):
        lines.append(_cell_line(f"전체 {v} (화 {a['eps']})", a[v]))
    tail = ["", f"- 거리 모름 재료 몫 {_num(a['unknown_share'])}",
            f"- 다시 매긴 흔들림 v2 {_num(a['jitter']['v2'])} v3 {_num(a['jitter']['v3'])}", ""]
    return "\n".join(head + lines + tail)


def cmd_use(a) -> None:
    m1 = _read(Path(a.m1)) if a.m1 else None
    u = use_table(_read(Path(a.material)), _read(Path(a.labels)), m1)
    Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_md).write_text(use_md(u), encoding="utf-8")
    _dump(Path(a.out_json), u)
    print(use_md(u))


# ---------- ablate ----------

def pick_ablate(p, k: int = ABLATE_EPS) -> list[int]:
    pool = [n for n in target_eps(p) if ABLATE_RANGE[0] <= n <= ABLATE_RANGE[1]]
    return sorted(random.Random(SEED).sample(pool, min(k, len(pool))))


def arm_prompts(base: str) -> dict[str, Optional[str]]:
    return {"B1": base, "B2": base,
            "S": base.replace(prompts.WRITE_SHIFT_LINE, "", 1) if prompts.WRITE_SHIFT_LINE in base else None,
            "M": base + "\n" + M_LINE,
            "P": _drop_sentence(base),
            "T": base + "\n" + T_LINE}


def _drop_sentence(base: str) -> Optional[str]:
    """P 판: P_SENTENCE 를 앞의 공백 하나까지 한 번 지운다. 없으면 None(해당 없음)."""
    if P_SENTENCE not in base:
        return None
    return base.replace(" " + P_SENTENCE if " " + P_SENTENCE in base else P_SENTENCE, "", 1)


def _head_kept(q, n: int, aps: dict) -> dict[str, bool]:
    head = prompts.write_head(q, n)
    return {arm: pr.startswith(head) for arm, pr in aps.items() if pr is not None}


def _write_price_name(write_model: str) -> str:
    return (settings.stage_model("write")[0] or settings.model()[0]) if write_model == WRITE_MODEL else write_model


def _cost(model: str, chars: int, calls: int, out_tokens: int) -> float:
    return round(usage.cost(mm._price(model), chars / CHARS_PER_TOKEN, calls * out_tokens), 4)


def _label_estimate(p, eps: list[int], arms: list[str], have: set[int]) -> tuple[int, int]:
    top = max(eps)
    bodies = {e.plot.number: cm.body_of(p, e.plot.number) for e in p.episodes}
    need = [n for n, t in bodies.items() if t and n < top and n not in have]
    calls = len(need) + (len(arms) + 1) * len(eps)
    chars = sum(len(bodies[n]) + mm.PROMPT_CHARS for n in need)
    chars += sum(p.meta.words_per_episode + mm.PROMPT_CHARS + (n - 1) * mm.SUMMARY_CHARS for n in eps) * (len(arms) + 1)
    return calls, chars


def ablate_dry_run(p, eps: list[int], arms: list[str], write_model: str, label_model: str, summaries_have: set[int]) -> dict:
    """호출 수 · 글자 수 · 어림 비용. LLM 을 부르지 않는다."""
    wcalls = wchars = shift = 0
    kept: dict[str, bool] = {}
    for n in eps:
        q = cm.rebuild(p, n, "exact")
        aps = arm_prompts(prompts.episode_prompt(q, n))
        shift += aps["S"] is not None
        system = len(prompts.writer_system(q))
        for arm, ok in _head_kept(q, n, aps).items():
            kept[arm] = kept.get(arm, True) and ok
        for arm in arms:
            if aps[arm] is not None:
                wcalls += 1
                wchars += len(aps[arm]) + system
    lcalls, lchars = _label_estimate(p, eps, arms, summaries_have)
    wcost = _cost(_write_price_name(write_model), wchars, wcalls, WRITE_OUT_TOKENS)
    lcost = _cost(label_model, lchars, lcalls, mm.OUT_TOKENS)
    return {"eps": eps, "write": {"calls": wcalls, "chars": wchars, "cost_usd": wcost},
            "label": {"calls": lcalls, "chars": lchars, "cost_usd": lcost},
            "total_usd": round(wcost + lcost, 4), "shift_eps": shift, "head_kept": {a: kept.get(a) for a in arms}}


def _summaries_have(a) -> set[int]:
    src = Path(a.summaries) if a.summaries else (Path(a.out) / "summaries.json" if a.out else None)
    return {int(k) for k in (_read(src) or {})} if src else set()


def _ablate_eps(a, p) -> list[int]:
    if a.eps:
        return sorted(a.eps)
    eps = pick_ablate(p)
    have = _summaries_have(a)
    est = ablate_dry_run(p, eps, a.arms, a.write_model, a.label_model, have)
    if est["total_usd"] > ABLATE_BUDGET:
        print(f"어림이 ${ABLATE_BUDGET:.0f} 를 넘어요. 3화로 줄여요")
        eps = pick_ablate(p, 3)
        print(f"줄인 어림 ${ablate_dry_run(p, eps, a.arms, a.write_model, a.label_model, have)['total_usd']}")
    return eps


def _write_llm(a):
    if a.write_model == WRITE_MODEL:
        return mm._PerThread(lambda: llm_mod.get_llm("write"))
    provider, _, name = a.write_model.partition(":")
    effort = settings.stage_effort("write")[0]
    return mm._PerThread(lambda: llm_mod.make_llm(provider, name, effort))


def _write_model_name(a) -> str:
    if a.write_model == WRITE_MODEL:
        return f"{settings.stage_provider('write')[0]}:{settings.stage_model('write')[0]}"
    return a.write_model


def _check_write_not_mock(a) -> None:
    """쓰기 모델이 단계 설정이고 그 백엔드가 mock 이면 멈춘다. mock 으로 돌리려면 --write-model mock 을 준다."""
    if a.write_model == WRITE_MODEL and settings.stage_provider("write")[0] == "mock":
        raise SystemExit("쓰기 모델이 mock 이에요. CANON_LLM 을 주세요 (mock 으로 돌리려면 --write-model mock)")


def _text_path(out: Path, key: str, n: int, arm: str) -> Path:
    return out / "texts" / f"{key}-{n}-{arm}.txt"


def _write_one(llm, task, out: Path, key: str, retries: int) -> None:
    n, arm, q, prompt = task
    text = mm._retry(lambda: pipeline._write(llm, q, n, prompt), retries)
    if not text or not text.strip():
        raise EmptyText("빈 글이에요")
    path = _text_path(out, key, n, arm)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_stage(a, llm, ctx: dict, out: Path, key: str) -> tuple[dict, bool]:
    """판마다 본문을 쓴다. 실패가 있는 화가 화 수의 반을 넘으면 멈춘다. (실패 목록, 멈췄는가)."""
    errors: dict[str, str] = {}
    failed: set[int] = set()
    lock = threading.Lock()

    def one(task) -> None:
        try:
            _write_one(llm, task, out, key, a.retries)
        except Exception as e:  # noqa: BLE001 거절 · 끊김은 세어서 보고한다
            with lock:
                errors[f"{task[1]}-{task[0]}"] = type(e).__name__
                failed.add(task[0])

    for n, (q, aps) in ctx.items():
        todo = [(n, arm, q, aps[arm]) for arm in a.arms if aps[arm] is not None and not _text_path(out, key, n, arm).exists()]
        mm._par(a.workers, one, todo)
        if len(failed) * 2 > len(ctx):
            return errors, True
    return errors, False


def _text_of(p, out: Path, key: str, n: int, arm: str) -> Optional[str]:
    if arm == "X":
        return cm.body_of(p, n)
    path = _text_path(out, key, n, arm)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _ep_values(p, n: int, text: str, labels: Optional[list], err: Optional[str]) -> dict:
    row = {"thought_per_1k": metrics.thought_per_1k(text), "inner_line_share": metrics.inner_line_share(text),
           "chars": len(text), "body_per_1k": metrics.body_per_1k(text),
           "style_distance": metrics.style_distance(p.style_baseline, text) if p.style_baseline else None,
           "c2": None, "c3": None}
    if err:
        row["err"] = err
    if labels is not None:
        ds = [mm._dist(x, n) for x in labels if x["kind"] == "마음"]
        row["c2"] = sum(d is not None and NEAR[0] <= d <= NEAR[1] for d in ds)
        row["c3"] = sum(d is not None and d > FAR for d in ds)
    return row


def arm_summary(rows: list) -> Optional[dict]:
    rows = [r for r in rows if isinstance(r, dict) and "chars" in r]
    if not rows:
        return None
    ok = [r for r in rows if r.get("c2") is not None]
    chars = sum(r["chars"] for r in ok)
    out = {v: (round(sum(r[c] for r in ok) / chars * 10000, 3) if chars else None) for v, c in (("v2", "c2"), ("v3", "c3"))}
    for f in ("thought_per_1k", "inner_line_share", "body_per_1k", "style_distance"):
        vals = [r[f] for r in rows if r.get(f) is not None]
        out[f] = round(sum(vals) / len(vals), 4) if vals else None
    return out


def _label_stage(a, llm, p, key: str, eps: list[int], out: Path, prev: dict, na: dict[str, set[int]]) -> tuple[dict, dict]:
    """(판별 줄, 실패 목록)."""
    summaries = mm.summarize(llm, tm.canon_episodes(a.project, 1), out / "summaries.json", upto=max(eps),
                             workers=a.workers, retries=a.retries, stats={}, max_out=a.max_out)
    arms = ("X", *a.arms)
    done: dict[tuple, tuple] = {}
    lock = threading.Lock()

    def one(task) -> None:
        arm, n = task
        res, err = mm._try_label_err(llm, n, _text_of(p, out, key, n, arm), summaries, a.retries, a.max_out)
        if res is not None and len(res) >= mm.LABEL_MAX:
            res, err = None, "Capped"
        with lock:
            done[task] = (res, err)

    todo = [(arm, n) for arm in arms for n in eps
            if (arm == "X" or _text_path(out, key, n, arm).exists())
            and (prev.get(arm, {}).get("eps", {}).get(str(n)) or {}).get("c2") is None]
    mm._par(a.workers, one, todo)
    env = {"done": done, "prev": prev, "errors": {}, "na": na}
    rows = {arm: {str(n): _arm_row(p, out, key, n, arm, env) for n in eps} for arm in arms}
    return rows, env["errors"]


def _arm_row(p, out: Path, key: str, n: int, arm: str, env: dict):
    """한 칸의 값. env 는 done(라벨 결과) · prev(이전 줄) · errors · na(판마다 해당 없는 화 번호)."""
    if n in env["na"].get(arm, ()):
        return "해당 없음"
    old = env["prev"].get(arm, {}).get("eps", {}).get(str(n)) or {}
    if old.get("c2") is not None:
        return old
    text = _text_of(p, out, key, n, arm)
    if text is None:
        return {"err": "NoText"}
    res, err = env["done"].get((arm, n), (None, "NotLabeled"))
    if err:
        env["errors"][f"label-{arm}-{n}"] = err
    return _ep_values(p, n, text, res, err)


def _arm_doc(rows: dict, kept: dict) -> dict:
    out = {}
    for arm, eps in rows.items():
        doc = {"eps": eps, "summary": arm_summary(list(eps.values()))}
        if arm in kept:
            doc["head_kept"] = kept[arm]
        out[arm] = doc
    return out


def _prepare_out(a, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "summaries.json"
    if a.summaries and not dest.exists():
        dest.write_text(Path(a.summaries).read_text(encoding="utf-8"), encoding="utf-8")


def _ablate_ctx(p, eps: list[int]) -> tuple[dict, dict]:
    ctx, kept = {}, {}
    for n in eps:
        q = cm.rebuild(p, n, "exact")
        aps = arm_prompts(prompts.episode_prompt(q, n))
        ctx[n] = (q, aps)
        for arm, ok in _head_kept(q, n, aps).items():
            kept[arm] = kept.get(arm, True) and ok
    return ctx, kept


def cmd_ablate(a, write_llm=None, label_llm=None) -> int:
    p = store.load(a.project)
    key = work_keys([a.project], a.keymap)[a.project]
    eps = _ablate_eps(a, p)
    print(f"{key} 고른 화 {eps}")
    if a.dry_run:
        print(json.dumps(ablate_dry_run(p, eps, a.arms, a.write_model, a.label_model, _summaries_have(a)), ensure_ascii=False, indent=1))
        return 0
    _check_write_not_mock(a)
    if a.timeout:
        os.environ["CANON_LOCAL_TIMEOUT"] = str(a.timeout)
    out = Path(a.out)
    _prepare_out(a, out)
    write_llm = write_llm or _write_llm(a)
    label_llm = label_llm or mm._PerThread(lambda: mm.make_llm(a.label_model))
    doc = {"key": key, "eps": eps, "write_model": _write_model_name(a), "label_model": a.label_model, "arms": {}, "errors": {}}
    ctx, kept = _ablate_ctx(p, eps)
    errors, stopped = _write_stage(a, write_llm, ctx, out, key)
    doc["errors"] = errors
    if stopped:
        _dump(out / "ablate.json", doc)
        print("쓰기 실패가 화의 반을 넘었어요. 멈추고 원인을 먼저 봐요")
        return 3
    prev = ((_read(out / "ablate.json") or {}).get("arms") or {}) if a.resume else {}
    na = {arm: {n for n, (_, aps) in ctx.items() if aps[arm] is None} for arm in ALL_ARMS}
    rows, label_errors = _label_stage(a, label_llm, p, key, eps, out, prev, na)
    doc["arms"] = _arm_doc(rows, kept)
    doc["errors"] = {**errors, **label_errors}
    _dump(out / "ablate.json", doc)
    print(f"{key} 판 {len(doc['arms'])}개 실패 {len(doc['errors'])}번")
    return 0


# ---------- table ----------

RULES = (
    "판정 규칙 (값을 보기 전에 정했다). 값(v2 가까운 · v3 먼)마다 따로 판정한다.",
    "- 재료 없음: 화당 재료 수의 중앙값이 레퍼런스 한 화의 기대 건수보다 작다",
    "- 있는데 안 씀: 재료 없음이 아니고, 쓴 재료 비율이 0.5 아래다",
    "- 줄이 막음: S · M · P · T 판 가운데 하나의 값이 B1 · B2 평균보다 높고, 그 차가 |B1 − B2| 보다 크다",
    "- 못 가름: 대상 화가 10화 아래이거나, 거리 모름이 재료의 반을 넘거나, 다시 매긴 흔들림이 재료 수 중앙값보다 크다",
    "- '줄이 막음'은 앞 두 판정과 함께 설 수 있다",
    "- X 판과 B 판: |X − B 평균| 이 |B1 − B2| 보다 크면 '옛 길과 지금 길이 다르다'",
)
LIMITS = (
    "- 재료와 본문 라벨은 화 번호(1화 안쪽)로만 맞춘다. 내용은 견주지 않는다",
    "- ablate 는 3~4화다. 두 배쯤 되는 큰 차만 잡는다",
)


def _arm_values(ablate: Optional[dict], v: str) -> dict[str, Optional[float]]:
    out = {}
    for arm, doc in ((ablate or {}).get("arms") or {}).items():
        out[arm] = (doc.get("summary") or {}).get(v)
    return out


def _line_blocks(vals: dict) -> tuple[Optional[bool], Optional[float], Optional[float]]:
    """(줄이 막음, B 평균, |B1 − B2|)."""
    b1, b2 = vals.get("B1"), vals.get("B2")
    if b1 is None or b2 is None:
        return None, None, None
    base, gap = (b1 + b2) / 2, abs(b1 - b2)
    tests = [vals[x] for x in ("S", "M", "P", "T") if vals.get(x) is not None]
    return any(t > base and t - base > gap for t in tests), base, gap


def _undecided(use: Optional[dict], v: str) -> Optional[bool]:
    if use is None:
        return None
    a = use["all"]
    jit, med = a["jitter"].get(v), a[v]["median"]
    return bool(a["eps"] < 10 or (a["unknown_share"] or 0) > 0.5 or (jit is not None and med is not None and jit > med))


def _verdict_text(undecided, flags: dict) -> str:
    if undecided:
        return "못 가름"
    names = [name for name, on in flags.items() if on]
    if names:
        return " · ".join(names)
    return "자료 없음" if all(on is None for on in flags.values()) else "해당 없음"


def _one_verdict(use: Optional[dict], ablate: Optional[dict], v: str) -> dict:
    cell = use["all"][v] if use else None
    no_mat = unused = None
    if cell and cell["expected"] is not None and cell["median"] is not None:
        no_mat = cell["median"] < cell["expected"]
    if cell and no_mat is not None and cell["used_ratio"] is not None:
        unused = (not no_mat) and cell["used_ratio"] < 0.5
    vals = _arm_values(ablate, v)
    line, base, gap = _line_blocks(vals)
    old_new = None
    if base is not None and vals.get("X") is not None:
        old_new = abs(vals["X"] - base) > gap
    und = _undecided(use, v)
    reasons = [f"{n}: {s}" for n, s in (("재료 없음", no_mat), ("있는데 안 씀", unused), ("줄이 막음", line),
                                       ("못 가름", und), ("옛 길과 지금 길", old_new)) if s]
    flags = {"재료 없음": no_mat, "있는데 안 씀": unused, "줄이 막음": line}
    return {"no_material": no_mat, "unused": unused, "line_blocks": line, "undecided": und, "old_vs_new": old_new,
            "reasons": reasons, "verdict": _verdict_text(und, flags)}


def verdicts(use: Optional[dict], ablate: Optional[dict]) -> dict:
    return {v: _one_verdict(use, ablate, v) for v in ("v2", "v3")}


def _scan_summary(scan: dict) -> dict:
    out = {}
    for key, w in scan["works"].items():
        eps = list(w["eps"].values())
        share = lambda f: round(sum(e[f] for e in eps) / len(eps), 3) if eps else None  # noqa: E731
        out[key] = {"targets": w["targets"], "unknown": len(w["unknown"]),
                    "prompt_chars_median": _median([e["prompt_chars"] for e in eps]),
                    "shift_share": share("shift_line"), "pov_share": share("pov_line"),
                    "carry_eps": sum(e["carry"] > 0 for e in eps), "trails_max": max((e["trails"] for e in eps), default=0)}
    return out


def _fill_expected(use: dict, m1: dict) -> None:
    for v, b in BUCKET_OF.items():
        if use["all"][v].get("expected") is None:
            use["all"][v]["expected"] = expected_of(use["rows"], m1, b)


def table(scan: dict, use: Optional[dict], ablate: Optional[dict], m1: Optional[dict]) -> dict:
    if use and m1:
        _fill_expected(use, m1)
    arms = {arm: doc.get("summary") for arm, doc in ((ablate or {}).get("arms") or {}).items()} if ablate else None
    return {"rules": list(RULES), "limits": list(LIMITS), "scan": _scan_summary(scan),
            "use": use["all"] if use else None, "ablate": arms, "verdicts": verdicts(use, ablate)}


def _md_scan(t: dict) -> list[str]:
    lines = ["## 요청 훑기", "", "| 글 | 대상 화 | 모름 | 요청 글자 중앙값 | 감정 이름 금지 줄 | 시점 줄 | carry 화 | 자취 최대 |",
             "|---|---|---|---|---|---|---|---|"]
    for k, s in t["scan"].items():
        lines.append(f"| {k} | {s['targets']} | {s['unknown']} | {_num(s['prompt_chars_median'])} | {_num(s['shift_share'])} "
                     f"| {_num(s['pov_share'])} | {s['carry_eps']} | {s['trails_max']} |")
    return lines + [""]


def _md_verdicts(t: dict) -> list[str]:
    lines = ["## 판정", "", "| 줄 | v2 가까운 | v3 먼 |", "|---|---|---|"]
    names = (("재료 없음", "no_material"), ("있는데 안 씀", "unused"), ("줄이 막음", "line_blocks"),
             ("못 가름", "undecided"), ("옛 길과 지금 길", "old_vs_new"), ("결론", "verdict"))
    for label, field in names:
        lines.append(f"| {label} | " + " | ".join(_num(t["verdicts"][v][field]) for v in ("v2", "v3")) + " |")
    return lines + [""]


def _md_ablate(t: dict) -> list[str]:
    if not t["ablate"]:
        return ["## 판별 값", "", "- 판별 자료 없음", ""]
    cols = ("v2", "v3", "thought_per_1k", "inner_line_share", "body_per_1k", "style_distance")
    lines = ["## 판별 값", "", "| 판 | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for arm, s in t["ablate"].items():
        lines.append(f"| {arm} | " + " | ".join(_num((s or {}).get(c)) for c in cols) + " |")
    return lines + [""]


def table_md(t: dict) -> str:
    return "\n".join(["# 원인 가르기 표", "", *RULES, "", *LIMITS, ""] + _md_scan(t) + _md_verdicts(t) + _md_ablate(t))


def cmd_table(a) -> None:
    ablate = _read(Path(a.ablate) / "ablate.json") if a.ablate else None
    t = table(_read(Path(a.scan)), _read(Path(a.use)) if a.use else None, ablate, _read(Path(a.m1)) if a.m1 else None)
    Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_md).write_text(table_md(t), encoding="utf-8")
    _dump(Path(a.out_json), t)
    print(table_md(t))


# ---------- 명령줄 ----------

def _common_llm(sp) -> None:
    sp.add_argument("--workers", type=int, default=1)
    sp.add_argument("--retries", type=int, default=0)
    sp.add_argument("--timeout", type=float)
    sp.add_argument("--max-out", type=int, default=4000)
    sp.add_argument("--resume", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--out")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--projects", nargs="+", required=True)
    s.add_argument("--keymap")
    s.add_argument("--out", required=True)
    s.add_argument("--samples-out")
    m = sub.add_parser("material")
    m.add_argument("--projects", nargs="+", required=True)
    m.add_argument("--keymap")
    m.add_argument("--model", default=FLASH_MODEL)
    m.add_argument("--repeat", type=int, default=5)
    _common_llm(m)
    u = sub.add_parser("use")
    u.add_argument("--material", required=True)
    u.add_argument("--labels", required=True)
    u.add_argument("--m1")
    u.add_argument("--out-md", required=True)
    u.add_argument("--out-json", required=True)
    ab = sub.add_parser("ablate")
    ab.add_argument("--project", required=True)
    ab.add_argument("--keymap")
    ab.add_argument("--eps", nargs="+", type=int)
    ab.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ALL_ARMS))
    ab.add_argument("--write-model", default=WRITE_MODEL)
    ab.add_argument("--label-model", default=FLASH_MODEL)
    ab.add_argument("--summaries")
    _common_llm(ab)
    t = sub.add_parser("table")
    t.add_argument("--scan", required=True)
    t.add_argument("--use")
    t.add_argument("--ablate")
    t.add_argument("--m1")
    t.add_argument("--out-md", required=True)
    t.add_argument("--out-json", required=True)
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd in ("material", "ablate") and not a.dry_run and not a.out:
        raise SystemExit("--out 이 필요해요")
    if a.cmd == "scan":
        cmd_scan(a)
    elif a.cmd == "material":
        return cmd_material(a)
    elif a.cmd == "use":
        cmd_use(a)
    elif a.cmd == "ablate":
        return cmd_ablate(a)
    else:
        cmd_table(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
