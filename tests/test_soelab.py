"""쇠맛 실험실 (canon/soelab.py): 모으기 · 정규화 · 대기열 · 판정 기록 · 보고서 · 내보내기. AI 를 부르지 않는다.
시험 글은 tests/fixtures/soelab/ 의 직접 지은 글에서 문장을 섞어 만든다."""
import json
import multiprocessing
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from canon import metrics, revlab, soelab, store
from canon.mock import MockLLM
from canon.schema import Episode, EpisodePlot, Meta, Project, RevEpisode, RevLab, RevTake

FIX = Path(__file__).parent / "fixtures" / "soelab"
TEXTS = [p.read_text(encoding="utf-8") for p in sorted(FIX.glob("*.txt"))]
SENTS = [s for t in TEXTS for s in metrics.sentences(t) if len(s) > 8]
BOOT = 200  # 시험은 짧게. 실제 보고서는 2,000번


def story(k: int, size: int = 1300) -> str:
    """지은 글의 문장을 시드 k 로 섞은 글 (k 마다 다른 글)."""
    rng = random.Random(k)
    paras, cur, n = [], [], 0
    while n < size:
        s = rng.choice(SENTS)
        cur.append(s)
        n += len(s) + 1
        if len(cur) >= rng.randint(2, 4):
            paras.append(" ".join(cur))
            cur = []
    paras.append(" ".join(cur))
    return "\n\n".join(x for x in paras if x)


def serial(start: int, count: int, offset: int = 0) -> str:
    return "\n\n".join(f"{n}화 제목\n\n{story(offset + n)}" for n in range(start, start + count))


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_USAGE", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    soelab._cache.clear()
    return tmp_path


def _project(name: str, texts: dict[int, str]) -> Project:
    p = Project(meta=Meta(title=name), episodes=[
        Episode(plot=EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=["일"], characters=[], emotional_shift="", ending_hook=""), text=t, status="finalized")
        for n, t in texts.items()])
    store.save(name, p)
    return p


# ---------- 2. 같은 글은 한 번 · 원천 상한 · 정규화 ----------

def test_normalize_same_across_sources(home):
    base = TEXTS[1]
    curly = re.sub(r'"([^"\n]*)"', r"“\1”", base)
    head, rest = curly.split("\n", 1)
    v1 = ("# 3화 정비소\n\n**" + head + "**\n" + rest).replace("\n", "\r\n")  # 제목 줄 · 굵게 · 둥근 따옴표 · CRLF
    v2 = re.sub(r"\n\n+", "\n", re.sub(r'"([^"\n]*)"', r"「\1」", base))           # 빈 줄 없이 · 낫표
    v3 = base.replace("\n\n", "\n\n【 상태창 】\n[시스템: 알림이 왔습니다]\n\n", 1)  # 상태창 · 시스템 글
    v4 = "<p>" + base.replace("\n\n", "</p>\n\n<p>") + "</p>"
    want = soelab.normalize(base)
    for v in (v1, v2, v3, v4):
        assert soelab.normalize(v) == want
    assert "\n\n" in want and "\n\n\n" not in want
    assert soelab.normalize("그는 말했다... 그리고 ―― 웃었다…….") == "그는 말했다… 그리고 — 웃었다…."

    # 원천이 달라도 같은 조각 id 가 나와 한 번만 들어간다
    a = soelab.collect_paste(v1, "붙여 넣은 글")
    corpus = home / "corpus" / "작가"
    corpus.mkdir(parents=True)
    (corpus / "작품.txt").write_text(v2, encoding="utf-8")
    b = soelab.collect_research(str(home / "corpus"))
    _project("작품", {3: v3})
    c = soelab.collect_episodes("작품")
    assert [x.id for x in a] == [x.id for x in b] == [x.id for x in c] and a
    assert soelab.add(a)["added"] == 1
    assert soelab.add(b + c) == {"added": 0, "dup": 2, "capped": 0, "by_origin": {}}


def test_chunks_near_2000_and_reject(home):
    long = soelab.normalize("\n\n".join(story(k) for k in range(5)))
    parts = soelab.chunks(long)
    assert len(parts) >= 2 and all(soelab.MIN_CHUNK <= len(x) <= 2400 for x in parts)
    assert all(abs(len(x) - 2000) < 400 for x in parts[:-1])
    assert soelab.collect_paste(story(1, 600), "짧은 글") == []          # 1,000자 아래
    assert soelab.collect_paste("This is English. " * 120, "영어") == []  # 한글이 적은 글


def test_dedupe_and_cap(home):
    pieces = soelab.collect_paste(serial(1, 30), "긴 연재", origin="ai", model="gemini:gemini-4-argon")
    assert len(pieces) == 30 and len({p.group for p in pieces}) == 30
    assert all(p.model_source == "author" and p.model == "gemini:gemini-4-argon" for p in pieces)
    r = soelab.add(pieces, cap=20)
    assert (r["added"], r["capped"]) == (20, 10)
    assert soelab.add(pieces, cap=20) == {"added": 0, "dup": 20, "capped": 10, "by_origin": {}}
    # 상한은 원천 하나 · 출처 한쪽마다: 다른 원천은 따로 센다
    assert soelab.add(soelab.collect_paste(serial(1, 5, 100), "다른 글"), cap=20)["added"] == 5
    assert len(soelab.load_pieces()) == 25


# ---------- 3. 프로세스 둘이 동시에 판정을 덧붙임 ----------

def _append_many(root: str, tag: str, n: int) -> None:
    store.ROOT = Path(root)
    from canon.schema import SoeLabel, SoeSpan
    for i in range(n):  # 긴 줄이라 쓰기가 끊기면 깨진 줄이 남는다
        soelab.append_label(SoeLabel(id=f"{tag}{i}", piece="p" * 12, verdict="ai", spans=[SoeSpan(start=i, end=i + 1, quote="글" * 300)]))


def test_concurrent_append(home):
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_append_many, args=(str(home), t, 200)) for t in ("a", "b")]
    for pr in procs:
        pr.start()
    for pr in procs:
        pr.join(60)
        assert pr.exitcode == 0
    lines = (home / ".soelab" / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 400
    assert all(json.loads(x)["spans"][0]["quote"] == "글" * 300 for x in lines)
    assert len(soelab.load_labels()) == 400


# ---------- 4. AI 호출 0 ----------

def test_no_llm_calls(home, monkeypatch):
    calls = []
    monkeypatch.setattr(MockLLM, "json", lambda self, *a, **k: calls.append("json"))
    monkeypatch.setattr(MockLLM, "text", lambda self, *a, **k: calls.append("text"))
    from canon import llm
    real = llm.get_llm
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: calls.append("get_llm") or real(*a, **k))
    _project("작품", {n: story(200 + n) for n in range(1, 13)})
    soelab.add(soelab.collect_episodes("작품"))
    soelab.add(soelab.collect_paste(serial(1, 12, 300), "사람 글", origin="human"))
    soelab.add(soelab.collect_edits("작품"))
    now = datetime(2026, 11, 1, 9).astimezone()
    for pid in soelab.load_queue()["order"][:5]:
        soelab.judge(pid, "ai", spans=[{"start": 0, "end": 5, "kind": "other"}], now=now)
    soelab.report(n_boot=BOOT)
    soelab.export()
    soelab.view()
    assert calls == []


# ---------- 5. 내보내기에 원문 · 표시한 글 · 메모가 없음 ----------

def test_export_has_no_text(home):
    soelab.add(soelab.collect_paste(serial(1, 6, 500), "사람 글", origin="human"))
    soelab.add(soelab.collect_paste(serial(1, 6, 600), "AI 글", origin="ai", model="claude:x"))
    pieces = {p.id: p for p in soelab.load_pieces()}
    order = soelab.load_queue()["order"]
    for pid in order:
        soelab.judge(pid, "human", spans=[{"start": 3, "end": 30, "quote": pieces[pid].text[3:30], "kind": "번역투", "note": "메모 비밀 글귀"}])
    out = soelab.export(include_hidden=True)
    blob = json.dumps(out, ensure_ascii=False)
    assert "메모 비밀 글귀" not in blob and '"quote"' not in blob and '"text"' not in blob and '"note"' not in blob
    for p in pieces.values():
        for s in metrics.sentences(p.text)[:3]:
            if len(s) > 15:
                assert s not in blob
    assert len(out["pieces"]) == len(pieces) and out["labels"][0]["spans"] == [{"start": 3, "end": 30, "kind": "번역투"}]


# ---------- 6. 다시 읽기는 모을 때 정하고 7일 전에는 막힘 ----------

def test_redo_set_at_collect_and_blocked_before_7_days(home):
    soelab.add(soelab.collect_paste(serial(1, 15, 700), "사람 글", origin="human"))
    q1 = soelab.load_queue()
    assert len(q1["order"]) == 15 and len(q1["redo"]) == 5 and q1["carry"] == []  # 셋에 하나
    assert all(r in q1["order"] for r in q1["redo"])
    early = datetime(2026, 10, 30, 21).astimezone()
    for pid in q1["order"][:4]:
        soelab.judge(pid, "human", now=early)
    # 더 모아도 판정한 자리와 다시 읽기는 그대로. 남은 자리는 사람 · AI 를 섞어 다시 짠다
    soelab.add(soelab.collect_paste(serial(1, 10, 800), "AI 글", origin="ai"))
    q2 = soelab.load_queue()
    assert q2["order"][:4] == q1["order"][:4] and q2["redo"][:5] == q1["redo"]
    assert len(q2["redo"]) == 8 and len(q2["carry"]) == 1  # 새 10개 → 셋 묶음 셋, 하나는 다음에
    pieces = {p.id: p for p in soelab.load_pieces()}
    assert "ai" in [pieces[x].origin for x in q2["order"][4:10]]
    # 같은 조각 · 같은 시드면 같은 다시 읽기
    again = soelab.extend_queue({"seed": soelab.SEED, "order": q1["order"], "redo": q1["redo"], "spare": q1["spare"],
                                 "spare_carry": q1["spare_carry"]}, soelab.load_pieces(),
                                judged=set(q1["order"][:4]))
    assert again["redo"] == q2["redo"] and again["order"] == q2["order"]

    day0 = datetime(2026, 11, 1, 21).astimezone()
    target = next(x for x in q2["redo"] if x not in q1["order"][:4])
    not_redo = next(x for x in q2["order"] if x not in q2["redo"])
    with pytest.raises(ValueError, match="첫 판정"):
        soelab.redo(target, "ai", now=day0)
    for pid in q2["order"][4:]:
        soelab.judge(pid, "ai", now=day0)
    with pytest.raises(ValueError, match="이미 판정"):
        soelab.judge(target, "ai", now=day0)
    with pytest.raises(ValueError, match="11월 8일부터 다시 읽을 수 있어요"):
        soelab.redo(target, "human", now=day0 + timedelta(days=6, hours=2))
    early_redo = set(q2["redo"]) & set(q1["order"][:4])  # 10월 30일에 판정한 것은 11월 6일부터
    assert set(soelab.redo_due((day0 + timedelta(days=6)).date())) == early_redo
    with pytest.raises(ValueError, match="다시 읽기 예정이 아닌"):
        soelab.redo(not_redo, "human", now=day0 + timedelta(days=8))
    due = set(soelab.redo_due((day0 + timedelta(days=7)).date()))
    assert due == set(q2["redo"]) and set(soelab.redo_due((early + timedelta(days=7)).date())) == early_redo
    lb = soelab.redo(target, "human", now=day0 + timedelta(days=7))
    assert lb.redo_of and target not in soelab.redo_due((day0 + timedelta(days=7)).date())
    # '이번 10개'는 판정 차례로
    batches = [x.batch for x in soelab.load_labels() if not x.redo_of]
    assert batches[:10] == ["b1"] * 10 and batches[10:20] == ["b2"] * 10


def test_first_block_one_piece_per_group(home):
    # 사람 글 25화(화마다 조각 하나) + AI 글 10화(화마다 조각 둘)
    soelab.add(soelab.collect_paste(serial(1, 25, 900), "사람 글", origin="human"), cap=100)
    two = "\n\n".join(f"{n}화\n\n{story(1000 + n, 3600)}" for n in range(1, 11))
    soelab.add(soelab.collect_paste(two, "AI 글", origin="ai", model="gemini:g"), cap=100)
    pieces = {p.id: p for p in soelab.load_pieces()}
    q = soelab.load_queue()
    first = [pieces[x] for x in q["order"][:soelab.FIRST]]
    assert len(q["order"]) == 45 and len({p.group for p in first[:35]}) == 35
    assert q["doubled"]  # 묶음이 35개라 1차 40개를 채우려면 같은 화에서 2조각
    assert [p.origin for p in first[:20]].count("ai") == 10  # 사람 · AI 를 번갈아
    assert len(soelab.hidden_ids()) == 45


def test_known_and_edits_not_queued(home):
    soelab.add(soelab.collect_paste(serial(1, 4, 1100), "읽은 글", origin="human", known=True))
    p = _project("작품", {1: story(1200)})
    p.episodes[0].edits = [__import__("canon.schema", fromlist=["TextEdit"]).TextEdit(
        id="e1", preset="less_ai", before=story(1201, 300), after=story(1202, 300))]
    store.save("작품", p)
    edits = soelab.collect_edits("작품")
    assert [x.origin for x in edits] == ["edited", "edited"] and edits[1].pair_of == edits[0].id
    soelab.add(edits)
    assert soelab.load_queue()["order"] == [] and len(soelab.load_pieces()) == 6


# ---------- 모델 축 (4.8) ----------

def test_models_from_usage_and_record(home):
    rows = [
        {"project": "작품", "episode": 1, "stage": "write", "ok": True, "backend": "gemini", "model": "gemini-4-argon"},
        {"project": "작품", "episode": 1, "stage": "write", "ok": True, "backend": "claude", "model": "claude-opus-5-5"},
        {"project": "작품", "episode": 1, "stage": "write", "ok": False, "backend": "gemini", "model": "gemini-x"},
        {"project": "작품", "episode": 2, "stage": "check", "ok": True, "backend": "gemini", "model": "gemini-4-argon"},
    ]
    (home / "usage.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    _project("작품", {1: story(1300), 2: story(1301)})
    got = {p.source.episode: (p.model, p.model_source) for p in soelab.collect_episodes("작품")}
    assert got == {1: ("claude:claude-opus-5-5", "usage"), 2: ("", "unknown")}

    lab = RevLab(id=1, episodes=[RevEpisode(number=1, text=story(1302), take=RevTake(text=story(1303), model="gemini-4-argon"),
                                            take_style=RevTake(text=story(1304), model=""))])
    revlab.save(lab)
    ps = soelab.collect_revlab(1)
    orig = [p for p in ps if p.origin == "human"]
    assert len(orig) == 1 and all(p.group == "revlab1:1" for p in ps)
    take = next(p for p in ps if p.source.take == "take")
    assert (take.model, take.model_source, take.pair_of) == ("gemini:gemini-4-argon", "record", orig[0].id)
    assert next(p for p in ps if p.source.take == "take_style").model_source == "unknown"


def _corpus(home, judged: int = 0):
    """사람 글 12화 · AI 글 (모델 둘) 12화씩. AI 글에는 쇠맛 패턴 문장을 섞는다."""
    soelab.add(soelab.collect_paste(serial(1, 12, 2000), "사람 글", origin="human"), cap=100)
    ai_sent = "그것은 단순한 바람이 아니었다. 어둡고, 차갑고, 조용했다. 불안감이 밀려왔다 — 그는 숨을 삼켰다."
    for model, off in (("gemini:g", 3000), ("claude:c", 4000)):
        txt = "\n\n".join(f"{n}화\n\n{ai_sent}\n\n{story(off + n)}\n\n{ai_sent}" for n in range(1, 13))
        soelab.add(soelab.collect_paste(txt, f"AI {model}", origin="ai", model=model), cap=100)
    now = datetime(2026, 11, 1, 9).astimezone()
    pieces = {p.id: p for p in soelab.load_pieces()}
    for pid in soelab.load_queue()["order"][:judged]:
        soelab.judge(pid, pieces[pid].origin, now=now)


def test_report_source_models_and_hidden(home):
    _corpus(home)
    rep = soelab.report(n_boot=BOOT, save=True)
    assert rep["metrics_version"] == metrics.METRICS_VERSION and rep["boot"] == BOOT
    assert (home / ".soelab" / "reports" / f"{rep['id']}.json").exists()
    row = next(r for r in rep["metrics"] if r["id"] == "ai_patterns")
    src = row["source"]
    assert src["value"] == 1.0 and src["chip"] in ("yes", "weak") and src["ai_groups"] == 24 and src["human_groups"] == 12
    assert src["ci95"][0] <= src["value"] and src["level"] == pytest.approx(1 - 0.05 / 14)
    assert {m["model"] for m in row["by_model"]} == {"gemini:g", "claude:c"}
    assert all(m["chip"] in ("yes", "weak") for m in row["by_model"])
    assert rep["notes"] == []  # 묶음 36개 · 모델 둘 · 사람 글은 웹소설
    style = next(r for r in rep["metrics"] if r["id"] == "style_distance")
    assert style["source"]["chip"] == "na"
    # 모두 가린 조각(판정 전)이라 조각별 줄이 없다. 모은 숫자는 있다
    assert rep["pieces"] == [] and rep["counts"]["hidden"] == 36
    assert rep["metrics"][0]["author"] is None and rep["consistency"]["hold"]
    assert "가르는 힘" in soelab.describe(rep)


def test_report_author_and_patterns(home):
    _corpus(home, judged=36)
    pieces = {p.id: p for p in soelab.load_pieces()}
    rep = soelab.report(n_boot=BOOT, save=False)
    row = next(r for r in rep["metrics"] if r["id"] == "ai_patterns")
    assert row["author"]["value"] == 1.0 and row["author"]["ai_pieces"] == 24
    hidden = soelab.hidden_ids()
    q = soelab.load_queue()
    assert len(q["redo"]) == 12 and len(q["spare"]) == 6  # 셋에 하나는 다시 읽기, 여섯에 하나는 예비
    assert hidden == set(q["redo"]) | set(q["spare"])  # 다시 읽기 예정은 재판정 전까지, 예비는 보여 줄 때까지 가린다
    assert {r["id"] for r in rep["pieces"]} == set(pieces) - hidden
    assert not hidden & {p["id"] for p in soelab.export()["pieces"]}
    assert next(r for r in rep["patterns"] if r["pattern"] == "other") == {"pattern": "other", "marked": 0}


def test_model_split_rule():
    assert soelab._model_split([{"chip": "yes"}, {"chip": "none"}])
    assert soelab._model_split([{"chip": "yes"}, {"chip": "reverse"}])
    assert not soelab._model_split([{"chip": "yes"}, {"chip": "weak"}])
    assert not soelab._model_split([{"chip": "yes"}, {"chip": "few"}])


def test_pattern_table_precision_recall(home):
    from canon.schema import SoeLabel, SoeSpan, SoePiece, SoeSource
    text = "그것은 단순한 꿈이 아니었다. 그는 문을 열었다. 바람이 불었다."
    p = SoePiece(id="x" * 12, text=text, origin="ai", source=SoeSource(kind="paste"), group="g")
    first = metrics.sentence_spans(text)
    lb = SoeLabel(id="l1", piece=p.id, verdict="ai", spans=[SoeSpan(start=first[0][0], end=first[0][1], kind="부정 후 재정의"),
                                                            SoeSpan(start=first[1][0], end=first[1][1], kind="other")])
    t = {r["pattern"]: r for r in soelab.pattern_table({p.id: p}, [lb])}
    assert (t["부정 후 재정의"]["hits"], t["부정 후 재정의"]["marked_too"], t["부정 후 재정의"]["found"]) == (1, 1, 1)
    assert t["부정 후 재정의"]["few"] and t["other"]["marked"] == 1


def test_cli(home, capsys):
    from canon.cli import main
    f = home / "글.txt"
    f.write_text(serial(1, 3, 5000), encoding="utf-8")
    main(["soelab", "collect", "paste", str(f), "--origin", "ai", "--model", "claude:c"])
    out = capsys.readouterr().out
    assert "조각 3개를 더했어요" in out and "모델이 하나뿐" in out
    main(["soelab", "report", "--boot", "50", "--no-save"])
    assert "지표 버전" in capsys.readouterr().out
    main(["soelab", "export", "--out", str(home / "out.json")])
    assert json.loads((home / "out.json").read_text(encoding="utf-8"))["left_out"] == 3
