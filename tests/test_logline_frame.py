"""로그라인 웹소설 칸 (docs/webnovel/specs/03-logline.md): 드라마 틀 요청이 고치기 전과 같음, 웹소설 틀의 설정 대화 · 칸 아이디어,
응답 형식, 적용 · 적용 취소, 저장한 변경안 읽기, 명령줄 물음, 화면의 틀 바꾸기 · 예시 채우기 · 찾기. 실행: python -m pytest tests"""
import builtins
import hashlib
import json
import random
from typing import get_args

from canon import cli, genres, logline, naming, pipeline, prompts, setupchat, store
from canon.mock import MockLLM
from canon.schema import ChatMessage, LoglineParts, Meta, Project, SetupEdit, SetupKey, SetupRevision, SetupRevisionWeb, WebSetupKey

from .jsvm import dump, needs_node, run_js

FULL = dict(who="사진관을 하는 채은", why="오빠 소식에", goal="되짚는다", block="막는다", stake="잃는다")

# 칸을 더하기 전 코드(main 7ada3743)로 만든 드라마 틀 요청의 sha256 앞 16자
BEFORE = {
    "empty:chat": "7ee2a1683e7df863", "empty:chat_opt": "656f58707803c987", "empty:field:who": "2b2a11b6be0caad0",
    "empty:field:why": "304d2e8d7577ab26", "empty:field:goal": "2f1fc7b2029aff07", "empty:field:block": "4fe0316b17885507",
    "empty:field:stake": "4c3f3338fcdca066", "empty:field:title": "4ce24878b147c9e8", "full:chat": "bb0717f331614c3c",
    "full:chat_opt": "1a847406b119e3e8", "full:field:who": "0197476ea7501402", "full:field:why": "22ae1b551952ef25",
    "full:field:goal": "0e07e24c678ca09a", "full:field:block": "cc3159717f57b568", "full:field:stake": "5b38cfb6ee06ed26",
    "full:field:title": "1b2e7c4a88eb5b70",
}


def _project(frame="drama", **parts) -> Project:
    p = Project(meta=Meta(title="등대", genres=["light_novel", "mystery"], logline="x", frame=frame))
    p.meta.logline_parts = LoglineParts(**parts)
    return p


def _requests(p: Project, tag: str) -> dict[str, str]:
    random.seed(0)
    out = {f"{tag}:chat": prompts.setup_chat_prompt(p, "로그라인 다듬어 줘", history_lines=[]),
           f"{tag}:chat_opt": prompts.setup_chat_prompt(p, "여러 안", mode="options", history_lines=[])}
    for k in ("who", "why", "goal", "block", "stake"):
        out[f"{tag}:field:{k}"] = prompts.field_prompt(p, f"meta.logline_parts.{k}")
    out[f"{tag}:field:title"] = prompts.field_prompt(p, "meta.title")
    return out


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def test_drama_requests_match_before(monkeypatch):
    """드라마 틀 작품의 설정 대화 · 칸 아이디어 요청이 칸을 더하기 전과 글자까지 같다. 웹소설 칸 값이 남아 있어도 같다."""
    monkeypatch.setattr(naming, "_rng", lambda rng: rng or random.Random(0))
    got = {**_requests(_project(), "empty"), **_requests(_project(**FULL), "full")}
    assert {k: _h(v) for k, v in got.items()} == BEFORE
    left = _requests(_project(**FULL, edge="그만 본다", appeal="매번 이긴다"), "full")
    assert {k: _h(v) for k, v in left.items()} == {k: v for k, v in BEFORE.items() if k.startswith("full:")}
    assert prompts.setup_schema(_project()) is SetupRevision


def test_webnovel_requests_name_the_new_cells():
    p = _project("webnovel", **FULL, edge="그만 본다")
    chat = prompts.setup_chat_prompt(p, "로그라인 다듬어 줘", history_lines=[])
    assert prompts.SETUP_LOGLINE_KEYS["webnovel"] in chat and prompts.SETUP_LOGLINE_KEYS["drama"] not in chat
    assert '"edge": "그만 본다"' in chat and '"appeal": ""' in chat  # 덤프는 웹소설 틀의 칸 모두
    field = prompts.field_prompt(p, "meta.logline_parts.edge")
    assert "'주인공만 가진 것'" in field and "게임을 만든 그만 모든 분기와 엔딩을 안다" in field  # 라이트노벨 예시
    assert " /  / " not in field and not field.rstrip().endswith("/")  # 칸이 빈 미스터리 예시는 넣지 않는다
    assert prompts.setup_schema(p) is SetupRevisionWeb
    fmt = prompts.brief_parts(p, 1, "setup_chat")[1]
    assert '"logline.edge"' in fmt and '"logline.appeal"' in fmt
    assert '"logline.edge"' not in prompts.brief_parts(_project(), 1, "setup_chat")[1]


def test_keys_and_stored_revisions():
    """저장한 변경안은 새 키도 읽고, 드라마 틀 응답 형식에는 지금 키만 보인다."""
    assert set(get_args(WebSetupKey)) == set(get_args(SetupKey)) | {"logline.edge", "logline.appeal"}
    assert list(setupchat.KEY_LABELS) == list(get_args(WebSetupKey))
    schema = json.dumps(SetupRevision.model_json_schema(), ensure_ascii=False)
    assert "logline.edge" not in schema
    msg = ChatMessage(role="assistant", text="", setup=SetupRevision(reply="", edits=[SetupEdit(key="logline.appeal", text="매번 이긴다")]))
    assert ChatMessage.model_validate(json.loads(msg.model_dump_json())).setup.edits[0].key == "logline.appeal"
    try:
        SetupEdit(key="logline.nope")
        raise AssertionError("모르는 칸")
    except ValueError:
        pass


def test_webnovel_setup_chat_apply_and_undo():
    """웹소설 틀 작품의 설정 대화: 새 칸 변경안을 받아 저장 형식으로 옮기고, 적용하면 웹소설 문장으로 다시 합치고, 취소하면 돌아간다."""
    p = _project("webnovel", who="말 없는 소녀", goal="오빠를 찾는다")
    p.meta.logline = logline.compose(p.meta.logline_parts, "webnovel")
    rev = pipeline.revise_setup(MockLLM(), p, "로그라인 다듬어 줘")
    assert type(rev) is SetupRevision and [e.key for e in rev.edits][:2] == ["logline.edge", "logline.block"]  # 칸 차례 (KEY_LABELS)
    setupchat.record(p, "로그라인 다듬어 줘", "", rev)
    i = len(p.chat("setup").messages) - 1
    setupchat.apply(p, i, ["logline.edge", "logline.block"])
    assert p.meta.logline == "말 없는 소녀가 오빠를 찾는다. 그녀만 꺼진 등대의 신호를 읽는다. 하지만 바다를 지키는 마을 사람들."
    setupchat.undo(p, i)
    assert p.meta.logline == "말 없는 소녀가 오빠를 찾는다." and p.meta.logline_parts.edge == ""
    assert "logline.edge" not in [e.key for e in pipeline.revise_setup(MockLLM(), _project(), "다듬어 줘").edits]  # 드라마 틀은 그대로


def test_frame_switch_keeps_cells_on_save(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _project("webnovel", **FULL, edge="그만 본다", appeal="매번 이긴다")
    store.save("t", p)
    q = store.load("t")
    q.meta.frame = "drama"
    store.save("t", q)
    back = store.load("t")
    assert (back.meta.frame, back.meta.logline_parts.edge, back.meta.logline_parts.appeal) == ("drama", "그만 본다", "매번 이긴다")


def test_cli_asks_webnovel_cells(monkeypatch, capsys):
    answers = iter(["게임 폐인 대학생", "게임 속으로 들어가", "배드엔딩을 막는다", "그만 엔딩을 안다", "엔딩을 바꿀 때마다 길이 열린다", "", ""])
    asked = []
    monkeypatch.setattr(builtins, "input", lambda q="": asked.append(q) or next(answers))
    parts = cli.ask_logline(["light_novel"], "webnovel")
    out = capsys.readouterr().out
    assert [q.split(" (")[0] for q in asked] == ["누가", "무엇 때문에", "무엇을 하려 하나", "주인공만 가진 것", "독자가 받는 재미", "무엇이 막나", "무엇이 걸렸나"]
    assert "무엇이 막나 (선택)" in asked[5]
    assert parts.edge == "그만 엔딩을 안다" and "로그라인: 게임 폐인 대학생이 게임 속으로 들어가 배드엔딩을 막는다. 그만 엔딩을 안다." in out
    assert "주인공만 가진 것이 있어요" in out
    assert "게임을 만든 그만 모든 분기와 엔딩을 안다." in out and "파티장은" not in out  # 예시는 웹소설 칸 다섯만

    drama = iter(["서윤", "", "찾는다", "막는다", ""])
    asked.clear()
    monkeypatch.setattr(builtins, "input", lambda q="": asked.append(q) or next(drama))
    cli.ask_logline(["mystery"])
    assert [q.split(" (")[0] for q in asked] == ["누가", "무엇 때문에", "무엇을 하려 하나", "무엇이 막나", "무엇이 걸렸나"]
    assert asked[3] == "무엇이 막나 (사람이나 힘): "


@needs_node
def test_screen_slots_match_server():
    got = run_js(["app.js", "setup.js"], "[LOGLINE_SLOTS.map((s) => s[0]), LOGLINE_FRAME_SLOTS]", None)
    assert got[0] == list(LoglineParts.model_fields)
    assert {k: [list(a), list(b)] for k, (a, b) in logline.SLOTS.items()} == got[1]


SCREEN = ["app.js", "home.js", "ideas.js", "setup.js", "palette.js"]


@needs_node
def test_screen_frame_switch_recomposes_and_keeps_cells():
    """틀을 바꾸면 칸 값은 그대로, 칸으로 합친 문장만 새 틀로. 직접 고친 문장은 그대로. 웹소설 틀 화면에 새 칸과 접은 칸."""
    p = _project("drama", **FULL, edge="그만 본다", appeal="매번 이긴다")
    p.meta.logline = logline.compose(p.meta.logline_parts)
    expr = """(() => {
      S.genres = data.cat; S.route = ['p', 't', 'setup']; S.project = data.project; S.name = 't';
      const drama = loglineBuilder();
      actions.setFrame('webnovel');
      const web = { line: P().meta.logline, parts: { ...P().meta.logline_parts }, html: loglineBuilder() };
      actions.setFrame('drama');
      const back = { line: P().meta.logline, parts: { ...P().meta.logline_parts } };
      P().meta.logline = '직접 쓴 문장';
      actions.setFrame('webnovel');
      return { drama, web, back, manual: P().meta.logline }; })()"""
    got = run_js(SCREEN, expr, {"cat": [g.model_dump() for g in genres.CATALOG], "project": dump(p)})
    assert got["web"]["line"] == logline.compose(p.meta.logline_parts, "webnovel")
    assert got["back"]["line"] == logline.compose(p.meta.logline_parts)
    assert got["web"]["parts"] == got["back"]["parts"] == p.meta.logline_parts.model_dump()
    assert got["manual"] == "직접 쓴 문장"
    assert "주인공만 가진 것" not in got["drama"] and "더 쓰기" not in got["drama"]
    web = got["web"]["html"]
    assert web.index("f-meta-logline_parts-appeal") < web.index("더 쓰기: 무엇이 막나 · 무엇이 걸렸나 (선택)") < web.index("f-meta-logline_parts-block")
    assert '<details class="slot-more" open>' in web  # 막는 것을 적어 펼쳐 둔다


@needs_node
def test_screen_example_fills_only_frame_cells_and_palette_follows_frame():
    p = _project("webnovel", block="작가가 쓴 막는 것", edge="작가가 쓴 것")
    p.meta.genres = ["light_novel"]
    expr = """(async () => {
      S.genres = data.cat; S.route = ['p', 't', 'setup']; S.project = data.project; S.name = 't';
      globalThis.askConfirm = async () => true;
      await actions.useExample(1);
      const web = { ...P().meta.logline_parts };
      const webFields = palSetupFields(P()).map((f) => f.path);
      P().meta.frame = 'drama';
      await actions.useExample(0);
      return { web, drama: { ...P().meta.logline_parts }, webFields, dramaFields: palSetupFields(P()).map((f) => f.path) }; })()"""
    got = run_js(SCREEN, expr, {"cat": [g.model_dump() for g in genres.CATALOG], "project": dump(p)})
    ex1, ex0 = genres.BY_ID["light_novel"].logline[1], genres.BY_ID["light_novel"].logline[0]
    assert got["web"]["edge"] == ex1.edge and got["web"]["appeal"] == ex1.appeal and got["web"]["block"] == "작가가 쓴 막는 것"
    assert got["drama"]["block"] == ex0.block and got["drama"]["edge"] == ex1.edge  # 드라마 틀 예시는 웹소설 칸을 두고 바꾼다
    assert "meta.logline_parts.edge" in got["webFields"] and "meta.logline_parts.edge" not in got["dramaFields"]
