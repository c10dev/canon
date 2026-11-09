"""초반 1~3화: 지표, 흡입력 판정, 여는 방식 여러 안. canon/pipeline.py 에서 옮겼다.

pipeline 이 맨 끝에서 이 모듈을 불러 여기서 정한 이름(EXPORTS)을 pipeline 에도 둔다 (pipeline.<이름> 으로 부르는 코드가 그대로 돈다)."""
from __future__ import annotations

from . import elements, metrics, prompts, storylines
from .llm import LLM
from .schema import Episode, EpisodePlot, HookReport, OpeningPlots, Project
from .pipeline import (  # pipeline 의 공용 도우미
    LOCKED,
    _now,
    style_baseline,
    sync_candidates,
    text_basis,
    write_episode,
)


def hero_name(p: Project) -> str:
    """주인공 이름: 역할에 '주인공'이 들어간 인물, 없으면 첫 주역."""
    lead = next((c for c in p.characters if "주인공" in c.role), None) or next(
        (c for c in p.characters if c.tier == "main"), None)
    return lead.name if lead else ""


def lore_terms(p: Project) -> list[str]:
    """설정어: 세계관 장소 이름('등대: 설명' 이면 '등대')과 이야기 요소 이름 · 다른 이름."""
    import re

    out = [re.split(r"[:(（\-–—,]", x, maxsplit=1)[0].strip() for x in p.world.locations]
    for el in p.elements:
        out += [el.name, *el.aliases]
    return [x for x in dict.fromkeys(out) if len(x) >= 2]


def opening_metrics(p: Project, n: int, text: str | None = None) -> tuple[metrics.OpeningMetrics, list[str]]:
    """1~3화 초반 지표와 경고. text 를 주면 그 글(비교본)을 잰다."""
    body = p.episode(n).text if text is None else text
    hero = hero_name(p)
    m = metrics.measure_opening(body, [c.name for c in p.characters], hero, lore_terms(p))
    return m, metrics.opening_warnings(m, n, style_baseline(p).dialogue_ratio or None, hero)




def check_hook(llm: LLM, p: Project, n: int, text: str | None = None) -> HookReport:
    """1~3화 흡입력 판정. 저장하지 않는다. text 를 주면 그 글(비교본)을 판정한다."""
    if not prompts.is_opening(n):
        raise ValueError(f"흡입력 판정은 1~{prompts.OPENING_EPISODES}화만 해요")
    body = p.episode(n).text if text is None else text
    if not body.strip():
        raise ValueError(f"{n}화 본문이 없어요")
    rep = llm.json(prompts.SYSTEM_HOOK, prompts.hook_prompt(p, n, body), HookReport,
                   hint={"episode": n, "text": body})
    return clean_hook(rep, n, body)


def clean_hook(rep: HookReport, n: int, text: str) -> HookReport:
    """본문에서 찾지 못한 인용은 지우고 점수를 1로 내린다 (LLM 판정자가 근거 없이 후하게 주는 것을 막는다).
    같은 항목이 둘이면 앞의 것만, 빠진 항목은 그대로 둔다. 전제 문장의 위치를 잰다."""
    rep.episode = n
    seen, items = set(), []
    for it in rep.items:
        if it.aspect in seen:
            continue
        seen.add(it.aspect)
        it.score = min(5, max(1, it.score))
        if it.quote.strip() and not elements.find(text, it.quote):
            it.quote, it.score = "", 1
            it.note = (it.note + " (근거 문장을 본문에서 찾지 못해 1점으로 내림)").strip()
        items.append(it)
    rep.items = items
    hit = elements.find(text, rep.premise_quote) if rep.premise_quote.strip() else None
    if rep.premise_quote.strip() and not hit:
        rep.premise_quote = ""
    rep.premise_at = hit[0] if hit else -1
    rep.basis, rep.checked_at = text_basis(text), _now()
    return rep


def apply_hook(p: Project, rep: HookReport) -> None:
    """판정은 참고용이라 승인 없이 화에 붙인다. 다시 판정하면 덮어쓴다."""
    p.episode(rep.episode).hook = rep


def hook_stale(p: Project, n: int) -> bool:
    e = p.episode(n)
    return bool(e.hook) and e.hook.basis != text_basis(e.text)


def _approaches(approaches: list[str] | None) -> list[str]:
    picked = [a for a in dict.fromkeys(approaches or prompts.DEFAULT_APPROACHES) if a in prompts.OPENING_APPROACHES]
    if not 2 <= len(picked) <= 4:
        raise ValueError(f"여는 방식은 2~4개를 고르세요: {', '.join(prompts.OPENING_APPROACHES)}")
    return picked


def suggest_openings(llm: LLM, p: Project, n: int, approaches: list[str] | None = None) -> OpeningPlots:
    """n화(1~3) 플롯을 여는 방식만 달리한 여러 안. 저장하지 않는다."""
    if not prompts.is_opening(n):
        raise ValueError(f"여는 방식 비교는 1~{prompts.OPENING_EPISODES}화만 해요")
    cur = next((e for e in p.episodes if e.plot.number == n), None)
    if cur and cur.status in LOCKED:
        raise ValueError(f"{n}화는 본문이 있어 플롯을 바꿀 수 없어요")
    if not p.beats() or not p.act_for(n):
        raise ValueError("다음 아크를 먼저 기획하세요" if p.serial else "기승전결 구조(arc)를 먼저 만드세요")
    ways = _approaches(approaches)
    out = llm.json(prompts.SYSTEM_PLANNER, prompts.opening_plots_prompt(p, n, ways), OpeningPlots,
                   hint={"episode": n, "approaches": ways, "act": p.act_for(n).name})
    return clean_openings(p, n, out, ways)


def clean_openings(p: Project, n: int, out: OpeningPlots, ways: list[str]) -> OpeningPlots:
    """요청한 방식만 한 번씩, 화 번호와 구간은 맞추고, 작가가 붙인 이야기 줄기는 지킨다."""
    cur = next((e for e in p.episodes if e.plot.number == n), None)
    act = p.act_for(n)
    keep, seen = [], set()
    for o in out.options:
        if o.approach not in ways or o.approach in seen:
            continue
        seen.add(o.approach)
        o.plot.number = n
        if act:
            o.plot.act = act.name
        if cur and (cur.plot.storyline or cur.plot.threads) and not (o.plot.storyline or o.plot.threads):
            o.plot.storyline, o.plot.threads = cur.plot.storyline, list(cur.plot.threads)
        keep.append(o)
    if not keep:
        raise ValueError("AI가 요청한 여는 방식으로 안을 내지 않았어요. 다시 시도하세요")
    out.options = keep
    return out


def apply_opening(p: Project, n: int, plot: EpisodePlot) -> None:
    """고른 안을 n화 플롯으로. 본문이 있는 화는 막고, 확정했던 화는 초안으로 돌린다 (플롯 대화 반영과 같은 규칙)."""
    if plot.number != n:
        raise ValueError(f"{n}화 플롯이 아니에요 ({plot.number}화)")
    by_no = {e.plot.number: e for e in p.episodes}
    cur = by_no.get(n)
    if cur and cur.status in LOCKED:
        raise ValueError(f"{n}화는 본문이 있어 플롯을 바꿀 수 없어요")
    act = p.act_for(n)
    if act:
        plot.act = act.name
    plot = plot.model_copy(deep=True)
    if cur:  # 여는 방식과 상관없는 칸은 작가가 정한 값을 지킨다: 시점, 서술 방식, 회수 복선, 넣어 둔 인물
        plot.pov = cur.plot.pov or plot.pov
        plot.pov_mode = cur.plot.pov_mode or plot.pov_mode
        plot.foreshadow_payoff = cur.plot.foreshadow_payoff or plot.foreshadow_payoff
        plot.characters = list(dict.fromkeys(cur.plot.characters + plot.characters))
    # 처음 고르기 전 플롯을 남겨 새로고침 뒤에도 되돌릴 수 있게 한다. 다른 안으로 다시 바꿔도 처음 것을 지킨다
    prev = (cur.opening_prev or cur.plot).model_copy(deep=True) if cur else None
    by_no[n] = Episode(plot=plot, opening_prev=prev, direction=cur.direction if cur else "")  # 작가 연출 지시는 안을 바꿔도 남긴다
    storylines.clean_plot(p, by_no[n])
    p.episodes = [by_no[k] for k in sorted(by_no)]
    sync_candidates(p)


def undo_opening(p: Project, n: int) -> None:
    """n화 플롯을 여는 방식 안을 처음 고르기 전으로 되돌린다. 화는 초안이 된다 (확정했던 화는 다시 확정한다)."""
    e = p.episode(n)
    if e.opening_prev is None:
        raise ValueError(f"{n}화는 여는 방식 안을 고르기 전 플롯이 남아 있지 않아요")
    if e.status in LOCKED:
        raise ValueError(f"{n}화는 본문이 있어 플롯을 바꿀 수 없어요")
    plot = e.opening_prev.model_copy(deep=True)
    act = p.act_for(n)
    if act:
        plot.act = act.name
    p.episodes = [Episode(plot=plot, direction=x.direction) if x.plot.number == n else x for x in p.episodes]
    storylines.clean_plot(p, p.episode(n))
    sync_candidates(p)


def opening_drafts(llm: LLM, p: Project, n: int, approaches: list[str] | None = None) -> dict[str, str]:
    """n화(1~3) 본문을 여는 방식마다 하나씩 쓴다. 키는 방식 이름. 저장은 호출자가 한다 (research.save_compare)."""
    if not prompts.is_opening(n):
        raise ValueError(f"여는 방식 비교는 1~{prompts.OPENING_EPISODES}화만 해요")
    return {prompts.OPENING_APPROACHES[a][0]: write_episode(llm, p, n, a) for a in _approaches(approaches)}


EXPORTS = (
    "_approaches",
    "apply_hook",
    "apply_opening",
    "check_hook",
    "clean_hook",
    "clean_openings",
    "hero_name",
    "hook_stale",
    "lore_terms",
    "opening_drafts",
    "opening_metrics",
    "suggest_openings",
    "undo_opening",
)
