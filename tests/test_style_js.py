"""문체 화면(static/style.js)의 목차 · 카드 계산과 그리기를 node 로 맞춰 본다. node 가 있을 때만 돈다.
목차 수(styleCount) · 빈 카드(styleCardEmpty) · 목차 줄(styleTocItems), 읽는 모양과 고치는 칸, 빈 작품의 세 갈래, 라이브러리 항목."""
from canon import pipeline
from canon.schema import Meta, Project, StyleDevice, StyleMarker, StyleProfile

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "setup.js", "chat.js", "passage.js", "marks.js", "style.js", "mystyle.js", "stylechat.js"]


def profile() -> StyleProfile:
    return StyleProfile(narration_pov="3인칭 제한", tense="과거형", dos=["감정은 몸의 반응으로", "문단 끝은 사물로"], donts=["설명하는 독백"],
                        banned_phrases=["가슴이 먹먹했다"], markers=[StyleMarker(text="것이었다", note="문단 끝", per_1k=0.8)],
                        devices=[StyleDevice(name="사물 떨림 컷", when="감정을 누를 때", cues=["떨었다"], every=4)],
                        sample_passages=["가마는 아직 식지 않았다."])


def project(style: StyleProfile | None = None) -> Project:
    eps = [episode(n, text=t, status="finalized")
           for n, t in [(1, "컵이 떨었다. 또 떨었다."), (2, "조용했다.")]]
    return Project(meta=Meta(title="유리", target_episodes=4), style=style or StyleProfile(), episodes=eps)


def js(p: Project, expr: str, **kw):
    return run_js(FILES, f"(() => {{ S.project = data.p; S.name = 'g'; S.route = ['p', 'g', 'style']; S.libs = data.libs || []; {expr} }})()",
                  {"p": dump(p), **kw})


@needs_node
def test_counts_and_empty_cards():
    got = js(project(profile()), """const st = P().style;
      return [STYLE_CARDS.map(([id]) => styleCount(id, st)), STYLE_CARDS.map(([id]) => styleCardEmpty(id, st)),
              styleCardEmpty('narr', emptyProfile()), styleCount('narr', emptyProfile())];""")
    assert got[0] == ["2/10", "4", "1", "1", "1"]
    assert got[1] == [False] * 5
    assert got[2] is True and got[3] == "0/10"


@needs_node
def test_card_keys_cover_profile_fields():
    keys = js(project(), "return STYLE_CARDS.flatMap(([id]) => styleCardKeys(id));")
    assert sorted(keys) == sorted([*pipeline.STYLE_KEYS, "sample_passages"])


@needs_node
def test_toc_items_marks_todo_hot_and_link():
    rows = js(project(profile()), """return styleTocItems(P().style, { hot: new Set(['tense', 'markers']), todo: 2, example: '바뀜', link: '다름', learn: '5건' });""")
    assert rows[0] == ["todo", "확인할 것", "2", "warn"]
    assert rows[1] == ["example", "이 문체로 쓴 예시", "바뀜", "warn"]
    by = {r[0]: r for r in rows}
    assert by["narr"][3] == "hot" and by["markers"][3] == "hot" and by["rules"][3] == ""
    assert by["status"] == ["status", "라이브러리 · 기준 지표", "다름", "warn"]
    assert [r[0] for r in rows].index("-") < [r[0] for r in rows].index("source")
    plain = js(project(profile()), "return styleTocItems(P().style).map((r) => r[0]);")
    assert "todo" not in plain


@needs_node
def test_view_reads_cards_and_opens_one_for_editing():
    html = js(project(profile()), """const a = viewStyle();
      S.styleOpen = { [pfKey('', 'markers')]: true };
      return [a, viewStyle()];""")
    read, edit = html
    assert 'id="sty-toc"' in read and 'class="pf-dl"' in read and 'class="pf-table"' in read
    assert 'data-bind="style.markers.0.text"' not in read and 'data-bind="style.narration_pov"' not in read
    assert "마지막으로 쓴 화 1화" in read  # 1화에 '떨었다' 두 번 (marks.js deviceLast)
    assert '>기승전결 · 플롯으로</a>' in read and 'class="btn primary"' in read
    assert 'data-bind="style.markers.0.text"' in edit and 'aria-label="표지 1 쓰임"' in edit and "다 고쳤어요" in edit
    assert 'data-bind="style.narration_pov"' not in edit  # 다른 카드는 그대로 읽는 모양


@needs_node
def test_blank_style_shows_three_ways_then_empty_cards():
    libs = [{"id": "a1", "name": "느린 3인칭", "source": "연습", "narration_pov": "3인칭", "tense": "", "passages": 2, "rules": 3,
             "banned": 0, "markers": 0, "devices": 0, "used_by": []}]
    html = js(project(), "const a = viewStyle(); S.styleManual = { g: true }; return [a, viewStyle()];", libs=libs)
    blank, manual = html
    assert 'data-action="analyzeStyle"' in blank and 'class="btn primary" data-action="analyzeStyle"' in blank
    assert 'data-action="useLibStyle" data-arg="a1"' in blank and "빈 카드 열기" in blank
    assert 'id="pf-narr"' not in blank
    # 직접 채우기: 빈 카드는 바로 고치는 칸이고 '고치기' 버튼이 없다
    assert 'data-bind="style.narration_pov"' in manual and 'data-action="styleEdit"' not in manual
    assert 'data-pf-key="g:narr"' in manual


@needs_node
def test_library_entry_uses_same_cards():
    entry = {"id": "e1", "name": "느린 3인칭", "source": "", "notes": "", "sample": "", "profile": profile().model_dump(),
             "baseline": None, "used_by": [], "created_at": "", "updated_at": "", "version": 1}
    html = js(project(), "S.lib = data.e; S.libVersions = []; S.projects = []; return viewLibEntry();", e=entry)
    assert 'id="sty-toc"' in html and 'id="pf-info"' in html and 'id="pf-versions"' in html
    assert 'class="pf-dl"' in html and 'data-arg="lib|narr"' in html
    assert "마지막으로 쓴 화" not in html  # 라이브러리는 작품 화가 없다
