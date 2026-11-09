"""app.js keepSwap: 다시 그려도 data-keep 칸(집필 본문)을 같은 요소로 남긴다. 값이 바뀌면 새 요소를 쓴다.
Chrome 은 요소를 떼거나 옮기기만 해도 되돌리기 기록을 지우므로, 지킨 칸과 조상은 옮기지 않는다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

# 가짜 DOM: keepSwap 이 쓰는 것만 둔다. 노드를 옮기면 moves 에 센다 (지킨 칸 · 조상은 0 이어야 한다)
FAKE = r"""
let moves = 0;
class N {
  constructor(tag, attrs = {}, kids = [], value) {
    this.tagName = tag; this.attrs = { ...attrs }; this.childNodes = []; this.parentNode = null; this.value = value;
    kids.forEach((k) => this.appendChild(k));
  }
  get attributes() { return Object.entries(this.attrs).map(([name, value]) => ({ name, value })); }
  get dataset() { return { keep: this.attrs['data-keep'] }; }
  get firstChild() { return this.childNodes[0] || null; }
  get nextSibling() { const s = this.parentNode.childNodes; return s[s.indexOf(this) + 1] || null; }
  hasAttribute(k) { return k in this.attrs; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; if (c.mark) moves++; return c; }
  appendChild(c) { return this.insertBefore(c, null); }
  insertBefore(c, ref) {
    if (c.parentNode) c.parentNode.removeChild(c);
    const i = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
    this.childNodes.splice(i, 0, c); c.parentNode = this; return c;
  }
  querySelectorAll() {
    const out = [];
    const walk = (n) => n.childNodes.forEach((c) => { if ('data-keep' in c.attrs) out.push(c); walk(c); });
    walk(this);
    return out;
  }
}
const h = (tag, attrs, kids, value) => new N(tag, attrs, kids, value);
const text = (v, attrs = {}) => h('TEXTAREA', { 'data-keep': 'draft-3', 'data-draft': '3', ...attrs }, [], v);
// #app > .shell > main > .prose > textarea, 옆에 머리 줄
const page = (ta, head = '머리') => h('DIV', {}, [h('DIV', { class: 'shell' }, [h('MAIN', { class: 'main' }, [
  h('HEADER', { title: head }), h('DIV', { class: 'prose' }, [ta]), h('P', { title: '아래' })])])]);
const tags = (n) => n.childNodes.map((c) => c.tagName + (c.attrs.title ? ':' + c.attrs.title : '') + (c.childNodes.length ? '(' + tags(c) + ')' : '')).join(',');
const textOf = (root) => root.querySelectorAll()[0];
const mark = (root) => { for (let n = textOf(root); n; n = n.parentNode) n.mark = true; };
"""


@needs_node
def test_same_value_keeps_same_element():
    got = run_js(["app.js"], FAKE + """(() => {
      const app = page(text('본문'));
      const old = textOf(app);
      mark(app);
      const kept = keepSwap(app, page(text('본문', { readonly: '', 'aria-describedby': 'draft-lock' }), '새 머리'));
      return { kept: kept.length, same: textOf(app) === old, moves, tree: tags(app), attrs: old.attrs };
    })()""", None)
    assert got["kept"] == 1
    assert got["same"] is True
    assert got["moves"] == 0  # 지킨 칸과 조상을 떼거나 옮기지 않았다
    assert got["tree"] == "DIV(MAIN(HEADER:새 머리,DIV(TEXTAREA),P:아래))"  # 형제는 새 것으로 바뀌고 차례는 그대로
    assert got["attrs"] == {"data-keep": "draft-3", "data-draft": "3", "readonly": "", "aria-describedby": "draft-lock"}


@needs_node
def test_dropped_attribute_is_removed_from_kept_element():
    got = run_js(["app.js"], FAKE + """(() => {
      const app = page(text('본문', { readonly: '', 'data-pick': '' }));
      const old = textOf(app);
      keepSwap(app, page(text('본문')));
      return { same: textOf(app) === old, attrs: old.attrs };
    })()""", None)
    assert got == {"same": True, "attrs": {"data-keep": "draft-3", "data-draft": "3"}}


@needs_node
def test_changed_value_uses_new_element():
    got = run_js(["app.js"], FAKE + """(() => {
      const app = page(text('본문'));
      const old = textOf(app);
      return { kept: keepSwap(app, page(text('AI가 쓴 새 본문'))), still: textOf(app) === old };
    })()""", None)
    assert got == {"kept": None, "still": True}  # null 이면 paintApp 이 innerHTML 을 통째로 바꾼다


@needs_node
def test_other_shape_or_missing_key_uses_new_html():
    got = run_js(["app.js"], FAKE + """(() => {
      const wrap = h('DIV', {}, [h('DIV', { class: 'shell' }, [h('MAIN', {}, [h('DIV', { class: 'prose' }, [h('DIV', { class: 'hl-wrap' }, [text('본문')])])])])]);
      return {
        deeper: keepSwap(page(text('본문')), wrap),  // 밑줄 층(.hl-wrap)이 새로 생겼다
        otherTag: keepSwap(page(text('본문')), page(h('DIV', { 'data-keep': 'draft-3' }, [], '본문'))),
        noKey: keepSwap(page(text('본문')), page(h('P', {}))),
        otherKey: keepSwap(page(text('본문')), page(text('본문', { 'data-keep': 'draft-4' }))),
      };
    })()""", None)
    assert got == {"deeper": None, "otherTag": None, "noKey": None, "otherKey": None}
