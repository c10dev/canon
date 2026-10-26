"""상태창 수치(canon/statwin.py) 테스트 (mock LLM): 상대값 계산, 변경안 반영, 작가 수정, 되돌리기, 화별 비교표, 프롬프트 규칙, CLI, 웹. 실행: python -m pytest tests"""
import importlib

from fastapi.testclient import TestClient

from canon import cli, pipeline, prompts, statwin, store
from canon.mock import MockLLM
from canon.schema import StatValue

from .test_storylines import _short

LLM = MockLLM()


def _play(p, frm, upto):
    for n in range(frm, upto + 1):
        pipeline.confirm_plot(p, n)
        p.episode(n).text = pipeline.write_episode(LLM, p, n)
        p.episode(n).status = "written"
        pipeline.apply_delta(p, pipeline.extract_state(LLM, p, n))
    return p


def _stats(p, cid="hero"):
    return {s.name: s.value for s in p.state_of(cid).stats}


def test_resolve():
    assert statwin.resolve("10", "+3") == "13"
    assert statwin.resolve("1,200", "-200") == "1,000"  # 자릿수 쉼표는 이전 값을 따른다
    assert statwin.resolve("1.5", "+0.25") == "1.75"
    assert statwin.resolve("B급", "+1") == "+1"  # 이전 값이 숫자가 아니면 적은 그대로
    assert statwin.resolve("3", "A급") == "A급"


# (이전 값, 적은 값, 새 값). tests/test_statwin_js.py 가 statwin.js 의 swResolve 도 같은지 본다
RESOLVE_CASES = [
    ("10", "+3", "13"), ("1,200", "-200", "1,000"), ("1.5", "+0.25", "1.75"), ("B급", "+1", "+1"), ("3", "A급", "A급"),
    ("", "+3", "+3"), ("5", "-5", "0"), ("2", "-3.5", "-1.5"), ("10", "-", "-"),
    # 단위가 붙은 수치
    ("1200골드", "+300", "1500골드"), ("1,200골드", "+300골드", "1,500골드"), ("1,200 G", "-1,500", "-300 G"),
    ("₩5000", "+500", "₩5500"), ("Lv.3", "+1", "Lv.4"), ("1200골드", "+3G", "+3G"), ("999,500원", "+700", "1,000,200원"),
    # 목록 항목
    ("화염구 Lv3, 은신", "+독 내성", "화염구 Lv3, 은신, 독 내성"),
    ("화염구 Lv3, 은신", "+화염구 Lv4, -은신", "화염구 Lv4"),
    ("", "+화염구, +은신", "화염구, 은신"),
    ("검 · 방패", "+포션 3개", "검 · 방패 · 포션 3개"),
    ("포션 3개, 검", "+포션 5개", "포션 5개, 검"),
    ("화염구(B급)", "+화염구(A급)", "화염구(A급)"),
    ("화염구, 은신", "-없는 것", "화염구, 은신"),
    ("화염구, 은신", "-은신, -화염구", ""),
    ("화염구 Lv3", "화염구 Lv5", "화염구 Lv5"),
    ("1200", "+독", "+독"), ("화염구", "+독, 은신", "+독, 은신"),
]


def test_resolve_units_and_lists():
    for before, value, want in RESOLVE_CASES:
        assert statwin.resolve(before, value) == want, (before, value)


def test_list_items_through_review_and_timeline():
    p = _short(8)
    statwin.set_stats(p, "hero", [StatValue(name="스킬", value="화염구 Lv3, 은신"), StatValue(name="골드", value="1,200골드")])
    _play(p, 1, 1)
    pipeline.confirm_plot(p, 2)
    p.episode(2).text = pipeline.write_episode(LLM, p, 2)
    p.episode(2).status = "written"
    d = pipeline.extract_state(LLM, p, 2)
    hero = next(u for u in d.character_updates if u.character_id == "hero")
    hero.stats = [StatValue(name="스킬", value="+독 내성, -은신"), StatValue(name="골드", value="+300")]
    pipeline.apply_delta(p, d)
    assert _stats(p)["스킬"] == "화염구 Lv3, 독 내성" and _stats(p)["골드"] == "1,500골드"
    ch = statwin.timeline(p, "hero")["columns"][-1]["changed"]
    assert ch["스킬"]["added"] == ["독 내성"] and ch["스킬"]["removed"] == ["은신"]
    assert "added" not in ch["골드"]  # 수치는 이전 → 새 값만
    out = statwin.describe(p, "hero")
    assert "스킬 +독 내성 -은신" in out and "골드 1,200골드 → 1,500골드" in out


def test_inventory_splits_attire_rule():
    p = _short(8)
    statwin.set_stats(p, "hero", [StatValue(name="레벨", value="1")])
    assert not statwin.inventory(p) and statwin.check_rule(p) == "" and "attire 에는 입고 있거나" not in statwin.state_rule(p)
    statwin.set_stats(p, "hero", [StatValue(name="레벨", value="1"), StatValue(name="인벤토리", value="포션 3개")])
    assert statwin.inventory(p)
    assert "attire 에는 입고 있거나" in statwin.state_rule(p)
    assert "attire 에 없어도" in statwin.write_rule(p) and "인벤토리:" in statwin.check_rule(p)
    _play(p, 1, 1)
    assert "인벤토리:" in prompts.check_prompt(p, 1) and "attire 에는 입고 있거나" in prompts.state_prompt(p, 1)


def test_off_until_author_sets_stats():
    p = _play(_short(8), 1, 1)
    assert not statwin.enabled(p) and p.stat_log == [] and _stats(p) == {}
    assert statwin.write_rule(p) == "" and statwin.state_rule(p) == "" and statwin.check_rule(p) == ""
    assert "상태창" not in prompts.episode_prompt(p, 2)


def test_ai_updates_author_fix_and_timeline():
    p = _short(8)
    statwin.set_stats(p, "hero", [StatValue(name="레벨", value="1"), StatValue(name="힘", value="10"), StatValue(name="스킬", value="")])
    assert _stats(p) == {"레벨": "1", "힘": "10", "스킬": ""}  # 값이 빈 항목도 틀로 남는다
    assert statwin.enabled(p) and "stats" in statwin.state_rule(p)
    assert "레벨: 1" in statwin.write_rule(p) and "스킬" not in statwin.render(p, "hero")
    _play(p, 1, 3)  # mock 은 화마다 레벨 +1
    assert _stats(p)["레벨"] == "4"
    statwin.set_stats(p, "hero", [StatValue(name="레벨", value="+3"), StatValue(name="스킬", value="불꽃")])
    assert _stats(p) == {"레벨": "7", "스킬": "불꽃"}
    assert {s.name: s.value for s in p.snapshot(3).states[0].stats} == {"레벨": "7", "스킬": "불꽃"}  # 그 화 스냅샷도 맞춘다
    t = statwin.timeline(p, "hero")
    assert [c["episode"] for c in t["columns"]] == [0, 1, 2, 3]
    last = t["columns"][-1]
    assert last["changed"]["레벨"] == {"before": "3", "source": "both"}  # AI 3 → 4, 작가 4 → 7
    assert last["changed"]["힘"]["source"] == "author" and "힘" not in {k for k, v in last["values"].items() if v}
    assert "4화" not in statwin.describe(p, "hero") and "레벨 3 → 7 (승인 뒤 작가가 고침)" in statwin.describe(p, "hero")


def test_revert_restores_stats_and_log():
    p = _short(8)
    statwin.set_stats(p, "hero", [StatValue(name="레벨", value="1")])
    _play(p, 1, 3)
    pipeline.revert(p, 1)
    assert _stats(p) == {"레벨": "2"} and max(r.episode for r in p.stat_log) == 1


def test_set_stats_rejects_duplicates_and_unknown():
    p = _short(8)
    for rows, cid in (([StatValue(name="레벨", value="1"), StatValue(name="레벨", value="2")], "hero"), ([], "nobody-x")):
        try:
            statwin.set_stats(p, cid, rows)
            raise AssertionError("막혀야 한다")
        except (ValueError, KeyError):
            pass


def test_cli_and_web(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    importlib.reload(store)
    store.save("sw", _short(8))
    cli.main(["statwin", "sw", "hero", "--set", "레벨=5", "--set", "HP=100"])
    cli.main(["statwin", "sw", "hero", "--set", "HP=-30"])
    out = capsys.readouterr().out
    assert "HP: 70" in out
    assert _stats(store.load("sw")) == {"레벨": "5", "HP": "70"}

    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    r = c.get("/api/projects/sw/statwin/hero").json()
    assert r["names"] == ["레벨", "HP"] and "HP: 70" in r["text"] and "growth" in r["presets"]
    p = c.put("/api/projects/sw/statwin/hero", json={"stats": [{"name": "레벨", "value": "6"}]}).json()
    assert [s["name"] for s in next(s for s in p["states"] if s["character_id"] == "hero")["stats"]] == ["레벨"]
    assert c.put("/api/projects/sw/statwin-template", json={"template": "없음"}).status_code == 400
    c.put("/api/projects/sw/statwin-template", json={"template": "[{name}]\n{rows}", "row": "· {key} {value}"})
    assert c.get("/api/projects/sw/statwin/hero").json()["text"] == "[서윤]\n· 레벨 6"
