"""가려 읽기 묶음 (canon/blindset.py): 넣기 · 점수 · 결과 열기 · 흔들림 · 열쇠 가리기 · 거슬린 문장 긋기 · 기준 항목 체크 · 쌍 비교 · API · 명령줄 · 화면."""
import json

import pytest

from canon import blindset

from .jsvm import needs_node, run_js

TEXTS = ["가 판의 첫 글이다.", "나 판의 첫 글이다.", "가 판의 둘째 글이다.", "나 판의 둘째 글이다.", "가 판의 첫 글이다.", "나 판의 첫 글이다."]
KEY = [{"no": f"{i:02d}", "arm": arm, "piece": piece} for i, (arm, piece) in
       enumerate([("가", "장면 1"), ("나", "장면 1"), ("가", "장면 2"), ("나", "장면 2"), ("가", "장면 1"), ("나", "장면 1")], 1)]


def _set():
    return blindset.create("규칙 시험", [{"text": t} for t in TEXTS], KEY, note="메모")


def test_create_numbers_items_and_checks_input(client):
    s = _set()
    assert [x.no for x in s.items] == ["01", "02", "03", "04", "05", "06"] and len(s.key) == 6 and blindset.load(s.id).title == "규칙 시험"
    with pytest.raises(ValueError, match="2~60편"):
        blindset.create("하나", [{"text": "글"}])
    with pytest.raises(ValueError, match="비어 있어요"):
        blindset.create("빈 글", [{"text": "글"}, {"text": "  "}])
    with pytest.raises(ValueError, match="덮지 않아요"):
        blindset.create("열쇠 모자람", [{"text": "가"}, {"text": "나"}], [{"no": "01", "arm": "가"}])
    with pytest.raises(ValueError, match="열쇠에 없는 번호"):
        blindset.create("열쇠 번호", [{"text": "가"}, {"text": "나"}], [{"no": "09", "arm": "가"}])
    assert blindset.create("열쇠 없음", [{"text": "가"}, {"text": "나"}]).key == []
    assert [x.title for x in blindset.sets()].count("규칙 시험") == 1


def test_view_hides_the_key_until_reveal(client):
    s = _set()
    v = blindset.view(s)
    assert v["has_key"] and v["result"] is None and v["scored"] == 0 and v["scale"] == 5
    assert "arm" not in json.dumps(v, ensure_ascii=False) and "장면 1" not in json.dumps(v, ensure_ascii=False)
    with pytest.raises(ValueError, match="6편"):
        blindset.reveal(s.id)
    for no, n in zip(["01", "02", "03", "04", "05", "06"], [4, 2, 5, 3, 3, 2]):
        blindset.score(s.id, no, n, "한마디" if no == "03" else "")
    with pytest.raises(ValueError, match="1~5점"):
        blindset.score(s.id, "01", 6)
    with pytest.raises(KeyError):
        blindset.score(s.id, "99", 3)
    assert blindset.view(blindset.load(s.id))["result"] is None  # 다 매겨도 열기 전에는 가린다
    v = blindset.view(blindset.reveal(s.id))
    r = v["result"]
    # 같은 글 두 편(01 · 05, 02 · 06)은 평균 하나로 친다: 가 = (3.5 + 5) / 2, 나 = (2 + 3) / 2
    assert [(a["arm"], a["mean"], a["texts"]) for a in r["arms"]] == [("가", 4.25, 2), ("나", 2.5, 2)]
    assert [(p["a"], p["b"], p["diff"]) for p in r["pairs"]] == [("01", "05", 1), ("02", "06", 0)] and r["noise"] == 0.5
    assert r["arms"][0]["close"] and not r["arms"][1]["close"]  # 1.75점 차는 흔들림 0.5 보다 크다
    assert r["rows"][2] == {"no": "03", "score": 5, "note": "한마디", "arm": "가", "piece": "장면 2", "marks": [], "flags": []}
    with pytest.raises(ValueError, match="고칠 수 없어요"):
        blindset.score(s.id, "01", 1)


def test_score_zero_clears_and_no_pairs_means_no_noise(client):
    s = blindset.create("짝 없음", [{"text": "가"}, {"text": "나"}], [{"no": "01", "arm": "가"}, {"no": "02", "arm": "나"}])
    blindset.score(s.id, "01", 3)
    assert blindset.score(s.id, "01", 0).items[0].score == 0
    blindset.score(s.id, "01", 3)
    blindset.score(s.id, "02", 4)
    r = blindset.result(blindset.reveal(s.id))
    assert r["noise"] is None and r["pairs"] == [] and not any(a["close"] for a in r["arms"])


def test_import_folder_reads_numbered_texts_and_the_key(client, tmp_path):
    d = tmp_path / "exp" / "blind"
    d.mkdir(parents=True)
    for i, t in enumerate(TEXTS[:3], 1):
        (d / f"{i:02d}.txt").write_text(t, encoding="utf-8")
    (d / "notes.txt").write_text("글이 아니다", encoding="utf-8")
    (d / "scores.json").write_text("{}", encoding="utf-8")
    (d.parent / "blind_key.json").write_text(json.dumps({"01": {"arm": "A", "passage": "대목 1", "same_text_again": False},
                                                         "02": {"arm": "B", "passage": "대목 1"}, "03": {"arm": "A", "passage": "대목 2"}}, ensure_ascii=False), encoding="utf-8")
    s = blindset.import_folder(str(d))
    assert s.title == "exp" and [x.no for x in s.items] == ["01", "02", "03"] and s.source == str(d)
    assert [(k.no, k.arm, k.piece) for k in s.key] == [("01", "A", "대목 1"), ("02", "B", "대목 1"), ("03", "A", "대목 2")]
    with pytest.raises(ValueError, match="txt 파일이 없어요"):
        blindset.import_folder(str(tmp_path))


def test_api_flow(client):
    r = client.post("/api/blind", json={"title": "API 묶음", "items": [{"text": t} for t in TEXTS[:2]], "key": KEY[:2]})
    assert r.status_code == 200 and r.json()["result"] is None
    bid = r.json()["id"]
    assert client.get("/api/blind").json()["sets"][0]["title"] == "API 묶음"
    assert client.post(f"/api/blind/{bid}/reveal").status_code == 400
    assert client.put(f"/api/blind/{bid}/items/01", json={"score": 4, "note": "좋음"}).json()["scored"] == 1
    assert client.put(f"/api/blind/{bid}/items/02", json={"score": 9}).status_code == 400
    assert client.put(f"/api/blind/{bid}/items/77", json={"score": 3}).status_code == 404
    client.put(f"/api/blind/{bid}/items/02", json={"score": 2})
    got = client.post(f"/api/blind/{bid}/reveal").json()
    assert got["revealed_at"] and [a["arm"] for a in got["result"]["arms"]] == ["가", "나"]
    assert client.put(f"/api/blind/{bid}/items/01", json={"score": 1}).status_code == 400
    assert client.get("/api/blind/00000000").status_code == 404 and client.post("/api/blind", json={"items": [{"text": "하나"}]}).status_code == 400
    assert client.delete(f"/api/blind/{bid}").json() == {"ok": True} and client.get(f"/api/blind/{bid}").status_code == 404


def test_cli_import_and_list(client, tmp_path, capsys):
    from canon import cli

    d = tmp_path / "blind"
    d.mkdir()
    (d / "1.txt").write_text("가", encoding="utf-8")
    (d / "2.txt").write_text("나", encoding="utf-8")
    cli.main(["blind", "import", str(d), "--title", "명령줄 묶음"])
    out = capsys.readouterr().out
    assert "묶음을 넣었어요: 명령줄 묶음 (2편, 열쇠 없음)" in out and "#/blind/" in out
    cli.main(["blind", "list"])
    assert "명령줄 묶음  0/2편 매김" in capsys.readouterr().out


@needs_node
def test_screen_shows_no_key_before_reveal_and_one_primary_button():
    texts = [{"no": "01", "text": "첫 글.\n\n둘째 문단.", "chars": 10, "score": 4, "note": ""}, {"no": "02", "text": "둘째 글.", "chars": 5, "score": 0, "note": ""},
             {"no": "03", "text": "셋째 글.", "chars": 5, "score": 0, "note": ""}]
    got = run_js(["app.js", "blindset.js"], """(() => {
      fmtDateTime = () => '';
      const texts = data.texts;
      S.jobs = []; S.route = ['blind'];
      const out = { next: [blNext(texts, '01'), blNext(texts, '03'), blNext(texts.map((t) => ({ ...t, score: 3 })), '01')], progress: blProgress({ scored: 1, items: 3 }) };
      S.bl = { id: 'b1', title: '묶음', items: 3, scored: 1, scale: 5, texts, has_key: true, result: null, revealed_at: '' }; S.blNo = '02';
      const open = viewBlind();
      out.open = { primary: (open.match(/btn primary/g) || []).length, scores: (open.match(/data-action="blScore"/g) || []).length, body: open.includes('둘째 글.'), nav: (open.match(/class="bl-no/g) || []).length };
      S.bl = { ...S.bl, scored: 3, texts: texts.map((t) => ({ ...t, score: 3 })) };
      out.done = (viewBlind().match(/btn primary/g) || []).length;
      const result = { arms: [{ arm: '가', mean: 4, texts: 2, low: 3, high: 5, close: true }, { arm: '나', mean: 3.5, texts: 2, low: 3, high: 4, close: true }, { arm: '다', mean: 2, texts: 2, low: 2, high: 2, close: false }],
        pairs: [{ a: '01', b: '03', diff: 1 }], noise: 1, rows: texts.map((t) => ({ no: t.no, score: 3, note: '', arm: '가', piece: '장면' })) };
      S.bl = { ...S.bl, result, revealed_at: '2026-11-13T10:00:00' }; S.blNo = '';
      const shown = viewBlind();
      out.result = { table: shown.includes('<td>가</td>'), locked: !shown.includes('data-action="blReveal"'), notes: result.arms.map((a) => blArmNote(a, 4, 1)) };
      S.blNo = '01';
      out.locked = (viewBlind().match(/data-action="blScore" data-arg="\\d"[^>]*disabled/g) || []).length;
      return out;
    })()""", {"texts": texts})
    assert got["next"] == ["02", "02", ""] and got["progress"] == "1 / 3편 매김"
    assert got["open"] == {"primary": 0, "scores": 5, "body": True, "nav": 3}  # 다 매기기 전에는 주 버튼이 없다
    assert got["done"] == 1  # 다 매기면 '결과 보기' 하나
    assert got["result"]["table"] and got["result"]["locked"] and got["locked"] == 5
    assert got["result"]["notes"] == ["가장 높아요", "0.5점 낮지만 흔들림(1) 안이에요", "2점 낮고 흔들림(1)보다 커요"]


def test_sentences_split_paragraphs_and_keep_numbers(client):
    got = blindset.sentences('첫 문장이다. 둘째는 3.5점이다!\n"말했다." 그가 웃었다.\n\n끝이 없는 줄')
    assert got == [["첫 문장이다.", "둘째는 3.5점이다!", '"말했다."', "그가 웃었다."], ["끝이 없는 줄"]]
    assert blindset.sentences("  \n\n ") == []


def test_marks_need_reveal_and_follow_the_same_text(client):
    s = _set()
    assert blindset.view(s)["pieces"] == []  # 대목이 곧 열쇠라 열기 전에는 싣지 않는다
    with pytest.raises(ValueError, match="결과를 연 뒤"):
        blindset.mark(s.id, "01", 0)
    for no, n in zip(["01", "02", "03", "04", "05", "06"], [4, 2, 5, 3, 3, 2]):
        blindset.score(s.id, no, n)
    assert blindset.view(blindset.load(s.id))["pieces"] == []
    blindset.reveal(s.id)
    with pytest.raises(ValueError, match="없는 문장"):
        blindset.mark(s.id, "01", 5)
    with pytest.raises(KeyError):
        blindset.mark(s.id, "99", 0)
    got = blindset.mark(s.id, "01", 0)
    # 글자가 같은 05번에도 같이 긋는다
    assert [(x.no, [(m.idx, m.text) for m in x.marks]) for x in got.items if x.marks] == [("01", [(0, "가 판의 첫 글이다.")]), ("05", [(0, "가 판의 첫 글이다.")])]
    v = blindset.view(got)
    # 점수 차가 큰 대목이 앞, 대목 안에서는 낮은 글부터, 같은 글 두 편은 하나로. 판 이름은 싣지 않는다
    assert [(g["piece"], g["spread"], [(t["nos"], t["scores"], t["marks"]) for t in g["texts"]]) for g in v["pieces"]] == [
        ("장면 2", 2.0, [(["04"], [3], []), (["03"], [5], [])]),
        ("장면 1", 1.5, [(["02", "06"], [2, 2], []), (["01", "05"], [4, 3], [0])])]
    assert "arm" not in json.dumps(v["pieces"], ensure_ascii=False) and v["pieces"][0]["texts"][0]["paras"] == [["나 판의 둘째 글이다."]]
    assert v["result"]["rows"][0]["marks"] == [{"idx": 0, "text": "가 판의 첫 글이다."}]
    assert blindset.mark(s.id, "05", 0, on=False).items[0].marks == []  # 지울 때도 같은 글 둘 다


def test_marks_api(client):
    r = client.post("/api/blind", json={"title": "긋기", "items": [{"text": t} for t in TEXTS[:2]], "key": KEY[:2]})
    bid = r.json()["id"]
    assert client.put(f"/api/blind/{bid}/items/01/marks", json={"idx": 0}).status_code == 400  # 열기 전
    client.put(f"/api/blind/{bid}/items/01", json={"score": 4})
    client.put(f"/api/blind/{bid}/items/02", json={"score": 2})
    client.post(f"/api/blind/{bid}/reveal")
    got = client.put(f"/api/blind/{bid}/items/01/marks", json={"idx": 0}).json()
    assert [t["marks"] for t in got["pieces"][0]["texts"]] == [[], [0]]
    assert client.put(f"/api/blind/{bid}/items/01/marks", json={"idx": 0, "on": False}).json()["pieces"][0]["texts"][1]["marks"] == []
    assert client.put(f"/api/blind/{bid}/items/01/marks", json={"idx": 9}).status_code == 400
    assert client.put(f"/api/blind/{bid}/items/77/marks", json={"idx": 0}).status_code == 404


def test_old_set_file_without_marks_still_loads(client):
    s = _set()
    path = blindset.root() / f"{s.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for x in raw["items"]:
        x.pop("marks")
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert blindset.load(s.id).items[0].marks == []


@needs_node
def test_marks_screen_hides_arms_and_adds_no_primary_button():
    pieces = [{"piece": "장면 1", "spread": 1, "texts": [{"nos": ["01"], "scores": [2], "paras": [["첫 문장.", "둘째 문장."], ["셋째 문장."]], "marks": [1]},
                                                    {"nos": ["02", "09"], "scores": [3, 4], "paras": [["다른 글."]], "marks": []}]},
              {"piece": "", "spread": 0, "texts": [{"nos": ["03"], "scores": [3], "paras": [["끝."]], "marks": [0]}]}]
    got = run_js(["app.js", "blindset.js"], """(() => {
      fmtDateTime = () => '';
      S.jobs = []; S.route = ['blind'];
      const rows = [{ no: '01', score: 2, note: '', arm: '가판', piece: '장면 1', marks: [] }];
      S.bl = { id: 'b1', title: '묶음', items: 3, scored: 3, scale: 5, texts: [{ no: '01', text: '첫 문장.', chars: 5, score: 2, note: '' }], has_key: true, revealed_at: 'x',
        result: { arms: [{ arm: '가판', mean: 2, texts: 1, low: 2, high: 2, close: false }], pairs: [], noise: null, rows }, pieces: data.pieces };
      S.blNo = ''; S.blPiece = -1;
      const res = viewBlind();
      S.blPiece = 0;
      const html = viewBlind();
      return { link: res.includes('href="#/blind/b1/marks"'), count: [blMarkCount(S.bl), blMarkCount(S.bl, 0), blMarkCount(S.bl, 1)], head: data.pieces[0].texts.map(blColHead),
        primary: (html.match(/btn primary/g) || []).length + (res.match(/btn primary/g) || []).length, arm: html.includes('가판'),
        spans: (html.match(/data-bl-mark=/g) || []).length, on: (html.match(/aria-pressed="true" data-bl-mark="01" data-idx="1"/g) || []).length,
        idx: [...html.matchAll(/data-bl-mark="01" data-idx="(\\d)"/g)].map((m) => m[1]).join(''), tabs: (html.match(/marks\\/\\d"/g) || []).length, unnamed: html.includes('대목 2') };
    })()""", {"pieces": pieces})
    assert got["link"] and got["count"] == [2, 1, 1] and got["head"] == ["01번 · 2점", "02번 · 09번 · 3 · 4점"]
    assert got["primary"] == 0 and not got["arm"]  # 긋는 동안 판 이름은 보이지 않는다
    assert got["spans"] == 4 and got["on"] == 1 and got["idx"] == "012" and got["tabs"] == 2 and got["unnamed"]


def test_flags_keep_when_not_sent_and_count_the_same_text_once(client):
    s = _set()
    crit = list(blindset.CRITERIA)
    assert s.criteria == crit and blindset.view(s)["criteria"] == crit  # 넣을 때의 항목을 묶음에 적어 둔다
    blindset.score(s.id, "02", 0, flags=[crit[1], crit[0]])  # 점수 없이도 남고, 항목 차례로 적는다
    assert blindset.load(s.id).items[1].flags == crit[:2] and not blindset.load(s.id).items[1].score
    blindset.score(s.id, "02", 2, "한마디")  # 점수만 보내는 호출은 체크를 지우지 않는다
    assert blindset.load(s.id).items[1].flags == crit[:2]
    with pytest.raises(ValueError, match="없는 기준 항목"):
        blindset.score(s.id, "02", 2, flags=["없는 항목"])
    blindset.score(s.id, "02", 2, flags=[crit[0]])
    for no, n in zip(["01", "03", "04", "05", "06"], [4, 5, 3, 3, 2]):
        blindset.score(s.id, no, n, flags=[crit[0]] if no == "04" else None)
    v = blindset.view(blindset.load(s.id))
    assert v["texts"][1]["flags"] == [crit[0]] and v["result"] is None
    f = blindset.view(blindset.reveal(s.id))["result"]["flags"]
    # 나 판의 글 둘: 02 · 06 은 같은 글이라 하나로 치고 한 편만 체크해 0.5, 04 는 1
    assert f["arms"] == ["가", "나"] and f["rows"][0] == {"label": crit[0], "counts": [{"arm": "가", "n": 0, "texts": 2}, {"arm": "나", "n": 1.5, "texts": 2}], "total": 2}
    assert f["checked"] == 2 and f["diff"] == 1  # 같은 글 02 · 06 에서 엇갈린 체크 하나
    with pytest.raises(ValueError, match="고칠 수 없어요"):
        blindset.score(s.id, "02", 2, flags=[])
    with pytest.raises(ValueError, match="8개까지"):
        blindset.create("항목 많음", [{"text": "가"}, {"text": "나"}], criteria=[f"항목 {i}" for i in range(9)])
    assert blindset.create("항목 따로", [{"text": "가"}, {"text": "나"}], criteria=["늘어짐", " 늘어짐 ", ""]).criteria == ["늘어짐"]


def test_duels_pair_texts_of_one_piece_and_hide_arms(client):
    s = _set()
    pairs = blindset.duel_pairs(s)
    # 장면 1 은 글이 둘(각각 두 번)이라 네 쌍, 장면 2 는 한 쌍. 글자가 같은 01 · 05, 02 · 06 은 묻지 않는다
    assert sorted(tuple(sorted(p)) for p in pairs) == [("01", "02"), ("01", "06"), ("02", "05"), ("03", "04"), ("05", "06")]
    assert pairs == blindset.duel_pairs(blindset.load(s.id))  # 요청마다 같은 차례 · 같은 좌우
    assert blindset.view(s)["duels"] == []  # 다 매기기 전에는 싣지 않는다
    with pytest.raises(ValueError, match="모두 매긴 뒤"):
        blindset.duel(s.id, *pairs[0], pairs[0][0])
    for no, n in zip(["01", "02", "03", "04", "05", "06"], [4, 2, 5, 3, 3, 2]):
        blindset.score(s.id, no, n)
    v = blindset.view(blindset.load(s.id))
    assert [(d["a"], d["b"], d["pick"]) for d in v["duels"]] == [(a, b, "") for a, b in pairs] and v["result"] is None
    assert "arm" not in json.dumps(v, ensure_ascii=False) and "장면 1" not in json.dumps(v, ensure_ascii=False)
    with pytest.raises(KeyError):
        blindset.duel(s.id, "01", "05", "01")  # 같은 글끼리는 쌍이 아니다
    with pytest.raises(ValueError, match="골라 주세요"):
        blindset.duel(s.id, *pairs[0], "03" if "03" not in pairs[0] else "01")
    ga = {"01", "03", "05"}  # 가 판의 글
    for a, b in pairs:
        blindset.duel(s.id, b, a, a if a in ga else b)  # 번호를 뒤집어 보내도 같은 쌍이다
    got = blindset.load(s.id)
    assert [(d.a, d.b) for d in got.duels] == pairs and all(d.pick in ga for d in got.duels)
    tie = next(p for p in pairs if "03" not in p)
    blindset.duel(s.id, *tie, blindset.TIE)
    blindset.duel(s.id, "03", "04", "")  # 지우면 안 고른 쌍으로 돌아간다
    assert sum(1 for d in blindset.view(blindset.load(s.id))["duels"] if not d["pick"]) == 1
    blindset.duel(s.id, "03", "04", "03")
    d = blindset.view(blindset.reveal(s.id))["result"]["duel"]
    # 장면 1 의 네 답은 같은 글 한 쌍이라 한 번으로 친다: (1 + 1 + 1 + 0.5) / 4 = 0.875, 장면 2 는 1
    assert d["total"] == 5 and d["answered"] == 5 and d["repeat"]["of"] == 3 and d["repeat"]["same"] in (1, 2)
    assert d["arms"] == [{"arm": "가", "rate": 0.94, "pairs": 2, "win": 4, "tie": 1, "loss": 0}, {"arm": "나", "rate": 0.06, "pairs": 2, "win": 0, "tie": 1, "loss": 4}]
    with pytest.raises(ValueError, match="고칠 수 없어요"):
        blindset.duel(s.id, "03", "04", "04")


def test_duels_skip_sets_without_pieces_or_key(client):
    two = [{"text": "가"}, {"text": "나"}]
    assert blindset.duel_pairs(blindset.create("열쇠 없음", two)) == []
    s = blindset.create("대목 없음", two, [{"no": "01", "arm": "가"}, {"no": "02", "arm": "나"}])
    assert blindset.duel_pairs(s) == []
    blindset.score(s.id, "01", 3)
    blindset.score(s.id, "02", 4)
    r = blindset.view(blindset.reveal(s.id))["result"]
    assert r["duel"] == {"total": 0, "answered": 0, "arms": [], "repeat": None} and r["flags"]["checked"] == 0 and r["flags"]["diff"] is None


def test_old_set_file_gets_checks_and_duels_and_still_reveals(client):
    s = _set()
    path = blindset.root() / f"{s.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for k in ("criteria", "duels"):
        raw.pop(k)
    for x in raw["items"]:
        x.pop("flags")
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    old = blindset.load(s.id)
    assert old.criteria == [] and blindset.view(old)["criteria"] == list(blindset.CRITERIA)  # 열기 전의 옛 묶음에는 지금 항목을 보인다
    blindset.score(s.id, "01", 4, flags=[blindset.CRITERIA[2]])
    assert blindset.load(s.id).criteria == list(blindset.CRITERIA)  # 처음 체크할 때 적어 둔다
    for no, n in zip(["02", "03", "04", "05", "06"], [2, 5, 3, 3, 2]):
        blindset.score(s.id, no, n)
    assert len(blindset.view(blindset.load(s.id))["duels"]) == 5
    assert blindset.view(blindset.reveal(s.id))["result"]["duel"]["answered"] == 0  # 쌍 비교를 건너뛰어도 열린다
    # 항목을 적은 적 없이 이미 결과를 연 옛 묶음에는 항목을 보이지 않는다
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["criteria"] = []
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert blindset.view(blindset.load(s.id))["criteria"] == []


def test_flags_and_duels_api(client):
    r = client.post("/api/blind", json={"title": "기준", "items": [{"text": t} for t in TEXTS[:4]], "key": KEY[:4], "criteria": ["늘어짐", "말투"]})
    bid, v = r.json()["id"], r.json()
    assert v["criteria"] == ["늘어짐", "말투"] and v["duels"] == []
    assert client.put(f"/api/blind/{bid}/items/01", json={"score": 0, "flags": ["말투"]}).json()["texts"][0]["flags"] == ["말투"]
    assert client.put(f"/api/blind/{bid}/items/01", json={"score": 4, "note": "메모"}).json()["texts"][0]["flags"] == ["말투"]  # flags 를 안 보내면 그대로
    assert client.put(f"/api/blind/{bid}/items/01", json={"score": 4, "flags": ["없음"]}).status_code == 400
    assert client.put(f"/api/blind/{bid}/duels", json={"a": "01", "b": "02", "pick": "01"}).status_code == 400  # 다 매기기 전
    for no in ("02", "03", "04"):
        v = client.put(f"/api/blind/{bid}/items/{no}", json={"score": 3}).json()
    assert sorted(tuple(sorted((d["a"], d["b"]))) for d in v["duels"]) == [("01", "02"), ("03", "04")]
    assert client.put(f"/api/blind/{bid}/duels", json={"a": "01", "b": "03", "pick": "01"}).status_code == 404  # 다른 대목
    assert client.put(f"/api/blind/{bid}/duels", json={"a": "01", "b": "02", "pick": "09"}).status_code == 400
    got = client.put(f"/api/blind/{bid}/duels", json={"a": "02", "b": "01", "pick": "="}).json()
    assert [d["pick"] for d in got["duels"] if {d["a"], d["b"]} == {"01", "02"}] == ["="]
    r = client.post(f"/api/blind/{bid}/reveal").json()["result"]
    assert r["duel"]["answered"] == 1 and r["duel"]["total"] == 2 and r["flags"]["rows"][1]["total"] == 1 and r["rows"][0]["flags"] == ["말투"]
    assert client.put(f"/api/blind/{bid}/duels", json={"a": "01", "b": "02", "pick": "01"}).status_code == 400  # 연 뒤


@needs_node
def test_checks_and_duel_screen_keep_one_primary_button_and_hide_numbers():
    got = run_js(["app.js", "blindset.js"], """(() => {
      fmtDateTime = () => '';
      S.jobs = []; S.route = ['blind'];
      const texts = ['01', '02', '03'].map((no, i) => ({ no, text: '글 ' + no + '.', chars: 5, score: i < 2 ? 3 : 0, note: '', flags: i ? [] : ['말투'] }));
      const base = { id: 'b1', title: '묶음', items: 3, scale: 5, criteria: ['늘어짐', '말투'], has_key: true, revealed_at: '', result: null, pieces: [] };
      S.bl = { ...base, scored: 2, texts, duels: [] };
      S.blNo = '01'; S.blPiece = -1; S.blDuel = -1;
      const reading = viewBlind();
      const done = texts.map((t) => ({ ...t, score: 3 }));
      const duels = [{ a: '02', b: '01', pick: '' }, { a: '01', b: '03', pick: '03' }, { a: '03', b: '02', pick: '' }];
      S.bl = { ...base, scored: 3, texts: done, duels };
      S.blNo = '';
      const ask = viewBlind();
      S.bl = { ...S.bl, duels: duels.map((d) => ({ ...d, pick: '=' })) };
      const picked = viewBlind();
      S.bl = { ...S.bl, duels: [] };
      const none = viewBlind();
      S.bl = { ...base, scored: 3, texts: done, duels };
      S.blDuel = 0;
      const duel = viewBlind();
      S.blDuel = -1;
      const result = { arms: [{ arm: '가판', mean: 3, texts: 1, low: 3, high: 3, close: false }], pairs: [], noise: null,
        rows: [{ no: '01', score: 3, note: '', arm: '가판', piece: '장면', marks: [], flags: ['말투'] }],
        flags: { criteria: ['늘어짐', '말투'], arms: ['가판'], rows: [{ label: '말투', counts: [{ arm: '가판', n: 0.5, texts: 1 }], total: 1 }], checked: 1, diff: 1 },
        duel: { total: 3, answered: 2, arms: [{ arm: '가판', rate: 0.75, pairs: 2, win: 1, tie: 1, loss: 0 }], repeat: { same: 1, of: 2 } } };
      S.bl = { ...base, scored: 3, texts: done, duels, revealed_at: 'x', result };
      const res = viewBlind();
      S.bl = { ...S.bl, result: { ...result, flags: { ...result.flags, checked: 0 }, duel: { ...result.duel, answered: 0 } } };
      const bare = viewBlind();
      const n = (h, re) => (h.match(re) || []).length;
      return { flags: n(reading, /data-bl-flag=/g), on: n(reading, /aria-pressed="true" data-bl-flag="말투"/g), early: n(reading, /btn primary/g) + n(reading, /duel/g),
        ask: [n(ask, /btn primary/g), ask.includes('class="btn primary" href="#/blind/b1/duel">쌍 비교 1 / 3'), ask.includes('2쌍이 남았어요')],
        picked: [n(picked, /btn primary/g), picked.includes('class="btn" href="#/blind/b1/duel">쌍 비교 3 / 3'), picked.includes('class="btn primary" data-action="blReveal"')],
        none: [n(none, /btn primary/g), none.includes('쌍 비교')],
        duel: [n(duel, /btn primary/g), n(duel, /data-action="blPick"/g), duel.includes('aria-pressed="false" data-action="blPick" data-arg="a">왼쪽이 나아요'), duel.includes('글 02.') && duel.includes('글 01.'), /0[123]번/.test(duel), duel.includes('3점')],
        next: [blDuelNext(duels, -1), blDuelNext(duels, 0), blDuelNext(duels, 2), blDuelNext([{ pick: '=' }], 0)], left: blDuelLeft({ duels }),
        res: [res.includes('<h2>쌍 비교</h2>'), res.includes('2 / 3쌍을 골랐어요'), res.includes('2번 가운데 1번은 답이 같았어요'), res.includes('<h2>거슬린 점</h2>'), res.includes('0.5 / 1'), res.includes('엇갈린 체크는 1개')],
        bare: [bare.includes('<h2>쌍 비교</h2>'), bare.includes('<h2>거슬린 점</h2>')] };
    })()""", {})
    assert got["flags"] == 2 and got["on"] == 1 and got["early"] == 0  # 다 매기기 전에는 쌍 비교도 결과 보기도 없다
    assert got["ask"] == [1, True, True] and got["picked"] == [1, True, True] and got["none"] == [1, False]  # 주 버튼은 늘 하나
    assert got["duel"] == [0, 3, True, True, False, False]  # 쌍 비교 화면은 번호와 점수를 보이지 않는다
    assert got["next"] == [0, 2, 0, -1] and got["left"] == 2
    assert all(got["res"]) and got["bare"] == [False, False]  # 하지 않은 것은 결과에 칸을 만들지 않는다


def test_flag_toggles_one_item_and_leaves_the_score(client):
    s = _set()
    crit = list(blindset.CRITERIA)
    blindset.score(s.id, "01", 4, "한마디")
    blindset.flag(s.id, "01", crit[3])
    got = blindset.flag(s.id, "01", crit[0]).items[0]
    assert (got.flags, got.score, got.note) == ([crit[0], crit[3]], 4, "한마디")  # 앞의 체크 · 점수 · 한마디가 그대로다
    assert blindset.flag(s.id, "01", crit[3], on=False).items[0].flags == [crit[0]]
    with pytest.raises(ValueError, match="없는 기준 항목"):
        blindset.flag(s.id, "01", "없는 항목")
    assert client.put(f"/api/blind/{s.id}/items/02/flags", json={"label": crit[1]}).json()["texts"][1]["flags"] == [crit[1]]
    assert client.put(f"/api/blind/{s.id}/items/02/flags", json={"label": "없음"}).status_code == 400
    assert client.put(f"/api/blind/{s.id}/items/99/flags", json={"label": crit[1]}).status_code == 404
    for no in ("02", "03", "04", "05", "06"):
        blindset.score(s.id, no, 3)
    blindset.reveal(s.id)
    assert client.put(f"/api/blind/{s.id}/items/02/flags", json={"label": crit[1], "on": False}).status_code == 400
