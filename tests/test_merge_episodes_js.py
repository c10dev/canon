"""한 화 작업이 끝나면 그 화만 받는다 (app.js 의 mergeEpisodes · touchedEpisodes, GET /episodes).
화를 뺀 나머지의 판(rest) · 저장 횟수 · 화 번호 목록이 다르거나 요청이 실패하면 작품 전체를 받는다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

# url 로 답을 고르는 가짜 fetch. 부른 주소를 urls 에 남긴다
FAKE = """
const urls = [];
const reply = (a) => ({ status: a.status || 200, ok: (a.status || 200) < 300,
  headers: { get: (k) => (a.headers || {})[k] || null }, json: async () => a.body });
let answers = {};
fetch = async (url) => { urls.push(url); const a = answers[url.includes('/episodes') ? 'eps' : 'whole']; return reply(typeof a === 'function' ? a() : a); };
const ep = (n, text = '') => ({ plot: { number: n, title: '' }, status: 'confirmed', text });
const first = { meta: { title: '등대' }, facts: [], edit_rev: 3, saved_by: 'x', episodes: [ep(1), ep(2)] };
answers.whole = { headers: { ETag: '"v1"', 'X-Project-Rest': 'r1' }, body: first };
const open = async () => { S.name = 'lh'; S.project = await api('GET', '/projects/lh'); S.dirty = false; urls.length = 0; };
const eps = (over) => ({ body: { etag: '"v2"', edit_rev: 3, saved_by: 'x', rest: 'r1', numbers: [1, 2], episodes: [ep(2, '새 본문')], ...over } });
const texts = () => P().episodes.map((e) => e.text);
"""


def _run(body: str):
    return run_js(["app.js"], f"(async () => {{ {FAKE} {body} }})()", None)


@needs_node
def test_merge_fetches_only_the_touched_episode():
    got = _run("""
      await open();
      const obj = P();
      answers.eps = eps();
      await mergeEpisodes((e) => e.plot.number === 2, [2]);
      return { urls, texts: texts(), same: P() === obj, base: projectBase.eps.get(2) === JSON.stringify(P().episodes[1]) };
    """)
    # 작품 전체를 다시 받지 않고 2화만 받아 그 자리에 넣었다. 저장 기준(projectBase)도 그 화를 받은 판으로 맞췄다
    assert got == {"urls": ["/api/projects/lh/episodes?nums=2"], "texts": ["", "새 본문"], "same": True, "base": True}


@needs_node
def test_merge_falls_back_to_whole_project_on_mismatch():
    whole2 = "answers.whole = { headers: { ETag: '\"v2\"', 'X-Project-Rest': 'r2' }, body: { ...first, facts: ['새 사실'], episodes: [ep(1), ep(2, '전체')] } };"
    got = _run(f"""
      const out = {{}};
      for (const [name, over] of Object.entries({{
        rest: {{ rest: 'r2' }}, rev: {{ edit_rev: 4 }}, added: {{ numbers: [1, 2, 3] }}, removed: {{ numbers: [2] }}, error: null }})) {{
        answers.whole = {{ headers: {{ ETag: '"v1"', 'X-Project-Rest': 'r1' }}, body: first }};
        await open();
        answers.eps = over ? eps(over) : {{ status: 500, body: {{ detail: '실패' }} }};
        {whole2}
        await mergeEpisodes((e) => e.plot.number === 2, [2]);
        out[name] = {{ urls: [...urls], texts: texts(), facts: P().facts }};
      }}
      return out;
    """)
    for name, r in got.items():
        # 화만으로는 맞출 수 없어 작품 전체를 받아 화 밖(사실)까지 바꿨다
        assert r == {"urls": ["/api/projects/lh/episodes?nums=2", "/api/projects/lh"], "texts": ["", "전체"], "facts": ["새 사실"]}, name


@needs_node
def test_merge_without_rest_or_after_save_uses_whole_project():
    got = _run("""
      answers.whole = { headers: { ETag: '"v1"' }, body: first };  // 판 없는 답 (옛 서버)
      await open();
      await mergeEpisodes((e) => e.plot.number === 2, [2]);
      return urls;
    """)
    assert got == ["/api/projects/lh"]


@needs_node
def test_merge_keeps_unsaved_edits_of_other_episodes():
    got = _run("""
      await open();
      P().episodes[0].plot.title = '고치던 제목';
      S.dirty = true;
      answers.eps = { body: { etag: '"v2"', edit_rev: 3, saved_by: 'x', rest: 'r1', numbers: [1, 2], episodes: [{ ...ep(1), plot: { number: 1, title: '서버' } }, ep(2, '새 본문')] } };
      const changed = await mergeEpisodes((cur, e) => e.plot.number === 2, [1, 2]);
      return { changed, titles: P().episodes.map((e) => e.plot.title), texts: texts() };
    """)
    # 입력 중인 1화는 두고 작업이 쓴 2화만 바꿨다
    assert got == {"changed": [2], "titles": ["고치던 제목", ""], "texts": ["", "새 본문"]}
