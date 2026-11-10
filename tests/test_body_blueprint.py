"""설계도에서 신체 특징 가져오기 (docs/blueprint/specs/10-body-suggest.md). LLM 비용 없음 (mock · 가짜 응답)."""
import json

import pytest

from canon import blueprint, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import BlueprintBodyDraft, BodyFeatureDraft, BodySuggestion, ContactLadder, ContactRung, Milestone

from .test_blueprint import _body_project


class _Fake:
    """정해 둔 답을 돌려주고 부른 횟수를 센다."""
    def __init__(self, answer: BlueprintBodyDraft | None = None):
        self.answer, self.calls = answer or BlueprintBodyDraft(), []

    def json(self, system, prompt, schema, hint=None):
        self.calls.append((prompt, schema, hint))
        return self.answer


def _project():
    """hero ↔ ally 사다리 칸 메모와 hero → ally 이정표 라벨에 ally 의 신체 특징을 적은 작품. ally 에는 이미 특징 둘이 있다."""
    p = _body_project()
    lad = p.blueprint.ladders[0]
    lad.rungs[1].note = "서윤이 앨리의 왼쪽 옆구리 흉터를 처음 본다"
    p.blueprint.milestones = [Milestone(source="hero", target="ally", from_ep=6, to_ep=7, label="등의 나비 문신을 보고 정체를 안다", trigger="샤워실")]
    return p


def test_body_lines_cover_both_sides_and_name_the_partner():
    p = _project()
    names = {c.id: c.name for c in p.characters}
    lines, cut = blueprint.body_lines(p, "ally")
    assert cut == 0 and len(lines) == 4  # 이정표 1줄 + 이름이 있는 사다리 칸 3줄
    assert lines[0] == f"- [6~7화] 관계 이정표 {names['hero']} → {names['ally']}: 등의 나비 문신을 보고 정체를 안다 (계기: 샤워실)"
    assert f"접촉 사다리 {names['hero']} ↔ {names['ally']} 칸 2. 가슴 (맨살 · 서윤이 앨리의 왼쪽 옆구리 흉터를 처음 본다)" in lines[2]
    assert blueprint.body_lines(p, "hero")[0] == lines  # 보는 쪽 · 쌍의 다른 쪽도 같은 줄을 받는다
    p.blueprint.milestones[0].label = p.blueprint.milestones[0].trigger = ""
    for r in p.blueprint.ladders[0].rungs:
        r.label = r.note = ""
    assert blueprint.body_lines(p, "ally") == ([], 0)  # 작가 글이 없는 줄은 뺀다


def test_body_lines_budget():
    p = _project()
    p.blueprint.ladders[0].rungs = [ContactRung(label=f"칸 {i}", from_ep=1, to_ep=1) for i in range(blueprint.BODY_LINES_MAX + 5)]
    lines, cut = blueprint.body_lines(p, "ally")
    assert len(lines) == blueprint.BODY_LINES_MAX and cut == 6  # 이정표 1줄 + 칸 65줄 가운데 60줄
    assert "(재료 상한을 넘어 뺀 줄 6개)" in prompts.body_blueprint_prompt(p, "ally", lines, cut, False)


def test_no_lines_means_no_call():
    p = _body_project()
    for r in p.blueprint.ladders[0].rungs:
        r.label = ""
    llm = _Fake()
    s = pipeline.suggest_body_from_blueprint(llm, p, "ally")
    assert llm.calls == [] and s.features == "" and s.build == "" and "없어요" in s.note
    with pytest.raises(KeyError):
        pipeline.suggest_body_from_blueprint(llm, p, "nobody")


def test_mock_finds_features_and_appends_to_existing():
    p = _project()
    s = pipeline.suggest_body_from_blueprint(MockLLM(), p, "ally")
    assert s.features == "함몰유두, 왼쪽 쇄골 아래 점, 나비 문신, 옆구리 흉터"  # 지금 값 뒤에 이어 적용이 지금 특징을 지우지 않는다
    assert s.height == s.weight == s.measurements == ""
    assert "옆구리 흉터: 「옆구리 흉터」" in s.evidence and s.note
    assert p.characters[[c.id for c in p.characters].index("ally")].body.features == "함몰유두, 왼쪽 쇄골 아래 점"  # 저장하지 않는다


def test_cleaning_drops_unquoted_known_and_numbers():
    p = _project()
    ans = BlueprintBodyDraft(features=[BodyFeatureDraft(text="옆구리 흉터", quote="왼쪽 옆구리 흉터"),
                                       BodyFeatureDraft(text="쇄골 아래 점", quote="옆구리"),  # 이미 있는 특징 (띄어쓰기 상관없이 겹침)
                                       BodyFeatureDraft(text="배꼽 피어싱", quote="배꼽 피어싱"),  # 설계도에 없는 구절
                                       BodyFeatureDraft(text="왼쪽 옆구리 흉터", quote="옆구리 흉터"),  # 같은 답 안에서 겹침
                                       BodyFeatureDraft(text="나비 문신", quote="")],  # 근거 없음
                             build="등이 넓다", build_quote="등이 넓다", note="찾았어요")
    llm = _Fake(ans)
    s = pipeline.suggest_body_from_blueprint(llm, p, "ally")
    assert s.features == "함몰유두, 왼쪽 쇄골 아래 점, 옆구리 흉터" and s.build == ""  # 체형 근거가 설계도에 없다
    assert s.evidence == ["옆구리 흉터: 「왼쪽 옆구리 흉터」"]
    prompt, schema, hint = llm.calls[0]
    assert schema is BlueprintBodyDraft and hint["character"] == "ally" and len(hint["lines"]) == 4
    ans.features, ans.build, ans.build_quote = [], "마른 편", "옆구리"
    assert pipeline.suggest_body_from_blueprint(_Fake(ans), p, "ally").build == ""  # 지금 체형과 같으면 내지 않는다
    ans.build = "옆구리가 단단하다"
    s = pipeline.suggest_body_from_blueprint(_Fake(ans), p, "ally")
    assert s.build == "옆구리가 단단하다" and s.features == ""  # 새 특징이 없으면 특징 칸을 내지 않는다


def test_prompt_order_and_minor():
    p = _project()
    lines, cut = blueprint.body_lines(p, "ally")
    text = prompts.body_blueprint_prompt(p, "ally", lines, cut, False)
    ally = next(c for c in p.characters if c.id == "ally")
    assert text.index("# 인물") < text.index("# 설계도 줄") < text.index("요구사항:")  # 바뀌지 않는 블록이 앞, 요청이 맨 뒤
    assert "지금 신체 프로필 특징: 함몰유두, 왼쪽 쇄골 아래 점" in text and "84-58-86" not in text  # 쓰리사이즈는 넣지 않는다
    hero = next(c for c in p.characters if c.id == "hero")
    assert f"{hero.name}의 몸에 대한 것은 적지 않습니다" in text and f"{ally.name}의 몸에 대한 것만" in text
    assert "미성년" not in text and "미성년이라 몸매를" in prompts.body_blueprint_prompt(p, "ally", lines, cut, True)
    schema = json.dumps(BlueprintBodyDraft.model_json_schema(), ensure_ascii=False)
    assert "measurements" not in schema and "height" not in schema  # 숫자 칸은 응답 형식에 없다
    assert "evidence" not in json.dumps(BodySuggestion.model_json_schema(), ensure_ascii=False)  # 근거는 서버가 채운다
    assert prompts.KINDS["body_blueprint"].request == "body_blueprint_prompt"


def test_minor_gets_no_measurements():
    p = _project()
    ally = next(c for c in p.characters if c.id == "ally")
    ally.age = "17세"
    s = pipeline.suggest_body_from_blueprint(MockLLM(), p, "ally")
    assert s.measurements == "" and "옆구리 흉터" in s.features


def test_web_endpoint_and_job_do_not_save(client):
    from .test_ai_jobs import _run, _saved
    from .test_plot_chat import _project as _web_project
    from canon import store
    _web_project(client)
    p = store.load("lh")
    p.blueprint.ladders = [ContactLadder(a="hero", b="ally", rungs=[ContactRung(label="손목", note="손목의 화상 자국을 본다", from_ep=1, to_ep=1)])]
    store.save("lh", p)
    before = _saved("lh")
    s = client.post("/api/projects/lh/characters/ally/body/blueprint").json()
    assert "화상 자국" in s["features"] and s["evidence"]
    assert client.post("/api/projects/lh/characters/nobody/body/blueprint").status_code == 400
    j = _run(client, "lh", {"kind": "char_body_bp", "target": "ally"})
    assert j["target"] == "ally" and "화상 자국" in j["result"]["features"]
    assert _saved("lh") == before  # 작가가 칸에서 골라 적용하고 저장해야 들어간다


# ---------- 화면 (static/cast.js · blueprint.js · research.js) ----------

from .jsvm import STATIC, needs_node, run_js  # noqa: E402

FILES = __import__("re").findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


@needs_node
def test_js_has_lines_matches_server():
    """'설계도에서 가져오기'를 보일지 정하는 bodyBpHas 가 서버 blueprint.body_lines 와 같은 인물에서 참이다."""
    p = _project()
    cases = []
    for edit in (lambda p: None,
                 lambda p: setattr(p.blueprint.milestones[0], "label", ""),
                 lambda p: [setattr(r, "label", "") or setattr(r, "note", " ") for r in p.blueprint.ladders[0].rungs],
                 lambda p: setattr(p.blueprint.milestones[0], "trigger", "")):
        edit(p)
        cases.append(json.loads(p.model_dump_json()))
    ids = ["hero", "ally", "nobody"]
    got = run_js(FILES, "data.cases.map((p) => data.ids.map((id) => bodyBpHas(p, id)))", {"cases": cases, "ids": ids})
    from canon.schema import Project
    want = [[bool(blueprint.body_lines(Project.model_validate(c), i)[0]) for i in ids] for c in cases]
    assert got == want and want[0] == [True, True, False] and want[-1] == [False, False, False]


@needs_node
def test_js_button_card_and_blueprint_row():
    p = _project()
    ally = next(c for c in p.characters if c.id == "ally")
    sug = {"height": "", "weight": "", "build": "", "measurements": "", "features": "함몰유두, 왼쪽 쇄골 아래 점, 옆구리 흉터",
           "note": "찾았어요", "evidence": ["옆구리 흉터: 「옆구리 흉터」"]}
    got = run_js(FILES, """(() => {
      S.project = data.project; S.name = 'lh';
      const c = S.project.characters.find((x) => x.id === 'ally');
      const fields = bodyFields(c, 'characters.1');
      JOB_RESULT.char_body_bp({ kind: 'char_body_bp', target: 'ally', result: data.sug, label: '앨리 설계도 신체 특징' });
      const card = bodySuggestCard(c);
      S.bp = { blueprint: S.project.blueprint };
      const row = bpBodyRow('ally~hero');
      S.project.blueprint = { milestones: [], ladders: [], note: '' };
      S.bp = { blueprint: S.project.blueprint };
      return { fields, card, row, none: bodyFields(c, 'characters.1'), noRow: bpBodyRow('ally~hero'),
               btns: JOB_BTNS.bodyBpAI('ally'), screen: SCREEN_ONLY_JOBS.has('char_body_bp'), pages: JOB_PAGES.char_body_bp };
    })()""", {"project": json.loads(p.model_dump_json()), "sug": sug})
    assert 'data-action="bodyBpAI"' in got["fields"] and "설계도에서 가져오기" in got["fields"]
    assert 'data-action="bodyBpAI"' not in got["none"]  # 설계도에 이 인물의 글이 없으면 버튼을 두지 않는다
    assert "설계도에서 찾은 특징" in got["card"] and "근거: 옆구리 흉터: 「옆구리 흉터」" in got["card"]
    assert '<span class="before">함몰유두, 왼쪽 쇄골 아래 점</span>' in got["card"]  # 지금 값과 견준다
    assert 'value="features" checked' not in got["card"]  # 지금 값이 있는 칸은 기본으로 고르지 않는다 (작가가 골라야 바뀐다)
    assert got["row"].count('data-action="bpBodyGo"') == 2 and f"{ally.name} 신체 프로필" in got["row"] and got["noRow"] == ""
    assert got["btns"] == ["char_body_bp", "ally"] and got["screen"] and got["pages"] == ["cast"]
