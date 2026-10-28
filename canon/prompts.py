"""프롬프트 템플릿과 컨텍스트 조립.

일관성 유지의 핵심은 build_episode_context(): 매 화마다 '현재 시점의 데이터'만 골라
같은 순서와 형식으로 넣는다. 이전 본문 전체 대신 요약 + 직전 화 끝부분만 넣어
분량이 늘어도 컨텍스트가 일정하게 유지된다.
검수(check_prompt)는 반대로 앞선 본문을 한도 안에서 통째로 넣는다. 쓸 때는 압축, 검사할 때는 전체.
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from . import context, elements, genres, metrics, naming, storylines
from .dynamics import VIEWS, describe_relations
from .llm import _inline_refs, dump
from .schema import Birth, Character, ChatMessage, Claim, ConsistencyIssue, ConsistencyReport, Foreshadow, ImpactReport, PlayInfo, Project, Selection, StateDelta, StoryElement
from . import charlog, foreshadows, statwin, timeline, travel

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
    ("", "장면 안에서 인물의 위치, 몸이 향한 쪽, 자세, 손에 든 것, 가려진 곳은 바꾸는 행동을 쓰기 전까지 그대로입니다. 등을 돌린 인물의 얼굴과 표정은 보이지 않습니다."),
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


BIRTH_CAST = 12      # 무작위 출생 프롬프트에 한 줄씩 넣는 세계 인물 수 (주역 먼저)
BIRTH_PLACES = 30    # 장소 이름 수
BIRTH_FACTIONS = 10  # 세력 요소 수


def _birth_known(p: Project, kind: str) -> list:
    """반영한 마지막 화까지 생겼고 독자에게 드러난 kind 요소."""
    from . import birth

    n = birth.last_finalized(p)
    return [el for el in p.elements if el.kind == kind and el.name.strip() and el.since_ep <= n and el.reveal_ep <= n]


def birth_prompt(p: Project, b: Birth) -> str:
    """무작위 출생의 배경 채우기 (birth.sketch, BirthSketch). 코드가 굴린 값(b)은 바꾸지 않고 세계에 맞게 살을 붙인다.
    세계 블록이 앞, 굴린 값이 뒤. 원형 카드는 요약 · 성격 · 원하는 것만 넣는다 (시작 관계 예시는 관계를 지어내게 해서 뺀다)."""
    from . import archetypes, birth, cast

    places = birth.birth_places(p)
    place_lines = [f"- {x['name']}" + (f": {_clip(x['description'], 120)}" if x["description"] else "") for x in places[:BIRTH_PLACES]]
    if len(places) > BIRTH_PLACES:
        place_lines.append(f"(장소 {len(places) - BIRTH_PLACES}곳은 뺐습니다)")
    factions = _birth_known(p, "세력")
    faction_lines = [f"- {el.name}" + (f": {_clip(el.description, 120)}" if el.description else "") for el in factions[:BIRTH_FACTIONS]]
    if len(factions) > BIRTH_FACTIONS:
        faction_lines.append(f"(세력 {len(factions) - BIRTH_FACTIONS}개는 뺐습니다)")
    order = {"main": 0, "support": 1, "minor": 2}
    people = sorted((c for c in p.characters if c.name.strip()), key=lambda c: order.get(c.tier, 3))
    cast_lines = [f"- {c.name} ({', '.join(x for x in (c.role, c.age) if x)})" + (f": {_clip(c.goal, 80)}" if c.goal else "")
                  for c in people[:BIRTH_CAST]]
    if len(people) > BIRTH_CAST:
        cast_lines.append(f"(인물 {len(people) - BIRTH_CAST}명은 뺐습니다)")

    rolled = [f"- 이름: {b.name or '(정하지 않음: 이 세계의 이름 짓는 규칙에 맞게 짓습니다)'}",
              f"- 성별: {b.gender or '(정하지 않음)'}", f"- 나이: {b.age or '(정하지 않음)'}",
              f"- 태어나 자란 곳: {b.place or '(정하지 않음: 세계 안의 이름 없는 곳으로 두고 새 고유 지명을 만들지 않습니다)'}"]
    a = archetypes.BY_ID.get(b.archetype)
    if a:
        rolled.append(f"- 원형: {a.name}. {a.summary}" + "".join(f" {label}: {v}" for label, v in (
            ("성격", a.personality), ("원하는 것", a.goal)) if v))
    w = archetypes.WOUND_BY_ID.get(b.wound)
    if w:
        rolled.append(f"- 상처: {archetypes.wound_text(w)} 회복 방향: {w.heal}")
    sp = archetypes.SPEECH_BY_ID.get(b.speech)
    if sp:
        rolled.append(f"- 말투 틀: {archetypes.speech_text(sp)}")
    if b.twist:
        rolled.append(f"- 비틀기: {b.twist}")
    minor = "\n- 이 인물은 미성년입니다. 외모와 배경에 성적인 묘사를 넣지 않습니다." if b.age and cast.is_minor_age(b.age) else ""

    return f"""아래 세계에 새로 태어난 인물 한 명의 배경을 채우세요. 이 인물은 플레이어가 맡아 이 세계를 살아갈 주인공입니다.

[작품 정보]
{meta_text(p)}

[세계관]
{dump(p.world.model_dump(exclude={"name_style"}))}

[이 세계의 장소]
{chr(10).join(place_lines) or "(정해진 장소 없음)"}

[이 세계의 세력]
{chr(10).join(faction_lines) or "(정해진 세력 없음)"}

[이 세계에 이미 있는 인물]
{chr(10).join(cast_lines) or "(없음)"}

[굴린 값]
{chr(10).join(rolled)}

요구사항:
- [굴린 값]의 이름 · 성별 · 나이 · 태어나 자란 곳은 바꾸지 않습니다. 원형 · 상처 · 말투 틀 · 비틀기는 이 인물의 바탕으로 삼되, 원형 이름이나 도감 문장을 그대로 옮기지 말고 이 세계의 말로 풀어 씁니다.
- 세계관 규칙과 시대를 지킵니다. 장소와 세력은 위 목록에 있는 것만 씁니다. 새 고유 지명이나 새 세력을 만들지 않습니다.
- 이미 있는 인물과 가족 · 연인 · 스승 · 원수 같은 관계를 만들지 않습니다. 같은 곳에 산다면 소문으로 이름을 아는 정도까지만 씁니다.
- appearance: 첫눈에 보이는 특징 두세 가지. personality: 원형과 상처가 드러나는 성격 한두 문장.
- background: 집안, 자란 곳, 지금까지의 삶을 3~5문장으로. 상처가 된 일이 이 세계에서 어떻게 일어났는지 담습니다.
- goal: 이 세계 안에서 지금 원하는 것 한 문장. 플레이를 시작할 이유가 되게 구체적으로 씁니다.
- speech_style: 말투 틀을 따른 어미 · 호칭 규칙과 대사 예시 한 줄.
- opening: 플레이를 시작하는 순간 이 인물이 어디서 무엇을 하고 있는지 한두 문장. 태어나 자란 곳이나 위 장소 중 하나에서 시작합니다.{minor}"""


# ---------- 설정 도우미 대화 ----------
# 앞쪽은 지금 설정(작품 · 세계관 · 인물 · 관계), 뒤쪽은 쓴 화 · 이름 후보(뽑을 때마다 바뀜) · 대화 · 새 말.

SYSTEM_SETUP_CHAT = (
    "당신은 작가와 함께 소설의 기획 설정(로그라인, 주제, 톤, 세계관, 인물, 관계)을 다듬어 가는 기획 편집자입니다. "
    "작가의 말을 듣고 바꿀 칸만 고친 변경안을 내고, 왜 그렇게 고쳤는지 짧게 설명합니다. "
    "작가가 방향을 청하면 변경안 대신 서로 분명히 다른 방향 여러 안을 내서 고르거나 섞게 합니다. "
    "변경안은 제안일 뿐이며 작가가 골라서 적용합니다. 작가가 채운 설정은 존중합니다. 모든 출력은 한국어로 작성합니다."
)

SETUP_CHAT_HISTORY = 12  # 설정 대화에서 넣는 최근 메시지 수
SETUP_CHAT_RECENT = 5    # 쓴 화 요약을 넣는 최근 화 수


def _setup_chat_line(p: Project, m: ChatMessage) -> str:
    from . import setupchat

    if m.role == "user":
        return f"작가{' [방향 여러 안 요청]' if m.mode == 'options' else ''}: {m.text}"
    line = f"편집자: {m.text}"
    r = m.setup
    if r and r.options:
        line += "\n  (방향 안: " + " / ".join(f"{i}. {x.title}" for i, x in enumerate(r.options, 1)) + ")"
    elif r:
        parts = ", ".join(setupchat.label(p, r, x) for x in setupchat.part_ids(r))
        applied = ", ".join(setupchat.label(p, r, x) for x in m.applied)
        result = {"applied": f"작가가 적용함: {applied}", "dismissed": "작가가 적용하지 않음"}.get(m.outcome, "아직 결정 전")
        line += f"\n  (변경안: {parts} / {result})"
    return line


def setup_chat_prompt(p: Project, message: str, mode: str = "") -> str:
    """설정 도우미 대화. mode 'options' 면 변경안 대신 방향 여러 안을 청한다."""
    from . import setupchat

    begun = setupchat.started(p)
    chars = [c.model_dump(exclude={"narration_voice", "first_ep", "body", "context"}) for c in p.characters]
    relations = [r.model_dump(exclude={"a_view", "b_view"} if begun else set()) for r in p.relationships]
    written = sorted((e for e in p.episodes if e.text.strip()), key=lambda e: e.plot.number)
    story = ""
    if written:
        lines = [f"- {e.plot.number}화 {e.plot.title}: {_clip(e.summary or e.plot.summary, 200)}" for e in written[-SETUP_CHAT_RECENT:]]
        story = f"\n[이미 쓴 화] 본문이 있는 화 {len(written)}개 (마지막 {written[-1].plot.number}화). 최근 화:\n" + "\n".join(lines) + "\n"
    chat = next((c for c in p.chats if c.topic == "setup"), None)
    history = "\n".join(_setup_chat_line(p, m) for m in (chat.messages[-SETUP_CHAT_HISTORY:] if chat else []))
    head = f"""[작품]
{meta_text(p)}

[로그라인 다섯 칸] (위 logline 은 이 칸을 합친 문장)
{dump(p.meta.logline_parts)}

[세계관]
{dump(p.world)}

[인물]
{dump(chars) if chars else "아직 없음"}

[관계]
{dump(relations) if relations else "아직 없음"}
{story}
[이름·지명 후보]
{naming.prompt_block(p)}

[지금까지의 대화]
{history or "없음 (첫 대화)"}

[작가의 새 말]
{message}

요구사항:
"""
    if mode == "options":
        return head + """- 작가가 방향 여러 안을 청했습니다. options 에 서로 분명히 다른 방향 2~3개를 넣습니다. 같은 방향의 강약 조절이 아니라 인물의 욕망과 결핍, 갈등의 축, 세계의 규칙, 톤처럼 줄기가 다르게 갈라지게 합니다.
- 각 안의 title 은 방향 이름 한 줄, idea 에는 이 설정이면 어떤 이야기가 되는지 2~3문장, changes 에는 바뀌는 칸을 한 줄씩 (예: '주인공 약점: 남을 믿지 못함 → 거절을 못 함'), tradeoff 에는 얻는 것과 잃는 것을 씁니다.
- 작가가 채운 칸은 작가가 바꾸자고 한 것이 아니면 살리는 방향을 먼저 냅니다.
- edits, characters, new_characters, relationships 는 모두 비웁니다. 작가가 안을 고르면 그때 변경안을 만듭니다.
- reply 에는 안들을 어떤 기준으로 나눴는지 1~2문장으로 씁니다."""
    rel_rule = ("- 1화 상태를 반영한 뒤라 지금 관계는 본문의 관계 사건으로 계산됩니다. 관계는 type, description, goal_conflict 만 고치고 a_view, b_view 는 비웁니다. 관계 수치는 적지 않습니다."
                if begun else
                f"- 관계의 a_view(a 가 b 를 보는 방식)와 b_view(b 가 a 를 보는 방식)는 {', '.join(VIEWS)} 중에서 1~2개 고릅니다. 시작 호감은 프로그램이 보는 방식으로 계산합니다.")
    return head + f"""- reply 에는 작가에게 하는 대답을 2~5문장으로 씁니다. 무엇을 왜 바꿨는지, 이야기에 어떤 차이가 생기는지 말합니다. 요청이 모호하면 가장 그럴듯하게 해석해 고치고 어떻게 해석했는지 밝힙니다. 질문만 받았으면 변경 없이 대답만 합니다. 작가에게 더 물어볼 것이 있으면 reply 끝에 짧은 질문 하나를 붙입니다.
- 작가가 앞서 낸 방향 안 중 하나를 고르거나 섞어 달라고 하면 그 방향으로 변경안을 만듭니다. options 는 비웁니다.
- 바뀌는 칸만 넣고, 칸마다 바뀐 뒤 값 전체를 씁니다. 작가가 채운 칸은 작가가 바꾸자고 했거나 요청을 이루는 데 꼭 필요할 때만 바꿉니다. 칸을 비우는 변경은 내지 않습니다.
- edits 의 key: title 제목, logline.who 누가(이름보다 특징이 먼저 보이게), logline.why 무엇 때문에, logline.goal 무엇을 하려 하나('~한다'로 끝나는 눈에 보이는 행동), logline.block 무엇이 막나(사람이나 힘), logline.stake 무엇이 걸렸나, theme 주제(이야기가 끝까지 묻는 질문 하나), tone 톤 문장, notes 메모, world.setting 배경, world.era 시대, world.rules 깨면 안 되는 규칙, world.locations 장소, world.name_rules 이름 규칙. 로그라인은 다섯 칸으로만 고칩니다 (한 문장은 프로그램이 합칩니다). 다섯 칸이 비어 있고 logline 문장만 있으면 로그라인을 고칠 때 그 문장을 다섯 칸으로 나눠 함께 채웁니다.
- 글 칸은 text, world.rules · world.locations · world.name_rules 는 items 에 씁니다. 목록은 그대로 둘 항목도 빠짐없이 넣습니다. 빠진 항목은 지워집니다.
- characters 에는 이미 있는 인물의 바뀌는 칸만 (id, field) 하나씩 넣습니다. field 는 name, role, age, gender, appearance, personality, background, goal, wound, speech_style, secrets(목록, items), arc 입니다. id 와 서술 말투는 바꾸지 않습니다. speech_style 은 대사 예시 한 줄을 포함해 구체적으로 씁니다.
- new_characters 에는 작가가 청했거나 요청을 이루는 데 꼭 필요한 인물만, 모든 칸을 채워 넣습니다. id 는 이미 있는 인물과 겹치지 않는 영문 소문자이고 narration_voice 는 비웁니다. gender(남/여)를 적고, 이름은 위 [이름·지명 후보]에서 고르거나 같은 시대와 결로 짓습니다. 다른 인물과 이름의 첫 글자나 끝 글자가 겹치지 않게 합니다.
- relationships 에는 바뀌는 관계와 새 관계만, 두 인물 id 와 바뀐 뒤 값 전체를 넣습니다. 같은 두 인물이면 그 관계를 고칩니다. 새 인물을 넣으면 그 인물과 이미 있는 인물의 관계도 하나 이상 넣습니다.
{rel_rule}
- 인물이나 관계를 지우는 제안은 하지 않습니다. 지워야 한다고 보면 reply 에서 말하면 작가가 화면에서 지웁니다.
{"- 이미 쓴 화의 본문은 바뀌지 않습니다. 쓴 내용과 어긋나는 설정 변경이면 reply 에서 어느 화와 어긋나는지 알립니다." + chr(10) if written else ""}- options 는 비웁니다."""


def style_prompt(sample: str) -> str:
    return f"""아래 예시 소설 텍스트의 문체를 분석해 스타일 프로필을 만드세요.
다른 작품을 쓸 때 이 문체를 재현할 수 있도록, 관찰 가능한 특징을 구체적으로 적습니다
(예: "문장 평균 20자 안팎, 짧은 문장 연속 후 긴 문장 하나로 감정 폭발").
sample_passages 에는 원문에서 문체가 가장 잘 드러나는 문단 2~4개를 수정 없이 발췌합니다
(서술 위주 하나, 대화 위주 하나는 꼭 포함).
markers 에는 이 문체를 알아보게 하는 어미, 조사, 말버릇 5~10개를 원문에 적힌 글자 그대로 적습니다
(예: "것이었다", "하더라", "말이지"). 원문에서 여러 번 나오는 것만 고르고, 인물 이름이나 이 작품에만 있는 낱말은 넣지 않습니다.
per_1k 는 0 으로 두세요. 원문에서 직접 셉니다.
devices 에는 원문에서 특정 상황에만 쓰는 장면 장치(예: 자문자답으로 꼬리를 무는 망상, 장면 끝 독백 한 줄)를 0~3개 적습니다.
매 화 넣으면 버릇이 되는 것들이라 dos 나 inner_monologue 같은 칸에 규칙으로 적지 말고 devices 에만 적습니다.
when 은 쓰는 상황, cues 는 그 장치를 알아보는 글자 1~3개(원문에 적힌 그대로), every 는 원문에서 나온 빈도로 짐작한 최소 간격(화), example 은 원문 한두 줄입니다.
그런 장치가 담긴 문단은 sample_passages 로 고르지 않습니다.

[예시 텍스트]
{sample}"""


SYSTEM_STYLE_EDITOR = (
    "당신은 한 작가의 문체를 오래 봐 온 편집자입니다. 작가가 AI 초안을 고친 기록만 근거로, "
    "작가가 되풀이해서 고치는 방향을 문체 규칙으로 정리합니다. 한 번뿐인 고침이나 내용(사건, 설정, 사실, 동선)을 "
    "고친 것은 규칙으로 만들지 않습니다. 모든 출력은 한국어로 작성합니다."
)

EDIT_SOURCE_TEXT = {"manual": "고른 부분을 직접 고침", "typed": "본문을 직접 고쳐 저장", "ai": "AI 후보 중 골라 넣음"}


def _clip(t: str, k: int = 400) -> str:
    t = t.strip()
    return t if len(t) <= k else t[:k] + "…"


def learn_edit_line(ref: str, e) -> str:
    """수정 기록(TextEdit) 하나를 학습 프롬프트용 글로."""
    how = "AI 후보를 작가가 손봐 넣음" if e.source == "ai" and e.proposed else EDIT_SOURCE_TEXT.get(e.source, e.source)
    ask = PASSAGE_PRESETS[e.preset][0] if e.preset in PASSAGE_PRESETS else ""
    ask = " / ".join(x for x in (ask, e.instruction.strip()) if x)
    lines = [f"[{ref}] {how}" + (f" (요청: {_clip(ask, 120)})" if ask else ""),
             f"  고치기 전: «{_clip(e.before)}»", f"  고친 뒤: «{_clip(e.after)}»"]
    if e.proposed:
        lines.append(f"  AI 후보 원래 글: «{_clip(e.proposed)}»")
    for r in e.rejected[:2]:
        lines.append(f"  작가가 버린 후보: «{_clip(r, 200)}»")
    return "\n".join(lines)


def learn_prompt(p: Project, edits: list) -> str:
    """edits 는 (ref, TextEdit) 목록, 오래된 것부터."""
    st = p.style
    rules = "\n".join([
        f"지킬 것: {' / '.join(st.dos) or '없음'}",
        f"피할 것: {' / '.join(st.donts) or '없음'}",
        f"금지 표현: {', '.join(st.banned_phrases) or '없음'}",
        f"문체 표지: {', '.join(m.text for m in st.markers) or '없음'}",
        f"가끔 쓰는 장치: {', '.join(d.name for d in st.devices) or '없음'}",
    ])
    return f"""아래는 작가가 AI 가 쓴 본문을 고친 기록입니다. 작가가 되풀이해서 고치는 방향을 찾아 스타일 프로필에 넣을 규칙 후보로 정리하세요.

[지금 스타일 프로필의 규칙]
{rules}

[수정 기록] (오래된 것부터, 대괄호 안이 화:수정 id)
{chr(10).join(learn_edit_line(r, e) for r, e in edits)}

요구사항:
- 같은 방향의 고침이 두 번 이상 보일 때만 후보로 냅니다. evidence 에 그 수정들의 화:id 를 적힌 그대로(예: "3:e5") 두 개 이상 적습니다.
- 사건, 설정, 사실, 인물 위치나 동선을 바꾼 고침은 문체가 아니므로 쓰지 않습니다.
- kind 별로:
  - do / dont: 관찰할 수 있는 규칙 한 문장 (예: "감정은 이름 대신 손이나 시선의 움직임으로 보여 준다", "문단 끝을 짧은 여운 문장으로 닫지 않는다"). "자연스럽게", "생생하게" 같은 막연한 말은 쓰지 않습니다.
  - banned: 작가가 매번 지우거나 바꾼 구체적 표현을 고치기 전 글(또는 버린 후보)에 적힌 그대로. 고친 뒤 글에는 없어야 합니다.
  - marker: 작가가 새로 넣은 어미, 조사, 말버릇을 고친 뒤 글에 적힌 그대로. 인물 이름이나 이 작품에만 있는 낱말은 넣지 않습니다.
  - device: 작가가 줄이거나 지운 장면 장치(예: 자문자답으로 꼬리를 무는 망상). 아예 빼는 게 아니라 가끔만 쓰게 할 때 씁니다. text 는 장치 이름, note 는 써도 되는 상황, cues 는 그 장치를 알아보는 글자 1~3개를 고치기 전 글에 적힌 그대로, every 는 몇 화에 한 번까지인지.
- 지금 규칙과 같은 것은 내지 않습니다. 지금 규칙과 부딪히면 replaces 에 그 규칙을 위 목록에 적힌 그대로 적습니다.
- 많아야 8개, 근거가 많은 것부터.
- summary 에는 작가가 AI 문장을 고치는 경향을 두세 문장으로 적습니다."""


# ---------- 대화로 문체 다듬기 ----------
# 앞쪽은 작품 정보와 지금 프로필(잘 바뀌지 않음), 뒤쪽은 최근 화 지표 · 참고할 화 · 대화 · 새 말. 캐시가 맞도록 이 순서를 지킨다.

SYSTEM_STYLE_COACH = (
    "당신은 작가와 함께 문체를 다듬어 가는 편집자입니다. 작가가 말로 바라는 것을 듣고, 스타일 프로필에서 바꿀 칸만 "
    "고쳐 제안하고, 바뀐 문체로 짧은 시험 문단을 써서 보여 줍니다. 규칙은 다음 화를 쓰는 AI 가 그대로 따를 수 있게 "
    "관찰할 수 있는 말로 씁니다. 모든 출력은 한국어로 작성합니다."
)

STYLE_CHAT_HISTORY = 10   # 문체 대화에서 넣는 최근 메시지 수
STYLE_REF_LIMIT = 4000    # 참고할 화 본문을 이만큼까지 넣는다
STYLE_KEY_LABELS = {
    "narration_pov": "시점", "tense": "시제", "sentence_rhythm": "문장 리듬", "description_density": "묘사 밀도",
    "dialogue_ratio": "대사 비율", "dialogue_style": "대사 방식", "inner_monologue": "내면 독백", "pacing": "전개 속도",
    "scene_transition": "장면 전환", "vocabulary": "어휘", "dos": "지킬 것", "donts": "피할 것",
    "banned_phrases": "금지 표현", "markers": "문체 표지", "devices": "가끔 쓰는 장치",
}


def _style_chat_line(m: ChatMessage) -> str:
    if m.role == "user":
        return f"작가{f' ({m.episode}화 참고)' if m.episode else ''}: {m.text}"
    line = f"편집자: {m.text}"
    if m.style and m.style.edits:
        keys = ", ".join(STYLE_KEY_LABELS.get(e.key, e.key) for e in m.style.edits)
        applied = ", ".join(STYLE_KEY_LABELS.get(x, x) for x in m.applied)
        result = {"applied": f"작가가 적용함: {applied}", "dismissed": "작가가 적용하지 않음"}.get(m.outcome, "아직 결정 전")
        line += f"\n  (변경안: {keys} / {result})"
    return line


def style_chat_prompt(p: Project, message: str, episode: int = 0, recent: list[str] | None = None) -> str:
    """recent: 최근 화 문체 지표와 경고 줄 (pipeline.style_chat_recent). episode: 작가가 참고하라고 고른 화."""
    st = p.style
    voices = [f"- {c.name}: {_clip(c.narration_voice, 200)}" for c in p.characters if c.narration_voice.strip()]
    samples = "\n\n---\n\n".join(_clip(x, 600) for x in st.sample_passages) or "없음"
    chat = next((c for c in p.chats if c.topic == "style"), None)
    history = "\n".join(_style_chat_line(m) for m in (chat.messages[-STYLE_CHAT_HISTORY:] if chat else []))
    ref = ""
    if episode and (ep := next((e for e in p.episodes if e.plot.number == episode and e.text), None)):
        body = ep.text if len(ep.text) <= STYLE_REF_LIMIT else ep.text[:STYLE_REF_LIMIT] + "\n…(뒤 생략)"
        ref = f"\n[작가가 참고하라고 고른 {episode}화 본문]\n{body}\n"
    preview_rule = (f"- preview_source 에는 위 {episode}화 본문에서 이번 변경이 가장 잘 드러날 한 대목(200~500자)을 글자 그대로 옮기고, "
                    "preview 에는 그 대목을 같은 내용, 같은 사건으로 바뀐 문체에 맞춰 고쳐 씁니다." if ref else
                    "- preview_source 는 비웁니다. preview 에는 이 작품의 인물과 세계로 짧은 장면을 바뀐 문체로 씁니다. 이미 쓴 화의 사건을 새로 만들지 않습니다.")
    return f"""[작품]
{meta_text(p)}

[지금 스타일 프로필] (sample_passages 는 아래 대표 문단)
{dump(st.model_dump(exclude={"sample_passages"}))}

[대표 문단] (원문 발췌. 고치지 않는다)
{samples}
{f"{chr(10)}[시점 인물별 서술 말투] (인물 설정에 있는 칸. 그 인물이 시점인 화에서는 프로필보다 앞선다. 여기서는 바꾸지 않는다){chr(10)}{chr(10).join(voices)}{chr(10)}" if voices else ""}
[최근 화 문체 지표] (기준은 레퍼런스 원문)
{chr(10).join(recent or []) or "아직 쓴 화가 없음"}
{ref}
[지금까지의 대화]
{history or "없음 (첫 대화)"}

[작가의 새 말]
{message}

요구사항:
- reply 에는 작가에게 하는 대답을 2~5문장으로 씁니다. 무엇을 왜 바꿨는지, 다음 화에 어떻게 달라질지 말합니다. 요청이 모호하면 가장 그럴듯하게 해석해 고치고 어떻게 해석했는지 밝힙니다. 질문만 받았거나 되물어야 하면 edits 를 비우고 대답만 합니다.
- edits 에는 바뀌는 칸만 넣고, 칸마다 바뀐 뒤 값 전체를 씁니다. 글 칸은 text, dos · donts · banned_phrases 는 items, markers 는 markers, devices 는 devices 하나만 채웁니다. 목록 칸은 그대로 둘 항목도 빠짐없이 넣습니다. 빠진 항목은 지워집니다.
- 규칙은 관찰할 수 있게 씁니다 (예: "문장은 대개 25자 안팎, 감정이 터질 때만 한 문장을 길게"). "자연스럽게", "생생하게" 같은 막연한 말은 쓰지 않습니다.
- 새 규칙이 지금 규칙과 부딪히면 지금 규칙을 고치거나 뺍니다. 같은 뜻의 규칙을 두 칸에 겹쳐 쓰지 않습니다.
- banned_phrases 와 markers 의 text 는 본문에서 글자 그대로 찾을 표현입니다. markers 의 per_1k 는 지금 값을 그대로 두고 새 표지는 0 으로 둡니다.
- 특정 상황에만 가끔 쓰는 장면 장치는 dos 나 inner_monologue 에 규칙으로 적지 말고 devices 에 적습니다 (when, cues 1~3개, every).
- 대표 문단은 원문 발췌라 바꾸지 않습니다. 대표 문단과 부딪히는 규칙을 만들면 reply 에서 알립니다.
- 시점 인물별 서술 말투와 부딪히는 변경이면 reply 에서 알립니다.
{preview_rule}
- 변경이 없으면 preview_source 와 preview 를 모두 비웁니다. 시험 문단에는 마크다운 기호를 쓰지 않고 문단은 빈 줄로 나눕니다."""


STYLE_EXAMPLE_CHARS = (600, 900)  # 예시 글 길이


def style_example_prompt(p: Project, scene: str = "", episode: int = 0) -> str:
    """지금 문체로 예시 글을 쓰게 한다. 앞쪽은 본문 쓰기와 같은 static_context (캐시), 뒤쪽은 장면 요청."""
    lo, hi = STYLE_EXAMPLE_CHARS
    ep = next((e for e in p.episodes if e.plot.number == episode and e.text), None) if episode else None
    if ep:
        body = ep.text if len(ep.text) <= STYLE_REF_LIMIT else ep.text[:STYLE_REF_LIMIT] + "\n…(뒤 생략)"
        task = f"""# {episode}화 본문
{body}

# 할 일
위 {episode}화 본문에서 문체가 가장 잘 드러날 한 대목(300~600자)을 골라 source 에 글자 그대로 옮기고,
text 에는 그 대목을 같은 내용, 같은 사건, 같은 인물로 위 스타일 프로필에 맞춰 고쳐 씁니다.{f"{chr(10)}작가가 바라는 장면: {scene}" if scene else ""}"""
    else:
        task = f"""# 할 일
이 작품의 인물과 세계로 짧은 장면을 위 스타일 프로필대로 {lo}~{hi}자 씁니다. source 는 비웁니다.
{f"장면: {scene}" if scene else "장면은 서술과 대사가 함께 있는 일상적인 순간으로 고릅니다. 이미 쓴 화의 큰 사건을 새로 만들지 않습니다."}"""
    return f"""{static_context(p)}

{task}

요구사항:
- 문체 예시를 보여 주는 글입니다. 스타일 프로필의 시점, 시제, 문장 리듬, 대사 방식, 지킬 것과 피할 것, 문체 표지를 따릅니다. 금지 표현은 쓰지 않습니다.
- 문체 예시 문단의 문장을 그대로 옮기지 않습니다.
- 대사는 인물 설정의 speech_style 을 따르고, 문단은 빈 줄로 나눕니다. 제목, 해설, 마크다운 기호는 쓰지 않습니다."""


def arc_prompt(p: Project) -> str:
    return f"""아래 작품을 총 {p.meta.target_episodes}화로 완결하는 기승전결 구조를 설계하세요.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{cast_block(p)}
[관계]
{rels(p, context.without_off(p, None))}
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}

요구사항:
{arc_range_rule(p.meta.target_episodes)}
- goal 은 그 구간이 끝날 때 도달해야 하는 이야기 상태, key_turn 은 핵심 전환점입니다.
- 주인공의 arc 가 결 구간에서 완성되도록 합니다.
- 기 구간은 소개가 아니라 발단입니다. 1화에 사건이 시작되고, 주인공의 결핍과 작품의 핵심 장치가 1~3화 안에 드러나며, 3화 안에 작은 보상이 하나 옵니다.
{pov_plan_rule(p, "구간")}"""


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
{cast_block(p)}
[관계]
{rels(p, context.without_off(p, None))}
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[기승전결 구조]
{dump(p.arc)}
[앞 화 플롯 (확정 또는 초안, 이어지게 쓸 것)]
{dump(prior) if prior else "없음"}{candidates_block(p)}
[현재 열린 복선]
{dump([f for f in p.foreshadows if f.status == "open"]) or "없음"}{time_plan(p, start)}

요구사항:
{plot_rules(p, start <= OPENING_EPISODES)}{new_cast_rule(p)}"""


def serial_plot_prompt(p: Project, start: int, end: int) -> str:
    """장편: 앞 화 플롯 전부 대신 접은 줄거리와 이번 아크의 앞 화 플롯만 넣는다."""
    arc = p.arc_for(start)
    lo = arc.start_ep if arc else start
    near = [e.plot for e in p.episodes if max(1, lo - 2) <= e.plot.number < start]
    ids = context.without_off(p, set(arc.cast if arc else []) | {c for e in near for c in e.characters})
    fs, more = relevant_foreshadows(p, start)
    return f"""{start}화부터 {end}화까지 화별 플롯을 작성하세요.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[주역]
{dump(static_characters(p))}
[이 아크의 다른 인물]
{dump(side_characters(p, ids)) or "없음"}
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
{dump(near) if near else "없음"}{candidates_block(p)}
[열린 복선]{f" (그 밖에 {more}개는 이번 아크와 거리가 멀어 뺐습니다)" if more else ""}
{dump(fs) or "없음"}{time_plan(p, start)}{rebuild_map_block(p, start, end)}

요구사항:
{plot_rules(p, start <= OPENING_EPISODES)}{new_cast_rule(p)}"""


def episode_plot_prompt(p: Project, n: int, fit_next: bool = True) -> str:
    """앞뒤가 정해진 화 하나의 플롯. 작가가 적어 둔 칸을 살려 나머지를 채운다.
    fit_next: 바로 뒤 화를 바꾸지 않는 화로 보고 그 시작으로 이어지게 한다 (끼워 넣은 화).
    끄면 작가가 적은 것대로 이 화를 마무리하고, 뒤 화와 어긋나는 점은 next_gap 으로 받는다 (EpisodeDraft)."""
    e = p.episode(n)
    nxt = next((x.plot for x in p.episodes if x.plot.number == n + 1), None)
    seed = {k: v for k, v in e.plot.model_dump().items() if v and k not in ("number", "act")}
    line = p.storyline(e.plot.storyline)
    line_text = (f"\n[이 화가 따라가는 이야기 줄기]\n{storylines.describe(p, line)}\n"
                 f"storyline 칸에 {line.id} 를 그대로 넣습니다." if line else "")
    head = plot_prompt(p, n, n) + f"""

[작가가 이 화에 적어 둔 것 (살려서 나머지 칸을 채울 것)]
{dump(seed) if seed else "없음. 앞뒤 화 사이에 자연스럽게 들어가는 화를 만듭니다"}"""
    if nxt and not fit_next:
        return head + f"""
[바로 뒤 화 플롯 (참고만. 작가가 이 화에 적은 것이 우선)]
{dump(nxt)}{line_text}

이 화에 대한 요구사항:
- {n}화 하나만 씁니다.
- 작가가 적어 둔 제목은 그대로 쓰고, 요약 · 사건 · 등장 인물은 뜻을 바꾸지 않고 살려 다듬고 빈 칸을 채웁니다.
- 작가가 적은 요약이 이 화에서 끝내려는 일을 이 화 안에서 끝까지 마무리합니다. 뒤 화에서 일어나기로 되어 있던 일이라도 작가 요약에 있으면 이 화에서 일으키고, 뒤 화로 미루지 않습니다.
- 작가가 적은 것과 부딪치지 않는 한 뒤 화 시작으로 자연스럽게 넘어가게 엔딩 훅을 씁니다.
- 이 화를 이렇게 마무리해서 뒤 화 플롯과 어긋나게 된 점(뒤 화에서 다시 일어나게 되는 사건, 이어지지 않는 첫 장면, 이미 풀린 갈등 등)을 next_gap 에 뒤 화에서 고칠 것 위주로 한두 문장 적습니다. 어긋나지 않으면 비웁니다."""
    return head + f"""
[바로 뒤 화 플롯 (바꾸지 않음. {n}화의 끝이 이 화의 시작으로 자연스럽게 넘어가야 함)]
{dump(nxt) if nxt else "없음 (마지막 화)"}{line_text}

이 화에 대한 요구사항:
- {n}화 하나만 씁니다. {"앞 화와 바로 뒤 화 사이에 끼워 넣는 화입니다." if nxt else "앞 화에 이어지는 화입니다."}
- 작가가 적어 둔 제목은 그대로 쓰고, 요약 · 사건 · 등장 인물은 뜻을 바꾸지 않고 살려 다듬고 빈 칸을 채웁니다.
- 바로 뒤 화에서 일어날 사건을 미리 일으키거나 뒤 화와 모순되는 사실을 만들지 않습니다. 엔딩 훅은 뒤 화의 시작으로 이어지게 씁니다."""


USE_LABEL = {"keep": "옛 본문 그대로","revise": "옛 본문을 다듬음", "rewrite": "옛 화를 재료로 새로 씀", "new": "새 화"}


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


def time_plan(p: Project, start: int) -> str:
    """기획 프롬프트에 붙는 작품 속 시간 블록 (timeline.plan_block). 기록이 없으면 아무것도 넣지 않는다."""
    b = timeline.plan_block(p, start)
    return f"\n[작품 속 시간 ({start}화 직전)]\n{b}" if b else ""


def lines_block(p: Project) -> str:
    """기획 프롬프트에 붙는 이야기 줄기 블록. 줄기가 없으면 아무것도 넣지 않는다."""
    b = storylines.plan_block(p)
    return f"\n[이야기 줄기 (메인에서 갈라졌다 합류하는 서브플롯 · 회상 · 외전)]\n{b}" if b else ""


def plot_rules(p: Project, opening: bool = False) -> str:
    """화별 플롯을 쓸 때 지킬 규칙. 초안 생성과 대화형 수정이 같이 쓴다.
    opening 이면 1~3화 규칙과 장르별 초반 박자를 붙인다 (다룰 화에 1~3화가 있을 때만, 장편 뒤쪽 프롬프트를 키우지 않게)."""
    pov_rule = pov_plot_rule(p)
    common = f"""- 각 화는 소속 구간(act)의 goal 을 향해 전진해야 하며, 구간의 key_turn 은 해당 구간 안의 특정 화에 배치합니다.
- 한 화에 사건 3~6개, 분량은 약 {p.meta.words_per_episode}자 기준.
- emotional_shift 는 감정 이름이 아니라 감정 변화가 겉으로 드러나는 행동이나 대사로 적습니다 (예: "상대의 전화를 세 번째에야 받는다").
- 모든 화가 같은 모양이 되지 않도록, 필요한 화에는 회상, 시간 건너뛰기, 곁가지 사건, 주인공의 잘못된 선택을 씁니다. 갈등은 너무 깔끔하게 정리하지 않습니다.
- 이야기 요소는 시점을 지킵니다. 'n화부터 생김'은 그 화 전에 사실로 쓰지 않고, '나올 화'에는 그 요소를 사건으로 넣고, '드러나는 화' 전에는 암시만 둡니다.
- characters 에는 인물 id 만 씁니다.
{pov_rule}""" + storylines.plan_rule(p) + (opening_plot_rule(p) if opening else "")
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


def pov_plan_rule(p: Project, unit: str) -> str:
    """기승전결 · 아크 기획 때 서술 시점 운용 규칙. 작가가 정한 기본 시점을 함부로 바꾸지 않게 한다."""
    base = p.style.narration_pov or "정하지 않음"
    return (f"- pov 에는 그 {unit}의 서술 시점 운용을 한 줄로 적습니다 (예: '도현 1인칭', '서윤 3인칭 제한, 도현 시점 장면 교차'). "
            f"작품 기본 시점은 '{base}'입니다. 작가의 요청이나 설정에 시점 전환이 있으면 따르고, "
            f"시점 인물을 바꾸는 것이 이야기에 분명히 도움이 될 때만 바꿉니다. 기본 시점 그대로인 {unit}은 비웁니다.")


def pov_plot_rule(p: Project) -> str:
    """화별 플롯의 pov · pov_mode 규칙."""
    base = p.style.narration_pov or "정하지 않음"
    return (f"- pov 에는 이 화의 시점 인물 id, pov_mode 에는 서술 방식(1인칭, 3인칭 제한, 3인칭 전지)을 적습니다. "
            f"소속 구간이나 아크의 pov 를 따르고, 거기에 시점이 없으면 둘 다 비워 작품 기본 시점('{base}')으로 둡니다. "
            "시점 인물은 그 화의 characters 에 넣습니다. 시점이 바뀌는 화는 첫 장면(opening)에서 누구의 시점인지 드러나게 합니다.")


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
FACTS_RECENT = context.FACTS_RECENT
FORESHADOW_RECENT = 30  # 이 화수 안에 심은 복선은 늘 넣는다
FORESHADOW_CAP = context.FORESHADOW_CAP


def story_so_far(p: Project, n: int) -> str:
    """n화 직전까지의 줄거리. 단편은 화별 요약 전부. 장편은 끝난 부 → 이번 부의 끝난 아크 → 이번 아크의 화 순서로 접어서,
    300화째에도 크기가 일정하다 (story_parts)."""
    return "\n\n".join(x for x in story_parts(p, n) if x)


def story_parts(p: Project, n: int) -> tuple[str, str]:
    """(끝난 부와 아크의 접은 줄거리, 이번 아크의 화별 요약). 앞쪽은 아크가 끝날 때만 바뀌어 캐시가 맞는 자리에 둘 수 있다.
    장편은 블록 예산(context.BUDGET)을 넘으면 오래된 것부터 더 짧게 접는다. 요약이 아직 승인되지 않은 아크는
    화별 요약 → 화마다 첫 문장 → 아크 한 줄 순서로 줄고, 승인된 요약은 마지막에야 첫 문장으로 줄인다."""
    eps = sorted((e for e in p.episodes if e.plot.number < n and e.summary), key=lambda e: e.plot.number)
    line = lambda e: f"{e.plot.number}화 {storylines.summary_tag(p, e)}{timeline.tag(p, e)}{e.plot.title}: {e.summary}"  # noqa: E731
    short = lambda e: f"{e.plot.number}화 {storylines.summary_tag(p, e)}{timeline.tag(p, e)}{e.plot.title}: {context.first_sentence(e.summary)}"  # noqa: E731
    if not p.serial or not p.story_arcs:
        return "", "\n".join(map(line, eps))
    cur_arc = p.arc_for(n)
    cur_part = p.part_for(n)
    arc_start = cur_arc.start_ep if cur_arc else n
    part_start = cur_part.start_ep if cur_part else 1
    entries: list[list[str]] = []  # 블록마다 [자세히, 줄임, 한 줄]

    def arc_entry(a) -> list[str]:
        head = f"[아크 {a.number} {a.title} ({a.start_ep}~{a.end_ep}화)]"
        if a.summary:
            return [f"{head} {a.summary}"] * 2 + [f"{head} {context.first_sentence(a.summary, 200)}"]
        inside = [e for e in eps if a.start_ep <= e.plot.number <= a.end_ep]
        if not inside:
            return [head] * 3
        return [head + "\n" + "\n".join(map(line, inside)),
                f"{head} (아크 요약 대기: 화마다 첫 문장)\n" + "\n".join(map(short, inside)),
                f"{head} 목표: {a.goal} (아크 요약 대기)"]

    for part in sorted(p.parts, key=lambda x: x.start_ep):
        if part.end_ep >= part_start:
            break
        if part.summary:
            head = f"[{part.number}부 {part.title} ({part.start_ep}~{part.end_ep}화)]"
            entries.append([f"{head} {part.summary}"] * 2 + [f"{head} {context.first_sentence(part.summary, 300)}"])
        else:
            entries += [arc_entry(a) for a in p.story_arcs if part.start_ep <= a.start_ep <= part.end_ep]
    if not p.parts:
        part_start = 1
    entries += [arc_entry(a) for a in sorted(p.story_arcs, key=lambda a: a.start_ep) if part_start <= a.start_ep and a.end_ep < arc_start]
    level = [0] * len(entries)
    size = lambda: sum(len(e[k]) + 2 for e, k in zip(entries, level))  # noqa: E731
    for target in (1, 2):  # 오래된 것부터 한 단계씩 접는다
        for i in range(len(entries)):
            if size() <= context.BUDGET["story_past"]:
                break
            level[i] = max(level[i], target)
    past = "\n\n".join(e[k] for e, k in zip(entries, level))

    tail = [e for e in eps if e.plot.number >= arc_start]
    if n - arc_start < 3:  # 아크 첫머리에는 직전 아크의 마지막 화들도 이어서 본다
        tail = [e for e in eps if arc_start - 3 <= e.plot.number < arc_start] + tail
    rows = [line(e) for e in tail]
    keep = 8  # 이번 아크가 길면 최근 8화를 빼고 오래된 화부터 첫 문장으로
    for i in range(max(0, len(tail) - keep)):
        if sum(len(r) + 1 for r in rows) <= context.BUDGET["story_arc"]:
            break
        rows[i] = short(tail[i])
    cur = f"[이번 아크{f' {cur_arc.number} {cur_arc.title}' if cur_arc else ''}]\n" + "\n".join(rows) if tail else ""
    return past, cur


def structure_text(p: Project, n: int, head: str = "[지금 부와 아크]") -> str:
    """n화가 속한 부와 아크, 아크 안 기승전결. 장편 전용."""
    part, arc = p.part_for(n), p.arc_for(n)
    lines = []
    if part:
        lines.append(f"[{part.number}부 {part.title} ({part.start_ep}~{part.end_ep}화)]\n목표: {part.goal}\n전환점: {part.key_turn}")
    if arc:
        lines.append(dump(arc.model_dump(exclude={"summary"}) | {"title": f"아크 {arc.number} {arc.title}"}))
    return head + "\n" + ("\n".join(lines) or "아직 없음")


def state_view(p: Project, states: list, n: int | None = None, query: str = "") -> tuple[list, int]:
    """장편에서는 화마다 쌓이는 knows 를 n화와 관련된 것부터 고른 사본을 쓴다 (context.pick_knows). 저장된 상태는 그대로다.
    query 는 이번 화 플롯이나 본문, 이름은 넘긴 상태의 인물, 요소 · 장소는 n화의 것(context.query_terms). (사본, 뺀 수)"""
    if not p.serial:
        return states, 0
    names = [c.name for c in p.characters if c.id in {s.character_id for s in states}]
    terms = context.query_terms(p, n) if n is not None else []
    out, cut = [], 0
    for s in states:
        knows, k = context.pick_knows(s.knows, query, names, terms)
        out.append(s.model_copy(update={"knows": knows}) if k else s)
        cut += k
    return out, cut


def write_states(p: Project, states: list) -> list:
    """본문 쓰기의 인물 상태. 상태창 수치를 줄 형식(lines)으로 넣거나 넣지 않으면(none) stats 를 뺀다 (statwin.write_rule).
    검수 · 상태 정리는 state_view 그대로 수치를 모두 본다."""
    if p.stat_window.prompt == "json":
        return states
    return [s.model_copy(update={"stats": []}) if s.stats else s for s in states]


def knows_note(cut: int) -> str:
    """인물 상태 머리글에 붙이는 뺀 수. 뺀 것이 없으면 빈 글 (단편은 늘 빈 글)."""
    return f" (아는 정보는 이번 화와 관련된 것부터, {cut}개 생략)" if cut else ""


# ---------- 지금 차림 (CharacterState.attire) ----------
# 옷 · 상처 · 지닌 물건은 화가 넘어가면 요약에서 빠진다. 지금 값만 상태에 덮어써 두고(기록은 화별 스냅샷),
# 쓰기 · 검수 규칙은 차림이 하나라도 기록된 작품에만 붙인다. 상태 변경안은 늘 차림을 적게 한다.

def has_attire(p: Project) -> bool:
    return any(s.attire for s in p.states)


def attire_write_rule(p: Project) -> str:
    """본문 쓰기 프롬프트 끝에 붙는 규칙. 기록된 차림이 없으면 빈 글."""
    if not has_attire(p):
        return ""
    return ("\n\n차림: [인물 현재 상태]의 attire 는 직전 화가 끝났을 때 그 인물의 옷, 몸에 남은 상처 · 얼룩, 지닌 물건입니다. "
            "장면이 이어지면 그대로 지키고, 달라지려면 갈아입거나 다치거나 물건을 잃는 행동을 본문에 보여 줍니다. "
            "날이 바뀌면 옷은 갈아입었을 수 있지만 상처와 지닌 물건은 이어집니다. 차림을 장면마다 묘사하지 않고 필요할 때만 씁니다.")


def attire_check_rule(p: Project) -> str:
    """검수 요구사항에 붙는 한 줄. 기록된 차림이 없으면 빈 글."""
    if not has_attire(p):
        return ""
    return ("\n- 차림: [인물 현재 상태]의 attire(직전 화가 끝났을 때의 옷, 상처, 지닌 물건)와 어긋나는 차림이 갈아입거나 다치거나 잃는 행동 없이 나오는지 봅니다. "
            "날이 바뀌어 옷만 달라진 것은 모순이 아닙니다. type 은 사실, source_episode 는 0, source_quote 는 그 attire 문구입니다.")


ATTIRE_STATE_RULE = (
    "\n- character_updates 의 attire 에는 이번 화가 끝났을 때 그 인물의 옷차림, 몸에 남은 상처 · 얼룩 · 찢어짐, 지니고 다니는 중요한 물건을 "
    "40자 안팎으로 적습니다 (예: '젖은 검은 코트, 왼쪽 소매 찢어짐, 오른손 붕대, 허리에 아버지의 단검'). "
    "본문에서 차림이 처음 드러났거나 바뀐 인물만 적고 그대로면 비웁니다. 바꿀 때는 이어지는 상처와 물건도 함께 다시 적습니다. "
    "본문의 차림이 [이전 인물 상태]의 attire 와 설명 없이 어긋나면 warnings 에 적습니다."
)


def static_characters(p: Project) -> list[Character]:
    """앞 블록(캐시)에 늘 넣는 인물: 주역과 '항상' 인물, '넣지 않음' 은 뺀다 (context.core_ids). 예전 작품은 모두 주역이라 지금과 같다."""
    core = context.core_ids(p)
    return [c for c in p.characters if c.id in core]


def roster_line(p: Project, exclude: set[str]) -> str:
    """설정 전체를 넣지 않는 인물의 한 줄 목록. 플롯이 이미 있는 인물을 다시 만들지 않게 한다. '넣지 않음' 인물도 여기에 이름만 남는다."""
    core = context.core_ids(p)
    return ", ".join(f"{c.id}: {c.name}({c.role})" for c in p.characters if c.id not in core and c.id not in exclude)


def side_characters(p: Project, ids: set[str]) -> list[Character]:
    """ids 중 매 화 넣는 인물(static_characters)이 아니고 '넣지 않음' 도 아닌 인물: 나오는 화에만 설정을 넣는 조연 · 단역."""
    skip = context.core_ids(p) | context.off_ids(p)
    return [c for c in p.characters if c.id in ids and c.id not in skip]


def cast_block(p: Project) -> str:
    """단편 기획 프롬프트의 [인물]: 인물 전부. '넣지 않음' 인물은 설정 대신 id · 이름 · 역할 한 줄 (다시 만들지 않게)."""
    off = context.off_ids(p)
    if not off:
        return dump(p.characters)
    line = ", ".join(f"{c.id}: {c.name}({c.role})" for c in p.characters if c.id in off)
    return f"{dump([c for c in p.characters if c.id not in off])}\n(설정을 넣지 않는 인물 (id: 이름, 역할) — 다시 만들지 않습니다) {line}"


def extra_block(extra: list[Character], cut: int = 0) -> str:
    """본문 쓰기 · 부분 수정의 이번 화 조연 · 단역 설정 블록. cut 은 '항상' 인물 때문에 예산(context.fit_cast)으로 뺀 수."""
    if not extra and not cut:
        return ""
    note = f" ('항상' 넣는 인물 때문에 예산을 넘어 {cut}명은 설정을 뺐습니다. 이름은 등장 인물 줄에 있습니다)" if cut else ""
    return f"{chr(10)}# 이번 화에 나오는 조연 · 단역 설정{note}{chr(10)}{dump(cast_view(extra)) if extra else '없음'}{chr(10)}"


def candidates_block(p: Project) -> str:
    """앞 플롯이 데려왔지만 아직 등록하지 않은 새 인물과 새 장소. 다음 구간 플롯이 같은 인물이나 장소를 또 만들지 않게 한다."""
    out = ""
    if p.cast_candidates:
        out += "\n[새 인물 후보 (앞 플롯이 데려온 인물, 아직 등록 전. 다시 만들지 말고 이 id 를 씁니다)]\n" + dump(p.cast_candidates)
    if p.place_candidates:
        out += "\n[새 장소 후보 (앞 플롯이 지은 장소, 아직 등록 전. 다시 만들지 말고 이 이름을 씁니다)]\n" + dump(p.place_candidates)
    return out


def places_line(p: Project, text: str = "") -> str:
    """이미 있는 장소 이름 한 줄. 장편은 예산까지 (text 에 나오는 이름 먼저) 넣고 뺀 수를 적는다."""
    if p.serial:
        names, more = context.pick_places(p, text, context.BUDGET["places"])
    else:
        names, more = naming.known_places(p), 0
    return (", ".join(names) or "없음") + (f" (그 밖에 {more}곳은 이번 화와 멀어 뺐습니다)" if more else "")


def new_cast_rule(p: Project) -> str:
    """플롯 초안과 플롯 대화가 새 인물을 들일 때의 규칙 (new_characters 칸이 있는 스키마에만 붙인다)."""
    return f"""
- 인물 목록에 없는 인물이 꼭 필요하면 new_characters 에 전체 설정(이름, 역할, 나이, 성별, 성격, 원하는 것, 말투 speech_style)을 넣고, 나오는 화의 characters 에 그 id 를 넣습니다. 여러 화에 걸쳐 나오면 tier 를 support, 한두 화 나오고 마는 인물이면 minor 로 둡니다.
- 이미 있는 인물과 새 인물 후보는 다시 만들지 않습니다. 이름 없는 행인이나 군중은 인물로 만들지 않습니다. 인물 목록에 없는 id 를 characters 에 쓰면 반드시 new_characters 에도 넣습니다.
- 장소 목록, 이야기 요소의 장소, 새 장소 후보에 있는 곳은 그 이름 그대로 씁니다 (띄어쓰기와 '마을', '촌' 같은 끝말도 바꾸지 않습니다).
- 이름을 붙인 새 장소(지형, 마을, 건물, 가게 등)가 필요하면 new_places 에 플롯에 쓴 이름 그대로, kind 에 종류 한 단어, description 에 어떤 곳인지 한 줄을 넣습니다.
- 새 인물 이름은 아래 후보에서 고르거나 같은 결로 짓고, 있는 인물과 이름이 같거나 첫 글자나 끝 글자가 겹치지 않게 합니다.
[이름 후보]
{naming.new_cast_hint(p)}"""


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

    picked = context.rank_foreshadows(p, [f for f in opened if keep(f)], n, FORESHADOW_CAP)
    return picked, len(opened) - len(picked)


def relevant_facts(p: Project, cast: set[str], n: int | None = None, budget: str = "facts") -> tuple[list[str], int]:
    """확정 사실이 많으면 이번 화 인물 이름이 들어간 것과 최근 것만 넣는다.
    장편은 n 화 플롯과 이야기 요소로 관련 순서를 매겨 블록 예산(context.BUDGET[budget])만큼만 넣는다."""
    if len(p.facts) <= FACTS_FILTER_FROM:
        return p.facts, 0
    if p.serial:
        query = elements.plot_text(p.episode(n)) if n is not None and any(e.plot.number == n for e in p.episodes) else ""
        terms = context.query_terms(p, n) if n is not None else []
        return context.pick_facts(p, cast, query, context.BUDGET[budget], terms)
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
{rels(p, context.without_off(p, None))}
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
    opened = [f for f in p.foreshadows if f.status == "open"]
    fs_more = max(0, len(opened) - context.PLAN_FORESHADOW_CAP)
    opened = context.rank_foreshadows(p, opened, start, context.PLAN_FORESHADOW_CAP)  # 끝까지 갈 큰 떡밥과 기한 지난 것 먼저
    ids = context.planning_cast(p, start)
    fs_lines = "\n".join(
        f"- {f.id} ({f.planted_ep}화에 심음, {f.scope}{f', {f.due_ep}화 회수 예정' if f.due_ep else ''}"
        f"{', 오래됨' if start - f.planted_ep > 50 else ''}): {f.description}" for f in opened)
    prev = max(p.story_arcs, key=lambda a: a.start_ep) if p.story_arcs else None
    prev_eps = [e.plot for e in p.episodes if prev and prev.start_ep <= e.plot.number <= prev.end_ep][-3:]
    plan_secrets, _ = context.pick_secrets(p, ids, note + "\n" + "\n".join(x.summary for x in prev_eps),
                                           context.BUDGET["state_secrets"])
    size = f"{length}화 안팎" if length else "내용에 맞게 5~30화 (보통 10~25화). 첫 아크는 25화 안에 큰 보상이 오도록 짧고 세게"
    main_states, knows_cut = state_view(p, [s for s in p.states if s.character_id in {c.id for c in static_characters(p)}],
                                        query=note + "\n" + "\n".join(x.summary for x in prev_eps))
    return f"""장편 연재의 다음 아크 하나를 기획하세요. 이 아크는 {start}화에서 시작합니다.

[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[주역]
{dump(static_characters(p))}
[다른 인물 (id: 이름, 역할)]
{roster_line(p, set()) or "없음"}
[관계 (주역 · 조연 · 최근 아크 인물)]
{describe_relations(p, ids, secrets=plan_secrets) or rels(p, ids)}
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[인물 현재 상태]{knows_note(knows_cut)}
{dump(main_states) or "설정 그대로"}
[부 구성]
{dump(p.parts) if p.parts else "부 구성 없음 (작품 전체가 한 부)"}

[지금까지의 줄거리]
{story_so_far(p, start) or "없음 (첫 아크)"}
[직전 아크]
{dump(prev.model_dump(exclude={"summary"})) if prev else "없음"}
[직전 아크의 마지막 화 플롯]
{dump(prev_eps) if prev_eps else "없음"}
[열린 복선]{f" (그 밖에 {fs_more}개는 오래된 아크 단위 복선이라 뺐습니다)" if fs_more else ""}
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
{pov_plan_rule(p, "아크")}
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
    ids = context.planning_cast(p, written + 1) if p.serial else context.without_off(p, None)
    secrets = context.open_secrets(p) if p.serial else p.secrets  # 장편: 모두에게 드러난 비밀은 뺀다
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
{describe_relations(p, ids, secrets=[] if p.serial else None) or rels(p, ids)}
[비밀 (hidden_from 의 인물은 아직 모른다)]
{dump(secrets) or "없음"}
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
    "작가의 말을 듣고 부 구성, 아크, 기승전결 구간, 화별 플롯을 고친 변경안을 내고, 왜 그렇게 고쳤는지 짧게 설명합니다. "
    "작가가 방향을 청하면 변경안 대신 서로 분명히 다른 방향 여러 안을 내서 고르거나 섞게 합니다. "
    "변경안은 제안일 뿐이며 작가가 골라서 반영합니다. 설정과 인물, 이미 쓴 본문은 존중합니다. "
    "모든 출력은 한국어로 작성합니다."
)

# 대화 기록은 최근 것만 넣는다. 오래된 대화의 결과는 이미 구조와 플롯에 들어가 있다.
CHAT_HISTORY_LIMIT = 12

APPLIED_LABEL = {"acts": "구조", "arc": "아크 칸", "parts": "부 구성"}


def _chat_line(m: ChatMessage) -> str:
    if m.role == "user":
        seen = f" (보던 곳: {m.where})" if m.where else ""
        return f"작가{seen}{' [방향 여러 안 요청]' if m.mode == 'options' else ''}: {m.text}"
    line = f"편집자: {m.text}"
    r = m.revision
    if r and r.options:
        line += "\n  (방향 안: " + " / ".join(f"{i}. {x.title}" for i, x in enumerate(r.options, 1)) + ")"
    elif r and (r.has_changes() or r.total_episodes):
        parts = (["부 구성"] if r.parts else []) + (["아크 칸"] if r.arc.title else []) + (["구조"] if r.acts else []) \
            + [f"{e.number}화" for e in r.episodes]
        applied = ", ".join(APPLIED_LABEL.get(x, f"{x}화") for x in m.applied)
        result = {"applied": f"작가가 반영함: {applied}", "dismissed": "작가가 반영하지 않음"}.get(m.outcome, "아직 결정 전")
        target = {"next": "다음 아크 초안"}.get(m.target, m.target.replace("arc:", "아크 ") if m.target else "")
        line += f"\n  (변경안{f' [{target}]' if target else ''}: {', '.join(parts)} / {result})"
    return line


def request_block(note: str) -> str:
    """구조 · 부 구성 · 플롯 초안을 만들 때 작가가 함께 보낸 요청. 프롬프트 맨 끝에 붙여 앞쪽 캐시를 지킨다."""
    note = (note or "").strip()
    return f"\n\n[작가의 요청]\n{note}\n- 위 요구사항과 부딪히지 않는 한 작가의 요청을 먼저 따릅니다." if note else ""


def _chat_tail(p: Project, message: str, scope, rules: str, options_scope: str) -> str:
    """대화 기록 · 보던 곳 · 새 말 · 요구사항. 화마다 바뀌는 부분이라 맨 뒤에 둔다."""
    from .pipeline import chat_where

    history = next((c.messages for c in p.chats if c.topic == "plot"), [])[-CHAT_HISTORY_LIMIT:]
    where = chat_where(p, scope)
    locked = [e.plot.number for e in p.episodes if e.status in ("written", "finalized")]
    head = f"""[지금까지의 대화]
{chr(10).join(_chat_line(m) for m in history) or "없음 (첫 대화)"}
{f"[작가가 보고 있는 곳] {where} (작가가 '이 화', '여기', '이 구간'이라고 하면 이곳입니다){chr(10)}" if where else ""}
[작가의 새 말]
{message}

요구사항:
"""
    if scope.mode == "options":
        return head + f"""- 작가가 방향 여러 안을 청했습니다. options 에 서로 분명히 다른 방향 2~3개를 넣습니다. 같은 방향의 강약 조절이 아니라 갈등, 인물의 선택, 사건 순서, 결말처럼 줄기가 다르게 갈라지게 합니다.
- 각 안의 idea 에는 그 방향이면 이야기가 어떻게 되는지, changes 에는 바뀌는 {options_scope}을(를) 한 줄씩, tradeoff 에는 얻는 것과 잃는 것을 씁니다.
- 본문이 있는 화({", ".join(map(str, locked)) or "없음"})와 어긋나는 방향은 내지 않습니다.
- acts, episodes, arc, parts, new_characters, new_places 는 모두 비우고 total_episodes 는 0 입니다. 작가가 안을 고르면 그때 변경안을 만듭니다.
- reply 에는 안들을 어떤 기준으로 나눴는지 1~2문장으로 씁니다."""
    return head + f"""- reply 에는 작가에게 하는 대답을 2~5문장으로 씁니다. 무엇을 왜 바꿨는지, 다른 화에 어떤 영향이 있는지 말합니다.
- 요청이 모호하면 가장 그럴듯한 해석으로 고치고, reply 에서 어떻게 해석했는지 밝힙니다. 고칠 것이 없거나 질문만 받았으면 변경 없이 대답만 합니다.
- 작가가 앞서 낸 방향 안 중 하나를 고르거나 섞어 달라고 하면 그 방향으로 변경안을 만듭니다. options 는 비웁니다.
{rules}"""


def plot_chat_prompt(p: Project, message: str, scope=None) -> str:
    """앞쪽은 작품 설정(잘 바뀌지 않음), 뒤쪽은 지금 구조와 플롯, 대화. 캐시가 맞도록 이 순서를 지킨다.
    scope 는 schema.ChatScope (대상 아크, 보던 구간 · 화, 방향 여러 안 모드, 다음 아크 초안)."""
    from .schema import ChatScope

    scope = scope or ChatScope()
    if p.serial:
        return serial_plot_chat_prompt(p, message, scope)
    eps = [{"status": e.status, **e.plot.model_dump()} for e in p.episodes]
    done = [e for e in p.episodes if e.summary]
    locked = [e.plot.number for e in p.episodes if e.status in ("written", "finalized")]
    confirmed = [e.plot.number for e in p.episodes if e.status == "confirmed"]
    style = p.style.model_dump(include={"narration_pov", "pacing", "scene_transition", "dialogue_ratio"})
    open_fs = [f for f in p.foreshadows if f.status == "open"]
    rules = f"""- 바꾸는 것만 넣습니다. 구조를 바꾸면 acts 에 네 구간을 모두 넣고, 그대로면 빈 목록입니다. episodes 에는 바뀌는 화만, 모든 칸을 채운 전체 플롯으로 넣습니다.
{"- 아직 구조가 없습니다. 작가의 말에 맞춰 acts 에 기승전결 네 구간을 새로 짭니다. 화별 플롯은 작가가 청할 때만 넣습니다." + chr(10) if not p.arc else ""}- 본문이 있는 화({", ".join(map(str, locked)) or "없음"})는 바꾸지 않습니다. 그 화의 내용과 이어지도록 뒤의 화를 고칩니다.
- 작가가 확정한 화({", ".join(map(str, confirmed)) or "없음"})는 작가가 그 화를 바꿔 달라고 했을 때만 바꿉니다.
- 한 화를 바꾸면 앞뒤 화의 엔딩 훅, 복선 심기와 회수가 어긋나지 않게 이어지는 화도 함께 고칩니다.
- 총 화수를 바꿔야 하면 total_episodes 에 새 화수를 넣고, acts 를 새 화수에 맞추고, 새로 생기거나 내용이 밀리는 화를 episodes 에 모두 넣습니다. 화수를 바꾸지 않으면 0 입니다.
- 구간은 기, 승, 전, 결 순서로 1화부터 마지막 화까지 빈틈없이 이어집니다.
- arc 와 parts 는 장편에서만 씁니다. arc.title 은 비우고 parts 는 빈 목록입니다.
{plot_rules(p, opening_pending(p))}{new_cast_rule(p)}"""
    return f"""[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[인물]
{cast_block(p)}
[관계]
{rels(p, context.without_off(p, None))}
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[문체 요약 (전개 속도 판단용)]
{dump(style)}

[지금 기승전결 구조] 총 {p.meta.target_episodes}화
{dump(p.arc) if p.arc else "아직 없음"}
[지금 화별 플롯] status: draft 초안, confirmed 작가가 확정, written 본문 있음, finalized 반영 완료
{dump(eps) if eps else "아직 없음"}{candidates_block(p)}
[이미 쓴 화의 실제 줄거리]
{chr(10).join(f"{e.plot.number}화: {e.summary}" for e in done) or "없음"}
[열린 복선]
{dump(open_fs) if open_fs else "없음"}

""" + _chat_tail(p, message, scope, rules, "구간 · 화")


def serial_plot_chat_prompt(p: Project, message: str, scope=None) -> str:
    """장편: 고칠 대상은 화면에서 고른 아크(없으면 pipeline.focus_arc)나 다음 아크 초안, 그리고 부 구성이다.
    앞선 내용은 접은 줄거리로 보고, 화별 플롯은 대상 아크부터 기획한 끝까지만 넣는다 (옛 아크를 고르면 그 아크 범위만)."""
    from .pipeline import ARC_MAX, ARC_MIN, chat_next_limit, chat_target, focus_arc, next_arc_start
    from .schema import ChatScope

    scope = scope or ChatScope()
    target, focus = chat_target(p, scope.target)
    planned = p.planned_until()
    start = next_arc_start(p)
    lo = focus.start_ep if focus else start
    default = focus_arc(p)
    hi = focus.end_ep + 2 if focus and default and focus.start_ep < default.start_ep else planned
    eps = [{"status": e.status, **e.plot.model_dump()} for e in p.episodes if lo - 2 <= e.plot.number <= hi]
    locked = [e.plot.number for e in p.episodes if e.status in ("written", "finalized") and lo <= e.plot.number <= hi]
    confirmed = [e.plot.number for e in p.episodes if e.status == "confirmed"]
    fs, more = relevant_foreshadows(p, lo)
    arcs = [a.model_dump(exclude={"summary"}) for a in p.story_arcs if a.end_ep >= lo - 1 and a.start_ep <= hi]
    ids = context.without_off(p, context.planning_cast(p, lo) | {c for e in p.episodes if lo - 2 <= e.plot.number <= hi for c in e.plot.characters})
    limit = chat_next_limit(p) if start <= p.meta.target_episodes else 0
    if focus:
        last = focus.start_ep == max(a.start_ep for a in p.story_arcs)
        part = p.part_for(focus.start_ep)
        end_limit = part.end_ep if part else p.meta.target_episodes
        target_block = f"""[고칠 아크] 아크 {focus.number} ({focus.start_ep}~{focus.end_ep}화). 구조(acts)와 아크 칸(arc)을 바꾸면 이 아크에 들어갑니다
{dump(focus.model_dump(exclude={"summary"}))}"""
        target_rules = f"""- acts 는 아크 {focus.number}의 기승전결을 바꿀 때만 네 구간 모두, 그대로면 빈 목록입니다. 구간은 {focus.start_ep}화부터 아크 끝 화까지 기, 승, 전, 결 순서로 빈틈없이 이어집니다.
- 아크 칸(제목, 목표, 갈등, 보상, 주요 인물, 회수할 복선, 서술 시점)을 바꿀 때만 arc 에 모든 칸을 채웁니다. 바꾸지 않는 칸은 지금 값을 그대로 씁니다. 그대로면 arc.title 을 비웁니다. cast 에는 이미 있는 인물 id 만 넣습니다.
""" + (f"- 아크 끝 화를 바꾸려면 arc.end_ep 에 새 끝 화({focus.start_ep + ARC_MIN - 1}~{min(end_limit, focus.start_ep + ARC_MAX - 1)}화)를 넣고 acts 도 새 범위에 맞춥니다. 그대로면 0 입니다. 줄일 때 확정했거나 본문이 있는 화는 빼지 않습니다.\n"
       if last else f"- 아크 {focus.number} 뒤에 다음 아크가 이어져 끝 화는 바꿀 수 없습니다. arc.end_ep 는 0 입니다.\n") \
            + f"- 기획한 아크 밖의 화({planned + 1}화부터)는 만들지 않습니다. 그 뒤 아크는 '다음 아크'를 골라 기획합니다."
    else:
        d = scope.draft
        where = f"{limit}화({'부' if p.part_for(start) else '작품'} 끝)"
        target_block = f"""[다음 아크 기획] 아크 {len(p.story_arcs) + 1}, {start}화부터 시작해 {where}까지 끝낼 수 있습니다. 보통 {p.meta.arc_length}화 안팎
[지금 다음 아크 초안 (적용 전, 작가가 손봤을 수 있음)]
{dump({"arc": d.arc.model_dump(exclude={"summary", "number", "start_ep"}), "new_characters": [c.model_dump(include={"id", "name", "role"}) for c in d.new_characters]}) if d else "아직 없음. 작가와 이야기하며 새로 짭니다"}"""
        target_rules = f"""- 다음 아크를 짜거나 고칠 때 arc 에 모든 칸을 채우고 arc.end_ep 에 끝 화({start + ARC_MIN - 1}~{min(limit, start + ARC_MAX - 1)}화)를, acts 에 {start}화부터 끝 화까지 기, 승, 전, 결 네 구간을 넣습니다.{" 초안이 있으면 작가가 말하지 않은 칸은 초안 값을 그대로 둡니다." if d else ""}
- 아크는 하나의 문제를 열고 해결합니다. goal 은 아크가 끝날 때 바뀌어 있어야 하는 것, conflict 는 주인공을 막는 문제나 상대, payoff 는 클라이맥스에서 독자가 받는 보상입니다. 직전 아크와 같은 모양의 갈등을 되풀이하지 않습니다.
- payoffs 에는 열린 복선 id 만 넣습니다. 새 인물이 필요하면 new_characters 에 전체 설정(speech_style 포함)을 넣고 cast 에 그 id 를 넣습니다. tier 는 support 나 minor 입니다.
- 다음 아크의 화별 플롯은 만들지 않습니다 (아크를 적용한 뒤 초안을 만듭니다). episodes 는 이미 기획한 화({planned}화까지) 중 다음 아크와 이어지게 고칠 화가 있을 때만 넣습니다."""
    rules = f"""- 바꾸는 것만 넣습니다. episodes 에는 바뀌는 화만, 모든 칸을 채운 전체 플롯으로 넣습니다.
- 장편이라 total_episodes 는 늘 0 입니다. 총 화수는 설정에서 바꿉니다.
{target_rules}
- 부 구성(부 제목, 범위, 목표, 전환점, 아크 후보)을 바꿔야 할 때만 parts 에 모든 부를 넣습니다. 1화부터 {p.meta.target_episodes}화까지 빈틈없이 이어지고, 이미 기획한 아크(1~{planned}화)의 경계를 넘지 않습니다. summary 는 비웁니다. 그대로면 빈 목록입니다.
- 본문이 있는 화({", ".join(map(str, locked)) or "없음"})는 바꾸지 않습니다.
- 작가가 확정한 화({", ".join(map(str, confirmed)) or "없음"})는 작가가 그 화를 바꿔 달라고 했을 때만 바꿉니다.
- 한 화를 바꾸면 앞뒤 화의 엔딩 훅, 복선 심기와 회수가 어긋나지 않게 이어지는 화도 함께 고칩니다.
{plot_rules(p, opening_pending(p))}{new_cast_rule(p)}"""
    return f"""[작품]
{meta_text(p)}
[세계관]
{dump(p.world)}
[주역]
{dump(static_characters(p))}
[다른 인물 (id: 이름, 역할)]
{roster_line(p, set()) or "없음"}
[관계]
{rels(p, ids)}
[이야기 요소 (작가가 더한 설정과 사건, 시점 포함)]
{elements.plan_block(p) or "없음"}{lines_block(p)}
[부 구성]
{dump(p.parts) if p.parts else "부 구성 없음"}

[지금까지의 줄거리]
{story_so_far(p, lo) or "없음"}
{target_block}
[가까운 아크]
{dump(arcs) if arcs else "아직 없음"}
[화별 플롯] status: draft 초안, confirmed 작가가 확정, written 본문 있음, finalized 반영 완료
{dump(eps) if eps else "아직 없음"}{candidates_block(p)}
[열린 복선]{f" (그 밖에 {more}개)" if more else ""}
{dump(fs) or "없음"}

""" + _chat_tail(p, message, scope, rules, "부 · 아크 · 구간 · 화")


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
    "blocking": ("동선 맞추기", "이 부분에서 인물의 위치, 몸이 향한 쪽, 자세, 손에 든 것, 가려진 곳이 바로 앞 본문과 이어지게 고쳐 주세요. 바뀌어야 하면 바꾸는 행동을 짧게 넣고, 보이지 않는 쪽(등 돌린 사람의 표정, 가린 곳)은 보이는 것처럼 쓰지 않습니다. 뜻과 사건은 그대로 둡니다."),
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
    facts, facts_cut = relevant_facts(p, cast_ids, n)
    cast_ids = context.without_off(p, cast_ids)
    states, knows_cut = state_view(p, [s for s in p.states if s.character_id in cast_ids], n, elements.plot_text(ep) + "\n" + sel.text)
    extra = side_characters(p, cast_ids)
    els = elements.episode_block(p, n)
    chat = next((c for c in p.chats if c.topic == f"text:{n}"), None)
    history = "\n".join(_passage_line(m) for m in (chat.messages[-PASSAGE_HISTORY:] if chat else []))
    hits = [f"{name} {cnt}회" for name, cnt in metrics.pattern_counts(sel.text).items() if cnt] if preset == "less_ai" else []
    request = passage_request(message, preset) or "더 낫게 다듬어 주세요."
    return f"""{static_context(p)}

# 확정된 사실{f" (이번 화와 관련된 것만, {facts_cut}개 생략)" if facts_cut else ""}
{chr(10).join("- " + f for f in facts) or "없음"}{f"{chr(10)}{chr(10)}# 이야기 요소 (이번 화와 관련된 설정, 어기지 말 것){chr(10)}{els}" if els else ""}
{extra_block(extra)}
# 인물 현재 상태 ({n - 1}화 종료 시점){knows_note(knows_cut)}
{dump(states) or "1화 시작 시점, 설정 그대로"}

# 이번 화 플롯
{dump(ep.plot)}{f"{chr(10)}{chr(10)}# 이번 화 서술 시점 (스타일 프로필보다 우선){chr(10)}{pov}" if (pov := pov_block(p, n)) else ""}

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


# ---------- 서술 시점: 화마다 바뀔 수 있다 ----------
# 작품 기본 시점은 스타일 프로필 narration_pov (static_context, 캐시). 화 · 구간 · 아크에 시점을 적으면
# 그 화에만 뒤쪽 블록으로 덮어쓴다. 직전 화 끝부분을 이어 쓰며 시점이 따라 굳는 것을 전환 안내로 끊는다.

def _plan_pov(p: Project, n: int) -> str:
    """n화가 속한 구간, 장편이면 아크에 적은 시점 글."""
    act = p.act_for(n)
    arc = p.arc_for(n) if p.serial else None
    return ((act.pov if act else "") or (arc.pov if arc else "")).strip()


def mode_in(text: str) -> str:
    """시점 글 속 서술 방식 ('1인칭' · '3인칭 제한' · '3인칭 전지'). 없으면 빈 문자열. 화면의 modeIn 과 같은 규칙."""
    if "전지" in text:
        return "3인칭 전지"
    if "3인칭" in text:
        return "3인칭 제한"
    return "1인칭" if "1인칭" in text else ""


def pov_of(p: Project, n: int) -> tuple[str, str]:
    """n화의 서술 시점 (비교 키, 한 줄 설명). 화 플롯 → 구간 → 아크 순서로 찾고, 없으면 ("", "") 곧 작품 기본.
    화에 시점 인물이나 서술 방식 한쪽만 적었으면 나머지는 구간 · 아크 시점에서 물려받는다."""
    e = next((x for x in p.episodes if x.plot.number == n), None)
    if e and (e.plot.pov or e.plot.pov_mode):
        plan = _plan_pov(p, n)
        if e.plot.pov:
            c = next((c for c in p.characters if e.plot.pov in (c.id, c.name)), None)
        else:
            c = None if "전지" in (e.plot.pov_mode + plan) else char_in_text(p, plan)
        who = f"{c.name}({c.id})" if c else e.plot.pov
        mode = e.plot.pov_mode or mode_in(plan) or (f"작품 기본({p.style.narration_pov})" if p.style.narration_pov else "")
        text = ", ".join(x for x in [f"시점 인물 {who}" if who else "", f"서술 {mode}" if mode else ""] if x)
        return f"{c.id if c else e.plot.pov}|{e.plot.pov_mode or mode_in(plan)}", text
    act = p.act_for(n)
    if act and act.pov.strip():
        return act.pov.strip(), act.pov.strip()
    arc = p.arc_for(n) if p.serial else None
    if arc and arc.pov.strip():
        return arc.pov.strip(), arc.pov.strip()
    return "", ""


def char_in_text(p: Project, text: str) -> Character | None:
    """글 속 이름(또는 id)으로 인물 찾기. 글에 먼저 나온 인물을 고르고, 같은 자리면 긴 이름을 고른다
    ('강서윤 시점, 도현 등장' 은 강서윤). 화면의 charInText 와 같은 규칙."""
    if not text:
        return None
    best = None
    for c in p.characters:
        for key in (c.name, c.id):
            i = text.find(key) if key else -1
            if i >= 0 and (best is None or (i, -len(key)) < best[0]):
                best = ((i, -len(key)), c)
    return best[1] if best else None


def pov_character(p: Project, n: int) -> Character | None:
    """n화의 시점 인물. 화에 정한 인물 → 구간 · 아크 시점 글 속 인물 → 작품 기본 시점 글 속 인물(이름이 없고 '주인공'이면 역할이 주인공인 인물).
    전지 시점이면 없음. 화면의 povChar(static/app.js)와 같은 규칙."""
    e = next((x for x in p.episodes if x.plot.number == n), None)
    if e and e.plot.pov:
        return next((c for c in p.characters if e.plot.pov in (c.id, c.name)), None)
    if e and "전지" in e.plot.pov_mode:
        return None
    # 서술 방식만 적은 화는 시점 인물을 구간 · 아크 · 작품 기본에서 물려받는다
    plan = _plan_pov(p, n)
    if plan:
        return None if "전지" in plan else char_in_text(p, plan)
    base = p.style.narration_pov
    if "전지" in base:
        return None
    lead = next((c for c in p.characters if "주인공" in c.role), None) if "주인공" in base else None
    return char_in_text(p, base) or lead


def voice_line(p: Project, n: int) -> str:
    """시점 인물에게 서술 말투가 있으면 그 지시 한 줄."""
    c = pov_character(p, n)
    if not c or not c.narration_voice.strip():
        return ""
    body = "\n".join(f"  {x.strip()}" for x in c.narration_voice.strip().splitlines() if x.strip())
    return (f"- 서술 말투 ({c.name} 시점)\n{body}\n"
            "  지문과 내면 독백에 이 말투를 씁니다. 대사는 인물마다 speech_style 을 따릅니다. "
            "스타일 프로필의 어미 · 시제 · 문체 표지와 부딪히면 이 말투를 따르고, 문장 리듬과 묘사 밀도는 스타일 프로필을 따릅니다.")


def pov_block(p: Project, n: int) -> str:
    """이번 화 서술 시점과, 직전 화와 다르면 전환 안내, 시점 인물의 서술 말투. 어느 것도 없으면 빈칸."""
    key, text = pov_of(p, n)
    prev_key, prev_text = pov_of(p, n - 1) if n > 1 else ("", "")
    voice = voice_line(p, n)
    if not key and not prev_key and not voice:
        return ""
    default = f"작품 기본 시점({p.style.narration_pov})" if p.style.narration_pov else "작품 기본 시점"
    lines = [f"이번 화: {text or default}"]
    e = next((x for x in p.episodes if x.plot.number == n), None)
    mode = (e.plot.pov_mode or p.style.narration_pov) if e else ""
    if key:
        lines.append("- 스타일 프로필의 narration_pov 대신 이 시점을 따릅니다."
                     + ("" if "전지" in mode else " 시점 인물이 보고 듣고 아는 것만 서술하고, 다른 인물의 속마음은 행동과 대사로만 드러냅니다."))
    c = next((c for c in p.characters if e.plot.pov in (c.id, c.name)), None) if e and e.plot.pov else None
    if c and "1인칭" in mode:
        lines.append(f"- 1인칭의 '나'는 {c.name}입니다.")
    if n > 1 and key != prev_key:
        lines.append(f"- 시점이 바뀝니다 (직전 {n - 1}화: {prev_text or default}). 직전 화 끝부분의 시점을 이어받지 말고, "
                     "첫 문단에서 지금 시점 인물이 누구인지 독자가 바로 알게 씁니다.")
        prev = pov_character(p, n - 1)
        if voice and prev and prev.narration_voice.strip() and prev.id != pov_character(p, n).id:
            lines.append(f"- 직전 화 끝부분은 {prev.name}의 서술 말투입니다. 그 어미를 이어 쓰지 않습니다.")
    if voice:
        lines.append(voice)
    return "\n".join(lines)


def build_episode_context(p: Project, n: int) -> str:
    """앞쪽은 화가 바뀌어도 그대로인 블록, 뒤쪽은 화마다 바뀌는 블록이다.
    Claude API 캐시는 앞부분이 같은 요청에 맞으므로(claude.cache_blocks) 이 순서를 지킨다.
    Gemini 4 암묵적 캐시는 화 사이 겹침을 쓰지 않고 앞 요청을 통째로 품은 요청에만 맞는다 (DESIGN.md 실측).
    장편은 줄거리를 부 → 아크 → 화로 접고, 인물·복선·사실을 이번 화에 관련된 것만 골라 크기를 일정하게 둔다."""
    ep = p.episode(n)
    act = p.act_for(n)
    together = p.acts_for(n)[1:]  # 짧은 작품에서 이 화에 함께 들어간 뒤 구간
    cast_ids = set(ep.plot.characters) or {c.id for c in static_characters(p)} or {c.id for c in p.characters}
    cast_names = ", ".join(f"{c.name}({c.id})" for c in p.characters if c.id in cast_ids)  # '넣지 않음' 인물도 이름은 남긴다
    facts, facts_cut = relevant_facts(p, cast_ids, n)
    cast_ids = context.without_off(p, cast_ids)  # 상태 · 관계 · 설정은 '넣지 않음' 인물을 뺀다
    states = [s for s in p.states if s.character_id in cast_ids]
    rels = [r for r in p.relationships if r.a in cast_ids and r.b in cast_ids]
    last_text = next((e.text for e in reversed(p.episodes) if e.plot.number == n - 1 and e.text), "")
    extra, extra_cut = side_characters(p, cast_ids), 0
    if p.serial:  # 장편: '항상' 조연 · 단역이 예산을 차지하면 이번 화 조연 · 단역을 단역부터 뺀다
        always = [c for c in static_characters(p) if c.tier != "main"]
        used = len(dump(cast_view(always))) if always else 0
        extra, extra_cut = context.fit_cast(extra, used, lambda c: len(dump(cast_view([c]))), context.BUDGET["cast"])
    fs, fs_cut = relevant_foreshadows(p, n)
    if p.serial:  # 아크 안 구간은 아크 안에서도 바뀌어 serial_episode_context 가 접은 줄거리 뒤에 둔다 (act_line)
        where = structure_text(p, n, "# 현재 부와 아크")
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
    tl = timeline.episode_block(p, n)
    line += f"\n\n# 작품 속 시간 (어기지 말 것)\n{tl}" if tl else ""
    tr = travel.episode_block(p, n)
    line += f"\n\n# 이동 거리 (지도 기준)\n{tr}" if tr else ""
    pov = pov_block(p, n)
    pov = f"\n\n# 이번 화 서술 시점 (스타일 프로필보다 우선)\n{pov}" if pov else ""
    dev = device_block(p, n)
    dev = f"\n\n# 가끔 쓰는 장치 (최근 화에서 쓴 화를 센 것. 스타일 프로필과 예시 문단보다 우선)\n{dev}" if dev else ""

    facts_text = chr(10).join("- " + f for f in facts) or "없음"
    if p.serial:
        act_line = f"현재 아크 안 구간: {act.name if act else '?'} ({act.start_ep if act else '?'}~{act.end_ep if act else '?'}화) 목표: {act.goal if act else ''}"
        return serial_episode_context(p, n, where=where, act_line=act_line, line=line, facts=facts_text, facts_cut=facts_cut, els=els,
                                      cast_names=cast_names, extra=extra_block(extra, extra_cut), states=states, rels=rels, cast_ids=cast_ids,
                                      fs=fs, fs_cut=fs_cut, last_text=last_text, tail=f"{pov}{dev}{material_block(p, n)}")

    return f"""{static_context(p)}

# 확정된 사실{f" (이번 화와 관련된 것만, {facts_cut}개 생략)" if facts_cut else ""}
{facts_text}{els}

# 이번 화 등장 인물
{cast_names or "설정의 인물 전원"}
{extra_block(extra)}
# 인물 현재 상태 ({n - 1}화 종료 시점)
{dump(write_states(p, state_view(p, states)[0])) or "1화 시작 시점, 설정 그대로"}

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
{dump(ep.plot)}{pov}{dev}{material_block(p, n)}"""


def serial_episode_context(p: Project, n: int, *, where: str, act_line: str, line: str, facts: str, facts_cut: int, els: str,
                           cast_names: str, extra: str, states: list, rels: list, cast_ids: set[str],
                           fs: list, fs_cut: int, last_text: str, tail: str) -> str:
    """장편 본문 쓰기 컨텍스트. 바뀌는 빈도 순서로 놓는다: 작품 고정(static_context) → 아크 동안 그대로인 것
    (부 · 아크 구조, 끝난 아크의 접은 줄거리) → 화마다 바뀌는 것(아크 안 구간 act_line 부터). 앞부분이 같을수록 캐시가 길게 맞는다."""
    past, cur = story_parts(p, n)
    secrets, _ = context.pick_secrets(p, cast_ids, elements.plot_text(p.episode(n)), context.BUDGET["secrets"])
    states, knows_cut = state_view(p, states, n, elements.plot_text(p.episode(n)))
    states = write_states(p, states)
    return f"""{static_context(p)}

{where}

# 지금까지의 줄거리 (끝난 부와 아크)
{past or "없음"}

# 이번 화 위치
{act_line}

# 확정된 사실{f" (이번 화와 관련된 것만, {facts_cut}개 생략)" if facts_cut else ""}
{facts}{els}

# 이번 화 등장 인물
{cast_names or "설정의 인물 전원"}
{extra}
# 인물 현재 상태 ({n - 1}화 종료 시점){knows_note(knows_cut)}
{dump(states) or "1화 시작 시점, 설정 그대로"}

# 관계 현재 상태
{describe_relations(p, cast_ids, secrets=secrets) or dump(rels) or "없음"}

# 열린 복선{f" (이번 아크와 관련된 것만, {fs_cut}개 생략)" if fs_cut else ""}
{dump(fs) or "없음"}

# 지금까지의 줄거리 (이번 아크)
{cur or "없음 (첫 화)"}{line}

# 직전 화 마지막 부분 (내용 연결용, 문체 기준은 위의 예시 문단)
{last_text[-1500:] or "없음"}

# 이번 화 플롯
{dump(p.episode(n).plot)}{tail}"""


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
    style_rules = style.model_dump(exclude={"markers", "devices"}) | {"sample_passages": []}  # 표지 · 장치는 따로 적는다
    return f"""# 작품 정보
{meta_text(p)}

# 세계관 (깨면 안 되는 규칙 포함)
{dump(p.world)}

# 스타일 프로필
{dump(style_rules)}{marker_block(p)}

# 문체 예시 (이 문체를 따를 것, 내용은 가져오지 말 것)
{samples}

# 인물 설정{static_note(p)}
{dump(cast_view(static_characters(p)))}"""


def static_note(p: Project) -> str:
    """앞 블록 인물 설정의 머리 설명. 모두 넣으면 빈 글."""
    cs = static_characters(p)
    if len(cs) >= len(p.characters):
        return ""
    who = "주역과 늘 넣는 인물" if any(c.tier != "main" for c in cs) else "주역"
    return f" ({who}. 조연 · 단역은 나오는 화에만 뒤에 넣는다)"


def device_block(p: Project, n: int) -> str:
    """가끔 쓰는 장치마다 이번 화에 써도 되는지. 최근 화 본문에서 쓴 화를 세므로 화마다 바뀐다 (뒤쪽 블록)."""
    rows = []
    for d in p.style.devices:
        if not d.name.strip():
            continue
        last = metrics.device_last(p.episodes, d.cues, n) if d.cues else 0
        if d.every and last and n - last < d.every:
            rows.append(f"- {d.name}: 이번 화에는 쓰지 않습니다 ({last}화에 썼고 {d.every}화에 한 번까지)")
            continue
        when = f"{d.when.strip()}, 이런 상황에서만" if d.when.strip() else "꼭 맞는 상황에서만"
        info = [f"{d.every}화에 한 번까지"] if d.every else []
        if d.cues:
            info.append(f"마지막으로 쓴 화 {last}화" if last else "아직 쓰지 않음")
        row = f"- {d.name}: {when} 한 번까지 씁니다. 그런 상황이 없으면 쓰지 않습니다" + (f" ({', '.join(info)})" if info else "")
        if d.example.strip():
            row += f"\n  예: {d.example.strip()[:200]}"
        rows.append(row)
    return "\n".join(rows)


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
        + statwin.write_rule(p, n)
        + attire_write_rule(p)
    )


# ---------- 다시 생성 ----------
# 작가가 지난 판을 읽고 다시 써 달라고 할 때. 쓰기 프롬프트(episode_prompt)는 그대로 두고 요청을 맨 뒤에 붙인다
# (앞부분이 같아야 캐시가 맞는다). 화면(rewrite.js)은 서버가 준 빠른 요청과 재료 목록을 그대로 쓴다.

# 빠른 요청: id → (버튼 이름, AI 에게 하는 말)
REWRITE_PRESETS: dict[str, tuple[str, str]] = {
    "slower": ("전개 늦추기", "사건을 서두르지 않습니다. 장면마다 인물의 반응과 망설임을 보여 준 뒤 다음 사건으로 넘어갑니다."),
    "faster": ("전개 빠르게", "설명과 겹치는 장면을 줄이고 사건으로 빨리 들어갑니다. 장면 전환 사이의 군더더기를 덜어 냅니다."),
    "dialogue": ("대사 늘리기", "서술로 넘긴 부분을 인물의 대사와 짧은 행동으로 바꿉니다. 말투는 인물 설정의 speech_style 을 따릅니다."),
    "emotion": ("감정선 살리기", "플롯의 emotional_shift 가 행동, 대사, 사물로 더 분명히 드러나게 합니다. 감정 이름으로 설명하지 않습니다."),
    "hook": ("엔딩 세게", "마지막 장면을 ending_hook 으로 더 날카롭게 끊어, 독자가 다음 화를 바로 누르게 끝냅니다."),
    "plot": ("플롯대로", "이번 화 플롯의 사건을 순서대로 빠짐없이 장면으로 씁니다. 플롯에 없는 큰 사건은 더하지 않습니다."),
    "less_ai": ("쇠맛 줄이기", "AI 가 쓴 티가 나는 표현을 덜어 냅니다. 감정 이름, 정리하는 문장, 번역투, 셋씩 나열, 여운을 노린 짧은 끝 문장 대신 구체적인 행동과 사물을 씁니다."),
    "style": ("문체에 맞게", "스타일 프로필과 문체 예시 문단에 더 가깝게 씁니다. 시점, 시제, 문장 리듬, 대사 처리 방식을 맞춥니다."),
    "length": ("분량 맞추기", "목표 분량에 맞춥니다. 사건을 더하거나 빼지 말고 장면의 밀도로 조절합니다."),
}

# 함께 넣을 재료: id → (화면 이름, 프롬프트 머리말)
REWRITE_MATERIALS: dict[str, tuple[str, str]] = {
    "issues": ("검수에서 찾은 곳", "[검수에서 찾은 곳] 지난 판의 모순입니다. 새 판에는 같은 모순이 없게 합니다."),
    "hook": ("흡입력 판정", "[흡입력 판정] 지난 판을 처음 보는 독자 눈으로 본 결과입니다. 점수가 낮은 항목부터 고칩니다."),
    "style": ("문체 지표 경고", "[문체 지표 경고] 지난 판이 작품의 문체 기준에서 벗어난 곳입니다. 새 판은 기준에 가깝게 씁니다."),
    "edits": ("내가 고친 곳", "[작가가 지난 판에서 직접 고친 곳] 작가가 바라는 방향입니다. 같은 방향으로 쓰고, 고친 뒤의 글은 되도록 살립니다."),
}
REWRITE_KEEP = 5  # 살릴 부분 개수
REWRITE_KEEP_LIMIT = 1500  # 살릴 부분 하나의 글자 수
REWRITE_FULL_LIMIT = 20_000  # 고쳐 쓸 때 넣는 지난 판 본문 한도


def rewrite_block(p: Project, n: int, req, materials: dict[str, list[str]], old: str = "") -> str:
    """다시 쓰기 요청 블록. materials 는 재료 id → 넣을 줄 (pipeline.rewrite_materials). old 는 고쳐 쓸 지난 판 본문."""
    asks = []
    for x in req.presets:
        if x in REWRITE_PRESETS:
            ask = REWRITE_PRESETS[x][1]
            if x == "length" and old:
                ask += f" 지난 판은 {len(old):,}자였고 목표는 약 {p.meta.words_per_episode:,}자입니다."
            asks.append(ask)
    if req.feedback.strip():
        asks.append(req.feedback.strip())
    parts = [f"# {n}화 다시 쓰기\n작가가 지난 판을 읽고 다시 써 달라고 했습니다. 위 자료와 지시는 그대로 지키면서 아래를 반영합니다."]
    parts.append("[작가 요청]\n" + ("\n".join(f"- {a}" for a in asks) if asks else "- 같은 플롯으로 더 낫게 써 주세요."))
    for key in req.materials:
        lines = materials.get(key) or []
        if key in REWRITE_MATERIALS and lines:
            parts.append(REWRITE_MATERIALS[key][1] + "\n" + "\n".join(lines))
    keep = [k.strip() for k in req.keep if k.strip()]
    if keep:
        parts.append("[살릴 부분] 작가가 지난 판에서 마음에 들어 한 글입니다. 거의 그대로, 흐름에 맞는 자리에 넣습니다.\n"
                     + "\n".join(f"«{k}»" for k in keep))
    if req.mode == "revise" and old:
        body = old if len(old) <= REWRITE_FULL_LIMIT else old[:REWRITE_FULL_LIMIT] + "\n(이하 생략)"
        parts.append(f"[지난 판 본문]\n{body}\n\n지난 판의 흐름과 좋은 문장은 살리고, 요청과 지적한 곳을 고쳐 처음부터 끝까지 다시 씁니다. "
                     "바뀐 곳만이 아니라 전문을 씁니다.")
    else:
        parts.append("지난 판을 이어 고치지 말고 처음부터 새로 씁니다.")
    parts.append("설명이나 머리말 없이 본문만 씁니다.")
    return "\n\n".join(parts)


def rewrite_prompt(p: Project, n: int, req, materials: dict[str, list[str]], old: str = "") -> str:
    return episode_prompt(p, n) + "\n\n" + rewrite_block(p, n, req, materials, old)


def state_prompt(p: Project, n: int) -> str:
    ep = p.episode(n)
    if p.serial:  # 장편: 이번 화에 나온 인물과 주역만 자세히, 나머지는 한 줄 목록으로 ('넣지 않음' 인물은 한 줄 목록에)
        ids = context.without_off(p, set(ep.plot.characters) | {c.id for c in static_characters(p)})
        chars = [c for c in p.characters if c.id in ids]
        states, knows_cut = state_view(p, [s for s in p.states if s.character_id in ids], n, ep.text + "\n" + elements.plot_text(ep))
        relations = rels(p, ids)
        fs, _ = relevant_foreshadows(p, n)
        others = roster_line(p, ids)
        # 드러난 비밀, 이번 화 인물과 상관없는 비밀은 빼고 본문과 겹치는 것부터
        secrets, _ = context.pick_secrets(p, ids, ep.text + "\n" + elements.plot_text(ep), context.BUDGET["state_secrets"])
    else:
        chars, states, relations, knows_cut = p.characters, p.states, rels(p), 0
        fs, others = [f for f in p.foreshadows if f.status == "open"], ""
        secrets = p.secrets
        if off := context.off_ids(p):  # '넣지 않음' 인물은 설정 · 상태 · 관계를 빼고 한 줄 목록에 (다시 만들지 않게)
            chars = [c for c in p.characters if c.id not in off]
            states = [s for s in p.states if s.character_id not in off]
            relations = rels(p, context.without_off(p, None))
            others = ", ".join(f"{c.id}: {c.name}({c.role})" for c in p.characters if c.id in off)
    return f"""{n}화 본문을 읽고 상태 변경안을 작성하세요.

[인물 설정]
{dump(chars)}
{f"[다른 인물 (id: 이름, 역할) — 다시 만들지 않습니다]{chr(10)}{others}{chr(10)}" if others else ""}[이전 인물 상태]{knows_note(knows_cut)}
{dump(states) or "설정 그대로"}
[이전 관계]
{relations}
[현재 비밀]
{dump(secrets) or "없음"}
[열린 복선]
{dump(fs) or "없음"}
[이번 화 플롯]
{dump(ep.plot)}
[이미 있는 장소]
{places_line(p, ep.text)}
{f"[작품 속 시간]{chr(10)}{timeline.state_block(p, n)}{chr(10)}" if timeline.enabled(p) else ""}
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
- 아래 [이미 있는 장소]에 없는 장소(지형, 마을, 건물, 가게 등)가 이름을 갖고 처음 나왔으면 new_places 에 넣습니다. name 은 본문에 쓴 그대로, kind 는 종류 한 단어, description 은 본문에서 드러난 것만 한 줄입니다. 이름 없는 길, 방, 골목은 넣지 않습니다.
- 이미 있는 장소를 다른 이름이나 표기로 부른 것이면 new_places 에 넣지 않고 warnings 에 적습니다.
- character_updates 의 location 에는 [이미 있는 장소]나 new_places 의 이름을 표기 그대로 앞에 씁니다 (예: '하르덴 왕궁 서재'). 옮겨 가는 중이면 '하르덴에서 벨라 항구로 가는 배 위'처럼 떠난 곳과 갈 곳을 함께 씁니다.
- warnings 에는 플롯 사건 누락, 설정/말투 위반, 확정 사실과의 모순을 적습니다. 본문 문장이 걸리면 그 문장을 «» 안에 글자 그대로 넣어 작가가 바로 찾게 합니다.{storylines.state_rule(p, n)}{foreshadows.state_rule(p)}{statwin.state_rule(p)}{ATTIRE_STATE_RULE}{charlog.state_rule(p)}{timeline.state_rule(p, n)}"""


def _check_full(p: Project, n: int) -> tuple[str, str, str, str, str, str]:
    """검수 자료 전부: 앞선 본문은 한도(CHECK_TEXT_LIMIT)까지 최근 화부터 원문, 사실 · 상태 · 관계 · 비밀은 모두."""
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
            f"## {e.plot.number}화 {timeline.tag(p, e)}{e.plot.title}\n{e.text}" for e in prior if e.plot.number in full_nos)
    else:
        past = "\n\n".join(
            f"## {e.plot.number}화 {timeline.tag(p, e)}{e.plot.title}\n{e.text if e.plot.number in full_nos else '(요약) ' + e.summary}"
            for e in prior
        )
    off = context.off_ids(p)  # '넣지 않음' 인물의 상태 · 관계는 뺀다
    states = [s for s in p.states if s.character_id not in off] if off else p.states
    relations = rels(p, context.without_off(p, None)) if off else rels(p)
    return (chr(10).join("- " + f for f in p.facts) or "없음", dump(states) or "1화 시작 시점, 설정 그대로",
            relations if p.relationships else "없음", dump(p.secrets) or "없음", past, "")


def check_recall(p: Project, n: int) -> tuple[list, list[tuple[int, list[str]]]]:
    """장편 검수(budget)가 원문으로 넣는 직전 화와 옛 화에서 찾은 단락. 검수 넓히기(pipeline.widen_check)가 첫 검수에 없던 단락을 가려낼 때도 쓴다."""
    ep = p.episode(n)
    ids = context.episode_cast(p, n)
    prior = sorted((e for e in p.episodes if e.plot.number < n and e.text), key=lambda e: e.plot.number)
    recent = prior[-context.CHECK_RECENT:]
    recent_nos = {e.plot.number for e in recent}
    first = min(recent_nos) if recent else n
    terms = context.query_terms(p, n) + context.names_of(p, ids)[1]
    return recent, context.recall(p, first, ep.text + "\n" + elements.plot_text(ep), context.BUDGET["check_recall"], recent_nos, terms)


def _check_budget(p: Project, n: int) -> tuple[str, str, str, str, str, str]:
    """장편 검수 자료: 직전 CHECK_RECENT 화는 원문, 그보다 앞은 접은 줄거리와 이번 화와 겹치는 옛 단락(context.recall),
    사실 · 상태 · 관계 · 비밀은 이번 화 인물과 주역 것만. 예전 방식은 최근 화만 원문이라 오래된 장면과의 모순은 요약으로만 봤다."""
    ep = p.episode(n)
    ids = context.episode_cast(p, n)
    recent, found = check_recall(p, n)
    recent_nos = {e.plot.number for e in recent}
    first = min(recent_nos) if recent else n
    title = {e.plot.number: e.plot.title for e in p.episodes}
    parts = []
    story = story_so_far(p, first) if first > 1 else ""
    if story:
        parts.append(f"## {first - 1}화까지의 줄거리 (요약)\n{story}")
    if found:
        parts.append("## 옛 화에서 찾은 관련 단락 (이번 화와 겹치는 인물 · 장소 · 사물이 나오는 곳. 원문 발췌)\n\n" + "\n\n".join(
            f"### {m}화 {title.get(m, '')} (발췌)\n" + "\n…\n".join(paras) for m, paras in found))
    parts += [f"## {e.plot.number}화 {timeline.tag(p, e)}{e.plot.title}\n{e.text}" for e in recent]
    facts, cut = relevant_facts(p, ids, n, "check_facts")
    facts_text = (f"(이번 화와 관련된 것만, {cut}개 생략)\n" if cut else "") + (chr(10).join("- " + f for f in facts) or "없음")
    picked, knows_cut = state_view(p, [s for s in p.states if s.character_id in ids], n, ep.text + "\n" + elements.plot_text(ep))
    states = (f"(아는 정보는 이번 화와 관련된 것부터, {knows_cut}개 생략)\n" if knows_cut else "") + (dump(picked) or "1화 시작 시점, 설정 그대로")
    relations = describe_relations(p, ids, secrets=[]) or rels(p, ids) or "없음"  # 비밀은 아래 비밀 칸에
    picked, _ = context.pick_secrets(p, ids, ep.text + "\n" + elements.plot_text(ep), context.BUDGET["state_secrets"])
    secrets = dump(picked) or "없음"
    note = (" (직전 화는 원문, 그보다 앞은 줄거리 요약과 이번 화와 겹치는 단락 발췌. 발췌에서 인용할 때 source_episode 는 그 발췌의 화)"
            if found or story else "")
    return facts_text, states, relations, secrets, "\n\n".join(parts), note


CHECK_MODES = {"full": "앞선 본문 한도까지 원문 + 자료 전부 (단편 기본)",
               "budget": "직전 화 원문 + 옛 화에서 찾은 관련 단락 + 이번 화 인물 자료 (장편 기본)"}


SEVERITY_RULE = ("- severity: crit 은 독자가 바로 알아챌 모순이거나 뒤 화 전개를 흔드는 것(죽은 인물이 나옴, 다친 곳을 그냥 씀), "
                 "mid 는 눈여겨 읽으면 보이는 어긋남, low 는 이야기에 영향이 거의 없는 사소한 세부(물건 색, 시각 몇 분 차이)입니다.")


def check_prompt(p: Project, n: int, mode: str = "") -> str:
    """검수 프롬프트. mode 를 비우면 장편은 budget, 단편은 full. 연구 화면 검수 시험이 두 방식을 견준다."""
    return f"""{check_material(p, n, mode)}

{n}화 본문에서 위 자료와 어긋나는 곳을 찾으세요.
- 확인할 것: 확정 사실, 이야기 요소와 세부(이름, 나이, 외모, 장소, 물건), 시간 순서와 인과, 인물이 아직 모르는 정보를 아는 듯 행동하는지, 말투(호칭, 존댓말/반말, 어미), 세계관 규칙, 플롯 사건 누락.
- 동선: 한 장면 안에서 인물의 위치, 몸이 향한 쪽(앞 · 뒤, 등 · 배), 자세, 손에 든 것, 가려진 곳이 바꾸는 행동 없이 달라지는지 봅니다. 예: 등을 돌리고 망토로 몸을 가렸는데 다음 문장에서 그 인물의 표정이나 가슴께가 보임. 이때 source_episode 는 {n}, source_quote 는 같은 화의 앞 문장입니다.
- 시점: 서술이 이 화의 서술 시점(위에 따로 없으면 스타일 프로필의 narration_pov)을 벗어나는지 봅니다. 시점 인물이 볼 수 없거나 아직 모르는 것을 서술함, 1인칭의 '나'가 다른 인물로 바뀜, 장면 구분 없이 시점 인물이 바뀜, 서술 말투가 정해진 화에서 지문의 어미가 그 말투를 벗어남(대사는 보지 않음). 근거가 시점 지시면 source_episode 는 0, source_quote 는 그 지시 문장입니다.{timeline.check_rule(p, n)}{travel.check_rule(p, n)}{attire_check_rule(p)}{statwin.check_rule(p)}
- source_quote 와 current_quote 는 원문을 그대로 옮깁니다. 근거가 설정이나 인물 상태면 source_episode 는 0 입니다.
{SEVERITY_RULE}
- 근거를 인용할 수 없는 의심은 넣지 않습니다. 모순이 없으면 issues 를 빈 목록으로 둡니다.
- episode 는 {n} 입니다."""


def _finding_text(n: int, f: ConsistencyIssue) -> str:
    src = "설정 · 확정 사실" if not f.source_episode else ("이번 화 앞 문장" if f.source_episode == n else f"{f.source_episode}화")
    return (f"- 갈래: {f.type}\n- 무엇이 어긋났나: {f.description}\n- 이번 화 문장: {f.current_quote}\n"
            f"- 근거 ({src}): {f.source_quote}" + (f"\n- 검수가 낸 고칠 방향: {f.suggestion}" if f.suggestion else ""))


def _decided_text(decided: list[ConsistencyIssue]) -> str:
    return "\n".join(f"- {f.current_quote}" for f in decided if f.current_quote.strip()) or "없음"


def fix_prompt(p: Project, n: int, f: ConsistencyIssue, decided: list[ConsistencyIssue]) -> str:
    """검수 지적 하나의 고침안. 앞은 검수와 같은 자료(캐시), 뒤에 지적과 요청. decided: 작가가 그대로 두기로 한 지적."""
    return f"""{check_material(p, n)}

# 고칠 지적
{_finding_text(n, f)}

# 작가가 일부러 그대로 둔 문장 (바꾸지 않음)
{_decided_text(decided)}

이 지적을 풀 고침안을 2~3개 서로 다른 방향으로 내세요.
- text 에는 '이번 화 문장' 자리에 들어갈 글만 씁니다. 앞뒤 본문은 되풀이하지 않습니다. 문체와 길이는 원래 문장과 비슷하게 둡니다.
- 이 고침 때문에 {n}화 안의 다른 문장도 함께 바꿔야 어긋나지 않으면 extra 에 넣습니다. quote 는 {n}화 본문 원문 그대로, replacement 는 최소로 고친 문장, reason 은 왜 함께 바꾸는지 한 문장입니다. 바꿀 곳이 없으면 extra 는 빈 목록입니다.
- '이번 화 문장'은 extra 에 다시 넣지 않습니다. 작가가 그대로 둔 문장은 바꾸지 않습니다. 다른 화와 설정은 바꿀 수 없습니다.
- label 은 고침안 이름 2~8자, note 는 무엇을 바꿨는지 한 줄입니다. reply 는 안들이 어떻게 다른지 한두 문장입니다."""


def recheck_prompt(p: Project, n: int, f: ConsistencyIssue, changes: list[tuple[str, str]],
                   decided: list[ConsistencyIssue]) -> str:
    """검수 지적 하나만 다시 묻는다. 앞은 검수와 같은 자료(캐시), 뒤에 지적과 작가가 고친 곳.
    changes: (고치기 전, 고친 뒤) 쌍. decided: 작가가 그대로 두기로 한 지적."""
    fixed = "\n".join(f"- 「{a}」 → 「{b}」" for a, b in changes) or "없음 (작가가 직접 고쳤거나 고친 곳을 모름)"
    return f"""{check_material(p, n)}

# 다시 볼 지적 (지난 검수가 짚은 것)
{_finding_text(n, f)}

# 작가가 이 지적 때문에 고친 곳
{fixed}

# 작가가 일부러 그대로 둔 문장 (다시 짚지 않음)
{_decided_text(decided)}

이 지적 하나만 다시 보세요. 다른 어긋남을 새로 찾지 않습니다.
- resolved: 지금 {n}화 본문에서 이 지적의 어긋남이 풀렸으면 true 입니다. 이번 화 문장이 바뀌었으면 바뀐 문장을 찾아 봅니다.
- reason: 그렇게 본 까닭을 한두 문장으로 씁니다. 풀리지 않았으면 무엇이 아직 어긋나는지 씁니다.
- new_issues: 작가가 고친 문장 때문에 새로 어긋난 곳만 넣습니다. 근거는 위 자료(앞선 본문, 설정, 확정 사실, {n}화의 다른 문장)에서 원문 그대로 인용합니다. 고친 곳과 상관없던 어긋남, 작가가 그대로 둔 문장은 넣지 않습니다. 없으면 빈 목록입니다.
- new_issues 의 current_quote 는 지금 {n}화 본문 원문 그대로입니다.
{SEVERITY_RULE}"""


def check_material(p: Project, n: int, mode: str = "") -> str:
    """검수 · 고침안 · 다시 검수가 함께 쓰는 자료: 작품 설정부터 검수할 본문까지. 요청은 뒤에 붙인다 (캐시)."""
    mode = mode or ("budget" if p.serial else "full")
    ep = p.episode(n)
    if mode == "budget":
        facts_text, states, relations, secrets, past, note = _check_budget(p, n)
    else:
        facts_text, states, relations, secrets, past, note = _check_full(p, n)
    els = elements.active_block(p, n)
    els = f"\n\n# 이야기 요소 ({n}화 시점에 사실인 것)\n{els}" if els else ""
    line = storylines.episode_block(p, n)
    line = f"\n\n# {n}화의 이야기 줄기\n{line}" if line else ""
    tl = timeline.episode_block(p, n)
    line += f"\n\n# 작품 속 시간\n{tl}" if tl else ""
    tr = travel.episode_block(p, n)
    line += f"\n\n# 이동 거리 (지도 기준)\n{tr}" if tr else ""
    pov = pov_block(p, n)
    pov = f"\n\n# {n}화 서술 시점 (스타일 프로필보다 우선)\n{pov}" if pov else ""
    return f"""{static_context(p)}

# 확정된 사실
{facts_text}{els}

# 인물 현재 상태 ({n - 1}화 종료 시점)
{states}

# 관계 현재 상태
{relations}

# 비밀 (hidden_from 의 인물은 아직 모른다)
{secrets}

# 앞선 본문{note}
{past or "없음 (첫 화)"}

# {n}화 플롯
{dump(ep.plot)}{line}{pov}

# {n}화 본문 (검수 대상)
{ep.text}"""


# ---------- 검수 시험: 모순을 심어 검수가 찾는지 본다 (연구 화면) ----------

SYSTEM_PLANTER = (
    "당신은 소설 검수 도구를 시험하는 편집자입니다. 이번 화 본문의 문장 몇 개를 앞선 내용과 어긋나게 바꿔 "
    "검수가 찾아내는지 봅니다. 바꾼 문장은 문체와 길이가 원래 문장과 비슷해 눈에 띄지 않아야 하고, 근거와 견주면 분명히 틀려야 합니다."
)
PLANT_OLD_EPISODES = 2  # 근거로 보여 줄 옛 화 수 (직전 화들은 빼고 무작위로)
PLANT_OLD_CHARS = 6_000  # 옛 화 하나에서 보여 줄 본문 글자


def plant_old(p: Project, n: int, seed: int) -> list:
    """모순의 근거로 쓸 옛 화. 검수가 원문으로 넣는 직전 화는 빼고 무작위로 골라, 옛 화를 기억하는지 시험한다."""
    import random
    older = [e for e in sorted(p.episodes, key=lambda e: e.plot.number)
             if e.text and e.plot.number < n - context.CHECK_RECENT]
    picks = random.Random(seed).sample(older, min(PLANT_OLD_EPISODES, len(older)))
    return sorted(picks, key=lambda e: e.plot.number)


def plant_prompt(p: Project, n: int, count: int, seed: int = 0) -> str:
    ep = p.episode(n)
    ids = context.episode_cast(p, n)
    old = "\n\n".join(f"## {e.plot.number}화 {e.plot.title}\n{e.text[:PLANT_OLD_CHARS]}" for e in plant_old(p, n, seed))
    return f"""{n}화 본문의 문장 {count}개를 골라 앞선 내용과 어긋나는 문장으로 바꾸세요. 검수 시험용이라 작품에는 저장하지 않습니다.

[인물 설정]
{dump(cast_view(context.characters_by_ids(p, ids)))}
[확정된 사실 (최근)]
{chr(10).join("- " + f for f in p.facts[-FACTS_RECENT:]) or "없음"}
[옛 화 본문 (일부)]
{old or "없음"}

[{n}화 본문]
{ep.text}

요구사항:
- items 에 {count}개를 넣습니다. 근거는 고르게 씁니다: 옛 화 본문이 있으면 그중 하나 이상, 인물 설정(말투, 호칭, 성격, 외형)이나 확정 사실에서 하나 이상, {n}화 앞 문장이 정한 몸 상태(동선)에서 하나 이상.
- 동선 모순은 한 장면 안에서 앞 문장이 정한 상태를 뒤 문장이 바꾸는 행동 없이 어기게 합니다. part 로 갈래를 적습니다.
  - 몸: 한 인물의 위치, 몸이 향한 쪽(앞 · 뒤, 등 · 배), 자세, 가려진 곳. 예: 등을 돌렸는데 표정이 보임.
  - 접촉: 두 인물이 맞닿은 상태(잡은 손 · 손목, 안음 · 업음, 맞닿은 쪽의 좌우)와 그동안 쓸 수 있는 손. 예: 두 손으로 그의 손을 감싸 쥐었는데 한 손으로 찻잔을 듦. 예: 한 팔로 쓰러지는 그녀를 받친 채 다른 손으로 손잡이를 잡았는데, 그대로 두 손을 써서 외투를 벗음.
  - 물건: 인물과 물건의 상태(손에 든 것, 가방 · 주머니 안에 넣은 것, 내려놓은 것, 건넨 것, 칼집에 넣은 칼, 잠근 문), 옷과 멘 것의 겹침 순서, 밀착한 몸 사이의 자리. 예: 가방을 의자에 내려놓았는데 어깨에 멘 가방에서 꺼냄. 예: 백팩을 멘 채 끈을 내리지 않고 그 아래 셔츠를 벗음. 예: 상대가 가슴에 바짝 붙어 있는데 그 사이로 백팩을 앞으로 돌려 멤.
  - 이 화에 그런 장면이 있으면 접촉과 물건을 먼저 고릅니다. type 은 동선, source_episode 는 {n}, source_quote 는 상태를 정한 앞 문장입니다. 동선이 아니면 part 는 비웁니다.
- quote 는 {n}화 본문의 문장 하나를 글자 그대로 옮깁니다. 대사면 따옴표까지 옮깁니다.
- replacement 는 그 문장에서 이름, 숫자, 장소, 관계, 아는 것, 말투, 몸 · 물건의 상태 중 하나만 근거와 어긋나게 바꾼 문장입니다. 나머지는 그대로 둡니다.
- type 은 모순의 종류, source_episode 와 source_quote 는 어긋나는 근거가 나온 화(설정이나 확정 사실이면 0)와 그 원문입니다.
- 서로 다른 문장을 고르고, 앞뒤 문장을 함께 고쳐야만 말이 되는 변경은 피합니다."""


# ---------- 장면 상태표 검수: 몸 · 손 · 옷 · 물건 상태를 적은 뒤 동선만 본다 (연구 화면) ----------
# 모델은 문장마다 그럴듯하게 쓰지만 몸 상태를 따로 기억하지 않는다. 머릿속 장면을 표로 적게 하면 동선을 더 찾는지 검수 시험으로 잰다.

SCENE_BEATS = 40  # 상태표 줄 수 상한

SYSTEM_SCENE = (
    "당신은 소설의 동선을 맞추는 교정 편집자입니다. 본문을 읽으며 장면을 머릿속에 그리고, 그 그림을 상태표로 적은 뒤 "
    "상태표와 어긋나는 문장만 찾습니다. 문장의 좋고 나쁨, 개연성, 취향은 평가하지 않습니다. 모든 출력은 한국어로 작성합니다."
)


def scene_prompt(p: Project, n: int) -> str:
    """이번 화 본문과 등장 인물 이름만 넣는다. 같은 화 앞 문장이 근거라 옛 화와 설정은 넣지 않는다."""
    ep = p.episode(n)
    cast = context.characters_by_ids(p, context.episode_cast(p, n))
    names = "\n".join(f"- {c.name} ({c.role})" for c in cast) or "없음"
    return f"""[등장 인물]
{names}

[{n}화 본문]
{ep.text}

할 일:
1. beats 에 장면 상태표를 먼저 적습니다. 인물의 몸 · 손 · 옷 · 물건 상태를 정하거나 바꾸는 문장마다 한 줄, 최대 {SCENE_BEATS}줄입니다.
- quote 는 그 문장 원문 그대로입니다. bodies 에는 그 문장 뒤의 상태를 상태가 바뀐 인물만 적습니다. 적지 않은 인물과 칸은 앞 줄 그대로입니다.
- facing 은 누구 · 무엇을 향했는지(마주 봄, 등을 댐, 옆), hands 는 두 손 각각 하는 일, worn 은 걸친 것을 안쪽에서 바깥 순서로, front · back 은 몸 앞 · 뒤에 맞닿거나 놓인 사람과 물건, items 는 그 밖의 물건 자리입니다.
- 본문이 말하지 않은 칸은 비웁니다. 짐작으로 채우지 않습니다. 장소나 시간이 바뀌어 장면이 넘어가면 상태를 새로 적습니다.
2. issues 에는 상태표를 따라가며 뒤 문장이 바꾸는 행동 없이 앞 상태와 어긋나는 곳만 적습니다.
- 향한 쪽: 돌아서는 행동 없이 향한 쪽이 바뀜, 등을 진 인물의 얼굴이나 앞모습이 보임.
- 손: 두 손이 다 찬 채 다른 일을 함, 쥔 것을 놓지 않고 그 손으로 다른 것을 함.
- 겹침 순서: 바깥에 걸친 것을 벗지 않고 안쪽 것을 벗거나 입음.
- 몸 사이 자리: 몸 앞이나 뒤가 사람 · 물건으로 찬 채 그 자리에 다른 것을 둠.
- 물건 자리: 내려놓거나 건넨 물건을 다시 집지 않고 씀, 넣은 곳과 다른 곳에서 꺼냄.
- type 은 동선, source_episode 는 {n}, source_quote 는 상태를 정한 앞 문장, current_quote 는 어긋난 문장입니다. 둘 다 원문 그대로 옮깁니다.
- 근거 문장을 인용할 수 없는 의심은 넣지 않습니다. 어긋남이 없으면 issues 를 빈 목록으로 둡니다."""


# ---------- 두 걸음 검수: 진술 뽑기 → 판단기가 근거와 견줌 → 의심만 판정 (연구 화면) ----------
# 긴 검수 입력 하나를 짧은 판단 여러 개로 바꾼다. 판단기(judge.py)는 고르기만 하고, 보고서는 검수 모델이 근거를 인용해 쓴다.

TWOSTEP_CLAIMS = 30  # 한 화에서 뽑는 진술 수 상한
TWOSTEP_EVIDENCE = 3_000  # 진술 하나에 붙이는 근거 글자. 판단기 입력이 8k 토큰 서버에도 들어가게
TWOSTEP_FLAG = 0.25  # '어긋남' 확률이 이 이상이면 의심으로 올린다. 판단기가 놓친 것은 검수 모델도 못 보므로 낮게 잡는다
TWOSTEP_FLAG_MAX = 8  # 검수 모델에 넘기는 의심 진술 수
CLAIM_OPTIONS = ["근거와 맞음", "근거와 어긋남", "근거에 없음"]

SYSTEM_CLAIMS = (
    "당신은 연재 소설의 교정 편집자입니다. 이번 화 본문에서 앞선 내용과 견줘 볼 사실 진술을 뽑습니다. "
    "해석이나 평가는 하지 않습니다. 모든 출력은 한국어로 작성합니다."
)

SYSTEM_JUDGE_CHECK = (
    "당신은 소설 검수용 판단기입니다. 물음의 진술이 자료(앞선 화 발췌, 인물 설정, 작품 설정, 확정 사실, 비밀)와 맞는지 고릅니다. "
    "자료에 같은 대상에 대한 다른 내용이 있으면 어긋남, 같은 내용이 있으면 맞음, 자료가 그 대상을 다루지 않으면 없음입니다. "
    "이름, 숫자, 기간(사흘과 일주일), 나이, 호칭, 존댓말과 반말, 다친 곳, 물건의 주인, 누가 무엇을 아는지가 다르면 어긋남입니다."
)


def claims_prompt(p: Project, n: int) -> str:
    ep = p.episode(n)
    names = ", ".join(f"{c.name}({c.role})" if c.role else c.name for c in context.characters_by_ids(p, context.episode_cast(p, n)))
    return f"""{n}화 본문에서 앞선 화 · 설정 · 확정 사실과 견줘 볼 사실 진술을 최대 {TWOSTEP_CLAIMS}개 뽑으세요.

[등장 인물]
{names or "없음"}

[{n}화 본문]
{ep.text}

요구사항:
- 견줄 거리가 있는 문장을 고릅니다: 인물의 이름 · 나이 · 외모 · 관계 · 호칭, 몸 상태와 다친 곳, 장소와 거리, 물건과 그 주인, 날짜와 시간 순서, 기간과 횟수(사흘, 일주일, 몇 년 전, 몇 번), 누가 무엇을 알고 모르는지, 세계관 규칙, 말투(존댓말 · 반말 · 호칭이 드러나는 대사).
- 숫자 · 기간 · 나이 · 인원이 나오는 문장은 빠짐없이 뽑고, claim 에도 그 숫자를 그대로 씁니다.
- 분위기 묘사, 감정, 이번 화 안에서만 쓰이는 사소한 동작은 뽑지 않습니다.
- quote 는 본문 문장을 글자 그대로 옮깁니다. 대사면 따옴표까지 옮깁니다.
- 진술 하나에는 사실 하나만 씁니다. 한 문장에 견줄 거리가 여럿(호칭과 기간, 인원과 장소 등)이면 같은 quote 로 진술을 여러 개 씁니다.
- claim 은 그 사실을 짧은 평서문 하나로 씁니다. '그', '그녀' 대신 이름을 씁니다. 말투가 거리면 "서윤이 도현에게 반말을 한다"처럼 씁니다.
- 본문 순서대로 씁니다."""


def setting_lines(p: Project) -> list[str]:
    """근거로 고를 작품 설정 줄: 세계관(배경, 시대, 규칙, 장소), 인물의 성격 · 배경 · 목표 · 상처 · 변화, 관계 설명. 문장 단위로 나눈다."""
    out = []
    w = p.world
    out += [f"배경: {x}" for x in metrics.sentences(w.setting)]
    out += [f"시대: {w.era}"] if w.era else []
    out += [f"규칙: {x}" for x in w.rules if x]
    out += [f"장소: {x}" for x in w.locations if x]
    for c in p.characters:
        for label, v in (("성격", c.personality), ("배경", c.background), ("목표", c.goal), ("상처", c.wound), ("변화", c.arc)):
            out += [f"{c.name} {label}: {x}" for x in metrics.sentences(v)]
    names = {c.id: c.name for c in p.characters}
    out += [f"{names.get(r.a, r.a)}와 {names.get(r.b, r.b)}({r.type}): {x}" for r in p.relationships for x in metrics.sentences(r.description)]
    return out


def claim_evidence(p: Project, n: int, claim: Claim, index: context.PassageIndex, budget: int = TWOSTEP_EVIDENCE) -> str:
    """진술 하나에 붙일 근거: 진술에 이름이 나온 인물의 설정, 겹치는 작품 설정 줄 · 확정 사실 · 비밀, 옛 화에서 찾은 단락. LLM 호출 없음."""
    return evidence_text(*claim_sources(p, n, claim, index, budget))


def evidence_text(parts: list[str], found: list[tuple[int, list[str]]]) -> str:
    parts = parts + [f"[{m}화 발췌]\n" + "\n…\n".join(paras) for m, paras in found]
    return "\n\n".join(parts) or "자료 없음"


def claim_sources(p: Project, n: int, claim: Claim, index: context.PassageIndex,
                  budget: int = TWOSTEP_EVIDENCE) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """claim_evidence 의 재료: (설정 · 사실 · 비밀 블록, 옛 화에서 찾은 단락 [(화, [단락...])]). 단락을 따로 돌려 검수 넓히기가 새 단락인지 본다."""
    text = f"{claim.quote}\n{claim.claim}"
    people = [c for c in p.characters if c.name and c.name in text]
    parts, used = [], 0
    if people:
        rows = "\n".join(f"- {c.name}: " + " / ".join(x for x in (c.role, c.age, c.gender, c.appearance, f"말투: {c.speech_style}" if c.speech_style else "") if x)
                         for c in people)[: budget // 4]
        parts.append(f"[인물 설정]\n{rows}")
        used += len(rows)
    lines = context.related_lines(setting_lines(p), text, budget // 5)
    if lines:
        rows = "\n".join("- " + x for x in lines)
        parts.append(f"[작품 설정]\n{rows}")
        used += len(rows)
    facts = context.related_facts(p, text, budget // 4)
    if facts:
        rows = "\n".join("- " + f for f in facts)
        parts.append(f"[확정 사실]\n{rows}")
        used += len(rows)
    if people:
        picked, _ = context.pick_secrets(p, {c.id for c in people}, text, budget // 6)
        if picked:
            names = {c.id: c.name for c in p.characters}
            rows = "\n".join(f"- {s.content} (모르는 인물: {', '.join(names.get(x, x) for x in s.hidden_from)})" for s in picked)
            parts.append(f"[비밀]\n{rows}")
            used += len(rows)
    return parts, index.find(text, max(0, budget - used), [c.name for c in people])


def judge_message(state: str, text: str, options: list[str]) -> str:
    """판단기 질문 하나. 선택지는 A, B, C 글자로 고르게 한다 (LocalJudge 가 그 글자의 확률을 읽는다)."""
    labels = "ABCDEFGH"
    opts = "\n".join(f"{labels[i]}. {o}" for i, o in enumerate(options))
    return f"[자료]\n{state or '없음'}\n\n[물음]\n{text}\n\n[선택지]\n{opts}\n\n선택지 글자 하나로만 답하세요."


def claim_question(claim: Claim) -> str:
    return f"이번 화 문장: {claim.quote}\n진술: {claim.claim}\n이 진술은 자료와 어떤가요?"


def verdict_prompt(p: Project, n: int, items: list[tuple[Claim, str, float]]) -> str:
    """두 걸음 검수 마지막: 판단기가 올린 의심 진술만 근거와 함께 검수 모델에 넣는다. 출력은 보통 검수와 같은 ConsistencyReport."""
    ep = p.episode(n)
    rows = "\n\n".join(f"## {i}. {c.claim}\n이번 화 문장: {c.quote}\n(판단기의 어긋남 확률 {prob:.0%})\n\n{ev}"
                        for i, (c, ev, prob) in enumerate(items, 1))
    return f"""# 세계관 (깨면 안 되는 규칙 포함)
{dump(p.world)}

# 의심 진술과 근거 ({n}화 본문에서 뽑아 판단기가 앞선 자료와 어긋날 수 있다고 본 것)
{rows}

# {n}화 본문 (검수 대상)
{ep.text}

위 의심 진술마다 근거 자료와 견줘 실제로 어긋나는 것만 보고하세요.
- 판단기는 틀릴 수 있습니다. 근거를 직접 읽고 판단합니다. 이야기 안에서 바뀐 까닭이 본문에 있으면 모순이 아닙니다.
- source_quote 와 current_quote 는 원문을 그대로 옮깁니다. 근거가 발췌면 source_episode 는 그 발췌의 화, 인물 설정 · 작품 설정 · 확정 사실 · 비밀 · 세계관이면 0 입니다.
- 근거를 인용할 수 없는 의심은 넣지 않습니다. 모순이 없으면 issues 를 빈 목록으로 둡니다.
- episode 는 {n} 입니다."""


# ---------- 검수 넓히기: 장편 검수(budget)에서 근거를 못 넣은 진술만 옛 화를 더 찾아 다시 묻는다 ----------
# 첫 검수는 이번 화 전체로 한 번 찾은 단락(check_recall)만 본다. 진술마다 따로 찾으면 그때 빠진 단락이 나온다 (Self-Route).

WIDEN_MAX = 8  # 다시 묻는 진술 수 상한. 첫 검수에서 근거를 하나도 못 본 진술부터


def widen_prompt(p: Project, n: int, items: list[tuple[Claim, str]], known: list[ConsistencyIssue]) -> str:
    """검수 넓히기 마지막: 첫 검수에 넣지 않은 옛 단락이 근거로 나온 진술만 그 근거와 함께 검수 모델에 넣는다. 출력은 ConsistencyReport."""
    ep = p.episode(n)
    rows = "\n\n".join(f"## {i}. {c.claim}\n이번 화 문장: {c.quote}\n\n{ev}" for i, (c, ev) in enumerate(items, 1))
    seen = "\n".join(f"- {x.current_quote}" for x in known)
    seen = f"\n\n# 이미 보고한 문장 (다시 넣지 않습니다)\n{seen}" if seen else ""
    return f"""# 세계관 (깨면 안 되는 규칙 포함)
{dump(p.world)}

# 진술과 더 찾은 근거 ({n}화 본문에서 뽑은 진술마다 옛 화 단락을 더 넓게 찾은 것. 대부분은 앞선 검수에서 보지 못한 단락)
{rows}{seen}

# {n}화 본문 (검수 대상)
{ep.text}

위 진술마다 근거 자료와 견줘 실제로 어긋나는 것만 보고하세요.
- 같은 대상(이름, 숫자, 기간, 나이, 호칭, 존댓말과 반말, 다친 곳, 물건의 주인, 누가 무엇을 아는지)에 대한 다른 내용이 근거에 있을 때만 어긋남입니다. 근거가 그 대상을 다루지 않으면 넣지 않습니다.
- 이야기 안에서 바뀐 까닭이 본문에 있으면 모순이 아닙니다.
- source_quote 와 current_quote 는 원문을 그대로 옮깁니다. 근거가 발췌면 source_episode 는 그 발췌의 화, 인물 설정 · 작품 설정 · 확정 사실 · 비밀 · 세계관이면 0 입니다.
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
        summary = e.summary or e.plot.summary
        if p.serial and n not in full and n not in linked:  # 아크 요약 대기 중인 먼 화는 첫 문장만
            summary = context.first_sentence(summary)
        out.append(f"## {n}화 {e.plot.title}\n{e.text if n in full else '(요약) ' + summary}")
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
    chars, relations, facts, texts = p.characters, rels(p), p.facts, impact_texts(p, linked)
    others_line, facts_note, fs_note = "", "", ""
    if p.serial:  # 장편: 요소와 관련 화에 나오는 인물 설정만 자세히, 사실은 요소와 관련된 순서로 예산만큼, 본문은 한도를 줄인다
        ids = {c.id for c in static_characters(p)} | set(el.characters) | {
            c for e in p.episodes if e.plot.number in linked | set(el.episodes) for c in e.plot.characters}
        chars, relations = [c for c in p.characters if c.id in ids], rels(p, ids)
        others_line = roster_line(p, ids)
        if len(p.facts) > FACTS_FILTER_FROM:
            facts, cut = context.pick_facts(p, set(el.characters), f"{el.name} {el.description}",
                                            context.BUDGET["impact_facts"], elements.terms(el))
            facts_note = f" (요소와 관련된 것과 최근 것만, {cut}개 생략)" if cut else ""
        texts = impact_texts(p, linked, context.BUDGET["impact_text"])
        fs_cut = len(open_fs) - context.PLAN_FORESHADOW_CAP
        if fs_cut > 0:
            open_fs = context.rank_foreshadows(p, open_fs, max(linked | {1}), context.PLAN_FORESHADOW_CAP)
            fs_note = f" (회수가 가까운 것과 큰 떡밥 먼저, {fs_cut}개 생략)"
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
{dump(chars)}
{f"[다른 인물 (id: 이름, 역할)]{chr(10)}{others_line}{chr(10)}" if others_line else ""}[관계]
{relations}
[확정된 사실]{facts_note}
{chr(10).join("- " + f for f in facts) or "없음"}
[다른 이야기 요소]
{others or "없음"}

{impact_structure(p)}
[화별 플롯] status: draft 초안, confirmed 작가가 확정, written 본문 있음, finalized 반영 완료{f" (요소와 관련 없는 본문 있는 화 {skipped}개의 플롯은 빼고 아래 본문과 요약으로 대신합니다)" if skipped else ""}
{dump(eps) if eps else "아직 없음"}
[열린 복선]{fs_note}
{dump(open_fs) if open_fs else "없음"}

[이미 쓴 본문]
{texts or "없음 (아직 쓴 화가 없음)"}

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
이미 있는 장소: {places_line(p)}

[대상]
{target}

[코드가 뽑은 후보]
{cand}

요구사항:
- 절반 이상은 위 후보에서 고르고, 나머지는 같은 시대와 결로 새로 짓습니다.
- 이미 있는 인물과 첫 글자나 끝 글자가 겹치는 이름, 이미 있는 장소와 같은 이름은 피합니다.
- reason 에는 이 대상에 맞는 이유를 한 줄로 적습니다 (시대, 나이, 신분, 성격, 지형 등)."""


# ---------- 삽화 프롬프트 (NovelAI) ----------
# AI 는 장면을 태그로 옮기기만 한다. 인물 외형(저장된 태그), 인물 수, 등급, 품질 태그는 canon/illust.py 가 붙인다.

SYSTEM_ILLUSTRATOR = (
    "당신은 소설 삽화를 기획하는 일러스트 디렉터이자 NovelAI 이미지 생성 프롬프트 전문가입니다. "
    "본문의 한 장면을 그림 한 장으로 옮길 때 무엇이 보이는지 정하고, 그것을 Danbooru 식 영어 태그로 적습니다. "
    "태그는 영어 소문자, 낱말 사이는 띄어쓰기, 쉼표 없이 목록 원소 하나에 태그 하나입니다. "
    "본문에 없는 사건이나 인물을 지어내지 않습니다. 설명(scene, note)은 한국어로 씁니다."
)

ILLUST_BEFORE, ILLUST_AFTER = 1_500, 600
ILLUST_FULL_LIMIT = 12_000  # 장면을 AI 가 고를 때 넣는 본문 한도


def _illust_cast(p: Project, n: int, text: str) -> list[dict]:
    """이번 화 등장 인물과 본문에 이름이 나오는 인물: 설정 외모와 저장된 외형 태그, 지금 상태."""
    ep = p.episode(n)
    ids = list(ep.plot.characters) + [c.id for c in p.characters if c.name and c.name in text and c.id not in ep.plot.characters]
    out = []
    for c in p.characters:
        if c.id not in ids:
            continue
        v = p.visual(c.id)
        st = p.state_of(c.id)
        out.append({
            "id": c.id, "name": c.name, "gender": c.gender, "age": c.age, "appearance": c.appearance,
            "saved_look_tags": v.look if v else [], "saved_outfit_tags": v.outfit if v else [],
            "location_now": st.location if st else "",
            "attire_now": st.attire if st else "",
        })
    return out


def illust_prompt(p: Project, n: int, sel: Selection | None, request: str = "") -> str:
    ep = p.episode(n)
    text = ep.text
    if sel is not None:
        start, end = sel.start, sel.start + len(sel.text)
        body = (f"# {n}화 본문 중 그릴 장면 (【그릴 장면】부터 【여기까지】)\n"
                f"{text[max(0, start - ILLUST_BEFORE):start]}【그릴 장면】{sel.text}【여기까지】{text[end:end + ILLUST_AFTER]}")
        pick = "- 【그릴 장면】 안에서 가장 그림이 되는 한순간을 고릅니다. quote 에는 그 순간의 문장을 【그릴 장면】 안에서 원문 그대로 옮깁니다."
    else:
        cut = len(text) > ILLUST_FULL_LIMIT
        body = f"# {n}화 본문{' (앞부분)' if cut else ''}\n{text[:ILLUST_FULL_LIMIT]}"
        pick = ("- 이 화에서 삽화 한 장으로 가장 좋은 장면을 고릅니다. 이 화의 핵심 사건이나 감정이 바뀌는 순간, 인물이 또렷이 보이는 순간을 고르고 "
                "마지막 장면의 반전은 미리 보여 주지 않습니다. quote 에는 그 장면 문장을 본문에서 원문 그대로 1~3문장 옮깁니다.")
    rating = ("성인 독자 대상 작품입니다. 장면에 맞게 general, sensitive, questionable, explicit 중에서 고릅니다."
              if p.meta.adult else "전연령 작품입니다. general 이나 sensitive 만 씁니다. 노출과 잔혹한 묘사는 그림에서 피합니다.")
    return f"""# 작품
제목: {p.meta.title}
장르: {genres.label(p.meta)}
배경: {p.world.setting} / 시대: {p.world.era}
장소: {", ".join(p.world.locations) or "없음"}

# 인물 (saved_look_tags 는 작가가 정한 외형 태그. 프로그램이 그대로 넣는다)
{dump(_illust_cast(p, n, text))}

# 이번 화 플롯
제목: {ep.plot.title}
요약: {ep.plot.summary}

{body}

# 작가의 요청
{request.strip() or "없음"}

요구사항:
{pick}
- characters 에는 그림에 보이는 인물만 넣습니다. 이름이 있는 인물은 위 인물 목록의 id 를 씁니다. 목소리만 나오거나 화면 밖에 있는 인물은 넣지 않습니다.
- 외형 태그(saved_look_tags)가 있는 인물은 look 을 빈 목록으로 둡니다. 없는 인물은 appearance, age, gender 를 보고 look 에 머리 색, 머리 길이와 모양, 눈 색, 체형, 나이대 태그를 넣습니다 (예: black hair, long hair, ponytail, brown eyes, mature female).
- outfit 은 본문에 옷차림이 나오거나 장면에 맞는 옷이 저장된 기본 옷차림(saved_outfit_tags)과 다를 때만 적습니다 (예: school uniform, white shirt, pajamas, armor).
- attire_now 는 가장 최근에 반영한 그 인물의 차림(옷, 상처, 지닌 물건)입니다. 장면 본문이 다르게 말하면 본문을 따르고, 본문에 없으면 attire_now 를 태그로 옮깁니다 (예: torn sleeve, bandaged hand, dagger at hip).
- expression 과 action 은 이 순간의 모습입니다. 시선(looking at viewer, looking at another, looking away), 자세(standing, sitting, kneeling), 손(holding umbrella, hand on own chest)을 구체적으로 적습니다.
- 두 인물이 주고받는 행동은 하는 쪽 action 에 source#행동, 받는 쪽에 target#행동, 서로 하면 둘 다 mutual#행동 으로 적습니다 (예: source#hug, target#hug, mutual#holding hands).
- 인물이 둘 이상이면 position 에 left, center, right 중 하나를 적어 서로 겹치지 않게 합니다.
- setting 에는 장소와 시간대, 날씨를, lighting 에는 빛을, composition 에는 구도와 카메라를 적습니다. 인물 수에 맞는 구도를 고릅니다 (한 명: upper body, cowboy shot / 여럿: wide shot, full body).
- mood 에는 장면의 분위기를 살리는 소품과 효과를 적습니다. 본문에 나온 사물을 우선합니다.
- 1girl, 2boys 같은 인물 수 태그, rating 태그, 품질 태그(masterpiece, best quality), 인물 이름, 작품 이름은 어디에도 넣지 않습니다. 프로그램이 붙입니다.
- caption 은 장면을 영어 한 문장으로 씁니다. 이름 대신 the girl with black hair, the tall man 처럼 씁니다.
- negative 에는 이 장면에서 특히 나오면 안 되는 것만 적습니다 (예: 우산을 쓰지 않은 비 장면이면 umbrella). 일반적인 품질 부정어는 넣지 않습니다.
- rating: {rating}
- scene 에는 고른 장면을 한국어 한 문장으로 적습니다."""


def cast_view(cs: list[Character]) -> list[dict]:
    """본문 · 검수에 넣는 인물 설정. 서술 말투는 그 인물이 시점 인물인 화에만 시점 블록으로 넣는다 (다른 화에 옮아오지 않게).
    신체 프로필(body)은 인물 카드에만 보이는 작가 메모라 넣지 않는다."""
    return [c.model_dump(exclude={"narration_voice", "body", "context"}) for c in cs]


SYSTEM_VOICE = (
    "당신은 한국 웹소설 편집자입니다. 한 인물이 시점 인물인 화에서 서술(지문과 내면 독백)이 어떤 말투로 흘러야 "
    "그 인물답게 읽히는지 정리합니다. 대사 말투가 아니라 서술 말투를 씁니다. 모든 출력은 한국어로 작성합니다."
)


def voice_prompt(p: Project, cid: str, request: str = "") -> str:
    c = next(c for c in p.characters if c.id == cid)
    style = p.style.model_dump(include={"narration_pov", "tense", "sentence_rhythm", "inner_monologue", "vocabulary"})
    return f"""아래 인물이 시점 인물인 화의 서술 말투를 정해 주세요.

# 작품
{meta_text(p)}

# 인물
{dump(c.model_dump(include={"id", "name", "role", "age", "gender", "personality", "background", "goal", "wound", "speech_style", "narration_voice"}))}

# 작품 기본 문체 (다른 시점 화는 이 문체로 씁니다)
{dump(style)}

# 작가의 요청
{request.strip() or "없음"}

요구사항:
- voice 에는 서술 어미와 문장 끝맺음(예: ~했다 / ~했어요 / ~인 걸까요?), 문장 길이와 리듬, 내면 독백을 어떻게 섞는지, 자주 쓰는 표현, 피할 것을 3~6줄로 적습니다.
- 인물의 나이, 성격, 배경, 대사 말투(speech_style)에서 출발하되 대사를 그대로 옮기지 않습니다. 서술은 대사보다 조금 차분해도 됩니다.
- 작품 기본 시점이 3인칭이면 이 인물 화의 서술도 3인칭으로 두고, 어휘와 내면 독백으로만 인물 색을 냅니다. 1인칭이면 '나'의 말투로 씁니다.
- 마지막 줄은 '예: ' 뒤에 이 말투로 쓴 서술 문장 두 개를 붙입니다. 대사(따옴표)는 넣지 않고, 작품의 실제 사건을 지어내지 않습니다.
- 이미 적힌 narration_voice 가 있으면 그것을 살려 다듬습니다.
- note 에는 이 말투를 고른 까닭과, 작품 기본 문체와 달라서 독자가 시점 전환을 알아챌 지점을 한두 문장으로 적습니다."""


def look_prompt(p: Project, cid: str) -> str:
    c = next(c for c in p.characters if c.id == cid)
    v = p.visual(cid)
    return f"""아래 인물을 소설 삽화에서 매번 같은 모습으로 그릴 수 있게 NovelAI 외형 태그로 옮기세요.

# 작품
제목: {p.meta.title}
장르: {genres.label(p.meta)}
배경: {p.world.setting} / 시대: {p.world.era}

# 인물
{dump(c.model_dump(include={"id", "name", "role", "age", "gender", "appearance", "personality", "background"}))}
{f"지금 저장된 태그: {', '.join((v.look if v else []) + (v.outfit if v else []))}" if v and (v.look or v.outfit) else ""}

요구사항:
- subject 는 여성 girl, 남성 boy, 사람이 아니거나 정할 수 없으면 other 입니다.
- look 에는 바뀌지 않는 외형만 6~12개: 머리 색, 머리 길이, 머리 모양, 앞머리, 눈 색, 피부, 체형, 키, 나이대(child, teenage, young adult, mature female, old man 등), 흉터 · 안경 · 점 같은 특징.
- outfit 에는 이 인물이 평소 입는 옷 2~5개를 시대와 배경에 맞게 적습니다.
- 태그는 Danbooru 식 영어 소문자, 낱말 사이는 띄어쓰기, 원소 하나에 태그 하나입니다. 이름, 인물 수(1girl), 품질 태그는 넣지 않습니다.
- 설정에 없는 외형은 나이, 성격, 배경에 어울리게 정하되 흔한 조합(silver hair, red eyes)으로 몰지 않습니다.
- note 에는 설정에서 태그로 옮기기 어려웠던 것이나 새로 정한 것을 한국어 한두 문장으로 적습니다."""


def body_prompt(p: Project, cid: str, minor: bool) -> str:
    """신체 프로필 제안 (pipeline.suggest_body). 신체 프로필은 다른 프롬프트에는 넣지 않고 이 제안에만 쓴다."""
    c = next(c for c in p.characters if c.id == cid)
    have = {k: v for k, v in c.body.model_dump().items() if v.strip()}
    return f"""아래 인물의 신체 프로필(키, 몸무게, 체형, 쓰리사이즈, 신체 특징)을 작품 설정에 맞게 제안하세요. 작가가 칸별로 골라 씁니다.

# 작품
제목: {p.meta.title}
장르: {genres.label(p.meta)}
배경: {p.world.setting} / 시대: {p.world.era}

# 인물
{dump(c.model_dump(include={"name", "role", "age", "gender", "appearance", "personality", "background"}))}
{f"작가가 이미 적은 신체 프로필: {dump(have)}" if have else "작가가 적은 신체 프로필 없음"}

요구사항:
- 설정에 적힌 외모 · 나이 · 성별 · 역할과 어긋나지 않게 정합니다. 작가가 이미 적은 값은 그대로 두고 비어 있는 칸을 채웁니다.
- height 는 cm, weight 는 kg 단위 숫자로 적습니다 (예: 165cm, 48kg). 시대와 나이에 그럴듯한 값으로, 극단으로 몰지 않습니다.
- build 는 체형을 한 줄로 적습니다 (예: 마른 근육형, 어깨가 넓고 다부지다).
{"- 이 인물은 미성년이라 measurements 는 반드시 빈 문자열로 둡니다. 다른 칸에도 몸매를 성적으로 묘사하지 않습니다." if minor else "- measurements 는 가슴-허리-엉덩이 cm 를 하이픈으로 잇습니다 (예: 84-58-86). 성별과 체형에 맞게 적고, 덧붙이는 말은 넣지 않습니다."}
- features 에는 본문에서 이어질 만한 바뀌지 않는 신체 특징 1~3개를 쉼표로 적습니다 (예: 왼손잡이, 오른쪽 손목에 점). 선정적인 묘사는 쓰지 않습니다.
- note 에는 무엇을 근거로 정했는지 한국어 한두 문장으로 적습니다."""



def stat_window_prompt(p: Project, request: str = "") -> str:
    """상태창 꾸미기 제안 (pipeline.suggest_stat_window). 본문 서식 · 창 이름 · 항목 틀 · 화면 스킨을 함께 낸다."""
    w = p.stat_window
    names: list[str] = []
    for s in p.states:
        names += [x.name for x in s.stats if x.name not in names]
    sample = statwin.render(p, next((s.character_id for s in p.states if s.stats), ""), statwin.sample_rows(p)) if names else ""
    skins = "\n".join(f"- {k}: {v}" for k, v in statwin.SKINS.items())
    rules = "\n".join(f"- {r}" for r in p.world.rules[:8])
    return f"""아래 작품에 어울리는 상태창 꾸미기 안을 {2 if request else 3}개 제안하세요. 작가가 하나를 골라 씁니다.

# 작품
제목: {p.meta.title}
장르: {genres.label(p.meta)}
로그라인: {p.meta.logline}
톤: {p.meta.tone}
배경: {p.world.setting} / 시대: {p.world.era}
{f"세계관 규칙:{chr(10)}{rules}" if rules else ""}

# 지금 상태창
항목: {", ".join(names) or "아직 없음"}
{f"지금 서식으로 쓴 예:{chr(10)}{sample}" if sample else f"지금 서식: {w.template!r} / 항목 줄: {w.row!r}"}
{f"{chr(10)}# 작가 요청{chr(10)}{request.strip()}{chr(10)}" if request.strip() else ""}
# 화면 스킨 (skin 에 하나)
{skins}

요구사항:
- 안마다 분위기를 다르게 합니다. 세계관의 말(무협이면 경지 · 내공, 마법 학교면 학년 · 마력 회로, 헌터물이면 등급 · 협회)로 창 이름과 항목 이름을 짓습니다.
- template 은 웹소설 본문에 그대로 붙여 넣는 글입니다. {{name}} 과 {{rows}} 를 꼭 넣고, 마크다운 · HTML · 코드 블록 표시는 쓰지 않습니다. 줄바꿈은 \\n 으로 적습니다.
- 테두리와 장식은 ━ ─ │ ┃ ═ 【】 『』 [ ] ▸ · ◆ 같은 글자만 씁니다. 휴대폰에서 줄이 넘지 않게 한 줄은 24자 안쪽으로 맞춥니다. 장식은 2~3줄로 끝냅니다.
- row 는 항목 한 줄입니다. {{key}} 와 {{value}} 를 꼭 넣습니다 (예: ▸ {{key}} ┃ {{value}}).
- title 은 창 이름이고 template 머리의 이름과 같게 씁니다.
- names 에는 이 세계관에 맞는 항목 이름을 4~8개 적습니다. 지금 항목이 있으면 그 뜻을 살린 이름으로 바꾸거나 그대로 둡니다. 숫자 항목과 목록 항목(스킬 · 칭호 · 인벤토리 같은 것)을 섞습니다.
- skin 은 위 목록에서 세계관에 가장 맞는 것을 고릅니다.
- why 에는 작품 설정의 무엇에 맞췄는지 한국어 한 문장으로 적습니다."""


def stat_init_prompt(p: Project, request: str = "") -> str:
    """1화 전 상태창 처음 수치 제안 (pipeline.suggest_initial_stats). 신체 프로필은 넣지 않는다."""
    keys = {"id", "name", "role", "tier", "age", "gender", "personality", "background", "goal", "wound", "arc"}
    cast = "\n".join(dump(c.model_dump(include=keys)) for c in p.characters)
    have = "\n".join(f"- {s.character_id}: " + ", ".join(f"{x.name} {x.value or '(빈칸)'}" for x in s.stats) for s in p.states if s.stats)
    names = p.stat_window.names
    rules = "\n".join(f"- {r}" for r in p.world.rules[:8])
    return f"""아래 작품의 1화가 시작할 때 인물들의 상태창 수치를 제안하세요. 작가가 인물마다 골라 씁니다.

# 작품
제목: {p.meta.title}
장르: {genres.label(p.meta)}
로그라인: {p.meta.logline}
배경: {p.world.setting} / 시대: {p.world.era}
{f"세계관 규칙:{chr(10)}{rules}" if rules else ""}

# 인물
{cast}

# 상태창 항목
{f"작품 틀(이 항목만, 이 이름 그대로): {', '.join(names)}" if names else "작품 틀이 없습니다. 이 세계관에 맞는 항목 이름 4~8개를 names 에 정합니다."}
{f"작가가 이미 적은 값:{chr(10)}{have}" if have else "작가가 적은 값 없음"}
{f"{chr(10)}# 작가 요청{chr(10)}{request.strip()}{chr(10)}" if request.strip() else ""}
요구사항:
- 상태창이 있는 인물만 characters 에 넣습니다. 세계관 규칙상 상태창을 볼 수 있거나 수치로 재는 인물입니다(흔히 주인공 하나). 단역은 넣지 않습니다.
- 값은 1화가 시작할 때의 값입니다. +3 같은 바뀐 양이 아니라 값 그대로 적습니다(레벨 1, HP 100/100, 1,200골드).
- 로그라인과 배경의 처지에 맞춥니다. 바닥에서 시작하는 주인공은 낮게, 회귀 · 빙의 주인공은 기억은 있어도 몸의 수치는 낮게 둡니다. 성장할 여지를 남깁니다.
- 스킬 · 칭호 · 인벤토리처럼 늘어놓는 항목은 쉼표로 잇습니다. 1화 전에 얻지 않은 것은 넣지 않습니다.
- 작가가 이미 적은 값은 바꾸지 말고 그대로 적습니다. 빈칸만 채웁니다.
- 숫자 단위와 표기는 인물 사이에 맞춥니다(한 인물이 HP 100/100 이면 다른 인물도 같은 꼴).
- note 에는 설정의 무엇을 근거로 정했는지 한국어 한 문장으로 적습니다."""

# ---------- 지도: 장소와 맞지 않은 위치 글 정리 ----------

SYSTEM_PLACE_SORTER = (
    "당신은 연재 소설의 설정 관리 담당 편집자입니다. 상태 기록에 적힌 인물 위치 글이 작품의 어느 장소를 가리키는지 "
    "작품 설정과 화별 요약만 근거로 정리합니다. 근거가 없으면 짐작해 잇지 않습니다."
)


def place_sort_prompt(p: Project, items: list[dict], places: list[dict]) -> str:
    """items: atlas.unmatched 의 {text, characters, episodes}. places: atlas.places."""
    name = {c.id: c.name or c.id for c in p.characters}
    eps = sorted({n for it in items for n in it["episodes"] if n})
    summaries = []
    for n in eps:
        e = p.episode(n) if any(x.plot.number == n for x in p.episodes) else None
        s = (e.summary or e.plot.summary).strip() if e else ""
        if s:
            summaries.append(f"{n}화: {s[:160]}")
    place_lines = []
    for pl in places:
        alias = f" (다른 이름: {', '.join(pl['aliases'])})" if pl["aliases"] else ""
        desc = f": {pl['description'][:80]}" if pl["description"] else ""
        place_lines.append(f"- {pl['name']}{alias}{desc}")
    rows = []
    for i, it in enumerate(items, 1):
        who = ", ".join(name.get(c, c) for c in it["characters"])
        when = ", ".join(f"{n}화" if n else "시작" for n in it["episodes"][:6]) + (" 등" if len(it["episodes"]) > 6 else "")
        rows.append(f"{i}. {it['text']} — {who} · {when}")
    return f"""인물 위치 글마다 작품의 어느 장소인지 정해 주세요. 지도에 인물을 그리는 데 씁니다.

# 작품
제목: {p.meta.title}
배경: {p.world.setting} / 시대: {p.world.era}

# 장소 목록
{chr(10).join(place_lines) or "(아직 없음)"}

# 화별 요약
{chr(10).join(summaries) or "(없음)"}

# 위치 글 (글 — 그 위치에 있던 인물 · 화)
{chr(10).join(rows)}

요구사항:
- 위치 글마다 matches 에 하나씩, text 는 받은 글 그대로 씁니다.
- '서재', '2층 복도', '기숙사 방'처럼 장소 안의 한 곳이면 그곳을 품은 장소를 place 에 [장소 목록]의 이름 그대로 씁니다. 화별 요약과 인물로 어디인지 알 수 있을 때만 잇습니다.
- 장소 목록에 없는 곳을 여러 위치 글이 가리키거나 이야기에서 중요한 곳이면 new_places 에 하나만 넣고 그 글들의 new_place 에 같은 이름을 씁니다. 이름은 위치 글에 나온 이름을 그대로 쓰고 지어내지 않습니다. 방 하나, 길 위, '집'처럼 이름 없는 곳은 새 장소로 만들지 말고 품은 장소에 잇거나 비웁니다.
- 옮겨 가는 중이면 가는 곳에 잇습니다. 꿈속, 회상 속, 알 수 없는 곳처럼 지도의 한 곳으로 그릴 수 없으면 skip 을 true 로 둡니다.
- 정할 근거가 없으면 place, new_place 를 비우고 skip 도 false 로 둡니다. 작가가 직접 고릅니다."""


# ---------- 지도: 마을 만들기 설정 제안 ----------

SYSTEM_MAP_PLANNER = (
    "당신은 소설 배경 지도를 기획하는 편집자입니다. 작품 설정과 장소 설명만 근거로 이 이야기의 마을이나 도시가 어떤 모습인지 정합니다. "
    "좌표나 건물 배치는 프로그램이 정하므로 정하지 않습니다."
)


def map_suggest_prompt(p: Project, rows: list[dict], places: list[dict], kinds: list[tuple[str, str]], options: dict) -> str:
    """rows: atlas.gen_places (지금 고른 종류), places: atlas.places (설명), kinds: (id, 이름),
    options: 지도 종류(village, city)마다 설정 칸 (towngen.OPTIONS, citygen.OPTIONS)."""
    desc = {pl["key"]: pl for pl in places}
    lines = []
    for r in rows:
        pl = desc.get(r["key"], {})
        alias = f" (다른 이름: {', '.join(pl['aliases'])})" if pl.get("aliases") else ""
        about = f": {pl['description'][:100]}" if pl.get("description") else ""
        lines.append(f"- {r['name']}{alias}{about}")
    names = {"village": "마을", "city": "도시"}
    opt = "\n".join(f"## {names.get(kind, kind)} (kind={kind})\n" + "\n".join(
        f"- {key}: " + ", ".join(f"{oid}({label})" for oid, label in vals.items()) for key, vals in opts.items())
        for kind, opts in options.items())
    kind_lines = "\n".join(f"- {cid}: {label}" for cid, label in kinds)
    rules = [r for r in p.world.rules if r.strip()][:8]
    return f"""이 작품의 주 무대가 되는 마을이나 도시 지도를 만들려고 합니다. 지도 생성기에 넣을 설정과 장소마다 종류를 정해 주세요.

# 작품
제목: {p.meta.title}
장르: {genres.label(p.meta) or "정하지 않음"}
배경: {p.world.setting} / 시대: {p.world.era}
{("세계 규칙:" + chr(10) + chr(10).join("- " + r for r in rules)) if rules else ""}

# 장소 목록
{chr(10).join(lines) or "(아직 없음)"}

# 설정 칸 (id(뜻))
{opt}

# 종류 (id: 뜻)
{kind_lines}

요구사항:
- kind 는 village(마을) 나 city(성벽이 있는 도시)입니다. 배경이 도시이거나 성문 · 대성당 · 귀족 저택 · 큰 시장처럼 도시를 바라는 장소가 여럿이면 city, 아니면 village 입니다.
- size, water, fields, forest 는 고른 kind 의 [설정 칸]에서 id 하나씩입니다. roads 는 마을에만 쓰고, 도시면 cross 로 둡니다. 장소 목록과 배경에 맞게 고릅니다.
- 등대, 항구, 어시장, 포구처럼 바다를 바라는 장소가 있으면 water 는 sea, 다리 · 나루 · 방앗간 · 강가가 있으면 river 처럼 장소가 바라는 물을 고릅니다. 근거가 없으면 none 입니다.
- 장소 목록의 장소마다 places 에 하나씩 넣고 name 은 목록의 이름 그대로 씁니다. kind 는 [종류]의 id 하나입니다. 이름에 종류 낱말이 없어도 설명으로 판단합니다 (예: '검은 파도'가 술을 파는 곳이면 inn).
- 왕궁, 다른 도시, 먼 산처럼 이 지도 안에 둘 수 없는 곳은 kind 를 far, put 을 false 로 둡니다. 이 마을이나 도시 자체를 가리키는 이름은 center 입니다.
- 정할 근거가 없으면 kind 는 home, put 은 true 로 둡니다.
- reason 에는 왜 이 설정인지 한국어 한두 문장으로, 장소 설명이나 배경에서 근거를 들어 적습니다."""


# ---------- 플레이 모드 (canon/play.py) ----------
# 한 구간 = Episode 하나 = 흘러간 일 몇 줄과, 있으면 결정 장면 하나. Gemini 암묵 캐시는 구간 사이 앞부분을 다시 쓰지 않아 구간마다 넣는 양이 곧 비용이다 (DESIGN 10.2).
# 장면 프롬프트는 앞쪽에 구간 사이에 덜 바뀌는 것(진행 규칙, 작품, 세계관, 줄인 문체, 플레이어 인물 설정),
# 뒤쪽에 구간마다 바뀌는 것(줄거리, 장면 인물, 사실, 관계, 복선, 시간, 직전 장면, 행동, 운)을 둔다. 블록마다 context.BUDGET["play_*"].
# 상태 변경안은 소설의 state_prompt 를 장면 인물만 남긴 작품 보기(play_view)로 부른다. 소설 경로의 프롬프트는 그대로다.

SYSTEM_PLAY = (
    "당신은 텍스트 게임의 진행자이자 소설가입니다. 플레이어가 한 행동을 받아 그 결과로 이어지는 장면 하나를 쓰고, "
    "다음 행동 선택지를 냅니다. 세계관 규칙은 플레이어의 행동보다 앞섭니다. 규칙에 어긋나는 행동은 실패나 대가로 씁니다."
)

PLAY_PERSON = {"first": "1인칭 ('나')", "second": "2인칭 ('당신')", "third": "3인칭 (플레이어 인물의 이름)"}
LUCK_WORDS = {-2: "아주 나쁨", -1: "나쁨", 0: "보통", 1: "좋음", 2: "아주 좋음"}
PLAY_LAST = 1500  # 직전 장면 끝부분 글자. 구간 본문은 결정 장면이 400~1,200자라 보통 통째로 들어간다
PLAY_SAMPLE = 500  # 줄인 스타일 프로필에 붙이는 예시 문단 글자
PLAY_ROSTER = 600  # 설정을 넣지 않은 인물 이름 줄 글자
PLAY_STORY_KEEP = 5  # 이번 장에서 요약을 줄이지 않는 최근 구간 수
# 줄인 스타일 프로필에 넣는 칸, 넣는 순서. 시점은 플레이마다 고르므로(PlayInfo.person) narration_pov 는 뺀다
PLAY_STYLE_KEYS = ("donts", "banned_phrases", "dos", "dialogue_style", "tense", "sentence_rhythm", "vocabulary",
                   "inner_monologue", "description_density", "dialogue_ratio")

PLAY_RULES = """[진행 규칙]
- 이 게임은 시간이 흐르는 삶입니다. 한 번에 '구간' 하나를 씁니다. 구간은 흘러간 일(beats)과, 플레이어 인물이 무언가 정해야 하는 순간이 오면 결정 장면(text, choices)으로 됩니다.
- beats 에는 [이번 구간]에 적은 시간 칸 안에서 흘러간 일을 시간 순서대로 3~8줄 씁니다. 줄마다 작품 속 시점(time: day 는 날수, part 는 시간대)과 한두 문장. 줄 하나가 시간 한 칸을 넘어도 됩니다. 날수는 앞 구간이 끝난 날보다 앞으로 가지 않습니다.
- 흘러간 일은 [이번 구간]의 초점과 플레이어 인물의 목표 · 성격 · 지금 상태를 따라 플레이어 인물이 스스로 하는 일, 주변 사람의 움직임, 세계의 일입니다. 큰 결정은 흘러간 일 안에서 내리지 않고 결정 장면으로 남깁니다.
- 결정 장면은 플레이어 인물이 갈림길에 서는 순간에만 씁니다(구간마다 꼭 있을 필요는 없습니다). text 에 400~1,200자로 그 순간을 장면으로 쓰고, 플레이어가 골라야 하는 순간에 멈춥니다. 제목, 해설, 선택지 목록은 본문에 쓰지 않습니다. 결정 장면이 오면 그 뒤 일은 쓰지 않습니다.
- choices 에는 결정 장면의 선택지 3~4개를 플레이어 인물이 할 행동 한 줄씩 적습니다. 서로 다른 방향으로 고르고, 장면에 나온 사람 · 물건 · 장소를 씁니다. lean 에는 플레이어 인물의 성격과 목표라면 고를 선택지 번호를 적습니다. 결정 장면이 없으면 text 는 비우고 choices 는 빈 목록, lean 은 0 입니다.
- [이번 행동]은 플레이어 인물이 하려는 '시도'입니다. 구간은 그 결과부터 시작합니다. 결과는 세계관 규칙, 인물 설정, 확정 사실, 지금 상태, 운으로 정합니다. 세계관 규칙이나 지금 능력으로 할 수 없는 행동은 실패하거나 대가를 치르는 것으로 씁니다. 행동에 적힌 결과를 그대로 이루어 주지 않습니다.
- 플레이어 인물의 대사, 속마음은 행동과 초점에 담긴 만큼만 씁니다. 다른 인물은 자기 목표와 성격, 말투대로 움직이고 말합니다.
- 플레이어 인물이 모르는 비밀과 숨긴 정보는 밝히지 않습니다. 플레이어가 알아내려 하면 그 행동에 맞는 단서만 줍니다.
- 열린 복선과 기한은 흐름에 맞을 때 잇고, 억지로 회수하지 않습니다. 이유 없이 인물을 불러오지 않습니다.
- ending 은 플레이어 인물의 이야기가 이 구간에서 끝날 때만 채웁니다: 죽음, 다시 돌아올 수 없게 떠남, 마지막 목표를 이룸, 한도에 닿음. 그때는 마지막 일을 마무리로 쓰고 choices 를 비웁니다. 위험하거나 지는 일만으로는 끝내지 않습니다.
- 이번 구간의 운은 일이 기우는 쪽입니다. '운'이라는 말이나 수치를 쓰지 않고, 우연, 남의 반응, 일이 풀리는 정도로만 드러냅니다."""

PLAY_UNIT_WORDS = {"hour": "한 시간", "day": "하루", "month": "한 달", "year": "한 해"}


def play_player(p: Project, info: PlayInfo) -> Character | None:
    return next((c for c in p.characters if c.id == info.player), None)


def play_person_rule(info: PlayInfo, c: Character | None) -> str:
    """서술 시점 한 줄. 3인칭은 플레이어 인물의 이름을 넣는다."""
    name = c.name if c and c.name else info.player
    rule = {"first": f"'나'는 {name}입니다. 지문과 속마음을 {name}의 눈과 말로 씁니다."
                     + (" 서술 말투는 플레이어 인물 설정의 narration_voice 를 따릅니다." if c and c.narration_voice.strip() else ""),
            "second": f"플레이어 인물({name})을 '당신'이라고 부르고, 당신이 보고 듣고 느끼는 것만 씁니다.",
            "third": f"3인칭 제한 시점입니다. 플레이어 인물은 이름({name})으로 부르고, 그 인물이 보고 듣고 아는 것만 씁니다."}[info.person]
    return f"{PLAY_PERSON[info.person]}. {rule} 다른 인물의 속마음은 행동과 대사로만 드러냅니다."


def play_style(p: Project) -> str:
    """줄인 스타일 프로필: PLAY_STYLE_KEYS 칸을 예산(context.BUDGET['play_style'])까지, 남으면 예시 문단 하나를 앞부분만."""
    style = p.style.model_dump()
    out, used, cut = {}, 2, 0
    for k in PLAY_STYLE_KEYS:
        v = style.get(k)
        if not v:
            continue
        cost = len(dump({k: v}))
        if used + cost > context.BUDGET["play_style"]:
            cut += 1
            continue
        out[k] = v
        used += cost
    text = dump(out) if out else "없음"
    sample = next((s for s in p.style.sample_passages if s.strip()), "")
    room = context.BUDGET["play_style"] - used
    if sample and room > 200:
        clip = sample.strip()[:min(PLAY_SAMPLE, room)]
        text += f"\n\n[문체 예시 (이 문체를 따를 것, 내용은 가져오지 말 것)]\n{clip}"
    return text + (f"\n(스타일 칸 {cut}개는 분량 때문에 뺐습니다)" if cut else "")


def _name_keys(c: Character) -> list[str]:
    """본문에서 인물을 찾을 말: 이름 전체, 띄어 쓴 이름의 첫 말, 성까지 세 글자인 한국 이름의 끝 두 글자."""
    name = c.name.strip()
    keys = [name] if name else []
    parts = name.split()
    if len(parts) > 1 and len(parts[0]) >= 2:
        keys.append(parts[0])
    if len(name) == 3 and " " not in name and all("가" <= ch <= "힣" for ch in name):
        keys.append(name[1:])
    return keys


def _named(c: Character, text: str) -> bool:
    return bool(text) and any(k in text for k in _name_keys(c))


def _place_key(p: Project, location: str) -> str:
    """위치 글 속 가장 긴 아는 장소 이름. 없으면 위치 글 그대로."""
    loc = location.strip()
    hits = [k for k in naming.known_places(p) if k and k in loc]
    return max(hits, key=len) if hits else loc


def play_cast(p: Project, player: str, text: str, action: str = "") -> list[str]:
    """장면 인물 id 를 넣을 순서로: 플레이어, 행동에 이름이 나온 인물, 직전 장면(text)에 나온 인물, 플레이어와 같은 곳에 있는 인물,
    '항상' 인물, 주역. '넣지 않음' 인물은 뺀다 (context.core_ids · off_ids 를 따른다). 엔진이 구간 Episode 의 plot.characters 로 써도 된다."""
    off = context.off_ids(p)
    me = p.state_of(player)
    here = _place_key(p, me.location) if me and me.location.strip() else ""
    core = context.core_ids(p)

    def rank(c: Character) -> int | None:
        st = p.state_of(c.id)
        if _named(c, action):
            return 0
        if _named(c, text):
            return 1
        if here and st and st.location.strip() and _place_key(p, st.location) == here:
            return 2
        if c.context == "always":
            return 3
        if c.id in core:
            return 4
        return None

    ranked = sorted(((r, i, c.id) for i, c in enumerate(p.characters)
                     if c.id != player and c.id not in off and (r := rank(c)) is not None))
    return [player] + [cid for _, _, cid in ranked]


def play_story(p: Project, n: int) -> str:
    """플레이 장면의 줄거리: story_parts 를 플레이 예산으로 다시 접는다. 앞쪽(끝난 장 · 아크 · 부)은 오래된 묶음부터 첫 문장으로,
    그래도 넘치면 오래된 묶음을 뺀다. 이번 장은 최근 PLAY_STORY_KEEP 구간을 빼고 오래된 구간부터 첫 문장으로, 그래도 넘치면 뺀다.
    뺀 수를 적는다. 소설의 story_parts · 예산은 그대로다."""
    past, cur = story_parts(p, n)
    entries = [x for x in past.split("\n\n") if x.strip()]
    size = lambda xs: sum(len(x) + 2 for x in xs)  # noqa: E731
    for i, e in enumerate(entries):
        if size(entries) <= context.BUDGET["play_story_past"]:
            break
        head, _, body = e.partition("]")
        entries[i] = f"{head}] {context.first_sentence(body.strip(), 120)}" if body else e
    dropped = 0
    while entries and size(entries) > context.BUDGET["play_story_past"]:
        entries.pop(0)
        dropped += 1
    lines = cur.splitlines()
    head, rows = (lines[0], lines[1:]) if lines and lines[0].startswith("[") else ("", lines)
    for i in range(max(0, len(rows) - PLAY_STORY_KEEP)):
        if size(rows) <= context.BUDGET["play_story_arc"]:
            break
        lead, sep, body = rows[i].partition(": ")
        rows[i] = f"{lead}{sep}{context.first_sentence(body)}" if sep else context.first_sentence(rows[i])
    shown = 0
    while rows and size(rows) > context.BUDGET["play_story_arc"]:
        rows.pop(0)
        shown += 1
    out = []
    if dropped:
        out.append(f"(오래된 줄거리 {dropped}묶음은 분량 때문에 뺐습니다)")
    out += entries
    if rows or shown:
        out.append("\n".join(([head] if head else []) + ([f"(앞 {shown}화는 분량 때문에 뺐습니다)"] if shown else []) + rows))
    return "\n\n".join(out)


def _play_terms(p: Project, query: str) -> list[str]:
    """query 에 나오는 이야기 요소 이름 · 별칭과 아는 장소 (context.query_terms 의 플레이판: 구간 Episode 가 아직 없어도 된다)."""
    out = [t for el in p.elements if el.context != "off" for t in elements.terms(el) if t in query]
    out += [x for x in naming.known_places(p) if len(x) >= 2 and x in query]
    return list(dict.fromkeys(out))


def _play_states(p: Project, ids: list[str], player: str, query: str, terms: list[str]) -> tuple[list, int]:
    """장면 인물의 지금 상태. 아는 정보는 플레이어 PLAY_KNOWS, 다른 인물 PLAY_KNOWS_OTHER 개 (context.pick_knows). (상태들, 뺀 수)"""
    names = [c.name for c in p.characters if c.id in ids and c.name]
    out, cut = [], 0
    for cid in ids:
        s = p.state_of(cid)
        if not s:
            continue
        limit, recent = context.PLAY_KNOWS if cid == player else context.PLAY_KNOWS_OTHER
        knows, k = context.pick_knows(s.knows, query, names, terms, limit, recent)
        out.append(s.model_copy(update={"knows": knows}) if k else s)
        cut += k
    return write_states(p, out), cut


def _play_elements(p: Project, n: int, ids: set[str], query: str) -> tuple[list[str], int]:
    """장면에 넣을 이야기 요소 줄: '항상' · 이번 구간에 나올 요소, 장면 글에 이름이 나온 요소, 장면 인물이 얽힌 요소 순서로 예산까지."""
    ranked = []
    for el in p.elements:
        if el.context == "off" or not elements.exists_at(el, n):
            continue
        named = any(t in query for t in elements.terms(el))
        if el.context == "always" or n in el.episodes:
            r = 0
        elif named:
            r = 1
        elif set(el.characters) & ids and not el.found_in:
            r = 2
        else:
            continue
        ranked.append((r, elements.describe(p, el, n)))
    lines = [x for _, x in sorted(ranked, key=lambda x: x[0])]
    return context.fit_lines(lines, context.BUDGET["play_elements"])


def _play_turn(info: PlayInfo, n: int, action: str, kind: str = "") -> str:
    """[이번 구간] 줄: 몇 번째 구간인지, 시간 단위와 칸 수, 한도, 초점, 행동의 종류 (흐름 · 고른 선택지 · 자동 결정 · 자유 입력)."""
    turn = n - info.world_ep
    unit = PLAY_UNIT_WORDS.get(info.unit, "하루")
    rows = [f"{turn}번째 구간. 시간 단위는 {unit}, 이번 구간은 많아야 {max(1, info.segment_units)}칸({unit} × {max(1, info.segment_units)})입니다."]
    limits = [x for x in (f"구간 {info.max_turns}개" if info.max_turns else "", f"작품 속 {info.end_days}일" if info.end_days else "",
                          f"결정 {info.end_decisions}번" if info.end_decisions else "") if x]
    if limits:
        rows.append(f"한도: {', '.join(limits)} (먼저 닿는 것)")
    if info.max_turns and turn >= info.max_turns:
        rows.append("이번이 마지막 구간입니다. 이야기를 마무리하고 ending 을 채웁니다.")
    rows.append(f"초점: {info.focus.strip() or '정하지 않음 (플레이어 인물의 목표와 지금 상태를 따른다)'}")
    prev = next((t for t in info.turns if t.number == n - 1), None)
    now = next((t for t in info.turns if t.number == n), None)
    pick = next((c for c in (prev.choices if prev else []) if c.text.strip() == action.strip()), None) if action.strip() else None
    kind = kind or (now.kind if now else ("start" if not prev else "flow" if not action.strip() else "choice" if pick else "free"))
    if kind == "start":
        rows.append("첫 구간입니다. 플레이어 인물 설정과 지금 상태에서 시작해, 플레이어 인물이 어디서 무엇을 하며 사는지 보여 줍니다.")
    elif kind == "flow":
        rows.append("플레이어가 행동하지 않고 시간을 흘려보냈습니다. 앞 구간에서 이어지는 삶을 씁니다.")
    elif kind == "free":
        rows.append("플레이어가 직접 적은 행동입니다 (시도). 세계관 규칙과 지금 능력으로 될 일인지 먼저 따지고, 안 되면 실패나 대가로 씁니다.")
    elif kind == "auto":
        rows.append("플레이어가 자동 결정을 켜 두어, 플레이어 인물이 스스로 고른 선택지입니다.")
    elif kind == "skip":
        rows.append("시간 건너뛰기: 건너뛴 동안의 일은 몇 줄로 접고, 건너뛴 뒤를 이어 씁니다.")
    else:
        rows.append("플레이어가 고른 선택지입니다.")
    return "\n".join(rows)


def play_scene_prompt(p: Project, info: PlayInfo, n: int, action: str, luck: int, kind: str = "") -> str:
    """플레이 n 구간(Episode n) (PlayScene). action 은 플레이어의 행동, 흐름 · 첫 구간은 빈 값. kind 는 PlayTurn.kind (비면 짐작).
    구간 Episode n 이 아직 없어도 된다.
    장면 인물은 play_cast 순서로 플레이어를 빼고 예산(context.BUDGET['play_cast'])까지 설정과 상태를 넣고, 나머지는 이름만."""
    c = play_player(p, info)
    prev = next((e for e in p.episodes if e.plot.number == n - 1 and e.text), None)
    last = prev.text[-PLAY_LAST:] if prev else ""
    query = f"{last}\n{action}"
    terms = _play_terms(p, query)
    order = play_cast(p, info.player, last, action)
    others, cast_cut, used = [], 0, 0
    for cid in order[1:]:
        o = next(x for x in p.characters if x.id == cid)
        st, _ = _play_states(p, [cid], info.player, query, terms)
        cost = len(dump(cast_view([o]))) + len(dump(st))
        if used + cost > context.BUDGET["play_cast"]:
            cast_cut += 1
            continue
        others.append(o)
        used += cost
    ids = [info.player] + [o.id for o in others]
    states, knows_cut = _play_states(p, ids, info.player, query, terms)
    rest = sorted((x for x in p.characters if x.id not in ids),
                  key=lambda x: (not _named(x, query), x.tier != "main", -x.first_ep))
    roster, roster_cut = context.fit_lines([f"{x.id}: {x.name}({x.role})" for x in rest], PLAY_ROSTER)

    facts, facts_cut = context.play_facts(p, set(ids), query, context.BUDGET["play_facts"], terms)
    els, els_cut = _play_elements(p, n, set(ids), query)
    me = c.name if c else ""
    rel_lines = describe_relations(p, ids, secrets=[]).splitlines()
    rel_lines = sorted(rel_lines, key=lambda x: not (me and me in x))
    rels_, rels_cut = context.fit_lines(rel_lines, context.BUDGET["play_relations"])
    secrets, secrets_cut = context.pick_secrets(p, set(ids), query, context.BUDGET["play_secrets"])
    name = {x.id: x.name for x in p.characters}
    secret_lines = [f"- {name.get(s.owner, s.owner)}의 비밀: {s.content} · 모르는 인물: {', '.join(name.get(h, h) for h in s.hidden_from)}"
                    + (" (플레이어 인물도 모름)" if info.player in s.hidden_from else "") for s in secrets]
    opened = [f for f in p.foreshadows if f.status == "open"]
    fs = context.rank_foreshadows(p, opened, n, context.PLAY_FORESHADOW_CAP)
    fs_lines, _ = context.fit_lines([f"- {f.id}: {f.description}" + (f" (회수 예정 {f.due_ep}화)" if f.due_ep else "") for f in fs],
                                    context.BUDGET["play_foreshadows"])
    fs_cut = len(opened) - len(fs_lines)
    tl = timeline.episode_block(p, n)
    first = n == info.world_ep + 1
    player_view = cast_view([c])[0] | ({"narration_voice": c.narration_voice} if info.person == "first" and c.narration_voice.strip() else {}) if c else {"id": info.player}
    note = lambda k, what="이번 장면과 관련된 것만": f" ({what}, {k}개 생략)" if k else ""  # noqa: E731

    return f"""{PLAY_RULES}

[서술 시점]
{play_person_rule(info, c)}

[작품 정보]
{meta_text(p)}

[세계관 (깨면 안 되는 규칙 포함)]
{dump(p.world)}

[스타일 프로필 (줄인 것)]
{play_style(p)}

{prose_rules(styled(p))}

[플레이어 인물]
{dump(player_view)}

[지금까지의 줄거리]
{play_story(p, n) or "아직 없음"}

[이야기 요소]{note(els_cut, "관련된 것만")}
{chr(10).join(els) or "없음"}

[확정된 사실]{note(facts_cut)}
{chr(10).join("- " + f for f in facts) or "없음"}

[장면 인물 설정]{note(cast_cut, "분량 때문에 이름만")}
{dump(cast_view(others)) if others else "없음"}
[다른 인물 (id: 이름, 역할). 설정은 넣지 않았습니다{f", {roster_cut}명 더 있음" if roster_cut else ""}]
{", ".join(roster) or "없음"}

[인물 현재 상태]
({n - 1}화가 끝났을 때{f". 아는 정보는 이번 장면과 관련된 것부터, {knows_cut}개 생략" if knows_cut else ""})
{dump(states) or "설정 그대로"}

[관계]{note(rels_cut)}
{chr(10).join(rels_) or "없음"}

[숨긴 비밀]{note(secrets_cut)}
{chr(10).join(secret_lines) or "없음"}

[열린 복선]{note(fs_cut)}
{chr(10).join(fs_lines) or "없음"}
{f"{chr(10)}[작품 속 시간 (어기지 말 것)]{chr(10)}{tl}{chr(10)}" if tl else ""}
[직전 장면 마지막 부분]{f" (세계 작품 {n - 1}화 끝, 플레이를 시작하기 전)" if first and last else ""}
{last or "없음 (첫 장면)"}

[이번 구간]
{_play_turn(info, n, action, kind)}

[이번 행동]
{action or ("(첫 구간: 플레이어 인물이 처음 등장한다)" if n == info.world_ep + 1 else "(없음: 시간이 흐른다)")}

[이번 구간의 운]
{LUCK_WORDS.get(luck, "보통")}

위 [이번 행동]의 결과부터 이어지는 구간 하나를 쓰세요: 흘러간 일을 beats 에, 결정할 순간이 오면 그 장면을 text 에, 선택지를 choices 에, 이 인물이라면 고를 번호를 lean 에, 결말이면 그 까닭을 ending 에.{statwin.write_rule(p, n)}{attire_write_rule(p)}"""


PLAY_STATE_RULE = (
    "\n- 이 화는 텍스트 게임 플레이의 한 구간이라 본문이 흘러간 일 몇 줄과, 있으면 결정 장면 하나입니다. 본문에 나오지 않은 인물의 상태는 바꾸지 않습니다. "
    "time 에는 본문 마지막 줄의 시점을 적습니다. "
    "summary 는 이번 구간에 플레이어 인물이 한 일과 그 결과를 두세 문장으로 적습니다 (다음 구간 줄거리에 들어갑니다)."
)


def play_state_cast(p: Project, n: int) -> set[str]:
    """n 구간 상태 변경안에서 설정 · 상태 · 관계를 넣을 인물: 플레이어(구간 Episode 의 plot.pov, 없으면 앞 구간의 pov), plot.characters,
    본문에 이름이 나온 인물, '항상' 인물. '넣지 않음' 인물은 뺀다. 2인칭 본문에는 플레이어 이름이 안 나오므로 pov 가 플레이어를 잡는다."""
    ep = p.episode(n)
    known = {c.id for c in p.characters}
    player = next((e.plot.pov for e in sorted(p.episodes, key=lambda e: -e.plot.number)
                   if e.plot.number <= n and e.plot.pov in known), "")
    ids = {player} - {""} | (set(ep.plot.characters) & known)
    ids |= {c.id for c in p.characters if c.context == "always" or _named(c, ep.text)}
    return ids - context.off_ids(p)


def play_view(p: Project, n: int, ids: set[str]) -> tuple[Project, int, int]:
    """상태 변경안용 작품 보기: ids 인물은 '항상', 나머지는 '넣지 않음'으로 둔 얕은 사본. 비밀은 ids 가 얽히고 본문과 겹치는 것을
    예산(context.BUDGET['play_state_secrets'])까지, 열린 복선은 순위대로 PLAY_STATE_FORESHADOW_CAP 개만 남긴다.
    저장하지 않는 보기라 원래 작품은 바뀌지 않는다. (보기, 뺀 비밀 수, 뺀 복선 수)"""
    ep = p.episode(n)
    chars = [c.model_copy(update={"context": "always" if c.id in ids else "off"}) for c in p.characters]
    secrets, secrets_cut = context.pick_secrets(p, ids, ep.text + "\n" + elements.plot_text(ep), context.BUDGET["play_state_secrets"])
    opened = [f for f in p.foreshadows if f.status == "open"]
    fs = context.rank_foreshadows(p, opened, n, context.PLAY_STATE_FORESHADOW_CAP)
    view = p.model_copy(update={"characters": chars, "secrets": secrets, "foreshadows": fs})
    return view, secrets_cut, len(opened) - len(relevant_foreshadows(view, n)[0])  # state_prompt 가 더 거르는 것까지 센다


def play_state_prompt(p: Project, n: int) -> str:
    """플레이 n 구간의 상태 변경안 (StateDelta). 소설의 state_prompt 를 장면 인물만 남긴 보기(play_view)로 부르고 플레이 규칙을 덧붙인다.
    장면에 나오지 않은 인물은 '다른 인물' 한 줄 목록에 이름만 남아 새 인물로 다시 만들지 않는다. 플레이 사본은 늘 장편이라
    단편 작품이면 소설과 같은 프롬프트를 낸다."""
    if not p.serial:
        return state_prompt(p, n)
    view, secrets_cut, fs_cut = play_view(p, n, play_state_cast(p, n))
    cut = (f"\n- [현재 비밀]과 [열린 복선]은 이번 구간 인물과 관련된 것만 넣었습니다 (비밀 {secrets_cut}개, 복선 {fs_cut}개 생략). "
           "목록에 없는 비밀 · 복선의 id 는 쓰지 않습니다.") if secrets_cut or fs_cut else ""
    return state_prompt(view, n) + PLAY_STATE_RULE + cut
