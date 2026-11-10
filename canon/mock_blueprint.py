"""설계도 거꾸로 뽑기 가짜 응답 (CANON_LLM=mock). BlueprintProposal 을 mock.RESPONDERS 에 등록한다.
범위 첫 화 · 가운데 화에 이정표와 사다리 칸을 하나씩 내고, 정리(blueprint.clean_proposal)가 거르는 줄도 하나씩 섞는다."""
from __future__ import annotations

from .mock import responds
from .schema import BlueprintEvidence, BlueprintProposal, MilestoneDraft, RungDraft


@responds(BlueprintProposal)
def _r_blueprint(prompt: str, hint: dict) -> BlueprintProposal:
    start, end, a, b = int(hint["start"]), int(hint["end"]), hint["a"], hint["b"]
    mid = (start + end) // 2
    ev = [BlueprintEvidence(episode=start, quote="두 사람이 처음 마주친다")]
    return BlueprintProposal(
        milestones=[MilestoneDraft(source=a, target=b, from_ep=start, to_ep=mid, stage="경계", label="상대를 경계한다", trigger="첫 만남", evidence=ev),
                    MilestoneDraft(source=b, target=a, from_ep=mid, to_ep=end, stage="호감", label="마음이 기운다", evidence=[]),
                    MilestoneDraft(source=a, target="nobody", from_ep=start, to_ep=end, stage="적대", label="쌍 밖 줄 (정리가 뺀다)")],
        rungs=[RungDraft(label="손등 스침", parts=["hand_r", "tail"], acts=["brush"], layer="옷 위", lead=a, from_ep=mid, to_ep=mid,
                         evidence=[BlueprintEvidence(episode=mid, quote="손등이 스친다"), BlueprintEvidence(episode=end + 5, quote="범위 밖 근거")]),
               RungDraft(label="범위 밖 칸 (정리가 뺀다)", from_ep=end + 3, to_ep=end + 3),
               RungDraft(label="손목 잡기", parts=["wrist_r"], acts=["hold"], lead="nobody", from_ep=start, to_ep=start)],
        reply="관계 이정표 두 줄과 접촉 사다리 두 칸을 뽑았어요.",
    )
