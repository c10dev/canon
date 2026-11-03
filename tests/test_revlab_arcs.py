"""아크 · 부 역설계 (revlab.can_arcs · clean_arcs · run_arcs · set_arcs · take_offer, prompts.rev_arcs_prompt, 웹, static/revlab.js)."""
import pytest
from fastapi.testclient import TestClient

from canon import context, prompts, revlab
from canon.mock import MockLLM
from canon.schema import RevArc, RevArcSet, RevPart

from .jsvm import needs_node, run_js
from .test_revlab import FILES, home  # noqa: F401 (fixture)
from .test_web import _wait

BODY = "서윤이 등대 문을 연다. 바람이 분다. 아무도 대답하지 않는다. " * 12


def _lab(n=8, parse=True):
    lab = revlab.create("등대", "\n\n".join(f"{i}화\n\n{BODY}" for i in range(1, n + 1)))
    if parse:
        revlab.run_parse(lab.id, MockLLM())
    return revlab.load(lab.id)


def _spans(plan):
    return [(a.start_ep, a.end_ep) for a in plan.arcs]


def test_can_arcs_needs_parsed_episodes(home):
    with pytest.raises(ValueError, match="4개 넘게"):
        revlab.can_arcs(_lab(3))
    lab = _lab(5, parse=False)
    revlab.run_parse(lab.id, MockLLM(), [1, 2])
    with pytest.raises(ValueError, match="남은 화: 3, 4, 5"):
        revlab.can_arcs(revlab.load(lab.id))


def test_run_arcs_cleans_ai_answer(home):
    lab = _lab()
    plan = revlab.run_arcs(lab.id, MockLLM())
    assert _spans(plan) == [(1, 4), (5, 8)]  # 뒤 아크가 6화에서 시작해 빈 5화를 뒤 아크로 메웠다
    a, b = plan.arcs
    assert a.climax_ep == 4 and b.climax_ep == 0  # 범위 밖 999화는 비운다
    assert "유령" not in a.cast and a.cast  # 실험 인물 목록에 없는 이름은 뺀다
    assert b.title == "아크 2" and [x.name for x in b.acts] == list("기승전결")  # 빈 기승전결은 기본 비율로 나눈다
    for x in plan.arcs:
        assert x.acts[0].start_ep == x.start_ep and x.acts[-1].end_ep == x.end_ep
        assert all(p.end_ep + 1 == q.start_ep for p, q in zip(x.acts, x.acts[1:]))
    assert [(p.start_ep, p.end_ep) for p in plan.parts] == [(1, 4), (5, 8)]
    assert any("범위" in n for n in plan.notes) and plan.by == "ai" and plan.at
    saved = revlab.load(lab.id)
    assert saved.arcs == plan and saved.arc_offer is None
    v = revlab.view(saved)
    assert v["arcs"]["arcs"][0]["title"] == "등대 실종" and v["arc_state"] == {"outside": [], "reparsed": []}


def test_clean_cover_overlaps_and_drops():
    lab = revlab.RevLab(id=1, episodes=[revlab.RevEpisode(number=n, text="x") for n in range(3, 13)])
    d = RevArcSet(arcs=[RevArc(start_ep=1, end_ep=6), RevArc(start_ep=5, end_ep=9), RevArc(start_ep=7, end_ep=8), RevArc(start_ep=20, end_ep=30)],
                  parts=[RevPart(start_ep=3, end_ep=7), RevPart(start_ep=8, end_ep=12)])
    plan = revlab.clean_arcs(lab, d)
    assert _spans(plan) == [(3, 6), (7, 12)]  # 겹친 것은 밀고, 다 밀린 것과 범위 밖은 빼고, 끝은 마지막 화까지
    assert [p.title for p in plan.parts] == ["1부", "2부"]
    assert any("뺐어요" in n for n in plan.notes) and any("1부의 끝이 아크 경계와 맞지 않아요" in n for n in plan.notes)
    with pytest.raises(ValueError):
        revlab.clean_arcs(lab, RevArcSet(arcs=[RevArc(start_ep=50, end_ep=60)]))


def test_author_edit_keeps_new_ai_answer_aside(home):
    lab = _lab()
    revlab.run_arcs(lab.id, MockLLM())
    lab = revlab.load(lab.id)
    arcs = [x.model_copy() for x in lab.arcs.arcs]
    arcs[0].end_ep, arcs[1].start_ep, arcs[0].title = 2, 3, "고친 아크"
    revlab.set_arcs(lab, [], arcs)
    assert lab.arcs.by == "both" and _spans(lab.arcs) == [(1, 2), (3, 8)] and lab.arcs.arcs[0].acts[-1].end_ep == 2
    assert lab.arcs.arcs[0].climax_ep == 0 and lab.arcs.parts == []  # 범위를 벗어난 클라이맥스 화는 비운다
    revlab.save(lab)
    revlab.run_arcs(lab.id, MockLLM())
    lab = revlab.load(lab.id)
    assert lab.arcs.arcs[0].title == "고친 아크" and lab.arc_offer and lab.arc_offer.by == "ai"
    revlab.take_offer(lab, False)
    assert lab.arc_offer is None and lab.arcs.arcs[0].title == "고친 아크"
    with pytest.raises(ValueError):
        revlab.take_offer(lab, True)
    fresh = revlab.RevLab(**_lab().model_dump())
    revlab.set_arcs(fresh, [], [RevArc(title="하나", start_ep=1, end_ep=8)])
    assert fresh.arcs.by == "author"


def test_episode_changes_move_arcs(home):
    lab = _lab()
    revlab.run_arcs(lab.id, MockLLM())
    lab = revlab.load(lab.id)
    revlab.renumber(lab, 11)
    assert _spans(lab.arcs) == [(11, 14), (15, 18)] and lab.arcs.arcs[0].climax_ep == 14
    revlab.drop_episode(lab, 14)  # 첫 아크의 끝 화이자 클라이맥스
    assert _spans(lab.arcs) == [(11, 13), (14, 17)] and lab.arcs.arcs[0].climax_ep == 0
    assert lab.arcs.parts[0].end_ep == 13
    revlab.append_text(lab, f"1화\n\n{BODY}")
    assert revlab.arc_state(lab)["outside"] == [18]
    lab.episodes[0].made_at = "9999-01-01T00:00"
    assert revlab.arc_state(lab)["reparsed"] == [11]
    revlab.replace_text(lab, "새 글", f"1화\n\n{BODY}")
    assert lab.arcs is None and lab.arc_offer is None


def test_arcs_prompt_folds_but_keeps_every_episode(home):
    lab = _lab()
    p = prompts.rev_arcs_prompt(lab)
    assert "1~8화" in p and "## 8화" in p and "엔딩 훅" in p and "호흡: 최고 긴장" in p and "인물 목록" in p
    big = revlab.RevLab(**lab.model_dump())
    e = big.episodes[0]
    big.episodes = [e.model_copy(deep=True, update={"number": n}) for n in range(1, 301)]
    for x in big.episodes:
        x.plot.summary = "서윤이 등대에 간다. " * 30
    p = prompts.rev_arcs_prompt(big)
    assert "## 1화" in p and "## 300화" in p and "화가 300개라" in p and len(p) <= context.BUDGET["rev_arcs"] + 3000
    est = revlab.estimate(lab, "arcs")
    assert est["calls"] == 1 and est["rows"][0]["label"] == "아크 · 부" and "화마다" not in est["note"]


def test_web_arcs_flow(home):
    from canon import web

    lab = _lab()
    c = TestClient(web.app)
    assert c.post(f"/api/revlab/{lab.id}/estimate", json={"kind": "arcs"}).json()["calls"] == 1
    j = _wait(c, c.post(f"/api/revlab/{lab.id}/jobs", json={"kind": "arcs"}).json()["id"])
    assert j["status"] == "done" and j["result"] == {"arcs": 2, "parts": 2, "offer": False}
    v = c.get(f"/api/revlab/{lab.id}").json()
    arcs = v["arcs"]["arcs"]
    arcs[0]["end_ep"], arcs[1]["start_ep"] = 5, 6
    v = c.put(f"/api/revlab/{lab.id}/arcs", json={"parts": [], "arcs": arcs}).json()
    assert v["arcs"]["by"] == "both" and v["arcs"]["arcs"][0]["end_ep"] == 5
    j = _wait(c, c.post(f"/api/revlab/{lab.id}/jobs", json={"kind": "arcs"}).json()["id"])
    assert j["result"]["offer"] is True
    v = c.post(f"/api/revlab/{lab.id}/arcs/offer", json={"take": True}).json()
    assert v["arc_offer"] is None and v["arcs"]["by"] == "ai" and v["arcs"]["arcs"][0]["end_ep"] == 4
    assert c.post(f"/api/revlab/{lab.id}/arcs/offer", json={"take": False}).status_code == 400
    assert c.delete(f"/api/revlab/{lab.id}/arcs").json()["arcs"] is None
    small = _lab(3)
    assert c.post(f"/api/revlab/{small.id}/jobs", json={"kind": "arcs"}).status_code == 400


@needs_node
def test_js_arcs_card_and_band(home):
    from canon import web

    lab = _lab()
    revlab.run_arcs(lab.id, MockLLM())
    lab = revlab.load(lab.id)
    data = {"lab": revlab.view(lab), "pace": revlab.pace(lab), "home": {**revlab.labels(), **web._cue_labels(), "labs": revlab.listing()}}
    got = run_js(FILES, """(() => {
      S.project = null; S.name = null; S.route = ['revlab']; S.rev = data.home; S.cue = data.home;
      S.revLab = data.lab; S.revEp = 1; S.revPane = 'shape'; S.revPace = { id: data.lab.id, ...data.pace };
      S.revEsts = { 'arcs:': { usd: 0.03, calls: 1, rows: [], model: 'm', note: '' } };
      const card = revArcsCard();
      const band = revArcBand(data.pace.rows, 16, data.lab.arcs);
      actions.revArcEditOpen();
      actions.revArcSplit(1);
      const split = S.revArcEdit.arcs.map((a) => [a.start_ep, a.end_ep]);
      revArcInput('arcs:0:end_ep', '2', true);
      const moved = S.revArcEdit.arcs.map((a) => [a.start_ep, a.end_ep]);
      actions.revArcMerge('arcs:2');
      const merged = S.revArcEdit.arcs.map((a) => [a.start_ep, a.end_ep]);
      const editor = revArcsCard();
      return { card, band, split, moved, merged, editor, over: revLabCards() };
    })()""", data)
    assert "등대 실종" in got["card"] and "아크 다시 찾기" in got["card"] and "1부" in got["card"] and "4화" in got["card"]
    assert got["band"]["h"] > 0 and got["band"]["svg"].count("rev-band-arc") == 2 and "rev-band-climax" in got["band"]["svg"]
    assert got["split"] == [[1, 4], [5, 6], [7, 8]]
    assert got["moved"] == [[1, 2], [3, 6], [7, 8]]
    assert got["merged"] == [[1, 2], [3, 8]]
    assert 'data-action="revArcSave"' in got["editor"] and "아크 2개" in got["over"]
