"""작품 밖 도구(역설계 실험 · 문단 연습장)가 저마다 단계 AI 를 고르는 규칙.

고르기(AIPick)는 셋 가운데 하나다: 단계 프리셋 id · 백엔드 + 모델(직접 고름) · 모두 비움(설정 화면의 단계 칸을 따름).
작품 밖이라 작품의 단계 프리셋은 보지 않는다. 설정의 AI 가 mock 이면 무엇을 골랐든 mock 이다. LLM 을 부르지 않는다.
"""
from __future__ import annotations

from .schema import AIPick

PROVIDERS = ("gemini", "claude", "claude-api", "local")  # 직접 고를 수 있는 백엔드 (mock 은 설정에서만)


def default_model(provider: str) -> str:
    """모델 칸을 비웠을 때 그 백엔드가 쓰는 모델 이름 (llm.make_llm 과 같은 기본값). 로컬은 서버가 정하면 빈 글."""
    from . import claude, settings

    if provider == "gemini":
        return settings.model()[0]
    if provider == "local":
        return settings.local_model()[0]
    if provider == "claude":
        return settings.claude_model()[0]
    if provider == "claude-api":
        return settings.claude_model()[0] or claude.DEFAULT_API_MODEL
    return ""


def choice(pick: AIPick, stage: str) -> dict:
    """stage 호출이 쓸 백엔드와 모델 {provider, model, source}. source: settings(설정을 따름) · preset · own(직접 고름) ·
    gone(고른 프리셋이 지워져 설정을 따름) · mock(설정이 mock 이면 모든 호출이 mock)."""
    from . import settings

    if settings.provider()[0] == "mock":
        return {"provider": "mock", "model": "", "source": "mock"}
    pre = settings.find_preset(pick.preset) if pick.preset else None
    if pre:
        return {"provider": settings.stage_provider(stage, pre)[0], "model": settings.stage_model(stage, pre)[0], "source": "preset"}
    if not pick.preset and pick.provider:
        return {"provider": pick.provider, "model": pick.model, "source": "own"}
    return {"provider": settings.stage_provider(stage, None)[0], "model": settings.stage_model(stage, None)[0],
            "source": "gone" if pick.preset else "settings"}


def make(pick: AIPick, stage: str):
    """고른 AI 로 LLM 을 만든다. 키가 없으면 여기서 바로 오류를 낸다 (웹은 호출 전에 부른다)."""
    from .llm import make_llm

    c = choice(pick, stage)
    llm = make_llm(c["provider"], c["model"] or None)
    llm.stage = stage  # type: ignore[attr-defined]  # 사용량 기록이 단계를 적는다
    return llm


def clean(preset: str = "", provider: str = "", model: str = "") -> AIPick:
    """화면에서 받은 고르기를 정리한다: preset 이 있으면 프리셋, 아니면 provider(+ model), 모두 비면 설정을 따름."""
    from . import settings

    preset, provider, model = preset.strip(), provider.strip().lower(), model.strip()
    if preset:
        if not settings.find_preset(preset):
            raise ValueError("고른 프리셋을 찾지 못했어요. 설정 화면에서 지워졌는지 확인해 주세요")
        return AIPick(preset=preset)
    if provider:
        if provider not in PROVIDERS:
            raise ValueError(f"고를 수 없는 AI예요: {provider}")
        return AIPick(provider=provider, model=model)
    return AIPick()


def view(pick: AIPick, stage: str) -> dict:
    """화면 값: 고른 값 · 쓸 값(use) · 설정을 따를 때 값(follow). use · follow 의 default 는 모델 칸이 빌 때 그 백엔드의 기본 모델."""
    def now(p: AIPick) -> dict:
        c = choice(p, stage)
        return {**c, "default": default_model(c["provider"]) if not c["model"] else ""}
    return {"stage": stage, **pick.model_dump(), "use": now(pick), "follow": now(AIPick())}


def presets() -> list[dict]:
    from . import settings

    return [{"id": p["id"], "name": p["name"]} for p in settings.presets()]
