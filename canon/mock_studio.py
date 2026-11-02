"""문단 연습장 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

import re

from .mock import responds
from .schema import AnatomyLine, ParagraphAnatomy, ReaderCheck, ReaderGap, SceneVariant, SceneVariants, StudioCandidate, StudioDraft, VariantPerson


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


@responds(ParagraphAnatomy)
def _anatomy(prompt: str, hint: dict) -> ParagraphAnatomy:
    """문장마다 박자 하나 (깔기 → 계기 → 초점 → 가정 → 반응 → 끊기 차례로 돈다). 본보기에 없는 문장 하나를 더해 정리가 빼는지 본다."""
    model = hint.get("model") or ""
    sents = [x for x in re.split(r"(?<=[.!?”])\s+", model.strip()) if x.strip()]
    order = ["setup", "trigger", "focus", "imagine", "react", "cut"]
    lines = [AnatomyLine(quote=x.strip()[:15], beat=order[i % len(order)], note=f"{i + 1}번째 문장이 하는 일") for i, x in enumerate(sents)]
    lines.append(AnatomyLine(quote="본보기에 없는 지어낸 문장", beat="cut", note="빠져야 할 줄"))
    return ParagraphAnatomy(lines=lines, withhold=" 인물의 속마음 ", sense="보는 것 → 촉감", reader="다음에 일어날 일")


@responds(SceneVariants)
def _variants(prompt: str, hint: dict) -> SceneVariants:
    """k 개 상황에 더해 정리가 빼는지 볼 것: 지금 카드와 같은 상황, 첫 상황과 겹치는 상황, 일이 빈 상황."""
    k = int(hint.get("k") or 4)
    places = ["새벽 시장", "야간 버스", "도서관 서고", "빨래방", "옥상 정원"]
    out = [SceneVariant(place=places[i % len(places)], time="밤", action=f"{i + 1}번 상황의 일",
                        people=[VariantPerson(name=f"인물{i + 1}", note="처지 한 줄"), VariantPerson(name=" ", note="")],
                        pov=f"인물{i + 1}" if i else "없는 사람", why="계기 · 초점 · 가정") for i in range(k)]
    out += [SceneVariant(place=hint.get("place") or "", time="", action=hint.get("action") or "", people=[], pov="", why="지금 카드와 같음"),
            out[0].model_copy(), SceneVariant(place="빈 일", time="", action=" ", people=[], pov="", why="")]
    return SceneVariants(variants=out)


@responds(ReaderCheck)
def _reader(prompt: str, hint: dict) -> ReaderCheck:
    """적힌 것(진짜 인용), 적혔다는데 인용이 본문에 없는 것, 독자가 채울 것."""
    text = (hint.get("text") or "").strip()
    return ReaderCheck(gaps=[ReaderGap(imagined="장소의 분위기", written=True, quote=text[:8]),
                             ReaderGap(imagined="인물의 표정", written=True, quote="본문에 없는 인용"),
                             ReaderGap(imagined="다음에 일어날 일", written=False, quote="버려질 인용"),
                             ReaderGap(imagined=" ", written=False, quote="")])
