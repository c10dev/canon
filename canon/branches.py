"""갈래: 같은 작품에서 n화부터 다른 전개를 쓰는 사본. 갈래 하나는 작품 폴더 하나이고, 갈래 정보는 폴더의
branch.json(BranchInfo)에 둔다. 갈래끼리는 폴더 이름이 아니라 id 로 잇는다 (폴더 이름은 바뀔 수 있다).

합치기는 없다. 고르기는 본편으로 올리기(promote)다. 갈래를 만들어도 원본 project.json 은 바꾸지 않는다.
갈래 집안 계산(family, diverge, promote, remove)은 {폴더 이름: BranchInfo} 만 받는 순수 함수다. LLM 호출 없음."""
from __future__ import annotations

import hashlib
import shutil
import uuid

from . import dynamics, findings, pipeline, store, timeline
from .schema import (BranchDiff, BranchDiffRow, BranchEpisode, BranchInfo, BranchSide, Episode, ForkMode, Project,
                     Snapshot, TextVersion)

COPY_SKIP = ("autorun.json", "pending.json", "*.tmp")  # 갈래와 복제(web.duplicate_project)가 옮기지 않는 파일


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _ep(p: Project, n: int) -> Episode | None:
    return next((e for e in p.episodes if e.plot.number == n), None)


def last_finalized(p: Project) -> int:
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


def base_hash(p: Project, n: int) -> str:
    """1~(n-1)화 본문의 해시. 갈래가 함께 쓰는 앞 화가 갈라진 뒤 달라졌는지 본다."""
    h = hashlib.sha1()
    for e in sorted(p.episodes, key=lambda e: e.plot.number):
        if e.plot.number < n:
            h.update(f"{e.plot.number}\n{e.text}\n".encode())
    return h.hexdigest()[:16]


def shared_edited(p: Project, b: BranchInfo) -> bool:
    """p 의 1~(from_ep-1)화 본문이 갈래 b 가 갈라질 때와 다른가. 갈래 자신과 갈라져 나온 작품 양쪽에 쓴다."""
    return bool(b.parent and b.base) and base_hash(p, b.from_ep) != b.base


# ---------- 갈래 만들기 ----------

def check_fork(p: Project, n: int) -> None:
    """n화부터 갈라질 수 있는가. 1~(n-1)화가 모두 반영돼 있어야 한다 (반영은 화 순서대로라 마지막 반영 화로 본다)."""
    last = last_finalized(p)
    if not 1 <= n <= last + 1:
        raise ValueError(f"갈래는 1~{last + 1}화부터 만들 수 있어요 ({last}화까지 반영했어요)" if last
                         else "아직 반영한 화가 없어서 갈래는 1화부터만 만들 수 있어요")


def fork(p: Project, n: int, mode: ForkMode = "clear") -> list[int]:
    """p(복사한 작품)를 n화부터 갈라지게 만든다. n-1화 반영 직후로 되돌리고(pipeline.revert), 끝 화가 n화 이후인
    아크 · 부 요약과 n화부터의 스토리보드를 지운다. clear 면 n화부터의 본문을 이전 판으로 남기고 비워 플롯 확정 상태로 돌린다.
    keep 이면 본문을 남겨 상태 승인을 다시 하게 한다. 비운 화 번호를 낸다."""
    check_fork(p, n)
    if any(e.status == "finalized" and e.plot.number >= n for e in p.episodes):
        pipeline.revert(p, n - 1)
    for x in [*p.story_arcs, *p.parts]:  # revert 는 요약을 두지만, 갈래에서는 그 아크 · 부를 다시 쓴다
        if x.end_ep >= n:
            x.summary = ""
    for e in p.episodes:  # 스토리보드 · 큐 시트는 원본 전개의 쓰기 재료다. 갈래에서는 n화부터 다시 만든다
        if e.plot.number >= n:
            e.storyboard = None
            e.cue_sheet = None
    if mode == "keep":
        return []
    cleared = []
    for e in sorted(p.episodes, key=lambda e: e.plot.number):
        if e.plot.number < n or not e.text:
            continue
        if e.candidate:
            e.candidate.kind = "rejected"
            pipeline._keep_version(e, e.candidate)
            e.candidate = None
        pipeline._keep_version(e, TextVersion(id=pipeline._version_id(e), at=pipeline._now(), text=e.text,
                                              kind="previous", request=e.made_by, model=e.written_by,
                                              meta_cut=e.meta_cut))
        e.text, e.status, e.made_by, e.written_by, e.meta_cut = "", "confirmed", None, "", []
        e.hook, e.final_text = None, ""
        findings.clear(e)
        cleared.append(e.plot.number)
    return cleared


def make(name: str, to: str, n: int, mode: ForkMode = "clear", label: str = "") -> tuple[Project, BranchInfo]:
    """name 작품을 to 폴더로 복사해 n화부터 갈래를 만든다. 원본 project.json 은 바꾸지 않는다.
    원본에 갈래 정보가 없으면 원본을 본편으로 하는 branch.json 만 새로 쓴다."""
    if store.exists(to):
        raise ValueError(f"이미 있는 이름이에요: {to}")
    p = store.load(name)
    check_fork(p, n)
    src = store.load_branch(name)
    fresh = src is None
    if src is None:
        nid = _new_id()
        src = BranchInfo(id=nid, family=nid, at=pipeline._now())
    dst = store.project_dir(to)
    shutil.copytree(store.project_dir(name), dst, ignore=shutil.ignore_patterns(*COPY_SKIP))
    try:
        q = store.load(to)
        cleared = fork(q, n, mode)
        store.save(to, q)
        for k in cleared:  # store.save 는 본문이 있는 화만 내보내니 비운 화의 옛 파일은 지운다
            (dst / "episodes" / f"{k:02d}.md").unlink(missing_ok=True)
        info = BranchInfo(id=_new_id(), family=src.family, parent=src.id, from_ep=n, label=label.strip(),
                          at=pipeline._now(), base=base_hash(p, n))
        store.save_branch(to, info)
    except BaseException:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    if fresh:
        store.save_branch(name, src)
    return q, info


# ---------- 갈래 집안 ----------

def infos() -> dict[str, BranchInfo]:
    """모든 작품 폴더의 갈래 정보 (폴더 이름 → BranchInfo). branch.json 이 없는 작품은 빠진다."""
    out = {}
    if store.ROOT.exists():
        for d in sorted(store.ROOT.iterdir()):
            if (d / "project.json").exists() and (b := store.load_branch(d.name)) is not None:
                out[d.name] = b
    return out


def family(all_: dict[str, BranchInfo], name: str) -> dict[str, BranchInfo]:
    """name 과 같은 집안(본편과 갈래들). name 에 갈래 정보가 없으면 빈 dict."""
    b = all_.get(name)
    return {k: v for k, v in all_.items() if b is not None and v.family == b.family}


def main_of(fam: dict[str, BranchInfo]) -> str:
    return next((k for k, v in fam.items() if not v.parent), "")


def children(fam: dict[str, BranchInfo], name: str) -> list[str]:
    i = fam[name].id
    return [k for k, v in fam.items() if v.parent == i]


def path_up(fam: dict[str, BranchInfo], name: str) -> list[str]:
    """name 부터 본편까지 거슬러 오른 폴더 이름들. 부모를 지웠거나 고리가 있으면 거기서 멈춘다."""
    by_id = {v.id: k for k, v in fam.items()}
    out = [name]
    while (up := by_id.get(fam[out[-1]].parent)) and up not in out:
        out.append(up)
    return out


def diverge(fam: dict[str, BranchInfo], a: str, b: str) -> int:
    """a 와 b 가 몇 화부터 다른가 (1~(값-1)화를 함께 쓴다). 같은 작품이면 0, 이어지지 않으면 1."""
    if a == b:
        return 0
    if a not in fam or b not in fam:
        return 1
    up_a, up_b = path_up(fam, a), path_up(fam, b)
    common = next((x for x in up_a if x in up_b), None)
    if common is None:
        return 1
    hops = up_a[:up_a.index(common)] + up_b[:up_b.index(common)]
    return min(fam[x].from_ep for x in hops)


def order(fam: dict[str, BranchInfo]) -> list[tuple[str, int]]:
    """집안을 보일 순서: 본편부터, 자식 갈래는 갈라진 화 순서로 부모 바로 뒤에. (폴더 이름, 본편에서 몇 번 갈라졌는지).
    부모를 잃은 갈래도 빠뜨리지 않고 깊이 1로 붙인다."""
    out: list[tuple[str, int]] = []
    seen: set[str] = set()

    def walk(k: str, depth: int) -> None:
        seen.add(k)
        out.append((k, depth))
        for c in sorted(children(fam, k), key=lambda c: (fam[c].from_ep, c)):
            if c not in seen:
                walk(c, depth + 1)

    main = main_of(fam)
    for k in [main] * bool(main) + sorted(k for k in fam if k != main):
        if k not in seen:
            walk(k, 0 if k == main else 1)
    return out


def promote(fam: dict[str, BranchInfo], name: str) -> dict[str, BranchInfo]:
    """name 을 본편으로 올린다. 본편에서 name 까지 길의 이음을 뒤집고, 이음마다 갈라진 화와 해시는 그대로 둔다.
    다른 갈래는 그대로라 어느 두 작품이 몇 화부터 다른지(diverge)는 바뀌지 않는다. 바뀐 정보만 낸다."""
    up = path_up(fam, name)
    if len(up) == 1:
        return {}
    new = {k: fam[k].model_copy() for k in up}
    for child, parent in zip(up, up[1:]):
        c = fam[child]
        new[parent].parent, new[parent].from_ep, new[parent].base = c.id, c.from_ep, c.base
    new[name].parent, new[name].from_ep, new[name].base = "", 0, ""
    return new


def remove(fam: dict[str, BranchInfo], name: str) -> dict[str, BranchInfo]:
    """name 을 집안에서 뺀다 (지우기 · 끊기 전에 부른다). name 의 자식은 name 의 부모에 붙이고, 갈라진 화는 둘 중
    이른 화로 한다. name 이 본편이면 가장 늦게 갈라진 자식을 먼저 본편으로 올린다. name 을 뺀 바뀐 정보만 낸다."""
    fam = dict(fam)
    out: dict[str, BranchInfo] = {}
    if not fam[name].parent:
        kids = children(fam, name)
        if not kids:
            return {}
        out = promote(fam, max(kids, key=lambda k: (fam[k].from_ep, k)))
        fam.update(out)
    b = fam[name]
    for k in children(fam, name):
        c = fam[k]
        early = c.from_ep <= b.from_ep
        out[k] = c.model_copy(update={"parent": b.parent, "from_ep": c.from_ep if early else b.from_ep,
                                      "base": c.base if early else b.base})
    out.pop(name, None)
    return out


def promote_saved(name: str) -> None:
    """저장된 작품 name 을 본편으로 올린다. 갈래 정보(branch.json)만 바꾼다."""
    fam = family(infos(), name)
    if name not in fam:
        raise ValueError("갈래가 없는 작품이에요")
    for k, v in promote(fam, name).items():
        store.save_branch(k, v)


# ---------- 비교 ----------

STATE_FIELDS = (("emotional_state", "감정"), ("current_goal", "목표"), ("location", "위치"), ("attire", "차림"))


def _side(p: Project, n: int) -> BranchSide | None:
    e = _ep(p, n)
    if e is None:
        return None
    return BranchSide(title=e.plot.title, status=e.status, summary=e.summary, chars=len(e.text))


def _tie_text(t) -> str:
    return f"{dynamics.warmth_word(t.warmth)} · {dynamics.trust_word(t.trust)} · {t.stage}"


def _rows(a: Project, b: Project, sa: Snapshot, sb: Snapshot, from_ep: int, n: int) -> list[BranchDiffRow]:
    names = {c.id: c.name or c.id for c in [*b.characters, *a.characters]}
    rows: list[BranchDiffRow] = []

    def add(kind, who, field, x, y):
        if x != y:
            rows.append(BranchDiffRow(kind=kind, who=who, field=field, a=x, b=y))

    st_a = {s.character_id: s for s in sa.states}
    st_b = {s.character_id: s for s in sb.states}
    for cid in dict.fromkeys([*st_a, *st_b]):
        x, y = st_a.get(cid), st_b.get(cid)
        for key, label in STATE_FIELDS:
            add("character", names.get(cid, cid), label, getattr(x, key, "") if x else "", getattr(y, key, "") if y else "")
        add("character", names.get(cid, cid), "아는 것", " · ".join(x.knows) if x else "", " · ".join(y.knows) if y else "")

    ties_a = {(t.source, t.target): t for t in sa.ties}
    ties_b = {(t.source, t.target): t for t in sb.ties}
    for key in dict.fromkeys([*ties_a, *ties_b]):
        x, y = ties_a.get(key), ties_b.get(key)
        add("tie", f"{names.get(key[0], key[0])} → {names.get(key[1], key[1])}", "관계",
            _tie_text(x) if x else "", _tie_text(y) if y else "")

    for f in dict.fromkeys([*sa.facts, *sb.facts]):
        add("fact", "", "사실", f if f in sa.facts else "", f if f in sb.facts else "")

    fs_a = {f.id: f for f in sa.foreshadows}
    fs_b = {f.id: f for f in sb.foreshadows}
    fs_text = lambda f: f"{f.description} ({'회수' if f.status == 'resolved' else '열림'})" if f else ""
    for fid in dict.fromkeys([*fs_a, *fs_b]):
        add("foreshadow", fid, "복선", fs_text(fs_a.get(fid)), fs_text(fs_b.get(fid)))

    ea, eb = _ep(a, n), _ep(b, n)
    add("time", "", f"{n}화 끝", timeline.when(a, ea.time) if ea else "", timeline.when(b, eb.time) if eb else "")

    def settings(p: Project) -> dict[tuple[str, str], str]:
        return {(r.character_id, r.field): r.after for r in p.setting_log if from_ep <= r.episode <= n}

    set_a, set_b = settings(a), settings(b)
    for key in dict.fromkeys([*set_a, *set_b]):
        add("setting", names.get(key[0], key[0]), key[1], set_a.get(key, ""), set_b.get(key, ""))
    return rows


def compare(a: Project, b: Project, from_ep: int, n: int) -> BranchDiff:
    """두 갈래를 견준다. from_ep 화부터 화별 제목 · 요약, n화 본문, n화 반영 직후 상태에서 다른 칸.
    한쪽이라도 n화를 반영하지 않았으면 상태 차이는 비운다."""
    nums = sorted({e.plot.number for e in [*a.episodes, *b.episodes] if e.plot.number >= from_ep})
    sa, sb = a.snapshot(n), b.snapshot(n)
    ea, eb = _ep(a, n), _ep(b, n)
    return BranchDiff(from_ep=from_ep, episode=n, ready_a=sa is not None, ready_b=sb is not None,
                      text_a=ea.text if ea else "", text_b=eb.text if eb else "",
                      episodes=[BranchEpisode(number=k, a=_side(a, k), b=_side(b, k)) for k in nums],
                      rows=_rows(a, b, sa, sb, from_ep, n) if sa and sb else [])


def compare_saved(name: str, other: str, ep: int = 0) -> BranchDiff:
    """저장된 같은 집안의 두 작품을 견준다. ep 를 주지 않으면 두 작품이 함께 반영한 마지막 화(갈라진 화보다 앞이면 갈라진 화)."""
    fam = family(infos(), name)
    if other not in fam or other == name:
        raise ValueError("같은 갈래 집안의 다른 작품과만 견줄 수 있어요")
    a, b = store.load(name), store.load(other)
    start = diverge(fam, name, other)
    n = ep or max(start, min(last_finalized(a), last_finalized(b)))
    return compare(a, b, start, n)
