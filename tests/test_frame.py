"""이야기 틀 (Meta.frame, docs/webnovel/specs/01-frame.md): 기본값, 옛 작품 읽기, 프롬프트가 그대로인지, 장르의 틀 추천, 명령줄, 화면 칩.
실행: python -m pytest tests"""
from canon import cli, genres, prompts, store
from canon.schema import FRAMES, Meta, Project

from .jsvm import needs_node, run_js


def _project(**meta) -> Project:
    return Project(meta=Meta(title="등대", genres=["light_novel"], logline="채은이 오빠를 찾는다.", **meta))


def test_default_is_drama_and_old_project_reads():
    assert Meta().frame == "drama" and list(FRAMES) == ["drama", "webnovel"]
    old = Project.model_validate({"meta": {"title": "옛 작품", "genre": "로맨스"}})  # frame 이 없던 project.json
    assert old.meta.frame == "drama"
    assert Project.model_validate(_project(frame="webnovel").model_dump()).meta.frame == "webnovel"


def test_frame_does_not_change_prompts():
    a, b = _project(), _project(frame="webnovel")
    assert prompts.meta_text(a) == prompts.meta_text(b) and "frame" not in prompts.meta_text(b)  # 다른 요청 글은 tests/test_prompt_registry.py 의 스냅샷이 본다


def test_genres_recommend_a_frame_but_do_not_set_it():
    assert genres.frame_hint(["light_novel"]) == "webnovel" and genres.frame_hint(["romance", "regression"]) == "webnovel"
    assert genres.frame_hint(["romance", "mystery", "직접 적은 장르"]) == "" and genres.frame_hint([]) == ""
    assert Meta(genres=["light_novel"]).frame == "drama"  # 추천만 한다


def _new(tmp_path, monkeypatch, capsys, *extra) -> tuple[Project, str]:
    monkeypatch.setattr(store, "ROOT", tmp_path)
    cli.main(["new", "t", "--title", "등대", "--genre", "light_novel", "--logline", "채은이 오빠를 찾는다.", "--episodes", "12", "--no-suggest", *extra])
    return store.load("t"), capsys.readouterr().out


def test_cli_new_frame(tmp_path, monkeypatch, capsys):
    p, out = _new(tmp_path, monkeypatch, capsys)
    assert p.meta.frame == "drama" and "--frame webnovel" in out          # 권하기만 하고 기본은 그대로


def test_cli_new_frame_webnovel(tmp_path, monkeypatch, capsys):
    p, out = _new(tmp_path, monkeypatch, capsys, "--frame", "webnovel")
    assert p.meta.frame == "webnovel" and "--frame webnovel" not in out


@needs_node
def test_screen_frames_match_schema_and_hint():
    cat = [g.model_dump() for g in genres.CATALOG]
    expr = """(() => { S.genres = data.cat; S.route = ['p', 't', 'setup']; S.project = data.project;
      const html = (frame, gs) => { S.project.meta.frame = frame; S.project.meta.genres = gs; return frameField(); };
      return { frames: FRAMES, hints: data.sets.map((gs) => frameHint({ genres: gs })),
               rec: html('drama', ['light_novel']), picked: html('webnovel', ['light_novel']), none: html('drama', ['romance']) }; })()"""
    sets = [["light_novel"], ["romance", "regression"], ["romance"], []]
    got = run_js(["app.js", "home.js"], expr, {"cat": cat, "project": _project().model_dump(), "sets": sets})
    assert dict(got["frames"]) == FRAMES
    assert got["hints"] == [genres.frame_hint(s) for s in sets]
    assert "장르에 맞춰 추천" in got["rec"] and "장르에 맞춰 추천" not in got["picked"] and "장르에 맞춰 추천" not in got["none"]
    assert got["picked"].count('aria-pressed="true"') == 1 and 'aria-pressed="true" data-action="setFrame" data-arg="webnovel"' in got["picked"]


def test_frame_changes_only_arc_planning():
    """틀을 웹소설식으로 바꾸면 바뀌는 요청은 장편의 부 · 아크 기획(작업지시서 부 구성 · 다음 아크 · 대화 에이전트 첫 단계, 플롯 대화)뿐이다.
    단편은 전환 요청만 바뀐다 (docs/webnovel/specs/04-arc-frame.md). 나머지 요청은 스냅샷(드라마식)과 글자까지 같다."""
    import json

    from . import test_prompt_registry as reg

    want = json.loads(reg.SNAPSHOT.read_text(encoding="utf-8"))
    changed = {}
    for tag, make in (("short", reg._short), ("long", reg._long)):
        p = make()
        p.meta.frame = "webnovel"
        got = {f"{tag}:{k}": reg._h(v) for k, v in {**reg._requests(p), **reg._arc_requests(p)}.items()}
        assert set(got) <= set(want)
        changed[tag] = sorted(k for k, v in got.items() if want[k] != v)
    assert changed == {"short": ["short:convert"],
                       "long": ["long:brief:agent_plot", "long:brief:arc", "long:brief:series", "long:plot_chat:arc", "long:plot_chat:next"]}
    for g in genres.CATALOG:
        text = genres.guide(Meta(genres=[g.id])) + "\n".join(genres.opening_beats(Meta(genres=[g.id]), 1))
        assert "frame" not in text and "webnovel" not in text and "웹소설식" not in text, g.id
