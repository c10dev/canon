"""상태 칸 지우기(CharacterState.cleared) 시험: 반영 · 재생 · 저장 모양 · 프롬프트 규칙, 상태 승인 화면의 고치기 · 지우기. 실행: python -m pytest tests"""
import json

from canon import cast, pipeline, prompts
from canon.schema import CharacterState, Meta, Project, StateDelta

from .jsvm import dump, episode, needs_node, run_js
from .test_storylines import _short
from .test_timeline import _play


def _goal_project():
    p = _play(_short(8), 1, 3)
    st = p.state_of("hero")
    st.current_goal, st.location, st.notes = "오빠를 찾는다", "등대", "왼손잡이"
    return p


def test_empty_keeps_and_cleared_empties():
    p = _goal_project()
    pipeline.apply_delta(p, StateDelta(episode=4, summary="4화", character_updates=[
        CharacterState(character_id="hero", current_goal="", location="", cleared=["current_goal", "notes", "없는칸"])]))
    st = p.state_of("hero")
    assert st.current_goal == "" and st.notes == ""  # 지운 칸
    assert st.location == "등대"  # 빈 칸은 그대로
    assert "cleared" not in st.model_dump_json()  # 저장한 상태에는 지울 칸이 남지 않는다
    assert p.snapshot(4).states[0].current_goal == ""


def test_cleared_wins_over_value():
    p = _goal_project()
    pipeline.apply_delta(p, StateDelta(episode=4, summary="4화", character_updates=[
        CharacterState(character_id="hero", location="시장", cleared=["location"])]))
    assert p.state_of("hero").location == ""


def test_cleared_blanks_value_on_parse():
    d = StateDelta.model_validate({"episode": 4, "summary": "", "character_updates": [
        {"character_id": "hero", "location": "시장", "attire": "외투", "cleared": ["location", "없는칸"]}]})
    u = d.character_updates[0]
    assert u.location == "" and u.attire == "외투"  # 경고 · 표시가 지울 칸을 새 값으로 읽지 않는다


def test_new_state_does_not_keep_cleared():
    p = _goal_project()
    p.states = [s for s in p.states if s.character_id != "hero"]
    pipeline.apply_delta(p, StateDelta(episode=4, summary="4화", character_updates=[
        CharacterState(character_id="hero", emotional_state="불안", cleared=["current_goal"])]))
    assert p.state_of("hero").cleared == []


def test_cast_replay_clears():
    p = _goal_project()
    pipeline.apply_delta(p, StateDelta(episode=4, summary="4화", character_updates=[
        CharacterState(character_id="hero", cleared=["attire"])]))
    p.snapshots = [s for s in p.snapshots if s.episode in (0, 3)]  # 지워진 화는 변경안으로 다시 계산한다
    f4 = next(f for f in cast.frames(p) if f["episode"] == 4)
    assert next(s for s in f4["states"] if s["character_id"] == "hero")["attire"] == ""


def test_cleared_counts_as_involved():
    d = StateDelta(episode=1, summary="", character_updates=[CharacterState(character_id="hero", cleared=["current_goal"])])
    assert cast.involved(d) == {"hero"}


def test_delta_keeps_cleared_and_prompt_has_rule():
    d = StateDelta(episode=1, summary="", character_updates=[CharacterState(character_id="hero", cleared=["notes"])])
    assert json.loads(d.model_dump_json())["character_updates"][0]["cleared"] == ["notes"]
    p = _short(8)
    sp = prompts.state_prompt(p, 1)
    assert "cleared 에 넣습니다" in sp
    assert '"cleared"' not in prompts.dump(p.states)  # 이전 상태 블록에는 빈 지울 칸이 없다


@needs_node
def test_review_edits_and_clears_state_fields():
    e = episode(1, status="written", text="서윤은 등대에 섰다.")
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[e], states=[
        CharacterState(character_id="hero", current_goal="오빠를 찾는다", location="등대", notes="왼손잡이")])
    d = StateDelta(episode=1, summary="s", character_updates=[CharacterState(character_id="hero", emotional_state="안도", location="시장")])
    files = ["app.js", "hub.js", "notify.js", "settings.js", "home.js", "branches.js", "setup.js", "style.js", "plot.js", "write.js", "board.js", "review.js", "check.js", "flow.js", "research.js", "palette.js", "chat.js", "agent.js", "passage.js", "rewrite.js", "restate.js", "publish.js", "illust.js", "causal.js", "lines.js", "insert.js", "cast.js", "atlas.js", "auto.js", "convert.js", "opening.js", "usage.js", "claude.js", "vertex.js", "mystyle.js", "anchor.js", "stylechat.js", "setupchat.js", "ideas.js", "marks.js", "foreshadow.js", "statwin.js", "abilities.js", "stattrial.js", "cue.js", "revlab.js", "refs.js", "studio.js", "soelab.js", "timeline.js", "charlog.js", "address.js", "knows.js", "archetypes.js", "mentions.js", "tofix.js", "stage.js", "stage3d.js", "play.js"]  # index.html 차례
    got = run_js(files, """(() => {
      S.project = data.p; S.name = 't'; S.route = ['p', 't', 'review', '1'];
      setDelta(1, data.d);
      S.picks.c0 = true;  // 설정에 없는 시험 인물이라 기본으로 빠진다
      S.rvOpen = { '1:c0': true };
      const before = [deltaEdited(1), charEdited(1, 0)];
      const html = viewReview(1);
      const u = S.deltas[1].character_updates[0];
      u.current_goal = ' 등대를 지킨다 ';
      u.cleared = ['notes'];
      S.rvOpen = {};
      const closed = viewReview(1);
      return { before, html, after: [deltaEdited(1), charEdited(1, 0), itemEdited(1, 'go0'), itemEdited(1, 'no0'), itemEdited(1, 'lo0')],
               picked: pickedDelta(1).character_updates[0], closed };
    })()""", {"p": dump(p), "d": dump(d)})
    assert got["before"] == [False, False]
    html = got["html"]
    for f in ("current_goal", "location", "notes"):  # 목표 · 위치 · 메모도 고칠 수 있다
        assert f'data-dpath="character_updates.0.{f}"' in html
    for f in ("current_goal", "location", "notes"):  # 지금 값이 있는 칸은 지울 수 있다
        assert f'data-dclear="1:0:{f}"' in html
    assert "비우면 지금 목표를 그대로 둬요" in html
    assert got["after"] == [True, True, True, True, False]
    assert got["picked"]["current_goal"] == "등대를 지킨다" and got["picked"]["cleared"] == ["notes"]
    assert "메모</span> 지움" in got["closed"]  # 접은 줄에도 지운 칸이 보인다
