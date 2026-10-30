"""역설계 실험 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

import re
from collections import Counter

from .mock import responds
from .schema import RevCue, RevEpisodeDraft, RevHandover, RevLine, RevLineSet, RevPerson, RevQuote, RevScene, RevTime

FAKE_LINE = "원문에 없는 가짜 대사"  # 원문 확인(revlab.keep_lines)이 빼는지 보는 대사


def _source(prompt: str) -> str:
    """요청의 [원문] 칸."""
    body = prompt.split("\n# 원문 (", 1)[-1]
    return body.split("\n", 1)[-1].rsplit("\n\n위 [원문]", 1)[0]


def _names(text: str, known: list[str]) -> list[str]:
    """이미 나온 인물 + '…은/는 ' 앞에 두 번 넘게 나온 두세 글자 낱말. 없으면 '화자'."""
    found = [w for w, k in Counter(re.findall(r"([가-힣]{2,3})(?:은|는) ", text)).most_common() if k >= 2][:2]
    out = list(dict.fromkeys([*[x for x in known if x in text], *found]))
    return out or ["화자"]


@responds(RevEpisodeDraft)
def _episode(prompt: str, hint: dict) -> RevEpisodeDraft:
    """문단을 네 묶음으로 나눠 큐 넷(문단이 적으면 문단마다), 앞 절반은 장면 1 · 뒤는 장면 2. 시작 인용은 묶음 첫 문단의 앞 20자.
    원문의 첫 따옴표 대사를 둘째 큐 핵심 대사로, 마지막 큐에는 원문에 없는 가짜 대사를 함께 넣는다."""
    text = _source(prompt)
    paras = [x.strip() for x in re.split(r"\n\s*\n", text) if x.strip()]
    k = max(min(4, len(paras)), 1)
    groups = [paras[round(i * len(paras) / k):round((i + 1) * len(paras) / k)] for i in range(k)]
    names = _names(text, list(hint.get("names") or []))
    said = re.findall(r"[\"“]([^\"”\n]{2,40})[\"”]", text)
    cues = []
    for i, g in enumerate(groups):
        lines = [RevQuote(speaker=names[0], text=said[0])] if i == min(1, k - 1) and said else []
        if i == k - 1:
            lines.append(RevQuote(speaker=names[0], text=FAKE_LINE))
        fn = "T" if i == 0 else "D" if i == k - 1 else "S"
        cues.append(RevCue(start=g[0][:20] if g else "", scene=1 if i < (k + 1) // 2 else 2, function=fn, tension=min(2 + i, 5),
                           tempo={"T": "slow", "S": "mid", "D": "fast"}[fn], voice="dialogue" if lines and i < k - 1 else "action",
                           beat=f"큐 {i + 1}에서 바뀌는 일", lines=lines, exit=f"큐 {i + 1}이 끝난 자리"))
    n = int(hint.get("episode") or 1)
    scenes = [RevScene(place="바닷가 마을", spot="선착장" if s == 1 else "등대", time="새벽" if s == 1 else "아침", present=names,
                         events=[s], goal=f"장면 {s}의 목표", turn=f"장면 {s}의 전환", end_state=f"장면 {s}이 끝난 자리") for s in (1, 2)]
    return RevEpisodeDraft(
        title="", summary=f"{n}화에서 {names[0]}이 움직인다.", events=["첫 사건", "둘째 사건", "셋째 사건"],
        cast=[RevPerson(name=x, role="주인공" if j == 0 else "조연", speech="짧게 끊는 말투" if j == 0 else "") for j, x in enumerate(names)],
        emotional_shift="손을 멈춘다", ending_hook="문이 열린다", opening=paras[0][:30] if paras else "", time="",
        threads=["등대 사건"] + (["두 사람의 관계"] if n % 2 == 0 else []), scenes=scenes,
        board_time=RevTime(after=0, part="새벽", days=1, end_part="아침"),
        handover=[RevHandover(kind="장면", text="직전 화 끝 자리에서 이어진다")] if "# 직전 화 끝" in prompt else [],
        key="억눌린 불안", cadence="half", cues=cues)


@responds(RevLineSet)
def _lines(prompt: str, hint: dict) -> RevLineSet:
    """줄기 하나: 짝수 화를 따라가고 홀수 화(첫 화 빼고)에 끼어든다. 실험에 없는 99화도 넣는다 (정리가 빼는지 본다)."""
    eps = list(hint.get("episodes") or [])
    return RevLineSet(main="등대에서 사라진 사람을 찾을 수 있을까", lines=[
        RevLine(kind="서브플롯", title="두 사람의 관계", focus=["서윤"], goal="믿어도 될까",
                when="", episodes=[n for n in eps if n % 2 == 0] + [99], threads=[n for n in eps[1:] if n % 2 == 1], rejoin="")])
