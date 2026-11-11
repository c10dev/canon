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
    assert "여정 짜기" not in _run("viewBlueprint()", p)  # 개요 관계 줄은 쌍 이름 링크만 (11a)
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
    drafts = {"a|extract": {"character": "a", "start": 1, "end": 600, "mode": "extract", "reply": "세 줄을 뽑았어요.", "abilities": rows, "job": "j1"},
              "j|draft": {"character": "j", "start": 1, "end": 120, "mode": "draft", "reply": "", "abilities": [], "job": "j2"}}
    html = _run("viewBlueprint()", p, {"bpSel": "@ability", "bpAbDrafts": drafts})
    assert "AI가 제안한 능력 일정" in html and "AI가 뽑은 줄" in html and "AI가 짠 줄" in html and "제안한 줄이 없어요" in html
    assert "2화 「기척이 사라진다」" in html and "조건: 첫 위기" in html and html.count('data-action="bpAbDraftUse"') == 1
    assert html.count('<span class="chip warn">도감에 없음</span>') == 1 and "스킬 도감에 없는 이름이 1줄 있어요" in html  # 질주만 (다른 이름 · 띄어쓰기는 잇는다)
    assert html.count('<span class="chip warn">이미 있음</span>') == 1
    assert _run("bpAbPicks(S.project.blueprint, data.extra.rows)", p, {"rows": rows}) == [True, False, True]  # 이미 적은 같은 줄만 고르지 않는다
    assert _run("pendingShown({ kind: 'blueprint_ability', id: 'j1', result: { character: 'a', mode: 'extract' } })", p, {"bpAbDrafts": drafts}) is True
    assert _run("pendingShown({ key: 'blueprint_ability:1:a', kind: 'blueprint_ability', id: 'j1', ep: 1 })", p, {"bpAbDrafts": drafts}) is True  # 막 끝난 작업의 기록은 result 가 없다
    assert _run("pendingShown({ kind: 'blueprint_ability', id: 'old', result: { character: 'a', mode: 'extract' } })", p, {"bpAbDrafts": drafts}) is False  # 새 제안이 자리를 바꿨다
    assert _run("pendingShown({ kind: 'blueprint_ability_draft', id: 'j9', result: { character: 'a', mode: 'draft' } })", p, {"bpAbDrafts": drafts}) is False  # 같은 인물의 짠 제안은 다른 자리다
    arrive = "applyJobResult({ id: 'j3', kind: 'blueprint_ability_draft', status: 'done', result: { character: 'd', abilities: [], start: 1, end: 9, mode: 'draft' } })"
    assert _run(f"(delete S.bpAbDrafts, {arrive}, S.bpAbDrafts['d|draft'].job)", p) == "j3"  # 자리가 아직 없어도 받는다
    assert _run(f"({arrive}, Object.keys(S.bpAbDrafts).sort())", p, {"bpAbDrafts": drafts}) == ["a|extract", "d|draft", "j|draft"]
    assert _run("(actions.bpAbDraftPick('a|extract|0'), S.bpAbDrafts['a|extract'].picks)", p, {"bpAbDrafts": {"a|extract": {**drafts["a|extract"], "picks": [True, False, True]}}}) == [False, False, True]
    assert [x["from_ep"] for x in _run("bpAbUnique([...data.extra.rows, { ...data.extra.rows[2], ability: '질 주', from_ep: 30 }])", p, {"rows": rows})] == [2, 6, 9]  # 묶음끼리 같은 줄은 앞의 것만
    assert 'data-action="wholePick" data-arg="w|0"' in _run("bpAbDraftRows(data.extra.rows, [true, true, true], 'w', true, 'wholePick')", p, {"rows": rows})  # 11b 가 자기 동작으로 쓴다
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


@needs_node
def test_ability_codex_drafts_and_make_button():
    """도감 초안 묶음 · 고르기 · 보낼 초안, 능력 일정 줄의 '도감에 만들기' (docs/blueprint/specs/13-ability-codex.md)."""
    from canon.schema import Ability
    p = _proj()
    p.abilities = [Ability(id="ab-1", name="은신")]
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="a", ability="은신", grade="Lv2", from_ep=5, to_ep=8),
                                 AbilityPlan(id="ap-2", character="a", ability="질주", from_ep=9, to_ep=12)]
    html = _run("viewBlueprint()", p, {"bpSel": "@ability"})
    assert html.count('data-action="abNew"') == 1 and 'data-arg="|질주"' in html  # 도감에 없는 줄(ap-2, linked false)에만
    rows = [{"character": "a", "ability": "질주", "grade": "", "condition": "", "from_ep": 9, "to_ep": 12, "evidence": []},
            {"character": "a", "ability": "비행", "grade": "", "condition": "", "from_ep": 20, "to_ep": 21, "evidence": []}]
    codex = [{"name": "질주", "stat": "스킬", "description": "", "effect": "빨리 달린다", "cost": "숨이 찬다", "grades": [{"grade": "Lv2", "effect": ""}]},
             {"name": "은 신", "stat": "", "description": "", "effect": "그새 도감에 생김", "cost": "", "grades": []},
             {"name": "비행", "stat": "", "description": "난다", "effect": "", "cost": "", "grades": []}]
    drafts = {"a|draft": {"character": "a", "start": 1, "end": 120, "mode": "draft", "reply": "", "abilities": rows, "codex": codex, "job": "j1"},
              "j|draft": {"character": "j", "start": 1, "end": 120, "mode": "draft", "reply": "", "abilities": [], "job": "j2"}}
    html = _run("viewBlueprint()", p, {"bpSel": "@ability", "bpAbDrafts": drafts})
    assert "도감 초안" in html and "효과: 빨리 달린다" in html and "대가: 숨이 찬다" in html and "효과: 난다" in html and "등급 1" in html
    assert "그새 도감에 생김" not in html and html.count('data-action="bpAbCodexPick"') == 2  # 도감에 있는 이름은 숨긴다
    assert "고른 도감 초안은 줄과 함께 도감에 만들어요" in html
    picked = _run("(viewBlueprint(), actions.bpAbCodexPick('a|draft|2'), bpAbCodexPicked(Object.values(S.bpAbDrafts)).map((c) => c.name))", p, {"bpSel": "@ability", "bpAbDrafts": drafts})
    assert picked == ["질주"]  # 기본으로 고르고, 끈 것과 도감에 있는 이름은 보내지 않는다


@needs_node
def test_whole_band_lanes_and_crowd_border():
    p = _proj()
    p.relationships.append(Relationship(a="a", b="d", type="친구"))
    view = {"firsts": [{"pair": "a~j", "axis": "단계", "value": "경계", "from_ep": 1, "to_ep": 15, "id": "ms-1", "source": "a", "target": "j", "crowd": ["a~d"]},
                       {"pair": "a~d", "axis": "단계", "value": "경계", "from_ep": 10, "to_ep": 12, "id": "ms-9", "source": "d", "target": "a", "crowd": ["a~j"]},
                       {"pair": "a~j", "axis": "겹", "value": "옷 위", "from_ep": 1, "to_ep": 3, "id": "cr-1", "source": "j", "target": "a", "crowd": []}]}
    html = _run("(S.bp = { ...S.bp, ...data.extra.view }, viewBlueprint())", p, {"view": view})
    whole = html[html.index('id="bp-whole"'):]
    whole = whole[:whole.index("</section>")]
    assert "전체 띠" in whole and "아영 ↔ 지훈" in whole and "아영 ↔ 다은" in whole  # 빈 쌍도 한 줄
    assert "아영 → 지훈 경계 · 아영 ↔ 다은와 겹침" in whole and "접촉 옷 위" in whole
    assert whole.count("bp-crowd") == 2
    assert '<span class="small">경고</span><b>2</b>' in html  # 몰림은 경고 수에 넣지 않는다 (VIEW 의 경고 둘만)
    assert 'class="bp-pair"' in html and "여정 짜기" not in html


@needs_node
def test_whole_band_hidden_without_firsts_or_plans():
    p = _proj()
    assert 'id="bp-whole"' not in _run("viewBlueprint()", p)  # VIEW 에 firsts 가 없고 능력 일정도 없다
    p.blueprint.ability_plans = [AbilityPlan(id="ap-1", character="a", ability="은신", grade="Lv2", from_ep=5, to_ep=8)]
    html = _run("viewBlueprint()", p)
    assert 'id="bp-whole"' in html and "은신 Lv2" in html.split('id="bp-whole"')[1]


def _whole_draft() -> dict:
    return {"start": 1, "end": 600, "part": 0, "mode": "whole", "picked": ["a~j", "a~d"], "reply": "엇갈려 놓았어요.",
            "spotlight": [{"from_ep": 1, "to_ep": 20, "focus": ["a~j"], "note": "지훈 먼저"}],
            "pairs": [{"a": "a", "b": "j", "milestones": [{"source": "a", "target": "j", "from_ep": 2, "to_ep": 9, "stage": "경계", "label": "정체를 안다", "trigger": "", "evidence": []},
                                                         {"source": "j", "target": "a", "from_ep": 20, "to_ep": 25, "stage": "호감", "label": "끌린다", "trigger": "", "evidence": []}],
                       "rungs": [{"label": "손등", "parts": [], "acts": [], "layer": "맨살", "places": [], "lead": "", "note": "", "from_ep": 5, "to_ep": 5, "evidence": []}]},
                      {"a": "a", "b": "d", "milestones": [], "rungs": []}],
            "abilities": [{"character": "a", "ability": "해금", "grade": "1단계", "condition": "첫 위기", "from_ep": 3, "to_ep": 4, "evidence": []}],
            "firsts": [{"pair": "a~j", "axis": "단계", "value": "호감", "from_ep": 20, "to_ep": 25, "id": "+ms-0-1", "source": "j", "target": "a", "new": True}],
            "crowd": [{"pairs": ["a~j", "a~d"], "text": "지훈 → 아영(20~25화)와 다은 → 아영(20~30화)가 같은 화 범위에 호감 단계에 처음 닿아요."}],
            "mesh": []}


@needs_node
def test_whole_ai_card_opens_from_pairs_card():
    p = _proj()
    html = _run("viewBlueprint()", p)
    assert 'data-action="bpWholeToggle"' in html and 'aria-expanded="false"' in html and 'id="bp-whole-ai"' not in html
    html = _run("viewBlueprint()", p, {"bpWholeOpen": True})
    assert 'id="bp-whole-ai"' in html and html.count('class="bp-whole-pair"') == 2 and 'data-action="bpWholeAI"' in html


@needs_node
def test_whole_draft_card_groups_picks_and_pending():
    p = _proj()
    html = _run("viewBlueprint()", p, {"bpWhole": _whole_draft()})
    card = html[html.index('id="bp-whole-draft"'):]
    assert "AI가 짠 전체 설계도" in card and "같은 화 범위에 호감 단계" in card and "지훈 먼저" in card
    assert "아영 ↔ 지훈" in card and "아영 ↔ 다은" in card and "새 줄이 없어요." in card
    assert 'data-arg="a~j|ms|0" aria' in card and 'data-arg="a~j|ms|1" checked' in card  # 이미 있는 줄과 겹친 줄만 고르지 않는다
    assert card.count('class="chip warn">이미 있음') >= 1  # 이미 있는 1~15화 이정표와 같은 방향 · 겹치는 범위
    assert "bp-new" in card and 'data-action="bpWholeAbPick"' in card and 'data-action="bpWholeUse"' in card
    assert _run("pendingShown({ kind: 'blueprint_whole' })", p, {"bpWhole": _whole_draft()}) is True
    expr = """(() => { render = () => {}; S.bpWhole = data.extra.d; bpWholePicks(S.bpWhole); actions.bpWholePick('a~j|all'); const a = JSON.stringify(S.bpWhole.pick['a~j']);
      actions.bpWholePick('a~j|all'); return [a, JSON.stringify(S.bpWhole.pick['a~j'])]; })()"""
    on, off = _run(expr, p, {"d": _whole_draft()})
    assert on == '{"ms":[true,true],"rungs":[true]}' and off == '{"ms":[false,false],"rungs":[false]}'
