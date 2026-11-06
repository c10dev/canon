/* 팝업: 설정을 저장하고 background.js 에 모으기를 시킨다. 진행 상태는 storage 의 run 으로 받는다. */
'use strict';
const $ = (id) => document.getElementById(id);
const FIELDS = { canon: CANON_DEFAULT, sel: '[data-theme-novel-content]', next: '', count: '10' };

function cfg() {
  return { canon: $('canon').value.trim().replace(/\/+$/, ''), sel: $('sel').value.trim(), next: $('next').value.trim(), count: Math.max(1, Math.min(1000, Number($('count').value) || 1)) };
}

function show(run) {
  const busy = !!(run && run.running);
  $('one').disabled = busy;
  $('many').disabled = busy;
  $('stop').hidden = !busy;
  const st = $('status');
  st.textContent = run ? run.msg || '' : '';
  st.className = run && run.error ? 'err' : '';
}

async function start(count) {
  const c = cfg();
  await chrome.storage.local.set({ canon: c.canon, sel: c.sel, next: c.next, count: String(c.count) });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  chrome.runtime.sendMessage({ cmd: 'start', tabId: tab.id, cfg: { ...c, count } });
}

(async () => {
  const saved = await chrome.storage.local.get([...Object.keys(FIELDS), 'run']);
  for (const [k, v] of Object.entries(FIELDS)) $(k).value = saved[k] ?? v;
  show(saved.run);
  chrome.storage.onChanged.addListener((ch) => { if (ch.run) show(ch.run.newValue); });
  $('one').addEventListener('click', () => start(1));
  $('many').addEventListener('click', () => start(cfg().count));
  $('stop').addEventListener('click', () => chrome.runtime.sendMessage({ cmd: 'stop' }));
})();
