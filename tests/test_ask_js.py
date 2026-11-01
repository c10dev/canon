"""확인 대화상자(app.js askConfirm · askText)가 confirm · prompt 와 같은 값을 돌려주는지, 화면 파일에 브라우저 확인 창이 남지 않았는지.
node 가 있을 때만 도는 시험이 섞여 있다."""
import re

from .jsvm import STATIC, needs_node, run_js

# 대화상자 대역: showDialog 가 돌려주는 <dialog>. close(v) 는 returnValue 를 바꾸고 close 이벤트를 바로 부른다
FAKE = """
const fake = { html: '', el: null };
showDialog = (id, html) => {
  const inp = { id: id + '-in', value: '', focus() {}, select() {} };
  const m = html.match(/id="ask-dlg-in" value="([^"]*)"/);
  if (m) inp.value = m[1];
  const el = fake.el && fake.el.open ? fake.el : { open: false, dataset: {}, on: {}, returnValue: '',
    addEventListener(t, f) { (this.on[t] = this.on[t] || []).push(f); },
    close(v) { if (v !== undefined) this.returnValue = v; this.open = false; (this.on.close || []).forEach((f) => f()); } };
  el.open = true;
  el.querySelector = (sel) => (sel.includes('-in') ? inp : { focus() {} });
  el.inp = inp;
  fake.html = html;
  fake.el = el;
  return el;
};
"""


def ask(expr: str):
    return run_js(["app.js"], FAKE + expr, {})


@needs_node
def test_split_title_and_body():
    got = ask("""[
      askSplit('X를 지울까요? 되돌릴 수 없어요.'),
      askSplit('메모가 있어요. 지울까요?'),
      askSplit('첫 줄\\n\\n둘째 줄\\n셋째 줄'),
      askSplit('물음 없음', '제목'),
      askSplit('a? b\\nc'),
    ]""")
    assert got == [
        {"title": "X를 지울까요?", "body": ["되돌릴 수 없어요."]},
        {"title": "메모가 있어요. 지울까요?", "body": []},
        {"title": "첫 줄", "body": ["둘째 줄", "셋째 줄"]},
        {"title": "제목", "body": ["물음 없음"]},
        {"title": "a?", "body": ["b", "c"]},
    ]


@needs_node
def test_confirm_resolves_like_confirm():
    got = ask("""(async () => {
      const a = askConfirm('지울까요?', { ok: '지우기', danger: true });
      const html = fake.html;
      fake.el.close('ok');
      const b = askConfirm('바꿀까요?');
      fake.el.close();  // Esc · 바깥 누르기: returnValue 가 빈 채로 닫힌다
      const c = askConfirm('첫 물음?');
      const d = askConfirm('둘째 물음?');  // 열린 채로 또 물으면 앞 물음은 취소로 끝난다
      fake.el.close('ok');
      const e = askConfirm('취소 버튼?');
      fake.el.close('');
      return { a: await a, b: await b, c: await c, d: await d, e: await e, html };
    })()""")
    assert [got[k] for k in "abcde"] == [True, False, False, True, False]
    html = got["html"]
    assert '<h2 id="ask-dlg-title">지울까요?</h2>' in html
    # 취소가 먼저, 주 버튼(위험한 동작은 danger)이 오른쪽 끝
    assert html.index('data-ask=""') < html.index('data-ask="ok"')
    assert 'class="btn danger" data-ask="ok">지우기<' in html and "primary" not in html


@needs_node
def test_button_click_answers_at_once():
    got = ask("""(async () => {
      const press = (v) => fake.el.on.click[0]({ target: { closest: () => ({ dataset: { ask: v } }) } });
      const a = askConfirm('첫 물음?');
      press('ok');
      const b = askConfirm('둘째 물음?');  // 앞 답을 받자마자 이어 묻는 곳 (자동 집필 시작)
      fake.el.on.close.forEach((f) => f());  // 늦게 온 앞 close: 열린 동안은 무시한다
      press('');
      const c = askConfirm('셋째 물음?');
      fake.el.on.cancel[0]();  // Esc
      return [await a, await b, await c];
    })()""")
    assert got == [True, False, False]


@needs_node
def test_text_resolves_like_prompt():
    got = ask("""(async () => {
      const a = askText('', { title: '세션 이름', value: '옛 이름' });
      const html = fake.html;
      fake.el.inp.value = '새 이름';
      fake.el.close('ok');
      const b = askText('', { title: '이름' });
      fake.el.close('ok');
      const c = askText('', { title: '이름', value: 'x' });
      fake.el.close();
      return { a: await a, b: await b, c: await c, html };
    })()""")
    assert got["a"] == "새 이름" and got["b"] == "" and got["c"] is None
    assert 'value="옛 이름"' in got["html"] and 'aria-labelledby="ask-dlg-title"' in got["html"]
    assert 'class="btn primary" data-ask="ok">확인<' in got["html"]


@needs_node
def test_message_is_escaped():
    got = ask("""(async () => { askConfirm('<b>&</b>를 지울까요?'); return fake.html; })()""")
    assert "&lt;b&gt;&amp;&lt;/b&gt;" in got and "<b>" not in got


# 브라우저 확인 창(confirm · prompt · window.confirm …)은 쓰지 않는다. 디자인 시스템 Dialog 의 askConfirm · askText 를 쓴다.
# 남겨 둘 까닭이 있는 곳은 '파일:줄 내용' 이 아니라 파일 이름으로 여기 적고 docs/design/README.md '코드와 아직 다른 곳' 에 까닭을 쓴다
ALLOWED: set[str] = set()
BROWSER_ASK = re.compile(r"(?:(?<![\w$.])|(?<=window\.))(?:confirm|prompt)\s*\(")


def test_no_browser_confirm_or_prompt():
    left = [f"{f.name}:{i}" for f in sorted(STATIC.glob("*.js")) if f.name not in ALLOWED
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if BROWSER_ASK.search(line)]
    assert not left, f"브라우저 확인 창이 남았어요: {left}"


def test_pattern_skips_look_alike_names():
    hits = ["confirm('a')", "window.confirm('a')", "prompt('a', '')", "if (!confirm (x))"]
    misses = ["askConfirm('a')", "cancelConfirm()", "S.promptText", "prompts.x()", "x.confirm(1)", "confirmDrop('a')"]
    assert all(BROWSER_ASK.search(s) for s in hits)
    assert not any(BROWSER_ASK.search(s) for s in misses)
