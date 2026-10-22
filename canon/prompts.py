"""프롬프트 템플릿과 컨텍스트 조립.

일관성 유지의 핵심은 build_episode_context(): 매 화마다 '현재 시점의 데이터'만 골라
같은 순서와 형식으로 넣는다. 이전 본문 전체 대신 요약 + 직전 화 끝부분만 넣어
분량이 늘어도 컨텍스트가 일정하게 유지된다.
검수(check_prompt)는 반대로 앞선 본문을 한도 안에서 통째로 넣는다. 쓸 때는 압축, 검사할 때는 전체.
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from . import elements, genres, metrics, naming, storylines
from .dynamics import VIEWS, describe_relations
from .llm import _inline_refs, dump
from .schema import Character, ChatMessage, ConsistencyReport, Foreshadow, ImpactReport, Project, Selection, StateDelta, StoryElement

SYSTEM_PLANNER = (
    "당신은 한국 웹소설/단편소설 기획 전문 편집자입니다. "
    "주어진 설정을 존중하고, 모순 없이 구체적으로 제안합니다. 모든 출력은 한국어로 작성합니다."
)

# AI 글티('쇠맛')를 줄이는 기본 문체 규칙. 작품의 스타일 프로필과 부딪히면 스타일 프로필을 따른다.
# 강한 금지어보다 담담한 지시와 대신 할 일을 함께 적는다. 측정은 metrics.AI_PATTERNS 가 맡는다.
# STYLED_DROP 은 문체 원문을 분석한 작품에서 빼는 규칙이다. 원문 작가가 쉼표 많은 긴 문장, 셋씩 나열, 줄표를 즐겨 쓰면
# 이 규칙이 프로필과 부딪혀 모델이 둘 사이에서 흔들린다 (문체 반영도 연구, 2026-10).
_PROSE_RULES = [
    ("", "감정은 이름으로 말하지 않고 행동, 대사, 사물로 드러냅니다. 독자가 짐작할 수 있는 것은 설명하지 않습니다."),
    ("", "인물은 자기 감정과 동기를 정리해서 말하지 않습니다. 대사에는 말하지 않은 것이 남습니다."),
    ("", "장면을 주제나 교훈을 정리하는 문장으로 끝내지 않습니다. 마지막 문장은 행동이나 대사로 둡니다."),
    ("plain", '"단순한 A가 아니었다. B였다" 같은 부정 후 재정의, 셋씩 나열하는 수식, 문단 끝의 짧은 여운 문장은 한 화에 한 번 이하로 씁니다.'),
    ("styled", '"단순한 A가 아니었다. B였다" 같은 부정 후 재정의와 문단 끝의 짧은 여운 문장은 한 화에 한 번 이하로 씁니다.'),
    ("", "문장 길이를 불규칙하게 섞습니다. 문맥으로 알 수 있는 주어는 뺍니다."),
    ("plain", "한 문장에 쉼표가 둘 이상 필요하면 문장을 나눕니다."),
    ("", "'그는', '그녀의' 같은 대명사보다 이름이나 생략을 씁니다. '~를 통해', '~에 있어', '~하게 되었다' 대신 능동형 동사를 씁니다."),
    ("", "'묘한 불안감', '알 수 없는 감정' 같은 추상어 대신 이 장면에만 있는 사물, 소리, 행동을 씁니다."),
    ("", "비유는 아끼고, 쓸 때는 이 인물이 실제로 떠올릴 법한 것에서 가져옵니다."),
    ("", "대사의 어미, 호칭, 길이는 인물마다 다릅니다."),
    ("plain", "본문에 줄표(—), 굵은 글씨, 마크다운 기호를 쓰지 않습니다."),
    ("styled", "본문에 굵은 글씨, 마크다운 기호를 쓰지 않습니다."),
]


def prose_rules(styled: bool = False) -> str:
    """기본 문체 규칙. styled 면 문체 원문과 부딪히기 쉬운 쉼표, 셋씩 나열, 줄표 규칙을 뺀다."""
    skip = "plain" if styled else "styled"
    lines = [f"- {rule}" for kind, rule in _PROSE_RULES if kind != skip]
    return "[문체 기본 규칙] 스타일 프로필과 부딪히면 스타일 프로필을 따릅니다.\n" + "\n".join(lines)


PROSE_RULES = prose_rules()

_WRITER = (
    "당신은 소설가입니다. 주어진 스타일 프로필과 예시 문단의 문체를 따르고, "
    "인물 설정과 현재 상태, 확정된 사실을 절대 어기지 않습니다. "
    "플롯의 사건은 모두 다루되, 비중과 처리 방식은 장면에 맞게 조절합니다. "
    "중요한 사건은 장면으로 풀어 쓰고, 어떤 사건은 대사나 짧은 회상으로 처리해도 됩니다. "
    "본문만 출력하고 제목, 해설, 메모는 붙이지 않습니다.\n\n"
)
SYSTEM_WRITER = _WRITER + PROSE_RULES


def styled(p: Project) -> bool:
    """원문을 분석한 문체가 있는 작품인지. 예시 문단이나 표지가 있으면 그렇다고 본다."""
    return bool(p.style.sample_passages or p.style.markers)


def writer_system(p: Project) -> str:
    """본문 쓰기 시스템 프롬프트. 문체 원문이 있는 작품은 원문과 부딪히는 기본 규칙을 뺀다."""
    return _WRITER + prose_rules(styled(p))


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


def rels(p: Project, ids: set[str] | None = None) -> str:
    """관계 설정. a_view/b_view 는 시작 관계를 만드는 설정 단계 입력이라 뺀다 (지금 관계는 Tie 가 가진다).
    ids 를 주면 그 인물끼리의 관계만 넣는다."""
    return dump([r.model_dump(exclude={"a_view", "b_view"}) for r in p.relationships
                 if ids is None or (r.a in ids and r.b in ids)])


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
markers 에는 이 문체를 알아보게 하는 어미, 조사, 말버릇 5~10개를 원문에 적힌 글자 그대로 적습니다
(예: "것이었다", "하더라", "말이지"). 원문에서 여러 번 나오는 것만 고르고, 인물 이름이나 이 작품에만 있는 낱말은 넣지 않습니다.
per_1k 는 0 으로 두세요. 원문에서 직접 셉니다.

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
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}

요구사항:
{arc_range_rule(p.meta.target_episodes)}
- goal 은 그 구간이 끝날 때 도달해야 하는 이야기 상태, key_turn 은 핵심 전환점입니다.
- 주인공의 arc 가 결 구간에서 완성되도록 합니다.
- 기 구간은 소개가 아니라 발단입니다. 1화에 사건이 시작되고, 주인공의 결핍과 작품의 핵심 장치가 1~3화 안에 드러나며, 3화 안에 작은 보상이 하나 옵니다."""


def arc_range_rule(total: int) -> str:
    """구간 범위 요구사항. 4화보다 짧으면 한 화에 두 구간이 들어가야 하므로 따로 안내한다."""
    if total >= 4:
        return f"""- 기, 승, 전, 결 네 구간이 1화부터 {total}화까지 빈틈없이 이어져야 합니다. 구간끼리 화가 겹치면 안 됩니다.
- 일반적인 비율은 기 15~20%, 승 35~40%, 전 25%, 결 15~20% 입니다."""
    shape = {1: "기 1~1, 승 1~1, 전 1~1, 결 1~1 (한 화 안에 기승전결)",
             2: "기 1~1, 승 1~1, 전 2~2, 결 2~2",
             3: "기 1~1, 승 2~2, 전 3~3, 결 3~3"}.get(total, "")
    return f"""- 총 {total}화라 네 구간이 한 화씩 가질 수 없습니다. 이웃한 구간이 한 화를 함께 씁니다. 범위는 {shape} 로 하세요.
- 한 화를 함께 쓰는 구간은 그 화 안에서 차례로 지나갑니다. goal 과 key_turn 은 구간마다 따로 씁니다."""


def plot_prompt(p: Project, start: int, end: int) -> str:
    if p.serial:
        return serial_plot_prompt(p, start, end)
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
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[기승전결 구조]
{dump(p.arc)}
[앞 화 플롯 (확정 또는 초안, 이어지게 쓸 것)]
{dump(prior) if prior else "없음"}
[현재 열린 복선]
{dump([f for f in p.foreshadows if f.status == "open"]) or "없음"}

요구사항:
{plot_rules(p, start <= OPENING_EPISODES)}"""


def serial_plot_prompt(p: Project, start: int, end: int) -> str:
    """장편: 앞 화 플롯 전부 대신 접은 줄거리와 이번 아크의 앞 화 플롯만 넣는다."""
    arc = p.arc_for(start)
    lo = arc.start_ep if arc else start
    near = [e.plot for e in p.episodes if max(1, lo - 2) <= e.plot.number < start]
    ids = set(arc.cast if arc else []) | {c for e in near for c in e.characters}
    fs, more = relevant_foreshadows(p, start)
    return f"""{start}화부터 {end}화까지 화별 플롯을 작성하세요.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[주역]
{dump(static_characters(p))}
[이 아크의 다른 인물]
{dump([c for c in p.characters if c.id in ids and c.tier != "main"]) or "없음"}
[등장할 수 있는 다른 인물 (id: 이름, 역할)]
{roster_line(p, ids) or "없음"}
[관계]
{rels(p, ids | {c.id for c in static_characters(p)})}
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}

{structure_text(p, start)}

[지금까지의 줄거리]
{story_so_far(p, start) or "없음 (첫 화)"}
[바로 앞 화 플롯 (확정 또는 초안, 이어지게 쓸 것)]
{dump(near) if near else "없음"}
[열린 복선]{f" (그 밖에 {more}개는 이번 아크와 거리가 멀어 뺐습니다)" if more else ""}
{dump(fs) or "없음"}{rebuild_map_block(p, start, end)}

요구사항:
{plot_rules(p, start <= OPENING_EPISODES)}"""


USE_LABEL = {"keep": "옛 본문 그대로", "revise": "옛 본문을 다듬음", "rewrite": "옛 화를 재료로 새로 씀", "new": "새 화"}


def rebuild_map_block(p: Project, start: int, end: int) -> str:
    """재구성한 작품: 이 구간 화마다 정해 둔 내용과 옛 단편 화. 본문이 있는 화의 플롯은 바꾸지 않는다."""
    if p.archive is None:
        return ""
    lines = []
    for x in p.archive.map:
        if not start <= x.number <= end:
            continue
        olds = "; ".join(f"단편 {s}화 {src.plot.title}: {src.summary or src.plot.summary}"
                         for s in x.sources if (src := p.archive.source(s)))
        ep = next((e for e in p.episodes if e.plot.number == x.number), None)
        fixed = " (본문이 이미 있어 플롯 고정. 위 플롯과 같은 내용으로 이어지게)" if ep and ep.text else ""
        lines.append(f"- {x.number}화 [{USE_LABEL[x.use]}]{fixed} {x.title}: {x.summary}"
                     + (f"\n  옛 화: {olds}" if olds else "") + (f"\n  메모: {x.note}" if x.note else ""))
    if not lines:
        return ""
    fixed = [e.plot for e in p.episodes if start <= e.plot.number <= end and e.text]
    return ("\n[재구성 지도 (단편을 장편으로 다시 짠 계획. 화마다 이 내용을 따르세요)]\n" + "\n".join(lines)
            + (f"\n[본문이 있는 화의 플롯 (바꾸지 말고 그대로 다시 적을 것)]\n{dump(fixed)}" if fixed else ""))


def lines_block(p: Project) -> str:
    """기획 프롬프트에 붙는 이야기 줄기 블록. 줄기가 없으면 아무것도 넣지 않는다."""
    b = storylines.plan_block(p)
    return f"\n[이야기 줄기 (메인에서 갈라졌다 합류하는 서브플롯 · 회상 · 외전)]\n{b}" if b else ""


def plot_rules(p: Project, opening: bool = False) -> str:
    """화별 플롯을 쓸 때 지킬 규칙. 초안 생성과 대화형 수정이 같이 쓴다.
    opening 이면 1~3화 규칙과 장르별 초반 박자를 붙인다 (다룰 화에 1~3화가 있을 때만, 장편 뒤쪽 프롬프트를 키우지 않게)."""
    common = f"""- 각 화는 소속 구간(act)의 goal 을 향해 전진해야 하며, 구간의 key_turn 은 해당 구간 안의 특정 화에 배치합니다.
- 한 화에 사건 3~6개, 분량은 약 {p.meta.words_per_episode}자 기준.
- emotional_shift 는 감정 이름이 아니라 감정 변화가 겉으로 드러나는 행동이나 대사로 적습니다 (예: "상대의 전화를 세 번째에야 받는다").
- 모든 화가 같은 모양이 되지 않도록, 필요한 화에는 회상, 시간 건너뛰기, 곁가지 사건, 주인공의 잘못된 선택을 씁니다. 갈등은 너무 깔끔하게 정리하지 않습니다.
- 이야기 요소는 시점을 지킵니다. 'n화부터 생김'은 그 화 전에 사실로 쓰지 않고, '나올 화'에는 그 요소를 사건으로 넣고, '드러나는 화' 전에는 암시만 둡니다.
- characters 에는 인물 id 만 씁니다.""" + storylines.plan_rule(p) + (opening_plot_rule(p) if opening else "")
    if not p.serial:
        return common + """
- 매 화 ending_hook 을 둡니다. 마지막 화는 훅 대신 여운을 둡니다.
- 복선은 심는 화와 회수하는 화를 계획하고, 결 구간까지 모두 회수합니다."""
    return common + f"""
- act 는 그 화가 속한 아크 안의 기승전결 위치입니다. 아크의 conflict 가 결 구간에서 해결되고, 아크의 payoff 가 전 구간 끝이나 결 구간 첫 화에 확실하게 나옵니다.
- 주인공이 막히는 구간은 2~3화를 넘기지 않고, 막힌 만큼 시원하게 푸는 화를 뒤에 둡니다.
- 매 화 ending_hook 을 둡니다. 장면 한가운데나 새 정보가 드러나는 순간에 끊습니다. 아크 마지막 화는 다음 아크로 이어지는 떡밥으로 끊습니다. 작품 마지막 화({p.meta.target_episodes}화)만 훅 대신 여운을 둡니다.
- 이 아크에서 심은 작은 복선은 아크 안에서 회수합니다. 아크의 payoffs 에 있는 복선은 아크가 끝나기 전에 회수합니다. 부나 작품 끝까지 끌고 갈 복선은 심을 때 그렇다고 밝힙니다.
- 첫 아크의 큰 보상은 25화 안에 둡니다 (무료 공개 구간 안에 보상이 와야 계속 읽는다는 연재 관습)."""


# ---------- 초반 1~3화: 독자가 계속 읽을지 정하는 구간 ----------
# 무료 회차로 고르는 플랫폼에서는 1~3화에서 독자가 남을지 정한다. 이 화들에만 따로 규칙을 붙인다.
# 규칙은 화마다 바뀌는 뒤쪽 블록에 둬서 static_context 캐시를 깨지 않는다. 연구 보고서: canon/research/opening-hook.html

OPENING_EPISODES = 3

OPENING_JOBS = {
    1: "1화는 약속입니다. 주인공이 누구인지, 무엇이 없는지(결핍), 무엇이 뒤집히는지 보여 주고, 작품의 핵심 장치(회귀, 빙의, 각성, 계약, 사건 등)가 이 화 앞 절반 안에 일어나거나 확실히 예고됩니다.",
    2: "2화는 첫 행동입니다. 주인공이 처음으로 스스로 고르고, 그 선택의 대가가 보입니다. 1화가 남긴 질문에 일부 답하고, 장치나 능력의 규칙 하나가 사건 속에서 드러납니다.",
    3: "3화는 첫 보상입니다. 작은 보상(첫 성과, 첫 응징, 첫 설렘) 하나를 확실하게 주고, 첫 아크의 진짜 문제가 보이는 더 큰 질문으로 끊습니다.",
}

# 1화를 여는 방식. 여러 안을 써서 고를 때 안마다 하나씩 붙인다. id → (이름, 지시)
OPENING_APPROACHES: dict[str, tuple[str, str]] = {
    "in_medias_res": ("사건 한가운데", "위기나 갈등이 이미 벌어진 장면에서 시작합니다. 앞 사정은 장면이 진행되며 대사와 행동으로 조금씩 드러냅니다."),
    "lack_turn": ("결핍에서 전환", "주인공의 바닥인 처지를 짧은 장면 하나로 보여 주고(앞 3분의 1 안), 그 처지를 뒤집는 사건으로 넘어갑니다. 화 끝에 작품의 핵심 장치가 확정됩니다."),
    "premise_first": ("전제부터", "첫 문단은 작품의 핵심 장치(회귀, 빙의, 각성, 계약, 사건)가 이미 일어난 직후입니다. 주인공이 바뀐 처지를 확인하고 첫 판단을 내리는 데 이 화를 씁니다."),
    "flash_forward": ("미래 장면 먼저", "뒤에 올 결정적 장면 하나를 화 맨 앞에 500자 안팎으로 짧게 보여 준 뒤 시간을 되돌려 시작합니다. 그 장면은 설정을 어기지 않고, 어떻게 그렇게 되는지는 숨깁니다."),
}
DEFAULT_APPROACHES = ["in_medias_res", "lack_turn", "premise_first"]


def is_opening(n: int) -> bool:
    return 1 <= n <= OPENING_EPISODES


def opening_pending(p: Project) -> bool:
    """1~3화 가운데 아직 본문이 없는 화가 있는가. 플롯 대화 · 영향 분석이 초반 규칙을 붙일지 정한다."""
    written = {e.plot.number for e in p.episodes if e.text}
    return any(n not in written for n in range(1, OPENING_EPISODES + 1))


def opening_plot_rule(p: Project) -> str:
    """화별 플롯 규칙에 붙는 1~3화 규칙. 장르별 박자가 있으면 함께 넣는다."""
    beats = []
    for n in range(1, OPENING_EPISODES + 1):
        b = genres.opening_beats(p.meta, n)
        if b:
            beats.append(f"  {n}화: " + " / ".join(b))
    return f"""
- 1~3화는 독자가 계속 읽을지 정하는 초반입니다. {OPENING_JOBS[1]} {OPENING_JOBS[2]} {OPENING_JOBS[3]}
- 1~3화의 '기' 구간은 소개가 아니라 발단입니다. 세계관 설명이나 인물 소개만 하는 화를 두지 않고, 설정은 사건에 필요한 만큼만 나눠 드러냅니다. 1화에 이름을 붙여 등장시키는 인물은 다섯 명 이하로 둡니다.
- 1~3화는 opening 에 그 화를 여는 첫 장면을, reader_question 에 그 화를 읽은 독자가 다음 화로 들고 갈 질문을 적습니다. 다음 화는 앞 화의 질문에 일부 답하면서 더 큰 질문을 엽니다. 다른 화는 두 칸을 비워도 됩니다.""" + (
        "\n- 장르별 초반 박자 (출발점이며, 이야기에 맞게 바꿔도 됩니다):\n" + "\n".join(beats) if beats else "")


def opening_rules(p: Project, n: int, approach: str = "") -> str:
    """n화(1~3) 본문에 붙이는 초반 규칙. 그 밖의 화는 빈 문자열. approach 는 OPENING_APPROACHES 의 id."""
    if not is_opening(n):
        return ""
    beats = genres.opening_beats(p.meta, n)
    plot = next((e.plot for e in p.episodes if e.plot.number == n), None)
    lines = [
        f"# 초반 규칙 ({n}화, 독자가 계속 읽을지 정하는 화)",
        "문체는 스타일 프로필을 따르고, 사건 배치와 장면 시작 · 끝은 이 규칙을 따릅니다.",
        f"- {OPENING_JOBS[n]}",
        "- 첫 문단에서 주인공이 이미 무언가를 하고 있습니다. 세계관 설명, 날씨, 아침 기상, \"평범한 ~였다\" 같은 자기소개로 시작하지 않습니다.",
        "- 세계관과 인물 설정은 어기지 말라는 자료이지 모두 설명하라는 것이 아닙니다. 이번 화에 필요한 것만 장면, 대사, 속마음 속에서 드러냅니다. 설명하는 문장을 세 문장 넘게 잇지 않습니다.",
        "- 이름을 붙여 등장시키는 인물은 이번 화 등장 인물로 한정합니다. 주인공의 이름과 목소리(대사나 속마음)가 앞부분에 나옵니다.",
        "- 주인공의 결핍과 걸린 것은 감정 이름이 아니라 처지와 행동으로 보입니다.",
        "- 마지막 문단은 장면 한가운데나 새 정보가 드러나는 순간입니다. \"그때는 몰랐다\", \"이것이 시작이었다\" 같은 앞날 해설이나 정리하는 문장으로 끝내지 않습니다.",
    ]
    if plot and plot.opening:
        lines.append(f"- 여는 장면: {plot.opening}")
    if plot and plot.reader_question:
        lines.append(f"- 이 화를 읽은 독자가 들고 갈 질문: {plot.reader_question}")
    if beats:
        lines.append("- 장르별 박자: " + " / ".join(beats))
    if approach in OPENING_APPROACHES:
        label, how = OPENING_APPROACHES[approach]
        lines.append(f"- 여는 방식 ({label}): {how}")
    return "\n".join(lines)


# ---------- 장편 연재: 계층 줄거리, 관련 자료 고르기, 부 · 아크 기획 ----------

FACTS_FILTER_FROM = 60  # 확정 사실이 이보다 많으면 이번 화와 관련된 것만 넣는다
FACTS_RECENT = 30
FORESHADOW_RECENT = 30  # 이 화수 안에 심은 복선은 늘 넣는다
FORESHADOW_CAP = 25


def story_so_far(p: Project, n: int) -> str:
    """n화 직전까지의 줄거리. 단편은 화별 요약 전부. 장편은 끝난 부 → 이번 부의 끝난 아크 → 이번 아크의 화 순서로 접어서,
    300화째에도 크기가 일정하다. 요약이 아직 없는 부와 아크는 한 단계 아래 요약으로 대신한다."""
    eps = sorted((e for e in p.episodes if e.plot.number < n and e.summary), key=lambda e: e.plot.number)
    line = lambda e: f"{e.plot.number}화 {storylines.summary_tag(p, e)}{e.plot.title}: {e.summary}"  # noqa: E731
    if not p.serial or not p.story_arcs:
        return "\n".join(map(line, eps))
    cur_arc = p.arc_for(n)
    cur_part = p.part_for(n)
    arc_start = cur_arc.start_ep if cur_arc else n
    part_start = cur_part.start_ep if cur_part else 1
    out: list[str] = []

    def arc_text(a) -> str:
        if a.summary:
            return f"[아크 {a.number} {a.title} ({a.start_ep}~{a.end_ep}화)] {a.summary}"
        inside = [line(e) for e in eps if a.start_ep <= e.plot.number <= a.end_ep]
        return f"[아크 {a.number} {a.title} ({a.start_ep}~{a.end_ep}화)]\n" + "\n".join(inside)

    for part in sorted(p.parts, key=lambda x: x.start_ep):
        if part.end_ep >= part_start:
            break
        if part.summary:
            out.append(f"[{part.number}부 {part.title} ({part.start_ep}~{part.end_ep}화)] {part.summary}")
        else:
            out += [arc_text(a) for a in p.story_arcs if part.start_ep <= a.start_ep <= part.end_ep]
    if not p.parts:
        part_start = 1
    out += [arc_text(a) for a in sorted(p.story_arcs, key=lambda a: a.start_ep) if part_start <= a.start_ep and a.end_ep < arc_start]
    tail = [e for e in eps if e.plot.number >= arc_start]
    if n - arc_start < 3:  # 아크 첫머리에는 직전 아크의 마지막 화들도 이어서 본다
        tail = [e for e in eps if arc_start - 3 <= e.plot.number < arc_start] + tail
    if tail:
        out.append(f"[이번 아크{f' {cur_arc.number} {cur_arc.title}' if cur_arc else ''}]\n" + "\n".join(map(line, tail)))
    return "\n\n".join(out)


def structure_text(p: Project, n: int, head: str = "[지금 부와 아크]") -> str:
    """n화가 속한 부와 아크, 아크 안 기승전결. 장편 전용."""
    part, arc = p.part_for(n), p.arc_for(n)
    lines = []
    if part:
        lines.append(f"[{part.number}부 {part.title} ({part.start_ep}~{part.end_ep}화)]\n목표: {part.goal}\n전환점: {part.key_turn}")
    if arc:
        lines.append(dump(arc.model_dump(exclude={"summary"}) | {"title": f"아크 {arc.number} {arc.title}"}))
    return head + "\n" + ("\n".join(lines) or "아직 없음")


KNOWS_RECENT = 20  # 장편: 인물이 알게 된 정보는 최근 것만 넣는다 (확정 사실과 줄거리에 남아 있다)


def state_view(p: Project, states: list) -> list:
    """장편에서는 화마다 쌓이는 knows 를 최근 것만 남긴 사본을 쓴다. 저장된 상태는 그대로다."""
    if not p.serial:
        return states
    return [s.model_copy(update={"knows": s.knows[-KNOWS_RECENT:]}) if len(s.knows) > KNOWS_RECENT else s for s in states]


def static_characters(p: Project) -> list[Character]:
    """앞 블록(캐시)에 늘 넣는 인물. 예전 작품은 모두 주역이라 지금과 같다."""
    return [c for c in p.characters if c.tier == "main"]


def roster_line(p: Project, exclude: set[str]) -> str:
    """설정 전체를 넣지 않는 인물의 한 줄 목록. 플롯이 이미 있는 인물을 다시 만들지 않게 한다."""
    return ", ".join(f"{c.id}: {c.name}({c.role})" for c in p.characters if c.tier != "main" and c.id not in exclude)


def relevant_foreshadows(p: Project, n: int) -> tuple[list[Foreshadow], int]:
    """n화에 넣을 열린 복선과 뺀 개수. 단편은 전부. 장편은 이번 아크에 회수할 것, 회수 예정이 지난 것,
    작품 단위 복선, 최근에 심은 것만 넣는다."""
    opened = [f for f in p.foreshadows if f.status == "open"]
    if not p.serial:
        return opened, 0
    arc = p.arc_for(n)
    end = arc.end_ep if arc else n
    lo = arc.start_ep if arc else n

    def keep(f: Foreshadow) -> bool:
        return ((arc is not None and f.id in arc.payoffs) or (f.due_ep is not None and f.due_ep <= end)
                or f.scope == "series" or f.planted_ep >= min(lo, n - FORESHADOW_RECENT))

    picked = [f for f in opened if keep(f)][-FORESHADOW_CAP:]
    return picked, len(opened) - len(picked)


def relevant_facts(p: Project, cast: set[str]) -> tuple[list[str], int]:
    """확정 사실이 많으면 이번 화 인물 이름이 들어간 것과 최근 것만 넣는다."""
    if len(p.facts) <= FACTS_FILTER_FROM:
        return p.facts, 0
    names = [c.name for c in p.characters if c.id in cast and c.name]
    recent = set(p.facts[-FACTS_RECENT:])
    picked = [f for f in p.facts if f in recent or any(nm in f for nm in names)]
    return picked, len(p.facts) - len(picked)


def series_prompt(p: Project) -> str:
    total = p.meta.target_episodes
    return f"""아래 작품을 총 {total}화 장편 연재로 기획합니다. 작품 전체를 부(권, 시즌)로 나누세요.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{dump(static_characters(p))}
[관계]
{rels(p)}
[지금 부 구성]
{dump(p.parts) if p.parts else "아직 없음"}

요구사항:
- 부는 1화부터 {total}화까지 빈틈없이 이어지고 number 는 1부터 차례대로입니다. 부 하나는 보통 50~150화입니다.
- 부가 바뀔 때 무대, 상대, 걸린 것의 크기가 한 단계씩 커지게 합니다. 같은 크기의 갈등을 되풀이하지 않습니다.
- goal 은 그 부가 끝날 때 이야기가 도달해야 하는 상태, key_turn 은 부를 마무리하는 큰 사건이나 드러나는 비밀입니다.
- 주인공의 arc 와 작품의 theme 은 마지막 부에서 완성됩니다. 가장 큰 비밀은 부마다 조금씩 드러냅니다.
- arc_ideas 에는 그 부에서 다룰 아크(5~30화짜리 작은 이야기) 후보를 순서대로 3~8개 한 줄씩 적습니다. 화별 플롯은 쓰지 않습니다.
- summary 는 비워 둡니다."""


def next_arc_prompt(p: Project, start: int, length: int, note: str) -> str:
    part = p.part_for(start)
    limit = part.end_ep if part else p.meta.target_episodes
    opened = sorted((f for f in p.foreshadows if f.status == "open"), key=lambda f: f.planted_ep)
    fs_lines = "\n".join(
        f"- {f.id} ({f.planted_ep}화에 심음, {f.scope}{f', {f.due_ep}화 회수 예정' if f.due_ep else ''}"
        f"{', 오래됨' if start - f.planted_ep > 50 else ''}): {f.description}" for f in opened)
    prev = max(p.story_arcs, key=lambda a: a.start_ep) if p.story_arcs else None
    prev_eps = [e.plot for e in p.episodes if prev and prev.start_ep <= e.plot.number <= prev.end_ep][-3:]
    size = f"{length}화 안팎" if length else "내용에 맞게 5~30화 (보통 10~25화). 첫 아크는 25화 안에 큰 보상이 오도록 짧고 세게"
    return f"""장편 연재의 다음 아크 하나를 기획하세요. 이 아크는 {start}화에서 시작합니다.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[주역]
{dump(static_characters(p))}
[다른 인물 (id: 이름, 역할)]
{roster_line(p, set()) or "없음"}
[관계]
{describe_relations(p) or rels(p)}
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[인물 현재 상태]
{dump([s for s in p.states if s.character_id in {c.id for c in static_characters(p)}]) or "설정 그대로"}
[부 구성]
{dump(p.parts) if p.parts else "부 구성 없음 (작품 전체가 한 부)"}

[지금까지의 줄거리]
{story_so_far(p, start) or "없음 (첫 아크)"}
[직전 아크]
{dump(prev.model_dump(exclude={"summary"})) if prev else "없음"}
[직전 아크의 마지막 화 플롯]
{dump(prev_eps) if prev_eps else "없음"}
[열린 복선]
{fs_lines or "없음"}
[확정된 사실 (최근)]
{chr(10).join("- " + f for f in p.facts[-FACTS_RECENT:]) or "없음"}
[작가의 요청]
{note.strip() or "없음"}

요구사항:
- arc.number 는 {len(p.story_arcs) + 1}, start_ep 는 {start}, end_ep 는 {limit} 이하입니다. 길이는 {size}.
- 지금 부의 goal 과 arc_ideas 중 아직 다루지 않은 것을 따라가되, 지금까지 실제로 쓰인 줄거리에 맞게 고칩니다.
- 아크는 하나의 문제를 열고 해결합니다. goal 은 아크가 끝날 때 바뀌어 있어야 하는 것, conflict 는 주인공을 막는 문제나 상대, payoff 는 아크 클라이맥스에서 독자가 받는 보상(사이다)입니다.
- acts 는 아크 안의 기승전결로, {start}화부터 end_ep 까지 기, 승, 전, 결 순서로 빈틈없이 이어집니다. 마지막 1~2화는 정리와 다음 아크 떡밥에 씁니다.
{"- 첫 아크입니다. 기 구간은 소개가 아니라 발단으로, 1화에 사건이 시작되고 1~3화 안에 주인공의 결핍, 작품의 핵심 장치, 작은 보상 하나가 나옵니다." + chr(10) if start == 1 else ""}- 직전 아크와 같은 모양의 갈등을 되풀이하지 않습니다. 걸린 것이나 상대가 조금씩 커지게 합니다.
- payoffs 에는 이 아크에서 회수할 열린 복선 id 를 넣습니다. '오래됨' 표시가 있는 복선은 회수하거나 아크 안에서 다시 떠올립니다.
- cast 에는 이 아크에 주로 나오는 인물 id 를 넣습니다. 새 인물이 필요하면 new_characters 에 전체 설정(speech_style 포함)을 넣고 tier 는 support 나 minor 로 둡니다. 이미 있는 인물을 다시 만들지 않습니다.
- reply 에는 왜 이 아크인지, 어떤 복선을 회수하고 무엇을 다음으로 남기는지 2~4문장으로 씁니다.
- summary 는 비워 둡니다."""


def recap_prompt(p: Project, kind: str, number: int) -> str:
    if kind == "arc":
        a = next(x for x in p.story_arcs if x.number == number)
        body = "\n".join(f"{e.plot.number}화 {e.plot.title}: {e.summary}" for e in p.episodes
                         if a.start_ep <= e.plot.number <= a.end_ep and e.summary)
        what, size = f"아크 {a.number} {a.title} ({a.start_ep}~{a.end_ep}화)", "5~8문장, 600자 안팎"
        plan = dump(a.model_dump(exclude={"summary", "acts"}))
    else:
        x = next(x for x in p.parts if x.number == number)
        arcs = [a for a in p.story_arcs if x.start_ep <= a.start_ep <= x.end_ep]
        body = "\n\n".join(
            f"[아크 {a.number} {a.title}] " + (a.summary or " ".join(
                e.summary for e in p.episodes if a.start_ep <= e.plot.number <= a.end_ep and e.summary)) for a in arcs)
        what, size = f"{x.number}부 {x.title} ({x.start_ep}~{x.end_ep}화)", "8~12문장, 1,000자 안팎"
        plan = dump(x.model_dump(exclude={"summary", "arc_ideas"}))
    return f"""{what} 이(가) 끝났습니다. 아래 화별 요약만 근거로 이 구간의 요약을 쓰세요.
이 요약은 앞으로 수십 화 동안 이 구간 본문 대신 프롬프트에 들어갑니다.

[기획]
{plan}
[화별 요약 (작가가 승인한 것)]
{body or "없음"}

요구사항:
- {size}. 일어난 순서대로 씁니다.
- 반드시 남길 것: 인물 관계가 바뀐 계기, 드러난 비밀, 새로 생긴 약속이나 빚, 아직 풀리지 않은 문제, 주인공이 얻거나 잃은 것.
- 화별 요약에 없는 내용은 만들지 않습니다. 해석이나 평가는 쓰지 않습니다."""


# ---------- 이야기 줄기 제안 ----------

STORYLINE_PLOTS = 60  # 줄기 제안 때 넣는 아직 안 쓴 화 플롯 수 (장편에서 크기를 묶는다)


def storyline_prompt(p: Project, note: str, kind: str) -> str:
    written = max((e.plot.number for e in p.episodes if e.text), default=0)
    upcoming = [e.plot for e in sorted(p.episodes, key=lambda e: e.plot.number) if not e.text][:STORYLINE_PLOTS]
    brief = [{"number": x.number, "title": x.title, "summary": x.summary, "characters": x.characters,
              "storyline": x.storyline, "threads": x.threads} for x in upcoming]
    structure = structure_text(p, written + 1) if p.serial else f"[기승전결 구조]\n{dump(p.arc) or '아직 없음'}"
    return f"""이 작품의 메인 줄기에서 갈라졌다 다시 합류하는 이야기 줄기 하나를 기획하세요.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[주역]
{dump(static_characters(p))}
[다른 인물 (id: 이름, 역할)]
{roster_line(p, set()) or "없음"}
[관계]
{describe_relations(p) or rels(p)}
[비밀 (hidden_from 의 인물은 아직 모른다)]
{dump(p.secrets) or "없음"}
[이야기 요소]
{elements.plan_block(p) or "없음"}
[지금 이야기 줄기]
{storylines.plan_block(p) or "없음"}

{structure}

[지금까지의 줄거리 ({written}화까지 씀)]
{story_so_far(p, written + 1) or "없음 (아직 쓴 화 없음)"}
[아직 안 쓴 화 플롯 (줄기를 붙일 수 있는 화)]
{dump(brief) if brief else "없음"}
[열린 복선]
{dump([f for f in p.foreshadows if f.status == "open"][-FORESHADOW_CAP:]) or "없음"}
[작가의 요청]
{note.strip() or "없음"}{f"{chr(10)}[원하는 종류] {kind}" if kind else ""}

요구사항:
- kind 는 서브플롯(메인과 같은 시간에 다른 인물이나 다른 곳에서 진행), 과거 회상(인물의 과거를 보여 줌), 외전(본편 밖의 시간이나 인물), 인물 이야기(조연 한 명을 깊게 다룸) 중 하나입니다.
- 이미 있는 줄기와 겹치지 않게 하고, 비밀, 열린 복선, 인물의 결핍(wound)처럼 메인이 이미 품고 있는 것에서 출발합니다.
- focus 에는 중심 인물 id 를 넣습니다. when 은 메인과 다른 시점일 때만 적습니다 (예: 10년 전).
- branch_ep 는 메인에서 이 줄기를 부르는 계기(물건, 말, 장소, 만남)가 나오는 화, join_ep 는 줄기가 끝나고 메인으로 돌아오는 화입니다. rejoin 에는 합류할 때 메인에 남기는 것(드러난 비밀, 바뀐 관계, 얻거나 잃은 것)을 적습니다.
- episodes 에는 이 줄기를 주로 따라갈 화를, threads 에는 메인 화 안에 이 줄기 장면을 끼워 넣을 화를 위 '아직 안 쓴 화' 중에서 고릅니다. 메인을 따라가는 독자가 지치지 않게 줄기 화를 연달아 세 화 넘게 두지 않습니다. 서브플롯은 장면으로 나눠 끼우는 편이 낫습니다.
- 고른 화의 플롯 내용은 이번에 바꾸지 않습니다. 작가가 줄기를 반영한 뒤 플롯을 다시 다듬습니다.
- id 는 아무 값이나 두면 프로그램이 다시 매깁니다. summary 는 비워 둡니다.
- reply 에는 왜 이 줄기인지, 어디서 갈라져 어디서 합류하며 메인에 무엇을 남기는지 2~4문장으로 씁니다."""


# ---------- 단편 → 장편 전환 ----------

CONVERT_TAIL = 1500  # 단편 마지막 화 본문 끝부분. 결말을 어떻게 닫았는지 원문으로 본다

ENDING_GUIDE = {
    "keep": """결말 처리: 닫고 다음 이야기로 (ending = keep).
- 단편의 결말은 아크 1의 결말로 그대로 둡니다. 결말에서 해결된 것을 되돌리지 않습니다.
- 장편의 다음 갈등은 결말 뒤에 새로 생긴 문제에서 시작합니다. 결말에서 얻은 것(힘, 관계, 지위, 진실)이 다음 문제의 원인이 되게 하면 이어 읽힙니다.
- facts 와 episodes 는 보통 비워 둡니다.""",
    "reopen": """결말 처리: 결말 다시 열기 (ending = reopen).
- 단편의 결말이 진짜 끝이 아니었다는 장치를 씁니다: 거짓 승리, 드러나지 않은 배후, 치르지 않은 대가, 풀리지 않은 비밀 가운데 이 이야기에 맞는 것.
- 이미 쓴 본문과 모순되면 안 됩니다. 본문이 있는 화는 바꾸지 않고, 장치는 foreshadows(근거가 되는 화를 planted_ep 로)와 facts 로 겁니다.
- 본문이 아직 없는 화는 episodes 에 전체 플롯을 넣어 결말을 열어 둘 수 있습니다. 바꾸는 화만 넣습니다.""",
    "": """결말 처리: 아래 둘 중 이 이야기에 맞는 쪽을 고르고 ending 에 적으세요.
- keep(닫고 다음 이야기로): 결말은 그대로 두고, 결말 뒤에 새로 생긴 문제로 장편을 잇습니다. 결말에서 얻은 것이 다음 문제의 원인이 되게 합니다.
- reopen(결말 다시 열기): 결말이 진짜 끝이 아니었다는 장치(거짓 승리, 배후, 대가, 풀리지 않은 비밀)로 큰 갈등을 다시 엽니다.
  이미 쓴 본문과 모순되지 않게, 본문이 있는 화는 바꾸지 않고 foreshadows 와 facts 로 겁니다. 본문이 없는 화는 episodes 에 바뀐 전체 플롯을 넣을 수 있습니다.""",
}


def convert_prompt(p: Project, total: int, ending: str, note: str) -> str:
    """단편 → 장편 전환 제안. 단편은 화가 적어 화별 요약과 플롯을 모두 넣는다."""
    end = max((a.end_ep for a in p.arc), default=0)
    locked = [e for e in p.episodes if e.status in ("written", "finalized")]
    last = max(locked, key=lambda e: e.plot.number) if locked else None
    open_plots = [e.plot for e in p.episodes if e.status not in ("written", "finalized")]
    done = all(e.status == "finalized" for e in p.episodes) and len(p.episodes) >= end > 0
    opened = [f for f in p.foreshadows if f.status == "open"]
    tail = last.text[-CONVERT_TAIL:] if last else ""
    return f"""아래 단편({end or p.meta.target_episodes}화)을 총 {total}화 장편 연재로 늘리려 합니다. 전환 계획을 세우세요.
단편 전체(1~{end}화)는 그대로 장편의 아크 1이 됩니다. 이미 쓴 본문, 인물, 관계, 문체는 바꾸지 않습니다.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{dump(p.characters)}
[관계]
{describe_relations(p) or rels(p)}
[이야기 요소 (작가가 더한 설정과 사건)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[인물 현재 상태]
{dump(p.states) or "설정 그대로"}
[단편의 기승전결 (아크 1이 됨)]
{dump(p.arc) if p.arc else "없음"}
[지금까지의 줄거리 (작가가 승인한 화별 요약)]
{story_so_far(p, (end or p.meta.target_episodes) + 1) or "아직 없음"}
[본문이 없는 화의 플롯]
{dump(open_plots) if open_plots else "없음 (모두 썼음)"}
[마지막으로 쓴 {last.plot.number if last else 0}화 끝부분]
{tail or "없음"}
[열린 복선]
{chr(10).join(f"- {f.id} ({f.planted_ep}화에 심음, {f.scope}): {f.description}" for f in opened) or "없음"}
[확정된 사실]
{chr(10).join("- " + f for f in p.facts) or "없음"}
[작가의 요청]
{note.strip() or "없음"}

{ENDING_GUIDE.get(ending, ENDING_GUIDE[""])}

요구사항:
- total_episodes 는 {total} 입니다.
- arc 는 아크 1입니다. number 1, start_ep 1, end_ep {end}. title, goal, conflict, payoff, cast 는 단편에서 실제로 일어난 일로 채웁니다. acts 와 payoffs 는 비워 둡니다.
- arc.summary 는 {"화별 요약만 근거로 5~8문장, 600자 안팎으로 씁니다. 관계가 바뀐 계기, 드러난 비밀, 남은 문제를 남깁니다" if done else "비워 둡니다 (아직 다 쓰지 않았습니다)"}.
- parts 는 1화부터 {total}화까지 빈틈없이 이어지고 number 는 1부터 차례대로입니다. 부 하나는 보통 50~150화이고, 1부는 아크 1을 품어 {end}화보다 뒤에서 끝납니다.
- 부가 바뀔 때 무대, 상대, 걸린 것의 크기가 한 단계씩 커지게 합니다. 단편의 theme 은 마지막 부에서 완성됩니다.
- arc_ideas 에는 그 부의 아크(5~30화짜리 작은 이야기) 후보를 순서대로 3~8개 한 줄씩 적습니다. 1부는 아크 2부터 적습니다. 새 인물이 필요하면 "새 인물: 역할" 을 그 아크 줄에 함께 적습니다. summary 는 비워 둡니다.
- foreshadows 에는 장편 전체나 한 부를 끌고 갈 새 장기 떡밥 2~5개를 넣습니다. id 는 "fs-s-" 로 시작하고, scope 는 part 나 series, status 는 open, planted_ep 는 실마리가 이미 있는 화({end}화 이하)입니다.
- scopes 에는 열린 복선 가운데 장편에서 더 멀리 끌고 갈 것만 넣습니다.
- tiers 는 장편에서 비중이 달라지는 인물만 넣습니다. main 은 작품 전체를 끌고 갈 2~4명, 나머지는 support 나 minor 입니다.
- episodes 에는 본문이 없는 화만 넣고, 모든 칸을 채웁니다.
- reply 는 3~5문장: 결말을 어떻게 처리했는지, 장편 전체를 끄는 갈등이 무엇인지, 1부가 어디서 끝나는지."""


# ---------- 단편 → 장편 재구성 ----------

ENDING_AT = {
    "arc": "단편의 결말(클라이맥스와 해결)을 첫 아크 끝으로 옮깁니다. 첫 아크는 단편의 갈등을 다 풀고, 다음 아크부터 새 문제가 시작됩니다.",
    "part": "단편의 결말을 1부 끝으로 미룹니다. 단편의 중심 갈등이 1부 전체를 끌고, 앞 아크들은 그 갈등의 단계가 됩니다. 이번에 짜는 앞부분에는 결말이 들어가지 않을 수 있습니다.",
    "series": "단편의 결말을 작품의 결말로 미룹니다. 단편의 중심 갈등은 작품 전체의 큰 줄기가 되고, 앞부분은 그 줄기를 여는 데 씁니다. 단편 결말 장면은 이번에 짜는 앞부분에 넣지 않습니다.",
    "": "단편의 결말을 첫 아크 끝(arc), 1부 끝(part), 작품 끝(series) 가운데 이 이야기에 맞는 곳으로 옮기고 ending_at 에 적으세요.",
}


def rebuild_prompt(p: Project, total: int, span: int, ending_at: str, note: str) -> str:
    """단편을 씨앗으로 장편 앞부분을 다시 짜는 제안. 단편은 화가 적어 옛 화 전부를 넣는다."""
    old = sorted(p.episodes, key=lambda e: e.plot.number)
    rows = "\n".join(
        f"- {e.plot.number}화 {e.plot.title} [{'본문 있음' if e.text else '본문 없음'}, {len(e.text):,}자]: "
        f"{e.summary or e.plot.summary} / 엔딩 훅: {e.plot.ending_hook}" for e in old)
    return f"""아래 단편({len(old)}화)을 총 {total}화 장편 연재로 다시 짭니다. 단편을 그대로 이어 쓰지 않고, 단편을 씨앗으로 장편의 앞부분 1~{span}화를 새로 설계하세요.
옛 화마다 새 화 어디에 어떻게 쓸지 정합니다. 인물, 관계, 세계관, 문체는 그대로입니다.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{dump(p.characters)}
[관계]
{rels(p)}
[이야기 요소 (작가가 더한 설정과 사건)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[단편의 기승전결]
{dump(p.arc) if p.arc else "없음"}
[단편의 화 (번호, 제목, 요약, 엔딩 훅)]
{rows}
[작가의 요청]
{note.strip() or "없음"}

결말 위치: {ENDING_AT.get(ending_at, ENDING_AT[""])}

요구사항:
- total_episodes 는 {total} 입니다. arcs 는 1화부터 {span}화까지 빈틈없이 이어지는 아크 2~5개입니다. 아크 하나는 5~30화이고, 아크마다 acts 에 기, 승, 전, 결 네 구간을 빈틈없이 채웁니다. 아크마다 goal, conflict, payoff, cast 를 적습니다.
- episodes 는 1화부터 {span}화까지 한 화도 빠짐없이 한 줄씩 적습니다. title 과 summary(2~3문장)는 새 화 기준입니다.
- 옛 화는 보통 새 2~4화로 늘어납니다. 단편에서 한 문단으로 지나간 장면, 인물 소개, 관계가 바뀌는 계기, 세계관을 보여 줄 사건을 화 단위로 키웁니다. 단편에 없던 사건과 인물도 넣을 수 있습니다.
- 웹소설 연재 첫머리 규칙: 1화 안에 주인공과 이 작품의 핵심 사건(또는 능력, 계약, 비밀)을 보여 주고, 1~3화는 매 화 다음 화를 누르게 하는 훅으로 끝냅니다. 단편의 느린 도입은 뒤로 미루거나 줄입니다.
- 화마다 use 를 정합니다. keep 은 옛 화 본문을 그대로 쓸 수 있을 때만(옛 화 하나, 새 자리에서도 앞뒤가 맞을 때), revise 는 옛 화 본문을 살리되 고칠 것이 있을 때(note 에 무엇을 고칠지), rewrite 는 옛 화를 재료로 새로 쓸 때(note 에 무엇을 살릴지), new 는 새 화입니다. 옛 화 하나의 본문은 keep 이나 revise 로 한 번만 씁니다. sources 에는 그 화에 쓰는 옛 화 번호를 넣습니다.
- 본문이 없는 옛 화는 keep 이나 revise 로 쓸 수 없습니다. 쓰지 않는 옛 화는 dropped 에 넣습니다.
- parts 는 1화부터 {total}화까지 빈틈없이 이어지는 부 구성이고, 위 아크들이 부 경계를 넘지 않게 합니다. 부 하나는 보통 50~150화입니다. arc_ideas 에는 {span}화 뒤에 올 아크 후보를 순서대로 적고, 새 인물이 필요하면 "새 인물: 역할" 을 함께 적습니다. summary 는 비워 둡니다.
- foreshadows 에는 장편 전체나 한 부를 끌고 갈 새 장기 떡밥 2~5개를 넣습니다. id 는 "fs-r-" 로 시작하고, scope 는 part 나 series, planted_ep 는 그 떡밥을 심을 새 화 번호입니다.
- tiers 는 장편에서 비중이 달라지는 인물만 넣습니다. main 은 작품 전체를 끌고 갈 2~4명입니다.
- reply 는 3~5문장: 단편을 어떻게 늘렸는지, 결말을 어디로 옮겼는지, 1~3화 훅이 무엇인지."""


def rework_prompt(p: Project, n: int) -> str:
    """재구성에서 '다듬기'로 고른 화: 옛 본문을 새 자리(앞뒤 화, 새 플롯)에 맞게 최소로 고친다."""
    x = p.archive.entry(n) if p.archive else None
    ep = p.episode(n)
    return (build_episode_context(p, n) + f"""

# 고칠 원고 (단편 {x.sources[0] if x and x.sources else "?"}화였던 본문, 지금은 {n}화)
{ep.text}

# 고칠 것
{(x.note if x else "") or "새 자리의 앞뒤 화와 이번 화 플롯에 맞게"}

위 원고를 {n}화로 고쳐 text 에 본문 전체를 쓰세요.
- 원고의 문장과 장면은 되도록 살리고, 고칠 것과 앞뒤 화 · 플롯 · 확정 사실과 어긋나는 부분만 바꿉니다.
- 앞 화에서 이미 보여 준 소개나 설명은 줄이고, 아직 나오지 않은 인물이나 정보는 꺼내지 않습니다.
- 끝은 이번 화 플롯의 ending_hook 으로 맞춥니다. 문체는 스타일 프로필을 따릅니다.
- reply 에는 무엇을 고쳤는지 2~3문장으로 씁니다.""")


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
    if p.serial:
        return serial_plot_chat_prompt(p, message)
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
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
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
{plot_rules(p, opening_pending(p))}"""


def serial_plot_chat_prompt(p: Project, message: str) -> str:
    """장편: 고칠 대상은 아직 본문이 없는 첫 아크(pipeline.focus_arc)와 그 뒤에 기획한 아크다. 앞선 내용은 접은 줄거리로 본다."""
    from .pipeline import focus_arc

    focus = focus_arc(p)
    lo = focus.start_ep if focus else 1
    eps = [{"status": e.status, **e.plot.model_dump()} for e in p.episodes if e.plot.number >= lo - 2]
    locked = [e.plot.number for e in p.episodes if e.status in ("written", "finalized") and e.plot.number >= lo]
    confirmed = [e.plot.number for e in p.episodes if e.status == "confirmed"]
    history = next((c.messages for c in p.chats if c.topic == "plot"), [])[-CHAT_HISTORY_LIMIT:]
    fs, more = relevant_foreshadows(p, lo)
    arcs = [a.model_dump(exclude={"summary"}) for a in p.story_arcs if a.end_ep >= lo]
    return f"""[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[주역]
{dump(static_characters(p))}
[다른 인물 (id: 이름, 역할)]
{roster_line(p, set()) or "없음"}
[관계]
{rels(p)}
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[부 구성]
{dump(p.parts) if p.parts else "부 구성 없음"}

[지금까지의 줄거리]
{story_so_far(p, lo) or "없음"}
[고칠 수 있는 아크] 구조(acts)를 바꾸면 아크 {focus.number if focus else "?"}({focus.start_ep if focus else "?"}~{focus.end_ep if focus else "?"}화)의 기승전결 네 구간입니다
{dump(arcs) if arcs else "아직 없음"}
[화별 플롯] status: draft 초안, confirmed 작가가 확정, written 본문 있음, finalized 반영 완료
{dump(eps) if eps else "아직 없음"}
[열린 복선]{f" (그 밖에 {more}개)" if more else ""}
{dump(fs) or "없음"}

[지금까지의 대화]
{chr(10).join(_chat_line(m) for m in history) or "없음 (첫 대화)"}

[작가의 새 말]
{message}

요구사항:
- reply 에는 작가에게 하는 대답을 2~5문장으로 씁니다. 무엇을 왜 바꿨는지, 다른 화에 어떤 영향이 있는지 말합니다.
- 요청이 모호하면 가장 그럴듯한 해석으로 고치고, reply 에서 어떻게 해석했는지 밝힙니다. 고칠 것이 없거나 질문만 받았으면 변경 없이 대답만 합니다.
- 바꾸는 것만 넣습니다. acts 는 위 아크의 기승전결을 바꿀 때만 네 구간 모두, 그대로면 빈 목록입니다. episodes 에는 바뀌는 화만, 모든 칸을 채운 전체 플롯으로 넣습니다.
- 장편이라 total_episodes 는 늘 0 입니다. 아크를 새로 만들거나 길이를 바꾸는 것은 다음 아크 기획에서 합니다.
- 본문이 있는 화({", ".join(map(str, locked)) or "없음"})는 바꾸지 않습니다. 기획한 아크 밖의 화({p.planned_until() + 1}화부터)는 만들지 않습니다.
- 작가가 확정한 화({", ".join(map(str, confirmed)) or "없음"})는 작가가 그 화를 바꿔 달라고 했을 때만 바꿉니다.
- 한 화를 바꾸면 앞뒤 화의 엔딩 훅, 복선 심기와 회수가 어긋나지 않게 이어지는 화도 함께 고칩니다.
{plot_rules(p, opening_pending(p))}"""


# ---------- 본문 부분 수정 (집필 화면에서 고른 부분) ----------

_REVISER = (
    "당신은 작가 곁에서 원고를 다듬는 소설가입니다. 작가가 고른 부분만 다시 쓰고, 앞뒤 본문에 그대로 이어 붙을 글을 냅니다. "
    "스타일 프로필과 문체 예시를 따르고, 인물 설정과 현재 상태, 확정된 사실을 어기지 않습니다. "
    "작가가 바꾸라고 하지 않은 사건과 사실은 바꾸지 않습니다. 모든 출력은 한국어로 작성합니다.\n\n"
)
SYSTEM_REVISER = _REVISER + PROSE_RULES


def reviser_system(p: Project) -> str:
    return _REVISER + prose_rules(styled(p))


# 빠른 요청: id → (버튼 이름, AI 에게 하는 말). 화면(passage.js)은 서버가 준 목록을 그대로 쓴다.
PASSAGE_PRESETS: dict[str, tuple[str, str]] = {
    "longer": ("더 길게", "이 부분을 1.5~2배로 풀어 써 주세요. 사건을 더하지 말고 행동, 감각, 대사로 장면을 늘립니다."),
    "shorter": ("더 짧게", "뜻과 사건은 그대로 두고 절반에서 3분의 2 길이로 줄여 주세요. 설명과 겹치는 묘사부터 덜어 냅니다."),
    "dialogue": ("대사 늘리기", "서술로 넘긴 부분을 인물의 대사와 짧은 행동으로 바꿔 주세요. 말투는 인물 설정의 speech_style 을 따릅니다."),
    "less_ai": ("쇠맛 줄이기", "AI 가 쓴 티가 나는 표현을 덜어 주세요. 감정 이름, 정리하는 문장, 번역투, 셋씩 나열, 여운을 노린 짧은 끝 문장을 구체적인 행동과 사물로 바꿉니다."),
    "style": ("문체에 맞게", "스타일 프로필과 문체 예시에 맞춰 다시 써 주세요. 시점, 시제, 문장 리듬, 대사 처리 방식을 맞춥니다."),
}
PASSAGE_FULL_LIMIT = 12_000  # 본문이 이보다 짧으면 통째로 넣고, 길면 고른 부분 앞뒤만 넣는다
PASSAGE_BEFORE, PASSAGE_AFTER = 4_000, 2_000
PASSAGE_HISTORY = 6  # 같은 화 부분 수정 대화에서 넣는 최근 메시지 수


def passage_request(message: str, preset: str) -> str:
    """작가의 말. 빠른 요청을 골랐으면 그 지시를 앞에 둔다."""
    parts = [PASSAGE_PRESETS[preset][1]] if preset in PASSAGE_PRESETS else []
    if message.strip():
        parts.append(message.strip())
    return " ".join(parts)


def _passage_line(m: ChatMessage) -> str:
    if m.role == "user":
        quote = m.selection.text if m.selection else ""
        label = PASSAGE_PRESETS[m.preset][0] if m.preset in PASSAGE_PRESETS else ""
        said = f"[{label}] " + (m.text if m.text != label else "") if label else m.text
        return f"작가: {said.strip()}" + (
            f"\n  (고른 부분: {quote[:120]}{'…' if len(quote) > 120 else ''})" if quote else "")
    line = f"편집자: {m.text}"
    if m.passage and m.passage.candidates:
        picked = {"applied": f"작가가 {int(m.applied[0]) + 1}번 후보를 넣음" if m.applied else "작가가 넣음",
                  "dismissed": "작가가 모두 버림"}.get(m.outcome, "아직 고르지 않음")
        line += f"\n  (후보 {len(m.passage.candidates)}개 / {picked})"
    return line


def passage_prompt(p: Project, n: int, sel: Selection, message: str, preset: str = "") -> str:
    """앞쪽은 작품 설정(캐시), 뒤쪽은 이번 화 데이터와 본문, 대화, 요청. 본문 쓰기와 같은 순서를 지킨다."""
    ep = p.episode(n)
    text = ep.text
    start, end = sel.start, sel.start + len(sel.text)
    if len(text) <= PASSAGE_FULL_LIMIT:
        before, after, cut = text[:start], text[end:], ""
    else:
        before, after = text[max(0, start - PASSAGE_BEFORE):start], text[end:end + PASSAGE_AFTER]
        cut = " (고른 부분 앞뒤만)"
    cast_ids = set(ep.plot.characters) or {c.id for c in static_characters(p)} or {c.id for c in p.characters}
    states = [s for s in p.states if s.character_id in cast_ids]
    extra = [c for c in p.characters if c.id in cast_ids and c.tier != "main"]
    facts, facts_cut = relevant_facts(p, cast_ids)
    els = elements.episode_block(p, n)
    chat = next((c for c in p.chats if c.topic == f"text:{n}"), None)
    history = "\n".join(_passage_line(m) for m in (chat.messages[-PASSAGE_HISTORY:] if chat else []))
    hits = [f"{name} {cnt}회" for name, cnt in metrics.pattern_counts(sel.text).items() if cnt] if preset == "less_ai" else []
    request = passage_request(message, preset) or "더 낫게 다듬어 주세요."
    return f"""{static_context(p)}

# 확정된 사실{f" (이번 화와 관련된 것만, {facts_cut}개 생략)" if facts_cut else ""}
{chr(10).join("- " + f for f in facts) or "없음"}{f"{chr(10)}{chr(10)}# 이야기 요소 (이번 화와 관련된 설정, 어기지 말 것){chr(10)}{els}" if els else ""}
{f"{chr(10)}# 이번 화에 나오는 조연 · 단역 설정{chr(10)}{dump(extra)}{chr(10)}" if extra else ""}
# 인물 현재 상태 ({n - 1}화 종료 시점)
{dump(state_view(p, states)) or "1화 시작 시점, 설정 그대로"}

# 이번 화 플롯
{dump(ep.plot)}

# {n}화 본문{cut}. 【고칠 부분】부터 【여기까지】를 고칩니다
{before}【고칠 부분】{sel.text}【여기까지】{after}

# 이 화 부분 수정 대화 (최근)
{history or "없음"}

# 작가의 요청
{request}
{f"고른 부분에서 찾은 쇠맛 패턴: {', '.join(hits)}" if hits else ""}
요구사항:
- candidates 의 text 에는 【고칠 부분】 자리에 들어갈 글만 씁니다. 표시 기호와 앞뒤 본문은 넣지 않습니다.
- 후보는 2~3개를 서로 다른 방향으로 냅니다. note 에 무엇을 바꿨는지 한 줄로 적습니다.
- 첫 문장은 바로 앞 본문에, 마지막 문장은 바로 뒤 본문에 자연스럽게 이어집니다. 앞뒤에 이미 있는 내용은 되풀이하지 않습니다.
- 작가가 요청하지 않은 사건, 사실, 인물의 행동과 결정은 바꾸지 않습니다. 확정 사실과 인물 설정을 어기지 않습니다.
- 대사는 인물 설정의 speech_style 을 따르고, 문단은 빈 줄로 나눕니다. 마크다운 기호는 쓰지 않습니다.
- reply 에는 후보들이 어떻게 다른지 1~3문장으로 적습니다. 요청이 모호하면 가장 그럴듯하게 해석하고 그렇게 해석했다고 밝힙니다."""


def build_episode_context(p: Project, n: int) -> str:
    """앞쪽은 화가 바뀌어도 그대로인 블록, 뒤쪽은 화마다 바뀌는 블록이다.
    Gemini 암묵적 캐시는 앞부분이 같은 요청에 적용되므로 이 순서를 지킨다.
    장편은 줄거리를 부 → 아크 → 화로 접고, 인물·복선·사실을 이번 화에 관련된 것만 골라 크기를 일정하게 둔다."""
    ep = p.episode(n)
    act = p.act_for(n)
    together = p.acts_for(n)[1:]  # 짧은 작품에서 이 화에 함께 들어간 뒤 구간
    cast_ids = set(ep.plot.characters) or {c.id for c in static_characters(p)} or {c.id for c in p.characters}
    states = [s for s in p.states if s.character_id in cast_ids]
    rels = [r for r in p.relationships if r.a in cast_ids and r.b in cast_ids]
    last_text = next((e.text for e in reversed(p.episodes) if e.plot.number == n - 1 and e.text), "")
    cast_names = ", ".join(f"{c.name}({c.id})" for c in p.characters if c.id in cast_ids)
    extra = [c for c in p.characters if c.id in cast_ids and c.tier != "main"]
    facts, facts_cut = relevant_facts(p, cast_ids)
    fs, fs_cut = relevant_foreshadows(p, n)
    if p.serial:
        where = structure_text(p, n, "# 현재 부와 아크") + f"\n현재 아크 안 구간: {act.name if act else '?'} ({act.start_ep if act else '?'}~{act.end_ep if act else '?'}화) 목표: {act.goal if act else ''}"
    else:
        where = f"""# 현재 구간: {act.name if act else "?"} ({act.start_ep if act else "?"}~{act.end_ep if act else "?"}화)
목표: {act.goal if act else ""}
전환점: {act.key_turn if act else ""}"""
        for b in together:
            where += f"""\n# 이 화에 이어서 들어갈 구간: {b.name} ({b.start_ep}~{b.end_ep}화)
목표: {b.goal}
전환점: {b.key_turn}"""
        if together:
            where += "\n한 화 안에서 위 구간들을 차례로 지나가도록 쓰세요."

    els = elements.episode_block(p, n)
    els = f"\n\n# 이야기 요소 (이번 화와 관련된 설정, 어기지 말 것)\n{els}" if els else ""
    line = storylines.episode_block(p, n)
    line = f"\n\n# 이번 화의 이야기 줄기\n{line}" if line else ""

    return f"""{static_context(p)}

# 확정된 사실{f" (이번 화와 관련된 것만, {facts_cut}개 생략)" if facts_cut else ""}
{chr(10).join("- " + f for f in facts) or "없음"}{els}

# 이번 화 등장 인물
{cast_names or "설정의 인물 전원"}
{f"{chr(10)}# 이번 화에 나오는 조연 · 단역 설정{chr(10)}{dump(extra)}{chr(10)}" if extra else ""}
# 인물 현재 상태 ({n - 1}화 종료 시점)
{dump(state_view(p, states)) or "1화 시작 시점, 설정 그대로"}

# 관계 현재 상태
{describe_relations(p, cast_ids) or dump(rels) or "없음"}

# 열린 복선{f" (이번 아크와 관련된 것만, {fs_cut}개 생략)" if fs_cut else ""}
{dump(fs) or "없음"}

# 지금까지의 줄거리
{story_so_far(p, n) or "없음 (첫 화)"}

{where}{line}

# 직전 화 마지막 부분 (내용 연결용, 문체 기준은 위의 예시 문단)
{last_text[-1500:] or "없음"}

# 이번 화 플롯
{dump(ep.plot)}{material_block(p, n)}"""


MATERIAL_LIMIT = 6000  # 원고 재료로 넣는 옛 화 하나의 본문 글자 수
MATERIAL_SOURCES = 3


def material_block(p: Project, n: int) -> str:
    """재구성에서 '새로 쓰기'로 고른 화: 옛 단편 본문을 원고 재료로 넣는다. 아직 본문이 없을 때만."""
    x = p.archive.entry(n) if p.archive else None
    if x is None or x.use != "rewrite" or p.episode(n).text:
        return ""
    parts = []
    for s in x.sources[:MATERIAL_SOURCES]:
        src = p.archive.source(s)
        if src and (src.text or src.summary or src.plot.summary):
            body = src.text[:MATERIAL_LIMIT] + ("\n(이하 생략)" if len(src.text) > MATERIAL_LIMIT else "") if src.text \
                else "(본문 없음. 단편 때 플롯) " + (src.summary or src.plot.summary)
            parts.append(f"## 단편 {s}화 {src.plot.title}\n{body}")
    if not parts:
        return ""
    return ("\n\n# 원고 재료 (재구성 전 단편 원고. 이번 화 플롯에 필요한 장면과 문장만 살리고, 플롯에 없는 사건은 가져오지 않는다)\n"
            + (f"살릴 것: {x.note}\n\n" if x.note else "") + "\n\n".join(parts))


def static_context(p: Project) -> str:
    """작품 내내 바뀌지 않는 블록: 작품 정보, 세계관, 문체, 인물 설정."""
    style = p.style
    samples = "\n\n---\n\n".join(style.sample_passages) or "없음"
    style_rules = style.model_dump(exclude={"markers"}) | {"sample_passages": []}  # 표지는 marker_block 이 따로 적는다
    return f"""# 작품 정보
{meta_text(p)}

# 세계관 (깨면 안 되는 규칙 포함)
{dump(p.world)}

# 스타일 프로필
{dump(style_rules)}{marker_block(p)}

# 문체 예시 (이 문체를 따를 것, 내용은 가져오지 말 것)
{samples}

# 인물 설정{" (주역. 조연 · 단역은 나오는 화에만 뒤에 넣는다)" if len(static_characters(p)) < len(p.characters) else ""}
{dump(static_characters(p))}"""


def marker_block(p: Project) -> str:
    """문체 표지와 원문 빈도를 한 화 분량 기준 횟수로 바꿔 적는다. 모델이 표지를 몰아 쓰지 않게 한다."""
    marks = [m for m in p.style.markers if m.text.strip()]
    if not marks:
        return ""
    size = p.meta.words_per_episode
    rows = []
    for m in marks:
        if m.per_1k:
            k = m.per_1k * size / 1000
            freq = f"한 화에 {k:.0f}번 안팎" if k >= 1 else "몇 화에 한 번"
        else:
            freq = "원문 빈도 모름, 가끔"
        rows.append(f"- '{m.text}': {freq}{f' ({m.note})' if m.note else ''}")
    return (f"\n\n# 문체 표지 (원문에서 센 빈도를 이번 화 분량 약 {size}자에 맞춘 것. 이만큼 섞어 쓰고 몰아 쓰지 않습니다)\n"
            + "\n".join(rows))


def episode_prompt(p: Project, n: int, approach: str = "") -> str:
    """approach 는 1~3화를 여러 안으로 쓸 때 안마다 다르게 주는 여는 방식(OPENING_APPROACHES)."""
    rules = opening_rules(p, n, approach)
    flow = ("첫 화이므로 앞 이야기를 요약하거나 설명으로 깔지 않고 장면으로 시작하고, " if n == 1
            else "직전 화 마지막 장면과 자연스럽게 이어지고, ")
    return (
        build_episode_context(p, n)
        + (f"\n\n{rules}" if rules else "")
        + f"\n\n위 자료를 바탕으로 {n}화 본문을 약 {p.meta.words_per_episode}자 분량으로 쓰세요. "
        + flow + "플롯의 ending_hook 으로 끝납니다. "
        "문체는 스타일 프로필과 문체 예시 문단을 따르고, banned_phrases 의 표현은 쓰지 않습니다. "
        "플롯의 emotional_shift 는 감정 이름으로 서술하지 말고 행동과 대사로 보여 줍니다. "
        "인물의 말투는 speech_style 을 따릅니다."
    )


def state_prompt(p: Project, n: int) -> str:
    ep = p.episode(n)
    if p.serial:  # 장편: 이번 화에 나온 인물과 주역만 자세히, 나머지는 한 줄 목록으로
        ids = set(ep.plot.characters) | {c.id for c in static_characters(p)}
        chars = [c for c in p.characters if c.id in ids]
        states = state_view(p, [s for s in p.states if s.character_id in ids])
        relations = rels(p, ids)
        fs, _ = relevant_foreshadows(p, n)
        others = roster_line(p, ids)
    else:
        chars, states, relations = p.characters, p.states, rels(p)
        fs, others = [f for f in p.foreshadows if f.status == "open"], ""
    return f"""{n}화 본문을 읽고 상태 변경안을 작성하세요.

[인물 설정]
{dump(chars)}
{f"[다른 인물 (id: 이름, 역할) — 다시 만들지 않습니다]{chr(10)}{others}{chr(10)}" if others else ""}[이전 인물 상태]
{dump(states) or "설정 그대로"}
[이전 관계]
{relations}
[현재 비밀]
{dump(p.secrets) or "없음"}
[열린 복선]
{dump(fs) or "없음"}
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
- 새 복선 id 는 fs-{n:02d}-키워드 형식으로 짓습니다. 이번 아크 안에서 회수할 작은 복선은 scope 를 arc, 부나 작품 끝까지 갈 복선은 part 나 series 로 둡니다.
- 인물 설정과 목록에 없는 인물이 이름을 갖고 처음 나왔으면 new_characters 에 넣습니다. 조연은 tier 를 support, 지나가는 인물은 minor 로 두고, 본문에서 드러난 것만 적습니다.
- warnings 에는 플롯 사건 누락, 설정/말투 위반, 확정 사실과의 모순을 적습니다.{storylines.state_rule(p, n)}"""


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
    if p.serial and full and len(full) < len(prior):
        # 장편: 통째로 못 넣는 오래된 부분은 화별 요약 대신 접은 줄거리로 본다
        first = min(full_nos)
        past = f"## {first - 1}화까지의 줄거리 (요약)\n{story_so_far(p, first)}\n\n" + "\n\n".join(
            f"## {e.plot.number}화 {e.plot.title}\n{e.text}" for e in prior if e.plot.number in full_nos)
    else:
        past = "\n\n".join(
            f"## {e.plot.number}화 {e.plot.title}\n{e.text if e.plot.number in full_nos else '(요약) ' + e.summary}"
            for e in prior
        )
    els = elements.active_block(p, n)
    els = f"\n\n# 이야기 요소 ({n}화 시점에 사실인 것)\n{els}" if els else ""
    line = storylines.episode_block(p, n)
    line = f"\n\n# {n}화의 이야기 줄기\n{line}" if line else ""
    return f"""{static_context(p)}

# 확정된 사실
{chr(10).join("- " + f for f in p.facts) or "없음"}{els}

# 인물 현재 상태 ({n - 1}화 종료 시점)
{dump(p.states) or "1화 시작 시점, 설정 그대로"}

# 관계 현재 상태
{rels(p) if p.relationships else "없음"}

# 비밀 (hidden_from 의 인물은 아직 모른다)
{dump(p.secrets) or "없음"}

# 앞선 본문
{past or "없음 (첫 화)"}

# {n}화 플롯
{dump(ep.plot)}{line}

# {n}화 본문 (검수 대상)
{ep.text}

{n}화 본문에서 위 자료와 어긋나는 곳을 찾으세요.
- 확인할 것: 확정 사실, 이야기 요소와 세부(이름, 나이, 외모, 장소, 물건), 시간 순서와 인과, 인물이 아직 모르는 정보를 아는 듯 행동하는지, 말투(호칭, 존댓말/반말, 어미), 세계관 규칙, 플롯 사건 누락.
- source_quote 와 current_quote 는 원문을 그대로 옮깁니다. 근거가 설정이나 인물 상태면 source_episode 는 0 입니다.
- 근거를 인용할 수 없는 의심은 넣지 않습니다. 모순이 없으면 issues 를 빈 목록으로 둡니다.
- episode 는 {n} 입니다."""


# ---------- 인과율: 새 요소의 영향 분석 ----------

SYSTEM_IMPACT = (
    "당신은 연재 소설의 설정 편집자입니다. 작가가 새로 더하거나 고친 이야기 요소 하나가 이미 쓴 본문, "
    "정해 둔 화별 플롯, 기존 설정과 어떻게 부딪치고 무엇을 고쳐야 하는지 찾습니다. "
    "모든 지적은 기존 내용을 원문 그대로 인용합니다. 인용할 근거가 없으면 지적하지 않습니다. "
    "고칠 것은 최소로 제안하고, 새 요소를 살리는 쪽으로 고칩니다. 모든 출력은 한국어로 작성합니다."
)


def impact_texts(p: Project, linked: set[int], limit: int = CHECK_TEXT_LIMIT) -> str:
    """이미 쓴 화. 한도 안이면 모두 원문, 넘으면 언급이 있는 화와 최근 화부터 원문으로 넣고 나머지는 요약.
    장편은 원문으로 넣지 못한 화 중 요약이 승인된 아크에 속한 화를 아크 요약 한 줄로 접는다."""
    written = sorted((e for e in p.episodes if e.text), key=lambda e: e.plot.number)
    order = sorted(written, key=lambda e: (e.plot.number not in linked, -e.plot.number))
    full, budget = set(), limit
    for e in order:
        if len(e.text) <= budget:
            full.add(e.plot.number)
            budget -= len(e.text)
    out, folded = [], set()
    for e in written:
        n = e.plot.number
        arc = p.arc_for(n) if p.serial and n not in full and n not in linked else None
        if arc and arc.summary:
            if arc.number not in folded:
                folded.add(arc.number)
                out.append(f"## 아크 {arc.number} {arc.title} ({arc.start_ep}~{arc.end_ep}화, 아크 요약)\n{arc.summary}")
            continue
        out.append(f"## {n}화 {e.plot.title}\n{e.text if n in full else '(요약) ' + (e.summary or e.plot.summary)}")
    return "\n\n".join(out)


def impact_structure(p: Project) -> str:
    """영향 분석에 넣는 구조. 단편은 기승전결, 장편은 부 구성과 기획한 아크 (끝난 아크는 화별 구간을 뺀다)."""
    if not p.serial:
        return f"[기승전결 구조] 총 {p.meta.target_episodes}화\n{dump(p.arc) if p.arc else '아직 없음'}"
    done = max((e.plot.number for e in p.episodes if e.text), default=0)
    arcs = [a.model_dump(exclude={"acts"} if a.end_ep <= done else set()) for a in sorted(p.story_arcs, key=lambda a: a.start_ep)]
    last = p.planned_until()
    rest = (f"\n{last + 1}~{p.meta.target_episodes}화는 아직 아크로 기획하지 않았습니다. 이 화들에 미칠 영향은 "
            "부의 goal, key_turn, arc_ideas 에 비춰 summary 와 conflicts 로 알립니다." if last < p.meta.target_episodes else "")
    return f"""[부 구성] 장편 연재, 총 {p.meta.target_episodes}화
{dump(p.parts) if p.parts else "부 구성 없음 (작품 전체가 한 부)"}
[기획한 아크] summary 는 작가가 승인한 아크 요약
{dump(arcs) if arcs else "아직 없음"}{rest}"""


def impact_plots(p: Project, el: StoryElement, linked: set[int]) -> list[dict]:
    """영향 분석에 넣는 화별 플롯. 장편은 본문 없는 화와 요소가 걸린 화만 넣는다 (나머지는 본문과 요약으로 본다)."""
    keep = linked | set(el.episodes) | ({el.reveal_ep} if el.reveal_ep else set())
    return [{"status": e.status, **e.plot.model_dump()} for e in p.episodes
            if not p.serial or not e.text or e.plot.number in keep]


def impact_prompt(p: Project, el: StoryElement, linked: set[int]) -> str:
    """앞쪽은 작품 설정, 뒤쪽은 구조와 플롯, 이미 쓴 본문, 마지막에 분석할 요소."""
    eps = impact_plots(p, el, linked)
    skipped = len(p.episodes) - len(eps)
    locked = [e.plot.number for e in p.episodes if e.status in ("written", "finalized")]
    confirmed = [e.plot.number for e in p.episodes if e.status == "confirmed"]
    others = "\n".join(elements.describe(p, x) for x in p.elements if x.id != el.id and x.context != "off")
    open_fs = [f for f in p.foreshadows if f.status == "open"]
    if el.since_ep <= 0:
        when = ("처음부터 사실이었던 설정입니다. 이미 쓴 본문과 플롯 전체가 이 설정과 맞아야 합니다. "
                "본문에 이 설정과 어긋나는 문장이 있으면 지적합니다.")
    else:
        when = (f"{el.since_ep}화부터 생기는 일입니다. {el.since_ep}화 전 본문은 이 요소가 없던 때라 모순이 아닙니다. "
                f"다만 앞 본문이 이 일이 일어날 수 없게 못박았다면 지적합니다. {el.since_ep}화 이후 플롯에 이 요소가 반영되는지 봅니다.")
    return f"""[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{dump(p.characters)}
[관계]
{rels(p)}
[확정된 사실]
{chr(10).join("- " + f for f in p.facts) or "없음"}
[다른 이야기 요소]
{others or "없음"}

{impact_structure(p)}
[화별 플롯] status: draft 초안, confirmed 작가가 확정, written 본문 있음, finalized 반영 완료{f" (요소와 관련 없는 본문 있는 화 {skipped}개의 플롯은 빼고 아래 본문과 요약으로 대신합니다)" if skipped else ""}
{dump(eps) if eps else "아직 없음"}
[열린 복선]
{dump(open_fs) if open_fs else "없음"}

[이미 쓴 본문]
{impact_texts(p, linked) or "없음 (아직 쓴 화가 없음)"}

[새로 더하거나 고친 요소]
{elements.describe(p, el)}
이 요소는 {when}

요구사항:
- summary 에는 작가에게 2~5문장으로 영향 전체를 설명합니다. 영향이 없으면 그렇다고 말하고 나머지 목록은 비웁니다.
- conflicts 에는 근거가 분명한 어긋남만 넣습니다. quote 는 본문, 플롯, 설정, 확정 사실의 원문을 그대로 옮기고, 본문이나 플롯이면 episode 에 화 번호를 적습니다.{"""
- 부나 아크의 goal, conflict, payoff, key_turn, arc_ideas 와 어긋나면 target 을 설정으로 하고 그 문구를 그대로 옮깁니다. 부와 아크는 이 분석으로 바꾸지 않으니 fix 는 설명 추가나 그대로 둠 중에서 고르고, 부나 아크를 어떻게 고치면 좋을지는 problem 에 적습니다.""" if p.serial else ""}
- 본문이 있는 화({", ".join(map(str, locked)) or "없음"})의 모순은 patches(본문 최소 수정), new_facts(둘을 함께 성립시키는 설명), 또는 시점 변경 중 가장 덜 고치는 쪽을 fix 로 권합니다. 본문이 있는 화의 플롯은 episodes 에 넣지 않습니다.
- patches 의 quote 는 본문 문장을 한두 문장만 그대로 옮기고, replacement 는 같은 문체로 필요한 만큼만 고칩니다.
- episodes 에는 이 요소 때문에 바뀌어야 하는 본문 없는 화만, 모든 칸을 채운 전체 플롯으로 넣습니다. 나올 화가 정해져 있으면 그 화 사건에 넣고, 드러나는 화 전에는 foreshadow_plant 로 암시를 심습니다.
- 작가가 확정한 화({", ".join(map(str, confirmed)) or "없음"})는 꼭 필요할 때만 바꿉니다.
- 바꿀 필요가 없는 화는 넣지 않습니다.
{plot_rules(p, opening_pending(p))}"""


# ---------- 초반 1~3화: 흡입력 판정과 여는 방식 여러 안 ----------

SYSTEM_HOOK = (
    "당신은 한국 웹소설 플랫폼의 연재 담당 편집자입니다. 무료 회차를 읽은 독자가 다음 화를 누를지 판단합니다. "
    "모든 판단에는 본문 문장을 원문 그대로 인용하고, 근거가 없으면 점수를 낮게 줍니다. 후하게 주지 않습니다. "
    "문장의 아름다움보다 독자가 계속 읽고 싶어지는지를 봅니다. 모든 출력은 한국어로 작성합니다."
)

HOOK_GUIDE = {
    "첫 문단": "처음 3~5문장에 움직임, 균열, 궁금증이 있는가. 세계관 설명, 날씨, 기상, 평범한 자기소개로 시작하면 낮게",
    "주인공": "주인공이 누구이고 무엇이 없는지(결핍)나 무엇을 원하는지가 행동과 처지로 보이는가",
    "전제": "작품의 핵심 장치(회귀, 빙의, 각성, 계약, 사건 등)가 일어나거나 확실히 예고되는가. 늦을수록 낮게",
    "설명 부담": "설정 설명이 덩어리로 몰려 있는가. 몰려 있으면 낮게 주고 quote 에 가장 긴 설명을 옮긴다",
    "걸린 것": "주인공이 지금 잃을 수 있는 것이 분명한가",
    "장르 약속": "장르 독자가 기대하는 것이 이 화에서 보이는가",
    "엔딩": "마지막 문단이 장면 한가운데나 새 정보에서 끊기는가. 정리하거나 앞날을 해설하며 끝나면 낮게",
}


def hook_prompt(p: Project, n: int, text: str) -> str:
    """1~3화 판정. 작품 소개와 주인공, 앞 화 요약, 이번 화 플롯과 본문을 넣는다. text 는 판정할 본문 (비교본일 수 있다)."""
    ep = p.episode(n)
    leads = [c.model_dump(include={"name", "role", "goal", "wound", "personality"}) for c in static_characters(p)] or \
        [c.model_dump(include={"name", "role", "goal", "wound", "personality"}) for c in p.characters[:3]]
    prior = [e for e in sorted(p.episodes, key=lambda e: e.plot.number) if e.plot.number < n]
    before = "\n".join(f"{e.plot.number}화 {e.plot.title}: {e.summary or e.plot.summary}"
                       + (f" (독자 질문: {e.plot.reader_question})" if e.plot.reader_question else "") for e in prior)
    guide = "\n".join(f"- {k}: {v}" for k, v in HOOK_GUIDE.items())
    return f"""[작품]
{meta_text(p)}
[주인공과 주역]
{dump(leads)}

[앞 화]
{before or "없음 (첫 화)"}
[{n}화 플롯]
{dump(ep.plot)}

[{n}화 본문 (판정 대상)]
{text}

{n}화는 독자가 계속 읽을지 정하는 초반입니다. {OPENING_JOBS.get(n, "")}
아래 항목마다 items 에 하나씩 넣고 1~5점을 매기세요.
{guide}

요구사항:
- quote 와 premise_quote 는 본문 문장을 한두 문장만, 고치지 않고 그대로 옮깁니다. 근거를 옮길 수 없으면 빈칸으로 두고 점수를 낮게 줍니다.
- note 에는 한 줄 평과 고칠 방향을 적습니다. 좋은 점보다 고칠 점을 먼저 적습니다.
- reader_question 에는 마지막 장면을 읽은 독자가 들고 갈 질문을 한 문장으로 적습니다. 그런 질문이 생기지 않으면 빈칸입니다.
- next_click 은 이 화를 무료로 읽은 독자가 다음 화를 누를지, reason 은 그 가장 큰 이유입니다.
- episode 는 {n}, premise_at 은 -1, basis 와 checked_at 은 빈칸입니다."""


def opening_plots_prompt(p: Project, n: int, approaches: list[str]) -> str:
    """n화(1~3) 플롯을 여는 방식만 달리해 여러 안으로. 플롯 초안과 같은 자료를 넣고 요청만 바꾼다."""
    ways = "\n".join(f"- {a}: {OPENING_APPROACHES[a][0]}. {OPENING_APPROACHES[a][1]}" for a in approaches)
    return f"""{plot_prompt(p, n, n)}

[이번 요청]
위 자료로 {n}화 플롯 하나를 쓰되, 아래 여는 방식마다 하나씩 모두 {len(approaches)}개의 안을 내세요. 독자가 계속 읽을지 정하는 화라서 여는 방식을 비교해 고르려고 합니다.
{ways}

- options 마다 approach 에 위 id 를 그대로, plot 에 {n}화 전체 플롯을 넣습니다. plot.number 는 {n} 입니다.
- 안끼리 사건과 목표는 같은 이야기 안에 있어도 되지만, 첫 장면(opening), 사건 순서, 엔딩 훅은 여는 방식에 맞게 다르게 합니다.
- pitch 에는 이 안이 독자를 어떻게 붙잡는지 한두 문장으로 적습니다."""


# ---------- 작업지시서 (구독형 채팅 앱용) ----------
# API 경로와 같은 프롬프트를 그대로 쓴다. 나중에 MCP 서버의 prompt/tool 로 옮길 때도 이 함수들을 재사용한다.

def episode_brief(p: Project, n: int) -> str:
    return f"""# {p.meta.title or "작품"} {n}화 작업지시서

아래 지시를 그대로 따라 {n}화 본문을 작성해 주세요.

## 역할
{writer_system(p)}

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
