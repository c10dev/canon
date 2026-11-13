"""지시 연습 화면(static/drill.js): 단계마다 주 버튼 하나, 인용 표시, 쓰는 방식 줄 수, 가려 읽기, 기록. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

HOME = {"rounds": [], "sources": [{"id": "r1", "name": "가게", "eps": 4}], "kinds": ["대화"], "method_max": 5,
        "layers": [{"id": "ban", "label": "금지", "rule": "하지 않을 것"}, {"id": "manner", "label": "방식", "rule": "어떻게"}],
        "results": {"applied": "반영됨", "overdone": "과하게 풀림", "ignored": "무시됨", "unsure": "판정 못 함"},
        "boxes": {"events": "일어나는 일", "avoid": "하지 않는 것", "manner": "방식"}}
BRIEF = {"people": "서연: 손님", "pov": "서연", "place": "가게", "time": "밤", "before": "막 들어왔다", "events": "말을 건다", "change": "", "avoid": "손대기\n\n목소리 높이기",
         "manner": "짧게"}
ATTEMPT = {"no": 1, "brief": BRIEF, "with_text": "서연은 <낮게> 말했다.\n도윤은 물러섰다.", "bare_text": "서연은 소리쳤다.", "reviewed_at": "2026-11-12T10:00:00", "dropped": 2,
           "verdicts": [{"no": 1, "box": "avoid", "text": "손대기", "layer": "ban", "result": "applied", "quote": "", "bare_quote": "서연은 소리쳤다", "in_bare": False, "same_as": 0, "why": "지켰어요"},
                        {"no": 2, "box": "manner", "text": "짧게", "layer": "manner", "result": "applied", "quote": "<낮게> 말했다", "bare_quote": "", "in_bare": True, "same_as": 1, "why": ""},
                        {"no": 3, "box": "avoid", "text": "목소리 높이기", "layer": "manner", "result": "unsure", "quote": "", "bare_quote": "", "in_bare": False, "same_as": 0, "why": "근거 없음"}],
           "invented": [{"side": "with", "quote": "도윤은 물러섰다", "what": "없던 일"}], "gaps": [{"what": "가게의 소리", "quote": "종이 울렸다"}]}
ROUND = {"id": "d1", "title": "가게 1화 · 대목 2/4", "ref_name": "가게", "ep_label": "1화", "part": 2, "parts": 4, "source": "", "source_chars": 900, "style_name": "",
         "brief": BRIEF, "attempts": [], "measures": {}, "source_measure": None, "lines": [], "method_lines": 3,
         "hints": [{"box": "manner", "text": "짧게", "hint": "힌트 글"}, {"box": "avoid", "text": "", "hint": "비었어요"}]}
MEASURE = {"chars": 20, "sentences": 2, "dialogue_pct": 0, "hits": []}


@needs_node
def test_each_stage_has_one_primary_button():
    got = run_js(["app.js", "studio.js", "drill.js"], """(() => {
      fmtDateTime = () => '';
      S.jobs = []; S.route = ['drill']; S.libs = [];
      S.drHome = data.home; S.drNew = { ref_id: 'r1', order: 0, part: 0, kind: '', tension: 0, style_id: '' }; S.drEps = [{ order: 1, label: '1화', parts: 4, kind: '대화', tension: 3 }];
      const primary = (html) => (html.match(/class="btn primary"/g) || []).length;
      const out = { home: primary(viewDrill()), homeHtml: viewDrill() };
      S.drNew.order = 1;
      out.pick = viewDrill();
      S.drHome = { ...data.home, sources: [] };
      out.empty = viewDrill();
      S.drHome = data.home;
      for (const stage of ['facts', 'brief', 'written', 'reviewed']) {
        const done = stage === 'written' || stage === 'reviewed';
        const a = { ...data.attempt, reviewed_at: stage === 'reviewed' ? data.attempt.reviewed_at : '' };
        S.dr = { ...data.round, stage, source: done ? '종이 울렸다. 서연이 들어섰다.' : '', revealed: done, attempts: done ? [a] : [],
          measures: done ? { 1: { with: data.m, bare: data.m } } : {}, source_measure: done ? data.m : null };
        S.drForm = { brief: { ...data.round.brief } };
        const html = viewDrill();
        out[stage] = { primary: primary(html), html };
      }
      out.count = drMethodCount(data.round.brief);
      out.text = drText('가 <나>\\n다 라', [['<나>', 'device'], ['없는 말', 'rest'], ['다 라', 'banned'], ['나>', 'rest']]);
      return out;
    })()""", {"home": HOME, "round": ROUND, "attempt": ATTEMPT, "m": MEASURE})
    assert got["home"] == 1 and "화의 성격" in got["homeHtml"] and "dr-part" not in got["homeHtml"]
    assert 'id="dr-part"' in got["pick"] and "화의 성격" not in got["pick"]  # 화를 고르면 성격 대신 대목 번호를 고른다
    assert "레퍼런스 원고 열기" in got["empty"] and 'class="btn primary"' not in got["empty"]
    assert [got[s]["primary"] for s in ("facts", "brief", "written", "reviewed")] == [1, 1, 1, 1]
    assert 'data-action="drRevise"' in got["reviewed"]["html"] and "지시 고치기" in got["reviewed"]["html"] and 'data-root="drForm"' in got["reviewed"]["html"]
    assert 'data-action="drFacts"' in got["facts"]["html"] and 'data-action="drWrite"' in got["brief"]["html"]
    brief = got["brief"]["html"]
    assert "가려 둠" in brief and "종이 울렸다" not in brief and "3/5줄" in brief and 'data-root="drForm"' in brief
    assert 'id="f-brief-inner"' in brief and '<ul class="dr-list small" id="dr-hints"><li><strong>짧게</strong> 힌트 글</li><li><strong>하지 않는 것</strong> 비었어요</li></ul>' in brief
    assert "아직 되짚지 않았어요" in got["written"]["html"] and 'data-action="drReview"' in got["written"]["html"]
    done = got["reviewed"]["html"]
    assert '<mark class="hl device">&lt;낮게&gt; 말했다</mark>' in done and '<mark class="hl banned">도윤은 물러섰다</mark>' in done
    assert '<mark class="hl rest">종이 울렸다</mark>' in done and '<mark class="hl rest">서연은 소리쳤다</mark>' in done
    assert "지시 없는 판도 같아요" in done and "1번 줄과 같은 말이에요" in done and "판정 못 함" in done and "인용 2개는 버렸어요" in done
    assert "지어낸 사실" in done and "원문에는 있고 두 판에 없는 것" in done and "고친 지시로 다시 쓰기" in done
    assert got["count"] == 3
    assert got["text"] == '<p>가 <mark class="hl device">&lt;나&gt;</mark></p><p><mark class="hl banned">다 라</mark></p>'


@needs_node
def test_blind_pick_hides_sides_and_done_shows_the_result():
    second = {**ATTEMPT, "no": 2, "versus": 1, "old_text": "앞 지시로 다시 쓴 글이다.", "pick": "new", "brief": {**BRIEF, "manner": "짧게\n말 사이를 길게"}}
    hidden = {"no": 2, "versus": 1, "brief": second["brief"], "with_text": "", "old_text": "", "bare_text": "서연은 소리쳤다.", "verdicts": [], "invented": [], "gaps": [], "pick": "",
              "reviewed_at": "", "dropped": 0}
    got = run_js(["app.js", "studio.js", "drill.js"], """(async () => {
      fmtDateTime = () => ''; fmtDate = () => '11월 12일';
      S.jobs = []; S.route = ['drill']; S.libs = []; S.drHome = data.home;
      const base = { ...data.round, source: '종이 울렸다.', revealed: true, source_measure: data.m };
      S.dr = { ...base, stage: 'pick', attempts: [data.first, data.hidden], measures: { 1: { with: data.m, bare: data.m } }, blind: { left: '왼쪽에 놓인 글', right: '오른쪽에 놓인 글' } };
      S.drForm = { brief: { ...data.round.brief } };
      const pick = viewDrill();
      const calls = [];
      run = async (label, fn) => fn(); toast = (t) => calls.push(t); render = () => {};
      api = async (m, path, body) => { calls.push([m, path, body]); return { ...base, stage: 'done', attempts: [data.first, data.second], blind: null,
        measures: { 1: { with: data.m, bare: data.m }, 2: { with: data.m, bare: data.m, old: data.m } },
        changed: { added: [{ box: 'manner', text: '말 사이를 길게' }], removed: [] } }; };
      await actions.drPick('right');
      const done = viewDrill();
      S.dr = null;
      S.drNew = { ref_id: 'r1', order: 0, part: 0, kind: '', tension: 0, style_id: '' }; S.drEps = [];
      S.drHome = { ...data.home, stats: data.stats, rounds: [{ id: 'd1', title: '가게 1화', stage: 'done', pick: 'new', results: { applied: 2 }, created_at: '' }] };
      return { pick, calls, done, home: viewDrill() };
    })()""", {"home": HOME, "round": ROUND, "first": ATTEMPT, "second": second, "hidden": hidden, "m": MEASURE, "stats": {
        "rounds": 2, "lines": 5, "worked": 0.4, "recent_n": 5, "recent": 0.4, "before": None, "picks": {"new": 1, "old": 0, "skip": 1},
        "layers": [{"id": "ban", "label": "금지", "lines": 2, "share": 0.4, "applied": 2, "overdone": 0, "ignored": 0, "unsure": 0, "worked": 1, "added": 1, "won": 1},
                   {"id": "manner", "label": "방식", "lines": 3, "share": 0.6, "applied": 1, "overdone": 1, "ignored": 0, "unsure": 1, "worked": 1, "added": 0, "won": 0},
                   {"id": "action", "label": "동작", "lines": 0, "share": 0.0, "applied": 0, "overdone": 0, "ignored": 0, "unsure": 0, "worked": 0, "added": 0, "won": 0}],
        "trend": [{"id": "d1", "title": "가게 1화", "created_at": "2026-11-12T09:00:00", "lines": 3, "judged": 2, "worked": 1, "pick": "new", "layers": [{"id": "ban", "n": 2}]}]}})
    pick = got["pick"]
    assert "왼쪽에 놓인 글" in pick and "오른쪽에 놓인 글" in pick and pick.count('data-action="drPick"') == 3 and 'class="btn primary"' not in pick
    assert "고친 지시로 쓴 판" not in pick and "되짚기" not in pick and "<mark" not in pick  # 고르기 전에는 어느 쪽인지 · 되짚기를 보이지 않는다
    assert got["calls"] == [["POST", "/drill/d1/pick", {"side": "right"}], "고친 지시로 쓴 글을 골랐어요."]
    done = got["done"]
    assert "고친 지시로 쓴 글을 골랐어요" in done and "더한 줄: 말 사이를 길게" in done and "앞 지시로 다시 쓴 글이다." in done and "고친 지시로 쓴 판" in done
    assert done.count('class="btn primary"') == 1 and "새 판 시작" in done and "지시 없는 판</h2>" not in done
    home = got["home"]
    assert 'id="dr-stats"' in home and "판 2개 · 줄 5개 · 먹힌 줄 40% · 고친 지시 1승 0패 · 비슷함 1" in home
    assert "<td>금지</td><td>2</td><td>40%</td><td>2</td><td>0</td><td>0</td><td>50%</td><td>1/1판</td>" in home
    assert "<td>방식</td><td>3</td><td>60%</td><td>1</td><td>1</td><td>0</td><td>50%</td><td>–</td>" in home and "<td>동작</td>" not in home
    assert "고친 지시가 이김" in home and "금지 2</span>" in home and home.count('class="btn primary"') == 1


@needs_node
def test_new_round_starts_with_the_style_of_the_last_round():
    got = run_js(["app.js", "studio.js", "drill.js"], """(async () => {
      const home = { ...data.home, rounds: [{ id: 'd2', style_id: '' }, { id: 'd1', style_id: 'lib1' }] };
      api = async (m, path) => (path === '/drill' ? home : { episodes: [] });
      S.libs = [{ id: 'lib1', name: '문체' }];
      await drLoad();
      const first = S.drNew.style_id;
      S.drNew.style_id = ''; S.drStylePicked = true;  // 작가가 '고르지 않음'을 골랐다
      await drLoad();
      const kept = S.drNew.style_id;
      S.drNew = null; S.drStylePicked = false; S.libs = [];  // 라이브러리에서 지운 문체
      await drLoad();
      return { first, kept, gone: S.drNew.style_id };
    })()""", {"home": HOME})
    assert got == {"first": "lib1", "kept": "", "gone": ""}


@needs_node
def test_shrink_round_shows_the_dense_brief_then_the_blind_pick():
    dense = [{"box": "before", "text": "막 들어왔다"}, {"box": "inner", "text": "숨기는 것이 있다"}, {"box": "events", "text": "말을 건다"}, {"box": "events", "text": "피한다"}]
    att = {"no": 1, "brief": {**BRIEF, "events": "묻고 피한다\n나간다"}, "with_text": "줄인 지시로 쓴 글이다.", "old_text": "뽑은 지시로 쓴 글이다.", "bare_text": "", "pick": "skip",
           "verdicts": [], "invented": [], "gaps": [], "reviewed_at": "", "dropped": 0, "versus": 0}
    got = run_js(["app.js", "studio.js", "drill.js"], """(() => {
      fmtDateTime = () => ''; fmtDate = () => '';
      S.jobs = []; S.route = ['drill']; S.libs = [];
      S.drHome = { ...data.home, modes: { '': '지시 적기', shrink: '줄이기' }, shrink_max: 3 };
      S.drNew = { ref_id: 'r1', order: 0, part: 0, kind: '', tension: 0, style_id: '', mode: 'shrink' }; S.drEps = [];
      const primary = (html) => (html.match(/class="btn primary"/g) || []).length;
      const out = { home: viewDrill() };
      const base = { ...data.round, mode: 'shrink', dense: data.dense, shrink_max: 3, hints: [] };
      S.drForm = { brief: { ...data.round.brief, events: '하나\\n둘\\n셋\\n넷' } };
      for (const stage of ['facts', 'brief', 'pick', 'done']) {
        S.dr = { ...base, stage, attempts: stage === 'pick' ? [{ ...data.att, with_text: '', old_text: '', pick: '' }] : stage === 'done' ? [data.att] : [],
          blind: stage === 'pick' ? { left: '왼쪽 글', right: '오른쪽 글' } : null, source: stage === 'done' ? '종이 울렸다.' : '',
          measures: stage === 'done' ? { 1: { with: data.m, old: data.m, bare: data.m } } : {}, source_measure: stage === 'done' ? data.m : null };
        const html = viewDrill();
        out[stage] = { primary: primary(html), html };
      }
      S.dr = null;
      S.drHome = { ...S.drHome, stats: { rounds: 0, shrink: { new: 1, old: 0, skip: 2 } }, rounds: [{ id: 'd1', title: '가게 1화', mode: 'shrink', stage: 'done', pick: 'new', results: {}, created_at: '' }] };
      out.list = viewDrill();
      return out;
    })()""", {"home": HOME, "round": ROUND, "att": att, "dense": dense, "m": MEASURE})
    assert 'id="dr-mode"' in got["home"] and '<option value="shrink" selected>줄이기</option>' in got["home"] and "3줄로 줄여 보는 연습" in got["home"]
    assert [got[s]["primary"] for s in ("facts", "brief", "pick", "done")] == [1, 1, 0, 1]
    brief = got["brief"]["html"]
    assert 'data-action="drShrink"' in brief and "4/3줄" in brief and 'class="chip bad"' in brief and "숨기는 것이 있다" in brief and "가려 둠" in brief
    assert "쓰는 방식" not in brief and "바뀌는 것" not in brief and brief.count('<p class="small">') == 2
    pick = got["pick"]["html"]
    assert "왼쪽 글" in pick and pick.count('data-action="drPick"') == 3 and "줄인 지시로 쓴 판" not in pick and "종이 울렸다" not in pick
    done = got["done"]["html"]
    assert "두 글이 비슷하다고 골랐어요" in done and "줄인 지시로 쓴 판" in done and "뽑은 지시로 쓴 글이다." in done and "종이 울렸다." in done and "되짚기" not in done
    assert "<li>묻고 피한다</li><li>나간다</li>" in done and "2줄" in done and "4줄" in done
    assert "줄이기 3판: 줄인 지시 1 · 비슷함 2 · 뽑은 지시 0" in got["list"] and '<span class="chip">줄이기</span><span class="chip">골랐음</span><span class="chip">줄인 지시가 나음</span>' in got["list"]
