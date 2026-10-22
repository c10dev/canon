"""프롬프트 템플릿과 컨텍스트 조립.

일관성 유지의 핵심은 build_episode_context(): 매 화마다 '현재 시점의 데이터'만 골라
같은 순서와 형식으로 넣는다. 이전 본문 전체 대신 요약 + 직전 화 끝부분만 넣어
분량이 늘어도 컨텍스트가 일정하게 유지된다.
검수(check_prompt)는 반대로 앞선 본문을 한도 안에서 통째로 넣는다. 쓸 때는 압축, 검사할 때는 전체.
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from . import genres, naming
from .dynamics import VIEWS, describe_relations
from .llm import _inline_refs, dump
from .schema import ChatMessage, ConsistencyReport, Project, StateDelta

SYSTEM_PLANNER = (
    "당신은 한국 웹소설/단편소설 기획 전문 편집자입니다. "
    "주어진 설정을 존중하고, 모순 없이 구체적으로 제안합니다. 모든 출력은 한국어로 작성합니다."
)

# AI 글티('쇠맛')를 줄이는 기본 문체 규칙. 작품의 스타일 프로필과 부딪히면 스타일 프로필을 따른다.
# 강한 금지어보다 담담한 지시와 대신 할 일을 함께 적는다. 측정은 metrics.AI_PATTERNS 가 맡는다.
PROSE_RULES = """[문체 기본 규칙] 스타일 프로필과 부딪히면 스타일 프로필을 따릅니다.
- 감정은 이름으로 말하지 않고 행동, 대사, 사물로 드러냅니다. 독자가 짐작할 수 있는 것은 설명하지 않습니다.
- 인물은 자기 감정과 동기를 정리해서 말하지 않습니다. 대사에는 말하지 않은 것이 남습니다.
- 장면을 주제나 교훈을 정리하는 문장으로 끝내지 않습니다. 마지막 문장은 행동이나 대사로 둡니다.
- "단순한 A가 아니었다. B였다" 같은 부정 후 재정의, 셋씩 나열하는 수식, 문단 끝의 짧은 여운 문장은 한 화에 한 번 이하로 씁니다.
- 문장 길이를 불규칙하게 섞습니다. 문맥으로 알 수 있는 주어는 뺍니다.
- 한 문장에 쉼표가 둘 이상 필요하면 문장을 나눕니다.
- '그는', '그녀의' 같은 대명사보다 이름이나 생략을 씁니다. '~를 통해', '~에 있어', '~하게 되었다' 대신 능동형 동사를 씁니다.
- '묘한 불안감', '알 수 없는 감정' 같은 추상어 대신 이 장면에만 있는 사물, 소리, 행동을 씁니다.
- 비유는 아끼고, 쓸 때는 이 인물이 실제로 떠올릴 법한 것에서 가져옵니다.
- 대사의 어미, 호칭, 길이는 인물마다 다릅니다.
- 본문에 줄표(—), 굵은 글씨, 마크다운 기호를 쓰지 않습니다."""

SYSTEM_WRITER = (
    "당신은 소설가입니다. 주어진 스타일 프로필과 예시 문단의 문체를 따르고, "
    "인물 설정과 현재 상태, 확정된 사실을 절대 어기지 않습니다. "
    "플롯의 사건은 모두 다루되, 비중과 처리 방식은 장면에 맞게 조절합니다. "
    "중요한 사건은 장면으로 풀어 쓰고, 어떤 사건은 대사나 짧은 회상으로 처리해도 됩니다. "
    "본문만 출력하고 제목, 해설, 메모는 붙이지 않습니다.\n\n" + PROSE_RULES
)

SYSTEM_EDITOR = (
    "당신은 연재 소설의 설정 관리 담당 편집자입니다. 본문에서 실제로 일어난 일만 근거로 "
    "인물 상태, 관계, 확정 사실, 복선을 정리합니다. 추측하지 않습니다."
)


SYSTEM_NAMER = (
    "당신은 한국 웹소설 편집자로, 인물과 장소의 이름을 고릅니다. 시대, 나이, 신분, 세계관의 말맛에 맞는 이름을 고르고 "
    "AI 가 흔히 쓰는 이름은 피합니다. 모든 출력은 한국어로 작성합니다."
)

SYSTEM_CHECKER = (
    "당신은 연재 소설의 교정 편집자입니다. 이번 화 본문이 앞선 본문, 설정, 확정 사실과 모순되는지만 찾습니다. "
    "모든 지적에는 앞선 근거와 이번 화의 문장을 원문 그대로 인용합니다. 인용할 근거가 없으면 지적하지 않습니다. "
    "문장의 좋고 나쁨이나 취향은 평가하지 않습니다."
)

# 검수 때 앞선 본문을 통째로 넣는 한도(글자). 넘으면 오래된 화부터 요약으로 바꾼다.
CHECK_TEXT_LIMIT = 150_000


def meta_text(p: Project) -> str:
    """작품 정보와 장르 안내. 장르 id 대신 이름을 넣는다."""
    view = p.meta.model_dump(exclude={"genres", "adult", "logline_parts", "tone_dials"})
    view["genre"] = genres.label(p.meta)
    view["rating"] = "성인" if p.meta.adult else "전연령"
    return f"{dump(view)}\n\n[장르 안내]\n{genres.guide(p.meta)}"


def rels(p: Project) -> str:
    """관계 설정. a_view/b_view 는 시작 관계를 만드는 설정 단계 입력이라 뺀다 (지금 관계는 Tie 가 가진다)."""
    return dump([r.model_dump(exclude={"a_view", "b_view"}) for r in p.relationships])


def setup_prompt(p: Project) -> str:
    return f"""아래는 작가가 입력한 기본 설정입니다. 비어 있거나 부족한 부분을 채워 작품 설정을 제안하세요.
이미 입력된 내용은 바꾸지 말고 그대로 살려서 확장합니다.

[기본 정보]
{meta_text(p)}

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
- a_view(a 가 b 를 보는 방식)와 b_view(b 가 a 를 보는 방식)는 {", ".join(VIEWS)} 중에서 1~2개 고릅니다. 두 방향이 달라도 됩니다.
- 인물 id 는 영문 소문자로 짓고, 이미 있는 id 는 유지합니다.
- 인물에게 gender(남/여)를 적습니다. 이름과 장소는 아래 [이름·지명 후보]에서 고르거나 같은 시대와 결로 짓고, 피할 이름은 쓰지 않습니다.
- 인물끼리 이름의 첫 글자나 끝 글자가 겹치지 않게 합니다.

[이름·지명 후보]
{naming.prompt_block(p)}"""


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
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{dump(p.characters)}
[관계]
{rels(p)}

요구사항:
- 기, 승, 전, 결 네 구간이 1화부터 {p.meta.target_episodes}화까지 빈틈없이 이어져야 합니다.
- 일반적인 비율은 기 15~20%, 승 35~40%, 전 25%, 결 15~20% 입니다.
- goal 은 그 구간이 끝날 때 도달해야 하는 이야기 상태, key_turn 은 핵심 전환점입니다.
- 주인공의 arc 가 결 구간에서 완성되도록 합니다."""


def plot_prompt(p: Project, start: int, end: int) -> str:
    prior = [e.plot for e in p.episodes if e.plot.number < start]
    return f"""{start}화부터 {end}화까지 화별 플롯을 작성하세요.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{dump(p.characters)}
[관계]
{rels(p)}
[기승전결 구조]
{dump(p.arc)}
[앞 화 플롯 (확정 또는 초안, 이어지게 쓸 것)]
{dump(prior) if prior else "없음"}
[현재 열린 복선]
{dump([f for f in p.foreshadows if f.status == "open"]) or "없음"}

요구사항:
{plot_rules(p)}"""


def plot_rules(p: Project) -> str:
    """화별 플롯을 쓸 때 지킬 규칙. 초안 생성과 대화형 수정이 같이 쓴다."""
    return f"""- 각 화는 소속 구간(act)의 goal 을 향해 전진해야 하며, 구간의 key_turn 은 해당 구간 안의 특정 화에 배치합니다.
- 한 화에 사건 3~6개, 분량은 약 {p.meta.words_per_episode}자 기준.
- 매 화 ending_hook 을 둡니다. 마지막 화는 훅 대신 여운을 둡니다.
- emotional_shift 는 감정 이름이 아니라 감정 변화가 겉으로 드러나는 행동이나 대사로 적습니다 (예: "상대의 전화를 세 번째에야 받는다").
- 모든 화가 같은 모양이 되지 않도록, 필요한 화에는 회상, 시간 건너뛰기, 곁가지 사건, 주인공의 잘못된 선택을 씁니다. 갈등은 너무 깔끔하게 정리하지 않습니다.
- 복선은 심는 화와 회수하는 화를 계획하고, 결 구간까지 모두 회수합니다.
- characters 에는 인물 id 만 씁니다."""


# ---------- 플롯 대화 (기승전결 · 화별 플롯 화면) ----------

SYSTEM_PLOT_CHAT = (
    "당신은 작가와 함께 연재 소설의 구조를 다듬는 기획 편집자입니다. "
    "작가의 말을 듣고 기승전결 구간과 화별 플롯을 고친 변경안을 내고, 왜 그렇게 고쳤는지 짧게 설명합니다. "
    "변경안은 제안일 뿐이며 작가가 골라서 반영합니다. 설정과 인물, 이미 쓴 본문은 존중합니다. "
    "모든 출력은 한국어로 작성합니다."
)

# 대화 기록은 최근 것만 넣는다. 오래된 대화의 결과는 이미 구조와 플롯에 들어가 있다.
CHAT_HISTORY_LIMIT = 12


def _chat_line(m: ChatMessage) -> str:
    if m.role == "user":
        return f"작가: {m.text}"
    line = f"편집자: {m.text}"
    r = m.revision
    if r and (r.acts or r.episodes or r.total_episodes):
        parts = (["구조"] if r.acts else []) + [f"{e.number}화" for e in r.episodes]
        applied = ", ".join("구조" if x == "acts" else f"{x}화" for x in m.applied)
        result = {"applied": f"작가가 반영함: {applied}", "dismissed": "작가가 반영하지 않음"}.get(m.outcome, "아직 결정 전")
        line += f"\n  (변경안: {', '.join(parts)} / {result})"
    return line


def plot_chat_prompt(p: Project, message: str) -> str:
    """앞쪽은 작품 설정(잘 바뀌지 않음), 뒤쪽은 지금 구조와 플롯, 대화. 캐시가 맞도록 이 순서를 지킨다."""
    eps = [{"status": e.status, **e.plot.model_dump()} for e in p.episodes]
    done = [e for e in p.episodes if e.summary]
    locked = [e.plot.number for e in p.episodes if e.status in ("written", "finalized")]
    confirmed = [e.plot.number for e in p.episodes if e.status == "confirmed"]
    history = next((c.messages for c in p.chats if c.topic == "plot"), [])[-CHAT_HISTORY_LIMIT:]
    style = p.style.model_dump(include={"narration_pov", "pacing", "scene_transition", "dialogue_ratio"})
    open_fs = [f for f in p.foreshadows if f.status == "open"]
    return f"""[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{dump(p.characters)}
[관계]
{rels(p)}
[문체 요약 (전개 속도 판단용)]
{dump(style)}

[지금 기승전결 구조] 총 {p.meta.target_episodes}화
{dump(p.arc) if p.arc else "아직 없음"}
[지금 화별 플롯] status: draft 초안, confirmed 작가가 확정, written 본문 있음, finalized 반영 완료
{dump(eps) if eps else "아직 없음"}
[이미 쓴 화의 실제 줄거리]
{chr(10).join(f"{e.plot.number}화: {e.summary}" for e in done) or "없음"}
[열린 복선]
{dump(open_fs) if open_fs else "없음"}

[지금까지의 대화]
{chr(10).join(_chat_line(m) for m in history) or "없음 (첫 대화)"}

[작가의 새 말]
{message}

요구사항:
- reply 에는 작가에게 하는 대답을 2~5문장으로 씁니다. 무엇을 왜 바꿨는지, 다른 화에 어떤 영향이 있는지 말합니다.
- 요청이 모호하면 가장 그럴듯한 해석으로 고치고, reply 에서 어떻게 해석했는지 밝힙니다. 고칠 것이 없거나 질문만 받았으면 변경 없이 대답만 합니다.
- 바꾸는 것만 넣습니다. 구조를 바꾸면 acts 에 네 구간을 모두 넣고, 그대로면 빈 목록입니다. episodes 에는 바뀌는 화만, 모든 칸을 채운 전체 플롯으로 넣습니다.
- 본문이 있는 화({", ".join(map(str, locked)) or "없음"})는 바꾸지 않습니다. 그 화의 내용과 이어지도록 뒤의 화를 고칩니다.
- 작가가 확정한 화({", ".join(map(str, confirmed)) or "없음"})는 작가가 그 화를 바꿔 달라고 했을 때만 바꿉니다.
- 한 화를 바꾸면 앞뒤 화의 엔딩 훅, 복선 심기와 회수가 어긋나지 않게 이어지는 화도 함께 고칩니다.
- 총 화수를 바꿔야 하면 total_episodes 에 새 화수를 넣고, acts 를 새 화수에 맞추고, 새로 생기거나 내용이 밀리는 화를 episodes 에 모두 넣습니다. 화수를 바꾸지 않으면 0 입니다.
- 구간은 기, 승, 전, 결 순서로 1화부터 마지막 화까지 빈틈없이 이어집니다.
{plot_rules(p)}"""


def build_episode_context(p: Project, n: int) -> str:
    """앞쪽은 화가 바뀌어도 그대로인 블록, 뒤쪽은 화마다 바뀌는 블록이다.
    Gemini 암묵적 캐시는 앞부분이 같은 요청에 적용되므로 이 순서를 지킨다."""
    ep = p.episode(n)
    act = p.act_for(n)
    cast_ids = set(ep.plot.characters) or {c.id for c in p.characters}
    states = [s for s in p.states if s.character_id in cast_ids]
    rels = [r for r in p.relationships if r.a in cast_ids and r.b in cast_ids]
    prev = [e for e in p.episodes if e.plot.number < n and e.summary]
    last_text = next((e.text for e in reversed(p.episodes) if e.plot.number == n - 1 and e.text), "")
    cast_names = ", ".join(f"{c.name}({c.id})" for c in p.characters if c.id in cast_ids)

    return f"""{static_context(p)}

# 확정된 사실
{chr(10).join("- " + f for f in p.facts) or "없음"}

# 이번 화 등장 인물
{cast_names or "설정의 인물 전원"}

# 인물 현재 상태 ({n - 1}화 종료 시점)
{dump(states) or "1화 시작 시점, 설정 그대로"}

# 관계 현재 상태
{describe_relations(p, cast_ids) or dump(rels) or "없음"}

# 열린 복선
{dump([f for f in p.foreshadows if f.status == "open"]) or "없음"}

# 지금까지의 줄거리
{chr(10).join(f"{e.plot.number}화 {e.plot.title}: {e.summary}" for e in prev) or "없음 (첫 화)"}

# 현재 구간: {act.name if act else "?"} ({act.start_ep if act else "?"}~{act.end_ep if act else "?"}화)
목표: {act.goal if act else ""}
전환점: {act.key_turn if act else ""}

# 직전 화 마지막 부분 (내용 연결용, 문체 기준은 위의 예시 문단)
{last_text[-1500:] or "없음"}

# 이번 화 플롯
{dump(ep.plot)}"""


def static_context(p: Project) -> str:
    """작품 내내 바뀌지 않는 블록: 작품 정보, 세계관, 문체, 인물 설정."""
    style = p.style
    samples = "\n\n---\n\n".join(style.sample_passages) or "없음"
    style_rules = style.model_copy(update={"sample_passages": []})
    return f"""# 작품 정보
{meta_text(p)}

# 세계관 (깨면 안 되는 규칙 포함)
{dump(p.world)}

# 스타일 프로필
{dump(style_rules)}

# 문체 예시 (이 문체를 따를 것, 내용은 가져오지 말 것)
{samples}

# 인물 설정
{dump(p.characters)}"""


def episode_prompt(p: Project, n: int) -> str:
    return (
        build_episode_context(p, n)
        + f"\n\n위 자료를 바탕으로 {n}화 본문을 약 {p.meta.words_per_episode}자 분량으로 쓰세요. "
        "직전 화 마지막 장면과 자연스럽게 이어지고, 플롯의 ending_hook 으로 끝납니다. "
        "문체는 스타일 프로필과 문체 예시 문단을 따르고, banned_phrases 의 표현은 쓰지 않습니다. "
        "플롯의 emotional_shift 는 감정 이름으로 서술하지 말고 행동과 대사로 보여 줍니다. "
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
{rels(p)}
[현재 비밀]
{dump(p.secrets) or "없음"}
[열린 복선]
{dump([f for f in p.foreshadows if f.status == "open"]) or "없음"}
[이번 화 플롯]
{dump(ep.plot)}

[{n}화 본문]
{ep.text}

요구사항:
- episode 는 {n} 입니다.
- 변화가 있는 인물만 넣습니다.
- events 에는 인물 사이에 일어난 관계 사건을 본문 순서대로 적습니다. kind 는 정해진 목록에서 고르고, intensity 는 1(가벼움)~3(결정적), quote 에는 근거 문장을 본문에서 그대로 옮깁니다. 관계 수치는 프로그램이 사건으로 계산하므로 적지 않고, 수동보정은 쓰지 않습니다.
- relationship_updates 에는 관계 유형이나 설명이 바뀐 쌍만 넣습니다.
- 새로 생긴 비밀은 secrets_added 에 넣고, 비밀이 드러난 사건에는 reveals_secret 에 비밀 id 를 적습니다.
- 새 복선 id 는 fs-{n:02d}-키워드 형식으로 짓습니다.
- warnings 에는 플롯 사건 누락, 설정/말투 위반, 확정 사실과의 모순을 적습니다."""


def check_prompt(p: Project, n: int) -> str:
    ep = p.episode(n)
    prior = sorted((e for e in p.episodes if e.plot.number < n and e.text), key=lambda e: e.plot.number)
    full, budget = [], CHECK_TEXT_LIMIT
    for e in reversed(prior):
        if len(e.text) > budget:
            break
        full.append(e)
        budget -= len(e.text)
    full_nos = {e.plot.number for e in full}
    past = "\n\n".join(
        f"## {e.plot.number}화 {e.plot.title}\n{e.text if e.plot.number in full_nos else '(요약) ' + e.summary}"
        for e in prior
    )
    return f"""{static_context(p)}

# 확정된 사실
{chr(10).join("- " + f for f in p.facts) or "없음"}

# 인물 현재 상태 ({n - 1}화 종료 시점)
{dump(p.states) or "1화 시작 시점, 설정 그대로"}

# 관계 현재 상태
{rels(p) if p.relationships else "없음"}

# 비밀 (hidden_from 의 인물은 아직 모른다)
{dump(p.secrets) or "없음"}

# 앞선 본문
{past or "없음 (첫 화)"}

# {n}화 플롯
{dump(ep.plot)}

# {n}화 본문 (검수 대상)
{ep.text}

{n}화 본문에서 위 자료와 어긋나는 곳을 찾으세요.
- 확인할 것: 확정 사실과 세부(이름, 나이, 외모, 장소, 물건), 시간 순서와 인과, 인물이 아직 모르는 정보를 아는 듯 행동하는지, 말투(호칭, 존댓말/반말, 어미), 세계관 규칙, 플롯 사건 누락.
- source_quote 와 current_quote 는 원문을 그대로 옮깁니다. 근거가 설정이나 인물 상태면 source_episode 는 0 입니다.
- 근거를 인용할 수 없는 의심은 넣지 않습니다. 모순이 없으면 issues 를 빈 목록으로 둡니다.
- episode 는 {n} 입니다."""


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
    return f"""# {p.meta.title or "작품"} {n}화 상태 정리 작업지시서

## 역할
{SYSTEM_EDITOR}

{state_prompt(p, n)}

## 출력 형식
아래 JSON 스키마를 따르는 JSON 하나만 코드 블록 없이 출력하세요.

{_schema_text(StateDelta)}
"""


def check_brief(p: Project, n: int) -> str:
    return f"""# {p.meta.title or "작품"} {n}화 검수 작업지시서

## 역할
{SYSTEM_CHECKER}

{check_prompt(p, n)}

## 출력 형식
아래 JSON 스키마를 따르는 JSON 하나만 코드 블록 없이 출력하세요.

{_schema_text(ConsistencyReport)}
"""


def _schema_text(model: type[BaseModel]) -> str:
    return json.dumps(_inline_refs(model.model_json_schema()), ensure_ascii=False, indent=2)



def naming_prompt(p: Project, target: str, candidates: list, n: int) -> str:
    """target: 이름을 지을 대상 설명. candidates: naming.Candidate 목록 (코드가 뽑은 것)."""
    cand = "\n".join(f"- {c.name}" + (f" ({c.kind})" if c.kind else "") + (f": {c.note}" if c.note else "") for c in candidates)
    others = ", ".join(c.name for c in p.characters if c.name) or "없음"
    rules = "\n".join(f"- {r}" for r in p.world.name_rules) or "- 따로 없음"
    return f"""아래 작품에 쓸 이름을 {n}개 추천하세요.

[작품]
{meta_text(p)}
[세계관]
배경: {p.world.setting}
시대: {p.world.era}
이름 스타일: {naming.style_label(naming.resolve_style(p))}
이름 규칙:
{rules}
이미 있는 인물: {others}
이미 있는 장소: {", ".join(p.world.locations) or "없음"}

[대상]
{target}

[코드가 뽑은 후보]
{cand}

요구사항:
- 절반 이상은 위 후보에서 고르고, 나머지는 같은 시대와 결로 새로 짓습니다.
- 이미 있는 인물과 첫 글자나 끝 글자가 겹치는 이름, 이미 있는 장소와 같은 이름은 피합니다.
- reason 에는 이 대상에 맞는 이유를 한 줄로 적습니다 (시대, 나이, 신분, 성격, 지형 등)."""
