"""가려 읽기 묶음 (canon/blindset.py): 넣기 · 점수 · 결과 열기 · 흔들림 · 열쇠 가리기 · API · 명령줄 · 화면."""
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
    assert r["rows"][2] == {"no": "03", "score": 5, "note": "한마디", "arm": "가", "piece": "장면 2"}
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
