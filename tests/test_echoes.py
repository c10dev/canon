"""최근 화에서 되풀이한 구절 (canon/echoes.py, prompts.echo_block, Settings.recent_echoes): 여러 화에 그대로 나온 서술 구절을 찾고,
이름 · 호칭 · 확정 사실 · 대사는 빼고, 장편 본문 쓰기 요청의 뒤쪽 블록에만 넣는지. 웹 설정과 설정 화면 줄도 본다.

    python -m pytest tests/test_echoes.py
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from canon import echoes, prompts
from canon.schema import AddressForm, Character, Episode, EpisodePlot, Meta, Project, StoryArc

from .jsvm import needs_node, run_js

BODY = "한 손에 다 잡히지 않는 {adj} 가슴이 흔들렸다. 서윤은 창가에 섰다. 바람이 낡은 창틀을 덜컹덜컹 흔들었다."
FACT = "서윤의 왼쪽 손목 안쪽에 작은 흉터가 있다."
SCAR = "왼쪽 손목 안쪽의 하얀 흉터가 드러났다."
TALK = "\"가만히 있어 봐, 금방 끝나.\""
CALL = "선배님 하고 부르는 목소리가 복도를 울렸다."


def _plot(n):
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=[],
                       emotional_shift="", ending_hook="")


def _project(texts, form="serial") -> Project:
    """texts[i] 가 i+1 화 본문. 마지막 다음 화는 플롯만 확정."""
    p = Project(meta=Meta(title="t", form=form))
    p.story_arcs = [StoryArc(number=1, title="첫 아크", start_ep=1, end_ep=20, goal="g")]
    p.characters = [Character(id="hero", name="강서윤", role="주인공"), Character(id="sub", name="민도현", role="조연")]
    p.address_forms = [AddressForm(speaker="sub", listener="hero", calls="선배님")]
    p.facts = [FACT]
    for i, t in enumerate(texts, 1):
        p.episodes.append(Episode(plot=_plot(i), status="finalized", text=t))
    p.episodes.append(Episode(plot=_plot(len(texts) + 1), status="confirmed"))
    return p


def _texts(k=3):
    adjs = ["말랑한", "묵직한", "빵빵한", "말랑한", "묵직한"]
    return [" ".join([BODY.format(adj=adjs[i]), SCAR, TALK, CALL, f"{i + 1}화에만 있는 문장이 이어졌다."]) for i in range(k)]


def test_finds_phrases_across_episodes_and_skips_canon():
    p = _project(_texts())
    rows = dict(echoes.recent(p, 4))
    # 형용사가 화마다 갈리면 앞의 같은 구절에서 멈춘다
    assert rows["한 손에 다 잡히지 않는"] == [1, 2, 3]
    assert rows["바람이 낡은 창틀을 덜컹덜컹 흔들었다"] == [1, 2, 3]
    text = " / ".join(rows)
    assert "서윤" not in text and "선배님" not in text  # 이름 · 호칭이 든 구절은 뺀다
    assert "손목 안쪽" not in text  # 확정 사실에 조사만 다르게 적힌 구절은 뺀다 ('안쪽의' · '안쪽에')
    assert "가만히 있어 봐" not in text  # 대사는 세지 않는다
    assert "화에만 있는" not in text  # 한 화에만 나온 말


def test_needs_enough_episodes_and_window():
    assert echoes.recent(_project(_texts(1)), 2) == []  # 본문 있는 직전 화가 하나면 찾지 않는다
    two = dict(echoes.recent(_project(_texts(2)), 3))
    assert two["한 손에 다 잡히지 않는"] == [1, 2]  # 둘이면 두 화에 나온 것
    other = ["사과가 바닥에 떨어졌다.", "강물이 밤새 불었다.", "종이 세 번 울렸다.", "아이들이 골목을 달렸다.", "등불이 꺼져 갔다."]
    p = _project(_texts(3) + other)
    assert echoes.recent(p, 9) == []  # 직전 5화(4~8화)에 없는 구절은 세지 않는다
    assert [e.plot.number for e in echoes.window_of(p, 9)] == [4, 5, 6, 7, 8]


def test_limit():
    lines = [f"{w} 붉은 노을이 천천히 번져 갔다." for w in "가나다라마바사아자차카타"]
    texts = [" ".join(f"문장 {k} {line}" for k, line in enumerate(lines)) for _ in range(3)]
    assert len(echoes.recent(_project(texts), 4)) <= echoes.LIMIT


def test_block_only_in_serial_write_prompt_tail():
    p = _project(_texts())
    block = prompts.echo_block(p, 4)
    assert block.startswith("\n\n# 최근 화에서 되풀이한 구절 (1~3화 본문에서 3개 화 이상에 그대로 나온 서술)")
    assert "- 한 손에 다 잡히지 않는 (1, 2, 3화)" in block
    s = prompts.episode_prompt(p, 4)
    assert block in s
    assert s.index("# 이번 화 플롯") < s.index("# 최근 화에서 되풀이한 구절")  # 화마다 바뀌는 뒤쪽 블록
    assert "되풀이한 구절" not in prompts.static_context(p)  # 캐시가 맞는 앞쪽에는 두지 않는다
    assert "되풀이한 구절" not in prompts.build_episode_context(p, 4)  # 쓰기 요청이 아닌 곳(스토리보드 등)에는 넣지 않는다

    p.settings.recent_echoes = False
    assert prompts.echo_block(p, 4) == "" and "되풀이한 구절" not in prompts.episode_prompt(p, 4)

    short = _project(_texts(), form="short")
    assert prompts.echo_block(short, 4) == "" and "되풀이한 구절" not in prompts.episode_prompt(short, 4)


def test_default_on_and_old_files_read():
    assert Project().settings.recent_echoes is True
    assert Project.model_validate({"settings": {"show_numbers": True}}).settings.recent_echoes is True  # 예전 project.json


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web
    importlib.reload(store)
    store.save("a", Project(meta=Meta(title="가", form="serial")))
    return TestClient(web.app), store


def test_web_setting_saves(client):
    c, store = client
    r = c.put("/api/projects/a/recent-echoes", json={"on": False})
    assert r.status_code == 200 and r.json()["settings"]["recent_echoes"] is False
    assert store.load("a").settings.recent_echoes is False
    c.put("/api/projects/a/recent-echoes", json={"on": True})
    assert store.load("a").settings.recent_echoes is True


@needs_node
def test_settings_row_serial_only():
    files = ["app.js", "notify.js", "settings.js"]
    got = run_js(files, """(() => {
      const row = () => setRowHtml('echoes');
      S.project = { meta: { form: 'serial' }, settings: {}, episodes: [], relationships: [] }; S.name = 'a'; S.route = ['p', 'a'];
      const on = row();
      S.project.settings.recent_echoes = false;
      const off = row();
      S.project.meta.form = 'short';
      return { on, off, short: row(), found: settingsMatch(SET_ROWS, '반복 구절').map((r) => r.id) };
    })()""", {})
    assert 'aria-checked="true"' in got["on"] and 'aria-checked="false"' in got["off"]
    assert got["short"] == ""
    assert got["found"][0] == "echoes"
