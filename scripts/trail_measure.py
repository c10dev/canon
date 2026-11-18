"""인물 자취 일감 1 측정 도구 (docs/trail/specs/01-measure.md). LLM 을 부르지 않는다. 비용은 0 이다.

레퍼런스 원고와 Canon 장편에서 되짚기 표지(그때 · 예전에 · 지난번 · 했었 …)를 찾아 무작위 대목을 뽑는다.
사람이 매긴 갈래(README 1-2 의 아홉 줄)로 글별 표 · 1만 자당 수 · 일치율(코헨 카파)을 내고 판정 문장을 만든다.
Canon 화는 스냅샷으로 쓰기 요청을 다시 짓는다(scripts/context_measure.py 의 rebuild).
이 스크립트는 store.save 를 부르지 않는다. 작품 폴더에 쓰지 않고 --out 경로에만 쓴다.

실행 (작품과 .refs 를 임시 CANON_HOME 에 복사해 둔다):
  CANON_HOME=<임시 폴더> CANON_LLM=mock python scripts/trail_measure.py sample --refs 레퍼런스ID \\
      --projects 작품1 --per 40 --seed 7 --ref-range 11 150 --canon-start 11 --out samples.json
  CANON_HOME=<임시 폴더> python scripts/trail_measure.py table --samples samples.json --labels L.json \\
      --out-md T.md --out-json T.json
  CANON_HOME=<임시 폴더> python scripts/trail_measure.py prompt --project 작품1 --ep 21 --out prompt.txt
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CANON_LLM", "mock")

from canon import context, prompts, refs, store  # noqa: E402

MARKER_RE = re.compile(r"그때(?!야|서야|부터)|예전에|지난번|저번에|기억났|기억이 났|떠올랐|생각났|생각이 났|그날|했었|였었")
BEFORE, AFTER = 200, 70   # 대목: 표지 앞 200자 · 뒤 70자
CATS = {  # 갈래 번호 → 이름 (README 1-2 의 아홉 줄 차례)
    1: "되짚기가 아님",
    2: "같은 화 안의 일",
    3: "설정의 과거(1화 전 배경)",
    4: "앞 화 일: 줄거리 정보를 전함",
    5: "앞 화 일: 남이 인물의 말 · 행동을 기억하고 지금 태도를 정함",
    6: "앞 화 일: 함께 겪은 일을 기준점 · 구실로 씀",
    7: "앞 화 일: 상대에 대해 쌓인 앎",
    8: "앞 화 일: 자기 선택 · 경험이 지금 선택을 바꿈",
    9: "앞 화 일: 자기 · 관계 인식이 바뀐 것을 깨달음",
}
CHAR_CATS = (5, 6, 7, 8, 9)   # 인물을 드러내는 앞 화 되짚기
M2_KINDS = ("근거", "요약", "없음", "모름")  # 측정 2 갈래


def _context_measure():
    path = Path(__file__).resolve().parent / "context_measure.py"
    spec = importlib.util.spec_from_file_location("context_measure", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- 글 읽기 ----------

def ref_episodes(rid: str, start: int, end: int) -> list[tuple[int, str]]:
    """레퍼런스 원고의 (화 번호, 본문). refs.episodes(b) 와 refs.assemble(...) 을 같은 차례로 짝짓는다.
    kind == "main" 이고 label 이 숫자만인 화 가운데 start <= 번호 <= end 만. 빈 본문은 뺀다."""
    b = refs.load(rid)
    metas = refs.episodes(b)
    cuts = sorted(b.cuts, key=lambda c: c.line)
    texts = refs.assemble(refs.source(rid), b.cuts, b.strip_tails, b.strip_repeats)
    if not len(metas) == len(texts) == len(cuts):
        raise ValueError(f"화 목록과 본문 수가 달라요: {len(metas)} / {len(texts)}")
    out = []
    for c, t in zip(cuts, texts):
        if c.kind != "main" or not re.fullmatch(r"\d+", c.label or ""):
            continue
        num = int(c.label)
        if start <= num <= end and t["text"]:
            out.append((num, t["text"]))
    return out


def canon_episodes(name: str, start_index: int) -> list[tuple[int, str]]:
    """Canon 작품의 (화 번호, 본문). 본문은 e.final_text or e.text. 본문이 있는 화를 번호 차례로 놓고
    start_index 번째(1부터)부터. 예: start_index=11 이면 본문이 있는 11번째 화부터."""
    p = store.load(name)
    rows = sorted(((e.plot.number, e.final_text or e.text) for e in p.episodes), key=lambda r: r[0])
    rows = [r for r in rows if r[1]]
    return rows[max(0, start_index - 1):]


def find_markers(text: str) -> list[tuple[int, str]]:
    """(위치, 표지 글) 목록. MARKER_RE.finditer."""
    return [(m.start(), m.group(0)) for m in MARKER_RE.finditer(text)]


# ---------- 표본 ----------

def _item(key: str, k: int, ep: int, at: int, marker: str, text: str, width: int = 2) -> dict:
    return {"id": f"{key}-{k:0{width}d}", "ep": ep, "at": at, "marker": marker,
            "before": text[max(0, at - BEFORE):at], "after": text[at:at + len(marker) + AFTER]}


def _all_markers(eps: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    return sorted((n, at, mk) for n, t in eps for at, mk in find_markers(t))


def _stats(key: str, kind: str, eps: list[tuple[int, str]], total: int) -> dict:
    chars = sum(len(t) for _, t in eps)
    return {"key": key, "kind": kind, "eps": len(eps), "chars": chars, "markers": total,
            "per10k": round(total / chars * 10000, 2) if chars else 0.0,
            "first": eps[0][0] if eps else 0, "last": eps[-1][0] if eps else 0}


def sample_work(key: str, kind: str, eps: list[tuple[int, str]], per: int, seed: int) -> dict:
    """한 글의 표본: 화 수 · 글자 · 표지 수 · 1만 자당 표지와 무작위로 고른 대목(id 는 key-NN)."""
    texts = dict(eps)
    marks = _all_markers(eps)
    picked = random.Random(f"{seed}:{key}").sample(marks, min(per, len(marks)))
    items = [_item(key, k, n, at, mk, texts[n]) for k, (n, at, mk) in enumerate(sorted(picked), 1)]
    return {**_stats(key, kind, eps, len(marks)), "items": items}


# ---------- 갈래 표 · 일치율 ----------

def norm_label(v) -> dict:
    """정수(갈래) · None(모름) · dict 를 {cat, dist, who, shift, note} 로."""
    base = {"cat": None, "dist": None, "who": "", "shift": "", "note": ""}
    if isinstance(v, dict):
        return {**base, **{k: v[k] for k in base if k in v}}
    return {**base, "cat": v}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """비율 k/n 의 윌슨 구간 (lo, hi). n == 0 이면 (0.0, 0.0)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _share(char: int, known: int, per10k: float) -> dict:
    ci = wilson(char, known)
    return {"share": char / known if known else 0.0, "share_ci": ci,
            "char_per10k": round(per10k * (char / known if known else 0.0), 2),
            "char_per10k_ci": (round(per10k * ci[0], 2), round(per10k * ci[1], 2))}


def tally(work: dict, labels: dict) -> dict:
    """한 글의 표. work 는 sample_work 의 반환, labels 는 {id: 라벨}."""
    cats = {c: 0 for c in CATS}
    who = {"doer": 0, "witness": 0}
    shift = {"same": 0, "shifted": 0}
    dist, n, unknown = [], 0, 0
    for it in work["items"]:
        if it["id"] not in labels:
            continue
        n += 1
        lb = norm_label(labels[it["id"]])
        if lb["cat"] is None:
            unknown += 1
            continue
        cats[lb["cat"]] += 1
        if lb["cat"] not in CHAR_CATS:
            continue
        if lb["who"] in who:
            who[lb["who"]] += 1
        if lb["shift"] in shift:
            shift[lb["shift"]] += 1
        if lb["dist"] is not None:
            dist.append(lb["dist"])
    char = sum(cats[c] for c in CHAR_CATS)
    known = n - unknown
    return {"key": work["key"], "kind": work["kind"], "n": n, "known": known, "cats": cats, "unknown": unknown,
            "char": char, "who": who, "shift": shift, "dist": dist,
            "eps": work["eps"], "chars": work["chars"], "markers": work["markers"], "per10k": work["per10k"],
            **_share(char, known, work["per10k"])}


def group(rows: list[dict], kind: str) -> dict:
    """kind 가 같은 글들의 합: 표지 · 글자 합으로 per10k 를 다시 내고 known · char 합으로 share 와 구간을 낸다."""
    rs = [r for r in rows if r["kind"] == kind]
    chars = sum(r["chars"] for r in rs)
    markers = sum(r["markers"] for r in rs)
    per10k = round(markers / chars * 10000, 2) if chars else 0.0
    known = sum(r["known"] for r in rs)
    char = sum(r["char"] for r in rs)
    return {"key": kind, "kind": kind, "n": sum(r["n"] for r in rs), "known": known,
            "cats": {c: sum(r["cats"][c] for r in rs) for c in CATS}, "unknown": sum(r["unknown"] for r in rs),
            "char": char, "who": {k: sum(r["who"][k] for r in rs) for k in ("doer", "witness")},
            "shift": {k: sum(r["shift"][k] for r in rs) for k in ("same", "shifted")},
            "dist": [d for r in rs for d in r["dist"]],
            "eps": sum(r["eps"] for r in rs), "chars": chars, "markers": markers, "per10k": per10k,
            **_share(char, known, per10k)}


def _cohen(pairs: list[tuple[int, int]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in CATS)
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


def kappa(a: dict, b: dict) -> dict:
    """두 라벨 파일의 일치. 두 쪽 모두 cat 이 있는 id 만 센다."""
    pairs, diff = [], {}
    for i in sorted(set(a) & set(b)):
        x, y = norm_label(a[i])["cat"], norm_label(b[i])["cat"]
        if x is None or y is None:
            continue
        pairs.append((x, y))
        if x != y:
            diff[f"{x}→{y}"] = diff.get(f"{x}→{y}", 0) + 1
    n = len(pairs)
    agree = sum(x == y for x, y in pairs)
    char_agree = sum((x in CHAR_CATS) == (y in CHAR_CATS) for x, y in pairs)
    k = _cohen(pairs)
    return {"n": n, "agree": agree, "raw": agree / n if n else 0.0, "kappa": None if k is None else round(k, 3),
            "char_raw": char_agree / n if n else 0.0, "pairs": diff}


def _ci(ci) -> str:
    return f"{ci[0]:.2f}~{ci[1]:.2f}"


def table_md(rows: list[dict], groups: list[dict]) -> str:
    """마크다운 표 둘: 글별 표와 묶음(ref · canon) 표. 숫자만, 원문 인용 없음."""
    head = ["글", "종류", "화", "글자", "표지", "1만 자당 표지", *[f"갈래{c}" for c in CATS], "모름",
            "5~9 비율", "5~9 1만 자당(구간)"]
    out = []
    for title, rs in (("글별", rows), ("묶음", groups)):
        out += [f"### {title}", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for r in rs:
            cells = [r["key"], r["kind"], r["eps"], r["chars"], r["markers"], r["per10k"], *[r["cats"][c] for c in CATS],
                     r["unknown"], f"{r['share']:.2f} ({_ci(r['share_ci'])})",
                     f"{r['char_per10k']} ({_ci(r['char_per10k_ci'])})"]
            out.append("| " + " | ".join(str(c) for c in cells) + " |")
        out.append("")
    return "\n".join(out)


# ---------- 측정 2 · 3 셈과 판정 ----------

def m2_tally(judged: dict) -> dict:
    """측정 2 셈: 값은 M2_KINDS 중 하나이거나 {"kind": …}."""
    counts = {k: 0 for k in M2_KINDS}
    for v in judged.values():
        k = v.get("kind") if isinstance(v, dict) else v
        if k in counts:
            counts[k] += 1
    known = sum(counts[k] for k in M2_KINDS if k != "모름")
    return {"counts": counts, "known": known,
            "short": (counts["없음"] + counts["요약"]) / known if known else 0.0,
            "has": counts["근거"] / known if known else 0.0}


def verdict(m2: dict, m3: dict[str, int]) -> list[str]:
    """01-measure.md 의 '판정' 네 줄을 적용한 문장 목록."""
    out = []
    if m2["known"] < 10:
        out.append(f"측정 2 로 가르지 않는다(모름 뺀 건수 {m2['known']}). 차례를 그대로 둔다.")
    elif m2["short"] > 0.5:
        out.append(f"재료가 모자란 것이다. 없음 · 요약만 있음이 {m2['short']:.0%} 이다. "
                   "자취 일감(5 → 6 → 8 을 3 과 함께 당긴다).")
    elif m2["has"] > 0.5:
        out.append(f"모델이 쓰지 않는 것이다. 근거가 있음이 {m2['has']:.0%} 이다. 이어받기 결정(2 → 3 먼저).")
    else:
        out.append("측정 2 는 어느 쪽도 반을 넘지 않는다.")
    if m3 and all(v >= 2 for v in m3.values()):
        out.append("측정 3: 어긋난 묶음이 장편마다 2개 이상이다. 검수 일감(4)을 앞으로 당긴다.")
    else:
        out.append("측정 3 은 검수를 당길 기준(장편마다 2개 이상)에 못 미친다.")
    return out


def _fact_lines(p, c) -> list[dict]:
    names = {c.name, c.name.split()[0]} if c.name.split() else {c.name}
    first = {}
    for d in p.history:
        for f in d.new_facts:
            first.setdefault(f, d.episode)
    lines = [{"ep": first.get(f, 0), "text": f} for f in p.facts if any(nm and nm in f for nm in names)]
    lines += [{"ep": r.episode, "text": f"[설정 {r.field}] {r.before} → {r.after}"}
              for r in p.setting_log if r.character_id == c.id]
    return lines


def _unions(lines: list[dict], min_share: float) -> list[list[dict]]:
    gs = [context.grams(x["text"]) for x in lines]
    root = list(range(len(lines)))

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            if gs[i] and gs[j] and len(gs[i] & gs[j]) / min(len(gs[i]), len(gs[j])) >= min_share:
                root[find(i)] = find(j)
    buckets: dict[int, list[dict]] = {}
    for i, x in enumerate(lines):
        buckets.setdefault(find(i), []).append(x)
    return [sorted(b, key=lambda x: x["ep"]) for b in buckets.values() if len(b) >= 2]


def fact_groups(p, min_share: float = 0.3) -> list[dict]:
    """측정 3 의 후보: 인물마다 같은 과거를 말하는 확정 사실 · 설정 바꾸기 줄의 묶음(두 줄 이상)."""
    out = []
    for c in p.characters:
        for lines in _unions(_fact_lines(p, c), min_share):
            out.append({"character": c.name, "id": c.id, "lines": lines, "span": lines[-1]["ep"] - lines[0]["ep"]})
    return out


# ---------- 요청 다시 짓기 ----------

def rebuild_prompt(p, n: int) -> str | None:
    """n화 쓰기 요청. 직전 화 스냅샷이 없으면 None(모름)."""
    cm = _context_measure()
    if not cm.exact_ok(p, n):
        return None
    return prompts.episode_prompt(cm.rebuild(p, n, "exact"), n)


def snapshot_eps(p) -> list[int]:
    """스냅샷이 있고 본문이 있는 화 번호 목록(차례)."""
    cm = _context_measure()
    return sorted(e.plot.number for e in p.episodes if (e.final_text or e.text) and cm.exact_ok(p, e.plot.number))


# ---------- 작가용 라벨 화면 ----------

_CSS = """:root{--bg:#fbfaf7;--fg:#222;--mute:#666;--card:#fff;--line:#d9d6cf;--hit:#ffe58a;--acc:#2f6f4f}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1e;--fg:#e8e6e1;--mute:#a09d96;--card:#26262a;--line:#3a3a40;--hit:#6b5a12;--acc:#7fcf9f}}
body{background:var(--bg);color:var(--fg);font:16px/1.65 system-ui,sans-serif;margin:0;padding:16px}
main{max-width:640px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:14px 0}
.id{color:var(--mute);font-size:13px}
.txt{white-space:pre-wrap;margin:6px 0 10px}
mark{background:var(--hit);color:inherit;padding:0 2px;border-radius:3px}
label{display:block;padding:3px 0;cursor:pointer}
button{background:var(--acc);color:var(--bg);border:0;border-radius:6px;padding:10px 18px;font-size:16px;cursor:pointer}
"""

_JS = """const KEY='trail-measure-labels';let saved={};
try{saved=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
document.querySelectorAll('input[type=radio]').forEach(r=>{
  if(saved[r.name]!==undefined&&String(saved[r.name])===r.value)r.checked=true;
  r.addEventListener('change',()=>{saved[r.name]=r.value;try{localStorage.setItem(KEY,JSON.stringify(saved))}catch(e){}});
});
document.getElementById('save').addEventListener('click',()=>{
  const out={};
  document.querySelectorAll('.card').forEach(c=>{
    const id=c.dataset.id,r=c.querySelector('input[type=radio]:checked');
    if(r)out[id]=r.value==='null'?null:Number(r.value);
  });
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));
  a.download='labels-author.json';a.click();
});
"""


def _card(it: dict) -> str:
    e = html.escape
    mk, after = it["marker"], it["after"]
    rest = after[len(mk):] if after.startswith(mk) else after
    opts = [(str(c), f"{c}. {nm}") for c, nm in CATS.items()] + [("null", "모름")]
    radios = "".join(f'<label><input type="radio" name="{e(it["id"])}" value="{v}"> {e(t)}</label>' for v, t in opts)
    return (f'<section class="card" data-id="{e(it["id"])}"><div class="id">{e(it["id"])} · {it["ep"]}화</div>'
            f'<div class="txt">{e(it["before"])}<mark>{e(mk)}</mark>{e(rest)}</div>{radios}</section>')


def label_html(items: list[dict]) -> str:
    """자기 완결 HTML 한 장: 대목마다 갈래 라디오 버튼, '저장' 으로 labels-author.json 을 내려받는다."""
    cards = "\n".join(_card(it) for it in items)
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>되짚기 갈래 매기기</title>'
            f'<style>{_CSS}</style></head><body><main><h1>되짚기 갈래 매기기</h1>'
            '<p>대목마다 갈래를 하나 골라 주세요. 다 고르면 아래 저장 버튼을 눌러 파일을 받아 주세요. '
            '고른 값은 이 브라우저에 남아서 다시 열어도 이어져요.</p>'
            f'{cards}<button id="save" type="button">저장</button></main><script>{_JS}</script></body></html>')


# ---------- 하위 명령 ----------

def _dump(path: str, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _starts(a) -> dict[str, int]:
    out = {}
    for s in a.canon_start_for or []:
        name, _, k = s.rpartition("=")
        out[name] = int(k)
    return out


def cmd_sample(a) -> None:
    works = [sample_work(rid, "ref", ref_episodes(rid, *a.ref_range), a.per, a.seed) for rid in a.refs or []]
    starts = _starts(a)
    works += [sample_work(nm, "canon", canon_episodes(nm, starts.get(nm, a.canon_start)), a.per, a.seed)
              for nm in a.projects or []]
    _dump(a.out, {"seed": a.seed, "per": a.per, "marker_re": MARKER_RE.pattern, "works": works})


def cmd_scan(a) -> None:
    p = store.load(a.project)
    key = f"{a.project}@snap"
    eps = [(n, p.episode(n).final_text or p.episode(n).text) for n in snapshot_eps(p)]
    marks = _all_markers(eps)
    texts = dict(eps)
    items = [_item(key, k, n, at, mk, texts[n], 3) for k, (n, at, mk) in enumerate(marks, 1)]
    _dump(a.out, {**_stats(key, "canon", eps, len(marks)), "items": items})


def _merge_labels(paths: list[str]) -> dict:
    merged: dict = {}
    for f in paths:
        merged.update(json.loads(Path(f).read_text(encoding="utf-8")))
    return merged


def cmd_table(a) -> None:
    samples = json.loads(Path(a.samples).read_text(encoding="utf-8"))
    labels = _merge_labels(a.labels)
    rows = [tally(w, labels) for w in samples["works"]]
    groups = [group(rows, k) for k in ("ref", "canon")]
    Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_md).write_text(table_md(rows, groups), encoding="utf-8")
    _dump(a.out_json, {"rows": rows, "groups": groups})


def cmd_agree(a) -> None:
    x, y = (json.loads(Path(f).read_text(encoding="utf-8")) for f in (a.a, a.b))
    print(json.dumps(kappa(x, y), ensure_ascii=False, indent=1))


def cmd_prompt(a) -> None:
    text = rebuild_prompt(store.load(a.project), a.ep)
    if text is None:
        print("스냅샷이 없어요", file=sys.stderr)
        raise SystemExit(2)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text, encoding="utf-8")


def cmd_facts(a) -> None:
    _dump(a.out, fact_groups(store.load(a.project)))


def cmd_label(a) -> None:
    samples = json.loads(Path(a.samples).read_text(encoding="utf-8"))
    items = []
    for w in samples["works"]:
        if w["key"] in a.works:
            k = min(a.n, len(w["items"]))
            items += random.Random(f"{a.seed}:label:{w['key']}").sample(w["items"], k)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(label_html(items), encoding="utf-8")
    _dump(str(out.with_suffix(".ids.json")), [it["id"] for it in items])


def cmd_verdict(a) -> None:
    m2 = m2_tally(json.loads(Path(a.m2).read_text(encoding="utf-8")))
    m3 = json.loads(Path(a.m3).read_text(encoding="utf-8"))
    print(json.dumps({"m2": m2, "verdict": verdict(m2, m3)}, ensure_ascii=False, indent=1))


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, *opts):
        sp = sub.add_parser(name)
        for flag, kw in opts:
            sp.add_argument(flag, **kw)
    add("sample", ("--refs", {"nargs": "*"}), ("--projects", {"nargs": "*"}), ("--per", {"type": int, "default": 40}),
        ("--seed", {"type": int, "default": 7}), ("--ref-range", {"nargs": 2, "type": int, "default": [11, 150]}),
        ("--canon-start", {"type": int, "default": 11}), ("--canon-start-for", {"action": "append"}),
        ("--out", {"required": True}))
    add("scan", ("--project", {"required": True}), ("--out", {"required": True}))
    add("table", ("--samples", {"required": True}), ("--labels", {"action": "append", "required": True}),
        ("--out-md", {"required": True}), ("--out-json", {"required": True}))
    add("agree", ("--a", {"required": True}), ("--b", {"required": True}))
    add("prompt", ("--project", {"required": True}), ("--ep", {"type": int, "required": True}), ("--out", {"required": True}))
    add("facts", ("--project", {"required": True}), ("--out", {"required": True}))
    add("label", ("--samples", {"required": True}), ("--works", {"nargs": "+", "required": True}),
        ("--n", {"type": int, "default": 10}), ("--seed", {"type": int, "default": 7}), ("--out", {"required": True}))
    add("verdict", ("--m2", {"required": True}), ("--m3", {"required": True}))
    return ap


def main(argv: list[str] | None = None) -> None:
    a = _parser().parse_args(argv)
    cmds = {"sample": cmd_sample, "scan": cmd_scan, "table": cmd_table, "agree": cmd_agree, "prompt": cmd_prompt,
            "facts": cmd_facts, "label": cmd_label, "verdict": cmd_verdict}
    cmds[a.cmd](a)


if __name__ == "__main__":
    main()
