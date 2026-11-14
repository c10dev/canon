"""문체 규칙의 빈도 하한 줄 찾기 (metrics.rate_floor, LLM 없음)와 화면의 같은 규칙 (style.js rateFloor, node 가 있을 때).
실행: python -m pytest tests"""
from canon import metrics
from canon.schema import StyleProfile

from .jsvm import needs_node, run_js

FLOORS = [
    "한 화에 한 번은 위험이 실제로 일부 일어난다. 그 결과가 다음 화까지 남는다.",
    "주인공은 장면마다 한 번 이상 속으로 계산한다.",
    "두 사람의 온도 차이를 매 대화마다 교차 서술한다.",
    "몸과 마음이 부딪치는 아이러니를 매 장면 강조해 서술한다.",
    "아크마다 한 번은 상대가 먼저 고른다.",
    "새 위험을 아크마다 하나 더한다. 같은 문구를 화마다 되풀이하지 않는다.",
    "노골 장면 하나마다 인물에게 바뀌는 것 하나를 묶는다.",
    "빠르게 간다. 각 화마다 '확인 → 떠보기 → 밀회'로 이어지는 구성을 취한다.",
    "독백을 최소 두 줄 넣는다.",
    "한 화에 한 번은 들킬 뻔한 위기가 실제로 일어나고, 그 결과가 다음 화까지 남는다.",   # '까지' 는 횟수 뒤에서만 상한이다
    "웃음 포인트를 3번 이상 넣는다",
]
PASSES = [
    "'몸이 배신했다'처럼 설명하는 문장을 장면마다 쓰지 않는다.",
    "같은 협박 문구를 화마다 되풀이하지 않는다.",
    "이 장치는 한 화에 한 번까지만 쓴다.",
    "회사에 빗댄 비유를 한 장면에 한 번 넘게 쓰지 않는다.",
    "같은 낱말을 두 번 이상 쓰지 말 것",
    "셋은 화를 짜는 재료일 뿐 정해진 순서가 아니다. 화마다 순서와 비중이 달라진다.",
    "미션 조건을 아크마다 다르게 제시한다.",
    "손이 닿아 움직일 때마다 그 동작이 내는 소리를 의성어로 적는다.",
    "문단과 문단 사이에는 반드시 빈 줄을 넣는다.",
    "변화마다 표정을 적는다.",          # '화' 로 끝나는 다른 낱말
    "감정은 행동으로 보여 준다.",
    "",
]


def test_rate_floor_finds_floors_and_passes_caps():
    assert [x for x in FLOORS if not metrics.rate_floor(x)] == []
    assert [x for x in PASSES if metrics.rate_floor(x)] == []


def test_floor_lines_reads_only_pacing_and_dos():
    st = StyleProfile(pacing=FLOORS[7], dos=[FLOORS[0], PASSES[0]], donts=[FLOORS[1]],
                      sound_effects="화마다 세 번 이상 나온다", inner_monologue=FLOORS[1])
    assert metrics.floor_lines(st) == [("pacing", FLOORS[7]), ("dos", FLOORS[0])]
    assert metrics.floor_lines(StyleProfile()) == []


@needs_node
def test_screen_rule_matches_server():
    lines = FLOORS + PASSES
    got = run_js(["app.js", "style.js"], "data.map((x) => rateFloor(x))", lines)
    assert got == [metrics.rate_floor(x) for x in lines]
    src = run_js(["app.js", "style.js"], "[FLOOR_HIT.source, FLOOR_PASS.source]", None)
    assert src == [metrics.FLOOR_HIT, metrics.FLOOR_PASS]
