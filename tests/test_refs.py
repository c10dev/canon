"""레퍼런스 원고 (canon/refs.py): 화 표시 인식 · 오인식 거르기 · 저장 · 다시 나누기 · 문체 · 역설계 보내기 · API.
원고는 tests/fixtures/refs_story.txt (직접 지은 글: 목차, 공통 머리, 번호 빠짐, 반복 머리, 본문 속 번호 줄, 작가의 말, 외전 · 에필로그 · 후기)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from canon import refs, revlab, store, web
from canon.schema import RefCut


STORY = (Path(__file__).parent / "fixtures" / "refs_story.txt").read_text(encoding="utf-8")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("CANON_REFS", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    yield tmp_path


def _on(d):
    return [c for c in d["cuts"] if c["on"]]


def test_fixture_preview():
    d = refs.preview(STORY)
    assert d["rule"] == "heading" and d["unit"] == "화" and d["common_head"] == "등대 이야기"
    on = _on(d)
    assert [c["label"] for c in on] == ["프롤로그", "1", "2", "3", "4", "6", "7", "8", "9", "10", "11", "외전 1", "외전 2", "에필로그", "완결 후기"]
    assert [c["kind"] for c in on][-4:] == ["side", "side", "epilogue", "skip"]
    assert on[1]["title"] == "꺼진 불" and on[3]["title"] == "배 번호" and on[6]["title"] == "백스물두 칸"
    # 목차 줄은 끄고 머리 글로 남긴다
    toc = [c for c in d["cuts"] if "toc" in c["flags"]]
    assert len(toc) == 11 and not any(c["on"] for c in toc) and d["preface_end"] == on[0]["line"]
    # 3화 본문 속 '9화' 줄은 번호 줄기 밖이라 끈다
    mention = [c for c in d["cuts"] if "mention" in c["flags"] and c["line"] > d["preface_end"]]
    assert [c["label"] for c in mention] == ["9"] and not mention[0]["on"]
    # 6화: 반복 머리는 한 머리로 묶고(본문은 둘째 줄 다음부터), 5화가 없다
    six = on[5]
    assert six["title"] == "다시 켜진 불" and six["body"] == six["line"] + 3 and "gap" in six["flags"] and six["gap"] == [5, 5]
    # 2화 끝 작가의 말을 뗀다
    assert on[2]["tail_cut"] > 0
    assert d["counts"]["main"] == 10 and d["counts"]["side"] == 2 and d["counts"]["skip"] == 1


@pytest.mark.parametrize("line,label,title", [
    ("1화", "1", ""), ("제1화", "1", ""), ("001화", "1", ""), ("1화. 시작", "1", "시작"), ("[1화] 시작", "1", "시작"),
    ("【 3화 】", "3", ""), ("제 12 화 : 비", "12", "비"), ("12-1화", "12-1", ""), ("12화 (2)", "12-2", ""), ("12화 상", "12-상", ""),
    ("# 12화 비", "12", "비"), ("<7화> 바다", "7", "바다"),
])
def test_head_forms(line, label, title):
    d = refs.detect(f"{line}\n본문")
    on = _on(d)
    assert d["rule"] == "heading" and on[0]["label"] == label and on[0]["title"] == title, d


@pytest.mark.parametrize("line,unit", [("EP.3 비", "EP"), ("Episode 3", "EP"), ("Chapter 3: Rain", "Chapter"), ("3회", "회"), ("3편", "편"), ("第3話", "話")])
def test_other_units(line, unit):
    d = refs.detect(f"{line}\n본문")
    assert d["unit"] == unit and _on(d)[0]["label"] == "3"


def test_body_lines_are_not_heads():
    for t in ["3화가 끝나고 서윤은 잠들었다.\n그다음 날", "영화 3편 봤다\n본문", "그는 3화 전에 말했다고 했다\n본문", "Deep 3\n본문"]:
        assert refs.detect(t)["rule"] != "heading", t


def test_unit_choice_and_switch():
    text = "\n".join(f"제{c}장\n" + "\n".join(f"{(c - 1) * 3 + k}화\n본문 {k}" for k in range(1, 4)) for c in range(1, 4))
    d = refs.detect(text)
    assert d["unit"] == "화" and d["alts"] == [{"unit": "장", "count": 3}] and len(_on(d)) == 9
    d = refs.detect(text, unit="장")
    assert d["unit"] == "장" and [c["label"] for c in _on(d)] == ["1", "2", "3"]


def test_custom_example():
    text = "<<12>> 비\n본문\n<<13>>\n본문 둘"
    d = refs.detect(text, rule="custom", example="<<12>> 제목")
    assert d["rule"] == "custom" and [c["num"] for c in _on(d)] == [12, 13]
    with pytest.raises(ValueError, match="숫자"):
        refs.detect(text, rule="custom", example="제목만")


def test_short_episodes_are_not_toc():
    d = refs.detect("\n".join(f"{i}화\n본문" for i in range(1, 33)))
    assert len(_on(d)) == 32


def test_restart_in_second_file():
    a = "\n".join(f"{i}화\n본문 {i}" for i in range(1, 5))
    b = "\n".join(f"{i}화\n본문 {i}" for i in range(1, 4))
    text = a + "\n" + b
    d = refs.detect(text, files=[0, len(a.split("\n"))])
    on = _on(d)
    assert len(on) == 7 and "restart" in on[4]["flags"]


def test_restart_in_one_file_keeps_later_episodes():
    """한 파일 안에서 번호가 1부터 다시 시작하면(2부 1화) 뒤 화를 끄지 않는다. 예전에는 뒤 화가 모두 꺼져 앞 마지막 화가 아주 커졌다."""
    body = "본문 문장이다. " * 50
    heads = [f"{n}화" for n in range(1, 301)] + ["9화"] + [f"{n}화" for n in range(1, 81)]
    d = refs.preview("\n".join(f"{h}\n{body}" for h in heads))
    on = _on(d)
    assert len(on) == 380 and max(c["chars"] for c in on) < len(body) * 3  # 300화만 꺼진 '9화' 줄 글을 품어 두 배
    assert [c["label"] for c in d["cuts"] if not c["on"]] == ["9"]  # 300화 본문 속 '9화' 한 줄은 끈다
    assert [c["line"] for c in on if "restart" in c["flags"]] == [on[300]["line"]]
    # 3화 본문 속 '9화' 뒤의 4화는 새 줄기가 아니다
    d = refs.detect("\n".join(f"{h}\n본문" for h in ["1화", "2화", "3화", "9화", "4화", "5화", "6화"]))
    assert [c["label"] for c in _on(d)] == ["1", "2", "3", "4", "5", "6"] and not any("restart" in c["flags"] for c in d["cuts"])


@pytest.mark.parametrize("kw", [{}, {"rule": "custom", "example": "< EP.0 : 프롤로그 >"}])
def test_wrapped_heads_drop_closing_bracket(kw):
    """'< EP.1 : 시작 >' 처럼 화 표시 전체를 감싼 괄호의 닫는 쪽은 제목에 넣지 않는다. 'EP.0 : 프롤로그' 는 프롤로그다."""
    text = "\n".join(f"{h}\n본문" for h in ["< EP.0 : 프롤로그 >", "< EP.1 : 시작 >", "< EP.2 : 비 오는 날 (상) >", "< EP.3 >"])
    on = _on(refs.detect(text, **kw))
    assert [(c["label"], c["title"], c["kind"]) for c in on] == [
        ("프롤로그", "프롤로그", "prologue"), ("1", "시작", "main"), ("2", "비 오는 날 (상)", "main"), ("3", "", "main")]
    assert refs._title("제목 [완]") == "제목 [완]"


def test_five_digit_numbers():
    d = refs.detect("\n".join(f"{n}화\n본문" for n in range(9998, 10002)))
    assert [c["label"] for c in _on(d)] == ["9998", "9999", "10000", "10001"]


def test_rule_fallbacks():
    assert refs.detect("하나\n***\n둘")["rule"] == "mark"
    assert refs.detect("하나\n\n\n\n둘")["rule"] == "blank"
    assert refs.detect("한 덩어리")["rule"] == "one"


def test_store_roundtrip(home):
    d = refs.preview(STORY)
    cuts = [RefCut(**{k: c[k] for k in ("line", "body", "head", "label", "title", "kind")}) for c in _on(d)]
    with pytest.raises(ValueError, match="권리"):
        refs.create("등대", STORY, cuts)
    b = refs.create("등대", STORY, cuts, rights=True, unit="화", common_head="등대 이야기")
    assert (home / ".refs" / b.id / "source.txt").exists() and len(b.eps) == 15
    eps = refs.episodes(refs.load(b.id))
    assert eps[1]["label"] == "1화" and eps[0]["label"] == "프롤로그" and eps[11]["label"] == "외전 1"
    assert eps[1]["chars"] > 300 and 0 < eps[1]["dialogue"] < 1
    two = refs.episode_text(b.id, 3)
    assert "작가의 말" not in two and two.startswith("마을 회관")
    # 합치기: 2화 경계를 빼면 1화에 2화가 붙는다. 원문은 그대로
    b = refs.update(b.id, cuts=[c for c in b.cuts if c.label != "2"])
    assert len(b.eps) == 14 and "마을 회관" in refs.episode_text(b.id, 2)
    b = refs.update(b.id, strip_tails=False)
    assert "작가의 말" in refs.episode_text(b.id, 2)
    assert refs.source(b.id) == refs.lines_of(STORY)
    with pytest.raises(ValueError, match="줄 번호"):
        refs.update(b.id, cuts=[RefCut(line=99999, body=99999)])
    assert refs.summary(refs.entries()[0])["episodes"] == 14
    refs.delete(b.id)
    assert refs.entries() == []


def test_sample_and_revlab(home):
    d = refs.preview(STORY)
    cuts = [RefCut(**{k: c[k] for k in ("line", "body", "head", "label", "title", "kind")}) for c in _on(d)]
    b = refs.create("등대", STORY, cuts, rights=True)
    s = refs.sample(b.id, [2, 3, 4])
    assert s["source"] == "등대 1화~3화" and s["text"].startswith("새벽 네 시") and not s["cut"]
    with pytest.raises(ValueError, match="고른 화"):
        refs.sample(b.id, [15])  # 제외 화만 고르면 없다
    lab_id = refs.to_revlab(b.id, [5, 6, 7])
    lab = revlab.load(lab_id)
    assert [e.number for e in lab.episodes] == [4, 5, 6] and lab.episodes[1].head == "등대 이야기 6화. 다시 켜진 불"
    assert lab.title == "등대 4화~7화" and refs.load(b.id).made[0].kind == "revlab"
    with pytest.raises(ValueError, match="고른 화"):
        refs.to_revlab(b.id, [])


def test_revlab_split_uses_refs():
    s = revlab.split(STORY)
    assert s["how"] == "heading" and s["episodes"][0]["head"] == "등대 이야기 프롤로그"


def test_api(home):
    c = TestClient(web.app)
    assert c.get("/api/refs").json()["refs"] == []
    d = c.post("/api/refs/split", json={"text": STORY}).json()
    assert d["unit"] == "화" and "text" not in d
    cuts = [{k: x[k] for k in ("line", "body", "head", "label", "title", "kind")} for x in d["cuts"] if x["on"]]
    r = c.post("/api/refs", json={"name": "등대", "text": STORY, "cuts": cuts, "rights": False})
    assert r.status_code == 400 and "권리" in r.json()["detail"]
    b = c.post("/api/refs", json={"name": "등대", "text": STORY, "cuts": cuts, "rights": True}).json()
    rid = b["id"]
    assert len(b["episodes"]) == 15 and b["labels"]["kinds"][0]["label"] == "본편"
    assert c.get(f"/api/refs/{rid}/eps/2").json()["text"].startswith("새벽 네 시")
    assert c.get(f"/api/refs/{rid}/text?start=0&end=2").json()["lines"][0] == "등대지기의 밤"
    assert c.get(f"/api/refs/{rid}/source").json()["text"] == "\n".join(refs.lines_of(STORY))
    s = c.post(f"/api/refs/{rid}/sample", json={"eps": [2]}).json()
    st = c.post("/api/styles", json={"name": "등대체", "sample": s["text"], "source": s["source"], "ref": rid, "ref_eps": "1화"}).json()
    assert c.get(f"/api/refs/{rid}").json()["made"][0] == {"kind": "style", "id": st["id"], "at": c.get(f"/api/refs/{rid}").json()["made"][0]["at"], "eps": "1화"}
    lab = c.post(f"/api/refs/{rid}/revlab", json={"eps": [2, 3]}).json()["id"]
    assert c.get(f"/api/revlab/{lab}").status_code == 200
    put = c.put(f"/api/refs/{rid}", json={"name": "등대 2"}).json()
    assert put["name"] == "등대 2" and len(put["episodes"]) == 15
    assert c.get("/api/refs/zzz").status_code == 404
    assert c.delete(f"/api/refs/{rid}").json() == {"ok": True}
    assert c.get(f"/api/refs/{rid}").status_code == 404


# ---------- 화면 (static/refs.js) ----------

import re  # noqa: E402

from .jsvm import STATIC, needs_node, run_js  # noqa: E402

FILES = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


@needs_node
def test_js_decode():
    sample = "제1화 등대\n서윤은 계단을 올랐다.\r\n"
    cases = {"utf8": list(sample.encode("utf-8")), "bom": list(b"\xef\xbb\xbf" + sample.encode("utf-8")),
             "cp949": list(sample.encode("cp949")), "utf16": list(b"\xff\xfe" + sample.encode("utf-16-le"))}
    got = run_js(FILES, "Object.fromEntries(Object.entries(data).map(([k, b]) => [k, refDecode(new Uint8Array(b))]))", cases)
    want = sample.replace("\r\n", "\n")
    assert {k: (v["text"], v["encoding"]) for k, v in got.items()} == {
        "utf8": (want, "utf-8"), "bom": (want, "utf-8"), "cp949": (want, "euc-kr"), "utf16": (want, "utf-16le")}
    wrong = run_js(FILES, "refDecode(new Uint8Array(data), 'utf-8')", cases["cp949"])
    assert wrong["bad"] > 1  # CP949 를 UTF-8 로 풀면 깨진 글자가 많다


@needs_node
def test_js_assemble_matches_python():
    d = refs.preview(STORY)
    lines = refs.lines_of(STORY)
    for strip in (True, False):
        got = run_js(FILES, "refAssemble(data.lines, data.cuts, data.strip)", {"lines": lines, "cuts": d["cuts"], "strip": strip})
        want = [{"cut": e["cut"], "chars": len(e["text"]), "tail": e["tail_cut"]} for e in refs.assemble(lines, d["cuts"], strip)]
        assert got == want


@needs_node
def test_js_range_and_rows():
    eps = [{"order": 1, "label": "프롤로그", "kind": "prologue"}] + [{"order": i + 1, "label": f"{i}화", "kind": "main"} for i in range(1, 12)] + \
          [{"order": 13, "label": "외전 1", "kind": "side"}]
    got = run_js(FILES, "data.qs.map((q) => refRange(q, data.eps))", {"eps": eps, "qs": ["1~3", "3, 5~6", "2 ~ 4화", "외전 1", "없음"]})
    assert got == [[2, 3, 4], [4, 6, 7], [3, 4, 5], [13], []]
    d = refs.preview(STORY)
    rows = run_js(FILES, "refEpRows({ ...data.d, strip: true, filter: 'warn' }, data.lines)", {"d": d, "lines": refs.lines_of(STORY)})
    assert rows["counts"]["on"] == 15 and [r["label"] for r in rows["rows"]] == ["프롤로그", "6"]  # 짧은 프롤로그, 5화 빠짐
    assert rows["kinds"] == {"prologue": 1, "main": 10, "side": 2, "epilogue": 1, "skip": 1}


@needs_node
def test_js_views(home):
    d = refs.preview(STORY)
    cuts = [RefCut(**{k: c[k] for k in ("line", "body", "head", "label", "title", "kind")}) for c in _on(d)]
    b = refs.create("등대", STORY, cuts, rights=True)
    view = web.get_ref(b.id)
    got = run_js(FILES, """(() => {
      S.route = ['refs']; S.refLabels = data.labels; S.refList = [data.summary]; S.ref = null;
      const list = viewRefs();
      S.refList = []; const empty = viewRefs();
      S.route = ['refs', 'new']; S.refDraft = refBlank(); const file = viewRefs();
      S.refDraft.text = data.text; S.refDraft.preview = data.preview; S.refDraft.cuts = data.preview.cuts; S.refDraft.sel = 5;
      const draft = viewRefs();
      S.route = ['refs', data.view.id]; S.ref = data.view; S.refPane = ''; S.refPick = new Set([2, 3]); S.projects = [];
      const book = viewRefs();
      S.refPane = 2; S.refEp = { order: 2, text: '첫 문단\\n\\n둘째 문단' };
      const read = viewRefs();
      return { list, empty, file, draft, book, read };
    })()""", {"labels": refs.labels(), "summary": refs.summary(b), "text": STORY, "preview": d, "view": view})
    assert "등대" in got["list"] and "본편 10화" in got["list"] and "+ 원고 넣기" in got["list"]
    assert "아직 넣은 원고가 없어요" in got["empty"]
    assert "파일 고르기" in got["file"] and "권리" in got["file"] and 'data-action="refDetect" disabled' in got["file"]
    assert "저장하기 (15화)" in got["draft"] and "번호 빠짐" in got["draft"] and "여기부터 번호 다시 매기기" in got["draft"]
    assert "'등대 이야기'" in got["draft"] and "목차" in got["draft"]
    assert "2화 골랐어요" in got["book"] and "문체 만들기" in got["book"] and "화 표" in got["book"] and "ref-bar" in got["book"]
    assert 'data-action="refToRevlab">' in got["book"] and "화 수와 상관없이 모두 합쳐 3,000,000자까지" in got["book"]  # 화 수로 막지 않는다
    assert "첫 문단" in got["read"] and "이 화 경계 고치기" in got["read"]
