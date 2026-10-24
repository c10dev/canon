"""화 끼워 넣기 · 빼기: 아직 안 쓴 화 앞에 새 화를 넣거나 안 쓴 화를 뺄 때 화 번호를 품은 곳을 함께 옮긴다.

LLM 을 부르지 않는다. 검사(본문이 있는 화는 옮기지 않기, 구조가 맞는지)와 새 화 만들기는
pipeline.insert_episode / remove_episode 가 맡고, 여기는 번호를 옮기는 규칙만 둔다.

번호에는 두 가지가 있다.
- 한 화를 가리키는 번호(point): 플롯 번호, 복선 회수 화, 인과율 요소의 화, 줄기가 갈라지고 합류하는 화 등.
  끼워 넣으면 at 부터 한 칸씩 밀리고, 빼면 뒤 화가 한 칸씩 당겨진다. 뺀 화를 가리키던 번호는 그 자리에 온 다음 화를 가리킨다.
- 범위(구간 · 아크 · 부): 새 화는 바로 뒤 화(at)가 든 범위에 들어간다. 맨 끝에 붙이면 끝나는 범위가 늘어난다.
본문 · 상태 기록 · 스냅샷 · 사건 로그는 본문이 있는 화에만 있으므로 옮기지 않는다 (pipeline 이 그런 화를 옮기지 못하게 막는다).
"""
from __future__ import annotations

from typing import Callable

from .schema import Project

Point = Callable[[int], int]


def point_insert(at: int) -> Point:
    return lambda x: x + 1 if x and x >= at else x


def point_remove(n: int) -> Point:
    return lambda x: x - 1 if x and x > n else x


def shift_ranges(ranges: list, at: int) -> None:
    """at 화 앞에 한 화를 넣을 때 범위들(start_ep, end_ep)을 고친다. 새 화는 at 이 든 범위, 없으면 at-1 에서 끝나는 범위에 든다."""
    host = next((r for r in ranges if r.start_ep <= at <= r.end_ep), None) \
        or next((r for r in ranges if r.end_ep == at - 1), None)
    for r in ranges:
        if r is host:
            r.end_ep += 1
        elif r.start_ep >= at:
            r.start_ep += 1
            r.end_ep += 1
        elif r.end_ep >= at:  # 짧은 작품에서 한 화를 함께 쓰는 구간
            r.end_ep += 1


def shrink_ranges(ranges: list, n: int) -> list:
    """n 화를 뺄 때 범위들을 고친다. 비게 된 범위를 돌려준다."""
    for r in ranges:
        if r.start_ep > n:
            r.start_ep -= 1
            r.end_ep -= 1
        elif r.end_ep >= n:
            r.end_ep -= 1
    return [r for r in ranges if r.end_ep < r.start_ep]


def last_fixed(p: Project) -> int:
    """옮길 수 없는 마지막 화: 본문이 있거나 상태가 반영된 화 중 가장 뒤. 없으면 0."""
    eps = [e.plot.number for e in p.episodes if e.text or e.status in ("written", "finalized") or e.candidate]
    return max([*eps, *(d.episode for d in p.history), *(s.episode for s in p.snapshots), *(x.episode for x in p.events), 0])


def move_points(p: Project, f: Point, gone: int = 0) -> dict[str, int]:
    """화 하나를 가리키는 번호를 f 로 옮긴다. gone 은 빼는 화 (그 화만의 기록은 지운다). 고친 곳 수를 종류별로 돌려준다."""
    count = {"foreshadows": 0, "elements": 0, "storylines": 0, "characters": 0}

    def mv(x, key: str):
        y = f(x) if x else x
        if y != x:
            count[key] += 1
        return y

    for e in p.episodes:
        e.plot.number = f(e.plot.number)
        if e.hook:
            e.hook.episode = f(e.hook.episode)
    for fs in p.foreshadows:
        before = (fs.planted_ep, fs.payoff_ep, fs.due_ep)
        fs.planted_ep = f(fs.planted_ep)
        fs.payoff_ep = f(fs.payoff_ep) if fs.payoff_ep else fs.payoff_ep
        fs.due_ep = f(fs.due_ep) if fs.due_ep else fs.due_ep
        count["foreshadows"] += before != (fs.planted_ep, fs.payoff_ep, fs.due_ep)
    for el in p.elements:
        before = (el.since_ep, list(el.episodes), el.reveal_ep)
        el.since_ep = f(el.since_ep)
        el.episodes = sorted({f(x) for x in el.episodes})
        el.reveal_ep = f(el.reveal_ep)
        count["elements"] += before != (el.since_ep, el.episodes, el.reveal_ep)
        if el.impact:
            rep = el.impact.report
            for c in rep.conflicts:
                c.episode = f(c.episode)
            rep.episodes = [x for x in rep.episodes if x.number != gone]
            for x in rep.episodes:
                x.number = f(x.number)
            for t in rep.patches:
                t.episode = f(t.episode)
    for s in p.storylines:
        before = (s.branch_ep, s.join_ep)
        s.branch_ep, s.join_ep = f(s.branch_ep), f(s.join_ep)
        count["storylines"] += before != (s.branch_ep, s.join_ep)
    for c in [*p.characters, *p.cast_candidates]:
        c.first_ep = mv(c.first_ep, "characters")
    chats = []
    for c in p.chats:
        if c.topic.startswith("text:") and c.topic[5:].isdigit():
            k = int(c.topic[5:])
            if k == gone:
                continue
            c.topic = f"text:{f(k)}"
        for m in c.messages:
            if m.revision:
                m.revision.episodes = [x for x in m.revision.episodes if x.number != gone]
                for x in m.revision.episodes:
                    x.number = f(x.number)
        chats.append(c)
    p.chats = chats
    if p.archive:
        p.archive.map = [x for x in p.archive.map if x.number != gone]
        for x in p.archive.map:
            x.number = f(x.number)
    return count
