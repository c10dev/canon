"""프롬프트 크기 관리: 블록 재기, 장편 블록 예산, 관련 자료 고르기, 옛 본문 단락 찾기. LLM 을 부르지 않는다.

장편은 화가 쌓일수록 사실 · 상태 · 비밀 · 줄거리가 늘어난다. 입력이 길어지면 필요한 정보를 다 넣어도 품질이 떨어지고,
같은 인물에 대한 비슷한 문장이 서로 방해물이 된다 (장편 입력 토큰 진단, 2026-10). 그래서 장편 프롬프트는
블록마다 글자 예산(BUDGET)을 두고, 넘치면 이번 화와 덜 관련된 것부터 뺀 뒤 몇 개를 뺐는지 적는다.
저장된 데이터는 그대로 두고 프롬프트에 넣는 보기만 고른다. 단편(form="short") 경로는 쓰지 않는다.
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from typing import Iterable

from . import elements, metrics
from .schema import Character, Foreshadow, Project, Secret

CHARS_PER_TOKEN = 1.7  # 토크나이저가 없을 때 한국어 추정값 (gemma 실측 1.6~1.9)

# 장편 블록 예산 (글자). 넘치면 우선순위가 낮은 것부터 뺀다.
BUDGET = {
    "facts": 3_500,         # 본문 쓰기 · 부분 수정의 확정 사실
    "story_past": 6_000,    # 끝난 부와 아크의 접은 줄거리
    "story_arc": 6_000,     # 이번 아크의 화별 요약
    "check_facts": 6_000,   # 검수의 확정 사실
    "check_recall": 8_000,  # 검수: 옛 화에서 찾아 넣는 단락. 2026-11-03 시험(옛 화 근거 모순 40개)에서 2.4만 자와 찾은 수가 같거나 1개 적었다
    "impact_facts": 8_000,  # 인과율 영향 분석의 확정 사실
    "impact_text": 90_000,  # 인과율 영향 분석: 이미 쓴 본문
    "secrets": 2_500,       # 본문 쓰기의 관계 블록에 붙는 숨긴 비밀
    "state_secrets": 6_000,  # 상태 변경안 · 검수의 비밀 목록
    "state_facts": 4_000,   # 장편 상태 변경안: 이미 있는 확정 사실 (prompts.state_facts_block, 검수 자료를 앞에 두는 요청에는 넣지 않음)
    "places": 3_000,        # 기획 · 검수 · 상태 변경안에 넣는 본문 · 플롯에서 나온 장소
    "plan_fixed": 8_000,    # 화별 플롯 초안: 범위 안 · 바로 뒤의 이미 정해진 화 플롯 (prompts.fixed_plots, 장편만)
    "blueprint": 2_000,     # 장편 기획(다음 아크 · 화별 플롯 초안)의 설계도 줄: 범위에 걸린 이정표 · 사다리 칸과 그 뒤 첫 것 (prompts.blueprint_plan_block)
    "ability_plan": 1_000,  # 장편 기획의 설계도 능력 일정 줄: 범위를 지난 것 · 범위에 걸린 것 · 인물마다 그 뒤 첫 것 (prompts.blueprint_ability_block)
    "plan_stages": 1_500,   # 화별 플롯 초안: 기획 인물끼리 지금 관계 단계 한 줄씩 (prompts.plan_stage_block, 장편만). 주역끼리 먼저
    "storylines": 3_000,    # 장편 기획의 이야기 줄기 블록 (storylines.plan_block). 넘치면 합류가 끝난 줄기부터 뺀다
    "deadlines": 1_200,     # 쓰기 · 검수 · 기획 · 상태 변경안의 작품 속 열린 기한 (timeline.deadline_lines, 단편도)
    "plan_facts": 6_000,    # 다음 아크 기획: 부 목표 · 아크 아이디어 · 직전 아크 플롯과 관련된 확정 사실 (최근 FACTS_RECENT 개는 늘)
    "plan_states": 6_000,   # 다음 아크 기획: 주역 밖 기획 인물(planning_cast)의 지금 상태, 최근에 나온 인물부터
    "plot_facts": 4_000,    # 장편 화별 플롯 초안 · 플롯 대화: 아크 · 앞뒤 화 플롯과 관련된 확정 사실 (최근 FACTS_RECENT 개는 늘, prompts.plot_facts_states)
    "plot_states": 4_000,   # 장편 화별 플롯 초안 · 플롯 대화: 주역 밖 인물의 지금 상태, 최근에 나온 인물부터 (prompts.plot_facts_states)
    "cast": 8_000,          # 본문 쓰기: '항상' 넣는 조연 · 단역과 이번 화 조연 · 단역의 설정. '항상' 조연 · 단역이 있을 때만 센다 (fit_cast)
    "travel": 800,          # 쓰기 · 검수의 이동 거리 (mapprompt.travel_block, 지도 크기를 알 때만)
    "spots": 600,           # 쓰기 · 검수: 플롯에 나온 장소가 놓인 건물 한 줄 (mapprompt.spot_block, MapPin.spot)
    "stage": 1_500,         # 쓰기: 작가가 연출을 짠 사건의 박자 요약 (prompts.stage_block, 넘으면 뒤 사건의 장면부터 뺀다)
    "address": 1_500,       # 쓰기 · 검수 · 상태 변경안: 이번 화 인물끼리의 호칭 · 말씨 줄 (address.block)
    "stat_lines": 2_000,    # 쓰기: 상태창 줄 형식(stat_window.prompt = lines)의 도감 줄. 이번 화 인물의 수치 줄은 늘 넣는다
    "relations": 3_500,     # 장편 쓰기: 관계 줄. 이번 화 플롯 인물끼리의 줄 먼저 (prompts.serial_relations)
    "pairs": 600,           # 장편 쓰기: 이번 화 플롯 인물끼리 두 사람 사이에 있었던 일, 쌍마다 한 줄 라벨 (pairlog.write_block)
    "check_pairs": 3_000,   # 장편 검수: 쌍마다 사건 갈래별 처음 일어난 화와 근거 문장 (pairlog.check_block)
    "states": 7_000,        # 장편 쓰기: 인물 현재 상태. 넘으면 플롯 밖 인물의 아는 정보를 줄이고, 그래도 넘으면 그 인물 상태를 뺀다 (prompts.fit_states)
    # 플레이 모드 (prompts.play_scene_prompt · play_state_prompt). 한 턴은 짧은 장면이라 소설보다 작게 둔다
    "play_style": 1_800,    # 장면: 줄인 스타일 프로필 (PLAY_STYLE_KEYS + 예시 문단 하나)
    "play_story_past": 2_500,  # 장면: 끝난 장 · 아크 · 부의 접은 줄거리 (story_parts 의 앞쪽을 다시 접는다)
    "play_story_arc": 2_000,   # 장면: 이번 장의 턴별 요약
    "play_cast": 4_000,     # 장면: 플레이어 밖 장면 인물의 설정 + 지금 상태
    "play_facts": 1_800,    # 장면: 확정 사실 (play_facts)
    "play_elements": 1_000,  # 장면: 이야기 요소
    "play_relations": 1_200,  # 장면: 장면 인물 사이 관계 줄 (플레이어 줄 먼저)
    "play_secrets": 800,    # 장면: 장면 인물이 얽힌 숨긴 비밀 (pick_secrets 의 셈)
    "play_foreshadows": 900,  # 장면: 열린 복선 한 줄씩
    "play_state_secrets": 2_000,  # 상태 변경안: 장면 인물이 얽힌 비밀 (pick_secrets 의 셈, 넣는 글은 이보다 길다)
    "play_state_facts": 1_800,  # 상태 변경안: 이미 있는 확정 사실 (state_facts 의 플레이 크기)
    # 역설계 실험 (revlab). 화 수를 막지 않아서 화 수만큼 커지는 블록을 접는다. 30화 안팎 실험은 예산에 닿지 않는다
    "rev_story": 12_000,    # 되돌려 쓰기 사본의 앞 화 요약 (revlab.fold_story: 오래된 화부터 첫 문장 → 뺌). 장편 story_past + story_arc 와 같은 크기
    "rev_facts": 10_000,    # 되돌려 쓰기 사본의 사실 (revlab.fit_facts: 최근 화 사실부터)
    "rev_lines": 40_000,    # 이야기 줄기 요청의 화별 역설계 결과 (prompts.rev_lines_prompt: 넘으면 모든 화를 첫 문장 → 줄기 이름만)
    "rev_arcs": 40_000,     # 아크 역설계 요청의 화별 역설계 결과 (prompts.rev_arcs_prompt: 넘으면 모든 화를 첫 문장 → 제목 · 훅만)
}
PLAY_FORESHADOW_CAP = 8  # 장면에 넣는 열린 복선 수
PLAY_STATE_FORESHADOW_CAP = 10  # 상태 변경안에 넣는 열린 복선 수
PLAY_KNOWS = (10, 4)  # 장면: 플레이어 인물의 아는 정보 (넣는 수, 그중 늘 넣는 최근 수)
PLAY_KNOWS_OTHER = (5, 2)  # 장면: 다른 장면 인물의 아는 정보
FACTS_RECENT = 30  # 최근 사실은 예산과 상관없이 넣는다
CHECK_RECENT = 3  # 검수에 원문 그대로 넣는 직전 화 수
FORESHADOW_CAP = 25  # 본문 쓰기에 넣는 열린 복선 수
PLAN_FORESHADOW_CAP = 60  # 다음 아크 기획에 넣는 열린 복선 수


# 쓰기 가족 요청(prompts.episode_parts 와 그 위 요청)이 쓰는 예산 키. 작품 설정(Settings.budgets)으로 바꿀 수 있는 것은 이 키뿐이다
WRITE_KEYS = ("facts", "story_past", "story_arc", "secrets", "deadlines", "cast", "travel", "spots", "stage", "address",
              "stat_lines", "relations", "pairs", "states")


def budget(p: Project, key: str) -> int:
    """작품의 쓰기 예산. 장편이고 key 가 WRITE_KEYS 에 있고 작품 설정(Settings.budgets)에 budget_ok 를 지나는 값이 있으면 그 값, 아니면 BUDGET[key].
    단편은 저장한 값과 상관없이 늘 BUDGET 기본값이다 (spec 03 정할 것 3)."""
    if p.serial and key in WRITE_KEYS:
        for b in p.settings.budgets:
            if b.key == key and budget_ok(key, b.value):  # 범위 밖 값(손으로 고친 project.json 등)은 무시한다
                return b.value
    return BUDGET[key]


def budget_range(key: str) -> tuple[int, int]:
    """작품 예산으로 받는 값의 범위 (가장 작은 값, 가장 큰 값). 기본값의 1/4 ~ 4배를 100 단위로 내린 값, 가장 작은 값은 100 이상."""
    base = BUDGET[key]
    return max(100, base // 4 // 100 * 100), base * 4 // 100 * 100


def budget_ok(key: str, value: int) -> bool:
    """작품 예산으로 받을 수 있는 값인지: WRITE_KEYS 의 키, 100 단위, budget_range 안. 0 은 받지 않는다 (빼려면 블록을 끈다)."""
    if key not in WRITE_KEYS or value <= 0 or value % 100:
        return False
    lo, hi = budget_range(key)
    return lo <= value <= hi


# ---------- 넣은 이유 · 뺀 이유 (prompts 보기의 trace) ----------
# 화면이 보이는 이유 이름은 여기 한 곳에 둔다. 컨텍스트 활성화(docs/context 02)도 같은 이름을 쓴다.
REASON_ALWAYS = "늘 넣기"
REASON_PLOT = "이번 화 플롯 등장"
REASON_NAMED = "이름 발견"
REASON_SCORE = "관련 점수"
REASON_RECENT = "최근"
REASON_ARC = "아크 회수 · 기한"
REASON_SCOPE = "작품 · 부 단위"
REASON_ALL = "전부 넣음(수가 적음)"
REASON_NAME_IN = "이번 화 인물 이름"
REASON_SECRET = "고른 비밀"
REASON_RETURN = "오랜만의 재등장"
REASON_FIT = "예산 안에 듦"
DROP_BUDGET = "예산 넘음"
DROP_ARC = "아크와 무관"
DROP_CAP = "개수 상한"
DROP_UNRELATED = "이번 화와 무관"


class Trace:
    """요청을 조립하며 블록마다 넣은 항목과 뺀 항목을 (이름, 이유)로 적는다. 조립 함수의 trace 인자가 None 이면 적지 않는다."""

    def __init__(self):
        self.items: dict[str, list[tuple[str, str]]] = {}
        self.dropped: dict[str, list[tuple[str, str]]] = {}

    def item(self, block_id: str, name: str, reason: str) -> None:
        self.items.setdefault(block_id, []).append((name, reason))

    def drop(self, block_id: str, name: str, reason: str) -> None:
        self.dropped.setdefault(block_id, []).append((name, reason))

    def forget(self, block_id: str) -> None:
        """꺼진 블록의 항목을 지운다 (보기가 꺼진 블록의 항목을 보이지 않게)."""
        self.items.pop(block_id, None)
        self.dropped.pop(block_id, None)


TRACE_LABEL = 40  # 뺀 줄을 보기에 적을 때 이름 길이


def trace_label(line: str, limit: int = TRACE_LABEL) -> str:
    """뺀 줄의 짧은 이름: 앞 '- ' 와 공백을 떼고 limit 자를 넘으면 자르고 '…'."""
    text = line.strip().removeprefix("- ").strip().split("\n")[0]
    return text if len(text) <= limit else text[:limit - 1] + "…"


def trace_drops(trace: Trace | None, block_id: str, lines: Iterable[str], reason: str = "") -> None:
    """예산으로 뺀 줄들을 짧은 이름(trace_label)으로 trace 에 적는다. trace 가 None 이면 아무것도 하지 않는다."""
    if trace is None:
        return
    for line in lines:
        trace.drop(block_id, trace_label(line), reason or DROP_BUDGET)


def est_tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


# ---------- 블록 재기 ----------

_HEAD = re.compile(r"^(#{1,3} [^\n]{1,60}|\[[^\]\n]{1,40}\][^\n]{0,40})$", re.M)
_HEAD_TAIL = re.compile(r"[\s(:]*$")


def _label(head: str) -> str:
    """머리글을 기록용 이름으로: 기호와 괄호 설명을 뗀다."""
    h = head.strip().lstrip("#").strip()
    if h.startswith("["):
        h = h[1:h.index("]")] if "]" in h else h[1:]
    h = re.sub(r"\s*\(.*$", "", h)
    h = re.sub(r"\d+화", "N화", h)
    return _HEAD_TAIL.sub("", h)[:24] or "(머리)"


def blocks(text: str, top: int = 12) -> list[list]:
    """프롬프트를 머리글('# ...', '[...]')로 나눠 블록별 글자 수. 큰 것부터 top 개, 나머지는 '그 밖' 하나로."""
    sizes: Counter = Counter()
    last, name = 0, "(머리)"
    for m in _HEAD.finditer(text):
        sizes[name] += m.start() - last
        name, last = _label(m.group(1)), m.start()
    sizes[name] += len(text) - last
    rows = [[k, v] for k, v in sizes.most_common() if v > 0]
    if len(rows) > top:
        rest = sum(v for _, v in rows[top - 1:])
        rows = rows[:top - 1] + [["그 밖", rest]]
    return rows


# ---------- 글 조각 ----------

_HANGUL = re.compile(r"[가-힣]+")


def grams(text: str) -> set[str]:
    """띄어쓰기를 무시한 한글 3글자 조각. 조사와 띄어쓰기가 달라도 같은 말을 찾는다."""
    s = "".join(_HANGUL.findall(text))
    return {s[i:i + 3] for i in range(len(s) - 2)}


def first_sentence(text: str, limit: int = 90) -> str:
    t = " ".join(text.split())
    m = re.search(r"(.+?[.!?。])(\s|$)", t)
    s = m.group(1) if m else t
    return s if len(s) <= limit else s[:limit - 1] + "…"


# ---------- 확정 사실 ----------

def names_of(p: Project, ids: Iterable[str]) -> tuple[list[str], list[str]]:
    """(주역 이름, 그 밖 인물 이름). 한글 세 글자 이름은 성을 뗀 이름도 넣는다 ('최건우' → '건우', metrics.name_forms).
    사실 · 아는 정보는 흔히 성을 떼고 적어서, 온 이름만 찾으면 관련된 옛 사실을 놓친다."""
    ids = set(ids)
    main = [x for c in p.characters if c.id in ids and c.tier == "main" for x in metrics.name_forms(c.name)]
    other = [x for c in p.characters if c.id in ids and c.tier != "main" for x in metrics.name_forms(c.name)]
    return main, other


def query_terms(p: Project, n: int) -> list[str]:
    """n화와 관련된 고유한 말: 이번 화에 걸린 이야기 요소의 이름과 별칭, 플롯에 나온 장소."""
    try:
        e = p.episode(n)
    except KeyError:
        return []
    plot = elements.plot_text(e)
    out = [t for el in elements.for_episode(p, n) for t in elements.terms(el)]
    out += [loc for loc in p.world.locations if loc and loc in plot + e.text]
    return list(dict.fromkeys(out))


def pick_places(p: Project, text: str, budget: int) -> tuple[list[str], int]:
    """이미 있는 장소 이름을 예산(글자)만큼. text 에 나오는 이름 먼저, 그다음 설정 장소 칸, 최근에 처음 나온 곳. (이름들, 뺀 수)"""
    from . import naming

    names = naming.known_places(p)
    found = {t: el.found_ep for el in p.elements if el.kind == "장소" for t in [el.name, *el.aliases]}
    ranked = sorted(names, key=lambda x: (x not in text, found.get(x, 0) > 0, -found.get(x, 0)))
    out, used = [], 0
    for x in ranked:
        if used + len(x) + 2 <= budget:
            out.append(x)
            used += len(x) + 2
    return out, len(names) - len(out)


def trace_unrelated(trace: Trace | None, block_id: str, count: int) -> None:
    """이번 화와 무관해 넣지 않은 옛 사실을 하나하나 적지 않고 '옛 사실 N개' 한 줄로 적는다."""
    if trace is not None and count > 0:
        trace.drop(block_id, f"옛 사실 {count}개", DROP_UNRELATED)


def pick_facts(p: Project, ids: set[str], query: str, budget: int, terms: Iterable[str] = (),
               trace: Trace | None = None) -> tuple[list[str], int]:
    """확정 사실을 이번 화와 관련된 순서로 예산만큼. 최근 FACTS_RECENT 개는 늘 넣는다.
    관련: 조연 · 단역 이름(3) > 이야기 요소 · 장소(2) > 주역 이름(1), 같으면 query 와 겹치는 글 조각이 많은 것, 그다음 최근 것.
    아무것도 겹치지 않는 옛 사실은 넣지 않는다. 고른 사실은 원래 순서로 돌려준다."""
    facts = p.facts
    main, other = names_of(p, ids)
    terms = [t for t in terms if t]
    q = grams(query)
    recent = set(range(max(0, len(facts) - FACTS_RECENT), len(facts)))
    scored = []
    for i, f in enumerate(facts):
        if i in recent:
            continue
        s = 3 * any(nm in f for nm in other) + 2 * any(t in f for t in terms) + any(nm in f for nm in main)
        if not s:
            continue
        g = grams(f)
        overlap = len(g & q) / (len(g) or 1)
        scored.append((s, overlap, i))
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    keep = set(recent)
    used = sum(len(facts[i]) + 3 for i in recent)
    for _, _, i in scored:
        cost = len(facts[i]) + 3
        if used + cost > budget:
            continue
        keep.add(i)
        used += cost
    if trace is not None:  # 예산으로 뺀 사실은 이름으로, 아무것도 겹치지 않는 옛 사실은 개수 한 줄로
        scored_ids = {i for _, _, i in scored}
        for i, f in enumerate(facts):
            if i in keep:
                trace.item("facts", f, REASON_RECENT if i in recent else REASON_SCORE)
            elif i in scored_ids:
                trace.drop("facts", f, DROP_BUDGET)
        trace_unrelated(trace, "facts", len(facts) - len(recent) - len(scored))
    return [facts[i] for i in sorted(keep)], len(facts) - len(keep)


def facts_learned(p: Project) -> dict[str, int]:
    """{확정 사실: 들어온 화}. 반영 기록(history)의 new_facts 로 센다. 고친 화 다시 맞추기(apply_restate)와 빼 둔 사실 넣기도
    그 화 기록의 new_facts 에 더하므로 함께 잡힌다. 기록에 없는 사실(설정 단계, 작가가 직접 적은 것, 인과율 apply_impact)은 빠진다. 저장하지 않는다."""
    out: dict[str, int] = {}
    for d in sorted(p.history, key=lambda d: d.episode):
        for f in d.new_facts:
            out.setdefault(f, d.episode)
    return out


FACT_TAG = re.compile(r"^\s*\(\d+화\)\s*")  # prompts.fact_rows 가 장편 사실 줄 앞에 붙이는 표시


FACT_NEAR = 0.5  # 새 사실의 글 조각 가운데 이만큼이 한 옛 사실과 겹치면 비슷한 사실로 본다 (실제 장편 4편 1,192개에서 잼, DESIGN.md)
FACT_NEAR_MIN = 3  # 글 조각이 이보다 적은 짧은 사실은 견주지 않는다


def near_fact(fact: str, facts: Iterable[str]) -> str:
    """fact 와 가장 많이 겹치는 옛 사실. 겹침(새 사실의 글 조각 가운데 옛 사실과 같은 몫)이 FACT_NEAR 아래면 빈 글.
    같은 글은 반영이 이미 거르므로 여기서는 보지 않는다."""
    g = grams(fact)
    if len(g) < FACT_NEAR_MIN:
        return ""
    best, like = 0.0, ""
    for f in facts:
        if f == fact:
            continue
        r = len(g & grams(f)) / len(g)
        if r > best:
            best, like = r, f
    return like if best >= FACT_NEAR else ""


# ---------- 인물이 아는 정보 ----------

KNOWS_KEEP = 20  # 장편: 인물 하나에 넣는 아는 정보 수
KNOWS_RECENT = 8  # 그중 최근 것은 관련과 상관없이 늘 넣는다
KNOWS_OVERLAP = 0.2  # 이름 · 요소가 없을 때 이번 화 글과 겹친다고 볼 글 조각 비율


def pick_knows(knows: list[str], query: str, names: Iterable[str], terms: Iterable[str] = (),
               limit: int = KNOWS_KEEP, recent: int = KNOWS_RECENT, *, trace: Trace | None = None, who: str = "") -> tuple[list[str], int]:
    """인물이 아는 정보를 이번 화와 관련된 것부터 limit(KNOWS_KEEP) 개. 최근 recent(KNOWS_RECENT) 개는 늘 넣는다.
    관련: 이야기 요소 · 장소(2) > 이번 화 인물 이름(1), 같으면 query 와 겹치는 글 조각이 많은 것, 그다음 최근 것.
    관련된 것으로 다 차지 않으면 남은 자리는 최근 것으로 채운다. 고른 것은 원래 순서로. (고른 것, 뺀 수)
    플레이 장면은 limit · recent 를 줄여 부른다 (PLAY_KNOWS)."""
    if len(knows) <= limit:
        return list(knows), 0
    names = [x for x in names if x]
    terms = [t for t in terms if t]
    q = grams(query)
    keep = set(range(len(knows) - recent, len(knows)))
    scored = []
    for i, k in enumerate(knows):
        if i in keep:
            continue
        g = grams(k)
        overlap = len(g & q) / (len(g) or 1)
        s = 2 * any(t in k for t in terms) + any(nm in k for nm in names)
        if s or overlap >= KNOWS_OVERLAP:
            scored.append((s, overlap, i))
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    for _, _, i in scored[:limit - len(keep)]:
        keep.add(i)
    for i in range(len(knows) - 1, -1, -1):  # 남은 자리는 최근 것
        if len(keep) >= limit:
            break
        keep.add(i)
    if trace is not None:  # 상태 블록의 아는 정보: 이름은 '인물: 정보'
        for i, k in enumerate(knows):
            if i not in keep:
                trace.drop("states", f"{who}: {k}" if who else k, DROP_CAP)
    return [knows[i] for i in sorted(keep)], len(knows) - len(keep)


# ---------- 복선 ----------

def foreshadow_rank(p: Project, f: Foreshadow, n: int) -> int:
    """작을수록 먼저. 회수 예정이 지남 > 이번 아크에서 회수 > 이번 아크 안에 회수 예정 > 작품 단위 > 부 단위 > 이번 아크에 심음 > 그 밖 최근."""
    arc = p.arc_for(n)
    end = arc.end_ep if arc else n
    if f.due_ep is not None and f.due_ep <= n:
        return 0
    if arc is not None and f.id in arc.payoffs:
        return 1
    if f.due_ep is not None and f.due_ep <= end:
        return 2
    if f.scope == "series":
        return 3
    if f.scope == "part":
        return 4
    if arc is not None and f.planted_ep >= arc.start_ep:
        return 5
    return 6


# foreshadow_rank 순위 → 보기에 적는 넣은 이유. 0 회수 예정 지남 · 1 이번 아크 회수 · 2 아크 안 회수 예정은 '아크 회수 · 기한',
# 3 작품 단위 · 4 부 단위는 '작품 · 부 단위', 5 이번 아크에 심음 · 6 그 밖 최근은 '최근'
FORESHADOW_REASONS = {0: REASON_ARC, 1: REASON_ARC, 2: REASON_ARC, 3: REASON_SCOPE, 4: REASON_SCOPE, 5: REASON_RECENT, 6: REASON_RECENT}


def foreshadow_reason(p: Project, f: Foreshadow, n: int) -> str:
    """복선을 넣은 이유 (FORESHADOW_REASONS)."""
    return FORESHADOW_REASONS[foreshadow_rank(p, f, n)]


def rank_foreshadows(p: Project, fs: list[Foreshadow], n: int, cap: int) -> list[Foreshadow]:
    """순위대로 cap 개를 고르고 심은 순서로 돌려준다. 같은 순위면 작품 · 부 단위는 오래된 것, 나머지는 최근 것이 먼저.
    예전처럼 뒤에서 자르면 끝까지 갈 오래된 큰 떡밥이 먼저 빠진다."""
    def key(f: Foreshadow) -> tuple:
        r = foreshadow_rank(p, f, n)
        return (r, f.planted_ep if r in (3, 4) else -f.planted_ep)
    picked = sorted(fs, key=key)[:cap]
    return sorted(picked, key=lambda f: f.planted_ep)


# ---------- 비밀, 관계 볼 인물 ----------

def open_secrets(p: Project, ids: set[str] | None = None) -> list[Secret]:
    """아직 누군가 모르는 비밀. ids 를 주면 그 인물이 갖고 있거나 그 인물이 모르는 것만."""
    return [s for s in p.secrets if s.hidden_from
            and (ids is None or s.owner in ids or set(s.hidden_from) & ids)]


def pick_secrets(p: Project, ids: set[str], query: str, budget: int) -> tuple[list[Secret], int]:
    """open_secrets(ids) 중 이번 화와 관련된 순서로 예산만큼. (고른 것, 뺀 수)
    관련: query 와 겹치는 글 조각 비율, 조연 · 단역이 얽힘, 무게, 같으면 나중에 생긴 것. 고른 것은 원래 순서로.
    보기 기록은 trace_secrets 가 한다 (요청에 실제로 찍히는 비밀은 인물을 다 고른 뒤에야 안다)."""
    cand = open_secrets(p, ids)
    main = {c.id for c in p.characters if c.tier == "main"}
    q = grams(query)

    def score(i: int, s: Secret) -> tuple:
        g = grams(s.content)
        overlap = len(g & q) / (len(g) or 1)
        side = bool(({s.owner} | set(s.hidden_from)) & ids - main)
        return (-(3 * overlap + side + s.weight), -i)

    order = sorted(range(len(cand)), key=lambda i: score(i, cand[i]))
    keep, used = set(), 0
    for i in order:
        cost = len(cand[i].content) + 60
        if used + cost > budget:
            continue
        keep.add(i)
        used += cost
    return [cand[i] for i in sorted(keep)], len(cand) - len(keep)


def trace_secrets(trace: Trace | None, cand: list[Secret], picked: list[Secret], ids: set[str]) -> None:
    """관계 블록의 숨긴 비밀을 trace 에 적는다. ids 는 인물을 다 고른(상태 예산으로 뺀 뒤) 이번 화 인물이다.
    dynamics.describe_relations 와 같은 규칙(주인이 ids 에 있고 모르는 인물 하나 이상이 ids 에 있음)으로 요청에 찍히는 비밀만 적는다:
    고른 것은 넣은 항목('고른 비밀'), 예산으로 고르지 못한 것은 뺀 항목. pick_secrets 의 후보(cand)와 고른 것(picked)을 받는다."""
    if trace is None:
        return
    chosen = {id(s) for s in picked}
    for sec in cand:
        if sec.owner not in ids or not set(sec.hidden_from) & ids:
            continue
        if id(sec) in chosen:
            trace.item("relations", sec.content, REASON_SECRET)
        else:
            trace.drop("relations", sec.content, DROP_BUDGET)


# ---------- 인물 넣기 방식 (Character.context) ----------
# auto 는 비중대로 (주역은 매 화, 조연 · 단역은 나오는 화에만), always 는 비중과 상관없이 주역처럼 매 화,
# off 는 비중과 상관없이 설정 · 상태 · 관계를 빼고 이름만 (등장 인물 줄, 다시 만들지 않게 하는 한 줄 목록).
# 모두 auto 면 아래 함수는 예전 규칙(tier == "main")과 같은 결과를 내서 프롬프트가 한 글자도 바뀌지 않는다.

def core_ids(p: Project) -> set[str]:
    """매 화 설정을 넣는 인물: 주역과 '항상' 인물. '넣지 않음' 주역은 뺀다."""
    return {c.id for c in p.characters if c.context == "always" or (c.tier == "main" and c.context != "off")}


def off_ids(p: Project) -> set[str]:
    """'넣지 않음' 인물."""
    return {c.id for c in p.characters if c.context == "off"}


def without_off(p: Project, ids: set[str] | None) -> set[str] | None:
    """ids 에서 '넣지 않음' 인물을 뺀다. None 은 '모두'라서 '넣지 않음' 인물이 없으면 그대로 None,
    있으면 인물 · 관계 · Tie 에 나오는 id 전부에서 뺀 것 (설정에 없는 id 의 관계도 예전처럼 남긴다)."""
    off = off_ids(p)
    if not off:
        return ids
    if ids is None:
        ids = {c.id for c in p.characters} | {x for t in p.ties for x in (t.source, t.target)} \
            | {x for r in p.relationships for x in (r.a, r.b)}
    return set(ids) - off


def fit_cast(extra: list[Character], used: int, size, budget: int, trace: Trace | None = None) -> tuple[list[Character], int]:
    """'항상' 넣는 조연 · 단역 설정(used 글자)과 이번 화 조연 · 단역(extra) 설정을 합쳐 예산(글자) 안에 맞춘다.
    넘치면 단역 먼저, 같은 비중이면 뒤에 있는 인물부터 뺀다. size(인물) 는 그 인물 설정의 글자 수. (넣을 인물, 뺀 수)
    '항상' 조연 · 단역이 없으면(used 0) 예전처럼 다 넣는다."""
    if not used:
        keep = set(range(len(extra)))
    else:
        order = sorted(range(len(extra)), key=lambda i: (extra[i].tier == "minor", i))
        keep, total = set(), used
        for i in order:
            cost = size(extra[i])
            if total + cost > budget:
                continue
            keep.add(i)
            total += cost
    _trace_people(trace, "cast", extra, keep, None)  # 넣은 인물은 조립(prompts.context_parts)이 플롯 등장으로 적는다
    if not used:
        return extra, 0
    return [c for i, c in enumerate(extra) if i in keep], len(extra) - len(keep)


def _trace_people(trace: Trace | None, block_id: str, people: list[Character], keep: set[int], reason: str | None) -> None:
    """넣은 인물(reason 이 있을 때만)과 예산으로 뺀 인물을 trace 에 적는다."""
    if trace is None:
        return
    for i, c in enumerate(people):
        if i in keep:
            if reason:
                trace.item(block_id, c.name or c.id, reason)
        else:
            trace.drop(block_id, c.name or c.id, DROP_BUDGET)


PLAN_RECENT = 20  # 기획 프롬프트: 최근 몇 화 플롯에 나온 인물까지 관계를 본다


def planning_cast(p: Project, n: int) -> set[str]:
    """기획 프롬프트에서 관계를 볼 인물: 주역('항상' 인물 포함), 직전 아크와 지금 아크의 주요 인물, 최근 PLAN_RECENT 화와 이후 플롯에 나온 인물.
    '넣지 않음' 인물은 뺀다. 조연을 다 넣으면 300화쯤에 관계 블록만 2만 자가 넘는다."""
    ids = core_ids(p)
    arcs = sorted((a for a in p.story_arcs if a.start_ep < n + 30), key=lambda a: a.start_ep)[-2:]
    for a in arcs:
        ids |= set(a.cast)
    for e in p.episodes:
        if e.plot.number >= n - PLAN_RECENT:
            ids |= set(e.plot.characters)
    return ids - off_ids(p)


def episode_cast(p: Project, n: int, text: str = "") -> set[str]:
    """이번 화 등장 인물과 주역('항상' 인물 포함). text 를 주면 거기에 이름이 나오는 인물도 (named_ids). '넣지 않음' 인물은 뺀다."""
    try:
        cast = set(p.episode(n).plot.characters)
    except KeyError:
        cast = set()
    return (cast | core_ids(p) | (named_ids(p, text) if text else set())) - off_ids(p)


# ---------- 이름으로 켜는 인물 ----------
# 플롯 인물 목록(EpisodePlot.characters)에 없는 조연이 본문에 나오면 그 화의 쓰기 · 검수 · 상태 변경안에 설정 · 말투 · 상태가 없었다
# (실제 장편 83화에서 92번, 2026-10-30 인물 진단). 장편은 플롯 글 · 직전 화 끝 · 본문에 이름이 나온 인물도 넣는다.

NAMED_TAIL = 1_500  # 쓰기: 직전 화 끝에서 이름을 찾는 글자 수 (prev_block 의 끝부분과 같은 길이)
RETURN_GAP = 10  # 쓰기: 이만큼 화를 건너뛰고 다시 나오는 인물은 마지막으로 나온 화를 적는다 (return_lines)


# 한 글자 이름 뒤에 붙어도 이름으로 보는 말 (static/mentions.js 의 MN_TITLES · MN_JOSA · MN_FOCUS 와 같은 목록).
# 그 뒤는 글자가 아니어야 한다. 여기 없는 글자가 이어지면('진짜', '진심') 다른 낱말로 본다
_TITLES = ["씨", "님", "이"]
_JOSA = ["이", "가", "은", "는", "을", "를", "의", "에", "에게", "에게서", "한테", "한테서", "께", "께서", "와", "과", "랑", "이랑", "하고",
         "도", "만", "까지", "부터", "보다", "처럼", "같이", "로", "으로", "로서", "으로서", "로써", "으로써", "에서", "아", "야", "여", "이여",
         "나", "이나", "며", "이며", "든", "이든", "란", "이란", "라", "이라", "라고", "이라고", "라는", "이라는", "라면", "이라면", "야말로", "이야말로",
         "마저", "조차", "밖에", "뿐", "쯤", "다", "이다", "였다", "이었다", "예요", "이에요", "였던", "이었던", "던", "이던", "지만", "이지만", "고", "이고",
         "요", "이요", "야", "이야", "에겐", "한텐", "들", "네"]
_FOCUS = ["은", "는", "도", "만", "요", "가", "를", "을", "의", "에", "들", "이"]


def _alt(words: list[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))


SHORT_TAIL = rf"(?:{_alt(_TITLES)})?(?:{_alt(_JOSA)})?(?:{_alt(_FOCUS)})?(?![가-힣A-Za-z0-9])"


def name_pattern(c: Character) -> re.Pattern | None:
    """인물 이름을 찾는 정규식. 세 글자 한국 이름은 성을 뗀 이름도, 띄어 쓴 이름은 첫 낱말도 (2글자 이상, '마르타 부인' → '마르타').
    이름 바로 앞이 한글 · 영문이면 다른 낱말의 일부로 본다 ('김민정' 속 '민정'). 두 글자 이상은 조사가 뒤에 붙으므로 뒤는 보지 않는다.
    한 글자 이름('진')은 다른 낱말 머리에 들기 쉬워('진짜') 뒤에 호칭 · 조사만 오고 낱말이 끝나야 한다(SHORT_TAIL).
    다른 이름(Character.aliases)은 두 글자 이상만, 작가가 적은 꼴 그대로 더한다 (성 · 첫 낱말을 떼지 않는다)."""
    forms = metrics.name_forms(c.name)
    words = c.name.split()
    if len(words) > 1 and len(words[0]) >= 2:
        forms.append(words[0])
    forms += [a.strip() for a in c.aliases if len(a.strip()) >= 2]
    forms = sorted({f for f in forms if f}, key=len, reverse=True)
    if not forms:
        return None
    alts = [re.escape(f) + (f"(?={SHORT_TAIL})" if len(f) == 1 else "") for f in forms]
    return re.compile(r"(?<![가-힣A-Za-z])(?:" + "|".join(alts) + ")")


def named_ids(p: Project, text: str) -> set[str]:
    """text 에 이름이 나오는 인물 id. 이름은 name_pattern 규칙으로 찾는다."""
    if not text:
        return set()
    out = set()
    for c in p.characters:
        pat = name_pattern(c)
        if pat and pat.search(text):
            out.add(c.id)
    return out


def fit_named(named: list[Character], used: int, size, budget: int, trace: Trace | None = None) -> tuple[list[Character], int]:
    """이름으로 켠 인물(플롯 인물 목록 밖) 설정을 남은 예산에 넣는다. used 는 이미 넣은 조연 · 단역 설정 글자.
    조연 먼저, 같은 비중이면 앞 인물부터. (넣을 인물, 뺀 수)"""
    order = sorted(range(len(named)), key=lambda i: (named[i].tier == "minor", i))
    keep, total = set(), used
    for i in order:
        cost = size(named[i])
        if total + cost > budget:
            continue
        keep.add(i)
        total += cost
    _trace_people(trace, "named", named, keep, REASON_NAMED)
    return [c for i, c in enumerate(named) if i in keep], len(named) - len(keep)


def last_seen(p: Project, ids: Iterable[str], n: int) -> dict[str, int]:
    """n화 앞 본문이 있는 화 가운데 인물이 마지막으로 나온 화 (플롯 인물이거나 본문에 이름이 나옴). 나온 적 없는 인물은 빠진다."""
    want = {c.id: name_pattern(c) for c in p.characters if c.id in set(ids)}
    out: dict[str, int] = {}
    for e in sorted((e for e in p.episodes if e.text and e.plot.number < n), key=lambda e: -e.plot.number):
        for cid, pat in list(want.items()):
            if cid in e.plot.characters or (pat and pat.search(e.text)):
                out[cid] = e.plot.number
                del want[cid]
        if not want:
            break
    return out


# ---------- 옛 본문 단락 찾기 ----------

PARA_MAX = 700  # 단락 하나의 최대 글자. 넘으면 문장 경계에서 나눈다
COMMON = 0.3  # 이보다 많은 단락에 나오는 조각은 흔한 말로 보고 셈에서 뺀다


def _paragraphs(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        while len(para) > PARA_MAX:
            cut = max(para.rfind(".", 0, PARA_MAX), para.rfind("\n", 0, PARA_MAX))
            cut = cut + 1 if cut > PARA_MAX // 3 else PARA_MAX
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


class PassageIndex:
    """n화 앞 본문(skip 화 제외)의 단락과 글 조각 빈도. 질문 여러 개를 같은 색인으로 찾을 때(두 걸음 검수) 한 번만 만든다."""

    def __init__(self, p: Project, n: int, skip: set[int] = frozenset()):
        self.paras: list[tuple[int, int, str, set[str]]] = []
        for e in sorted(p.episodes, key=lambda e: e.plot.number):
            m = e.plot.number
            if m >= n or m in skip or not e.text:
                continue
            for k, para in enumerate(_paragraphs(e.text)):
                self.paras.append((m, k, para, grams(para)))
        self.df: Counter = Counter()
        for *_, g in self.paras:
            self.df.update(g)

    def find(self, query: str, budget: int, terms: Iterable[str] = ()) -> list[tuple[int, list[str]]]:
        """query 와 겹치는 단락을 예산만큼. [(화, [단락...])] 화 순서.
        점수는 겹치는 글 조각의 희소도(idf) 합을 단락 길이로 누른 값, terms(조연 이름, 이야기 요소, 장소)가 있으면 더 준다."""
        if not self.paras or budget <= 0:
            return []
        df, total = self.df, len(self.paras)
        q = {g for g in grams(query) if df[g] and df[g] <= COMMON * total}
        idf = {g: math.log(1 + total / df[g]) for g in q}
        terms = [t for t in terms if t]
        scored = []
        for m, k, para, g in self.paras:
            s = sum(idf[x] for x in g & q) / math.sqrt(1 + len(g) / 120)
            s += sum(4.0 for t in terms if t in para)
            if s > 0:
                scored.append((s, m, k, para))
        scored.sort(key=lambda x: -x[0])
        picked: dict[int, list[tuple[int, str]]] = {}
        used = 0
        for s, m, k, para in scored:
            if used + len(para) > budget:
                continue
            picked.setdefault(m, []).append((k, para))
            used += len(para)
        return [(m, [para for _, para in sorted(picked[m])]) for m in sorted(picked)]


INDEX_KEEP = 2  # 최근에 만든 단락 색인을 들고 있는 수. 검수 · 검수 넓히기가 같은 원고로 색인을 다시 만들지 않게
_index_cache: dict[tuple, "PassageIndex"] = {}
_index_lock = threading.Lock()


def passage_index(p: Project, n: int, skip: set[int] = frozenset()) -> "PassageIndex":
    """PassageIndex 를 만들되, 넣을 화와 그 본문이 같으면 최근에 만든 것을 다시 쓴다 (장편 300화에서 한 번에 0.15~0.25초).
    열쇠는 (화 번호, 본문) 목록이라 본문이 바뀌면 새로 만든다. 색인은 find 가 바꾸지 않아 스레드끼리 나눠 써도 된다."""
    key = tuple((e.plot.number, e.text) for e in sorted(p.episodes, key=lambda e: e.plot.number)
                if e.plot.number < n and e.plot.number not in skip and e.text)
    with _index_lock:
        hit = _index_cache.pop(key, None)
        if hit is not None:
            _index_cache[key] = hit  # 최근 것으로 옮긴다
            return hit
    built = PassageIndex(p, n, skip)
    with _index_lock:
        _index_cache[key] = built
        while len(_index_cache) > INDEX_KEEP:
            _index_cache.pop(next(iter(_index_cache)))
    return built


def recall(p: Project, n: int, query: str, budget: int, skip: set[int], terms: Iterable[str] = ()) -> list[tuple[int, list[str]]]:
    """n화 앞의 본문(skip 화 제외)에서 query 와 겹치는 단락을 예산만큼 찾는다. [(화, [단락...])] 화 순서."""
    return passage_index(p, n, skip).find(query, budget, terms)


def recall_size(p: Project, n: int, budget: int, skip: set[int]) -> list[tuple[int, list[str]]]:
    """recall 과 같은 모양으로 예산만큼 찬 자리만 낸다. 단락은 찾지 않는다 (자동 집필 추정, autorun.estimate).
    추정은 빈 화를 채움 글로 채워서, 옛 화가 하나라도 있으면 recall 은 예산을 거의 다 채운다."""
    old = [e.plot.number for e in p.episodes if e.plot.number < n and e.plot.number not in skip and e.text]
    return [(max(old), ["가" * budget])] if old else []


_COUNT = re.compile(r"\d|하루|이틀|사흘|나흘|닷새|엿새|이레|열흘|보름|일주일|[한두세네]\s?달|"
                    r"(?:[한두세네]|다섯|여섯|일곱|여덟|아홉|열|스물|서른|마흔|쉰|예순|일흔|여든|아흔)\s?(?:살|해|명|번|시간)")


def has_count(text: str) -> bool:
    """기간 · 나이 · 인원 · 횟수 같은 셈이 들어 있는지. '사흘'과 '일주일'처럼 글 조각은 안 겹쳐도 같은 거리를 묻는 문장을 잇는다."""
    return bool(_COUNT.search(text))


def related_lines(lines: list[str], query: str, budget: int) -> list[str]:
    """query 와 글 조각이 많이 겹치는 줄을 예산만큼, 원래 순서로. 겹치는 것이 없으면 넣지 않는다.
    query 에 셈(기간, 나이, 인원)이 있으면 셈이 있는 줄을 한 조각 더 겹친 것으로 본다."""
    q, count = grams(query), has_count(query)
    scored = []
    for i, line in enumerate(lines):
        g = grams(line)
        hit = len(g & q)
        if hit:
            hit += count and has_count(line)
            scored.append((hit / math.sqrt(len(g) or 1), i))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    keep, used = [], 0
    for _, i in scored:
        cost = len(lines[i]) + 3
        if used + cost <= budget:
            keep.append(i)
            used += cost
    return [lines[i] for i in sorted(keep)]


def related_facts(p: Project, query: str, budget: int) -> list[str]:
    """query 와 겹치는 확정 사실 (related_lines)."""
    return related_lines(p.facts, query, budget)


def characters_by_ids(p: Project, ids: set[str]) -> list[Character]:
    return [c for c in p.characters if c.id in ids]


# ---------- 플레이 모드 (prompts.play_scene_prompt) ----------
# 한 턴은 짧은 장면이라 소설보다 작은 예산을 쓴다. 고르는 규칙은 소설과 같은 결로 두되, 늘 넣는 최근 사실은 없다.

PLAY_FACTS_RECENT = 10  # 플레이 장면: 최근 사실은 겹치는 것이 없어도 후보로 둔다 (점수는 가장 낮게)


def play_facts(p: Project, ids: set[str], query: str, budget: int, terms: Iterable[str] = ()) -> tuple[list[str], int]:
    """플레이 장면의 확정 사실을 예산(글자)만큼. pick_facts 와 같은 점수(조연 · 단역 이름 3, 이야기 요소 · 장소 2, 주역 이름 1,
    같으면 query 와 겹치는 글 조각)에 최근 PLAY_FACTS_RECENT 개를 0.5 점 후보로 더한다. pick_facts 처럼 최근 30개를 예산 밖으로
    늘 넣지 않아 예산을 넘지 않는다. 아무것도 겹치지 않는 옛 사실은 넣지 않는다. 고른 사실은 원래 순서로. (사실들, 뺀 수)"""
    facts = p.facts
    main, other = names_of(p, ids)
    terms = [t for t in terms if t]
    q = grams(query)
    recent = set(range(max(0, len(facts) - PLAY_FACTS_RECENT), len(facts)))
    scored = []
    for i, f in enumerate(facts):
        s = 3 * any(nm in f for nm in other) + 2 * any(t in f for t in terms) + any(nm in f for nm in main)
        g = grams(f)
        overlap = len(g & q) / (len(g) or 1)
        if not s and overlap < KNOWS_OVERLAP and i not in recent:
            continue
        scored.append((s or (0.5 if i in recent else 0.2), overlap, i))
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    keep, used = set(), 0
    for _, _, i in scored:
        cost = len(facts[i]) + 3
        if used + cost > budget:
            continue
        keep.add(i)
        used += cost
    return [facts[i] for i in sorted(keep)], len(facts) - len(keep)


def fit_lines(lines: list[str], budget: int, first: int = 0) -> tuple[list[str], int]:
    """앞에서부터 예산(글자)에 드는 줄만 고른다. lines 는 넣을 순서(중요한 것 먼저)로 준다.
    first 개는 예산을 넘어도 넣는다 (플레이어 인물 줄처럼 빠지면 안 되는 것). (고른 줄, 뺀 수)"""
    out, used = [], 0
    for i, line in enumerate(lines):
        cost = len(line) + 1
        if i >= first and used + cost > budget:
            continue
        out.append(line)
        used += cost
    return out, len(lines) - len(out)
