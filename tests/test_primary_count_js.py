"""주 버튼 셈 (docs/ux/specs/11-hierarchy.md, docs/design/README.md '주 버튼 셈'): 작품 화면의 <main> 안에 먹색 주 버튼(.btn.primary)이 하나 이하인지 본다.
화면 파일을 index.html 차례대로 모두 읽은 vm 에서 app.js mainHtml 로 main 을 그린다. 대화 패널(chatDock)은 main 밖이라 '보내기'는 세지 않는다.
화면을 더하려면 SCREENS 에 (이름, 주소, 작품 상태) 줄을 더한다. 기준 수를 바꾸려면 그 줄의 limit 을 고친다. node 가 있을 때만 돈다."""
import re

import pytest

from canon.schema import Act, Character, Project, Relationship

from .jsvm import STATIC, dump, episode, needs_node, run_js

FILES = re.findall(r'src="/static/([^"]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))

# class 속성 안에 btn 과 primary 가 함께 있는 것 (차례 · 다른 클래스와 상관없이)
PRIMARY = re.compile(r'class="(?=[^"]*\bbtn\b)(?=[^"]*\bprimary\b)[^"]*"')

BEATS = [Act(name=x, start_ep=i * 2 + 1, end_ep=i * 2 + 2, goal="g", key_turn="t") for i, x in enumerate(["기", "승", "전", "결"])]


def _base(statuses: list[str], **kw) -> Project:
    """화 상태 목록으로 만든 8화 단편. 인물 · 관계 · 문체를 채워 설정 도우미가 기획서를 그린다."""
    p = Project(**kw)
    p.meta.title = "등대"
    p.meta.genre = "미스터리"
    p.meta.target_episodes = 8
    p.meta.logline = "책방 주인이 사라진 오빠를 찾는다"
    p.world.setting = "바닷가 소도시"
    p.characters = [Character(id="c1", name="서윤", role="주인공", speech_style="짧게"), Character(id="c2", name="도현", role="조연")]
    p.relationships = [Relationship(a="c1", b="c2", type="동료")]
    p.style.narration_pov = "3인칭 제한"
    p.style.sample_passages = ["바람이 불었다."]
    p.arc = BEATS
    p.episodes = [episode(i + 1, text="본문" if s in ("written", "finalized") else "", status=s,
                          plot={"act": BEATS[min(i // 2, 3)].name, "title": f"{i + 1}화", "summary": "요약"})
                  for i, s in enumerate(statuses)]
    return p


def _cast() -> Project:
    """2화 플롯에 AI 가 제안한 새 인물이 나오는 작품 (플롯 페이지의 '인물로 등록' 줄)."""
    p = _base(["finalized", "draft"], cast_candidates=[Character(id="n1", name="곽노인", role="단역")])
    p.episodes[1].plot.characters = ["c1", "n1"]
    return p


STATES = {
    "empty": lambda: Project(),
    "draft": lambda: _base(["finalized", "draft"]),
    "confirmed": lambda: _base(["finalized", "confirmed"]),
    "written": lambda: _base(["finalized", "written"]),
    "finished": lambda: _base(["finalized"] * 8),
    "cast": lambda: _cast(),
}

# 서버에서 받아 S 에 두는 화면 상태 (그리기 전에 넣는다)
ANCHOR = {"anchorView": {"anchor": None, "usable": [1], "suggest": [1], "trend": [], "band": [0, 1], "warn": 1, "window": 3, "min_chars": 1000}}

# (화면, 주소 뒤쪽, 작품 상태, 기준 수, S 에 넣을 값). 주소는 S.route 의 세 번째 칸부터다 (['p', 이름, 화면, 화])
SCREENS = [
    ("home", [], "empty", 1, {}),
    ("home", [], "draft", 1, {}),
    ("home", [], "finished", 1, {}),
    ("setup", ["setup"], "empty", 1, {}),
    ("setup", ["setup"], "written", 1, {}),
    ("style", ["style"], "empty", 1, {}),
    ("style", ["style"], "written", 1, {}),
    ("style", ["style"], "finished", 1, ANCHOR),
    ("style", ["style"], "finished", 1, {**ANCHOR, "anchorPick": [1]}),
    ("arc", ["arc"], "empty", 1, {}),
    ("arc", ["arc"], "draft", 1, {}),
    ("arc", ["arc"], "finished", 1, {}),
    ("arc", ["arc", "2"], "draft", 1, {}),
    ("arc", ["arc", "2"], "confirmed", 1, {}),
    ("arc", ["arc", "2"], "cast", 1, {}),
    ("write", ["write", "2"], "draft", 1, {}),
    ("write", ["write", "2"], "confirmed", 1, {}),
    ("write", ["write", "2"], "confirmed", 1, {"dirEdit": 2}),
    ("write", ["write", "2"], "written", 1, {}),
    ("write", ["write", "8"], "finished", 1, {}),
]

EXPR = """(() => {
  S.name = 't'; S.project = data.project; S.route = ['p', 't', ...data.route]; S.jobs = [];
  Object.assign(S, data.extra);
  const page = data.route[0] || '';
  const n = Number(data.route[1]) || currentEp();
  chatScreen(page, n);
  const views = { setup: viewSetup, style: viewStyle, arc: () => (plotPageN() ? viewPlotPage(plotPageN()) : serial() ? viewSerial() : viewArc()), write: viewWrite };
  return mainHtml(page, n, (views[page] || viewHome)(n));
})()"""


def main_html(route: list[str], state: str, extra: dict | None = None) -> str:
    return run_js(FILES, EXPR, {"project": dump(STATES[state]()), "route": route, "extra": extra or {}})


@needs_node
@pytest.mark.parametrize("screen,route,state,limit,extra", SCREENS,
                         ids=[f"{s}-{'-'.join(r) or 'home'}-{st}{'-' + '-'.join(x) if x else ''}" for s, r, st, _, x in SCREENS])
def test_main_has_one_primary(screen, route, state, limit, extra):
    html = main_html(route, state, extra)
    assert "<h1" in html or "page-head" in html, html[:300]  # 화면을 실제로 그렸다
    got = [re.sub(r"<[^>]+>", "", html[m.end():].split(">", 1)[1].split("</", 1)[0])[:30] for m in PRIMARY.finditer(html)]
    assert len(got) <= limit, f"{screen} ({state}) main 안 주 버튼 {len(got)}개: {got}"


@needs_node
def test_write_finished_export_is_secondary():
    """반영이 끝난 마지막 화의 다음 할 일이 '완결 원고 내보내기'면 집필 화면은 보조 버튼으로 둔다. 작품 홈은 주 버튼 그대로다."""
    html = main_html(["write", "8"], "finished")
    assert 'class="btn" data-action="exportAll"' in html
    assert 'class="btn primary" data-action="exportAll"' in main_html([], "finished")
