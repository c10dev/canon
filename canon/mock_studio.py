"""문단 연습장 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import StudioCandidate, StudioDraft


@responds(StudioDraft)
def _draft(prompt: str, hint: dict) -> StudioDraft:
    """n 개 안에 더해 정리가 빼는지 볼 안 셋: 빈 안, 첫 안과 같은 안, 굵은 글씨가 붙은 안(떼고 남긴다).
    첫 안은 감정 이름과 상투 표현을 넣어 문단 지표가 잡는지 본다."""
    n = int(hint.get("n") or 3)
    who = (hint.get("names") or ["그"])[0]
    what = hint.get("action") or "창밖을 본다"
    texts = [f"{who}은 불안을 느꼈다. 숨을 내쉬었다. {what}.",
             f"\"늦었네.\" {who}이 문틈으로 말했다. 빗소리가 창을 두드렸다. 그는 우산을 접었다. {what}.",
             f"빗물이 처마 끝에서 떨어졌다. {who}은 젖은 소매를 비틀어 짰다. 멀리서 개가 짖었다. {what}.",
             f"찻잔이 식어 갔다. {who}은 손잡이를 돌려 잡았다. {what}."]
    out = [StudioCandidate(text=texts[i % len(texts)], note=f"{i + 1}번 방향") for i in range(n)]
    out += [StudioCandidate(text="  ", note="빈 안"), StudioCandidate(text=texts[0], note="겹치는 안"),
            StudioCandidate(text=f"**{who}**은 문을 닫았다.", note="굵은 글씨")]
    return StudioDraft(candidates=out)
