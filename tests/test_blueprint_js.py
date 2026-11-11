"""설계도 화면(static/blueprint.js): 쌍 목록 · 그리기 · 저장할 몫 합치기. node 가 있을 때만 돈다."""
import typing

from canon.schema import AbilityPlan, Character, ContactLadder, ContactReach, ContactRung, Milestone, Project, Relationship, RelStage

from .jsvm import dump, needs_node, run_js
from .test_primary_count_js import FILES

VIEW = {"warnings": [{"source": "a", "target": "j", "text": "관계 이정표 아영 → 지훈: 경고"}],
        "plans": [{"id": "ap-1", "got": 3, "state": "앞섬", "linked": True}, {"id": "ap-2", "got": None, "state": "예정", "linked": False}],
        "ability_warnings": [{"character": "a", "text": "능력 일정 아영의 은신 Lv2: 3화에 얻었어요."}],
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



@needs_node
def test_review_rows_and_reached_marks():
    p = _proj()
    p.contact_log = [ContactReach(a="j", b="a", rung="cr-1", quote="손이 스친다", episode=3)]
    html = _run("viewBlueprint()", p, {"bpSel": "a~j"})
    assert "3화에 닿음" in html and "본문에서 닿음" in html
    d = {"contacts": [{"a": "a", "b": "j", "rung": "cr-1", "quote": "손이 스친다", "episode": 4}]}
    rows = run_js(FILES, "(S.name = 't', S.project = data.project, contactDeltaRows(4, data.d, (k) => `<input id=\"pk-${k}\">`))", {"project": dump(p), "d": d})
    assert 'id="pk-u0"' in rows and "1. 스침" in rows and "기본으로 고르지 않았어요" in rows
    picks = run_js(FILES, "(S.name = 't', S.project = data.project, defaultPicks(data.d))", {"project": dump(p), "d": {**d, "character_updates": [], "events": [], "secrets_added": [], "relationship_updates": [], "new_facts": [], "foreshadow_planted": [], "foreshadow_resolved": []}})
    assert picks.get("u0") is False
    p.contact_held = [ContactReach(a="a", b="j", rung="cr-1", episode=5)]
    html = _run("viewBlueprint()", p)
    assert 'id="bp-held"' in html and 'data-arg="0|take"' in html



@needs_node
def test_ai_card_and_draft_title():
    p = _proj()
    html = _run("viewBlueprint()", p, {"bpSel": "a~j"})
    assert 'data-action="bpDraftAI"' in html and 'id="bp-note-ai"' in html  # 플롯이 없어도 짜기는 보인다
    assert 'data-action="bpExtract"' not in html  # 뽑을 플롯이 없다
    draft = {"a": "a", "b": "j", "start": 1, "end": 600, "mode": "draft", "reply": "", "milestones": [], "rungs": []}
    assert "AI가 짠 설계도" in _run("viewBlueprint()", p, {"bpSel": "a~j", "bpDraft": draft})
    assert "여정 짜기" in _run("viewBlueprint()", p)
    assert _run("pendingShown({ kind: 'blueprint_draft' })", p, {"bpDraft": draft}) is True


@needs_node
def test_ability_page_and_merge():
    p = _proj()
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="a", ability="은신", grade="Lv2", condition="밤 훈련", from_ep=5, to_ep=8),
                                 AbilityPlan(id="ap-2", character="j", ability="추적", from_ep=20, to_ep=22)]
    html = _run("viewBlueprint()", p)
    assert "능력 일정" in html and "2줄" in html and "blueprint/%40ability" in html
    html = _run("viewBlueprint()", p, {"bpSel": "@ability"})
    assert 'id="bp-band"' in html and "은신 Lv2" in html and "3화에 얻음 · 계획보다 먼저" in html and "조건: 밤 훈련" in html and "도감에 없음" in html
    assert "능력 일정 아영의 은신 Lv2: 3화에 얻었어요." in html and "관계 이정표 아영 → 지훈: 경고" not in html  # 이 쪽은 능력 경고만
    html = _run("(S.bp.plans[1].state = '모름', viewBlueprint())", p, {"bpSel": "@ability"})
    assert "상태창이 없어 실제를 셀 수 없어요" in html
    html = _run("(S.bpEdit = { card: 'ap', key: '@ability', data: JSON.parse(JSON.stringify(S.project.blueprint)), orig: '' }, viewBlueprint())", p, {"bpSel": "@ability"})
    assert 'data-bp="ability_plans.0.ability"' in html and 'data-action="bpApAdd"' in html and html.count('data-action="bpSave"') == 1
    expr = """(() => {
      const data = JSON.parse(JSON.stringify(S.project.blueprint));
      data.ability_plans[0].grade = 'Lv3';
      data.ability_plans.push({ id: '', character: 'a', ability: ' ', grade: '', condition: '', from_ep: 0, to_ep: 0 });
      data.milestones = [];
      return bpMerged({ card: 'ap', key: '@ability', data }, S.project.blueprint);
    })()"""
    got = _run(expr, p)
    assert [x["grade"] for x in got["ability_plans"]] == ["Lv3", ""] and len(got["milestones"]) == 2  # 능력 일정 몫만 바꾸고 빈 줄은 뺀다


@needs_node
def test_ability_ai_card_and_draft_card():
    from canon.schema import Ability
    p = _proj()
    p.abilities = [Ability(id="ab-1", name="은신", aliases=["그림자 걸음"])]
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="a", ability="은신", grade="Lv2", from_ep=5, to_ep=8)]
    html = _run("viewBlueprint()", p, {"bpSel": "@ability"})
    assert 'id="bp-ab-ai"' in html and 'data-action="bpAbDraftAI"' in html and 'id="bp-ab-who"' in html
    assert 'data-action="bpAbExtract"' not in html and 'id="bp-ab-draft"' not in html  # 뽑을 플롯도 제안도 없다
    rows = [{"character": "a", "ability": "그림자 걸음", "grade": "", "condition": "첫 위기", "from_ep": 2, "to_ep": 2, "evidence": [{"episode": 2, "quote": "기척이 사라진다"}]},
            {"character": "a", "ability": "은 신", "grade": "(Lv2)", "condition": "", "from_ep": 6, "to_ep": 6, "evidence": []},
            {"character": "a", "ability": "질주", "grade": "", "condition": "", "from_ep": 9, "to_ep": 12, "evidence": []}]
    drafts = {"a": {"character": "a", "start": 1, "end": 600, "mode": "extract", "reply": "세 줄을 뽑았어요.", "abilities": rows, "job": "j1"},
              "j": {"character": "j", "start": 1, "end": 120, "mode": "draft", "reply": "", "abilities": [], "job": "j2"}}
    html = _run("viewBlueprint()", p, {"bpSel": "@ability", "bpAbDrafts": drafts})
    assert "AI가 제안한 능력 일정" in html and "AI가 뽑은 줄" in html and "AI가 짠 줄" in html and "제안한 줄이 없어요" in html
    assert "2화 「기척이 사라진다」" in html and "조건: 첫 위기" in html and html.count('data-action="bpAbDraftUse"') == 1
    assert html.count('<span class="chip warn">도감에 없음</span>') == 1 and "스킬 도감에 없는 이름이 1줄 있어요" in html  # 질주만 (다른 이름 · 띄어쓰기는 잇는다)
    assert html.count('<span class="chip warn">이미 있음</span>') == 1
    assert _run("bpAbPicks(S.project.blueprint, data.extra.rows)", p, {"rows": rows}) == [True, False, True]  # 이미 적은 같은 줄만 고르지 않는다
    assert _run("pendingShown({ kind: 'blueprint_ability', id: 'j1', result: { character: 'a' } })", p, {"bpAbDrafts": drafts}) is True
    assert _run("pendingShown({ kind: 'blueprint_ability_draft', id: 'old', result: { character: 'a' } })", p, {"bpAbDrafts": drafts}) is False  # 새 제안이 자리를 바꿨다
    assert _run("pendingShown({ kind: 'blueprint_ability', id: 'j9', result: { character: 'd' } })", p, {"bpAbDrafts": drafts}) is False
    got = _run("(applyJobResult({ id: 'j3', kind: 'blueprint_ability_draft', status: 'done', result: { character: 'd', abilities: [], start: 1, end: 9, mode: 'draft' } }), S.bpAbDrafts.d.job)", p, {"bpAbDrafts": {}})
    assert got == "j3"
    assert _run("JOB_LINK.blueprint_ability({ project: 't', target: 'a' })", p) == "#/p/t/blueprint/%40ability"
    assert sorted(_run("PENDING_KINDS", p)) == sorted(__import__("canon.web", fromlist=["x"]).PENDING_KINDS)


@needs_node
def test_overview_opens_without_relationships():
    p = _proj()
    p.relationships, p.blueprint.milestones, p.blueprint.ladders = [], [], []
    html = _run("viewBlueprint()", p)
    assert "관계가 아직 없어요" in html and 'id="bp-growth"' in html


def _many() -> Project:
    """배열 차례가 화 차례와 다른 이정표 다섯 줄 (실제 작품에서 AI 제안을 두 번 더한 모양)."""
    p = _proj()
    p.blueprint.milestones = [Milestone(id=f"ms-{k}", source="a", target="j", from_ep=k, to_ep=k + 5, label=f"줄{k}") for k in (30, 65, 175, 360, 155)]
    return p


@needs_node
def test_rows_have_edit_and_delete_and_edit_list_follows_episode_order():
    p = _many()
    html = _run("viewBlueprint()", p, {"bpSel": "a~j"})
    assert 'data-action="bpRowEdit" data-arg="milestones.0"' in html and 'data-action="bpRowDel" data-arg="ladders.0.rungs.0"' in html
    assert 'id="bp-band"' in html and 'data-action="bpClear"' in html
    card = "(S.bpEdit = { card: 'ms', key: 'a~j', data: JSON.parse(JSON.stringify(S.project.blueprint)), orig: '' }, viewBlueprint())"
    html = _run(card, p, {"bpSel": "a~j"})
    order = [html.index(f'data-bp="milestones.{i}.from_ep"') for i in (0, 1, 4, 2, 3)]  # 30 · 65 · 155 · 175 · 360화
    assert order == sorted(order)
    assert '<textarea class="bp-text" rows="2" data-bp="milestones.0.label"' in html  # 긴 라벨이 잘리지 않게 여러 줄 칸


@needs_node
def test_row_edit_opens_only_that_row():
    p = _many()
    row = "(S.bpEdit = { card: 'ms', key: 'a~j', data: JSON.parse(JSON.stringify(S.project.blueprint)), orig: '', row: 'milestones.4' }, viewBlueprint())"
    html = _run(row, p, {"bpSel": "a~j"})
    assert 'data-bp="milestones.4.label"' in html and 'data-bp="milestones.0.label"' not in html
    assert html.count('data-action="bpSave"') == 1 and "줄30" in html
    assert 'data-action="bpRowEdit" data-arg="milestones.0"' not in html  # 같은 카드에서 한 줄을 고치는 동안은 줄 버튼을 숨긴다
    assert 'data-action="bpRowEdit" data-arg="ladders.0.rungs.0"' in html  # 다른 카드의 줄 버튼은 그대로
    html = _run("(S.bpEdit = { card: 'ladder', key: 'a~j', data: JSON.parse(JSON.stringify(S.project.blueprint)), orig: '', row: 'ladders.0.rungs.0' }, viewBlueprint())", p, {"bpSel": "a~j"})
    assert 'data-bp="ladders.0.rungs.0.label"' in html and 'data-action="bpRungMove"' in html and 'data-action="bpRungDel"' not in html


@needs_node
def test_text_saves_as_one_line():
    p = _proj()
    got = _run("(S.bpEdit = { card: 'ms', key: 'a~j', data: JSON.parse(JSON.stringify(S.project.blueprint)), orig: '' }, bpSet('milestones.0.label', '첫 줄\\n  둘째 줄'), bpSet('milestones.0.to_ep', '12'), S.bpEdit.data.milestones[0])", p)
    assert got["label"] == "첫 줄 둘째 줄" and got["to_ep"] == 12


@needs_node
def test_draft_marks_overlaps_and_leaves_them_unpicked():
    p = _proj()
    p.blueprint.milestones[0].from_ep, p.blueprint.milestones[0].to_ep = 30, 35
    draft = {"a": "a", "b": "j", "start": 1, "end": 600, "mode": "draft", "reply": "",
             "milestones": [{"source": "a", "target": "j", "from_ep": 35, "to_ep": 40, "stage": "경계", "label": "의심", "trigger": "", "evidence": []},
                            {"source": "j", "target": "a", "from_ep": 35, "to_ep": 40, "stage": "", "label": "반대 방향", "trigger": "", "evidence": []},
                            {"source": "a", "target": "j", "from_ep": 90, "to_ep": 95, "stage": "", "label": "새 줄", "trigger": "", "evidence": []}],
             "rungs": [{"label": "스침 ", "parts": [], "acts": [], "layer": "", "places": [], "lead": "", "note": "", "from_ep": 50, "to_ep": 50, "evidence": []},
                       {"label": "포옹", "parts": [], "acts": [], "layer": "옷 위", "places": [], "lead": "", "note": "", "from_ep": 3, "to_ep": 4, "evidence": []},
                       {"label": "입맞춤", "parts": [], "acts": [], "layer": "맨살", "places": [], "lead": "", "note": "", "from_ep": 2, "to_ep": 2, "evidence": []}]}
    got = _run("(viewBlueprint(), [S.bpDraft.pickMs, S.bpDraft.pickRungs])", p, {"bpSel": "a~j", "bpDraft": draft})
    assert got == [[False, True, True], [False, False, True]]  # 끝 화가 닿는 범위(30~35 · 35~40), 비슷한 라벨, 범위가 겹치고 겹이 같은 칸
    html = _run("viewBlueprint()", p, {"bpSel": "a~j", "bpDraft": draft})
    assert html.count("이미 있음") == 3 and "30~35화 경계 정체를 안다" in html and "1. 1~3화 스침" in html


@needs_node
def test_undo_note_only_on_its_page():
    p = _proj()
    undo = {"bpUndo": {"name": "t", "key": "a~j", "before": "{}", "after": "{}", "msg": "아영 ↔ 지훈의 여정을 비웠어요"}}
    assert 'data-action="bpUndo"' in _run("viewBlueprint()", p, {"bpSel": "a~j", **undo})
    assert 'data-action="bpUndo"' not in _run("viewBlueprint()", p, {"bpSel": "a~d", **undo})
    assert 'data-action="bpUndo"' not in _run("viewBlueprint()", p, {"bpSel": "a~j", "bpUndo": {**undo["bpUndo"], "name": "other"}})


@needs_node
def test_ability_edit_list_follows_view_order():
    p = _proj()
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="a", ability="은신", from_ep=50, to_ep=60),
                                 AbilityPlan(id="ap-2", character="j", ability="추적", from_ep=1, to_ep=2),
                                 AbilityPlan(id="ap-3", character="a", ability="도약", from_ep=5, to_ep=8)]
    html = _run("(S.bpEdit = { card: 'ap', key: '@ability', data: JSON.parse(JSON.stringify(S.project.blueprint)), orig: '' }, viewBlueprint())", p, {"bpSel": "@ability"})
    order = [html.index(f'data-bp="ability_plans.{i}.ability"') for i in (1, 2, 0)]  # 인물 목록 차례(지훈, 아영), 그 안에서 화 차례
    assert order == sorted(order)
    html = _run("viewBlueprint()", p, {"bpSel": "@ability"})
    assert 'data-action="bpRowDel" data-arg="ability_plans.2"' in html
