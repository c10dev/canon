"""화별 스토리보드 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import BoardHandover, BoardScene, BoardStat, BoardTime, BoardWarning, StatValue, StoryboardDraft

CONFLICT = "[어긋남]"  # 이번 화 플롯 글에 이 표시가 있으면 이번 화 플롯 · 상태 어긋남 경고를 낸다 (자동 집필 멈춤 시험)


@responds(StoryboardDraft)
def _board(prompt: str, hint: dict) -> StoryboardDraft:
    """hint: episode, events(플롯 사건 수), characters(플롯 인물 id), stats(상태창 인물 → 항목 이름).
    사건마다 장면 하나(7개까지, 남는 사건은 마지막 장면), 상태창 인물은 첫 항목을 마지막 장면에서 1 줄인다."""
    k = max(int(hint.get("events") or 3), 1)
    n_scenes = min(k, 7)
    cast = list(hint.get("characters") or [])
    scenes = [BoardScene(place="바닷가 마을", spot="선착장", time="새벽" if i == 0 else "아침", present=cast,
                         events=[i + 1] if i < n_scenes - 1 else list(range(i + 1, k + 1)),
                         goal=f"장면 {i + 1}의 목표", turn=f"장면 {i + 1}의 전환", end_state=f"장면 {i + 1}이 끝난 자리")
              for i in range(n_scenes)]
    stats = [BoardStat(character_id=cid, scene=n_scenes, changes=[StatValue(name=names[0], value="-1")], window=True)
             for cid, names in (hint.get("stats") or {}).items() if names]
    warnings = [BoardWarning(kind="next_plot", target="next", field="events[1]", text="다음 화 플롯이 기대는 것", resolution="이번 화에서 건드리지 않아요")]
    if CONFLICT in prompt.split("# 이번 화 플롯")[-1]:  # 다음 화 플롯에 있는 표시는 세지 않는다
        warnings.insert(0, BoardWarning(kind="plot_vs_state", field="events[1]", text="플롯 수치가 지금 상태에서 닿을 수 없어요",
                                        resolution="지금 상태 값을 따라요"))
    return StoryboardDraft(
        scenes=scenes, time=BoardTime(after=0, part="새벽", days=1, end_part="아침"), stats=stats,
        stat_basis=["직전 화 끝 값에서 셈"] if stats else [],
        handover=[BoardHandover(kind="장면", text="직전 화 마지막 장면에서 이어진다")],
        protect=["다음 화 첫 사건의 전제를 깨지 않는다"], warnings=warnings)
