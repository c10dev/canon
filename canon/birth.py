"""무작위 출생과 새 세계: 플레이 모드에서 세계의 무작위 인물로 태어나거나, 장르 · 한 줄로 새 세계를 만든다.

굴리는 값(원형 · 상처 · 말투 · 비틀기 · 이름 · 태어난 곳)은 코드가 시드로 정하고(roll, archetypes.roll · naming 재사용),
AI 는 그 값에 맞춰 배경만 채운다(sketch). 같은 시드면 같은 출생이다.
새 세계는 설정 제안(pipeline.suggest_setup)으로 만든 일반 작품이다.

이 파일은 틀만 둔 처음 판이다. 무작위 출생 작업이 채운다.
"""
from __future__ import annotations

from .llm import LLM
from .schema import Birth, BirthSketch, Character, Project


def roll(p: Project, seed: int, gender: str = "", age: str = "") -> Birth:
    """p 세계에서 시드로 출생을 굴린다. LLM 호출 없음."""
    raise NotImplementedError


def sketch(llm: LLM, p: Project, b: Birth) -> BirthSketch:
    """굴린 값에 맞춰 AI 가 배경을 채운다 (prompts.birth_prompt)."""
    raise NotImplementedError


def to_character(p: Project, b: Birth, s: BirthSketch) -> Character:
    """플레이어 인물로 쓸 Character. id 는 세계 인물과 겹치지 않게 짓는다."""
    raise NotImplementedError


def new_world(llm: LLM, name: str, genre_ids: list[str], logline: str, adult: bool = False) -> Project:
    """장르와 한 줄로 새 세계 작품을 만들어 name 폴더에 저장한다 (pipeline.suggest_setup)."""
    raise NotImplementedError
