"""집필 경로의 큐 시트 (Episode.cue_sheet, cue.on · ep_basis · stale · set_episode · ep_view, prompts.episode_prompt 의 cue_write_block,
웹 작업 write · cues 와 …/cue-sheet, 자동 집필 _cues, static/cue.js 의 cueCard · cuePanel)."""
import contextlib
import io
import json

import pytest
from fastapi.testclient import TestClient

from canon import autorun, cue, jobs, pipeline, prompts, store
from canon.cli import main
from canon.mock import MockLLM
from canon.schema import Cue, CueLine, CueSheetDraft, StoryTime

from .jsvm import dump, needs_node, run_js
from .test_cue import FILES, _labels
from .test_web import _wait


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    """단편 6화 작품, 플롯 모두 확정. 큐 시트는 켠다 (단편 기본은 끔)."""
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
    p = store.load("demo")
    p.settings.cue_sheet = True
    store.save("demo", p)
    yield "demo"
    jobs.draining.clear()


def _sheet(line="등불을 끄지 마."):
    return CueSheetDraft(key="불안", cadence="half", cues=[
        Cue(function="T", tension=2, beat="등대에 오른다", length=1500),
        Cue(function="D", tension=5, voice="dialogue", beat="불을 두고 다툰다", lines=[CueLine(speaker="hero", text=line)], length=1500)])


def test_on_defaults_by_form(demo):
    p = store.load(demo)
    p.settings.cue_sheet = None
    assert not cue.on(p)  # 단편 기본 끔
    p.meta.form = "serial"
    assert cue.on(p)  # 장편 기본 켬
    p.settings.cue_sheet = False
    assert not cue.on(p)


def test_prompt_puts_sheet_last_and_score_condition_matches(demo):
    p = store.load(demo)
    plain = prompts.episode_prompt(p, 1)
    cue.set_episode(p, 1, _sheet())
    full = prompts.episode_prompt(p, 1)
    # 큐 시트는 쓰기 요청 맨 끝 (앞부분은 그대로라 캐시 순서를 깨지 않는다)
    assert full.startswith(plain) and full[len(plain):].lstrip().startswith("# 이번 화 큐 시트")
    assert "«등불을 끄지 마.»" in full and "한 번에 씁니다" in full
    assert "편성: 대사(" in full and "40% 넘게" in full  # 한 번에 쓰기도 편성 뜻을 받는다 (큐마다 지시가 없어서)
    assert "약 1500자, 그중 따옴표 안 대사 600자 이상]" in full  # 대사 큐는 대사 글자 수를 숫자로
    assert full.count("따옴표 안 대사") == 2  # 편성 뜻 한 줄 + 대사 큐 하나 (행동 큐에는 붙이지 않는다)
    assert prompts.episode_prompt(p, 1, use_cues=False) == plain
    # 실험의 '큐 시트를 주고 한 번에' 조건과 같은 글이다
    assert prompts.cue_score_prompt(p, 1, p.episode(1).cue_sheet) == full
    # 작업지시서 · 다시 생성도 같은 글을 쓴다 (다시 생성 요청은 그 뒤)
    assert full in prompts.episode_brief(p, 1)
    # 실험 사본은 화의 큐 시트를 지운다 (조건 oneshot 에 섞이지 않게)
    assert cue.before(p, 1).episode(1).cue_sheet is None and p.episode(1).cue_sheet is not None


def test_set_episode_basis_stale_and_view(demo):
    p = store.load(demo)
    cue.set_episode(p, 1, pipeline.make_cue_sheet(MockLLM(), p, 1), by="ai")
    s = p.episode(1).cue_sheet
    assert s.made_by == "ai" and s.basis == cue.ep_basis(p, 1) and not cue.stale(p, 1)
    cue.set_episode(p, 1, _sheet())  # 작가가 고치면 AI + 작가
    assert p.episode(1).cue_sheet.made_by == "both"
    p.episode(1).plot.events.append("새 사건")
    assert cue.stale(p, 1)  # 플롯이 바뀌었다
    with pytest.raises(ValueError):
        cue.set_episode(p, 1, CueSheetDraft(cues=[Cue()]))  # 빈 큐만
    p.episode(1).text = "바람이 불었다.\n\n\"등불을 끄지 마!\""
    v = cue.ep_view(p, 1)
    assert not v["stale"]  # 본문을 쓴 뒤에는 낡음을 보지 않는다
    assert (v["hit"], v["total"], v["missed"]) == (1, 1, [])
    cue.set_episode(p, 1, None)
    assert p.episode(1).cue_sheet is None


def test_web_write_makes_sheet_first_or_skips(demo):
    from canon import web

    c = TestClient(web.app)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 1})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2 and "큐 시트와" in r.json()["label"]
    assert _wait(c, r.json()["id"])["status"] == "done"
    e = store.load(demo).episode(1)
    assert e.cue_sheet and e.cue_sheet.made_by == "ai" and e.text
    said = [x.text for k in e.cue_sheet.cues for x in k.lines]
    assert said and all(x in e.text for x in said)  # 쓰기 요청에 큐 시트가 들어갔다 (mock 은 핵심 대사를 넣는다)
    v = c.get(f"/api/projects/{demo}/episodes/1/cue-sheet").json()
    assert v["on"] and v["hit"] == v["total"] == len(said)
    # 큐 시트 없이 쓰기: 만들지 않는다
    p = store.load(demo)
    p.episode(1).status = "finalized"
    store.save(demo, p)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 2, "cues": "none"})
    assert r.json()["total"] == 1
    assert _wait(c, r.json()["id"])["status"] == "done"
    assert store.load(demo).episode(2).cue_sheet is None and store.load(demo).episode(2).text


def test_web_job_put_board_delete_and_setting(demo):
    from canon import web

    c = TestClient(web.app)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "cues", "ep": 1})
    assert r.status_code == 200, r.text
    j = _wait(c, r.json()["id"])
    assert j["status"] == "done" and j["result"]["cues"] >= 1
    body = json.loads(_sheet().model_dump_json())
    out = c.put(f"/api/projects/{demo}/episodes/1/cue-sheet", json=body).json()
    got = next(e for e in out["episodes"] if e["plot"]["number"] == 1)["cue_sheet"]
    assert got["made_by"] == "both" and got["cues"][1]["lines"][0]["text"] == "등불을 끄지 마."
    out = c.post(f"/api/projects/{demo}/episodes/1/cue-sheet/board").json()
    got = next(e for e in out["episodes"] if e["plot"]["number"] == 1)["cue_sheet"]
    assert got["made_by"] == "board" and len(got["cues"]) == len(store.load(demo).episode(1).plot.events)
    assert c.delete(f"/api/projects/{demo}/episodes/1/cue-sheet").status_code == 200
    assert store.load(demo).episode(1).cue_sheet is None
    assert c.put(f"/api/projects/{demo}/cue-setting", json={"on": False}).json()["settings"]["cue_sheet"] is False
    # 끄면 쓰기가 큐 시트를 만들지 않는다
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 1})
    assert r.json()["total"] == 1
    assert _wait(c, r.json()["id"])["status"] == "done"


def test_autorun_makes_sheets_keeps_author_sheet_and_estimates(demo):
    p = store.load(demo)
    cue.set_episode(p, 2, _sheet("작가가 정한 말."))
    p.episode(2).cue_sheet.basis = "old"  # 낡은 작가 시트: 새로 만들지 않고 그대로 쓴다
    store.save(demo, p)
    est_on = autorun.estimate(p, 3, False, autorun.Policy())
    est_off = autorun.estimate(p, 3, False, autorun.Policy(cue_sheet=False))
    assert est_on["calls"]["plan"] == 2 and est_off["calls"]["plan"] == 0  # 2화는 이미 있어 1 · 3화만
    assert est_on["tokens_in"] > est_off["tokens_in"]
    run = autorun.start(demo, 3, False, autorun.Policy(hand_pick_opening=False, check=False), foreground=True)
    assert run.status == "done", run.reasons
    p = store.load(demo)
    assert p.episode(1).cue_sheet.made_by == "ai" and p.episode(3).cue_sheet.made_by == "ai"
    assert p.episode(2).cue_sheet.made_by == "author" and "작가가 정한 말." in p.episode(2).text
    assert any("큐 시트를 만든 뒤" in e.message for e in run.log)
    run = autorun.start(demo, 4, False, autorun.Policy(hand_pick_opening=False, check=False, cue_sheet=False), foreground=True)
    assert run.status == "done" and store.load(demo).episode(4).cue_sheet is None


def test_branch_drops_sheets_from_fork(demo):
    from canon import branches

    p = store.load(demo)
    for k in (1, 2, 3):
        cue.set_episode(p, k, _sheet())
    p.episode(1).text, p.episode(1).status = "앞 화.", "finalized"
    branches.fork(p, 2)
    assert p.episode(1).cue_sheet is not None
    assert p.episode(2).cue_sheet is None and p.episode(3).cue_sheet is None


@needs_node
def test_js_card_and_panel(demo):
    p = store.load(demo)
    cue.set_episode(p, 2, _sheet())
    p.episode(1).text, p.episode(1).status = "앞 화.", "finalized"
    p.episode(1).time = StoryTime(day=1)
    cue.set_episode(p, 1, _sheet())
    labels = {"candidates": [], "labs": [], "runs": [], **_labels(), "name": "demo"}
    got = run_js(FILES, """(() => {
      S.project = data.p; S.name = 'demo'; S.route = ['p', 'demo', 'write', '2'];
      S.cue = data.labels; S.cueViewSig = cueSig(2); S.cueViewData = { on: true, stale: true, hit: 0, total: 0, missed: [] };
      const card = cueCard(2, []);
      const edit = cueEd();
      const key = S.cueKey;
      S.cueSkip[cueKeyOf('ep', 3)] = true;
      const skip = cueWriteArg(3);
      S.cueViewSig = cueSig(1); S.cueViewData = { on: true, stale: false, hit: 0, total: 1, missed: ['등불을 끄지 마.'] };
      const panel = cuePanel(1);
      S.project.settings.cue_sheet = false;
      const off = cueCard(3, []);
      return { card, key, lines: edit.draft.cues[1].lines, skip, panel, off, none: cueWriteArg(2) };
    })()""", {"p": dump(p), "labels": labels})
    assert "큐 시트" in got["card"] and "cue-bars" in got["card"] and "큐 시트 고치기" in got["card"]
    assert "바뀌었어요" in got["card"] and "이번 화는 큐 시트 없이 쓰기" in got["card"]
    assert got["key"] == "ep:2:demo" and got["lines"][0]["text"] == "등불을 끄지 마."
    assert "AI가 지금 자료로 큐 시트를 새로 만들고" not in got["card"]  # 작가가 고친 시트는 낡아도 쓰기가 그대로 쓴다
    assert "큐 시트 고치기" in got["panel"] and "큐 시트 지우기" in got["panel"]  # 쓴 화도 다시 생성용 시트를 고친다
    assert got["skip"] == {"cues": "none"} and got["none"] == {}
    assert "핵심 대사 0/1" in got["panel"] and "본문에 없는 핵심 대사" in got["panel"]
    assert got["off"] == ""  # 끈 작품 · 시트 없는 화는 카드가 없다


def test_autorun_empty_remake_writes_without_stale_sheet(demo, monkeypatch):
    """낡은 AI 시트를 다시 받았는데 비어 오면 '큐 시트 없이 써요'대로 낡은 시트를 빼고 쓰고, 넣지 않았다고 적는다."""
    p = store.load(demo)
    cue.set_episode(p, 1, _sheet("옛 AI 대사."), by="ai")
    p.episode(1).cue_sheet.basis = "old"
    store.save(demo, p)
    monkeypatch.setattr(pipeline, "make_cue_sheet", lambda llm, p, n, **kw: _sheet().model_copy(update={"cues": []}))
    run = autorun.start(demo, 1, False, autorun.Policy(hand_pick_opening=False, check=False), foreground=True)
    assert run.status == "done", run.reasons
    e = store.load(demo).episode(1)
    assert any("비어 왔어요" in x.message for x in run.log)
    assert "옛 AI 대사." not in e.text and e.cue_sheet.skipped


def test_web_write_remakes_stale_ai_sheet_but_keeps_author_sheet(demo):
    """쓰기 작업은 낡은 AI · 뼈대 시트를 새로 만든다 (자동 집필 _cues 와 같은 규칙 cue.remake). 작가가 고친 시트는 그대로 쓴다."""
    from canon import web

    c = TestClient(web.app)
    p = store.load(demo)
    cue.set_episode(p, 1, _sheet("옛 AI 대사."), by="ai")
    p.episode(1).cue_sheet.basis = "old"
    cue.set_episode(p, 2, _sheet("작가가 정한 말."))
    p.episode(2).cue_sheet.basis = "old"
    store.save(demo, p)
    assert cue.remake(p, 1) and not cue.remake(p, 2) and cue.stale(p, 2)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 1})
    assert r.json()["total"] == 2 and "큐 시트와" in r.json()["label"]
    assert _wait(c, r.json()["id"])["status"] == "done"
    e = store.load(demo).episode(1)
    assert e.cue_sheet.basis != "old" and "옛 AI 대사." not in [x.text for k in e.cue_sheet.cues for x in k.lines]
    p = store.load(demo)
    p.episode(1).status = "finalized"
    store.save(demo, p)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 2})
    assert r.json()["total"] == 1
    assert _wait(c, r.json()["id"])["status"] == "done"
    e = store.load(demo).episode(2)
    assert e.cue_sheet.made_by == "author" and "작가가 정한 말." in e.text


def test_write_without_sheet_marks_skipped(demo):
    """'이번 화는 큐 시트 없이 쓰기'로 쓰면 시트에 skipped 를 적는다: 화면 값은 대사를 세지 않고, 다시 생성 · 검수 메모도 시트를 넣지 않는다."""
    from canon import web
    from canon.schema import RewriteRequest

    c = TestClient(web.app)
    p = store.load(demo)
    cue.set_episode(p, 1, _sheet())
    store.save(demo, p)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 1, "cues": "none"})
    assert r.json()["total"] == 1
    assert _wait(c, r.json()["id"])["status"] == "done"
    p = store.load(demo)
    assert p.episode(1).cue_sheet.skipped and "등불을 끄지 마." not in p.episode(1).text
    v = c.get(f"/api/projects/{demo}/episodes/1/cue-sheet").json()
    assert v["skipped"] and v["total"] == 0 and v["rows"] == []
    assert "# 이번 화 큐 시트" not in pipeline.rewrite_prompt(p, 1, RewriteRequest())
    assert "등대에 오른다" not in pipeline.memo_texts(p, 1)
    cue.set_episode(p, 1, _sheet("고친 말."))  # 본문이 있는 동안 작가가 고쳐도 지금 본문에 대한 사실은 그대로
    assert p.episode(1).cue_sheet.skipped
    store.save(demo, p)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 1})  # 큐 시트를 넣어 새로 쓰면 지운다
    assert _wait(c, r.json()["id"])["status"] == "done"
    p = store.load(demo)
    assert not p.episode(1).cue_sheet.skipped and "# 이번 화 큐 시트" in pipeline.rewrite_prompt(p, 1, RewriteRequest())


@needs_node
def test_js_keys_per_project_names_and_skipped_panel(demo):
    """고치는 큐 시트 · '없이 쓰기'는 작품마다 따로, 대사 칸은 인물 이름으로 읽고 쓴다, 없이 쓴 화의 패널."""
    p = store.load(demo)
    hero = next(ch for ch in p.characters if ch.id == "hero")
    cue.set_episode(p, 2, _sheet())
    p.episode(1).text, p.episode(1).status = "앞 화.", "finalized"
    cue.set_episode(p, 1, _sheet())
    p.episode(1).cue_sheet.skipped = True
    labels = {"candidates": [], "labs": [], "runs": [], **_labels(), "name": "demo"}
    got = run_js(FILES, """(() => {
      S.project = data.p; S.name = 'demo'; S.route = ['p', 'demo', 'write', '2'];
      S.cue = data.labels; S.cueViewSig = cueSig(2); S.cueViewData = { on: true, stale: false, hit: 0, total: 0, missed: [] };
      cueCard(2, []);
      cueEd().draft.cues[0].tension = 4; cueEd().dirty = true;
      S.cueSkip[cueKeyOf('ep', 2)] = true;
      const card = cueCard(2, []);
      const lines = cueLinesText(data.p.episodes[1].cue_sheet.cues[1].lines, cueName);
      const parsed = cueLinesParse(lines + '\\n모르는 사람: 안녕', 3, cueId);
      S.cueViewSig = cueSig(1); S.cueViewData = { on: true, skipped: true, stale: false, hit: 0, total: 0, missed: [], rows: [] };
      const panel = cuePanel(1);
      // 다른 작품의 같은 화: 고침도 '없이 쓰기'도 따라오지 않는다
      S.name = 'other'; S.cue = { ...data.labels, name: 'other' }; S.project = structuredClone(data.p); S.project.episodes[1].cue_sheet = null;
      S.cueViewSig = cueSig(2); S.cueViewData = { on: true, stale: false, hit: 0, total: 0, missed: [] };
      const other = cueCard(2, []);
      return { card, lines, parsed, panel, other, otherDraft: cueEd().draft, otherSkip: cueWriteArg(2) };
    })()""", {"p": dump(p), "labels": labels})
    assert "cue-row" not in got["card"] and "checked" in got["card"]  # 없이 쓰기를 고르면 편집기를 접는다
    assert got["lines"] == f"{hero.name}: 등불을 끄지 마."
    assert got["parsed"] == [{"speaker": "hero", "text": "등불을 끄지 마."}, {"speaker": "모르는 사람", "text": "안녕"}]
    assert "이 본문은 큐 시트 없이 썼어요" in got["panel"] and "핵심 대사" not in got["panel"] and "큐 시트 고치기" not in got["panel"]
    assert "아직 없음" in got["other"] and "cue-row" not in got["other"] and got["otherDraft"] is None
    assert got["otherSkip"] == {}
