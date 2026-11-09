"""반영 뒤 지금 상태 고치기(canon/stateedit.py) 테스트 (mock LLM): 작가 기록 합치기, 스냅샷 맞추기, 0화, 화 되돌리기, 웹 라우트. 실행: python -m pytest tests"""

import re
from pathlib import Path

import pytest

from canon import autorun, pipeline, prompts, stateedit, store
from canon.mock import MockLLM

from .test_storylines import _short

LLM = MockLLM()


def _play(p, frm, upto):
    for n in range(frm, upto + 1):
        pipeline.confirm_plot(p, n)
        p.episode(n).text = pipeline.write_episode(LLM, p, n)
        p.episode(n).status = "written"
        pipeline.apply_delta(p, pipeline.extract_state(LLM, p, n))
    return p


def _snap_state(p, n, cid="hero"):
    return next(s for s in p.snapshot(n).states if s.character_id == cid)


def test_edit_after_apply_records_and_fixes_snapshot():
    p = _play(_short(8), 1, 2)
    was = p.state_of("hero").location
    recs = stateedit.set_state(p, "hero", {"location": " 등대 꼭대기 ", "emotional_state": None})
    assert p.state_of("hero").location == "등대 꼭대기"  # 앞뒤 빈칸은 지운다
    assert [(r.episode, r.field, r.before, r.after) for r in recs] == [(2, "location", was, "등대 꼭대기")]
    assert _snap_state(p, 2).location == "등대 꼭대기"  # 그 화 스냅샷도 맞춘다
    assert "등대 꼭대기" in prompts.episode_prompt(p, 3)  # 다음 화 프롬프트에 들어간다
    # 같은 화 뒤에 또 고치면 한 기록으로 합치고, 반영 값으로 돌아오면 기록을 지운다
    stateedit.set_state(p, "hero", {"location": "부두"})
    assert [(r.before, r.after) for r in p.state_log] == [(was, "부두")]
    stateedit.set_state(p, "hero", {"location": was})
    assert p.state_log == [] and stateedit.edited(p, "hero") == [] and _snap_state(p, 2).location == was


def test_blank_clears_and_same_value_is_not_recorded():
    p = _play(_short(8), 1, 1)
    goal = p.state_of("hero").current_goal
    assert stateedit.set_state(p, "hero", {"current_goal": goal}) == [] and p.state_log == []
    stateedit.set_state(p, "hero", {"attire": "  "})
    assert p.state_of("hero").attire == ""


def test_before_first_apply_edits_episode_zero():
    p = _short(8)
    assert p.snapshot(0) is None
    stateedit.set_state(p, "hero", {"location": "기차역"})
    assert [(r.episode, r.after) for r in p.state_log] == [(0, "기차역")] and p.snapshot(0) is None
    _play(p, 1, 1)  # 첫 반영이 만드는 스냅샷 0 에 고친 값이 들어간다
    assert _snap_state(p, 0).location == "기차역"


def test_revert_cuts_later_records_only():
    p = _play(_short(8), 1, 1)
    stateedit.set_state(p, "hero", {"emotional_state": "1화 뒤 작가"})
    _play(p, 2, 3)
    stateedit.set_state(p, "hero", {"emotional_state": "3화 뒤 작가"})
    assert [r.episode for r in p.state_log] == [1, 3]
    pipeline.revert(p, 1)
    assert [r.episode for r in p.state_log] == [1]  # 뒤 기록을 1화로 옮기지 않고 자른다
    assert p.state_of("hero").emotional_state == "1화 뒤 작가"  # 1화 스냅샷에 고친 값이 들어 있다
    assert [r.after for r in stateedit.edited(p, "hero")] == ["1화 뒤 작가"]


def test_rejects_unknown_character_and_field():
    p = _short(8)
    with pytest.raises(KeyError):
        stateedit.set_state(p, "nobody-x", {"location": "어디"})
    with pytest.raises(ValueError):
        stateedit.set_state(p, "hero", {"knows": "비밀"})


def test_fields_match_cast_card():
    js = (Path(stateedit.__file__).parent / "static" / "cast.js").read_text(encoding="utf-8")
    sheet = re.search(r"const SHEET_STATE = (\[.*?\]);", js).group(1)
    assert re.findall(r"\['([^']+)', '([a-z_]+)'\]", sheet) == [(v, k) for k, v in stateedit.FIELDS.items()]
    assert set(re.findall(r"(\w+): '", re.search(r"const STATE_OBJ = \{(.*?)\};", js).group(1))) == set(stateedit.FIELDS)


def test_web_route(client, monkeypatch):
    p = _play(_short(8), 1, 1)
    store.save("se", p)
    r = client.put("/api/projects/se/state/hero", json={"location": "옥상"})
    assert r.status_code == 200
    got = r.json()
    assert next(s for s in got["states"] if s["character_id"] == "hero")["location"] == "옥상"
    assert [(x["episode"], x["field"], x["after"]) for x in got["state_log"]] == [(1, "location", "옥상")]
    assert _snap_state(store.load("se"), 1).location == "옥상"
    # 화면의 작품 저장은 기록을 고치지 않는다 (옛 사본이 기록을 지우지 않게)
    got["state_log"] = []
    assert client.put("/api/projects/se", json=got).status_code == 200
    assert len(store.load("se").state_log) == 1
    assert client.put("/api/projects/se/state/nobody-x", json={"location": "옥상"}).status_code == 400
    monkeypatch.setattr(autorun, "active", lambda name: True)
    r = client.put("/api/projects/se/state/hero", json={"location": "지하"})
    assert r.status_code == 400 and "자동 집필" in r.json()["detail"]
    assert store.load("se").state_of("hero").location == "옥상"


def test_old_project_reads_without_state_log():
    from canon.schema import Project
    assert Project.model_validate({}).state_log == []


def test_cast_frames_replay_edit_when_snapshot_is_pruned():
    from canon import cast
    p = _play(_short(8), 1, 1)
    stateedit.set_state(p, "hero", {"location": "1화 뒤 고친 곳"})
    _play(p, 2, 2)
    p.snapshots = [s for s in p.snapshots if s.episode != 1]  # 장편 스냅샷 줄이기처럼 1화 스냅샷이 없다
    f1 = next(f for f in cast.frames(p) if f["episode"] == 1)
    assert next(s for s in f1["states"] if s["character_id"] == "hero")["location"] == "1화 뒤 고친 곳"
