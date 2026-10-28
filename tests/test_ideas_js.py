"""설정 칸 하나의 AI 후보 화면(static/ideas.js)을 node 로 맞춰 본다: 칸 목록이 서버(prompts.FIELD_IDEAS)와 같고,
받기 전에는 칸이 그대로이며, 고르면 그 칸과 합친 로그라인만 바뀐다."""
from canon import prompts
from canon.schema import Project

from .jsvm import dump, needs_node, run_js

FILES = ["app.js", "home.js", "setup.js", "ideas.js"]


@needs_node
def test_idea_fields_match_server():
    got = run_js(FILES, "IDEA_FIELDS", {})
    assert got == {k: label for k, (label, _) in prompts.FIELD_IDEAS.items()}
    # 로그라인 칸 이름은 설정 화면의 칸 이름과 같다
    slots = run_js(FILES, "Object.fromEntries(LOGLINE_SLOTS.map(([k, label]) => ['meta.logline_parts.' + k, label]))", {})
    assert all(got[k] == v for k, v in slots.items())


@needs_node
def test_pick_idea():
    p = Project()
    p.meta.logline_parts.goal = "지도를 찾는다"
    p.meta.logline = "지도를 찾는다."
    expr = """(() => {
      S.project = data.project;
      S.name = 'demo';
      render = () => {};  // 화면 전체 그리기는 이 시험 밖
      const before = ideaList('meta.logline_parts.who');
      S.ideas = { 'meta.logline_parts.who': { loading: true } };
      const loading = ideaList('meta.logline_parts.who');
      S.ideas = { 'meta.logline_parts.who': { options: [{ text: '지도 제작자', reason: '장르' }, { text: '사서', reason: '' }] } };
      const shown = ideaList('meta.logline_parts.who');
      const btn = ideaBtn('meta.logline_parts.who');
      const untouched = P().meta.logline_parts.who;
      actions.useIdea('meta.logline_parts.who|1');
      const slot = [P().meta.logline_parts.who, P().meta.logline, S.dirty, 'meta.logline_parts.who' in S.ideas];
      S.ideas = { 'world.setting': { options: [{ text: '안개 낀 섬', reason: '' }] } };
      actions.useIdea('world.setting|0');
      return { before, loading, shown, btn, untouched, slot, setting: P().world.setting, none: ideaBtn('meta.genre') };
    })()"""
    got = run_js(FILES, expr, {"project": dump(p)})
    assert 'hidden' in got["before"] and 'id="ideas-meta-logline_parts-who"' in got["before"]
    assert "후보를 만들고 있어요" in got["loading"] and 'data-action="useIdea"' not in got["loading"]
    assert got["shown"].count('data-action="useIdea"') == 2 and "지도 제작자" in got["shown"] and "<small>장르</small>" in got["shown"]
    assert 'aria-expanded="true"' in got["btn"] and 'aria-controls="ideas-meta-logline_parts-who"' in got["btn"] and "✦ 후보" in got["btn"]
    assert got["untouched"] == ""  # 받기만 해서는 칸이 바뀌지 않는다
    assert got["slot"] == ["사서", "사서가 지도를 찾는다.", True, False]
    assert got["setting"] == "안개 낀 섬"
    assert got["none"] == ""


@needs_node
def test_wired_into_setup():
    """로그라인 다섯 칸 · 제목 · 배경에 ✦ 가 붙고, 설정 칸으로 점프하면 마법사가 아니라 기획서로 연다."""
    expr = """(() => {
      S.project = data.project;
      S.name = 'demo';
      const slots = loglineBuilder();
      const field = input('배경', 'world.setting', { aside: '<b>A</b>', beside: '<b>B</b>', after: '<b>C</b>' });
      const plain = input('시대', 'world.era');
      const wizard = setupMode();
      S.setupModes = {};
      S.jumpTo = '#f-meta-theme';
      const doc = viewSetup();
      return { slots: (slots.match(/data-action="fieldIdeas"/g) || []).length, field, plain, wizard, mode: S.setupModes.demo,
               docIdeas: (doc.match(/data-action="fieldIdeas"/g) || []).length, hasTheme: doc.includes('id="f-meta-theme"') };
    })()"""
    got = run_js(["app.js", "home.js", "setup.js", "archetypes.js", "statwin.js", "illust.js", "charlog.js", "chat.js", "setupchat.js", "ideas.js"],
                 expr, {"project": dump(Project())})
    assert got["slots"] == 5
    assert got["field"].index('class="lab-row"') < got["field"].index("<b>A</b>") < got["field"].index('class="in-ai"') < got["field"].index("<b>B</b>") < got["field"].index("<b>C</b>")
    assert "lab-row" not in got["plain"] and "in-ai" not in got["plain"]
    assert got["wizard"] == "wizard" and got["mode"] == "doc"  # 빈 새 작품은 마법사지만 칸 점프는 기획서로
    assert got["docIdeas"] == 7 and got["hasTheme"]
