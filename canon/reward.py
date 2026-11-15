"""웹소설 틀 장편의 보상 박자 경고 (docs/webnovel/specs/07-reward-warn.md). LLM 호출 없음. 막지 않고 알리기만 한다.

두 가지를 본다.
- 하렘 균열이 김: 주인공과 공략 대상(StoryArc.focus) 사이 관계가 균열 · 적대로 HAREM_MAX 화를 넘게 이어짐.
  반영한 화는 지금 관계(Tie.stage · stage_since)로, 안 쓴 화는 플롯이 바라는 관계 바뀜(pace.plot_shifts)으로 센다.
- 아크에 성장이 없음: 얻는 성장(StoryArc.gain)이 비었고 그 범위에 성장 일정(Blueprint.ability_plans) 줄도 없는 아크.

'사이다 없는 화가 이어짐' · '고구마 구간이 김'은 화마다 사이다를 가려 세는 신호가 없어 두지 않았다(명세서 정할 것 3 · 4).
화면 static/plot.js 의 rewardRows 가 같은 규칙이다 (tests/test_reward_warn.py).
"""
from __future__ import annotations

from . import dynamics, pace, prompts
from .schema import Project

HAREM_MAX = 3  # 하렘 쌍의 균열 · 적대가 이 화수를 넘게 이어지면 경고 (정할 것 8, 웹소설 규칙 '균열은 1~3화 오해')
ROUGH = ("균열", "적대")


def on(p: Project) -> bool:
    """경고를 내는 작품: 웹소설 틀 장편. 드라마 틀 · 단편은 늘 빈 목록이다."""
    return p.serial and prompts.webnovel(p)


def hero_id(p: Project) -> str:
    """주인공 id: 역할에 '주인공'이 들어간 인물, 없으면 첫 주역 (opening.hero_name 과 같은 규칙)."""
    lead = next((c for c in p.characters if "주인공" in c.role), None) or next((c for c in p.characters if c.tier == "main"), None)
    return lead.id if lead else ""


def _last_done(p: Project) -> int:
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


def _upcoming(p: Project, last: int) -> list[int]:
    """반영한 마지막 화 뒤의 본문 없는 화 번호 (차례대로)."""
    return sorted(e.plot.number for e in p.episodes if e.plot.number > last and not e.text.strip() and e.status in ("draft", "confirmed"))


def _mends(p: Project, n: int, a: str, b: str) -> bool:
    """n 화 플롯이 a ↔ b 관계를 가까워지는 쪽으로 옮기는가."""
    return any({x, y} == {a, b} and g[0] in pace.UP for x, y, g in pace.plot_shifts(p, n))


def harem_rows(p: Project) -> list[dict]:
    """하렘 균열이 김: [{kind: 'harem', n: 고칠 첫 화(없으면 0), text}]. 쌍마다 더 오래 이어진 쪽 하나."""
    if not (on(p) and prompts.harem(p)):
        return []
    hero = hero_id(p)
    names = {c.id: c.name or c.id for c in p.characters}
    focus = list(dict.fromkeys(a.focus for a in p.story_arcs if a.focus and a.focus != hero and a.focus in names))
    last = _last_done(p)
    ahead = _upcoming(p, last)
    out = []
    for f in focus:
        best = None
        for s, t in ((hero, f), (f, hero)):
            tie = dynamics.find_tie(p.ties, s, t)
            if not tie or tie.stage not in ROUGH:
                continue
            run = last - tie.stage_since + 1 if 0 < tie.stage_since <= last else last
            planned = 0
            for n in ahead:
                if _mends(p, n, hero, f):
                    break
                planned += 1
            if best is None or run + planned > best[0] + best[1]:
                best = (run, planned, tie)
        if best and best[0] + best[1] > HAREM_MAX:
            run, planned, tie = best
            more = f" (반영한 화 {run}화, 안 쓴 화 플롯 {planned}화)" if planned else ""
            out.append({"kind": "harem", "n": ahead[0] if ahead else 0,
                        "text": f"{names[tie.source]} → {names[tie.target]} 관계가 {tie.stage}로 {run + planned}화 이어져요{more}. "
                                f"하렘 관계의 균열은 {HAREM_MAX}화 안에 풀리는 오해로 둬요. 다음 화 플롯에서 풀어 주세요."})
    return out


def growth_rows(p: Project) -> list[dict]:
    """아크에 성장이 없음: [{kind: 'growth', n: 아크 번호, text}]. 본문 없는 화가 남은 아크만 (고칠 수 있는 아크)."""
    if not on(p):
        return []
    out = []
    for a in p.story_arcs:
        if a.gain.strip():
            continue
        if any(x.from_ep and x.from_ep <= a.end_ep and (x.to_ep or x.from_ep) >= a.start_ep for x in p.blueprint.ability_plans):
            continue
        if all(e.text.strip() for e in p.episodes if a.start_ep <= e.plot.number <= a.end_ep) and \
                any(a.start_ep <= e.plot.number <= a.end_ep for e in p.episodes):
            continue
        out.append({"kind": "growth", "n": a.number,
                    "text": f"아크 {a.number}의 얻는 성장이 비었고 {a.start_ep}~{a.end_ep}화에 성장 일정 줄도 없어요. 이 아크에서 주인공이 얻는 것을 적어 주세요."})
    return out


def rows(p: Project) -> list[dict]:
    """모든 보상 박자 경고. 웹소설 틀 장편이 아니면 빈 목록."""
    return harem_rows(p) + growth_rows(p)
