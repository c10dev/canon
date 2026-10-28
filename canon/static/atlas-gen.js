/* 지도 만들기 (atlas.js 에서 뗐다). app.js 의 S, actions, api, run, esc 와 atlas.js 의 atlasRefresh · atlasStage · atlasLoad · atlasRecord · atlasPinMap 을 쓴다.
   서버 canon/towngen.py 마을 생성기, canon/citygen.py 도시 생성기, canon/moderngen.py 현대 동네 생성기로 미리보기(저장 안 함)를 받고 고른 장소와 함께 적용한다.
   미리보기 중인지는 atlas.js 의 atlasGenPreview 가 본다 (지도 그림도 미리보기를 그린다). */
'use strict';

// ----- 지도 만들기 (서버 canon/towngen.py 마을 생성기, canon/citygen.py 도시 생성기, canon/moderngen.py 현대 동네 생성기) -----

/** 지도 만들기 상태. 작품이 바뀌면 서버가 준 입력(gen.spec, 장소 표)으로 새로 시작한다 */
function atlasGenState() {
  const g = S.atlas.gen;
  const rows = () => g.places.map((x) => ({ key: x.key, kind: x.kind, put: x.put }));
  if (!S.atlasGen || S.atlasGen.name !== S.name) {
    const spec = { ...g.spec, places: rows() };
    if (!g.made) spec.seed = atlasNewSeed();
    S.atlasGen = { name: S.name, open: false, spec, preview: null, take: {}, touched: {}, ai: null, hist: [], at: -1 };
  } else if (S.atlasGen.spec.places.map((x) => x.key).join('\n') !== g.places.map((x) => x.key).join('\n')) {
    S.atlasGen.spec.places = rows();  // 장소가 더해지거나 빠졌으면 표를 새로 (설정 · 시드는 그대로)
    S.atlasGen.preview = null;
  }
  return S.atlasGen;
}

const atlasNewSeed = () => 1 + Math.floor(Math.random() * 2147483646);
/** 고른 지도 종류(spec.kind)의 설정 칸 { size: {id: 이름}, ... }. 도시는 길 모양 칸이 없다 */
const atlasGenOpts = (kind) => S.atlas.gen.options[kind || (S.atlasGen && S.atlasGen.spec.kind) || 'village'] || {};
const atlasGenLabel = (key, id, kind) => String((atlasGenOpts(kind)[key] || {})[id] || id);
/** 지도 종류 이름 (마을 · 도시) */
const atlasGenWord = (kind) => ((S.atlas.gen.maps || []).find((x) => x.id === kind) || { label: '마을' }).label;
/** 다른 지도 종류로 바꿨을 때 그 종류에 없는 값은 고친다 (도시에는 호수가 없어 강으로) */
function atlasGenFit(spec) {
  Object.entries(atlasGenOpts(spec.kind)).forEach(([key, opts]) => {
    if (!(spec[key] in opts)) spec[key] = key === 'water' && spec[key] === 'lake' && 'river' in opts ? 'river' : Object.keys(opts)[Math.min(1, Object.keys(opts).length - 1)];
  });
}
const atlasKindLabel = (id) => ((S.atlas.gen.kinds || []).find((k) => k.id === id) || { label: id }).label;

function atlasGenForm(st) {
  const opts = atlasGenOpts(st.spec.kind);
  const sel = (key, label) => (opts[key] ? `<label class="at-gen-opt small">${label}
    <select data-at-gen="${key}">${Object.keys(opts[key]).map((id) => `<option value="${esc(id)}"${st.spec[key] === id ? ' selected' : ''}>${esc(atlasGenLabel(key, id))}</option>`).join('')}</select></label>` : '');
  const maps = (S.atlas.gen.maps || []).map((x) => `<option value="${esc(x.id)}"${st.spec.kind === x.id ? ' selected' : ''}>${esc(x.label)}</option>`).join('');
  const word = atlasGenWord(st.spec.kind);
  const notes = (st.ai && st.ai.notes) || {};
  const rows = S.atlas.gen.places.map((pl, i) => {
    const mine = st.spec.places[i];
    return `<div class="at-gen-place"><label class="small"><input type="checkbox" data-at-gen-put="${i}"${mine.put ? ' checked' : ''}> ${esc(pl.name)}</label>
      <select data-at-gen-kind="${i}" aria-label="${esc(pl.name)} 종류">${S.atlas.gen.kinds.map((k) => `<option value="${esc(k.id)}"${mine.kind === k.id ? ' selected' : ''}>${esc(k.label)}</option>`).join('')}</select>
      ${notes[pl.key] ? `<div class="small at-um-note at-gen-note">${esc(notes[pl.key])}</div>` : ''}</div>`;
  }).join('');
  const why = st.ai && st.ai.reason
    ? `<div class="note" role="status">AI 제안: ${esc(st.ai.reason)}</div>`
    : !S.atlas.gen.made && S.atlas.gen.spec.water !== 'none' && !st.touched.water
      ? `<div class="small">물가가 필요한 장소가 있어 물을 '${esc(atlasGenLabel('water', st.spec.water))}'(으)로 골라 뒀어요.</div>` : '';
  return `<div class="at-gen-opts"><label class="at-gen-opt small">지도<select data-at-gen="kind" aria-label="만들 지도">${maps}</select></label>
      ${sel('size', '크기')}${sel('roads', '길 모양')}${sel('water', '물')}${sel('fields', '밭')}${sel('forest', '숲')}
      <label class="at-gen-opt small">시드 <span class="row"><input type="number" min="0" max="2147483647" step="1" value="${st.spec.seed}" data-at-gen-seed aria-label="시드">
        <button type="button" class="btn small ghost" data-action="atlasGenSeed">새 시드</button></span></label></div>
    ${why}
    ${st.spec.kind === 'city' ? '<div class="small">도시는 성벽 · 성문 · 구역(시장, 신전, 귀족, 장인, 빈민 등)이 있는 큰 지도예요. 이야기 장소는 종류에 맞는 구역에 놓아요.</div>' : ''}
    ${st.spec.kind === 'modern' ? '<div class="small">현대 동네는 대로 격자 안에 아파트 단지 · 빌라촌 · 대로변 상가 · 역 앞 · 학교 · 공원이 있는 가상의 동네예요. 숲 칸은 공원 수를 정해요. 주막은 호텔, 신전은 교회, 장터는 마트 자리에 놓아요.</div>' : ''}
    <div class="small">같은 시드와 설정이면 언제나 같은 ${word}${word === '마을' ? '이' : '가'} 나와요. 장소 종류는 이름에서 찾았어요. 틀리면 고르거나 AI 제안을 받아 보세요.</div>
    <div class="at-gen-places">${rows}</div>
    <div class="row"><button type="button" class="btn small primary" data-action="atlasGenPreview">미리보기</button>
      <button type="button" class="btn small" data-action="atlasGenSuggest">AI로 설정 제안</button>
      <button type="button" class="btn small ghost" data-action="atlasGenOpen" data-arg="">닫기</button></div>`;
}

function atlasGenResult(st) {
  const pv = st.preview;
  const i = pv.info;
  const pins = pv.pins.map((s) => `<label class="small at-gen-take"><input type="checkbox" data-at-gen-take="${esc(s.place)}"${st.take[s.place] ? ' checked' : ''}>
      ${esc(s.name)} → ${esc(atlasKindLabel(s.kind))} 자리${s.had ? ' <span class="at-um-note">(지금 자리에서 옮겨요)</span>' : ''}</label>`).join('');
  const miss = pv.missing.map((m) => `<li>${esc(m.name)}: ${esc(m.reason)}</li>`).join('');
  const blocked = pv.blocked.map((b) => esc(b.name)).join(', ');
  const word = atlasGenWord(st.spec.kind);
  const homes = st.spec.kind === 'modern' ? '건물' : '집';
  return `<div class="small">${esc(word)} · 시드 ${st.spec.seed} · ${homes} ${i.houses.toLocaleString()}채 · 길 ${i.roads}개${i.bridges ? ` · 다리 ${i.bridges}개` : ''}${i.gates ? ` · 구역 ${i.wards}곳 · 성문 ${i.gates}곳` : ''} · 약 ${atlasMeters(i.width_m)} × ${atlasMeters(i.height_m)}</div>
    ${pins ? `<div class="at-gen-places">${pins}</div>` : '<div class="small">새로 놓을 장소가 없어요.</div>'}
    ${miss ? `<div class="note" role="status">놓지 못한 장소<ul class="at-list">${miss}</ul></div>` : ''}
    ${blocked ? `<div class="note" role="status">${blocked}: 지금 자리가 새 ${esc(word)}의 건물이나 물 위예요. 적용한 뒤 옮겨 주세요.</div>` : ''}
    <div class="small">적용하면 지금 지도 데이터를 바꿔요. 고른 장소만 새 자리로 옮기고, 나머지 장소 자리는 그대로 둬요.</div>
    <div class="row"><button type="button" class="btn small primary" data-action="atlasGenApply">적용</button>
      <button type="button" class="btn small" data-action="atlasGenSeed">다른 시드로</button>
      <button type="button" class="btn small ghost" data-action="atlasGenEdit">설정 고치기</button>
      <button type="button" class="btn small ghost" data-action="atlasGenOpen" data-arg="">그만두기</button></div>`;
}

function atlasGenBox() {
  if (!S.atlas.gen) return '';
  const st = atlasGenState();
  const made = S.atlas.gen.made && S.atlas.layout;
  const word = atlasGenWord(st.spec.kind);
  if (!st.open) {
    return `<div class="at-box"><h3>지도 만들기</h3>
      <div class="small">${made ? `시드 ${S.atlas.gen.spec.seed}로 만든 ${esc(atlasGenWord(S.atlas.gen.spec.kind))}예요. 설정을 바꿔 다시 만들 수 있어요.` : '마을 · 도시 · 현대 동네 생성기로 길 · 집 · 밭 · 물이 있는 지도를 만들어요. 도시는 성벽과 구역, 현대 동네는 아파트 단지와 빌라촌이 있어요. 이야기 장소는 종류에 맞는 자리(신전, 주막, 나루 등)에 놓아요.'}</div>
      <div class="row"><button type="button" class="btn small" data-action="atlasGenOpen" data-arg="1">${made ? '다시 만들기' : '지도 만들기'}</button></div></div>`;
  }
  return `<div class="at-box at-gen"><h3>${esc(word)} ${st.preview ? '미리보기' : '만들기'}</h3>${st.preview ? atlasGenResult(st) : atlasGenForm(st)}</div>`;
}

async function atlasGenRun() {
  const st = atlasGenState();
  await run(`${atlasGenWord(st.spec.kind)} 만드는 중`, async () => {
    const pv = await api('POST', `/projects/${enc(S.name)}/atlas/generate/preview`, st.spec);
    // 미리보기 이력: 지금 자리 뒤는 버리고 새로 붙인다 (최근 20개). ← → 로 다시 부르지 않고 오간다
    st.hist = [...st.hist.slice(0, st.at + 1), { spec: JSON.parse(JSON.stringify(st.spec)), pv }].slice(-20);
    st.at = st.hist.length - 1;
    atlasGenShow(pv);
  });
}

function atlasGenShow(pv) {
  const st = S.atlasGen;
  st.preview = pv;
  st.take = Object.fromEntries(pv.pins.map((s) => [s.place, !s.had]));  // 이미 놓은 장소는 그대로 두는 게 기본
  S.atlasBld = null;
  atlasRefresh();
}

/** 미리보기 조작 막대 (지도 아래에 붙는다) */
function atlasGenBar() {
  const st = S.atlasGen;
  const pv = atlasGenPreview();
  if (!pv) return '';
  const at = st.at;
  return `<div class="at-pv-bar" role="toolbar" aria-label="${esc(atlasGenWord(st.spec.kind))} 미리보기">
    <span class="small">시드 ${st.spec.seed} · 집 ${pv.info.houses.toLocaleString()}채${st.hist.length > 1 ? ` · ${at + 1}/${st.hist.length}` : ''}</span>
    <span class="row">
      <button type="button" class="btn small ghost" data-action="atlasGenHist" data-arg="-1" title="이전 미리보기 (←)" aria-label="이전 미리보기"${at <= 0 ? ' disabled' : ''}>◀</button>
      <button type="button" class="btn small" data-action="atlasGenSeed" title="다른 시드로 (Enter)">다른 시드</button>
      <button type="button" class="btn small ghost" data-action="atlasGenHist" data-arg="1" title="다음 미리보기 (→)" aria-label="다음 미리보기"${at >= st.hist.length - 1 ? ' disabled' : ''}>▶</button>
      <button type="button" class="btn small ghost" data-action="atlasGenOpen" data-arg="" title="그만두기 (Esc)">그만두기</button>
      <button type="button" class="btn small primary" data-action="atlasGenApply">적용</button></span></div>`;
}

Object.assign(actions, {
  atlasGenOpen(on) {
    const st = atlasGenState();
    st.open = !!on;
    st.preview = null;
    st.hist = [];
    st.at = -1;
    atlasRefresh();
  },
  atlasGenHist(d) {
    const st = atlasGenState();
    const at = st.at + Number(d);
    if (!st.preview || at < 0 || at >= st.hist.length) return;
    st.at = at;
    st.spec = JSON.parse(JSON.stringify(st.hist[at].spec));
    atlasGenShow(st.hist[at].pv);
  },
  async atlasGenSeed() {
    const st = atlasGenState();
    st.spec.seed = atlasNewSeed();
    if (st.preview) await atlasGenRun(); else atlasRefresh();
  },
  async atlasGenPreview() {
    await atlasGenRun();
  },
  async atlasGenSuggest() {
    const st = atlasGenState();
    await run('AI가 지도 설정을 고르는 중', async () => {
      const r = await api('POST', `/projects/${enc(S.name)}/atlas/generate/suggest`, st.spec);
      let changed = 0;
      // 작가가 고른 칸은 덮지 않는다. 지도 종류를 먼저 정하고 그 종류의 칸만 채운다
      ['kind', ...Object.keys(atlasGenOpts(st.touched.kind ? st.spec.kind : r.kind))].forEach((k) => {
        if (!st.touched[k] && r[k] && st.spec[k] !== r[k]) { st.spec[k] = r[k]; changed++; }
      });
      atlasGenFit(st.spec);
      const notes = {};
      r.places.forEach((g) => {
        const row = st.spec.places.find((x) => x.key === g.key);
        if (g.note) notes[g.key] = g.note;
        if (!row || st.touched['p:' + g.key] || (row.kind === g.kind && row.put === g.put)) return;
        row.kind = g.kind;
        row.put = g.put;
        changed++;
      });
      st.ai = { reason: r.reason, notes };
      atlasRefresh();
      toast(changed ? `AI 제안으로 ${changed}칸을 바꿨어요. 확인하고 미리보기를 누르세요` : 'AI 제안이 지금 설정과 같아요');
    });
  },
  atlasGenEdit() {
    atlasGenState().preview = null;
    atlasRefresh();
  },
  async atlasGenApply() {
    const st = atlasGenState();
    const pins = Object.keys(st.take).filter((k) => st.take[k]);
    const before = atlasPinMap();
    await run(`${atlasGenWord(st.spec.kind)} 적용하는 중`, async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/atlas/generate`, { spec: st.spec, pins });
      st.preview = null;
      st.open = false;
      await atlasLoad();
      atlasRecord(before, '지도 적용으로 장소 옮기기', atlasPinMap(), true);
      atlasRefresh();
      toast(`${atlasGenWord(st.spec.kind)}${st.spec.kind === 'village' ? '을' : '를'} 적용했어요${pins.length ? ` · 장소 ${pins.length}곳을 놓았어요` : ''}`);
    });
  },
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.matches('[data-at-gen]')) {
    const st = atlasGenState();
    st.spec[t.dataset.atGen] = t.value;
    st.touched[t.dataset.atGen] = true;
    if (t.dataset.atGen === 'kind') {  // 칸이 바뀌니 다시 그린다
      atlasGenFit(st.spec);
      atlasRefresh();
    }
    return;
  }
  if (t.matches('[data-at-gen-seed]')) {
    const seed = Number(t.value);
    if (!Number.isInteger(seed) || seed < 0 || seed > 2147483647) { toast('시드는 0~2147483647 사이 정수로 적으세요', true); return; }
    atlasGenState().spec.seed = seed;
    return;
  }
  if (t.matches('[data-at-gen-kind]')) {
    const st = atlasGenState();
    const row = st.spec.places[Number(t.dataset.atGenKind)];
    row.kind = t.value;
    row.put = t.value !== 'far';  // 마을 밖 장소는 놓지 않는 게 기본
    st.touched['p:' + row.key] = true;
    atlasRefresh();
    return;
  }
  if (t.matches('[data-at-gen-put]')) {
    const st = atlasGenState();
    const row = st.spec.places[Number(t.dataset.atGenPut)];
    row.put = t.checked;
    st.touched['p:' + row.key] = true;
    return;
  }
  if (t.matches('[data-at-gen-take]')) {
    atlasGenState().take[t.dataset.atGenTake] = t.checked;
    const stage = document.getElementById('atlas-stage');
    if (stage) stage.innerHTML = atlasStage();
    return;
  }
});
