"""프롬프트 관리 화면(static/prompts.js)의 순수 함수와 화면. node 가 있을 때만 돈다."""
import pytest

from .jsvm import needs_node, run_js

FILES = ["app.js", "prompts.js"]


@pytest.fixture(scope="module")
def reg():
    from canon.routes import prompts as routes

    return routes.registry()


@needs_node
def test_groups_put_view_kinds_first_and_filter(reg):
    got = run_js(FILES, """(() => {
      const all = pcGroups(data.reg);
      const flat = (rows) => rows.flatMap((g) => g.kinds.map((k) => k.id));
      return { groups: all.view.map((g) => g.group), view: flat(all.view), table: flat(all.table),
               q: flat(pcGroups(data.reg, '검수').view), qt: flat(pcGroups(data.reg, '검수').table), none: pcGroups(data.reg, 'zzz') };
    })()""", {"reg": reg})
    assert got["groups"] == ["설정", "문체", "계획", "쓰기", "검수", "상태"]  # 집필 흐름 차례
    assert got["view"][:2] == ["setup_chat", "style_chat"] and "episode" in got["view"] and "polish" in got["view"]
    assert len(got["view"]) == 17 and "setup" in got["table"] and "play_scene" in got["table"]
    assert set(got["view"]) & set(got["table"]) == set()
    assert got["q"] == ["check", "motion"] and "widen" in got["qt"]
    assert got["none"] == {"view": [], "table": []}


@needs_node
def test_topic_collects_pieces_in_place_order(reg):
    got = run_js(FILES, """(() => {
      const rows = pcTopic(data.reg, 'style');
      return { ids: rows.map((x) => x.id), places: rows.map((x) => x.place), send: pcTopic(data.reg, 'policy').find((x) => x.id === 'policy_note').kindLabels,
               ending: rows.find((x) => x.id === 'ending').kindLabels, counts: pcTagCounts(data.reg) };
    })()""", {"reg": reg})
    order = ["system", "front", "tail", "instruction", "second", "send"]
    assert [order.index(x) for x in got["places"]] == sorted(order.index(x) for x in got["places"])
    # '왜 필요한가' 표의 다섯 자리: 시스템 · 요청 앞 · 요청 뒤 · 지시문 꼬리 · 두 번째 호출
    assert {"system", "front", "tail", "instruction", "second"} <= set(got["places"])
    assert {"prose_rules", "style", "devices", "echo", "write_style", "ending", "polish_rules"} <= set(got["ids"])
    assert got["send"] == ["모든 갈래"]
    assert "본문 쓰기" in got["ending"]
    assert got["counts"]["style"] == len(got["ids"]) and all(v > 0 for v in got["counts"].values())


@needs_node
def test_count_prescriptions():
    got = run_js(FILES, """(() => [
      pcCounts("서술 문장 열에 셋쯤이 이렇게 이어진 문장이 되게 합니다. 말줄임은 화에 셋까지, 명사로 끝내는 문장은 장면에 하나까지만 씁니다."),
      pcCounts("비유는 장면마다 한두 번 씁니다. 장면 3~7개. 한 화에 한 번 이하로 씁니다. '~다.'로 끝나는 문장을 세 줄 넘게 잇지 않습니다."),
      pcCounts("감정은 이름으로 말하지 않고 행동으로 드러냅니다."),
      pcCounts("열에 셋쯤 열에 셋쯤"),
    ])()""", {})
    assert got[0] == ["열에 셋쯤", "화에 셋까지", "장면에 하나까지"]
    assert got[1] == ["한두 번", "3~7개", "화에 한 번 이하", "세 줄 넘게"]
    assert got[2] == []
    assert got[3] == ["열에 셋쯤"]


@needs_node
def test_kind_view_draws_places_and_pieces(client, reg):
    data = client.get("/api/prompts/kinds/episode").json()
    html = run_js(FILES, """(() => {
      S.pcReg = data.reg; S.pcView = 'kind'; S.pcData = data.d; S.route = ['prompts', 'episode'];
      return viewPrompts();
    })()""", {"reg": reg, "d": data})
    for label in ("시스템", "요청 앞 (캐시)", "요청 뒤 (화마다)", "지시문 꼬리", "보내기 직전"):
        assert f"<h3>{label}</h3>" in html
    assert "문체 기본 규칙" in html and "<code>_PROSE_RULES</code>" in html and "횟수 처방" in html
    assert 'aria-current="page">본문 쓰기</a>' in html and "토큰(추정)" in html
    assert 'data-action="pcPlayground"' in html and 'class="btn primary"' not in html
    assert 'href="#/prompts/topic/style"' in html


@needs_node
def test_topic_and_piece_views(client, reg):
    topic = client.get("/api/prompts/topics/style").json()
    piece = client.get("/api/prompts/pieces/ending").json()
    got = run_js(FILES, """(() => {
      S.pcReg = data.reg; S.route = ['prompts', 'topic', 'style'];
      S.pcView = 'topic'; S.pcData = data.topic; const t = viewPrompts();
      S.pcQ = '다듬기'; const q = viewPrompts(); S.pcQ = '';
      S.pcView = 'piece'; S.pcData = data.piece; const p = viewPrompts();
      return { t, q, p };
    })()""", {"reg": reg, "topic": topic, "piece": piece})
    assert "<h2>문체</h2>" in got["t"] and "두 번째 호출" in got["t"] and "서술 다듬기" in got["t"]
    assert 'aria-pressed="true">주제별' in got["t"]
    assert "서술 다듬기 규칙" in got["q"] and "문체 기본 규칙" not in got["q"]
    assert "<h2>문장 끝 섞기</h2>" in got["p"] and 'href="#/prompts/episode"' in got["p"]


@needs_node
def test_sidebar_and_menu_link_to_page():
    got = run_js(["app.js"], """(() => ({ tools: outNav().tools.map((x) => x[1]) }))()""", {})
    tools = got["tools"]
    assert tools.index("#/prompts") == tools.index("#/promptlab") + 1  # 작품 밖 도구 줄의 놀이터 옆 (정할 것 6)


@needs_node
def test_line_diff():
    got = run_js(FILES, """(() => ({
      same: pcLineDiff('a\\nb', 'a\\nb').map((r) => r.op).join(''),
      mid: pcLineDiff('a\\nb\\nc', 'a\\nB\\nc').map((r) => r.op + r.text),
      add: pcLineDiff('a', 'a\\nb').map((r) => r.op + r.text),
      del: pcLineDiff('a\\nb', 'b').map((r) => r.op + r.text),
      html: pcDiffHtml('1\\n2\\n3\\n4\\n5\\n6', '1\\n2\\n3\\n4\\n5\\nsix'),
      none: pcDiffHtml('x', 'x'),
    }))()""", {})
    assert got["same"] == "  "
    assert got["mid"] == [" a", "-b", "+B", " c"]
    assert got["add"] == [" a", "+b"] and got["del"] == ["-a", " b"]
    assert "… 4줄 같음" in got["html"] and "pc-diff-del" in got["html"] and "더한 줄: " in got["html"]
    assert "원래 글과 같아요" in got["none"]


@needs_node
def test_set_editor(client, reg, tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_PROMPTSETS", str(tmp_path / "sets"))
    ps = client.post("/api/promptsets", json={"name": "판", "kind": "episode"}).json()
    d = client.put(f"/api/promptsets/{ps['id']}", json={"name": "판", "kind": "episode", "note": "",
                                                        "changes": [{"piece": "write_style", "text": "문체는 예시 문단만 따릅니다. "},
                                                                    {"piece": "gone", "text": "x"}]}).json()
    html = run_js(FILES, """(() => {
      S.pcReg = data.reg; S.route = ['prompts', 'set', data.d.set.id]; S.pcView = 'set'; S.pcSets = [data.d.set];
      pcSetPut(data.d);
      return viewPrompts();
    })()""", {"reg": reg, "d": d})
    assert 'aria-pressed="true">실험 판' in html
    assert "프로필 따르기 · banned_phrases" in html and "바꿈</span>" in html and "없는 조각</span>" in html
    assert "pc-diff-add" in html and "문체는 예시 문단만 따릅니다." in html
    assert html.count('class="btn primary"') == 1 and 'data-action="pcSetOpen" data-arg="blind"' in html
    assert 'id="pc-set-add"' in html and 'value="write_style"' not in html.split('id="pc-set-add"')[1]  # 이미 바꾼 조각은 더하기 목록에 없다
