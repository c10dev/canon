"""짧은 응답 거르기. 형식은 맞지만 칸이 거의 빈 LLM 응답을 알아보고 한 번만 다시 부른다 (pipeline.extract_state · analyze_style).
다시 부르는 호출도 llm.json 을 거쳐 백엔드가 사용량에 기록한다. 스레드를 띄우지 않는다."""
from __future__ import annotations

import logging
from typing import Callable, TypeVar

from .schema import StateDelta, StyleProfile

T = TypeVar("T")

# 상태 변경안의 주요 칸. 본문이 있는 화에서 이 칸이 모두 비면 짧은 응답으로 본다
STATE_KEYS = ("character_updates", "events", "relationship_updates", "secrets_added", "new_facts",
              "foreshadow_planted", "foreshadow_resolved", "foreshadow_clues", "new_characters", "new_places",
              "setting_changes", "address_changes", "trails", "trail_echoes", "views")
STATE_MIN_TEXT = 1500  # 본문(앞뒤 공백 뺀 글자 수)이 이보다 짧은 화는 짧은 응답으로 보지 않는다
STYLE_MIN_FILLED = 6   # 문체 프로필의 글 칸(str 칸 11개) 가운데 채운 칸이 이보다 적으면 짧은 응답
THIN_MARK = "[짧은 응답]"  # 상태 변경안 경고의 머리. 자동 집필은 이 경고가 있으면 멈춘다 (autorun.review_reasons)
STATE_WARNING = (f"{THIN_MARK} AI가 두 번 불러도 인물 상태 · 사건 · 사실 같은 칸을 하나도 채우지 않았어요. "
                 "빠진 것이 많을 수 있으니 다시 만들거나 직접 채워 주세요")


class ThinResponse(ValueError):
    """다시 불러도 응답이 짧다. ValueError 라 웹은 400 과 이 문구를 보인다 (web._bad_request)."""


def state_thin(d: StateDelta, text: str) -> bool:
    """본문이 STATE_MIN_TEXT 자 이상인데 STATE_KEYS 칸이 모두 비었으면 참."""
    return len(text.strip()) >= STATE_MIN_TEXT and not any(getattr(d, k, None) for k in STATE_KEYS)


def style_text_keys() -> list[str]:
    """StyleProfile 의 글(str) 칸 이름."""
    return [k for k, f in StyleProfile.model_fields.items() if f.annotation is str]


def style_filled(p: StyleProfile) -> int:
    """글 칸 가운데 비지 않은 칸 수."""
    return sum(1 for k in style_text_keys() if getattr(p, k).strip())


def style_thin(p: StyleProfile) -> bool:
    return style_filled(p) < STYLE_MIN_FILLED


def once_more(call: Callable[[], T], thin: Callable[[T], bool], what: str) -> tuple[T, bool]:
    """call() 결과가 thin 이면 한 번만 다시 부른다. (마지막 결과, 마지막 결과도 짧은지).
    다시 부를 때 logging 'canon' 에 경고 한 줄(what 을 넣어)을 남긴다."""
    out = call()
    if not thin(out):
        return out, False
    logging.getLogger("canon").warning("%s 응답이 짧아 한 번 다시 불러요", what)
    out = call()
    return out, thin(out)
