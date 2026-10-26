"""인물 설정 변경(canon/charlog.py) 테스트 (mock LLM): 제안 정리, 고른 것만 반영 · 기록, 되돌리기, 작가 수정 기록,
자동 집필 · 명령줄 -y 는 남겨 두기, 웹 승인 · 남겨 둔 제안, 인물 화면 타임라인. 실행: python -m pytest tests"""
import contextlib
import io

from canon import autorun, cast, charlog, pipeline, prompts, store
from canon.cli import main
from canon.mock import MOCK_LOOK
from canon.schema import SettingChange, StateDelta

from .test_autorun import Policy, demo  # noqa: F401  (pytest fixture)
from .test_storylines import _short
from .test_timeline import LLM, _play
from .test_web import client  # noqa: F401  (pytest fixture)


def _written(p, n):
    pipeline.confirm_plot(p, n)
    p.episode(n).text = pipeline.write_episode(LLM, p, n)
    p.episode(n).status = "written"


def test_rule_and_mock_proposal():
    p = _short(8)
    assert charlog.state_rule(p) in prompts.state_prompt(p, 1)
    assert "setting_changes" in prompts.state_brief(p, 1)  # 채팅 앱 작업지시서도 같은 칸을 받는다
    _play(p, 1, 1)
    _written(p, 2)
    d = pipeline.extract_state(LLM, p, 2)
    assert [(x.character_id, x.field, x.value, x.episode) for x in d.setting_changes] == [("hero", "appearance", MOCK_LOOK, 2)]


def test_clean_drops_unknown_same_and_new():
    p = _short(8)
    hero = p.characters[0]
    d = StateDelta(episode=1, summary="s", new_characters=[hero.model_copy(update={"id": "newbie"})], setting_changes=[
        SettingChange(character_id="ghost", field="appearance", value="x"),
        SettingChange(character_id="newbie", field="appearance", value="x"),
        SettingChange(character_id=hero.id, field="speech_style", value=hero.speech_style),
        SettingChange(character_id=hero.id, field="appearance", value=" 첫 값 "),
        SettingChange(character_id=hero.id, field="appearance", value="뒤 값"),
        SettingChange(character_id=hero.id, field="role", value="  "),
    ])
    charlog.clean_delta(p, d)
    assert [(x.field, x.value) for x in d.setting_changes] == [("appearance", "뒤 값")]
    assert any("ghost" in w for w in d.warnings) and not any("newbie" in w for w in d.warnings)


def test_apply_records_and_revert_restores():
    p = _play(_short(8), 1, 2)  # mock 2화가 외모를 바꾼다 (테스트는 변경안 전부를 승인한 셈)
    hero = p.characters[0]
    assert hero.appearance == MOCK_LOOK
    rec = p.setting_log[-1]
    assert (rec.episode, rec.field, rec.before, rec.after, rec.source) == (2, "appearance", "", MOCK_LOOK, "ai")
    assert "인물 설정 바꾸기" not in prompts.episode_prompt(p, 3)  # 기록은 프롬프트에 넣지 않고
    assert MOCK_LOOK in prompts.episode_prompt(p, 3)  # 지금 설정만 들어간다
    pipeline.revert(p, 1)
    assert hero.appearance == "" and p.setting_log == []


def test_revert_keeps_later_author_edit():
    p = _play(_short(8), 1, 2)
    disk = p.model_copy(deep=True)
    p.characters[0].appearance = "작가가 고친 외모"
    charlog.record_author(disk, p)
    pipeline.revert(p, 1)
    assert p.characters[0].appearance == "작가가 고친 외모"  # 작가 값은 되돌리지 않는다
    assert [(r.episode, r.source, r.after) for r in p.setting_log] == [(1, "author", "작가가 고친 외모")]


def test_author_edits_logged_after_first_episode():
    p = _short(8)
    disk = p.model_copy(deep=True)
    p.characters[0].personality = "설정 짜는 중"
    assert charlog.record_author(disk, p) == [] and p.setting_log == []  # 1화 반영 전은 기록하지 않는다
    p = _play(_short(8), 1, 1)
    old = p.characters[0].personality
    for v in ("고침 1", "고침 2"):  # 같은 화 뒤에 여러 번 고치면 한 기록
        disk = p.model_copy(deep=True)
        p.characters[0].personality = v
        charlog.record_author(disk, p)
    assert [(r.episode, r.field, r.before, r.after) for r in p.setting_log] == [(1, "personality", old, "고침 2")]
    disk = p.model_copy(deep=True)
    p.characters[0].personality = old  # 처음 값으로 돌아오면 기록도 지운다
    charlog.record_author(disk, p)
    assert p.setting_log == []


def test_cast_timeline_and_describe():
    p = _play(_short(8), 1, 3)
    rows = {r["n"]: r for r in cast.timeline(p, "hero")}
    assert rows[2]["settings"][0]["label"] == "외모" and rows[2]["settings"][0]["after"] == MOCK_LOOK
    assert rows[3]["settings"] == []
    assert f"외모 (비어 있음) → {MOCK_LOOK}" in cast.describe(p, "hero")


def test_autorun_holds_setting_changes(demo):  # noqa: F811
    run = autorun.start(demo, 3, False, Policy(check=False), foreground=True)
    assert run.status == "done"
    p = store.load(demo)
    assert p.characters[0].appearance != MOCK_LOOK and p.setting_log == []
    assert [(x.episode, x.field) for x in p.setting_held] == [(2, "appearance")]
    assert any("남겨 뒀어요" in e.message for e in run.log)
    assert "남겨 둔 설정 바꾸기 제안 (2화)" in cast.describe(p, "hero")
    rec = charlog.take_held(p, 0, "고쳐서 적용한 외모")
    assert p.characters[0].appearance == "고쳐서 적용한 외모" and rec.episode == 2 and p.setting_held == []
    pipeline.revert(p, 1)
    assert p.characters[0].appearance == "" and p.setting_log == []


def test_cli_yes_holds(demo):  # noqa: F811
    with contextlib.redirect_stdout(io.StringIO()) as out:
        main(["run", "demo", "-y"])
    p = store.load(demo)
    assert all(e.status == "finalized" for e in p.episodes)
    assert p.characters[0].appearance != MOCK_LOOK and len(p.setting_held) == 1
    assert "설정 바꾸기 제안 (지금 → 바꾼 뒤)" in out.getvalue() and "남겨 뒀어요" in out.getvalue()


def test_web_review_and_held(client):  # noqa: F811
    from canon import store as st  # 픽스처가 다시 불러온 저장소

    p = _play(_short(8), 1, 1)
    _written(p, 2)
    st.save("lh", p)
    d = client.post("/api/projects/lh/episodes/2/state").json()
    assert d["setting_changes"][0]["field"] == "appearance"
    d["setting_changes"][0]["value"] = "승인 화면에서 고친 외모"
    out = client.post("/api/projects/lh/episodes/2/apply", json=d).json()
    assert out["characters"][0]["appearance"] == "승인 화면에서 고친 외모"
    assert out["setting_log"][0]["after"] == "승인 화면에서 고친 외모"
    rows = {r["n"]: r for r in client.get("/api/projects/lh/cast").json()["timelines"]["hero"]}
    assert rows[2]["settings"][0]["field"] == "appearance"

    # 설정 화면 저장은 작가 기록으로 (화면이 보낸 기록은 쓰지 않는다)
    out["characters"][0]["speech_style"] = "작가가 바꾼 말투"
    out["setting_log"] = []
    out = client.put("/api/projects/lh", json=out).json()
    assert [(r["field"], r["source"]) for r in out["setting_log"]] == [("appearance", "ai"), ("speech_style", "author")]

    p = st.load("lh")
    p.setting_held = [SettingChange(character_id="hero", field="age", value="20세", episode=2),
                      SettingChange(character_id="ally", field="role", value="배신자", episode=2)]
    st.save("lh", p)
    out = client.delete("/api/projects/lh/setting-held/1").json()
    assert len(out["setting_held"]) == 1
    out = client.post("/api/projects/lh/setting-held/0", json={}).json()
    assert out["characters"][0]["age"] == "20세" and out["setting_held"] == []
    assert client.post("/api/projects/lh/setting-held/0", json={}).status_code == 400
