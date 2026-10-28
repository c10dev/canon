"""플레이 모드: 세계 작품 속 인물이 되어 턴마다 장면을 이어 가는 텍스트 게임.

플레이 하나는 세계 작품 폴더를 복사한 작품이다(갈래 branches.make 와 같은 모양). 세계 작품은 바꾸지 않는다.
플레이 정보는 project.json 밖의 play.json (store.load_play · save_play). 한 턴은 Episode 하나다.
턴은 장면 먼저(scene, play 단계) → 상태는 뒤에서(settle, state 단계). 플레이어가 고른 행동이 그 턴의 승인이라
자동 집필처럼 사람 검토 없이 반영하고 Episode.auto 로 표시한다. 인물 설정 바꾸기 제안은 charlog.hold 로 남겨 둔다.
LLM 호출은 scene · settle · 장 요약뿐이고, 나머지는 코드다.

이 파일은 틀만 둔 처음 판이다. 엔진 작업이 채운다.
"""
from __future__ import annotations

from .llm import LLM
from .schema import Birth, Character, PlayInfo, PlayPerson, PlayScene, Project, StateDelta, TurnKind


def start(world: str, to: str, *, player: str = "", character: Character | None = None, birth: Birth | None = None,
          person: PlayPerson = "second", max_turns: int = 0, seed: int | None = None) -> tuple[Project, PlayInfo]:
    """world 작품을 to 폴더로 복사해 플레이를 연다. player 는 세계의 인물 id, 무작위 출생이면 character(birth.to_character)와
    birth 를 준다. 세계의 마지막 반영 화 직후 상태에서 시작하고(trim_after), 장편 경로(form serial)와 첫 장을 연다."""
    raise NotImplementedError


def trim_after(p: Project, n: int) -> None:
    """n 화(턴) 반영 직후로 돌리고 뒤 Episode 를 지운다. 장 범위를 n 에 맞게 자르고, n 을 넘는 닫힌 장은 다시 연다."""
    raise NotImplementedError


def roll_luck(info: PlayInfo, n: int) -> int:
    """n 턴의 운 -2~2. 같은 시드와 턴이면 같은 값."""
    raise NotImplementedError


def scene(llm: LLM, p: Project, info: PlayInfo, action: str = "", kind: TurnKind = "choice") -> PlayScene:
    """다음 턴 장면을 쓴다(prompts.play_scene_prompt). Episode 와 PlayTurn(state pending)을 더한다. 저장하지 않는다.
    앞 턴 상태 반영이 끝나지 않았거나 플레이가 끝났으면 막는다."""
    raise NotImplementedError


def settle(llm: LLM, p: Project, info: PlayInfo, n: int) -> StateDelta:
    """n 턴 상태 변경안을 만들어(prompts.play_state_prompt) 반영한다. 설정 바꾸기 제안은 남겨 두고 Episode.auto 를 켠다.
    장이 끝나면 요약으로 접고 다음 장을 연다. 결말이면 끝낸다. 저장하지 않는다."""
    raise NotImplementedError


def rewind(p: Project, info: PlayInfo, n: int) -> None:
    """n 턴 직후로 되감는다 (trim_after + 턴 기록 자르기, 결말도 지운다)."""
    raise NotImplementedError


def end(p: Project, info: PlayInfo, reason: str) -> None:
    """플레이를 끝낸다. 되감으면 다시 이어 갈 수 있다."""
    raise NotImplementedError
