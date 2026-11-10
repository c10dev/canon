"""설계도 화면(static/blueprint.js): 쌍 목록 · 그리기 · 저장할 몫 합치기. node 가 있을 때만 돈다."""
import typing

from canon.schema import Character, ContactLadder, ContactRung, Milestone, Project, Relationship, RelStage

from .jsvm import dump, needs_node, run_js
from .test_primary_count_js import FILES

VIEW = {"warnings": [{"source": "a", "target": "j", "text": "관계 이정표 아영 → 지훈: 경고"}],
        "parts": [{"id": "hand_r", "label": "오른 손"}], "acts": [{"id": "brush", "label": "스치다"}], "last": 3}


def _proj() -> Project:
    p = Project()
    p.meta.title, p.meta.target_episodes = "지하철", 600
    p.characters = [Character(id="j", name="지훈", role="상대"), Character(id="a", name="아영", role="주인공"), Character(id="d", name="다은", role="친구")]
    p.relationships = [Relationship(a="a", b="j", type="협박")]
    p.blueprint.milestones = [Milestone(id="ms-1", source="a", target="j", from_ep=1, to_ep=15, stage="경계", label="정체를 안다"),
                              Milestone(id="ms-2", source="d", target="a", from_ep=20, to_ep=30, stage="균열")]
    p.blueprint.ladders = [ContactLadder(a="j", b="a", rungs=[ContactRung(id="cr-1", label="스침", parts=["hand_r"], acts=["brush"], layer="옷 위", from_ep=1, to_ep=3)])]
    return p


def _run(expr: str, p: Project, extra: dict | None = None):
    setup = "S.name = 't'; S.project = data.project; S.route = ['p', 't', 'blueprint']; S.jobs = []; S.bp = { ...data.view, blueprint: data.project.blueprint }; Object.assign(S, data.extra);"
    return run_js(FILES, f"(() => {{ {setup} return {expr}; }})()", {"project": dump(p), "view": VIEW, "extra": extra or {}})


@needs_node
def test_stage_words_match_schema():
    got = run_js(FILES, "BP_STAGES", {})
    assert got == ["", *typing.get_args(RelStage)]


@needs_node
def test_pairs_keep_relationship_order_and_add_blueprint_only_pairs():
    got = _run("bpPairs(S.project, S.project.blueprint)", _proj())
    assert got == [["a~j", "a", "j"], ["a~d", "d", "a"]]


@needs_node
def test_overview_and_pair_page_render():
    p = _proj()
    html = _run("viewBlueprint()", p)
    assert "설계도" in html and "경고" in html and "아영 ↔ 지훈" in html and "다은 ↔ 아영" in html
    html = _run("viewBlueprint()", p, {"bpSel": "a~j"})
    assert 'id="bp-band"' in html and "아영 → 지훈" in html and "정체를 안다" in html and "1~3화" in html and "오른 손" in html
    assert "1~15화" in html and "작품 전체" in html  # 기획한 화(15화)가 작품 화수보다 짧아 범위 고르기를 보인다
    html = _run("(S.bpEdit = { card: 'ladder', key: 'a~j', data: JSON.parse(JSON.stringify(S.project.blueprint)), orig: '' }, viewBlueprint())", p, {"bpSel": "a~j"})
    assert 'data-bp="ladders.0.rungs.0.label"' in html and 'data-action="bpSave"' in html


@needs_node
def test_merged_replaces_only_the_edited_part():
    p = _proj()
    expr = """(() => {
      const server = S.project.blueprint;
      const data = JSON.parse(JSON.stringify(server));
      data.milestones = data.milestones.filter((m) => m.source !== 'a');
      data.milestones.push({ id: '', source: 'j', target: 'a', from_ep: 5, to_ep: 6, stage: '호감', label: '', trigger: '' });
      data.milestones.push({ id: '', source: 'd', target: 'a', from_ep: 1, to_ep: 1, stage: '', label: '다른 쌍', trigger: '' });
      data.ladders[0].rungs = [];
      data.note = '바뀐 원칙';
      const ms = bpMerged({ card: 'ms', key: 'a~j', data }, server);
      const lad = bpMerged({ card: 'ladder', key: 'a~j', data }, server);
      return { ms: ms.milestones.map((m) => [m.source, m.target, m.from_ep]), msNote: ms.note, lad: lad.ladders.length, ladMs: lad.milestones.length };
    })()"""
    got = _run(expr, p)
    assert got["ms"] == [["d", "a", 20], ["j", "a", 5]]  # 이 쌍 몫만 바뀌고 다른 쌍(다은 → 아영)은 서버 값 그대로
    assert got["msNote"] == "" and got["lad"] == 0 and got["ladMs"] == 2  # 칸을 다 지운 사다리는 빠진다


@needs_node
def test_relationship_card_links_to_journey():
    p = _proj()
    html = run_js(FILES, "(S.name = 't', S.project = data.project, relJourney(data.project.relationships[0]))", {"project": dump(p)})
    assert "이정표 1 · 사다리 1칸" in html and "/blueprint/a~j" in html



@needs_node
def test_draft_card_and_pending_shown():
    p = _proj()
    draft = {"a": "a", "b": "j", "start": 1, "end": 15, "arc": 1, "reply": "뽑았어요",
             "milestones": [{"source": "a", "target": "j", "from_ep": 2, "to_ep": 4, "stage": "경계", "label": "의심", "trigger": "", "evidence": [{"episode": 2, "quote": "눈을 피한다"}]}],
             "rungs": [{"label": "스침", "parts": ["hand_r"], "acts": ["brush"], "layer": "옷 위", "places": [], "lead": "j", "note": "", "from_ep": 3, "to_ep": 3, "evidence": []}]}
    html = _run("viewBlueprint()", p, {"bpSel": "a~j", "bpDraft": draft})
    assert 'id="bp-draft"' in html and "2화 「눈을 피한다」" in html and 'data-action="bpDraftUse"' in html and "지훈 주도" in html
    got = _run("[pendingShown({ kind: 'blueprint' }), (S.bpDraft = null, pendingShown({ kind: 'blueprint' }))]", p, {"bpDraft": draft})
    assert got == [True, False]
    html = _run("viewBlueprint()", p, {"bpSel": "a~d", "bpDraft": draft})
    assert 'id="bp-draft"' not in html  # 다른 쌍 쪽에는 보이지 않는다
