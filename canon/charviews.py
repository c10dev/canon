"""보는 눈: 한 인물이 다른 인물을 어떻게 보는지, 본문에 드러난 평가를 화마다 쌓은 기록 (Project.views, CharView).

채우는 길은 상태 변경안의 views 다 (docs/trail 일감 8-2). 작가가 승인한 것만 쌓인다.
기본으로 체크하고 hold 하지 않는다: 자동 집필 · run -y 도 반영한다 (본문에 드러난 일의 기록이라서, 관계 사건과 같다).
되돌리기(features.REVERT_LAST)와 다시 짜기(reshape)가 n화 뒤 줄과 지워진 인물의 줄을 지운다.
basis 에서는 없는 자취 id 만 뺀다(줄은 남긴다).
LLM 을 부르지 않는다.
"""
from __future__ import annotations

from . import context, trails
from .schema import CharView, Project, StateDelta, ViewChange

MAX_PER_EPISODE = 4  # 한 화에 받는 보는 눈 줄 수. 넘으면 앞의 것만


def live(p: Project) -> list[CharView]:
    """보는 사람과 대상이 모두 p.characters 에 있는 줄만, 저장 차례 그대로.
    basis 에서 살아 있는 자취에 없는 id 는 뺀 사본이다. p.views 는 바꾸지 않는다."""
    ids = {c.id for c in p.characters}
    alive = {t.id for t in trails.live(p)}
    out = []
    for v in p.views:
        if v.viewer in ids and v.target in ids:
            basis = [b for b in v.basis if b in alive]
            out.append(v if len(basis) == len(v.basis) else v.model_copy(update={"basis": basis}))
    return out


def revert(p: Project, n: int) -> None:
    """되돌리기 훅. n화 뒤 줄과, 보는 사람 · 대상이 없는 인물인 줄을 지운다. 남은 줄의 basis 에서는 p.trails 에 없는 id 를 뺀다."""
    ids = {c.id for c in p.characters}
    tids = {t.id for t in p.trails}
    p.views = [v for v in p.views if v.episode <= n and v.viewer in ids and v.target in ids]
    for v in p.views:
        v.basis = [b for b in v.basis if b in tids]


def latest(p: Project) -> dict[tuple[str, str], CharView]:
    """방향 쌍(보는 사람, 대상)마다 가장 최근 줄. 화가 큰 것이 이기고, 같은 화면 뒤에 저장된 것이 이긴다."""
    out: dict[tuple[str, str], CharView] = {}
    for v in live(p):
        cur = out.get((v.viewer, v.target))
        if cur is None or v.episode >= cur.episode:
            out[(v.viewer, v.target)] = v
    return out


def state_block(p: Project, ids: set[str] | None) -> str:
    """상태 변경안 요청에 넣는 지금 보는 눈. ids 안의 두 인물 사이 방향 쌍마다 가장 최근 줄, 최근 화가 먼저. 없으면 빈 글."""
    name = {c.id: c.name for c in p.characters}
    rows = [v for v in latest(p).values() if ids is None or (v.viewer in ids and v.target in ids)]
    rows.sort(key=lambda v: -v.episode)  # 안정 정렬이라 같은 화는 저장 차례 그대로
    lines = [f"- {name.get(v.viewer, v.viewer)} → {name.get(v.target, v.target)}: {v.episode}화 '{v.verdict}'"
             + (f" (겉으로는 '{v.surface}')" if v.surface else "") for v in rows]
    keep, cut = context.fit_lines(lines, context.BUDGET["plan_views"])
    if not keep:
        return ""
    return "\n[지금 보는 눈 (인물이 상대를 어떻게 보는지, 가장 최근 것)]\n" + "\n".join(keep) + (f"\n(그 밖 {cut}줄 생략)" if cut else "")


def plan_lines(p: Project, ids: set[str] | None) -> tuple[list[str], list[str]]:
    """기획 요청에 넣는 보는 눈 줄. 방향 쌍마다 첫 평가 + 최근 3개의 한 줄.
    쌍 차례는 주역끼리가 먼저, 그 안에서 마지막 평가의 화가 큰 쌍이 먼저. 예산을 넘는 쌍부터 뺀다. (넣을 줄, 뺀 쌍 이름)"""
    name = {c.id: c.name for c in p.characters}
    core = context.core_ids(p)
    pairs: dict[tuple[str, str], list[CharView]] = {}
    for v in live(p):
        if ids is None or (v.viewer in ids and v.target in ids):
            pairs.setdefault((v.viewer, v.target), []).append(v)
    order = sorted(pairs, key=lambda k: (not (k[0] in core and k[1] in core), -max(v.episode for v in pairs[k]), k[0], k[1]))
    keep: list[str] = []
    cut: list[str] = []
    used = 0
    for key in order:
        rows = sorted(pairs[key], key=lambda v: v.episode)  # 안정 정렬이라 같은 화는 저장 차례 그대로
        if len(rows) > 3:
            rows = [rows[0]] + rows[-3:]
        who = f"{name.get(key[0], key[0])} → {name.get(key[1], key[1])}"
        line = f"{who}: " + " / ".join(f"{v.episode}화 '{v.verdict}'" + (f" (겉으로는 '{v.surface}')" if v.surface else "") for v in rows)
        if used + len(line) + 1 > context.BUDGET["plan_views"]:
            cut.append(who)
            continue
        keep.append(line)
        used += len(line) + 1
    return keep, cut


def plan_block(p: Project, ids: set[str] | None) -> str:
    """기획 요청(화별 플롯 · 다음 아크 · 플롯 대화 · 단편 플롯)에 넣는 보는 눈 블록. 걸린 쌍이 없으면 빈 글."""
    keep, cut = plan_lines(p, ids)
    if not keep:
        return ""
    return ("\n[인물이 서로를 보는 눈 (본문에 드러난 평가의 흐름. 앞이 오래된 것)]\n" + "\n".join(keep)
            + (f"\n(그 밖 {len(cut)}쌍 생략)" if cut else ""))


def state_rule(p: Project) -> str:
    """상태 변경안 규칙 한 줄. 늘 붙는다."""
    return ("\n- views 에는 이번 화 본문에서 한 인물이 다른 인물을 어떻게 보는지(평가)가 새로 드러나거나 바뀐 방향만 넣습니다. "
            "viewer 가 보는 인물, target 이 대상이고 방향마다 따로 적습니다. "
            "verdict 에는 보는 인물이 속말 · 대사에서 쓰는 낱말을 살려 30자 안팎으로 적습니다(예: '말만 번지르르한 사람', '날 해칠 생각은 없는 사람'). "
            "겉으로 다르게 말하면 surface 에 그 말을 적고, 같으면 비웁니다. "
            "본문의 속말 · 대사 · 행동에 드러난 것만 적고 시점 밖 인물의 속을 짐작하지 않습니다. "
            "[지금 보는 눈]과 같은 평가가 이어지면 적지 않습니다. 대부분의 화에는 비어 있습니다.")


def clean_delta(p: Project, d: StateDelta) -> list[str]:
    """정리 훅 (features.CLEAN). 있는 인물 사이의 서로 다른 두 인물, 빈 verdict 가 아닌 줄만 남긴다. 경고 없이 조용히 거른다."""
    ids = {c.id for c in p.characters} | {c.id for c in d.new_characters}
    cur = latest(p)
    last: dict[tuple[str, str], ViewChange] = {}
    for x in d.views:
        verdict, surface = x.verdict.strip(), x.surface.strip()
        if x.viewer == x.target or x.viewer not in ids or x.target not in ids or not verdict:
            continue
        last[(x.viewer, x.target)] = x.model_copy(update={"verdict": verdict, "surface": surface})  # 같은 방향은 뒤의 것만
    keep = []
    for key, x in last.items():
        old = cur.get(key)
        if old is not None and old.verdict == x.verdict and old.surface == x.surface:
            continue
        keep.append(x)
    d.views = keep[:MAX_PER_EPISODE]
    return []


def apply_delta(p: Project, d: StateDelta) -> None:
    """반영 훅 (features.APPLY_LAST). d.views 를 d.episode 화의 CharView 로 쌓는다. 없는 인물이거나 최근 평가와 같은 줄은 건너뛴다."""
    ids = {c.id for c in p.characters}
    for x in d.views:
        if x.viewer not in ids or x.target not in ids:
            continue
        old = latest(p).get((x.viewer, x.target))
        if old is not None and old.verdict == x.verdict and old.surface == x.surface:
            continue
        p.views.append(CharView(viewer=x.viewer, target=x.target, episode=d.episode, verdict=x.verdict, surface=x.surface))
