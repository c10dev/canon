"""스킬 · 특성 도감(canon/abilities.py) 테스트: 조각 나누기, 상태창 잇기, 얻은 화 계산, 작가 편집, CLI, 웹. 실행: python -m pytest tests"""
import importlib

import pytest
from fastapi.testclient import TestClient

from canon import abilities, cli, pipeline, statwin, store
from canon.schema import Ability, AbilityGrade, StatValue

from .test_statwin import _play
from .test_storylines import _short


def _project():
    p = _short(8)
    statwin.set_stats(p, "hero", [StatValue(name="레벨", value="1"), StatValue(name="스킬", value="화염구 Lv3, 은신"),
                                  StatValue(name="인벤토리", value="포션 2개, 롱소드")])
    statwin.set_stats(p, "ally", [StatValue(name="특성", value="강철 피부")])
    return p


def _ab(name, **kw):
    return Ability(id="", name=name, **kw)


def test_split_and_key():
    assert abilities.split("화염구 Lv4") == ("화염구", "Lv4")
    assert abilities.split("롱소드 +2 (A급)") == ("롱소드", "+2 (A급)")
    assert abilities.split("청풍검법 3성") == ("청풍검법", "3성") and abilities.split("Lv3") == ("Lv3", "")
    assert abilities.key("화염 구 lv2") == abilities.key("화염구")


def test_lists_link_by_name_and_skip_inventory():
    p = _project()
    assert abilities.list_stats(p) == {"스킬", "특성"}  # 한 조각뿐인 특성도 이름으로, 인벤토리는 빼고
    fire = abilities.upsert(p, _ab("화염구", aliases=["파이어볼"], grades=[AbilityGrade(grade="Lv3", effect="반경 3m")]))
    assert abilities.find(p, "파이어볼 Lv9") is fire and abilities.find(p, "화염구 Lv3", "스킬") is fire
    assert abilities.owners(p, fire) == [{"character_id": "hero", "stat": "스킬", "item": "화염구 Lv3", "grade": "Lv3"}]
    assert abilities.grade_effect(fire, "lv 3") == "반경 3m"
    skin = abilities.upsert(p, _ab("강철 피부", stat="스킬"))  # 정한 상태창 항목의 조각만 잇는다
    assert abilities.owners(p, skin) == [] and abilities.find(p, "강철 피부", "특성") is None
    assert [(m["name"], m["stat"]) for m in abilities.unlinked(p)] == [("은신", "스킬"), ("강철 피부", "특성")]
    abilities.upsert(p, _ab("포션", stat="인벤토리"))  # 인벤토리는 도감 항목이 가리키면 잇는다
    assert "인벤토리" in abilities.list_stats(p) and ("롱소드", "인벤토리") in [(m["name"], m["stat"]) for m in abilities.unlinked(p)]


def test_acquired_from_stat_log_and_revert():
    p = _play(_project(), 1, 2)
    fire = abilities.upsert(p, _ab("화염구"))
    poison = abilities.upsert(p, _ab("독 내성"))
    st = p.state_of("hero")
    statwin.merge(p, st, [StatValue(name="스킬", value="+화염구 Lv4, +독 내성")], 3)
    statwin.merge(p, st, [StatValue(name="스킬", value="-독 내성")], 4)
    statwin.merge(p, st, [StatValue(name="스킬", value="+독 내성")], 5)
    assert [(h["episode"], h["kind"]) for h in abilities.history(p, "hero", fire)] == [(0, "얻음"), (3, "바뀜")]
    assert abilities.acquired(p, "hero", fire) == 0  # 등급만 바뀐 것은 얻은 화를 바꾸지 않는다
    assert [(h["episode"], h["kind"]) for h in abilities.history(p, "hero", poison)] == [(3, "얻음"), (4, "잃음"), (5, "얻음")]
    assert abilities.acquired(p, "hero", poison) == 5 and abilities.acquired(p, "ally", poison) is None
    statwin.revert(p, 3)  # 기록이 잘리면 계산도 따라간다
    assert [(h["episode"], h["kind"]) for h in abilities.history(p, "hero", poison)] == [(3, "얻음")]
    pipeline.revert(p, 1)
    assert abilities.history(p, "hero", poison) == [] and abilities.acquired(p, "hero", fire) == 0


def test_upsert_rules():
    p = _project()
    a = abilities.upsert(p, _ab("화염구 Lv3", aliases=["화염구", " 불덩이 ", "불덩이"], description=" 불 "))
    assert (a.id, a.name, a.aliases, a.description) == ("ab-01", "화염구", ["불덩이"], "불")
    with pytest.raises(ValueError):
        abilities.upsert(p, _ab("불덩이"))  # 다른 이름과 겹침
    with pytest.raises(ValueError):
        abilities.upsert(p, _ab("불덩이", stat="칭호"))  # 상태창 항목을 정하지 않은 항목과는 어느 목록이든 겹친다


def test_upsert_keeps_source_and_validates():
    p = _project()
    a = abilities.upsert(p, _ab("은신", stat="스킬"))
    p.abilities[0].source, p.abilities[0].created_ep = "ai", 3
    b = abilities.upsert(p, a.model_copy(update={"effect": "숨는다", "source": "author", "created_ep": 0}))
    assert (b.effect, b.source, b.created_ep) == ("숨는다", "ai", 3)  # 고쳐도 어디서 생겼는지는 남긴다
    abilities.upsert(p, _ab("은신", stat="칭호"))  # 상태창 항목이 다르면 같은 이름도 된다
    with pytest.raises(ValueError):
        abilities.upsert(p, _ab(" "))
    with pytest.raises(KeyError):
        abilities.remove(p, "ab-99")
    abilities.remove(p, a.id)
    assert [x.stat for x in p.abilities] == ["칭호"]


def test_cli_and_web(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    importlib.reload(store)
    p = _project()
    abilities.upsert(p, _ab("화염구", effect="불덩이", grades=[AbilityGrade(grade="Lv3", effect="반경 3m")]))
    store.save("ab", p)
    cli.main(["abilities", "ab"])
    out = capsys.readouterr().out
    assert "효과: 불덩이" in out and "서윤: 화염구 Lv3 (시작 때 얻음)" in out and "도감에 없는 항목: 은신(스킬), 강철 피부(특성)" in out

    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    v = c.get("/api/projects/ab/abilities").json()
    assert v["lists"] == ["스킬", "특성"] and v["abilities"][0]["owners"][0]["acquired"] == 0
    r = c.get("/api/projects/ab/abilities/lookup", params={"item": "화염구 Lv3", "cid": "hero", "stat": "스킬"}).json()
    assert (r["name"], r["grade"], r["grade_effect"], r["acquired"]) == ("화염구", "Lv3", "반경 3m", 0)
    assert c.get("/api/projects/ab/abilities/lookup", params={"item": "은신"}).json()["ability"] is None
    pj = c.put("/api/projects/ab/abilities", json={"id": "", "name": "은신", "stat": "스킬", "cost": "움직이면 풀린다"}).json()
    assert [a["name"] for a in pj["abilities"]] == ["화염구", "은신"]
    assert c.put("/api/projects/ab/abilities", json={"id": "", "name": "화염구"}).status_code == 400
    pj = c.delete(f"/api/projects/ab/abilities/{pj['abilities'][1]['id']}").json()
    assert [a["name"] for a in pj["abilities"]] == ["화염구"]
