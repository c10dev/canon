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


@needs_node
def test_causal_status_and_cells():
    """요소 상태(causalStatus)와 관련 화 칸(causalCells): 분석 전 · 다시 분석 · 검토 · 적용함, 반영한 화는 모순 · 고칠 화에서 빠진다."""
    from canon.schema import EpisodePlot, ImpactConflict, TextPatch
    plot = EpisodePlot(number=4, act="기", title="t", summary="", events=[], characters=[], emotional_shift="", ending_hook="")
    rep = ImpactReport(summary="s", conflicts=[ImpactConflict(target="본문", episode=2, quote="q", problem="p", fix="본문 수정")],
                       episodes=[plot], patches=[TextPatch(episode=2, quote="q", replacement="r")])
    base = StoryElement(id="el-x", name="탑", description="d", since_ep=2, reveal_ep=5)
    review = base.model_copy(update={"impact": ElementImpact(report=rep, basis=elements.basis(base))})
    applied = base.model_copy(update={"impact": ElementImpact(report=rep, basis=elements.basis(base), outcome="applied", applied=["patch:0"])})
    stale = base.model_copy(update={"impact": ElementImpact(report=rep, basis="옛 내용")})
    new = base.model_copy(update={"added_after": 3})
    links = [{"episode": 1, "where": [], "planned": False, "terms": [], "characters": ["c1"], "snippet": ""},
             {"episode": 3, "where": ["본문"], "planned": False, "terms": ["탑"], "characters": [], "snippet": "탑"}]
    eps = [{"n": n, "text": n <= 3} for n in range(1, 6)]
    expr = ("({ st: data.els.map((e) => causalStatus(e)).map((s) => [s.key, s.label, s.todo]),"
            " review: causalCells(data.els[1], data.links, 6, data.eps).map((c) => [c.cls, c.tag, c.group]),"
            " applied: causalCells(data.els[2], data.links, 6, data.eps).map((c) => c.cls) })")
    out = run_js(["app.js", "causal.js"], expr, {"els": [dump(e) for e in (base, review, applied, stale, new)], "links": links, "eps": eps})
    assert out["st"] == [["none", "", False], ["review", "검토할 것 · 2개 화", True], ["applied", "적용함", False],
                         ["stale", "다시 분석 필요", True], ["new", "분석 전", True]]
    assert out["review"] == [["rel weak tx before", "인물만", "char"], ["bad since tx", "모순", "bad"], ["rel tx", "이름이 나옴", "rel"],
                             ["plot", "고칠 화", "bad"], ["reveal", "", ""], ["none", "", ""]]
    assert out["applied"][1] == "done since tx" and out["applied"][3] == "plot"  # 적용한 본문 수정 화만 빠지고, 적용하지 않은 플롯 화는 남는다
