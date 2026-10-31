"""작품이 열리지 않은 화면(작품 목록)이 열린 작품을 읽다 터지지 않는지 node 로 본다. node 가 있을 때만 돈다.
문체 라이브러리에 문체가 있으면 새 작품 칸이 단계 이름(stepLabel)을 불렀고, stepLabel 이 장편인지(serial) 먼저 물어
'Cannot read properties of null (reading 'meta')' 로 작품 목록이 비었다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "home.js"]
SETUP = "S.project = null; S.route = ['']; S.libs = [{id: 'lib1', name: '건조체', source: ''}];"


@needs_node
def test_step_labels_without_project():
    got = run_js(FILES, SETUP + "['setup', 'style', 'arc', 'write', 'check', 'review'].map(stepLabel).concat([serial()])", None)
    assert got == ["설정 도우미", "문체 레퍼런스", "기승전결 · 플롯", "집필", "검수", "상태 승인", False]


@needs_node
def test_new_project_form_with_style_library():
    html = run_js(FILES, SETUP + "newProjectForm(true)", None)
    assert 'id="np-style"' in html and "문체 레퍼런스 단계를 건너뛸 수 있어요" in html


@needs_node
def test_floating_tool_closes_off_project():
    # 검수 고치는 창을 연 채 작품 목록으로 가면 창이 #app 밖에 남아, 그 버튼이 없는 작품을 읽다 터졌다
    got = run_js(FILES + ["chat.js", "passage.js"], "S.project = null; S.route = ['']; S.projects = []; S.selTool = {mode: 'finding', n: 3}; "
                 "try { drawApp(); } catch (e) { /* 사이드바 그리기에 필요한 다른 화면 파일은 싣지 않았다 */ } S.selTool", None)
    assert got is None


@needs_node
def test_select_in_leftover_textarea_without_project():
    # 작품 목록으로 옮기는 사이 남은 본문 칸에서 손을 떼도 없는 작품을 읽지 않는다
    got = run_js(FILES + ["chat.js", "passage.js"], "S.project = null; "
                 "const ta = {matches: () => true, dataset: {draft: '3'}}; String(onSelect({target: ta}))", None)
    assert got == "undefined"
