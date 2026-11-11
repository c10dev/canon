"""설계도 가짜 응답 (CANON_LLM=mock). BlueprintProposal · AbilityProposal · BlueprintPlanSet 을 mock.RESPONDERS 에 등록한다.
범위 첫 화 · 가운데 화에 이정표와 사다리 칸을 하나씩 내고, 정리(blueprint.clean_proposal)가 거르는 줄도 하나씩 섞는다."""
from __future__ import annotations

from .mock import responds
from .schema import AbilityCodexDraft, AbilityDraft, AbilityGrade, AbilityProposal, BlueprintEvidence, BlueprintPlanSet, BlueprintProposal, MilestoneDraft, PairDraft, RungDraft, SpotDraft


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


@responds(AbilityProposal)
def _r_abilities(prompt: str, hint: dict) -> AbilityProposal:
    """능력 일정 제안 (거꾸로 뽑기 · 짜기). 범위 첫 화 · 가운데 화에 한 줄씩 내고, 정리(blueprint.clean_abilities)가 거르는 줄을 섞는다:
    등급 꼬리를 이름에 붙인 줄, 같은 줄 되풀이, 다른 인물, 범위 밖. 도감 초안(blueprint.clean_codex)도 거르는 항목을 섞는다:
    등급 꼬리를 붙인 이름, 같은 이름 되풀이, 남은 줄이 없는 능력, 빈 등급."""
    start, end, cid = int(hint["start"]), int(hint["end"]), hint["character"]
    mid = (start + end) // 2
    return AbilityProposal(
        abilities=[AbilityDraft(character=cid, ability="은신", from_ep=start, to_ep=start, condition="첫 위기에서 눈뜬다",
                                evidence=[BlueprintEvidence(episode=start, quote="숨을 죽이자 기척이 사라진다"), BlueprintEvidence(episode=end + 5, quote="범위 밖 근거")]),
                   AbilityDraft(character=cid, ability="은신 Lv2", from_ep=mid, to_ep=end + 9, condition="밤 훈련"),
                   AbilityDraft(character=cid, ability="은신", grade="Lv2", from_ep=mid, to_ep=mid, condition="같은 줄 (정리가 뺀다)"),
                   AbilityDraft(character="nobody", ability="화염구", from_ep=start, to_ep=start, condition="다른 인물 (정리가 뺀다)"),
                   AbilityDraft(character=cid, ability="비행", from_ep=end + 3, to_ep=end + 3, condition="범위 밖 (정리가 뺀다)")],
        codex=[AbilityCodexDraft(name="은신 Lv1", stat="스킬", description="기척을 지운다", effect="잠시 남의 눈에 띄지 않는다", cost="움직이면 풀린다",
                                 grades=[AbilityGrade(grade="Lv2", effect="걸어도 풀리지 않는다"), AbilityGrade(grade=" ", effect="빈 등급 (정리가 뺀다)")]),
               AbilityCodexDraft(name="은신", effect="같은 이름 (정리가 뺀다)"),
               AbilityCodexDraft(name="비행", effect="줄이 없는 능력 (정리가 뺀다)")],
        reply="능력 일정 두 줄을 적었어요.",
    )


@responds(BlueprintPlanSet)
def _r_whole(prompt: str, hint: dict) -> BlueprintPlanSet:
    """작품 전체 짜기 (docs/blueprint/specs/11-whole.md 의 11b). 쌍마다 이정표 두 줄 · 칸 한 칸을 쌍 차례로 엇갈려 내고, 첫 쌍의 a 에 능력 한 줄을 낸다.
    정리(blueprint.clean_set)가 거르는 항목을 섞는다: 고르지 않은 쌍, 같은 쌍 두 번째 항목(합친다), 범위 밖 편성."""
    start, end, pairs = int(hint["start"]), int(hint["end"]), [tuple(x) for x in hint["pairs"]]
    step = max((end - start + 1) // max(len(pairs), 1), 1)
    out = []
    spots = []
    for i, (a, b) in enumerate(pairs):
        lo = min(start + i * step, end)
        hi = min(lo + step - 1, end)
        mid = (lo + hi) // 2
        ev = [BlueprintEvidence(episode=lo, quote="부 목표의 공략 차례")]
        out.append(PairDraft(a=a, b=b, milestones=[MilestoneDraft(source=b, target=a, from_ep=lo, to_ep=mid, stage="호감", label="마음이 기운다", evidence=ev),
                                                  MilestoneDraft(source=a, target=b, from_ep=mid, to_ep=hi, stage="신뢰", label="믿기 시작한다")],
                             rungs=[RungDraft(label="손 잡기", parts=["hand_r"], acts=["hold"], layer="맨살", lead=a, from_ep=mid, to_ep=mid)]))
        spots.append(SpotDraft(from_ep=lo, to_ep=hi, focus=[f"{a}~{b}", "nobody~x"], note="이 쌍이 나아간다"))
    if pairs:
        a, b = pairs[0]
        out.append(PairDraft(a=b, b=a, rungs=[RungDraft(label="같은 쌍 두 번째 항목 (합친다)", layer="옷 위", from_ep=start, to_ep=start)]))
        out.append(PairDraft(a=a, b="nobody", milestones=[MilestoneDraft(source=a, target="nobody", from_ep=start, to_ep=end, stage="적대", label="고르지 않은 쌍 (정리가 뺀다)")]))
    spots.append(SpotDraft(from_ep=end + 10, to_ep=end + 20, focus=[], note="범위 밖 (정리가 뺀다)"))
    abilities = [AbilityDraft(character=pairs[0][0], ability="마스터 어드민", grade="1단계", from_ep=start, to_ep=min(start + 5, end), condition="첫 해금")] if pairs else []
    codex = [AbilityCodexDraft(name="마스터 어드민", stat="권한", effect="비밀 계정을 연다")] if pairs else []
    return BlueprintPlanSet(spotlight=spots, pairs=out, abilities=abilities, codex=codex, reply=f"쌍 {len(pairs)}개를 차례로 엇갈려 놓았어요.")
