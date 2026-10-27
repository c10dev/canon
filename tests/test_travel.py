"""이동 시간 검사 테스트 (canon/travel.py): 시간대 읽기, 걸리는 시간, 반영한 화의 이동 판정, 상태 변경안 경고,
'괜찮아요', 쓰기 · 검수 프롬프트의 이동 거리, 웹 · 명령줄. 실행: python -m pytest tests/test_travel.py"""
import importlib
import os
import tempfile

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())
os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canon import atlas, cli, pipeline, prompts, store, travel  # noqa: E402
from canon.llm import get_llm  # noqa: E402
from canon.schema import CharacterState, MapPin, StoryTime  # noqa: E402

from .test_atlas import _played  # noqa: E402


def _mapped(span: float = 600):
    """등대(왼쪽 끝)와 흑송촌(오른쪽 끝)을 지도 가로 600km 지도에 놓는다. 곧은 거리 480km × 1.3 = 624km.
    인물 hero 는 1화 등대 → 2화 흑송촌 → 3화 등대 (mock 은 n화가 n일째 밤에 끝난다)."""
    p = _played()
    p.atlas.pins = [MapPin(place="el-2", x=0.1, y=0.5), MapPin(place="el-1", x=0.9, y=0.5), MapPin(place="w:수산시장", x=0.12, y=0.5)]
    p.atlas.aspect, p.atlas.span_km = 1.5, span
    return p


def test_hours_and_need():
    assert travel.hours("밤") == (18, 27) and travel.hours("한밤") == (22, 27) and travel.hours("") == (0, 24)
    assert travel.hours("오후 3시쯤") == (14, 16) and travel.hours("아침 7시") == (6, 8)
    assert travel.hours("밤 12시") == (23, 25) and travel.hours("3시") == (2, 16)  # 오전 · 오후를 모르면 넓게
    p = _mapped()
    normal, fast = travel.need(p, 100)  # 말: 하루 50km 두 날 → 첫날 다 가고 밤 쉬고 둘째 날 5시간
    assert normal == pytest.approx(29) and fast < normal
    assert travel.need(p, 10)[1] == pytest.approx(10 / 15)  # 가까우면 처음 몇 시간은 1.5배 빠르기
    p.atlas.travel.day_km = 80
    assert travel.speed(p)[2:] == (80, 160)
    assert travel.fmt_h(0.5) == "30분" and travel.fmt_h(5) == "5시간" and travel.fmt_h(60) == "2일 반" and travel.fmt_h(300) == "약 12일"
    assert travel.fmt_km(0.4) == "400m" and travel.fmt_km(624) == "624km"


def test_moves_on_played_episodes():
    p = _mapped()
    ms = travel.moves(p)
    hero = [m for m in ms if m["cid"] == "hero"]
    assert [(m["since"], m["episode"], m["stops"]) for m in hero] == [(1, 2, ["el-2", "el-1"]), (2, 3, ["el-1", "el-2"])]
    assert hero[0]["km"] == pytest.approx(624) and hero[0]["gap"] == pytest.approx(33)  # 1일째 18시 ~ 2일째 27시
    assert all(m["level"] == travel.FAST for m in hero)
    v = travel.view(p)
    assert len(v["moves"]) == 2 and v["checked"] == 2 and v["scale"] == [600, 400]
    # 걷기 하루 거리 안이면 걸리지 않고, 날수를 모르면 판정하지 않는다
    p.atlas.span_km = 20
    assert travel.view(p)["moves"] == []
    p = _mapped()
    p.episode(2).time = StoryTime()
    p.episode(3).time = StoryTime()
    assert all(m["gap"] is None for m in travel.moves(p) if m["cid"] == "hero") and travel.view(p)["unknown"] == 2
    # 축척을 모르거나 꺼지면 아무것도 보지 않는다
    p = _mapped(span=0)
    assert travel.moves(p) == [] and travel.view(p)["scale"] is None
    p = _mapped()
    p.atlas.travel.enabled = False
    assert travel.view(p)["moves"] == []


def test_accept_and_settings():
    p = _mapped()
    travel.accept(p, "hero", 2)
    travel.accept(p, "hero", 2)
    assert p.atlas.travel.ok == ["hero:2"]
    assert [m["accepted"] for m in travel.view(p)["moves"]] == [True, False]
    travel.accept(p, "hero", 2, ok=False)
    assert p.atlas.travel.ok == []
    travel.set_setting(p, True, "car", 0, 0, 600)
    assert travel.view(p)["moves"] == []  # 차로는 하루 만에 간다
    with pytest.raises(ValueError):
        travel.set_setting(p, True, "dragon", 0, 0, 600)
    with pytest.raises(ValueError):
        travel.set_setting(p, True, "walk", -1, 0, 600)


def test_layout_scale():
    p = _mapped(span=0)
    p.atlas.layout, p.atlas.layout_size, p.atlas.meters = "gen-village-1.json", [800, 600], 1.0
    assert travel.scale(p) == (0.8, 0.6)  # 마을은 1km 안팎이라 말로 금방 간다
    assert travel.view(p)["moves"] == [] and travel.view(p)["from_layout"]


def test_delta_warning():
    p = _mapped()
    pipeline.confirm_plot(p, 4)
    p.episode(4).text = pipeline.write_episode(get_llm("write"), p, 4)
    p.episode(4).status = "written"
    d = pipeline.extract_state(get_llm("state"), p, 4)
    d.time = StoryTime(day=3, part="밤 11시")  # 3화 끝(3일째 밤, 등대)에서 그날 밤 안에 흑송촌
    d.character_updates = [CharacterState(character_id="hero", location="흑송촌 장터"),
                           CharacterState(character_id="ally", location="수산시장")]
    d.warnings = []
    pipeline.clean_delta(p, d)
    warn = [w for w in d.warnings if "너무 빨리 옮겨 갔어요" in w]
    assert len(warn) == 1 and warn[0].startswith("서윤이 너무 빨리 옮겨 갔어요: 등대 → 흑송촌 약 624km를")
    assert "말로 보통 약 12일" in warn[0]
    travel.accept(p, "hero", 4)
    d.warnings = []
    pipeline.clean_delta(p, d)
    assert not any("너무 빨리 옮겨 갔어요" in w for w in d.warnings)
    p.atlas.travel.ok = []
    d.warnings, d.time = [], StoryTime(day=12)  # 9일이면 말로 갈 수 있다
    pipeline.clean_delta(p, d)
    assert not any("너무 빨리 옮겨 갔어요" in w for w in d.warnings)


def test_prompt_block():
    p = _mapped()
    pipeline.confirm_plot(p, 4)
    p.episode(4).plot.summary = "윤서가 흑송촌 장터로 간다"
    block = travel.episode_block(p, 4)
    assert block.startswith("지도 기준 거리") and "등대 → 흑송촌 약 624km" in block
    ctx = prompts.build_episode_context(p, 4)
    assert "# 이동 거리 (지도 기준)" in ctx and ctx.index("# 이동 거리") > ctx.index("# 작품 속 시간")
    chk = prompts.check_prompt(p, 4)
    assert "# 이동 거리 (지도 기준)" in chk and "- 이동: 위 '이동 거리'" in chk
    assert len(travel.episode_block(p, 4, budget=10).splitlines()) == 3  # 예산이 작아도 한 줄은 넣는다
    p.atlas.span_km = 0
    assert travel.episode_block(p, 4) == "" and "# 이동 거리" not in prompts.build_episode_context(p, 4)
    assert "- 이동: " not in prompts.check_prompt(p, 4)


def test_web_and_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("t", _mapped(span=0))
    c = TestClient(web.app)
    v = c.get("/api/projects/t/atlas").json()["travel"]
    assert v["scale"] is None and v["moves"] == [] and [m["id"] for m in v["modes"]] == list(travel.MODES)
    r = c.put("/api/projects/t/atlas/travel", json={"enabled": True, "mode": "horse", "span_km": 600})
    assert r.status_code == 200 and r.json()["atlas"]["span_km"] == 600
    v = c.get("/api/projects/t/atlas").json()["travel"]
    assert [m["level"] for m in v["moves"]] == ["fast", "fast"]
    assert c.put("/api/projects/t/atlas/travel", json={"mode": "dragon"}).status_code == 400
    r = c.put("/api/projects/t/atlas/travel/ok", json={"cid": "hero", "episode": 3})
    assert r.json()["atlas"]["travel"]["ok"] == ["hero:3"]

    monkeypatch.setattr(store, "ROOT", tmp_path)
    cli.main(["map", "t", "travel"])
    out = capsys.readouterr().out
    assert "가장 빠른 탈것: 말" in out and "1~2화 [너무 빨라요] 서윤: 등대 → 흑송촌" in out and "2~3화 [너무 빨라요 · 괜찮아요로 둠]" in out
    cli.main(["map", "t", "travel", "--mode", "car", "--unok", "hero:3"])
    out = capsys.readouterr().out
    assert "걸린 이동이 없어요" in out and store.load("t").atlas.travel.ok == []
