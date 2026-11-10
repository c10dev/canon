"""AI 상투 기호 빼기 (docs/ux/specs/10-ai-tells.md): 화면 파일에 ✦ 가 남지 않았는지,
대화 에이전트의 빈 세션 예시 요청을 작품 값으로 채우는지(agent.js agentExamples). node 가 있을 때만 도는 시험이 섞여 있다."""
from canon.schema import Character, Project, StoryArc

from .jsvm import STATIC, dump, episode, needs_node, run_js

FILES = ["app.js", "chat.js", "agent.js", "agentsetup.js"]


def test_no_sparkle_in_screen_files():
    """화면 파일(js · css · html)에 ✦ 를 쓰지 않는다. AI 를 부르는 버튼은 동사 문구로만 말한다 (docs/design/README.md 문구 절)."""
    files = [f for ext in ("*.js", "*.css", "*.html") for f in STATIC.rglob(ext) if "vendor" not in f.parts]
    left = [f.name for f in files if "✦" in f.read_text(encoding="utf-8")]
    assert not left, left


def _project(serial: bool = False, names: tuple = ("서윤", "도현")) -> dict:
    p = Project(episodes=[episode(n, status="finalized" if n == 1 else "draft") for n in range(1, 4)])
    p.characters = [Character(id=f"c{i}", name=x, role="조연" if i == 0 else "주인공") for i, x in enumerate(names)]
    if serial:
        p.meta.form = "serial"
        p.story_arcs = [StoryArc(number=2, title="섬", start_ep=1, end_ep=3, goal="g")]
    return dump(p)


def examples(project: dict, targets: list[str], sel_ep=None):
    return run_js(FILES, """(() => { S.name = 'demo'; S.project = data.project; S.selEp = data.sel;
      return Object.fromEntries(data.targets.map((t) => [t, agentExamples(t)])); })()""",
                  {"project": project, "targets": targets, "sel": sel_ep})


@needs_node
def test_examples_use_work_values():
    got = examples(_project(), ["", "setup", "ep:3", "text:2", "style"])
    # 주인공(역할)을 먼저 쓰고, 화 번호는 확정하지 않은 첫 화
    assert got[""] == ["2화 전개가 너무 빨라", "도현이 진실을 더 늦게 알게 해 줘"]
    assert got["setup"] == ["도현의 약점을 더 어둡게", "도현과 서윤 사이에 갈등을 하나 더"]
    assert got["ep:3"][0] == "3화 전개가 너무 빨라"
    assert got["text:2"] == [] and got["style"] == []
    # 화면에서 고른 화가 있으면 그 화
    assert examples(_project(), [""], sel_ep=3)[""][0] == "3화 전개가 너무 빨라"
    # 받침 없는 이름은 '가' · '와'
    assert examples(_project(names=("민지", "하나")), ["setup"])["setup"][1] == "하나와 민지 사이에 갈등을 하나 더"


@needs_node
def test_examples_serial_targets():
    got = examples(_project(serial=True), ["arc:2", "next", "part:1"])
    assert got["arc:2"] == ["아크 2 갈등을 더 개인적인 걸로", "도현의 비중을 이 아크에서 늘려 줘"]
    assert got["next"] == ["4화부터 15화짜리 아크로", "다음 아크는 도현 중심으로"]
    assert got["part:1"][0] == "1부 전환점을 더 늦게"


@needs_node
def test_no_data_no_pills():
    """채울 값이 없으면 예시를 두지 않는다. 버튼 줄도 그리지 않는다 (입력칸 예시 글만 남는다)."""
    got = run_js(FILES, """(() => { S.name = 'demo'; S.project = data.project;
      return [agentExamples(''), agentExamples('setup'), agentExampleRow('setup'), agentSetupIntro().includes('agentExample')]; })()""",
                 {"project": dump(Project())})
    assert got == [[], [], "", False]
    row = run_js(FILES, "(() => { S.name = 'demo'; S.project = data.project; return agentExampleRow('setup'); })()",
                 {"project": _project()})
    assert row.count('data-action="agentExample"') == 2
