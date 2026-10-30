"""장면 연출 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다.
계획 초안은 첫 인물이 소파 앞으로 걸어가는 박자 하나, 본문 뽑기는 첫 문장 박자 하나다. 규칙 판정에 걸리지 않는다.
빈 방 틀의 방이면 계획 초안은 '탁자' 기준점을 문 앞에 더하자고 하고 첫 인물이 그 앞으로 간다 (기준점 제안 화면 확인용).
검수 시험(hint plants)이면 첫 사건에서 심은 문장마다 손이 닿지 않는 접촉 박자를 더해 거리 규칙(reach)에 걸리게 한다."""
from __future__ import annotations

import re

from . import stage
from .mock import responds
from .schema import DraftAnchor, DraftBeat, DraftBody, DraftContact, StageDraft


def _names(prompt: str) -> list[str]:
    block = prompt.split("[등장 인물]", 1)[1].split("\n\n", 1)[0] if "[등장 인물]" in prompt else ""
    return re.findall(r"^- (.+?) \(", block, re.M)


@responds(StageDraft)
def _stage(prompt: str, hint: dict) -> StageDraft:
    room = hint.get("room")
    anchors = [a["name"] for a in room["anchors"]] if room else [x[0] for x in stage.ROOMS["living"][3]]
    names = _names(prompt)
    door = next((a for a in anchors if "문" in a), anchors[0] if anchors else "")
    far = [a for a in anchors if a != door] or [door]
    start = [DraftBody(name=x, at_ref=door, at_rel="front", posture="stand", facing="", left="빈손" if hint.get("role") == "plan" else "",
                       right="빈손" if hint.get("role") == "plan" else "") for x in names]
    d = StageDraft(room="" if room else "living", cast=names, start=start, beats=[], new_anchors=[])
    if hint.get("role") != "text":
        if room and room.get("template") == "empty" and "탁자" not in anchors:
            d.new_anchors = [DraftAnchor(name="탁자", kind="table", near=door, rel="front"),
                             DraftAnchor(name="탁자 서랍", kind="other", near="탁자", rel="front", part=True)]
            far = ["탁자"]
        if names:
            d.beats.append(DraftBeat(note="첫 인물이 자리를 옮긴다", bodies=[DraftBody(name=names[0], at_ref=far[0], at_rel="front", posture="walk")]))
        return d
    sents = [x.strip() for x in re.findall(r"[^.!?\n]+[.!?]", hint.get("text", "")) if len(x.strip()) > 4]
    if sents and names:
        d.beats.append(DraftBeat(quote=sents[0], note="첫 문장", bodies=[DraftBody(name=names[0], facing=door)]))
    if hint.get("event") == 0 and len(names) > 1 and len(far) > 1:
        for x in hint.get("plants", []):
            if x in hint.get("text", ""):  # 두 사람이 방 양쪽에 선 채 손이 닿는다
                d.beats.append(DraftBeat(quote=x.strip(), bodies=[
                    DraftBody(name=names[0], at_ref=far[0], at_rel="front", contacts=[DraftContact(by="right", to=names[1], part="shoulder_l", act="hold")]),
                    DraftBody(name=names[1], at_ref=far[-1], at_rel="front")]))
    return d
