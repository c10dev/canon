/* 모으기: 지금 탭에서 본문을 뽑아 Canon(POST /api/refs/inbox)에 보내고, '다음 화'를 눌러 다음 화가 뜨면 되풀이한다.
   진행 상태는 chrome.storage.local 의 run 에 두고 팝업이 그린다. 페이지 안에서 도는 함수는 extract · clickNext 둘이다.
   화를 보낼 때마다 그 화의 주소를 cursor 에 적어 두고, 이어서 모으기는 그 주소로 가 다음 화부터 모은다. */
'use strict';
const GAP_MS = 1500;      // 화 사이 쉬는 시간 (사이트에 부담을 주지 않게)
const WAIT_MS = 20000;    // 다음 화 본문이 뜨기를 기다리는 시간
let stopped = false;
let running = false;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const setRun = (run) => chrome.storage.local.set({ run });
const setCursor = (cursor) => chrome.storage.local.set({ cursor });

/** 페이지 안: 본문 위치의 문단을 모은다. 위치를 못 찾으면 빈 글. 위치가 비었으면 문서 전체의 문단. */
function extract(sel) {
  let host = null;
  if (sel) { try { host = document.querySelector(sel); } catch (e) { return { error: '본문 위치 선택자가 올바르지 않아요' }; } }
  const root = sel ? (host ? (host.shadowRoot || host) : null) : document;
  const text = root ? [...root.querySelectorAll('p')].map((p) => p.textContent.trim()).filter(Boolean).join('\n\n') : '';
  return { title: document.title, url: location.href, text };
}

/** 페이지 안: 다음 화 버튼을 찾아 누른다. sel 이 비면 '다음 화' · '다음' · 'next' 글자나 rel=next 로 찾는다(열린 Shadow DOM 안까지). */
function clickNext(sel) {
  const all = (root, q, out = []) => {
    root.querySelectorAll(q).forEach((el) => out.push(el));
    root.querySelectorAll('*').forEach((el) => { if (el.shadowRoot) all(el.shadowRoot, q, out); });
    return out;
  };
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  let el = null;
  if (sel) {
    try { el = all(document, sel).find(visible) || null; } catch (e) { return { ok: false, why: '다음 화 버튼 선택자가 올바르지 않아요' }; }
  } else {
    const cands = all(document, 'a, button, [role="button"]').filter(visible);
    const name = (x) => (x.textContent || x.getAttribute('aria-label') || x.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
    el = cands.find((x) => x.matches('a[rel~="next"]'))
      || cands.find((x) => /^(다음\s*화|다음\s*회차?|다음\s*편)(?=$|[\s>›→»)\]])/.test(name(x)))
      || cands.find((x) => /^(다음|next)(?=$|[\s>›→»)\]])/i.test(name(x)));
  }
  if (!el) return { ok: false, why: '다음 화 버튼이 없어 멈췄어요(마지막 화이거나 버튼을 못 찾음)' };
  if (el.disabled || el.getAttribute('aria-disabled') === 'true') return { ok: false, why: '마지막 화예요' };
  el.click();
  return { ok: true };
}

async function inPage(tabId, func, arg) {
  const [r] = await chrome.scripting.executeScript({ target: { tabId }, func, args: [arg] });
  return r ? r.result : null;
}

/** 본문이 뜨고, 앞 화와 다른 글이 될 때까지 기다린다 (주소가 바뀌는 사이트와 그대로인 사이트 모두). */
async function waitBody(tabId, sel, last) {
  const end = Date.now() + WAIT_MS;
  while (Date.now() < end && !stopped) {
    try {
      const r = await inPage(tabId, extract, sel);
      if (r && r.error) return r;
      if (r && r.text && r.text !== last) return r;
    } catch (e) { /* 페이지를 옮기는 중이면 다시 본다 */ }
    await sleep(500);
  }
  return null;
}

/** 탭을 주소로 옮긴 뒤, 그 페이지가 다 뜰 때까지 기다린다. */
async function goTo(tabId, url) {
  await chrome.tabs.update(tabId, { url });
  const end = Date.now() + WAIT_MS;
  await sleep(400);  // 옮기기가 시작되어 앞 페이지의 'complete' 를 잘못 잡지 않게
  while (Date.now() < end && !stopped) {
    try { const t = await chrome.tabs.get(tabId); if (t && t.status === 'complete') return true; } catch (e) { /* 옮기는 중 */ }
    await sleep(300);
  }
  return false;
}

async function send(canon, item) {
  const res = await fetch(`${canon}/api/refs/inbox`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(item) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Canon이 받지 못했어요 (${res.status})`);
  return data;
}

async function collect(tabId, cfg, resume = false) {
  running = true;
  stopped = false;
  let sent = 0;
  let last = '';
  const done = (msg, error = false) => setRun({ running: false, msg, error });
  try {
    if (resume) {
      const { cursor } = await chrome.storage.local.get('cursor');
      if (!cursor || !cursor.url) return done('이어서 모을 화가 없어요. 먼저 한 번 모아 주세요.', true);
      await setRun({ running: true, msg: `마지막으로 모은 화로 가는 중: ${cursor.title || cursor.url}` });
      await goTo(tabId, cursor.url);
      const r0 = await waitBody(tabId, cfg.sel, '');
      if (stopped) return done('멈췄어요.');
      if (!r0) return done('마지막으로 모은 화 본문을 불러오지 못했어요. 그 화를 직접 연 뒤 다시 해 주세요.', true);
      if (r0.error) return done(r0.error, true);
      last = r0.text;  // 이 화는 이미 보냈으니, 다음 화(다른 글)가 뜰 때까지 기다린다
      await sleep(GAP_MS);
      const nx = await inPage(tabId, clickNext, cfg.next);
      if (!nx || !nx.ok) return done(`${(nx && nx.why) || '다음 화로 넘기지 못했어요'}. 마지막으로 모은 화가 끝 화일 수 있어요.`, !(nx && nx.why && !nx.why.includes('선택자')));
    }
    for (let i = 0; i < cfg.count; i += 1) {
      if (stopped) return done(`멈췄어요. ${sent}화를 보냈어요.`);
      await setRun({ running: true, msg: `${i + 1}/${cfg.count}화 본문을 기다리는 중 (보낸 화 ${sent})` });
      const r = await waitBody(tabId, cfg.sel, last);
      if (stopped) return done(`멈췄어요. ${sent}화를 보냈어요.`);
      if (!r) return done(`본문을 찾지 못했어요. 보낸 화 ${sent}. 본문 위치를 확인해 주세요.`, true);
      if (r.error) return done(r.error, true);
      const got = await send(cfg.canon, { title: r.title, url: r.url, text: r.text });
      sent += 1;
      last = r.text;
      await setCursor({ url: r.url, title: r.title });
      await setRun({ running: true, msg: `보냈어요: ${r.title} (${r.text.length.toLocaleString()}자${got.dup ? ', 이미 받은 화' : ''}). 받은 화 ${got.count}개` });
      if (i === cfg.count - 1) break;
      await sleep(GAP_MS);
      const nx = await inPage(tabId, clickNext, cfg.next);
      if (!nx || !nx.ok) return done(`${(nx && nx.why) || '다음 화로 넘기지 못했어요'}. ${sent}화를 보냈어요.`, !(nx && nx.why && !nx.why.includes('선택자')) );
    }
    return done(`다 보냈어요. ${sent}화를 Canon 레퍼런스 원고 > 원고 넣기에서 가져가세요.`);
  } catch (e) {
    return done(`${e.message || e}. 보낸 화 ${sent}. Canon 주소를 확인해 주세요.`, true);
  } finally {
    running = false;
  }
}

chrome.runtime.onMessage.addListener((m) => {
  if (m.cmd === 'stop') stopped = true;
  if (m.cmd === 'start' && !running) collect(m.tabId, m.cfg);
  if (m.cmd === 'resume' && !running) collect(m.tabId, m.cfg, true);
});

// 서비스 워커가 다시 떴는데 run 이 '도는 중'으로 남아 있으면 끝난 것으로 고친다
chrome.storage.local.get('run').then(({ run }) => { if (run && run.running && !running) setRun({ ...run, running: false, msg: `${run.msg}\n(중간에 끊겼어요. 다시 눌러 주세요)` }); });
