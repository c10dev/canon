"""인물 자취: 승인한 본문에서 한 인물이 남긴 선택 · 말 · 드러냄과 뒤 화의 다시 꺼냄 (Project.trails, CharTrail, TrailEcho).

채우는 길은 상태 변경안의 trails · trail_echoes 다 (docs/trail 일감 6). 작가가 승인한 줄만 쌓인다.
기본으로 체크하고 hold 하지 않는다: 자동 집필 · run -y 도 반영한다 (본문에 드러난 일의 기록이라서, 보는 눈과 같다).
쓰는 길(기획 블록)은 일감 9 다.
되돌리기(features.REVERT_LAST)와 다시 짜기(reshape)가 n화 뒤 자취 · 다시 꺼냄과 지워진 인물을 지운다.
LLM 을 부르지 않는다.
"""
from __future__ import annotations

from . import context
from .schema import CharTrail, Project, StateDelta, TrailEcho, TrailEchoChange, TrailChange

MAX_PER_EPISODE = 3  # 한 화에 받는 자취 줄 수. 넘으면 앞의 것만
MAX_ECHOES = 4       # 한 화에 받는 다시 꺼냄 줄 수. 본 사람 줄을 앞으로 옮긴 뒤 자른다
FAR = 8              # 이 화 수보다 더 떨어진 자취를 '먼 화'로 본다. 쓰기 · 기획 요청의 접은 줄거리에서 빠진 화를 어림한 값


def _clean(t: CharTrail, ids: set[str], n: int | None = None) -> CharTrail:
    """지워진 인물(과 n화 뒤 다시 꺼냄)을 뺀 사본."""
    return t.model_copy(update={
        "witnesses": [w for w in t.witnesses if w in ids],
        "echoes": [e for e in t.echoes if e.character in ids and (n is None or e.episode <= n)],
    })


def live(p: Project) -> list[CharTrail]:
    """주인이 p.characters 에 있는 자취만, 저장 차례 그대로.
    witnesses 와 echoes 에서 지워진 인물(echo.character 가 없는 인물)은 뺀 사본. p.trails 는 바꾸지 않는다."""
    ids = {c.id for c in p.characters}
    return [_clean(t, ids) for t in p.trails if t.character in ids]


def revert(p: Project, n: int) -> None:
    """되돌리기 훅. episode > n 인 자취와, 주인이 없는 인물인 자취를 지운다.
    남은 자취의 echoes 에서 episode > n 인 줄과 character 가 없는 인물인 줄을 지우고, witnesses 에서 없는 인물을 뺀다."""
    ids = {c.id for c in p.characters}
    p.trails = [_clean(t, ids, n) for t in p.trails if t.episode <= n and t.character in ids]


def next_id(p: Project, n: int) -> str:
    """n화 자취의 다음 id: f"tr-{n:03d}-{k}", k = 그 화의 가장 큰 차례 + 1. 없으면 1."""
    prefix = f"tr-{n:03d}-"
    top = 0
    for t in p.trails:
        if t.episode == n and t.id.startswith(prefix) and t.id[len(prefix):].isdigit():
            top = max(top, int(t.id[len(prefix):]))
    return f"{prefix}{top + 1}"


def _decided(p: Project, n: int) -> set[int]:
    """n화 플롯의 이어받기 결정이 가리키는 화 번호. 0 은 건너뛴다. n화 플롯이 없으면 빈 집합."""
    try:
        return {c.episode for c in p.episode(n).plot.carry if c.episode > 0}
    except KeyError:
        return set()


def _overlap(t: CharTrail, ids: set[str] | None) -> int:
    """0: 주인과 본 사람이 함께 ids 에 있음, 1: 주인만, 2: 본 사람만. ids 가 None 이면 0."""
    if ids is None:
        return 0
    seen = any(w in ids for w in t.witnesses)
    if t.character in ids:
        return 0 if seen else 1
    return 2


def _line(t: CharTrail, name: dict[str, str]) -> str:
    line = f"- {t.id} {name.get(t.character, t.character)} · {t.kind} · {t.episode}화 '{t.label}'"
    if t.witnesses:
        line += f" (본 사람: {', '.join(name.get(w, w) for w in t.witnesses)})"
    if t.echoes:
        line += " · 다시 꺼냄: " + " / ".join(f"{e.episode}화 '{e.meaning}'" for e in t.echoes[-2:])
    return line


def state_block(p: Project, ids: set[str] | None, n: int) -> str:
    """상태 변경안 요청에 넣는 앞 화 자취. 결정이 가리키는 화 · 먼 화 · 가까운 화 차례, 같은 무리는 주인과 본 사람이 함께 나오는 것이 먼저. 없으면 빈 글."""
    decided = _decided(p, n)
    rows = [t for t in live(p) if t.episode < n and (ids is None or t.character in ids or any(w in ids for w in t.witnesses))]

    def key(t: CharTrail) -> tuple[int, int, int]:
        group = 0 if t.episode in decided else 1 if n - t.episode > FAR else 2
        return (group, _overlap(t, ids), -t.episode)

    rows.sort(key=key)  # 안정 정렬
    name = {c.id: c.name for c in p.characters}
    keep, cut = context.fit_lines([_line(t, name) for t in rows], context.BUDGET["state_trails"])
    if not keep:
        return ""
    return ("\n[앞 화 자취 (다시 꺼냈으면 trail_echoes 에 이 id 로 적는다)]\n" + "\n".join(keep)
            + (f"\n(그 밖 {cut}줄 생략)" if cut else ""))


def state_rule(p: Project) -> str:
    """상태 변경안 규칙 한 줄. 늘 붙는다."""
    return ("\n- trails 에는 이번 화 본문에서 한 인물이 뒤 화에서 다시 떠올릴 만한 선택 · 말 · 드러냄을 남긴 것만 넣습니다. "
            "본문의 속말 · 대사 · 행동에 드러난 일만 적고 시점 밖 인물의 속을 짐작하지 않습니다. "
            "label 은 문장이 아니라 짧은 이름으로 적습니다(예: '핑계를 대고 밥 약속을 거절함'). quote 는 이번 화 본문 그대로 한 문장입니다. "
            "witnesses 에는 그 자리에서 보거나 들은 인물을 빠짐없이 적습니다. 뒤 화에서 그 일을 기억해 태도를 정할 사람이며, 주인은 넣지 않습니다. "
            "상대에 대해 알게 된 것은 자취가 아니라 아는 정보(knows)에 둡니다. "
            "trail_echoes 에는 이번 화에서 [앞 화 자취]의 일을 떠올리거나 그 일을 근거로 움직인 곳을 그 id 로만 적습니다. "
            "주인이 아닌 인물(특히 본 사람)이 그 일을 기억해 지금 태도를 정한 곳을 먼저 적고, meaning 에는 이번 화에서 그 일이 갖는 뜻을 적습니다. "
            "본문이 그 자취와 다르게 말하면 conflict 에 무엇이 다른지 적습니다. 대부분의 화에는 trails 와 trail_echoes 가 모두 비어 있습니다.")


def _squash(s: str) -> str:
    """연속 공백 · 줄바꿈을 하나의 공백으로."""
    return " ".join(s.split())


def _clean_trails(d: StateDelta, ids: set[str], text: str) -> list[TrailChange]:
    flat = _squash(text)
    last: dict[tuple[str, str], TrailChange] = {}
    for x in d.trails:
        label = x.label.strip()
        if x.character not in ids or not label:
            continue
        seen: list[str] = []
        for w in x.witnesses:
            if w in ids and w != x.character and w not in seen:
                seen.append(w)
        quote = x.quote.strip()
        if quote and _squash(quote) not in flat:
            quote = ""
        last[(x.character, label)] = x.model_copy(update={"label": label, "quote": quote, "witnesses": seen})  # 같은 주인 · 같은 라벨은 뒤의 것만
    return list(last.values())[:MAX_PER_EPISODE]


def _echo_group(x: TrailEchoChange, t: CharTrail) -> int:
    """0: 본 사람, 1: 주인도 본 사람도 아님, 2: 주인."""
    if x.character in t.witnesses:
        return 0
    return 2 if x.character == t.character else 1


def _clean_echoes(p: Project, d: StateDelta, ids: set[str]) -> tuple[list[TrailEchoChange], dict[str, CharTrail]]:
    known = {t.id: t for t in live(p)}
    last: dict[tuple[str, str], TrailEchoChange] = {}
    for x in d.trail_echoes:
        meaning = x.meaning.strip()
        t = known.get(x.trail)
        if t is None or t.episode >= d.episode or x.character not in ids or not meaning:
            continue
        last[(x.trail, x.character)] = x.model_copy(update={"meaning": meaning, "conflict": x.conflict.strip()})
    rows = sorted(last.values(), key=lambda x: _echo_group(x, known[x.trail]))  # 안정 정렬
    return rows[:MAX_ECHOES], known


def clean_delta(p: Project, d: StateDelta) -> list:
    """정리 훅 (features.CLEAN). 없는 인물 · 빈 라벨 · 빈 뜻 줄과 본문에 없는 구절을 거른다.
    경고는 다시 꺼냄의 conflict 에서만 낸다: ('… 달라요: 어긋남', 인물 id). 빼는 줄에는 경고를 내지 않는다."""
    ids = {c.id for c in p.characters} | {c.id for c in d.new_characters}
    try:
        text = p.episode(d.episode).text
    except KeyError:
        text = ""
    d.trails = _clean_trails(d, ids, text)
    d.trail_echoes, known = _clean_echoes(p, d, ids)
    return [(f"'{known[x.trail].label}' 다시 꺼냄이 앞 화와 달라요: {x.conflict}", x.character) for x in d.trail_echoes if x.conflict]


def apply_delta(p: Project, d: StateDelta) -> None:
    """반영 훅 (features.APPLY_LAST). d.trails 를 d.episode 화의 CharTrail 로, d.trail_echoes 를 그 자취의 echoes 로 쌓는다.
    없는 인물 · 없는 자취인 줄은 건너뛴다. 같은 화 · 같은 인물의 다시 꺼냄은 뜻만 바꾼다."""
    ids = {c.id for c in p.characters}
    for x in d.trails:
        if x.character not in ids:
            continue
        p.trails.append(CharTrail(id=next_id(p, d.episode), character=x.character, episode=d.episode, kind=x.kind, label=x.label,
                                  quote=x.quote, witnesses=[w for w in x.witnesses if w in ids and w != x.character]))
    by_id = {t.id: t for t in p.trails}
    for x in d.trail_echoes:
        t = by_id.get(x.trail)
        if t is None or x.character not in ids:
            continue
        old = next((e for e in t.echoes if e.episode == d.episode and e.character == x.character), None)
        if old is not None:
            old.meaning = x.meaning
        else:
            t.echoes.append(TrailEcho(episode=d.episode, character=x.character, meaning=x.meaning))
