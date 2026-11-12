"""지시 연습 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import DrillFacts, DrillGap, DrillInvented, DrillLineVerdict, DrillPerson, DrillReview

_LAYER = {"change": "change", "avoid": "ban", "manner": "manner", "events": "event"}


@responds(DrillFacts)
def _facts(prompt: str, hint: dict) -> DrillFacts:
    """인물 둘 · 속사정 하나 · 일어나는 일 넷에 더해 정리가 빼는지 볼 것: 이름 없는 인물, 빈 줄, 원문 문장을 그대로 옮긴 줄."""
    source = " ".join((hint.get("source") or "").split())
    return DrillFacts(people=[DrillPerson(name="서연", note="가게에 처음 온 손님"), DrillPerson(name="도윤", note="야간 근무자"), DrillPerson(name=" ", note="빠질 인물")],
                      pov="서연", place="골목 끝 가게", time="밤", before="서연이 가게 문을 열고 들어온 참이다.",
                      inner=["서연은 물건을 사러 온 것이 아니다", " ", source[10:45]],
                      events=["서연이 도윤에게 말을 건다", "도윤이 짧게 대답한다", " ", "서연이 물러서지 않고 다시 묻는다", "도윤이 자리를 옮긴다", source[:30]])


@responds(DrillReview)
def _review(prompt: str, hint: dict) -> DrillReview:
    """줄마다 차례로 반영됨(진짜 인용) · 과하게 풀림(본문에 없는 인용: 판정 못 함이 된다) · 무시됨을 돌려 준다.
    없는 줄 번호 하나, 지어낸 사실 둘(진짜 인용 · 없는 인용), 놓친 것 둘(원문 인용 · 없는 인용)을 더해 정리가 빼는지 본다."""
    lines = hint.get("lines") or []
    with_text, bare_text, source = (hint.get(k) or "" for k in ("with_text", "bare_text", "source"))
    out = []
    for i, x in enumerate(lines):
        layer = _LAYER.get(x["box"], "background")
        if i % 3 == 0:
            out.append(DrillLineVerdict(no=x["no"], layer=layer, result="applied", quote=with_text[-14:], bare_quote=bare_text[:10], in_bare=False,
                                        why="지시 있는 판에만 있어요"))
        elif i % 3 == 1:
            out.append(DrillLineVerdict(no=x["no"], layer=layer, result="overdone", quote="본문에 없는 지어낸 인용", in_bare=False, same_as=lines[0]["no"],
                                        why="앞줄과 같은 말이에요"))
        else:
            out.append(DrillLineVerdict(no=x["no"], layer=layer, result="ignored", in_bare=True, why="무엇에서 무엇으로 바뀌는지 없어요"))
    out.append(DrillLineVerdict(no=99, layer="manner", result="applied", quote=with_text[:10], why="없는 줄"))
    return DrillReview(lines=out,
                       invented=[DrillInvented(side="with", quote=with_text[:12], what="지시에 없는 직업"),
                                 DrillInvented(side="bare", quote="어디에도 없는 문장이다", what="빠질 것")],
                       gaps=[DrillGap(what="상대가 겁먹은 것을 알아채는 대목", quote=source[:16]), DrillGap(what="빠질 것", quote="원문에 없는 인용이다")])
