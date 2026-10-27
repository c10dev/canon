"""인과율 화면(static/causal.js)의 elBasis · causalStale 이 elements.basis · stale 과 같은지. node 가 있을 때만 돈다.
elBasis 는 서버가 남긴 basis 글과 글자 그대로 비교하므로 따옴표 · 줄바꿈 · 이모지 같은 이스케이프까지 같아야 한다."""
from canon import elements
from canon.schema import ElementImpact, ImpactReport, StoryElement

from .jsvm import dump, needs_node, run_js

ELEMENTS = [
    StoryElement(id="el-01"),
    StoryElement(id="el-02", kind="장소", name="검은 탑", aliases=["탑", "흑탑"], description="북쪽 끝.\n문이 없다",
                 characters=["c1", "c2"], since_ep=3, episodes=[5, 9], reveal_ep=12),
    StoryElement(id="el-03", kind="물건", name='"봉인" 검 \\ 원본', description="탭\t제어\x01 · 줄 구분  · 🗡️ · é"),
    StoryElement(id="el-04", kind="예정 사건", name="축제", context="off", found_in="본문", found_ep=4),  # basis 밖 칸
]


@needs_node
def test_el_basis_matches_server():
    els = [e.model_copy(deep=True) for e in ELEMENTS]
    for e in els:
        e.impact = ElementImpact(report=ImpactReport(summary=""), basis=elements.basis(e))
    changed = [e.model_copy(deep=True) for e in els]
    changed[1].aliases.append("탑3")
    changed[2].description += " "
    changed[3].context, changed[3].found_ep = "always", 5  # basis 밖 칸은 지난 것으로 치지 않는다
    expr = "data.map((e) => [elBasis(e), causalStale(e)])"
    got = run_js(["app.js", "causal.js"], expr, [dump(e) for e in els + changed])
    assert got == [[elements.basis(e), elements.stale(e)] for e in els + changed]
    assert [s for _, s in got] == [False] * 4 + [False, True, True, False]
