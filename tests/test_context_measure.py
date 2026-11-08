"""컨텍스트 놓침 실측 스크립트 (scripts/context_measure.py, docs/context/specs/01-measure.md 의 '시험'). mock LLM, LLM 호출 없음."""
import importlib.util
from pathlib import Path

from canon import pipeline, store
from canon.mock import MockLLM
from canon.schema import Character, CharacterState, StoryElement
from tests.test_serial import _plan_arc, _serial

LLM = MockLLM()
SMITH = Character(id="smith", name="마르타 부인", role="대장장이", tier="support", speech_style="걸걸한 반말.")
EDITED = "3화 본문. 서윤은 길을 걸었다. 고쳐 쓴 본문이다."


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "context_measure.py"
    spec = importlib.util.spec_from_file_location("context_measure", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _project():
    """1~4화를 쓰고 반영한 장편. 대장장이는 어느 화 플롯에도 없고 3화 최종 본문(final_text)에만 이름이 나온다."""
    p = _serial()
    a = _plan_arc(p)
    p.characters.append(SMITH.model_copy())
    p.states.append(CharacterState(character_id="smith", location="북문 대장간"))
    for n in range(a.start_ep, a.start_ep + 4):
        pipeline.confirm_plot(p, n)
        e = p.episode(n)
        e.text, e.status = f"{n}화 본문. 서윤은 길을 걸었다.", "written"
        if n == 3:
            e.text = "3화 본문. 서윤은 길을 걸었다. 마르타가 망치를 내려놓았다."
        pipeline.apply_delta(p, pipeline.extract_state(LLM, p, n))
    e = p.episode(3)
    e.final_text, e.text = e.text, EDITED  # 반영 뒤 고친 화: 반영의 바탕은 final_text
    return p


def test_rows_miss_and_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _project()
    p.snapshots = [s for s in p.snapshots if s.episode != 0]  # 0화 스냅샷이 없으면 1화는 근사로만 센다
    store.save("측정", p)
    raw = (tmp_path / "측정" / "project.json").read_text(encoding="utf-8")
    cm = _script()
    r = cm.run_project("측정")
    assert r["unchanged"] and (tmp_path / "측정" / "project.json").read_text(encoding="utf-8") == raw
    exact = {e["episode"]: e for e in r["episodes"]["exact"]}
    approx = {e["episode"]: e for e in r["episodes"]["approx"]}
    assert sorted(approx) == [1, 2, 3, 4] and sorted(exact) == [2, 3, 4]  # 1화는 0화 스냅샷이 없어 정확한 재구성에서 빠진다
    for e in [*exact.values(), *approx.values()]:
        assert e["items"] and not e["align"] and not e["mutated"]  # 옮겨 쓴 선택이 만든 프롬프트의 블록과 같다
    smith = next(it for it in exact[3]["items"] if it["id"] == "smith")
    assert smith["appeared"] and not smith["selected"] and smith["appeared_alt"] is False  # final_text 로 셌다 (text 에는 없다)
    assert exact[3]["final_differs"]
    assert not next(it for it in exact[2]["items"] if it["id"] == "smith")["appeared"]
    main = next(it for it in exact[3]["items"] if it["kind"] == "char" and it["always"])
    assert main["selected"] and "설정" in main["blocks"]


def test_later_place_is_not_in_earlier_episode(tmp_path, monkeypatch):
    """4화 반영이 본문에서 등록한 장소는 2 · 3 · 4화를 다시 만들 때 없다. 안 쓴 5화 플롯에 이름이 있어 revert 가 '플롯에서 나옴'으로 남겨도."""
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _project()
    p.elements.append(StoryElement(id="el-forge", kind="장소", name="북문 대장간", found_in="본문", found_ep=4))
    p.episode(5).plot.summary += " 북문 대장간에 들른다."
    p.episode(3).final_text += " 북문 대장간 앞을 지났다."
    store.save("측정", p)
    r = _script().run_project("측정")
    for e in r["episodes"]["exact"] + r["episodes"]["approx"]:
        assert all(it["id"] != "el-forge" for it in e["items"])


def test_sticky_and_scope_simulation(tmp_path, monkeypatch):
    """3화 플롯 글에 이름이 나온 조연은 4화에 유지 1화로 들어가고, 지금 범위 흉내는 실제 선택과 같다."""
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _project()
    p.episode(3).plot.summary += " 마르타 부인이 검을 건넨다."
    p.episode(4).text += " 마르타가 웃었다."
    store.save("측정", p)
    cm = _script()
    r = cm.run_project("측정")
    sim = r["sim"]["exact"]
    row = lambda key, n: next(x for x in sim[key] if x["episode"] == n)  # noqa: E731
    assert "smith" not in row("now|none", 3)["miss"]  # 플롯 글에 이름이 나와 이름으로 넣었다
    assert "smith" in row("now|none", 4)["miss"]
    assert "smith" not in row("now|sticky1", 4)["miss"] and row("now|sticky1", 4)["why"]["smith"] == "sticky"
    assert all(not e["align"] for e in r["episodes"]["exact"])  # simulate-now 도 실제 선택과 같다
