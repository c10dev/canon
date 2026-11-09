"""컨텍스트 놓침 실측 (docs/context/specs/01-measure.md). LLM 을 부르지 않는다. 비용은 0 이다.

확정 화마다 그 화를 쓸 때 조립됐을 쓰기 프롬프트(prompts.episode_prompt)를 다시 만들고,
최종 본문에 이름이 나온 인물 · 이야기 요소 · 복선(대리 정답)과 견준다.
  놓침: 본문에 나왔는데 선택되지 않은 항목. 엄격한 놓침은 프롬프트 어디에도 이름이 없는 항목
  낭비: 선택됐는데 본문에 나오지 않은 항목
같은 자료로 이름을 찾는 범위(플롯 · 스토리보드 · 직전 화 끝)와 새 활성 조건(N화 유지, 한 단계 되부름)을 흉내 낸다.
재구성: 직전 화 스냅샷이 있으면 stattrial.before 꼴로 되돌린 사본(exact), 모든 화는 뒤에 생긴 것을 걸러낸 사본(approx)으로도 센다.
선택은 prompts.build_episode_context 의 과정을 옮겨 쓰고, 화마다 만든 프롬프트의 블록과 맞춰 본다(어긋나면 align 에 적는다).
열린 복선 블록 줄이기 흉내(docs/context/specs/10-foreshadow-trim.md 의 확인 (가)): 장편 화마다 prompts.serial_foreshadow_block 으로
한 줄 꼴과 예전 JSON 꼴 블록을 찍어 줄어든 글자를 센다. 한 줄 꼴은 고른 복선을 빼거나 자르지 않는다.

실행 (작품 폴더를 임시 CANON_HOME 에 복사해 둔다. 이 스크립트는 store.save 를 부르지 않는다):
  CANON_HOME=<임시 폴더> CANON_LLM=mock python scripts/context_measure.py --projects 작품1 작품2 \\
      --out reports/결과.json --sheets "reports/판정 시트"
  복선 흉내만 (범위 · 조건 흉내를 건너뛰고 표를 찍는다):
  CANON_HOME=<임시 폴더> CANON_LLM=mock python scripts/context_measure.py --projects 작품1 작품2 --fs-only --fs-table \\
      --out reports/복선.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CANON_LLM", "mock")

from canon import context, elements, labstats, prompts, stattrial, store  # noqa: E402
from canon.prompts import cast_view, dump  # noqa: E402
from canon.schema import Character, Project, StoryElement  # noqa: E402

TAILS = (0, 500, 1500, 3000)  # 범위 C 의 직전 화 끝 글자 수 (정할 것 6)
STICKY = (1, 2, 3, 5)  # N화 유지 후보 (정할 것 7)
WINDOW = 30  # 판정 시트의 매칭 위치 앞뒤 글자
SEED = 7
KINDS = ("char", "element", "foreshadow")
# 예산을 넘길 때 남기는 차례 (README Q17): 늘 넣기 > 키 직접 매칭 > 되부름 > N화 유지
RANK = {"direct": 1, "recursion": 2, "sticky": 3}
# 열린 복선 블록 줄이기 흉내 (spec 10 의 확인 (가))
FS_CHARS = 0.40  # 문턱: 블록 글자가 예전 JSON 꼴보다 이만큼 이상 준다
# 작품 기준의 독립 작품 셋. nsfw_saintess-claude 는 nsfw_saintess 의 사본이라 넣지 않는다 (정할 것 8)
FS_WORKS = ("nsfw_saintess", "subway-1-수정본", "불타는-세상에서-내-캠핑카만-진화한다")


# ---------- 재구성 ----------

def body_of(p: Project, n: int) -> str:
    """n화 최종 본문: 상태 반영의 바탕이 된 final_text, 없으면 text. 원본 p 에서 읽는다 (정할 것 2)."""
    e = p.episode(n)
    return e.final_text or e.text


def exact_ok(p: Project, n: int) -> bool:
    """직전 화 반영 직후 스냅샷이 있어야 정확한 재구성이다. stattrial.before(p, 1) 은 0화 스냅샷이 없어도 오류 없이 최신 사본을 준다."""
    return p.snapshot(n - 1) is not None


def approx(p: Project, n: int) -> Project:
    """스냅샷 없이 n화 쓰기 직전을 어림한 사본: 지금 상태에서 n화 뒤 반영이 더한 것을 걸러낸다. 인물 상태 · 아는 정보 · 관계 수치는 되돌리지 못한다."""
    q = p.model_copy(deep=True)
    later = [d for d in q.history if d.episode >= n]
    setup = {c.id for c in q.characters if not c.first_ep}
    new = {c.id for d in later for c in d.new_characters} - setup
    q.characters = [c for c in q.characters if c.id not in new]
    q.states = [s for s in q.states if s.character_id not in new]
    facts = {f for d in later for f in [*d.new_facts, *(d.added.facts if d.added else [])]}
    q.facts = [f for f in q.facts if f not in facts]
    secrets = {s.id for d in later for s in d.secrets_added}
    q.secrets = [s for s in q.secrets if s.id not in secrets]
    fs = []
    for f in q.foreshadows:
        if f.planted_ep >= n:
            continue
        if f.payoff_ep is not None and f.payoff_ep >= n:
            f = f.model_copy(update={"status": "open", "payoff_ep": None})
        fs.append(f)
    q.foreshadows = fs
    q.foreshadow_clues = [c for c in q.foreshadow_clues if c.episode < n]
    q.events = [e for e in q.events if e.episode < n]
    q.history = [d for d in q.history if d.episode < n]
    q.snapshots = []
    for e in q.episodes:
        if e.plot.number >= n and e.status == "finalized":
            e.status, e.summary = "written", ""
    return q


def settle(q: Project, n: int, p: Project) -> None:
    """두 재구성에 덧씌운다: n화 쓴 뒤 더한 이야기 요소를 빼고(revert 는 작가가 더한 것을 두므로), n화부터 본문을 비운다.
    n화 뒤 반영이 본문에서 등록한 장소는 원본 p 의 found_in · found_ep 로 뺀다. revert(elements.unregister_places)는 안 쓴 화 플롯에
    나오는 장소를 남기고 '플롯에서 나옴'으로 바꿔 적기 때문이다.
    명세서의 'since_ep > n-1 이면 뺀다'는 쓰지 않는다. since_ep 는 이야기 속 시점이라 since_ep == n 인 요소도 실제 프롬프트에 들어간다."""
    orig = {el.id: el for el in p.elements}

    def later(el: StoryElement) -> bool:
        o = orig.get(el.id, el)
        return el.added_after >= n or (o.found_in == "본문" and o.found_ep >= n)
    q.elements = [el for el in q.elements if not later(el)]
    for e in q.episodes:
        if e.plot.number >= n:
            e.text = e.final_text = ""


def rebuild(p: Project, n: int, mode: str) -> Project:
    q = stattrial.before(p, n) if mode == "exact" else approx(p, n)
    settle(q, n, p)
    return q


def digest(p: Project) -> str:
    return hashlib.sha256(p.model_dump_json().encode()).hexdigest()


# ---------- 이름 찾기 ----------

def char_hits(c: Character, text: str) -> list[int]:
    pat = context.name_pattern(c)
    return [m.start() for m in pat.finditer(text)] if pat and text else []


def el_hits(el: StoryElement, text: str, bound: bool = False) -> list[int]:
    """요소 이름 · 다른 이름(elements.terms) 위치. bound 면 인물처럼 앞이 한글 · 영문이 아니어야 한다."""
    out = []
    for t in elements.terms(el):
        pat = re.compile((r"(?<![가-힣A-Za-z])" if bound else "") + re.escape(t))
        out += [m.start() for m in pat.finditer(text)]
    return sorted(out)


def snippet(text: str, at: int, width: int = WINDOW) -> str:
    return " ".join(text[max(0, at - width):at + width + 8].split())


# ---------- 선택 옮겨 쓰기 (prompts.build_episode_context · serial_parts) ----------

def size_of(c: Character) -> int:
    return len(dump(cast_view([c])))


def cast_base(q: Project, n: int) -> dict:
    """찾는 범위와 상관없는 인물 선택: 고정 설정 인물, 플롯 인물, fit_cast 뒤 조연 · 단역, 이름으로 더할 예산의 출발점."""
    ep = q.episode(n)
    static = prompts.static_characters(q)
    static_ids = {c.id for c in static}
    cast_ids = set(ep.plot.characters) or static_ids or {c.id for c in q.characters}
    plot_ids = set(cast_ids)  # build_episode_context 의 plot_ids (빈 플롯이면 대신 넣은 인물)
    cast_ids = set(context.without_off(q, cast_ids))
    extra, extra_cut = prompts.side_characters(q, cast_ids), 0
    always = [c for c in static if c.tier != "main"]
    used = len(dump(cast_view(always))) if always else 0
    extra, extra_cut = context.fit_cast(extra, used, size_of, context.BUDGET["cast"])
    used += len(dump(cast_view(extra))) if extra else 0
    return {"static": static_ids, "plot": plot_ids, "cast": cast_ids, "extra": {c.id for c in extra},
            "extra_cut": extra_cut, "used": used}


def light(q: Project, n: int, base: dict) -> dict:
    """범위 · 조건 흉내에 쓰는 가벼운 사본 (되돌린 작품 사본 전체를 들고 있지 않으려고)."""
    off, core = context.off_ids(q), context.core_ids(q)
    return {"n": n, "plot_cast": set(q.episode(n).plot.characters), "base": base,
            "chars": [c for c in q.characters if c.id not in off],
            "side": {c.id for c in q.characters if c.id not in core and c.id not in off},
            "els": [el for el in q.elements if el.context != "off" and elements.exists_at(el, n)]}


def fit_ranked(L: dict, cands: dict[str, str], skip: set[str], used: int) -> tuple[set[str], int]:
    """이름 · 되부름 · 유지로 켠 인물을 남은 cast 예산에 넣는다. 활성 이유 차례, 같으면 조연 먼저, 같으면 인물 차례.
    이유가 모두 direct 면 context.fit_named(side_characters(...)) 와 같은 결과다."""
    order = [(i, c) for i, c in enumerate(L["chars"]) if c.id in L["side"] and c.id in cands and c.id not in skip]
    order.sort(key=lambda x: (RANK[cands[x[1].id]], x[1].tier == "minor", x[0]))
    keep, total = set(), used
    for _, c in order:
        cost = size_of(c)
        if total + cost > context.BUDGET["cast"]:
            continue
        keep.add(c.id)
        total += cost
    return keep, len(order) - len(keep)


def el_reason(el: StoryElement, plot_cast: set[str], n: int, scan: str) -> str:
    """elements.relevant 를 이유와 함께. scan 은 이름을 찾는 글 (지금은 플롯 글)."""
    if el.context == "off" or not elements.exists_at(el, n):
        return ""
    if el.context == "always":
        return "always"
    if n in el.episodes:
        return "episodes"
    if set(el.characters) & plot_cast:
        return "characters"
    return "direct" if any(t in scan for t in elements.terms(el)) else ""


def state_kept(q: Project, n: int, cast_ids: set[str]) -> set[str]:
    """인물 현재 상태 블록에 남는 인물 (state_view → write_states → fit_states)."""
    ep = q.episode(n)
    states = [s for s in q.states if s.character_id in cast_ids]
    states, _ = prompts.state_view(q, states, n, elements.plot_text(ep))
    kept, _ = prompts.fit_states(q, prompts.write_states(q, states), set(ep.plot.characters), context.BUDGET["states"])
    return {s.character_id for s in kept}


# ---------- 프롬프트와 맞춰 보기 ----------

def sections(prompt: str) -> dict[str, str]:
    """'# 제목' 줄로 나눈 블록. 같은 제목이 또 나오면 뒤 것을 붙인다."""
    out: dict[str, str] = {}
    head = ""
    for line in prompt.split("\n"):
        if line.startswith("# "):
            head = line[2:]
            out.setdefault(head, "")
        elif head:
            out[head] += line + "\n"
    return out


def block(secs: dict[str, str], start: str) -> str:
    return "".join(v for k, v in secs.items() if k.startswith(start))


def ids_in(text: str, key: str = "id") -> set[str]:
    return set(re.findall(rf'^\s*"{key}": "([^"]*)"', text, re.M))


def align(q: Project, prompt: str, sel: dict) -> list[str]:
    """옮겨 쓴 선택이 만든 프롬프트의 블록과 같은지. 다른 블록 이름을 돌려준다."""
    secs = sections(prompt)
    bad = []
    if ids_in(block(secs, "인물 설정")) != sel["static"]:
        bad.append("static")
    if ids_in(block(secs, "이번 화에 나오는 조연 · 단역 설정")) != sel["extra"]:
        bad.append("extra")
    if ids_in(block(secs, "플롯 글이나 직전 화 끝에 이름이 나온 인물 설정")) != sel["named"]:
        bad.append("named")
    if ids_in(block(secs, "인물 현재 상태"), "character_id") != sel["states"]:
        bad.append("states")
    fs_text = block(secs, "열린 복선")  # 단편은 JSON, 장편은 한 줄 꼴 (prompts.foreshadow_line)
    if ids_in(fs_text) | set(re.findall(r"^- (\S+) \(\d+화에 심음", fs_text, re.M)) != sel["fs"]:
        bad.append("foreshadow")
    names = {el.id: el.name for el in q.elements}
    got = set(re.findall(r"^- \[[^\]]+\] (.+?)(?: \(다른 이름: .*?\))?: ", block(secs, "이야기 요소"), re.M))
    if got != {names[i] for i in sel["elements"]}:
        bad.append("elements")
    return bad


# ---------- 화 하나 ----------

def measure(p: Project, n: int, mode: str, check: bool = True) -> dict:
    """화 하나의 재구성, 대리 정답, 선택, 범위 흉내에 쓸 글 조각."""
    q = rebuild(p, n, mode)
    ep = q.episode(n)
    before = digest(q) if check else ""
    prompt = prompts.episode_prompt(q, n)
    mutated = check and digest(q) != before
    plot = elements.plot_text(ep)
    board = prompts.board_block(q, n)
    last = next((e.text for e in q.episodes if e.plot.number == n - 1 and e.text), "")
    text = body_of(p, n)
    alt = p.episode(n).text if p.episode(n).final_text and p.episode(n).final_text != p.episode(n).text else ""

    base = cast_base(q, n)
    off = context.off_ids(q)
    chars = [c for c in q.characters if c.id not in off]
    scan_now = plot + "\n" + last[-context.NAMED_TAIL:]
    seen = context.named_ids(q, scan_now) - base["plot"]
    named, named_cut = context.fit_named(prompts.side_characters(q, seen), base["used"], size_of, context.BUDGET["cast"])
    named_ids = {c.id for c in named}
    cast_ids = base["cast"] | named_ids
    plot_cast = set(ep.plot.characters)
    els = [el for el in q.elements if el.context != "off" and elements.exists_at(el, n)]
    reasons = {el.id: el_reason(el, plot_cast, n, plot) for el in els}
    fs_sel, fs_cut = prompts.relevant_foreshadows(q, n)
    sel = {"static": base["static"], "extra": base["extra"], "named": named_ids,
           "states": state_kept(q, n, cast_ids), "fs": {f.id for f in fs_sel},
           "elements": {i for i, r in reasons.items() if r}}
    bad = align(q, prompt, sel)
    if set(sel["elements"]) != {el.id for el in elements.for_episode(q, n)}:
        bad.append("elements-for_episode")

    # 대리 정답
    new_chars = sorted(c.id for c in p.characters if c.id not in {x.id for x in q.characters} and char_hits(c, text))
    fs_open = [f for f in q.foreshadows if f.status == "open" and f.planted_ep < n]
    orig = {f.id: f for f in p.foreshadows}
    clue = defaultdict(list)
    for c in p.foreshadow_clues:
        if c.episode == n:
            clue[c.foreshadow].append(c.quote)
    loose = {c.foreshadow for d in p.history if d.episode == n for c in d.dismissed.foreshadow_clues}
    fs_named = {f.id for f in fs_open if clue.get(f.id) or (orig.get(f.id) and orig[f.id].payoff_ep == n)}
    planted_now = sorted(f.id for f in p.foreshadows if f.planted_ep == n)
    fs_trim = None
    if q.serial:
        fs_trim = fs_sim(fs_sel, fs_cut)
        if fs_trim.pop("line_block") not in prompt:
            bad.append("foreshadow-block")

    items = []
    for c in chars:
        hits = char_hits(c, text)
        blocks = [b for b, s in (("설정", sel["static"]), ("등장", base["plot"] | named_ids), ("상태", sel["states"])) if c.id in s
                  and not (b == "상태" and mode == "approx")]  # 근사는 인물 상태를 되돌리지 못해 세지 않는다
        why = "always" if c.id in base["static"] else "plot" if c.id in base["plot"] else "direct" if c.id in named_ids else ""
        items.append({"kind": "char", "id": c.id, "name": c.name, "desc": c.role[:60], "group": c.tier, "appeared": bool(hits),
                      "appeared_alt": bool(char_hits(c, alt)) if alt else None,
                      "selected": c.id in base["static"] or c.id in cast_ids, "in_text": bool(char_hits(c, prompt)),
                      "blocks": blocks, "reason": why, "always": c.id in base["static"],
                      "cost": size_of(c), "hits": [snippet(text, i) for i in hits[:3]],
                      "scan_hits": [snippet(scan_now, i) for i in char_hits(c, scan_now)[:2]]})
    for el in els:
        hits = el_hits(el, text)
        r = reasons[el.id]
        items.append({"kind": "element", "id": el.id, "name": el.name, "desc": " ".join(el.description.split())[:80],
                      "group": el.kind, "appeared": bool(hits),
                      "appeared_bound": bool(el_hits(el, text, bound=True)),
                      "appeared_alt": bool(el_hits(el, alt)) if alt else None,
                      "selected": bool(r), "in_text": bool(el_hits(el, prompt)), "blocks": ["이야기 요소"] if r else [],
                      "reason": r, "always": r == "always", "cost": len(elements.describe(q, el, n)) + 1,
                      "hits": [snippet(text, i) for i in hits[:3]], "scan_hits": [snippet(plot, i) for i in el_hits(el, plot)[:2]]})
    for f in fs_open:
        s = f.id in sel["fs"]
        items.append({"kind": "foreshadow", "id": f.id, "name": f.description[:60], "desc": "", "group": f.kind,
                      "appeared": f.id in fs_named, "appeared_loose": f.id in fs_named or f.id in loose,
                      "selected": s, "in_text": f.id in prompt or f.description in prompt, "blocks": ["열린 복선"] if s else [],
                      "reason": "rank" if s else "", "always": False, "cost": len(dump([f])), "hits": clue.get(f.id, [])[:2],
                      "scan_hits": []})
    return {"episode": n, "mode": mode, "prompt_chars": len(prompt), "mutated": mutated, "align": bad,
            "has_board": bool(board), "named_cut": named_cut, "extra_cut": base["extra_cut"], "fs_cut": fs_cut,
            "final_differs": bool(alt), "new_chars": new_chars, "planted_now": planted_now, "fs_trim": fs_trim,
            "items": items, "_L": light(q, n, base), "_scan": {"plot": plot, "board": board, "last": last}, "_body": text}


# ---------- 열린 복선 블록 줄이기 흉내 (spec 10 의 확인 (가)) ----------

def fs_sim(fs: list, fs_cut: int) -> dict:
    """화 하나의 블록 흉내: 한 줄 꼴과 예전 JSON 꼴의 글자, 설명 길이, 복선 하나의 JSON 덧붙는 글자."""
    line = prompts.serial_foreshadow_block(fs, fs_cut, as_json=False)
    old = prompts.serial_foreshadow_block(fs, fs_cut, as_json=True)
    return {"n_rel": len(fs), "fs_cut": fs_cut, "json_chars": len(old), "line_chars": len(line),
            "desc": {f.id: len(f.description) for f in fs},
            "overhead": len(prompts.dump(fs)) - sum(len(f.description) for f in fs) if fs else 0, "line_block": line}


def dist(xs: list[float]) -> dict:
    """개수 · 최소 · 사분위 · 최대 · 평균 (가까운 순위)."""
    if not xs:
        return {"n": 0}
    v = sorted(xs)
    at = lambda f: v[min(len(v) - 1, int(f * len(v)))]  # noqa: E731
    return {"n": len(v), "min": v[0], "p25": at(0.25), "median": at(0.5), "p75": at(0.75), "max": v[-1], "mean": sum(v) / len(v)}


def fs_summary(results: list[dict], mode: str = "exact") -> dict:
    """작품마다와 합친 값(ALL): 고른 수 · 설명 길이 · JSON 덧붙는 글자 분포와 두 꼴의 글자 합, 줄어든 몫.
    글자 합은 고른 복선이 하나라도 있는 화만으로 센다."""
    out = {}
    for r in results + [{"project": "ALL"}]:
        name = r["project"]
        rs = results if name == "ALL" else [r]
        eps = [e["fs_trim"] for x in rs for e in x["episodes"][mode] if e.get("fs_trim")]
        if not eps:
            continue
        desc: dict[str, int] = {}
        for e in eps:
            desc.update(e["desc"])
        with_fs = [e for e in eps if e["n_rel"]]
        old, new = sum(e["json_chars"] for e in with_fs), sum(e["line_chars"] for e in with_fs)
        out[name] = {"episodes": len(eps), "with_fs": len(with_fs), "n_rel": dist([e["n_rel"] for e in eps]),
                     "desc_len": dist(list(desc.values())),
                     "overhead_per_fs": sum(e["overhead"] for e in with_fs) / sum(e["n_rel"] for e in with_fs) if with_fs else None,
                     "json_chars": old, "line_chars": new, "cut_rel": 1 - new / old if old else None}
    return out


def fs_verdict(summary: dict, works: tuple[str, ...] = FS_WORKS) -> dict:
    """합친 값(ALL)과 독립 작품 셋 각각의 줄어든 몫이 FS_CHARS 이상인지. 결과에 없는 작품은 missing 에 적고 통과로 보지 않는다."""
    if "ALL" not in summary:
        return {}
    names = ["ALL", *works]
    per = {nm: summary[nm]["cut_rel"] is not None and summary[nm]["cut_rel"] >= FS_CHARS for nm in names if nm in summary}
    missing = [nm for nm in names if nm not in summary]
    return {"per": per, "missing": missing, "pass": not missing and all(per.values())}


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def fs_table(summary: dict, verdict: dict) -> str:
    """작품마다와 합친 값의 마크다운 표."""
    lines = ["| 작품 | 화 | 복선 있는 화 | 고른 수 중앙 · 최대 | 설명 평균 | JSON 덧붙는 글자 | JSON 글자 | 한 줄 글자 | 줄어듦 | 판정 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, row in summary.items():
        n, d, over = row["n_rel"], row["desc_len"], row["overhead_per_fs"]
        ok = verdict.get("per", {}).get(name)
        desc = f"{d['mean']:.0f}" if d["n"] else "-"
        extra = "-" if over is None else f"{over:.0f}"
        mark = "-" if ok is None else "통과" if ok else "못 넘음"
        lines.append(f"| {name} | {row['episodes']} | {row['with_fs']} | {n.get('median', '-')} · {n.get('max', '-')} | {desc} | {extra} | "
                     f"{row['json_chars']:,} | {row['line_chars']:,} | {pct(row['cut_rel'])} | {mark} |")
    if verdict:
        lines += ["", f"작품 기준(합친 값 + 독립 작품 셋, 줄어듦 {FS_CHARS:.0%} 이상): " + ("통과" if verdict["pass"] else "못 넘음")
                  + (f" (없는 작품: {', '.join(verdict['missing'])})" if verdict["missing"] else ""), ""]
    return "\n".join(lines)


# ---------- 범위 · 조건 흉내 ----------

def scopes() -> dict[str, tuple]:
    """범위 이름 → (인물 찾는 글 조각, 요소 찾는 글 조각). 조각은 ('plot' | 'board' | ('tail', N))."""
    out = {"now": (("plot", ("tail", context.NAMED_TAIL)), ("plot",)), "A": (("plot",), ("plot",)),
           "B": (("plot", "board"), ("plot", "board"))}
    for t in TAILS:
        if t:
            parts = ("plot", "board", ("tail", t))
            out[f"C{t}"] = (parts, parts)
    return out


def scan_text(scan: dict, parts: tuple) -> str:
    out = []
    for x in parts:
        if isinstance(x, tuple):
            out.append(scan["last"][-x[1]:] if x[1] else "")
        else:
            out.append(scan[x])
    return "\n".join(out)


def conditions() -> list[str]:
    """none 지금 조건, stickyN N화 유지, rec 되부름(요소 글 + 이번 화 조연 · 단역 설정), rec_core 되부름(주역 설정까지),
    rec_el 되부름(요소 글만, 명세서 02 의 정할 것 8)."""
    return ["none", *[f"sticky{k}" for k in STICKY], "rec", "rec_core", "rec_el"]


def direct_hits(m: dict, parts_c: tuple, parts_e: tuple) -> tuple[set[str], set[str]]:
    """찾는 범위에서 이름이 맞은 인물 · 요소 (플롯 인물인지와 상관없이). N화 유지의 씨앗이다."""
    L = m["_L"]
    ct, et = scan_text(m["_scan"], parts_c), scan_text(m["_scan"], parts_e)
    cs = {c.id for c in L["chars"] if char_hits(c, ct)}
    es = {el.id for el in L["els"] if any(t in et for t in elements.terms(el))}
    return cs, es


def simulate(m: dict, scope: tuple, cond: str, seeds: dict[int, tuple[set, set]]) -> dict:
    """한 범위 · 조건에서 선택된 인물 · 요소 id 와 예산으로 잘린 수. seeds 는 {화: (이름 맞은 인물, 요소)}."""
    L = m["_L"]
    n, base = L["n"], L["base"]
    direct_c, direct_e = direct_hits(m, *scope)
    cands = {cid: "direct" for cid in direct_c}
    el_sel = {}
    for el in L["els"]:
        r = el_reason(el, L["plot_cast"], n, "")
        if r:
            el_sel[el.id] = r
        elif el.id in direct_e:
            el_sel[el.id] = "direct"
    if cond.startswith("sticky"):
        k = int(cond[6:])
        live_c, live_e = {c.id for c in L["chars"]}, {el.id for el in L["els"]}
        for j in range(n - k, n):
            cs, es = seeds.get(j, (set(), set()))
            for cid in cs & live_c:
                cands.setdefault(cid, "sticky")
            for eid in es & live_e:
                el_sel.setdefault(eid, "sticky")
    if cond.startswith("rec"):
        src = [el.description for el in L["els"] if el.id in el_sel]
        on = base["plot"] | {c for c, r in cands.items() if r == "direct"}
        if cond != "rec_core":
            on -= base["static"]
        if cond != "rec_el":
            src += [dump(cast_view([c])) for c in L["chars"] if c.id in on or (cond == "rec_core" and c.id in base["static"])]
        text = "\n".join(src)
        for c in L["chars"]:
            if c.id not in cands and char_hits(c, text):
                cands[c.id] = "recursion"
        for el in L["els"]:
            if el.id not in el_sel and any(t in text for t in elements.terms(el)):
                el_sel[el.id] = "recursion"
    keep, cut = fit_ranked(L, cands, base["plot"], base["used"])
    return {"chars": base["static"] | base["cast"] | keep, "named": keep, "elements": set(el_sel), "cut": cut,
            "why_c": cands, "why_e": el_sel}


# ---------- 셈 ----------

def tally(items: list[dict], sel: dict[str, set] | None = None, key: str = "appeared") -> dict:
    """종류별 (나옴, 선택, 놓침, 엄격한 놓침, 낭비, 낭비 글자, 늘 넣기 낭비). sel 을 주면 인물 · 요소 선택을 그것으로 바꾼다."""
    out = {k: dict.fromkeys(("appeared", "selected", "miss", "miss_strict", "waste", "waste_chars", "waste_always"), 0) for k in KINDS}
    for it in items:
        k = it["kind"]
        s = it["selected"] if sel is None or k == "foreshadow" else it["id"] in sel["chars" if k == "char" else "elements"]
        a = bool(it.get(key)) if it.get(key) is not None else it["appeared"]
        t = out[k]
        t["appeared"] += a
        t["selected"] += s
        t["miss"] += a and not s
        t["miss_strict"] += a and not s and not it["in_text"]
        t["waste"] += s and not a
        t["waste_chars"] += it["cost"] if s and not a else 0
        t["waste_always"] += s and not a and it["always"]
    return out


def rate(eps: list[dict], kinds: tuple, num: str, den: str) -> dict:
    """화 묶음 부트스트랩으로 비율과 95% 구간. eps 는 [{kind: tally}]."""
    def stat(xs):
        d = sum(x[k][den] for x in xs for k in kinds)
        return sum(x[k][num] for x in xs for k in kinds) / d if d else None
    point = stat(eps)
    if point is None:
        return {"rate": None, "lo": None, "hi": None, "num": 0, "den": 0}
    groups = {str(i): [e] for i, e in enumerate(eps)}
    lo, hi = labstats.interval(labstats.cluster_boot(groups, stat), 0.95)
    return {"rate": point, "lo": lo, "hi": hi, "num": sum(x[k][num] for x in eps for k in kinds),
            "den": sum(x[k][den] for x in eps for k in kinds)}


# ---------- 작품 하나 ----------

def seed_of(p: Project, j: int) -> dict:
    """측정하지 않은 앞 화의 이름 매칭 재료만 (근사 사본, 프롬프트는 만들지 않는다)."""
    q = rebuild(p, j, "approx")
    ep = q.episode(j)
    last = next((e.text for e in q.episodes if e.plot.number == j - 1 and e.text), "")
    return {"episode": j, "_L": light(q, j, {}), "_scan": {"plot": elements.plot_text(ep), "board": prompts.board_block(q, j), "last": last}}


def run_project(name: str, approx_all: bool = True, check: bool = True, fs_only: bool = False) -> dict:
    """fs_only 면 범위 · 조건 흉내를 건너뛴다 (복선 흉내는 measure 가 화마다 한다)."""
    p = store.load(name)
    before = digest(p)
    fin = sorted(e.plot.number for e in p.episodes if e.status == "finalized")
    out = {"project": name, "finalized": len(fin), "keep_snapshots": p.settings.keep_snapshots,
           "fixed_only": p.settings.write_material == "fixed", "snapshots": sorted(s.episode for s in p.snapshots),
           "episodes": {"exact": [], "approx": []}, "sim": {"exact": {}, "approx": {}}}
    sc, conds = scopes(), conditions()
    pool: dict[int, dict] = {}  # N화 유지 씨앗을 셀 화 (근사 사본)
    for mode in ("approx", "exact"):
        todo = [n for n in fin if exact_ok(p, n)] if mode == "exact" else (fin if approx_all else [])
        ms = [measure(p, n, mode, check) for n in todo]
        if mode == "approx":
            pool = {m["episode"]: m for m in ms}
        have = {m["episode"]: m for m in ms}
        need = [] if fs_only else sorted({j for m in ms for j in range(m["episode"] - max(STICKY), m["episode"])} & set(fin))
        seeds = {s: {} for s in sc}
        for j in need:
            mj = have.get(j) or pool.get(j) or seed_of(p, j)
            for s, parts in sc.items():
                seeds[s][j] = direct_hits(mj, *parts)
        sim = {}
        for s, parts in ({} if fs_only else sc).items():
            for cond in conds:
                rows = []
                for m in ms:
                    r = simulate(m, parts, cond, seeds[s])
                    sel = {it["id"] for it in m["items"] if it["kind"] != "foreshadow" and it["selected"]}
                    got = {it["id"] for it in m["items"] if it["id"] in (r["chars"] if it["kind"] == "char" else r["elements"])
                           and it["kind"] != "foreshadow"}
                    if s == "now" and cond == "none" and got != sel:
                        m["align"].append("simulate-now")
                    t = tally(m["items"], r)
                    added = sum((1 if it["id"] in got else -1) * it["cost"] for it in m["items"]  # 지금보다 늘어난 항목 글자
                                if it["kind"] != "foreshadow" and (it["id"] in got) != it["selected"])
                    rows.append({"episode": m["episode"], "has_board": m["has_board"], "tally": t, "cut": r["cut"],
                                 "added_chars": added,
                                 "miss": sorted(it["id"] for it in m["items"] if it["kind"] != "foreshadow" and it["appeared"]
                                                and it["id"] not in got),
                                 "why": {**{k: v for k, v in r["why_c"].items() if v != "direct"},
                                         **{k: v for k, v in r["why_e"].items() if v in ("recursion", "sticky")}}})
                sim[f"{s}|{cond}"] = rows
        out["sim"][mode] = sim
        out["episodes"][mode] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in ms]
        if mode == "exact":
            out["_exact"] = ms
    out["unchanged"] = digest(p) == before
    return out


# ---------- 요약 ----------

def summarize(results: list[dict], mode: str = "exact") -> dict:
    """작품마다와 합친 값: 지금 범위의 놓침 · 낭비, 블록 · 종류별 셈, 범위 · 조건 흉내의 상대 변화."""
    out = {}
    for r in results + [{"project": "ALL"}]:
        name = r["project"]
        rs = results if name == "ALL" else [r]
        eps = [e for x in rs for e in x["episodes"][mode]]
        if not eps:
            continue
        ts = [tally(e["items"]) for e in eps]
        row = {"episodes": len(eps)}
        for k in KINDS:
            row[k] = {"miss": rate(ts, (k,), "miss", "appeared"), "miss_strict": rate(ts, (k,), "miss_strict", "appeared"),
                      "waste": rate(ts, (k,), "waste", "selected"),
                      "waste_chars": sum(t[k]["waste_chars"] for t in ts), "waste_always": sum(t[k]["waste_always"] for t in ts)}
        row["groups"] = groups(eps)
        row["blocks"] = blocks(eps)
        row["prompt_chars"] = sum(e["prompt_chars"] for e in eps) / len(eps)
        el_block = [sum(it["cost"] for it in e["items"] if it["kind"] == "element" and it["selected"]) for e in eps]
        row["element_block_max"] = max(el_block)  # 명세서 02 의 정할 것 11: 지금 데이터가 하나도 잘리지 않는 BUDGET["elements"]
        row["element_block_mean"] = sum(el_block) / len(el_block)
        row["align_bad"] = sum(1 for e in eps if e["align"])
        row["mutated"] = sum(1 for e in eps if e["mutated"])
        row["new_chars"] = sum(len(e["new_chars"]) for e in eps)
        row["planted_now"] = sum(len(e["planted_now"]) for e in eps)
        row["named_cut"] = sum(e["named_cut"] for e in eps)
        row["board_eps"] = sum(1 for e in eps if e["has_board"])
        row["final_differs"] = sum(1 for e in eps if e["final_differs"])
        row["alt"] = alt_diff(eps)
        row["el_bound"] = sum(1 for e in eps for it in e["items"] if it["kind"] == "element" and it["appeared"] and not it["appeared_bound"])
        row["fs_loose_extra"] = sum(1 for e in eps for it in e["items"] if it["kind"] == "foreshadow" and it["appeared_loose"] and not it["appeared"])
        row["sim"] = sim_table([x["sim"][mode] for x in rs])
        row["sim_board"] = sim_table([x["sim"][mode] for x in rs], board_only=True)
        out[name] = row
    return out


def overlap(results: list[dict]) -> dict:
    """정확한 재구성과 근사가 모두 된 화에서 두 값을 견준다 (근사의 치우침)."""
    out = {}
    for r in results:
        ex = {e["episode"]: e for e in r["episodes"]["exact"]}
        ap = [e for e in r["episodes"]["approx"] if e["episode"] in ex]
        if not ap:
            continue
        te, ta = [tally(ex[e["episode"]]["items"]) for e in ap], [tally(e["items"]) for e in ap]
        out[r["project"]] = {"episodes": len(ap), **{f"{m}_{k}": [sum(t[k][m] for t in te), sum(t[k][m] for t in ta)]
                                                     for k in KINDS for m in ("appeared", "selected", "miss", "waste")}}
    return out


def groups(eps: list[dict]) -> dict:
    out: dict = defaultdict(lambda: {"appeared": 0, "selected": 0, "miss": 0, "waste": 0})
    for e in eps:
        for it in e["items"]:
            g = out[f"{it['kind']}:{it['group']}"]
            g["appeared"] += it["appeared"]
            g["selected"] += it["selected"]
            g["miss"] += it["appeared"] and not it["selected"]
            g["waste"] += it["selected"] and not it["appeared"]
    return dict(out)


def blocks(eps: list[dict]) -> dict:
    """블록별 선택 수와 낭비 수 (인물 설정 · 이번 화 등장 · 인물 현재 상태 · 이야기 요소 · 열린 복선)."""
    out: dict = defaultdict(lambda: {"selected": 0, "waste": 0, "waste_chars": 0})
    for e in eps:
        for it in e["items"]:
            for b in it["blocks"]:
                out[b]["selected"] += 1
                out[b]["waste"] += not it["appeared"]
                out[b]["waste_chars"] += it["cost"] if not it["appeared"] else 0
    return dict(out)


def alt_diff(eps: list[dict]) -> dict:
    """final_text 대신 text 로 셌을 때 '나옴'이 바뀐 항목 수."""
    flips = sum(1 for e in eps for it in e["items"] if it.get("appeared_alt") is not None and it["appeared_alt"] != it["appeared"])
    return {"episodes": sum(1 for e in eps if e["final_differs"]), "flips": flips}


def sim_table(sims: list[dict], board_only: bool = False) -> dict:
    out = {}
    for key in sims[0]:
        rows = [row for s in sims for row in s[key] if row["has_board"] or not board_only]
        if not rows:
            continue
        ts = [row["tally"] for row in rows]
        out[key] = {"miss": sum(t[k]["miss"] for t in ts for k in ("char", "element")),
                    "appeared": sum(t[k]["appeared"] for t in ts for k in ("char", "element")),
                    "waste": sum(t[k]["waste"] for t in ts for k in ("char", "element")),
                    "selected": sum(t[k]["selected"] for t in ts for k in ("char", "element")),
                    "miss_char": sum(t["char"]["miss"] for t in ts), "miss_el": sum(t["element"]["miss"] for t in ts),
                    "waste_char": sum(t["char"]["waste"] for t in ts), "waste_el": sum(t["element"]["waste"] for t in ts),
                    "cut": sum(row["cut"] for row in rows), "added_chars": sum(row["added_chars"] for row in rows) / len(rows),
                    "episodes": len(rows)}
    return out


def verdict(summary: dict, names: list[str], key: str, base: str = "now|none", miss_drop: float = 0.2, waste_rise: float = 0.10,
            table: str = "sim") -> dict:
    """정할 것 8 · 9 · 10 의 문턱: 작품마다 놓침이 상대 miss_drop 이상 줄고 낭비가 상대 waste_rise 이하로 느는지."""
    per = {}
    for nm in names:
        t = summary.get(nm, {}).get(table, {})
        if key not in t or base not in t:
            continue
        a, b = t[base], t[key]
        dm = (b["miss"] - a["miss"]) / a["miss"] if a["miss"] else 0.0
        dw = (b["waste"] - a["waste"]) / a["waste"] if a["waste"] else 0.0
        per[nm] = {"miss_rel": dm, "waste_rel": dw, "pass": dm <= -miss_drop and dw <= waste_rise}
    return {"per": per, "votes": sum(1 for v in per.values() if v["pass"])}


# ---------- 판정 시트 ----------

def pick_samples(results: list[dict], per: int = 5) -> list[tuple[str, dict]]:
    """작품마다 놓침이 많은 화 2 · 낭비가 많은 화 2 · 무작위 1 (exact 화에서, 고정 씨앗)."""
    rnd = random.Random(SEED)
    out = []
    for r in results:
        ms = r.get("_exact", [])
        score = {m["episode"]: tally(m["items"]) for m in ms}
        miss = lambda n: score[n]["char"]["miss"] + score[n]["element"]["miss"] + score[n]["foreshadow"]["miss"]  # noqa: E731
        waste = lambda n: score[n]["char"]["waste"] + score[n]["element"]["waste"]  # noqa: E731
        eps = [m["episode"] for m in ms]
        chosen = sorted(eps, key=lambda n: (-miss(n), n))[:2]
        chosen += [n for n in sorted(eps, key=lambda n: (-waste(n), n)) if n not in chosen][:2]
        rest = [n for n in eps if n not in chosen]
        if rest:
            chosen.append(rnd.choice(rest))
        why = ["놓침 많음", "놓침 많음", "낭비 많음", "낭비 많음", "무작위"]
        by = {m["episode"]: m for m in ms}
        out += [(r["project"], by[n] | {"why": w}) for n, w in zip(chosen[:per], why)]
    return out


def sheet(project: str, m: dict) -> str:
    n = m["episode"]
    items = m["items"]
    lines = [f"# 판정 시트: {project} {n}화 ({m['why']})", "",
             "대리 정답(이름 매칭)과 다시 만든 쓰기 컨텍스트를 견준 결과입니다. 아래 세 칸을 채워 주세요.", "",
             "| 판정 | 적을 것 |", "|---|---|",
             "| 이름 없이 나온 항목 | (그 · 그녀 · 형 · 선배 · 직함 · 별명으로만 나온 인물 · 요소) |",
             "| 대리 정답이 잘못 '나옴'으로 본 항목 | (다른 뜻으로 맞은 낱말) |",
             "| 이 화를 쓰는 데 빠지면 안 됐던 항목 | (놓침 가운데 정말 필요했던 것) |", ""]
    for k, title in (("char", "인물"), ("element", "이야기 요소"), ("foreshadow", "열린 복선")):
        rows = [it for it in items if it["kind"] == k and (it["appeared"] or it["selected"])]
        if not rows:
            continue
        lines += [f"## {title}", "", "| 항목 | 본문에 나옴 | 선택됨 | 이유 · 블록 | 본문 매칭 앞뒤 30자 | 찾는 글 매칭 |", "|---|---|---|---|---|---|"]
        for it in sorted(rows, key=lambda x: (not x["appeared"], x["selected"], x["name"])):
            flag = "놓침" if it["appeared"] and not it["selected"] else "낭비" if it["selected"] and not it["appeared"] else ""
            lines.append(f"| {it['name']} ({it['id']}{', ' + it['desc'] if it['desc'] else ''}) {flag} | {'예' if it['appeared'] else ''} | {'예' if it['selected'] else ''} | "
                         f"{it['reason']} {'/'.join(it['blocks'])} | {' ／ '.join(h.replace('|', '¦') for h in it['hits'])} | "
                         f"{' ／ '.join(h.replace('|', '¦') for h in it['scan_hits'])} |")
        lines.append("")
    rest = [it for it in items if not it["appeared"] and not it["selected"]]
    if rest:
        lines += ["## 나오지도 선택되지도 않은 항목 (이름 없이 나왔는지 볼 때)", ""]
        lines += [f"- [{it['kind']}] {it['name']} ({it['id']}{', ' + it['desc'] if it['desc'] else ''})" for it in rest]
        lines.append("")
    if m["new_chars"]:
        lines += [f"데이터에 없던 인물(이 화 반영으로 생김, 세지 않음): {', '.join(m['new_chars'])}", ""]
    if m["planted_now"]:
        lines += [f"이번 화에 새로 심은 복선(세지 않음): {', '.join(m['planted_now'])}", ""]
    lines += ["## 본문", "", m["_body"]]
    return "\n".join(lines)


def write_sheets(results: list[dict], folder: Path) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for i, (proj, m) in enumerate(pick_samples(results), 1):
        f = folder / f"{i:02d} {proj} {m['episode']}화.md"
        f.write_text(sheet(proj, m), encoding="utf-8")
        t = tally(m["items"])
        index.append({"file": f.name, "project": proj, "episode": m["episode"], "why": m["why"],
                      "miss": {k: t[k]["miss"] for k in KINDS}, "waste": {k: t[k]["waste"] for k in KINDS}})
    (folder / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


# ---------- 실행 ----------

def main(argv: list[str] | None = None) -> dict:
    global TAILS, STICKY
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--projects", nargs="+", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--sheets", default="", help="판정 시트 20장을 쓸 폴더")
    ap.add_argument("--tail", default=",".join(map(str, TAILS)))
    ap.add_argument("--sticky", default=",".join(map(str, STICKY)))
    ap.add_argument("--no-approx", action="store_true", help="스냅샷 없는 화의 근사를 끈다")
    ap.add_argument("--fs-works", default=",".join(FS_WORKS), help="작품 기준의 독립 작품 (쉼표로)")
    ap.add_argument("--fs-mode", default="exact", choices=("exact", "approx"), help="복선 표와 판정에 쓸 재구성")
    ap.add_argument("--fs-only", action="store_true", help="범위 · 조건 흉내를 건너뛰고 복선 흉내만 한다")
    ap.add_argument("--fs-table", action="store_true", help="복선 흉내 표를 표준 출력에 찍는다")
    a = ap.parse_args(argv)
    TAILS = tuple(int(x) for x in a.tail.split(","))
    STICKY = tuple(int(x) for x in a.sticky.split(","))
    works = tuple(x for x in a.fs_works.split(",") if x)
    t0 = time.time()
    results = []
    for nm in a.projects:
        r = run_project(nm, approx_all=not a.no_approx, fs_only=a.fs_only)
        print(f"{nm}: exact {len(r['episodes']['exact'])}화 · approx {len(r['episodes']['approx'])}화 · 원본 그대로 {r['unchanged']} "
              f"({time.time() - t0:.0f}초)", file=sys.stderr)
        results.append(r)
    names = [r["project"] for r in results]
    summary = {"exact": summarize(results, "exact"), "approx": summarize(results, "approx"), "overlap": overlap(results)}
    keys = list(summary["exact"]["ALL"]["sim"]) if "ALL" in summary["exact"] else []
    verdicts = {k: {"scope": verdict(summary["exact"], names, k), "cond": verdict(summary["exact"], names, k, miss_drop=0.10, waste_rise=0.15),
                    "scope_board": verdict(summary["exact"], names, k, table="sim_board")} for k in keys}
    fs = {m: fs_summary(results, m) for m in ("exact", "approx")}
    fs_v = fs_verdict(fs[a.fs_mode], works)
    out = {"commit": os.popen("git -C " + str(Path(__file__).resolve().parents[1]) + " rev-parse --short HEAD").read().strip(),
           "projects": names, "summary": summary, "verdicts": verdicts,
           "foreshadow": {"mode": a.fs_mode, "works": list(works), "thresholds": {"chars": FS_CHARS},
                          "summary": fs, "verdict": fs_v},
           "results": [{k: v for k, v in r.items() if not k.startswith("_")} for r in results], "seconds": round(time.time() - t0)}
    if a.fs_table:
        print(fs_table(fs[a.fs_mode], fs_v))
    if a.sheets:
        out["sheets"] = write_sheets(results, Path(a.sheets))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=sorted), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
