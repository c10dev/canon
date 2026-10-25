"""새로 나온 장소 테스트 (mock LLM): 상태 변경안 · 플롯이 낸 새 장소를 인과율 '장소' 요소로 등록, 비슷한 이름 경고,
반영 취소, 장편 예산. 실행: python -m pytest tests"""
import json

from canon import autorun, elements, naming, pipeline, prompts
from canon.mock import NEW_CAST_EP, NEW_PLACE, MockLLM
from canon.schema import NewPlace, Project, StateDelta, StoryElement

from .test_passage import _written
from .test_web import client  # noqa: F401  (pytest fixture)

LLM = MockLLM()
TEXT = "서윤은 흑송마을 어귀에서 숨을 골랐다. 고개 너머로 백야천이 흘렀다. 등대 불빛이 멀리 보였다."


def _project(total=6) -> Project:
    """1화를 쓴 단편 (설정 장소: 등대, 수산시장 · 이미 있는 장소 요소: 흑송촌)."""
    p = Project()
    p.meta.title, p.meta.target_episodes = "등대", total
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    p.arc = pipeline.plan_arc(LLM, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, total))
    p.elements.append(StoryElement(id="el-01", kind="장소", name="흑송촌", description="산골 마을"))
    e = p.episode(1)
    e.text, e.status = TEXT, "written"
    return p


def _delta(p: Project, n: int = 1) -> StateDelta:
    d = StateDelta(episode=n, summary="요약", new_places=[
        NewPlace(name="등대", kind="등대"),                               # 설정 장소 칸에 이미 있음
        NewPlace(name="소금창고", kind="창고"),                            # 본문에 없음
        NewPlace(name="백야천", kind="강", description="고개 너머로 흐르는 강"),
        NewPlace(name="흑송마을", kind="마을"),                            # 흑송촌과 같은 갈래 끝말만 다름
        NewPlace(name="백야천", kind="강"),                                # 같은 변경안 안에서 겹침
    ])
    pipeline.clean_delta(p, d)
    return d


def test_similar_place_names():
    assert naming.similar_place("흑송마을", ["흑송촌", "등대"]) == "흑송촌"
    assert naming.similar_place("흑송 마을", ["흑송촌"]) == "흑송촌"
    assert naming.similar_place("흑송", ["흑송촌"]) == "흑송촌"       # 끝말 없이 부른 이름
    assert naming.similar_place("흑송산", ["흑송촌"]) == ""            # 갈래가 다르면 다른 곳
    assert naming.similar_place("흑송촌", ["흑송촌"]) == ""            # 같은 이름은 여기서 보지 않는다 (이미 있는 이름으로 뺀다)
    assert naming.place_key("흑송 · 마을") == "흑송마을"


def test_clean_keeps_only_new_places_in_text_and_warns_similar():
    p = _project()
    d = _delta(p)
    assert [x.name for x in d.new_places] == ["백야천", "흑송마을"]
    assert d.warnings == ["새 장소 '흑송마을'은 이미 있는 '흑송촌'과 이름이 비슷해요. 같은 곳이면 한 이름으로 맞추세요"]
    assert "[이미 있는 장소]" in prompts.state_prompt(p, 1) and "흑송촌" in prompts.state_prompt(p, 1)


def test_apply_registers_place_element_and_revert_removes_it():
    p = _project()
    pipeline.apply_delta(p, _delta(p))
    el = next(x for x in p.elements if x.name == "백야천")
    assert (el.kind, el.since_ep, el.found_in, el.found_ep, el.context) == ("장소", 0, "본문", 1, "auto")
    assert el.description == "고개 너머로 흐르는 강"  # 설명에 종류가 있으면 덧붙이지 않는다
    assert "백야천" in naming.known_places(p) and p.history[-1].new_places

    # 뒤 화 플롯에 나오면 그 화 본문 프롬프트에 한 줄로 들어간다
    p.episode(3).plot.events.append("백야천을 건넌다")
    block = elements.episode_block(p, 3)
    assert "- [장소] 백야천: 고개 너머로 흐르는 강 (1화에 처음 나옴)" in block
    assert "백야천" not in elements.episode_block(p, 2)

    # 1화부터 반영을 취소하면, 안 쓴 3화 플롯에 나오는 백야천은 '플롯에서 나옴'으로 남고 흑송마을은 빠진다
    pipeline.revert(p, 0)
    assert "흑송마을" not in [x.name for x in p.elements]
    el = next(x for x in p.elements if x.name == "백야천")
    assert (el.found_in, el.found_ep) == ("플롯", 3)


def test_author_edited_place_survives_revert():
    p = _project()
    pipeline.apply_delta(p, _delta(p))
    el = next(x for x in p.elements if x.name == "흑송마을")
    el.characters = ["hero"]  # 작가가 관련 인물을 더했다
    pipeline.revert(p, 0)
    assert any(x.name == "흑송마을" for x in p.elements)


def test_plot_place_candidate_registered_on_confirm():
    p = _project()
    assert [x.name for x in p.place_candidates] == [NEW_PLACE.name]
    assert "[새 장소 후보" in prompts.plot_prompt(p, NEW_CAST_EP + 1, NEW_CAST_EP + 2)
    pipeline.confirm_plot(p, NEW_CAST_EP)
    el = next(x for x in p.elements if x.name == NEW_PLACE.name)
    assert (el.found_in, el.found_ep, el.kind) == ("플롯", NEW_CAST_EP, "장소")
    assert p.place_candidates == []

    # 후보가 나오는 플롯을 다시 쓰면 후보도 사라진다
    q = _project()
    q.episode(NEW_CAST_EP).plot.events = ["다른 사건"]
    pipeline.sync_candidates(q)
    assert q.place_candidates == []


def test_restate_adds_places():
    p = _project()
    pipeline.apply_delta(p, StateDelta(episode=1, summary="요약"))
    out = pipeline.apply_restate(p, _delta(p))
    assert out["places"] == 2 and {"백야천", "흑송마을"} <= {x.name for x in p.elements}
    assert [x.name for x in p.history[-1].new_places] == ["백야천", "흑송마을"]


def test_serial_place_block_has_budget():
    p = _project()
    p.meta.form = "serial"
    for i in range(400):
        p.elements.append(StoryElement(id=f"el-p{i}", kind="장소", name=f"장소{i:03d}골", description="어딘가의 골짜기 " * 3,
                                       found_in="본문", found_ep=i % 50 + 1))
    p.episode(1).plot.events.append("장소000골에 간다")
    block = elements.plan_block(p)
    assert "흑송촌" in block                      # 작가가 더한 요소는 늘 넣는다
    assert "곳은 덜 관련돼 뺐다" in block
    assert len(block) < 4_000
    assert "장소000골" in elements.active_block(p, 1)  # 검수는 그 화에 나오는 곳 먼저
    assert "곳은 이번 화와 멀어 뺐습니다" in prompts.places_line(p, "")


def test_autorun_keeps_places_registered_by_state():
    p = _project()
    disk = p.model_copy(deep=True)
    pipeline.apply_delta(disk, _delta(disk))
    mine = p.model_copy(deep=True)  # 반영 전에 읽은 화면
    autorun.protected("nope", disk, mine)
    assert {"백야천", "흑송마을"} <= {x.name for x in mine.elements}


def test_web_chat_json_import_and_apply(client):  # noqa: F811
    _written(client)  # 1화 본문: 바람이 불었다. 서윤은 등대 앞에 섰다. ...
    client.put("/api/projects/lh/episodes/1/text", json={"text": "서윤은 갈매기 다방에 들렀다. 등대 앞에 섰다."})
    raw = json.dumps({"summary": "요약", "new_places": [{"name": "갈매기 다방", "kind": "가게"}, {"name": "등대"}, {"name": "없는 곳"}]})
    d = client.post("/api/projects/lh/episodes/1/state/parse", json={"raw": raw}).json()
    assert [x["name"] for x in d["new_places"]] == ["갈매기 다방"]
    p = client.post("/api/projects/lh/episodes/1/apply", json=d).json()
    el = next(x for x in p["elements"] if x["name"] == "갈매기 다방")
    assert (el["kind"], el["found_in"], el["found_ep"]) == ("장소", "본문", 1)
