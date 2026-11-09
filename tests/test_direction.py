"""작가 연출 지시 (Episode.direction · StoryArc.direction, prompts.direction_block, PUT …/direction, static/write.js dirCard).
실행: python -m pytest tests"""
import contextlib
import io
import json

import pytest

from canon import autorun, cue, jobs, llm, pipeline, prompts, store
from canon.cli import main
from canon.mock import MockLLM
from canon.schema import ArcProposal, HeatArcProposal, Project, StoryArc

from .jsvm import dump, episode, needs_node, run_js
from .test_cue_write import _sheet
from .test_serial import _plan_arc, _serial
from .test_storylines import _short

LLM = MockLLM()
GUARD = "플롯의 사건과 설정은 바꾸지 않습니다. 지시 문구를 본문에 쓰지 않습니다."


def _directed() -> Project:
    p = _serial()
    a = _plan_arc(p)
    a.direction = "아크 동안 서윤의 눈으로만 보여 줍니다"
    p.episode(2).direction = "회상은 한 문단으로 줄입니다"
    return p


def test_old_project_reads_with_empty_direction():
    p = Project.model_validate({"episodes": [{"plot": {"number": 1, "act": "기", "title": "t", "summary": "s", "events": [],
                                                        "characters": [], "emotional_shift": "", "ending_hook": ""}}],
                                "story_arcs": [{"number": 1, "title": "a", "start_ep": 1, "end_ep": 5, "goal": "g"}]})
    assert p.episodes[0].direction == "" and p.story_arcs[0].direction == ""


def test_arc_direction_stays_out_of_ai_schema_and_arc_dumps():
    for model in (ArcProposal, HeatArcProposal):
        assert "direction" not in json.dumps(model.model_json_schema())
    a = StoryArc(number=1, title="a", start_ep=1, end_ep=5, goal="g", direction="비밀 지시")
    assert "비밀 지시" not in llm.dump(a)
    assert "direction" not in a.model_dump(exclude=set(prompts.ARC_HEAT))
    p = _directed()
    assert "서윤의 눈으로만" not in prompts.build_episode_context(p, 2, write=True)  # 아크 덤프 블록에는 없다
    assert "서윤의 눈으로만" not in prompts.next_arc_prompt(p, 13, 10, "")


def test_block_is_last_with_arc_then_episode():
    p = _directed()
    w = prompts.episode_prompt(p, 2)
    block = prompts.direction_block(p, 2)
    assert w.endswith(block) and block.startswith("\n\n# 작가 연출 지시\n")
    assert block.index("이번 아크 동안: 아크 동안 서윤의 눈으로만") < block.index("이번 화만: 회상은 한 문단으로")
    assert GUARD in block and "가장 먼저" not in block  # 우선 차례는 priority_line 한 곳에만
    assert "이번 화 플롯, 작가 연출 지시, " in prompts.priority_line(p, 2, False) and "스타일 프로필과 문체 예시 차례로" in w
    assert prompts.episode_prompt(p, 2, direction=False) + block == w


def test_episode_direction_only_for_its_episode():
    p = _directed()
    w3 = prompts.episode_prompt(p, 3)
    assert "회상은 한 문단으로" not in w3  # 다음 화에는 넣지 않는다
    assert "이번 아크 동안: 아크 동안 서윤의 눈으로만" in w3 and "이번 화만" not in w3
    p.story_arcs[0].direction = ""
    assert "작가 연출 지시" not in prompts.episode_prompt(p, 3)


def test_no_direction_keeps_prompt():
    p = _short(8)
    w = prompts.episode_prompt(p, 1)
    assert "작가 연출 지시" not in w and prompts.direction_block(p, 1) == ""
    assert prompts.episode_prompt(p, 1, direction=False) == w


def test_short_form_has_episode_direction_only():
    p = _short(8)
    p.episode(1).direction = "대사를 짧게"
    assert prompts.direction_texts(p, 1) == ("", "대사를 짧게")
    assert prompts.episode_prompt(p, 1).endswith(prompts.direction_block(p, 1))
    assert prompts.priority_line(p, 1, False) == " 자료가 서로 부딪히면 이번 화 플롯, 작가 연출 지시, 스타일 프로필과 문체 예시 차례로 따릅니다."


def test_direction_follows_cue_sheet_in_every_path():
    p = _short(6)
    p.episode(1).status = "confirmed"
    p.settings.cue_sheet = "on"
    cue.set_episode(p, 1, _sheet())
    p.episode(1).direction = "대사를 짧게"
    full = prompts.episode_prompt(p, 1)
    block = prompts.direction_block(p, 1)
    assert full.endswith(block) and full.index("# 이번 화 큐 시트") < full.index("# 작가 연출 지시")
    assert prompts.cue_score_prompt(p, 1, p.episode(1).cue_sheet) == full  # 실험의 조건 score 와 같은 글
    assert prompts.cue_head(p, 1, p.episode(1).cue_sheet).endswith(block)
    assert full in prompts.episode_brief(p, 1)  # 작업지시서도 같은 글


def test_replanning_draft_keeps_direction():
    p = _short(8)
    p.episode(4).direction = "밤 장면으로"
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, 8))
    assert p.episode(4).direction == "밤 장면으로"


def test_write_episode_sends_direction(monkeypatch):
    p = _short(8)
    p.episode(1).status = "confirmed"
    p.episode(1).direction = "대사를 짧게"
    sent = []
    monkeypatch.setattr(pipeline, "_write", lambda llm_, q, n, prompt, cut=None, *rest: sent.append(prompt) or "본문")
    pipeline.write_episode(LLM, p, 1)
    assert sent[0].endswith(prompts.direction_block(p, 1))


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "4", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
    yield "demo"
    jobs.draining.clear()


def test_auto_run_uses_saved_episode_direction(demo, monkeypatch):
    p = store.load(demo)
    p.episode(1).direction = "대사를 짧게"
    store.save(demo, p)
    sent = []
    real = pipeline._write
    monkeypatch.setattr(pipeline, "_write", lambda llm_, q, n, prompt, cut=None, *rest: sent.append((n, prompt)) or real(llm_, q, n, prompt, cut, *rest))
    autorun.start(demo, 2, False, autorun.Policy(hand_pick_opening=False), foreground=True)
    by = dict(sent)
    assert "이번 화만: 대사를 짧게" in by[1] and "대사를 짧게" not in by[2]
    assert store.load(demo).episode(1).direction == "대사를 짧게"  # 쓴 뒤에도 기록으로 남는다


def _save_serial(client) -> Project:
    p = _serial()
    _plan_arc(p)
    store.save("lh", p)
    return p


def test_route_saves_episode_and_arc(client):
    _save_serial(client)
    r = client.put("/api/projects/lh/episodes/2/direction", json={"episode": " 회상 줄이기 ", "arc": "서윤 시점"})
    assert r.status_code == 200 and r.json() == {"episode": "회상 줄이기", "arc": "서윤 시점"}
    p = store.load("lh")
    assert p.episode(2).direction == "회상 줄이기" and p.arc_for(2).direction == "서윤 시점"
    r = client.put("/api/projects/lh/episodes/3/direction", json={"episode": "밤"})  # arc 를 빼면 아크 지시는 그대로
    assert r.json() == {"episode": "밤", "arc": "서윤 시점"}


def test_screen_save_keeps_directions(client):
    _save_serial(client)
    stale = client.get("/api/projects/lh").json()
    client.put("/api/projects/lh/episodes/2/direction", json={"episode": "회상 줄이기", "arc": "서윤 시점"})
    client.put("/api/projects/lh", json=stale)  # 지시를 적기 전에 읽은 화면이 작품 전체를 저장한다
    p = store.load("lh")
    assert p.episode(2).direction == "회상 줄이기" and p.arc_for(2).direction == "서윤 시점"


def test_route_refuses_draft_and_short_arc(client):
    p = _short(4)
    store.save("lh", p)
    r = client.put("/api/projects/lh/episodes/1/direction", json={"episode": "x"})
    assert r.status_code == 400 and "확정" in r.json()["detail"]
    p.episode(1).status = "confirmed"
    store.save("lh", p)
    r = client.put("/api/projects/lh/episodes/1/direction", json={"episode": "x", "arc": "y"})
    assert r.status_code == 400 and "아크" in r.json()["detail"]
    assert store.load("lh").episode(1).direction == ""  # 실패하면 화 지시도 저장하지 않는다


FILES = ["app.js", "plot.js", "write.js", "chat.js", "passage.js", "timeline.js"]


def _js_project():
    p = Project()
    p.meta.form, p.meta.target_episodes = "serial", 10
    p.story_arcs = [StoryArc(number=1, title="첫 탑", start_ep=1, end_ep=10, goal="g", direction="서윤 시점")]
    p.episodes = [episode(1, text="본문", status="finalized", direction="회상 줄이기"),
                  episode(2, status="confirmed"), episode(3, status="finalized"), episode(4)]
    return dump(p)


@needs_node
def test_card_shows_current_directions():
    expr = """S.project = data; S.name = 'lh'; S.jobs = [];
      const shown = dirCard(1), fresh = dirCard(2);
      S.project.story_arcs[0].direction = '';
      const none = dirCard(3), draft = dirCard(4);
      S.dirEdit = 2;
      [shown, fresh, none, draft, dirCard(2)]"""
    shown, fresh, none, draft, editing = run_js(FILES, expr, _js_project())
    assert "서윤 시점" in shown and "아크 1 첫 탑 · 1~10화" in shown and "1화를 쓸 때 준 지시" in shown and "회상 줄이기" in shown
    assert "서윤 시점" in fresh and "이번 화만" not in fresh and ">고치기<" in fresh  # 아크 지시는 다음 화에도 늘 보인다
    assert none == "" and draft == ""  # 지시가 없는 반영 끝난 화, 플롯 초안 화는 그리지 않는다
    assert 'id="dir-arc"' in editing and 'id="dir-ep"' in editing and 'data-action="dirSave"' in editing


@needs_node
def test_card_locks_while_auto_run():
    expr = """S.project = data; S.name = 'lh'; S.jobs = [{status: 'running', project: 'lh', ep: 2, kind: 'write'}];
      dirCard(2)"""
    out = run_js(FILES, expr, _js_project())
    assert "disabled" in out and "AI 작업이 끝난 뒤에 고칠 수 있어요" in out


@needs_node
def test_card_keeps_typed_text_on_redraw():
    expr = """S.project = data; S.name = 'lh'; S.jobs = []; S.dirEdit = 2; S.dirText = {'dir-ep': '새로 적는 중'};
      dirCard(2)"""
    out = run_js(FILES, expr, _js_project())
    assert "새로 적는 중</textarea>" in out and "서윤 시점</textarea>" in out


def test_plot_chat_keeps_direction():
    from canon.schema import PlotRevision
    p = _short(8)
    p.episode(4).status = "confirmed"
    p.episode(4).direction = "밤 장면으로"
    plot = p.episode(4).plot.model_copy(update={"title": "바뀐 제목"})
    pipeline.apply_revision(p, PlotRevision(episodes=[plot], reply=""), False, [4])
    assert p.episode(4).plot.title == "바뀐 제목" and p.episode(4).direction == "밤 장면으로"
