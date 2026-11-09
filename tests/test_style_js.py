"""문체 화면(static/style.js)의 목차 · 카드 계산과 그리기를 node 로 맞춰 본다. node 가 있을 때만 돈다.
목차 수(styleCount) · 빈 카드(styleCardEmpty) · 목차 줄(styleTocItems), 읽는 모양과 고치는 칸, 빈 작품의 세 갈래, 라이브러리 항목."""
from canon import pipeline
from canon.schema import Meta, Project, StyleDevice, StyleMarker, StyleProfile

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "setup.js", "chat.js", "passage.js", "marks.js", "style.js", "mystyle.js", "anchor.js", "stylechat.js"]


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
    assert got[0] == ["2/11", "4", "1", "1", "1"]
    assert got[1] == [False] * 5
    assert got[2] is True and got[3] == "0/11"


@needs_node
def test_card_keys_cover_profile_fields():
    keys = js(project(), "return STYLE_CARDS.flatMap(([id]) => styleCardKeys(id));")
    assert sorted(keys) == sorted([*pipeline.STYLE_KEYS, "sample_passages"])


@needs_node
def test_empty_profile_and_narr_keys_match_schema():
    """새 작품의 빈 프로필(emptyProfile)과 서술 카드 칸(NARR_KEYS)이 schema.StyleProfile 과 같은지."""
    got = js(project(), "return { empty: emptyProfile(), narr: NARR_KEYS };")
    assert got["empty"] == StyleProfile().model_dump(mode="json")
    assert list(got["empty"]) == list(StyleProfile.model_fields)
    assert got["narr"] == list(pipeline.STYLE_TEXT_KEYS)


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


# ----- 지표 요약 (metricGaps · metricSummary) · 빈 줄 묶기 (foldBlank) -----

BASE = {"sentence_len_mean": 20.0, "sentence_len_cv": 0.6, "paragraph_len_mean": 100.0, "dialogue_ratio": 0.3, "past_tense_ratio": 0.9,
        "mattr": None, "comma_sentence_ratio": 0.2, "dialogue_tilde_ratio": 0.0, "dialogue_line_len": 24.0,
        "sfx_per_1k": 1.0, "sfx_marks": {}, "sound_word_per_1k": 0.5}


def gaps(base, cur, extra: str = "return metricGaps(data.b, data.c);"):
    return js(project(), extra, b=base, c=cur)


@needs_node
def test_metric_gaps_picks_two_most_off_warned_first():
    """점수 = 차이 / 경고 폭. 경고 폭을 넘은 지표(warn)가 앞이고, 많아야 둘이다."""
    cur = {**BASE, "sentence_len_mean": 24.0,  # +20% / 0.3 = 0.67
           "paragraph_len_mean": 140.0,       # +40% / 0.5 = 0.8
           "dialogue_ratio": 0.1,             # -0.20 / 0.15 = 1.33 (경고)
           "dialogue_line_len": 15.0,         # -37.5% / 0.3 = 1.25 (경고)
           "mattr": 0.7,                      # 기준이 없어 뺀다
           "comma_sentence_ratio": 0.05,      # 높을 때만 보는 지표가 낮아져 뺀다
           "sfx_per_1k": 9.0}                 # 경고 기준이 없는 지표라 요약에 넣지 않는다
    got = gaps(BASE, cur)
    assert [(g["key"], g["warn"], g["up"]) for g in got] == [("dialogue_ratio", True, False), ("dialogue_line_len", True, False)]
    assert round(got[0]["score"], 2) == 1.33
    three = gaps(BASE, cur, "return metricGaps(data.b, data.c, 4).map((g) => [g.key, g.warn]);")
    assert three == [["dialogue_ratio", True], ["dialogue_line_len", True], ["paragraph_len_mean", False], ["sentence_len_mean", False]]
    line = gaps(BASE, cur, "return metricSummary(data.b, { n: 7, metrics: data.c });")
    assert "<strong>7화</strong>" in line and line.count('class="chip warn"') == 2
    assert "대사가 레퍼런스보다 적어요." in line and "대사 한 줄이 레퍼런스보다 짧아요." in line and "문단" not in line


@needs_node
def test_metric_gaps_skip_missing_values_and_small_gaps():
    """값이 없는 지표는 어느 쪽이든 빼고, 경고 폭의 절반도 안 되는 차이는 요약에 올리지 않는다."""
    none = {k: None for k in BASE if k != "sfx_marks"}
    only = gaps(BASE, {**none, "past_tense_ratio": 0.5})  # -0.4 / 0.2 = 2.0
    assert [(g["key"], g["warn"], g["up"], g["score"]) for g in only] == [("past_tense_ratio", True, False, 2.0)]
    assert gaps(none, {**BASE}) == []
    assert gaps({**BASE, "sentence_len_mean": 0}, {**BASE, "sentence_len_mean": 30}) == []  # 비율 지표의 기준 0
    near = {**BASE, "sentence_len_mean": 21.0, "dialogue_ratio": 0.33}
    assert gaps(BASE, near) == []
    line = gaps(BASE, near, "return metricSummary(data.b, { n: 3, metrics: data.c });")
    assert "레퍼런스와 크게 어긋난 지표가 없어요" in line and "chip warn" not in line


@needs_node
def test_no_summary_without_reference_or_episode():
    """견줄 화나 레퍼런스 값이 없으면 요약 줄을 두지 않는다. 기준 지표가 없으면 맨 위 카드는 분석 안내만 보인다."""
    got = js(project(profile()), """S.styleLink = { state: 'none' };
      const a = [metricSummary(data.b, null), metricSummary(null, { n: 1, metrics: data.b }), metricGaps(null, data.b), metricGaps(data.b, null)];
      const noBase = styleStatus();
      S.project.style_baseline = data.b;
      const noNow = styleStatus();
      S.styleNow = { name: 'other', n: 2, metrics: data.b };
      const otherWork = styleStatus();
      S.styleNow = { name: 'g', n: 2, metrics: { ...data.b, dialogue_ratio: 0.6 } };
      return [a, noBase, noNow, otherWork, styleStatus()];""", b=BASE)
    pure, no_base, no_now, other_work, ok = got
    assert pure == ["", "", [], []]
    assert "sty-sum" not in no_base and "원문을 분석하면" in no_base and "지표 풀이" not in no_base
    assert "sty-sum" not in no_now and "metric-chips" not in no_now and "지표 풀이" in no_now
    assert "sty-sum" not in other_work  # 다른 작품에서 잰 값은 쓰지 않는다
    assert "sty-sum" in ok and "대사가 레퍼런스보다 많아요" in ok and "metric-chips" not in ok


@needs_node
def test_metric_chips_skip_missing_values_and_rows_show_episode():
    """값이 없는 지표는 칩을 그리지 않는다. 풀이 표는 '–' 를 남기고, 견준 화의 값을 곁에 적는다."""
    got = js(project(), "return [metricChips(data.b), baselineRows(data.b, undefined, { n: 4, metrics: { ...data.b, sentence_len_mean: 12.5 } })];", b=BASE)
    chips, rows = got
    assert "문장 평균 <strong>20.0자</strong>" in chips and ">어휘 다양도 <strong>" not in chips and "<strong>–" not in chips
    assert "물결표 대사 <strong>0%</strong>" in chips  # 0% 는 잰 값이다
    assert "어휘 다양도</dt><dd>–" in rows and "· 4화 12.5자" in rows


@needs_node
def test_metric_gaps_match_server_thresholds():
    """요약의 경고 폭 · 비율 · 높을 때만이 metrics.THRESHOLDS · UPPER_ONLY 와 같아야 경고가 검수 화면과 맞는다."""
    from canon import metrics
    table = js(project(), "return METRIC_GAPS;")
    for key, (limit, relative, upper, up_text, down_text) in table.items():
        assert key in metrics.THRESHOLDS, key
        _, lim, rel = metrics.THRESHOLDS[key]
        assert (limit, relative, upper) == (lim, rel, key in metrics.UPPER_ONLY), key
        assert up_text.endswith("요") and (upper or down_text.endswith("요"))
        assert key in metrics.StyleMetrics.model_fields


@needs_node
def test_fold_blank_groups_empty_rows_and_keeps_open_ones():
    got = js(project(), """const has = (v) => (k) => !!v[k];
      return [foldBlank(['a', 'b', 'c'], has({ a: 1 })),
              foldBlank(['a', 'b', 'c'], has({ a: 1, b: 1 }), ['b', 'c']),
              foldBlank(['a', 'b', 'c'], has({ a: 1 }), ['b']),
              foldBlank(['a', 'b'], has({ a: 1, b: 1 }))];""")
    assert got[0] == {"shown": ["a"], "blank": ["b", "c"]}
    assert got[1] == {"shown": ["a"], "blank": ["b", "c"]}  # 펼친 동안 채운 b 는 고치는 칸에 남는다
    assert got[2] == {"shown": ["a"], "blank": ["b", "c"]}  # 펼친 뒤 비워진 c 도 묶음에 든다
    assert got[3] == {"shown": ["a", "b"], "blank": []}


@needs_node
def test_narr_card_shows_filled_rows_and_one_fill_button():
    """서술 카드는 값이 있는 줄만 읽는 모양으로 보이고, 빈 줄은 '빈 칸 n개 채우기' 하나로 묶는다.
    펼치면 빈 칸이 고치는 칸이 되고, 쓰는 동안 다시 그려도 접히지 않는다."""
    got = js(project(profile()), """render = () => {}; focusEl = () => {};
      const card = () => pfCard('narr', '서술', 'style', '', new Set());
      const folded = card();
      actions.styleFill('');
      const opened = card();
      P().style.description_density = '촘촘하게';
      const typed = card();
      actions.styleFill('');
      const closed = card();
      const hot = pfCard('narr', '서술', 'style', '', new Set(['pacing']));
      return [folded, opened, typed, closed, hot, S.styleFill];""")
    folded, opened, typed, closed, hot, fill = got
    assert folded.count("<dt") == 2 and "비어 있음" not in folded
    assert 'data-action="styleFill"' in folded and "빈 칸 9개 채우기" in folded and 'aria-expanded="false"' in folded
    assert 'data-bind="style.description_density"' not in folded
    assert opened.count('data-bind="style.') == 9 and "빈 칸 접기" in opened and 'aria-expanded="true"' in opened
    assert 'data-bind="style.description_density"' in typed and typed.count('data-bind="style.') == 9  # 채운 칸도 자리를 지킨다
    assert closed.count("<dt") == 3 and "빈 칸 8개 채우기" in closed and fill == {"g:narr": None}
    assert "전개 속도 <span class=\"chip hot\">변경안</span>" in hot and "빈 칸 7개 채우기" in hot  # 변경안이 바꿀 빈 칸은 보인다


@needs_node
def test_rules_card_drops_empty_placeholder():
    """지킬 · 피할 것 카드에서 수가 0인 묶음은 '비어 있음' 을 따로 적지 않는다."""
    html = js(project(profile()), "return pfRead('rules', P().style, '', new Set());")
    assert "비어 있음" not in html and "열 낱말 0" in html
