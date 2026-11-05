"""지금 차림(CharacterState.attire) 점검: 상태 변경안의 차림에 '가방', '옷'처럼 종류를 모르는 물건이 있으면 경고한다. LLM 호출 없음.

'가방'만 적으면 다음 화가 백팩으로도 핸드백으로도 쓸 수 있어 화 사이에 차림이 어긋난다. 규칙 글은 prompts.ATTIRE_STATE_RULE 이다.
색 · 재질('검은 가죽 가방')은 종류가 아니라 경고하고, 쓰임('서류 가방')이나 메는 자리('등에 멘 가방')가 있으면 넘어간다.
"""
from __future__ import annotations

import re

from .schema import Project, StateDelta

# 뭉뚱그린 이름 → 화면에 보일 종류 예시
VAGUE = {
    "가방": "백팩 · 숄더백 · 핸드백 · 크로스백 · 토트백",
    "옷": "셔츠 · 원피스 · 교복 · 정장",
    "겉옷": "코트 · 패딩 · 재킷",
    "신발": "운동화 · 구두 · 부츠",
}
# 이 말이 바로 앞에 오면 종류를 말한 것으로 본다 ('서류 가방', '등산 가방')
KIND_WORDS = ("서류", "노트북", "등산", "여행", "학교", "학생", "카메라", "기저귀", "왕진", "의료", "공구", "허리", "어깨", "보스턴", "더플", "스포츠", "운동")
# 가방이 몸 어디에 있는지 말하면 메는 방식은 정해진다
CARRY = re.compile(r"등에|어깨|손에|왼손|오른손|팔에|옆구리|허리에|크로스|메고|멘|멤|든 |들고")

_SPLIT = re.compile(r"[,，·/]|\s및\s")
_PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]")


def vague(text: str) -> list[str]:
    """차림 글에서 종류를 모르는 물건 조각. 조각마다 원문 그대로 돌려준다."""
    out = []
    for raw in _SPLIT.split(text or ""):
        raw = raw.strip()
        words = _PAREN.sub(" ", raw).split()  # 괄호 안 말('(지퍼 고장)')은 이름이 아니다
        if not words or words[-1] not in VAGUE:  # '책가방', '잠옷' 처럼 붙은 말은 종류다
            continue
        if len(words) > 1 and words[-2] in KIND_WORDS:
            continue
        if words[-1] == "가방" and CARRY.search(raw):  # 괄호 안 '(등에 멤)'도 메는 자리다
            continue
        out.append(raw)
    return out


def clean_delta(p: Project, d: StateDelta) -> list[tuple[str, str]]:
    """상태 변경안 정리 훅(features.CLEAN): (경고 글, 인물 id). 상태 승인 화면이 그 인물 줄 아래에 붙인다."""
    names = {c.id: c.name or c.id for c in p.characters} | {c.id: c.name or c.id for c in d.new_characters}
    out = []
    for u in d.character_updates:
        for part in vague(u.attire):
            head = _PAREN.sub(" ", part).split()[-1]
            out.append((f"{names.get(u.character_id, u.character_id)}의 차림 '{part}'은 무슨 {head}인지 몰라요. "
                        f"{VAGUE[head]}처럼 종류를 적어 주세요. 종류가 없으면 다음 화가 다른 {head}로 쓸 수 있어요.", u.character_id))
    return out
