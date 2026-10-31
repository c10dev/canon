"""관계 속도: 상태 변경안의 관계 유형 · 설명(쓴 뒤)과 화별 플롯(쓰기 전)이 관계 단계를 앞질러 가는지 본다. LLM 호출 없음.

관계 수치는 dynamics 가 사건으로 천천히 움직이는데, 관계 유형 · 설명은 상태 변경안이 언제든 새로 쓴다. 그래서 수치는
적대인데 유형은 '친구'가 되는 급변이 생긴다 (감정 급변 연구 2026-10-30, 9장). 여기서는 변경안의 사건을 사본에 돌려
반영 뒤 단계를 구하고, 글의 극성(낱말 사전)이 단계와 반대면 경고한다. 반대인 유형 바뀜은 상태 승인 화면에서 기본으로
체크하지 않고(StateDelta.rel_flagged), 사람 검토 없이 반영할 때는 빼서 남기지 않는다(hold). 막지는 않는다.
두 층 감정(prompts.LAYER, '겉: … / 속: …')으로 상대를 적은 인물은 일부러 만든 간극이라 보지 않는다.
인물 감정 글도 견줘 봤지만 한 문장에 인물이 여럿 나와 낱말이 누구를 향하는지 가리지 못해, 실제 작품 4개에서 8개가 모두 오탐이라 뺐다.
"""
from __future__ import annotations

import re
from collections import Counter, deque
from itertools import combinations

from . import dynamics, metrics, prompts
from .schema import Project, StateDelta

POSITIVE = ("친구", "연인", "동료", "화해", "동맹", "우정", "부부", "약혼", "애인", "신뢰", "믿", "사랑", "애정", "호감",
            "아끼", "고마", "감사", "설렘", "연모", "그리움", "의지")
NEGATIVE = ("원수", "앙숙", "숙적", "적대", "적의", "악연", "증오", "미움", "미워", "경멸", "혐오", "원망", "불신", "배신", "경계", "대립")
_WORD = re.compile("|".join(sorted(POSITIVE + NEGATIVE, key=len, reverse=True)))
_NOT = re.compile(r"^.{0,4}?(않|못|없|아니)")  # '믿지 않는', '사랑 없는' 처럼 바로 뒤에서 뒤집힌 말
STAGE_SIGN = {"호감": 1, "신뢰": 1, "화해": 1, "경계": -1, "균열": -1, "적대": -1, "낯섦": 0}
BIG = 3  # 한 쌍에 한 화 결정적(3) 사건이 이만큼이면 경고


_QUOTE = re.compile(r"[\'\"‘“「『][^\'\"’”」』]*[\'\"’”」』]")


def rel_polarity(type_: str, description: str) -> int:
    """관계의 극성. 유형 글로 보고, 유형이 중립이면 따옴표 속 대사를 뺀 설명으로 본다 (설명은 사건 이야기라 대사 속 '친구'가 섞인다)."""
    return polarity(type_) or polarity(_QUOTE.sub("", description or ""))


def polarity(text: str) -> int:
    """글의 극성: 긍정 낱말이 많으면 1, 부정 낱말이 많으면 -1, 같거나 없으면 0 ('앙숙에서 연인으로' 는 0)."""
    score = 0
    for m in _WORD.finditer(text or ""):
        sign = 1 if m.group(0) in POSITIVE else -1
        score += -sign if _NOT.match(text[m.end():]) else sign
    return (score > 0) - (score < 0)


def _after(p: Project, d: StateDelta) -> Project:
    """변경안의 사건을 돌린 뒤의 관계(사본). 작품은 그대로다."""
    sim = p.model_copy(update={"ties": [t.model_copy() for t in p.ties],
                               "relationships": [r.model_copy(deep=True) for r in p.relationships],
                               "secrets": [s.model_copy(deep=True) for s in p.secrets + d.secrets_added]})
    dynamics.seed_ties(sim)
    try:
        cast = set(p.episode(d.episode).plot.characters) | set(d.cast_added)
    except KeyError:
        cast = set()
    events = [e.model_copy(update={"episode": d.episode}) for e in d.events if e.kind != "수동보정"]
    dynamics.run_episode(sim, d.episode, events, cast)
    return sim


def _pair_sign(p: Project, a: str, b: str) -> int:
    """두 방향 단계가 같은 극성이면 그 극성. 한쪽만 있으면 그쪽, 엇갈리면 0 (한쪽만 숨긴 마음일 수 있다)."""
    signs = {STAGE_SIGN.get(t.stage, 0) for t in (dynamics.find_tie(p.ties, a, b), dynamics.find_tie(p.ties, b, a)) if t}
    return signs.pop() if len(signs) == 1 else 0


def _emotion(p: Project, d: StateDelta, cid: str) -> str:
    upd = next((u for u in d.character_updates if u.character_id == cid and u.emotional_state), None)
    if upd:
        return upd.emotional_state
    st = p.state_of(cid)
    return st.emotional_state if st else ""


def _masked(p: Project, d: StateDelta, a: str, b: str) -> bool:
    """a 나 b 의 감정이 두 층 라벨이고 상대 이름이 들어 있으면 일부러 만든 간극이다."""
    for x, y in ((a, b), (b, a)):
        text = _emotion(p, d, x)
        other = next((c.name for c in p.characters if c.id == y), "")
        if prompts.LAYER.search(text) and any(f in text for f in metrics.name_forms(other)):
            return True
    return False


def _names(p: Project) -> dict[str, str]:
    return {c.id: c.name or c.id for c in p.characters}


def clean_delta(p: Project, d: StateDelta) -> list[str]:
    """features.CLEAN 훅. 반대인 유형 바뀜의 차례를 d.rel_flagged 에 적고 경고 글을 돌려준다."""
    d.rel_flagged = []
    if not (d.relationship_updates or d.events):
        return []
    sim = _after(p, d)
    nm = _names(p)
    warns: list[str] = []
    for i, r in enumerate(d.relationship_updates):
        new = rel_polarity(r.type, r.description)
        cur = next((x for x in p.relationships if {x.a, x.b} == {r.a, r.b}), None)
        old = rel_polarity(cur.type, cur.description) if cur else 0
        sign = _pair_sign(sim, r.a, r.b)
        if new and new == -sign and new != old and not _masked(p, d, r.a, r.b):
            stage = dynamics.find_tie(sim.ties, r.a, r.b) or dynamics.find_tie(sim.ties, r.b, r.a)
            d.rel_flagged.append(i)
            warns.append(f"관계 유형: {nm.get(r.a, r.a)} ↔ {nm.get(r.b, r.b)} 유형이 '{r.type}'(으)로 바뀌는데, 반영 뒤 단계는 "
                         f"{stage.stage}예요. 사건이 아직 그만큼 쌓이지 않았어요. 기본으로 빼 두었으니 맞으면 체크해 주세요.")
    big = Counter(frozenset((e.actor, e.target)) for e in d.events if e.intensity >= 3 and e.kind != "수동보정")
    for pair, k in big.items():
        if k >= BIG and len(pair) == 2:
            a, b = sorted(pair)
            warns.append(f"관계 사건: {nm.get(a, a)} ↔ {nm.get(b, b)} 사이에 결정적(3) 사건이 {k}개예요. "
                         "그 화의 전환점 하나만 3으로 두면 관계가 덜 급하게 움직여요.")
    return warns


def hold(p: Project, d: StateDelta) -> int:
    """features.HOLD 훅 (자동 집필 · run -y · 플레이): 반대인 유형 바뀜은 반영하지 않고 뺀다.
    인물 화면에 남겨 두는 칸이 없어 남긴 개수(0)로 세지 않고, 무엇을 뺐는지 변경안 경고에 적어 반영 기록에 남긴다."""
    drop = set(d.rel_flagged)
    if not drop:
        return 0
    nm = _names(p)
    for i in sorted(drop):
        r = d.relationship_updates[i]
        d.warnings.append(f"관계 유형: 자동 반영에서 뺐어요: {nm.get(r.a, r.a)} ↔ {nm.get(r.b, r.b)} '{r.type}'")
    d.relationship_updates = [r for i, r in enumerate(d.relationship_updates) if i not in drop]
    d.rel_flagged = []
    return 0


# ---------- 쓰기 전: 화별 플롯이 한 화에 관계 단계를 몇 칸 옮기라고 하나 ----------
# 플롯이 한 화 만에 적 → 친구를 요구하면 쓰기 AI 는 그대로 쓴다 (jev 10화). 단계는 한 화에 한 칸(dynamics.STAGE_EDGES)이라
# 지금 단계에서 플롯이 바라는 쪽 단계까지 두 칸 넘으면 알린다. 앞에 안 쓴 화가 같은 쌍을 같은 쪽으로 옮기면 그만큼 칸을 더 준다.
# 화면 static/plot.js pacePlot 이 같은 규칙이다 (tests/test_plot_pace_js.py).
# 바뀜 말(정규식) → 가 닿을 단계. 친구 · 연인은 호감 · 신뢰, 화해 · 용서는 화해 (적대 → 화해는 한 칸이지만 적대 → 친구는 두 칸).
# 한글은 활용하면 끝 글자가 바뀌어('되' → '된' · '됐' · '돼') 활용형까지 적는다
_BE = "(?:되|된|됐|돼)"
FRIEND, MAKEUP = ("호감", "신뢰"), ("화해", "호감", "신뢰")
COOL, BREAK, ENEMY = ("경계", "균열", "적대"), ("균열", "적대"), ("적대",)
SHIFTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (f"친구가 {_BE}", FRIEND), ("친구로 (?:합류|인정|받아들)", FRIEND), ("마음을 (?:열|연)", FRIEND), (f"믿게 {_BE}", FRIEND),
    ("믿기 시작", FRIEND), ("신뢰하게", FRIEND), (f"연인이 {_BE}", FRIEND), ("사귀|사귄", FRIEND), ("고백을 받아들", FRIEND),
    ("화해", MAKEUP), ("용서", MAKEUP),
    ("등을 돌", COOL), ("멀어(?:지|진|졌|져)", COOL), ("믿지 않게", COOL), ("정을 (?:떼|뗀|뗐)", COOL),
    ("배신(?:하|한|했|해)", BREAK), ("절교", BREAK), ("결별", BREAK),
    (f"원수가 {_BE}", ENEMY), (f"적이 {_BE}", ENEMY), ("증오하게", ENEMY),
)
_SHIFTS = [(re.compile(pat), goal) for pat, goal in SHIFTS]


def _last_shift(sent: str) -> tuple[str, ...] | None:
    """문장의 바뀜 말 가운데 가장 뒤에 나온 것의 단계. 문장 끝 쪽이 그 화가 닿는 곳이다 ('용서하고 친구가 된다' 는 친구)."""
    best = max(((m.start(), goal) for rx, goal in _SHIFTS for m in rx.finditer(sent)), default=None, key=lambda x: x[0])
    return best[1] if best else None


_SENT = re.compile(r"[.!?。\n]+")
SIGN_WORD = {1: "가까워지는", -1: "멀어지는"}
UP = {"호감", "신뢰", "화해"}


def _steps(start: str, goals: tuple[str, ...]) -> int:
    """start 에서 goals 가운데 가장 가까운 단계까지 칸 수 (dynamics.STAGE_EDGES 의 너비 우선)."""
    seen, q = {start: 0}, deque([start])
    while q:
        cur = q.popleft()
        if cur in goals:
            return seen[cur]
        for nxt in dynamics.STAGE_EDGES.get(cur, ()):
            if nxt not in seen:
                seen[nxt] = seen[cur] + 1
                q.append(nxt)
    return 0


def name_forms(name: str) -> list[str]:
    """플롯 글에서 인물을 찾을 이름들: metrics.name_forms(세 글자 한글 이름은 성을 뗀 이름도)에 더해, 띄어 쓴 이름('야마이 렌')은
    두 글자 넘는 낱낱('야마이')도. 플롯 글은 흔히 이름 한 토막으로 부른다."""
    out = metrics.name_forms(name)
    return out + [w for w in name.split() if len(w) >= 2 and w not in out]


def plot_shifts(p: Project, n: int) -> list[tuple[str, str, tuple[str, ...]]]:
    """n 화 플롯(요약 · 사건 · 감정 변화)이 바라는 관계 바뀜: (인물, 인물, 가 닿을 단계들, SHIFTS).
    한 문장에 플롯 인물 이름이 둘이나 셋 있고 바뀜 말이 있을 때 그 이름들의 쌍마다. 넷 이상이면 누구 얘기인지 몰라 뺀다."""
    try:
        plot = p.episode(n).plot
    except KeyError:
        return []
    forms = [(c.id, f) for c in p.characters if c.id in plot.characters for f in name_forms(c.name)]
    out: list[tuple[str, str, tuple[str, ...]]] = []
    for sent in _SENT.split("\n".join([plot.summary, *plot.events, plot.emotional_shift])):
        goal = _last_shift(sent)
        if not goal:
            continue
        ids = sorted({cid for cid, f in forms if f in sent})
        if not 2 <= len(ids) <= 3:
            continue
        for a, b in combinations(ids, 2):
            if (a, b, goal) not in out:
                out.append((a, b, goal))
    return out


def plot_warnings(p: Project, n: int) -> list[str]:
    """n 화 플롯이 한 화에 관계 단계를 두 칸 넘게 옮기라고 하면 알린다. 지금 단계는 지금 관계(마지막 반영 뒤)다.
    마지막 반영 화와 n 화 사이 안 쓴 화가 같은 쌍을 같은 쪽으로 옮기면 한 화에 한 칸씩 더 준다."""
    last = max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)
    nm = _names(p)
    out = []
    for a, b, goal in plot_shifts(p, n):
        if _masked(p, StateDelta(episode=n, summary=""), a, b):
            continue
        ties = [t for t in (dynamics.find_tie(p.ties, a, b), dynamics.find_tie(p.ties, b, a)) if t]
        if not ties:
            continue
        far = max(ties, key=lambda t: _steps(t.stage, goal))
        need = _steps(far.stage, goal)
        sign = 1 if goal[0] in UP else -1
        room = 1 + sum(1 for k in range(last + 1, n) for x, y, g in plot_shifts(p, k) if (x, y) == (a, b) and (g[0] in UP) == (sign > 0))
        if need > room:
            out.append(f"{n}화 플롯: {nm.get(far.source, far.source)} → {nm.get(far.target, far.target)} 지금 단계는 {far.stage}예요. "
                       f"이 화는 {SIGN_WORD[sign]} 쪽을 바라는데 단계가 {need}칸 움직여야 해요(한 화에 한 칸). "
                       "계기 화와 받아들이는 화를 나누거나 앞 화에 다리를 놓아 주세요.")
    return out


def plan_warnings(p: Project) -> list[tuple[int, str]]:
    """본문이 없는 모든 화의 plot_warnings: (화, 경고)."""
    return [(e.plot.number, w) for e in sorted(p.episodes, key=lambda e: e.plot.number)
            if not e.text.strip() and e.status in ("draft", "confirmed") for w in plot_warnings(p, e.plot.number)]
