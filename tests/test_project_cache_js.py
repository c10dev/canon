"""작품 전체 GET 의 판 보관(app.js 의 api · projectCache)이 작품이 아닌 답을 작품으로 받지 않는지.
304 대신 본문이 빈 200 이 오면 보관한 판을 버리고 조건 없이 다시 받는다 (Safari 의 'p.episodes.map' 오류). node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

PROJECT = {"meta": {"title": "등대"}, "episodes": [{"plot": {"number": 1}}]}

# answers 를 차례로 돌려주는 가짜 fetch. 부를 때마다 보낸 If-None-Match 를 sent 에 남긴다
FAKE = """
const sent = [];
const reply = (a) => ({ status: a.status, ok: a.status >= 200 && a.status < 300,
  headers: { get: (k) => (a.headers || {})[k] || null },
  json: async () => { if (a.body === undefined) throw new SyntaxError('빈 본문'); return a.body; } });
const play = (answers) => { fetch = async (url, opt) => { sent.push(opt.headers['If-None-Match'] || ''); return reply(answers.shift()); }; };
const get = () => api('GET', '/projects/lh').then((p) => p.episodes.length, (e) => 'ERR ' + e.message);
"""


def _run(body: str):
    return run_js(["app.js"], f"(async () => {{ {FAKE} {body} }})()", None)


@needs_node
def test_empty_200_for_a_conditional_get_refetches_the_project():
    got = _run("""
      play([{ status: 200, headers: { ETag: '"v1"' }, body: data_p }, { status: 200, headers: { ETag: '"v1"' } }, { status: 200, headers: { ETag: '"v1"' }, body: data_p },
            { status: 304, headers: { ETag: '"v1"' } }]);
      const out = [await get(), await get(), await get()];
      return { out, sent };
    """.replace("data_p", repr(PROJECT).replace("'", '"')))
    # 두 번째는 빈 200 을 버리고 조건 없이 다시 받았다. 세 번째는 그렇게 받은 판으로 묻고 304 를 받았다
    assert got == {"out": [1, 1, 1], "sent": ["", '"v1"', "", '"v1"']}


@needs_node
def test_empty_answer_without_cache_is_an_error_not_a_project():
    got = _run("""
      play([{ status: 200, headers: { ETag: '"v1"' } }, { status: 200, headers: { ETag: '"v1"' }, body: data_p }]);
      const out = [await get(), await get()];
      return { out, sent };
    """.replace("data_p", repr(PROJECT).replace("'", '"')))
    # 보관한 판이 없으면 다시 받지 않고 알린다. 빈 답을 보관하지 않았으므로 다음 GET 은 조건 없이 간다
    assert got == {"out": ["ERR 작품을 받지 못했어요. 잠시 뒤 다시 시도하세요", 1], "sent": ["", ""]}


@needs_node
def test_save_answer_that_is_not_a_project_is_not_kept():
    got = _run("""
      play([{ status: 200, headers: { 'X-Project-ETag': '"v2"' }, body: { ok: true } }, { status: 200, headers: { ETag: '"v1"' }, body: data_p }]);
      await api('POST', '/projects/lh/view', {});  // 작품이 아닌 저장 응답은 판으로 보관하지 않는다
      return { out: await get(), sent };
    """.replace("data_p", repr(PROJECT).replace("'", '"')))
    assert got == {"out": 1, "sent": ["", ""]}
