"""가려 읽기 '나란히 한 번 읽기' 묶음 (blindset mode 'side'): 쌍 짓기 · 긋기 · 체크 · 고르기 · 결과 · API · 명령줄 · 화면."""
import json

import pytest

from canon import blindset

from .jsvm import needs_node, run_js


def _rows():
    """대목 셋 × 판 둘 × 글 두 편 + 01 과 글자가 같은 13번 = 13편."""
    items, key = [], []
    for p in range(1, 4):
        for arm in ("가", "나"):
            for k in (1, 2):
                no = f"{len(items) + 1:02d}"
                items.append({"no": no, "text": f"대목 {p}의 {arm} 판 {k}번째 글이다. 둘째 문장이다.\n\n새 문단이다."})
                key.append({"no": no, "arm": arm, "piece": f"대목 {p}"})
    items.append({"no": "13", "text": items[0]["text"]})
    key.append({"no": "13", "arm": "가", "piece": "대목 1"})
    return items, key


def _set():
    items, key = _rows()
    return blindset.create("나란히", items, key, mode="side")


def _pick_all(s, pick=None):
    arm = {k.no: k.arm for k in s.key}
    for a, b in blindset.side_pairs(s):
        blindset.duel(s.id, a, b, pick(a, b, arm) if pick else blindset.TIE)


def test_side_pairs_mix_arms_and_split_the_same_text(client):
    s = _set()
    pairs = blindset.side_pairs(s)
    arm = {k.no: k.arm for k in s.key}
    piece = {k.no: k.piece for k in s.key}
    text = {x.no: x.text for x in s.items}
    assert all(arm[a] != arm[b] and piece[a] == piece[b] and text[a] != text[b] for a, b in pairs)
    assert {no for p in pairs for no in p} == {x.no for x in s.items}  # 모든 글이 적어도 한 쌍에 든다
    assert not any({"01", "13"} <= set(p) for p in pairs)  # 같은 글 두 편은 다른 쌍에 든다
    assert len(pairs) == 7  # 대목 1 은 다섯 편이라 한 글이 두 번 읽힌다
    assert pairs == blindset.side_pairs(blindset.load(s.id)) == blindset.duel_pairs(s)  # 늘 같은 차례 · 같은 좌우


def test_side_create_needs_pieces_and_two_arms(client):
    items, key = _rows()
    with pytest.raises(ValueError, match="대목 이름"):
        blindset.create("열쇠 없음", items, mode="side")
    with pytest.raises(ValueError, match="대목 이름"):
        blindset.create("대목 없음", items, [{**k, "piece": ""} for k in key], mode="side")
    with pytest.raises(ValueError, match="짝이 없는 글"):
        blindset.create("한 판", items[:2], [{**k, "arm": "가"} for k in key[:2]], mode="side")
    with pytest.raises(ValueError, match="읽는 방식"):
        blindset.create("이상한", items, key, mode="score")
    assert blindset.create("보통", items, key).mode == ""


def test_side_flow_without_scores(client):
    s = _set()
    v = blindset.view(s)
    assert v["mode"] == "side" and v["pieces"] == [] and v["result"] is None and len(v["duels"]) == 7
    d0 = v["duels"][0]
    assert d0["left"]["paras"] == blindset.sentences(next(x.text for x in s.items if x.no == d0["a"])) and d0["left"]["marks"] == []
    dumped = json.dumps(v, ensure_ascii=False)
    assert "arm" not in dumped and "대목 1\"" not in dumped and '"piece"' not in dumped  # 판 · 대목 이름은 결과 전에 없다
    assert v["picked"] == 0 and v["pairs"] == 7
    a, b = blindset.side_pairs(s)[0]
    blindset.duel(s.id, a, b, a)  # 점수 없이 고른다
    blindset.flag(s.id, a, blindset.CRITERIA[0])
    blindset.mark(s.id, a, 1)
    v = blindset.view(blindset.load(s.id))
    assert v["duels"][0]["pick"] == a and v["duels"][0]["left"]["marks"] == [1] and v["duels"][0]["left"]["flags"] == [blindset.CRITERIA[0]]
    with pytest.raises(ValueError, match="고르지 않은 쌍이 6개"):
        blindset.reveal(s.id)
    _pick_all(s)
    assert blindset.summary(blindset.load(s.id))["picked"] == 7
    r = blindset.view(blindset.reveal(s.id))["result"]
    assert r["duel"]["answered"] == 7 and r["arms"] == [] and "marks" in r
    with pytest.raises(ValueError, match="결과를 연 묶음은 고칠 수 없어요"):
        blindset.mark(s.id, a, 0)


def test_side_marks_stay_on_one_copy_and_give_noise(client):
    s = _set()
    blindset.mark(s.id, "01", 0)
    blindset.mark(s.id, "01", 1)
    got = blindset.mark(s.id, "13", 2)
    assert [m.idx for m in got.items[0].marks] == [0, 1] and [m.idx for m in got.items[12].marks] == [2]  # 같은 글에 번지지 않는다
    blindset.mark(s.id, "02", 0)
    blindset.mark(s.id, "05", 0, on=False)
    _pick_all(s)
    m = blindset.result(blindset.reveal(s.id))["marks"]
    assert m["noise"] == 1  # 01 은 두 문장, 13 은 한 문장
    by = {r["arm"]: r for r in m["arms"]}
    # 가 판: 글 여섯 (01 · 13 은 글 하나로 치고 평균 1.5), 나 판은 아무것도 긋지 않았다
    assert by["가"]["texts"] == 6 and by["가"]["marks"] == 2.5 and by["가"]["per_text"] == round(2.5 / 6, 2) and by["가"]["per_1k"] > 0
    assert by["나"] == {"arm": "나", "texts": 6, "marks": 0, "per_text": 0, "per_1k": 0}


def test_side_api(client):
    items, key = _rows()
    r = client.post("/api/blind", json={"title": "API 나란히", "items": items, "key": key, "mode": "side"})
    assert r.status_code == 200 and r.json()["mode"] == "side" and len(r.json()["duels"]) == 7
    bid = r.json()["id"]
    d = r.json()["duels"][0]
    assert client.put(f"/api/blind/{bid}/items/{d['a']}/marks", json={"idx": 0}).status_code == 200  # 결과 전에 긋는다
    assert client.put(f"/api/blind/{bid}/items/{d['a']}/flags", json={"label": blindset.CRITERIA[1]}).status_code == 200
    assert client.put(f"/api/blind/{bid}/duels", json={"a": d["a"], "b": d["b"], "pick": "="}).status_code == 200
    assert client.post(f"/api/blind/{bid}/reveal").status_code == 400
    for x in client.get(f"/api/blind/{bid}").json()["duels"][1:]:
        client.put(f"/api/blind/{bid}/duels", json={"a": x["a"], "b": x["b"], "pick": x["a"]})
    got = client.post(f"/api/blind/{bid}/reveal").json()
    assert got["revealed_at"] and got["result"]["marks"]["arms"]
    assert client.put(f"/api/blind/{bid}/items/{d['a']}/marks", json={"idx": 0}).status_code == 400  # 결과 뒤
    assert client.post("/api/blind", json={"items": items, "mode": "side"}).status_code == 400


def test_side_cli_import_and_list(client, tmp_path, capsys):
    from canon import cli

    items, key = _rows()
    d = tmp_path / "side"
    d.mkdir()
    for x in items:
        (d / f"{x['no']}.txt").write_text(x["text"], encoding="utf-8")
    (d / "blind_key.json").write_text(json.dumps({k["no"]: {"arm": k["arm"], "passage": k["piece"]} for k in key}, ensure_ascii=False), encoding="utf-8")
    cli.main(["blind", "import", "--side", str(d), "--title", "명령줄 나란히"])
    out = capsys.readouterr().out
    assert "묶음을 넣었어요: 명령줄 나란히 (13편, 열쇠 있음)" in out and "나란히 읽으세요" in out
    s = next(x for x in blindset.sets() if x.title == "명령줄 나란히")
    assert s.mode == "side"
    a, b = blindset.side_pairs(s)[0]
    blindset.duel(s.id, a, b, a)
    cli.main(["blind", "list"])
    assert "명령줄 나란히  1/7쌍 고름" in capsys.readouterr().out


@needs_node
def test_side_screens_keep_one_primary_button_and_hide_arms():
    got = run_js(["app.js", "blindset.js"], """(() => {
      fmtDateTime = () => '';
      S.jobs = []; S.route = ['blind'];
      const side = (a) => ({ paras: [['첫 문장 ' + a + '.', '둘째 문장.'], ['셋째 문장.']], marks: a === '01' ? [1] : [], flags: a === '01' ? ['말투'] : [] });
      const duels = [{ a: '01', b: '02', pick: '', left: side('01'), right: side('02') }, { a: '04', b: '03', pick: '03', left: side('04'), right: side('03') }];
      const texts = ['01', '02', '03', '04'].map((no) => ({ no, text: '글 ' + no + '.', chars: 5, score: 0, note: '', flags: [] }));
      const base = { id: 's1', title: '나란히', mode: 'side', items: 4, scored: 0, picked: 1, pairs: 2, scale: 5, criteria: ['늘어짐', '말투'], has_key: true, revealed_at: '', result: null, pieces: [], texts };
      S.bl = { ...base, duels }; S.blNo = ''; S.blPiece = -1; S.blDuel = 0;
      const pair = viewBlind();
      S.bl = { ...base, picked: 2, duels: duels.map((d) => ({ ...d, pick: '=' })) };
      const done = viewBlind();
      const result = { arms: [], pairs: [], noise: null, rows: texts.map((t) => ({ no: t.no, score: 0, note: '', arm: '가판', piece: '장면', marks: [{ idx: 0, text: 'x' }], flags: [] })),
        flags: { criteria: [], arms: [], rows: [], checked: 0, diff: null }, duel: { total: 2, answered: 2, arms: [{ arm: '가판', rate: 0.75, pairs: 2, win: 1, tie: 1, loss: 0 }], repeat: null },
        marks: { arms: [{ arm: '가판', texts: 2, marks: 3, per_text: 1.5, per_1k: 12.5 }], noise: 1 } };
      S.bl = { ...base, picked: 2, duels, revealed_at: 'x', result }; S.blDuel = -1;
      const res = viewBlind();
      const n = (h, re) => (h.match(re) || []).length;
      return { pair: [n(pair, /btn primary/g), n(pair, /data-bl-mark="0[12]"/g), n(pair, /aria-pressed="true" data-bl-mark="01" data-idx="1"/g), n(pair, /data-bl-no=/g),
          n(pair, /aria-pressed="true" data-bl-flag="말투" data-bl-no="01"/g), n(pair, /data-action="blPick"/g), pair.includes('1 / 2쌍 골랐어요'), pair.includes('가판'), n(pair, /data-action="blScore"/g)],
        done: [n(done, /btn primary/g), done.includes('class="btn primary" data-action="blReveal"'), done.includes('2 / 2쌍 골랐어요')],
        res: [n(res, /btn primary/g), res.includes('<h2>그은 문장</h2>'), res.includes('12.5'), res.includes('평균 1개 달라요'), res.includes('<h2>쌍 비교</h2>'), res.includes('열쇠가 없는'), res.includes('#/blind/s1/marks')],
        progress: [blProgress(base), blProgress({ scored: 1, items: 3 })] };
    })()""", {})
    assert got["pair"] == [0, 6, 1, 4, 1, 3, True, False, 0]  # 다 고르기 전에는 주 버튼이 없고, 판 이름 · 점수 버튼도 없다
    assert got["done"] == [1, True, True]  # 다 고르면 주 버튼 '결과 보기' 하나
    assert got["res"] == [0, True, True, True, True, False, False]
    assert got["progress"] == ["1 / 2쌍 고름", "1 / 3편 매김"]


@needs_node
def test_side_reveal_from_the_bare_address_shows_the_result():
    # 목록에서 연 #/blind/<id> 에서 결과를 열면 주소가 그대로라 다시 읽지 않는다. 쌍 화면 차례가 남으면 결과 대신 쌍 비교 화면이 나온다
    got = run_js(["app.js", "blindset.js"], """(async () => {
      fmtDateTime = () => '';
      S.jobs = []; S.route = ['blind'];
      const side = { paras: [['문장.']], marks: [], flags: [] };
      const texts = ['01', '02'].map((no) => ({ no, text: '문장.', chars: 3, score: 0, note: '', flags: [] }));
      const base = { id: 's1', title: '나란히', mode: 'side', items: 2, scored: 0, picked: 1, pairs: 1, scale: 5, criteria: [], has_key: true, pieces: [], texts,
        duels: [{ a: '01', b: '02', pick: '=', left: side, right: side }] };
      const result = { arms: [], pairs: [], noise: null, rows: [], flags: { criteria: [], arms: [], rows: [], checked: 0, diff: null },
        duel: { total: 1, answered: 1, arms: [], repeat: null }, marks: { arms: [{ arm: '가판', texts: 1, marks: 0, per_text: 0, per_1k: 0 }], noise: null } };
      S.bl = { ...base, revealed_at: '', result: null }; S.blNo = ''; S.blPiece = -1; S.blDuel = 0;
      askConfirm = async () => true;
      api = async () => ({ ...base, revealed_at: 'x', result });
      run = async (label, fn) => fn();
      await actions.blReveal();
      const html = viewBlind();
      return { duel: S.blDuel, result: html.includes('<h2>그은 문장</h2>'), pair: html.includes('쌍 골랐어요') || html.includes('쌍 비교 ·') };
    })()""", {})
    assert got == {"duel": -1, "result": True, "pair": False}
