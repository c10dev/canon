"""프롬프트 템플릿과 컨텍스트 조립.

일관성 유지의 핵심은 build_episode_context(): 매 화마다 '현재 시점의 데이터'만 골라
같은 순서와 형식으로 넣는다. 이전 본문 전체 대신 요약 + 직전 화 끝부분만 넣어
분량이 늘어도 컨텍스트가 일정하게 유지된다.
"""
from __future__ import annotations

from .llm import dump
from .schema import Project

SYSTEM_PLANNER = (
    "당신은 한국 웹소설/단편소설 기획 전문 편집자입니다. "
    "주어진 설정을 존중하고, 모순 없이 구체적으로 제안합니다. 모든 출력은 한국어로 작성합니다."
)

SYSTEM_WRITER = (
    "당신은 소설가입니다. 주어진 스타일 프로필과 예시 문단의 문체를 따르고, "
    "인물 설정과 현재 상태, 확정된 사실을 절대 어기지 않습니다. "
    "플롯의 사건을 빠짐없이 순서대로 장면으로 풀어 쓰되 요약하듯 넘기지 않습니다. "
    "본문만 출력하고 제목, 해설, 메모는 붙이지 않습니다."
)

SYSTEM_EDITOR = (
    "당신은 연재 소설의 설정 관리 담당 편집자입니다. 본문에서 실제로 일어난 일만 근거로 "
    "인물 상태, 관계, 확정 사실, 복선을 정리합니다. 추측하지 않습니다."
)


def setup_prompt(p: Project) -> str:
    return f"""아래는 작가가 입력한 기본 설정입니다. 비어 있거나 부족한 부분을 채워 작품 설정을 제안하세요.
이미 입력된 내용은 바꾸지 말고 그대로 살려서 확장합니다.

[기본 정보]
{dump(p.meta)}

[이미 입력된 세계관]
{dump(p.world)}

[이미 입력된 인물]
{dump(p.characters)}

[이미 입력된 관계]
{dump(p.relationships)}

요구사항:
- 인물은 주인공 포함 3~6명. {p.meta.target_episodes}화 분량의 단편에 맞게 압축합니다.
- 각 인물의 speech_style 은 대사 예시 한 줄을 포함해 구체적으로 씁니다.
- 관계는 주요 인물 쌍마다 하나씩, affinity 와 tension 은 1화 시작 시점 기준입니다.
- 인물 id 는 영문 소문자로 짓고, 이미 있는 id 는 유지합니다."""


def style_prompt(sample: str) -> str:
    return f"""아래 예시 소설 텍스트의 문체를 분석해 스타일 프로필을 만드세요.
다른 작품을 쓸 때 이 문체를 재현할 수 있도록, 관찰 가능한 특징을 구체적으로 적습니다
(예: "문장 평균 20자 안팎, 짧은 문장 연속 후 긴 문장 하나로 감정 폭발").
sample_passages 에는 원문에서 문체가 가장 잘 드러나는 문단 2~4개를 수정 없이 발췌합니다
(서술 위주 하나, 대화 위주 하나는 꼭 포함).

[예시 텍스트]
{sample}"""


def arc_prompt(p: Project) -> str:
    return f"""아래 작품을 총 {p.meta.target_episodes}화로 완결하는 기승전결 구조를 설계하세요.

[작품]
{dump(p.meta)}
[세계관]
{dump(p.world)}
[인물]
{dump(p.characters)}
[관계]
{dump(p.relationships)}

요구사항:
- 기, 승, 전, 결 네 구간이 1화부터 {p.meta.target_episodes}화까지 빈틈없이 이어져야 합니다.
- 일반적인 비율은 기 15~20%, 승 35~40%, 전 25%, 결 15~20% 입니다.
- goal 은 그 구간이 끝날 때 도달해야 하는 이야기 상태, key_turn 은 핵심 전환점입니다.
- 주인공의 arc 가 결 구간에서 완성되도록 합니다."""


def plot_prompt(p: Project, start: int, end: int) -> str:
    prior = [e.plot for e in p.episodes if e.plot.number < start]
    return f"""{start}화부터 {end}화까지 화별 플롯을 작성하세요.

[작품]
{dump(p.meta)}
[세계관]
{dump(p.world)}
[인물]
{dump(p.characters)}
[관계]
{dump(p.relationships)}
[기승전결 구조]
{dump(p.arc)}
[이미 확정된 이전 화 플롯]
{dump(prior) if prior else "없음"}
[현재 열린 복선]
{dump([f for f in p.foreshadows if f.status == "open"]) or "없음"}

요구사항:
- 각 화는 소속 구간(act)의 goal 을 향해 전진해야 하며, 구간의 key_turn 은 해당 구간 안의 특정 화에 배치합니다.
- 한 화에 사건 3~6개, 분량은 약 {p.meta.words_per_episode}자 기준.
- 매 화 ending_hook 을 둡니다. 마지막 화는 훅 대신 여운을 둡니다.
- 복선은 심는 화와 회수하는 화를 계획하고, 결 구간까지 모두 회수합니다.
- characters 에는 인물 id 만 씁니다."""


def build_episode_context(p: Project, n: int) -> str:
    ep = p.episode(n)
    act = p.act_for(n)
    cast = [c for c in p.characters if c.id in ep.plot.characters] or p.characters
    cast_ids = {c.id for c in cast}
    states = [s for s in p.states if s.character_id in cast_ids]
    rels = [r for r in p.relationships if r.a in cast_ids and r.b in cast_ids]
    prev = [e for e in p.episodes if e.plot.number < n and e.summary]
    last_text = next((e.text for e in reversed(p.episodes) if e.plot.number == n - 1 and e.text), "")

    style = p.style
    samples = "\n\n---\n\n".join(style.sample_passages) or "없음"
    style_rules = style.model_copy(update={"sample_passages": []})

    return f"""# 작품 정보
{dump(p.meta)}

# 세계관 (깨면 안 되는 규칙 포함)
{dump(p.world)}

# 확정된 사실
{chr(10).join("- " + f for f in p.facts) or "없음"}

# 등장 인물 설정
{dump(cast)}

# 인물 현재 상태 ({n - 1}화 종료 시점)
{dump(states) or "1화 시작 시점, 설정 그대로"}

# 관계 현재 상태
{dump(rels) or "없음"}

# 열린 복선
{dump([f for f in p.foreshadows if f.status == "open"]) or "없음"}

# 지금까지의 줄거리
{chr(10).join(f"{e.plot.number}화 {e.plot.title}: {e.summary}" for e in prev) or "없음 (첫 화)"}

# 직전 화 마지막 부분
{last_text[-1500:] or "없음"}

# 현재 구간: {act.name if act else "?"} ({act.start_ep if act else "?"}~{act.end_ep if act else "?"}화)
목표: {act.goal if act else ""}
전환점: {act.key_turn if act else ""}

# 이번 화 플롯
{dump(ep.plot)}

# 스타일 프로필
{dump(style_rules)}

# 문체 예시 (이 문체를 따를 것, 내용은 가져오지 말 것)
{samples}"""


def episode_prompt(p: Project, n: int) -> str:
    return (
        build_episode_context(p, n)
        + f"\n\n위 자료를 바탕으로 {n}화 본문을 약 {p.meta.words_per_episode}자 분량으로 쓰세요. "
        "직전 화 마지막 장면과 자연스럽게 이어지고, 플롯의 ending_hook 으로 끝납니다. "
        "인물의 말투는 speech_style 을 따릅니다."
    )


def state_prompt(p: Project, n: int) -> str:
    ep = p.episode(n)
    return f"""{n}화 본문을 읽고 상태 변경안을 작성하세요.

[인물 설정]
{dump(p.characters)}
[이전 인물 상태]
{dump(p.states) or "설정 그대로"}
[이전 관계]
{dump(p.relationships)}
[열린 복선]
{dump([f for f in p.foreshadows if f.status == "open"]) or "없음"}
[이번 화 플롯]
{dump(ep.plot)}

[{n}화 본문]
{ep.text}

요구사항:
- episode 는 {n} 입니다.
- 변화가 있는 인물과 관계만 넣고, 관계는 변경 후 값 전체를 씁니다.
- 새 복선 id 는 fs-{n:02d}-키워드 형식으로 짓습니다.
- warnings 에는 플롯 사건 누락, 설정/말투 위반, 확정 사실과의 모순을 적습니다."""


# ---------- 작업지시서 (구독형 채팅 앱용) ----------
# API 경로와 같은 프롬프트를 그대로 쓴다. 나중에 MCP 서버의 prompt/tool 로 옮길 때도 이 함수들을 재사용한다.

def episode_brief(p: Project, n: int) -> str:
    return f"""# {p.meta.title or "작품"} {n}화 작업지시서

아래 지시를 그대로 따라 {n}화 본문을 작성해 주세요.

## 역할
{SYSTEM_WRITER}

{episode_prompt(p, n)}
"""


def state_brief(p: Project, n: int) -> str:
    import json

    from .llm import _inline_refs
    from .schema import StateDelta

    schema = json.dumps(_inline_refs(StateDelta.model_json_schema()), ensure_ascii=False, indent=2)
    return f"""# {p.meta.title or "작품"} {n}화 상태 정리 작업지시서

## 역할
{SYSTEM_EDITOR}

{state_prompt(p, n)}

## 출력 형식
아래 JSON 스키마를 따르는 JSON 하나만 코드 블록 없이 출력하세요.

{schema}
"""
