"""인물 심리 이어짐 후보 판 실행기 (목표 character-mind-continuity 의 명세 3).

작품 사본(판 폴더)에 판(B1 · B2 · K · D)마다 목표 화까지 사람 없이 자동 집필하고, 판마다 심리 값을 한 표로 본다.
  B1 · B2: 지금 그대로 (같은 판을 두 번 돌려 흔들림을 잰다)
  K: 상태 변경안 요청의 emotional_state 줄을 '앞 화에서 온 감정과 판단' 을 적게 바꾼다
  D: 쓰기 모델을 다른 모델로 바꾼다
원본 작품은 읽기만 한다. 판 폴더는 <home>/arm-<판>/<작품> 이고, 자동 집필은 거기에만 쓴다.
출력에는 판 이름 · 화 번호 · 숫자만 찍는다. 작품 이름 · 제목 · 인물 이름 · 본문 · 요약 글 · 멈춘 이유 글을 찍지 않는다.
run 은 유료 모델을 부른다. 먼저 --dry-run 으로 어림 비용을 본다.

실행 (CANON_HOME 은 원본 작품이 있는 저장소이고 --home 은 판 폴더를 둘 곳이다):
  CANON_HOME=<저장소> python scripts/mind_run.py run --project 작품 --arm K --to 98 --home <runs> --dry-run
  CANON_HOME=<저장소> python scripts/mind_run.py run --project 작품 --arm K --to 98 --home <runs>
  python scripts/mind_run.py table --home <runs> --project 작품 --arms B1 B2 K D --m1 T.json --summaries S.json \\
      --out-md R.md --out-json R.json
"""
import argparse
import contextlib
import importlib.util
import json
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CANON_LLM", "mock")

from canon import autorun, prompts, settings, store  # noqa: E402

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
mc = _Lazy("mind_cause")

ARMS = ("B1", "B2", "K", "D")
B_ARMS = ("B1", "B2")
AUX = ("body_per_1k", "style_distance")
D_PROVIDER, D_MODEL = "coralbricks", "deepseek-v4.1-flash"
K_OLD = "character_updates 의 emotional_state 는 짧은 라벨로 적습니다."
K_NEW = ("character_updates 의 emotional_state 는 지금 감정과 함께, 그 감정이 어느 앞 화의 무슨 일에서 왔는지(화 번호)와 "
         "그 인물이 지금 무엇을 생각하고 판단하는지를 한두 문장으로 적습니다.")
FLASH_MODEL = "coralbricks:deepseek-v4.1-flash"
FROM_EP = 89  # table 기본 첫 화 (--from 으로 바꿈)
TO_EP = 98
EXIT_STOP = 3
RULES = (
    "- 값 1 은 thought_per_1k 의 판 평균이에요.",
    "- floor 는 T.json 에 있는 레퍼런스(ref) 글의 값 1 중 최솟값이에요. 코드에 적어 두지 않아요.",
    "- B 평균은 (B1 + B2) / 2 이고 흔들림은 |B1 - B2| 예요.",
    "- 후보 판(B 가 아닌 판)이 통과하려면 값 1 이 floor 이상이고 (값 1 - B 평균) 이 흔들림보다 커야 해요.",
    "- 후보의 body_per_1k 나 style_distance 가 B 평균보다 그 지표의 흔들림을 넘게 크면 '보조 지표 나빠짐' 이고 통과가 아니에요.",
    "- 보조 지표 값이 없으면 그 지표는 '없음' 으로 찍고 판정에서 빼요.",
    "- B1 · B2 가 없으면 판정은 '못 냄' 이에요.",
)


def policy() -> autorun.Policy:
    return autorun.Policy(confirm_plots=True, hand_pick_opening=False, check=False, max_issues=10**6,
                          stop_on_critical=False, max_shift=0, stop_on_board_warnings=False)


# ---------- 판 바꾸기 ----------

@contextlib.contextmanager
def arm_env(arm: str):
    """판에 맞게 프롬프트나 환경 변수를 바꾼다. 나올 때 원래 값으로 되돌린다.
    K: prompts.LAYER_STATE_RULE 의 K_OLD 를 K_NEW 로 바꾼다. D: 쓰기 백엔드와 모델 환경 변수를 정한다."""
    old_rule = prompts.LAYER_STATE_RULE
    keys = ("CANON_LLM_WRITE", "CANON_MODEL_WRITE")
    old_env = {k: os.environ.get(k) for k in keys}
    try:
        if arm == "K":
            if K_OLD not in old_rule:
                raise SystemExit("K 판이 바꿀 줄을 prompts.LAYER_STATE_RULE 에서 찾지 못했어요. 명세와 코드가 맞지 않아요")
            prompts.LAYER_STATE_RULE = old_rule.replace(K_OLD, K_NEW)
        elif arm == "D":
            os.environ["CANON_LLM_WRITE"], os.environ["CANON_MODEL_WRITE"] = D_PROVIDER, D_MODEL
        yield
    finally:
        prompts.LAYER_STATE_RULE = old_rule
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------- 판 폴더 ----------

def arm_root(home: Path, arm: str) -> Path:
    return Path(home) / f"arm-{arm}"


def prepare(src_root: Path, home: Path, arm: str, project: str) -> Path:
    """판 폴더 <home>/arm-<arm>/<project> 가 없으면 원본을 복사한다(autorun.json 은 뺀다). 있으면 그대로 둔다(이어 쓴다).
    판 루트를 돌려준다."""
    root = arm_root(home, arm)
    src, dest = Path(src_root).resolve(), root.resolve()
    if dest == src or src in dest.parents:
        raise SystemExit("판 폴더가 원본 저장소 안에 있어요. --home 을 원본 밖으로 정하세요")
    target = root / project
    if not target.exists():
        origin = src / project
        if not origin.is_dir():
            raise SystemExit("원본 작품 폴더를 찾지 못했어요. CANON_HOME 과 --project 를 확인하세요")
        root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(origin, target, ignore=shutil.ignore_patterns("autorun.json"))
    return root


def check_write_not_mock(allow_mock: bool) -> None:
    """arm_env 안에서 부른다. 쓰기 백엔드가 mock 이고 allow_mock 이 아니면 멈춘다."""
    if not allow_mock and settings.stage_provider("write")[0] == "mock":
        raise SystemExit("쓰기 백엔드가 mock 이에요. CANON_LLM 을 주세요 (mock 으로 돌리려면 --allow-mock)")


# ---------- run ----------

def _dry_run(a) -> int:
    p = store.load(a.project)
    est = autorun.estimate(p, a.to, False, policy(), a.project)
    cost = f"약 ${est['cost']:.2f}" if est["cost"] is not None else "가격 모름"
    print(f"판 {a.arm}")
    print(f"쓰기 백엔드 {settings.stage_provider('write')[0]} / 모델 {settings.stage_model('write')[0] or settings.model()[0]}")
    print(f"{est['from'] or '-'}~{a.to}화, 남은 화 {est['episodes']}화")
    print(f"토큰 입력 {est['tokens_in']:,} / 출력 {est['tokens_out']:,} (추정)")
    print(f"비용 {cost}")
    print(f"플롯 없는 화 {len(est['missing'])}화")
    return 0


def _report(arm: str, run) -> None:
    """이유 글 · 로그 메시지는 찍지 않는다. 전문은 판 폴더 autorun.json 에 남는다."""
    print(f"판 {arm}")
    print(f"상태 {run.status}")
    print(f"마지막 화 {run.ep}")
    print(f"멈춘 종류 {run.halt or '-'}")
    print(f"멈춘 이유 {len(run.reasons)}개")
    print(f"자동 반영 {len(run.applied)}화")
    print(f"비용 ${run.cost:.2f}")


def _drive(a) -> int:
    run = autorun.start(a.project, a.to, False, policy(), foreground=True, echo=None)
    seen: set = set()
    code = 0
    while run.status != "done":
        if run.status != "review" or run.ep in seen:
            code = EXIT_STOP
            break
        seen.add(run.ep)
        try:
            run = autorun.resume(a.project, approve=True, foreground=True, echo=None)
        except ValueError as e:
            print(f"이어 가기가 거절됐어요: {type(e).__name__}")
            code = EXIT_STOP
            break
    _report(a.arm, run)
    return code


def cmd_run(a) -> int:
    src_root = store.ROOT
    root = prepare(src_root, Path(a.home), a.arm, a.project)
    store.ROOT = root
    try:
        with arm_env(a.arm):
            if a.dry_run:
                return _dry_run(a)
            check_write_not_mock(a.allow_mock)
            return _drive(a)
    finally:
        store.ROOT = src_root


# ---------- table ----------

def arm_rows(p, eps: list[int], labels: dict) -> list[dict]:
    """화마다 mind_cause._ep_values 를 그대로 부른다. 본문이 없거나 화가 없으면 뺀다."""
    have = {e.plot.number: e for e in p.episodes}
    rows = []
    for n in eps:
        ep = have.get(n)
        if ep is not None and ep.text and ep.text.strip():
            rows.append(mc._ep_values(p, n, ep.text, labels.get(n), None))
    return rows


def arm_values(rows) -> Optional[dict]:
    return mc.arm_summary(rows)


def m1_floor(t: dict) -> float:
    vals = [(w.get("thought_per_1k") or {}).get("value") for w in t.get("works", {}).values() if w.get("kind") == "ref"]
    vals = [v for v in vals if v is not None]
    if not vals:
        raise SystemExit("T.json 에 레퍼런스 글의 thought_per_1k 값이 없어요")
    return min(vals)


def _aux_state(cand: Optional[float], vals: dict, field: str) -> str:
    b = [(vals.get(k) or {}).get(field) for k in B_ARMS]
    if cand is None or None in b:
        return "없음"
    mean, jit = sum(b) / 2, abs(b[0] - b[1])
    return "나빠짐" if cand - mean > jit else "안 나빠짐"


def _judge(v: dict, vals: dict, floor: float, bmean: float, jit: float) -> dict:
    v1 = v.get("thought_per_1k")
    aux = {f: _aux_state(v.get(f), vals, f) for f in AUX}
    if v1 is None:
        return {"value1": None, "delta": None, "above_floor": None, "beats_jitter": None, "aux": aux, "label": "값 없음"}
    above, beats = v1 >= floor, (v1 - bmean) > jit
    if not (above and beats):
        label = "못 통과"
    elif "나빠짐" in aux.values():
        label = "보조 지표 나빠짐"
    else:
        label = "통과"
    return {"value1": v1, "delta": round(v1 - bmean, 4), "above_floor": above, "beats_jitter": beats, "aux": aux, "label": label}


def verdict(vals: dict, floor: float) -> dict:
    """vals 는 판 이름 -> arm_values. 규칙은 RULES 와 같다."""
    out: dict = {"floor": floor, "b_mean": None, "jitter": None, "undetermined": False, "arms": {}, "passed": []}
    b = [(vals.get(k) or {}).get("thought_per_1k") for k in B_ARMS]
    if None in b:
        out["undetermined"] = True
        return out
    bmean, jit = sum(b) / 2, abs(b[0] - b[1])
    out["b_mean"], out["jitter"] = round(bmean, 4), round(jit, 4)
    for arm, v in vals.items():
        if arm in B_ARMS or not v:
            continue
        out["arms"][arm] = _judge(v, vals, floor, bmean, jit)
        if out["arms"][arm]["label"] == "통과":
            out["passed"].append(arm)
    return out


def _num(x) -> str:
    return "없음" if x is None else f"{x:.3f}"


def _md_verdict(v: dict) -> list[str]:
    lines = ["## 판정", ""]
    if v["undetermined"]:
        return lines + ["- 판정: 못 냄 (B1 · B2 값이 둘 다 필요해요)", ""]
    lines += [f"- B 평균 {_num(v['b_mean'])}, 흔들림 {_num(v['jitter'])}", "",
              "| 판 | 값 1 | B 평균과 차 | floor 이상 | 흔들림 넘음 | body_per_1k | style_distance | 판정 |",
              "|---|---|---|---|---|---|---|---|"]
    for arm, r in v["arms"].items():
        lines.append(f"| {arm} | {_num(r['value1'])} | {_num(r['delta'])} | {r['above_floor']} | {r['beats_jitter']} "
                     f"| {r['aux']['body_per_1k']} | {r['aux']['style_distance']} | {r['label']} |")
    if not v["passed"]:
        lines += ["", "- 통과한 판 없음"]
    return lines + [""]


def table_md(doc: dict) -> str:
    cols = ("thought_per_1k", "inner_line_share", "v2", "v3", "body_per_1k", "style_distance")
    head = ["# 후보 판 표", "", "## 판정 규칙 (값을 보기 전에 정했어요)", "", *RULES,
            f"- floor 는 {_num(doc['floor'])} 이에요 (T.json 에서 가져왔어요).", ""]
    eps = doc["eps"]
    rows = ["## 판별 값", "", f"- 화 {eps[0]}~{eps[-1]}" if eps else "- 화 없음", "",
            "| 판 | 화 | " + " | ".join(cols) + " | 라벨 실패 |", "|---|---|" + "---|" * len(cols) + "---|"]
    for arm, s in doc["arms"].items():
        rows.append(f"| {arm} | {s['eps']} | " + " | ".join(_num(s.get(c)) for c in cols) + f" | {s['label_errors']} |")
    return "\n".join(head + rows + [""] + _md_verdict(doc["verdict"]))


def _load_arm(a, arm: str):
    """판 폴더의 작품과 (화 번호 -> 본문). 판 폴더가 없으면 None."""
    root = arm_root(Path(a.home), arm)
    if not (root / a.project).is_dir():
        return None
    store.ROOT = root
    p = store.load(a.project)
    have = {e.plot.number: e.text for e in p.episodes if e.text and e.text.strip()}
    return p, {n: have[n] for n in range(a.from_ep, a.to_ep + 1) if n in have}


def _have_summaries(a, root: Path) -> dict:
    cache = root / "mind_run" / "summaries.json"
    if not cache.exists() and a.summaries:
        cache = Path(a.summaries)
    return {int(k): v for k, v in (mm._read(cache) or {}).items()}


def _label_todo(root: Path, texts: dict) -> list[int]:
    got = mm._read(root / "mind_run" / "labels.json") or {}
    return [n for n in texts if got.get(str(n)) is None]


def _table_dry(a, loaded: dict) -> int:
    calls = chars = 0
    for arm, got in loaded.items():
        if got is None:
            continue
        root = arm_root(Path(a.home), arm)
        have = _have_summaries(a, root)
        miss = [n for n in got[1] if n not in have]
        todo = _label_todo(root, got[1])
        calls += len(miss) + len(todo)
        chars += sum(len(got[1][n]) for n in miss) + sum(len(got[1][n]) for n in todo)
    print(f"호출 {calls}번 (요약 + 라벨, 캐시에 있는 것 뺌)")
    print(f"어림 글자 수 {chars:,}자 (본문 기준)")
    return 0


def _prepare_cache(a, root: Path) -> tuple[Path, Path]:
    d = root / "mind_run"
    d.mkdir(parents=True, exist_ok=True)
    summ = d / "summaries.json"
    if not summ.exists() and a.summaries:
        summ.write_text(Path(a.summaries).read_text(encoding="utf-8"), encoding="utf-8")
    return summ, d / "labels.json"


def _label_arm(a, llm, root: Path, texts: dict) -> tuple[dict, int]:
    """(화 번호 -> 라벨, 실패한 화 수). 성공한 라벨만 labels.json 에 저장한다."""
    summ, lab = _prepare_cache(a, root)
    summaries = mm.summarize(llm, sorted(texts.items()), summ, workers=a.workers, retries=a.retries, stats={})
    got = {int(k): v for k, v in (mm._read(lab) or {}).items() if v is not None}
    lock = threading.Lock()

    def one(n: int) -> None:
        res, _err = mm._try_label_err(llm, n, texts[n], summaries, a.retries)
        if res is not None:
            with lock:
                got[n] = res
                mm._dump(lab, {str(k): v for k, v in got.items()})

    mm._par(a.workers, one, [n for n in texts if n not in got])
    return {n: got.get(n) for n in texts}, sum(1 for n in texts if n not in got)


def _arm_doc(p, a, labels: dict, texts: dict, bad: int) -> tuple[Optional[dict], dict]:
    rows = arm_rows(p, list(texts), labels)
    vals = arm_values(rows)
    return vals, {**(vals or {}), "eps": len(rows), "label_errors": bad}


def _table_doc(a, loaded: dict, llm, floor: float) -> dict:
    arms: dict = {}
    vals: dict = {}
    for arm, got in loaded.items():
        if got is None:
            arms[arm] = {"eps": 0, "label_errors": 0}
            continue
        p, texts = got
        store.ROOT = arm_root(Path(a.home), arm)
        labels, bad = _label_arm(a, llm, store.ROOT, texts)
        v, arms[arm] = _arm_doc(p, a, labels, texts, bad)
        if v:
            vals[arm] = v
    return {"eps": list(range(a.from_ep, a.to_ep + 1)), "floor": floor, "arms": arms, "verdict": verdict(vals, floor)}


def cmd_table(a, label_llm=None) -> int:
    floor = m1_floor(json.loads(Path(a.m1).read_text(encoding="utf-8")))
    src_root = store.ROOT
    try:
        loaded = {arm: _load_arm(a, arm) for arm in a.arms}
        if a.dry_run:
            return _table_dry(a, loaded)
        llm = label_llm or mm._PerThread(lambda: mm.make_llm(a.label_model))
        doc = _table_doc(a, loaded, llm, floor)
    finally:
        store.ROOT = src_root
    md = table_md(doc)
    for path in (Path(a.out_md), Path(a.out_json)):
        path.parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_md).write_text(md, encoding="utf-8")
    Path(a.out_json).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(md)
    return 0


# ---------- 명령줄 ----------

def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--project", required=True)
    r.add_argument("--arm", required=True, choices=list(ARMS))
    r.add_argument("--to", type=int, required=True)
    r.add_argument("--home", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--allow-mock", action="store_true")
    t = sub.add_parser("table")
    t.add_argument("--home", required=True)
    t.add_argument("--project", required=True)
    t.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    t.add_argument("--m1", required=True)
    t.add_argument("--summaries")
    t.add_argument("--label-model", default=FLASH_MODEL)
    t.add_argument("--out-md", required=True)
    t.add_argument("--out-json", required=True)
    t.add_argument("--from", dest="from_ep", type=int, default=FROM_EP)
    t.add_argument("--to", dest="to_ep", type=int, default=TO_EP)
    t.add_argument("--workers", type=int, default=4)
    t.add_argument("--retries", type=int, default=2)
    t.add_argument("--dry-run", action="store_true")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    a = _parser().parse_args(argv)
    return cmd_run(a) if a.cmd == "run" else cmd_table(a)


if __name__ == "__main__":
    sys.exit(main())
