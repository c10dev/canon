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
         "brief": BRIEF, "attempts": [], "measures": {}, "source_measure": None, "lines": [], "method_lines": 3}
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
