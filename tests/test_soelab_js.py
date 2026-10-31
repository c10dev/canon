"""쇠맛 실험실 화면(static/soelab.js)의 순수 함수를 node 로 서버 규칙과 맞춰 본다 (명세 8장 시험 9~11).
- soeVerdict ↔ labstats.verdict: 경계값(하한 0.5, 값 0.7)과 그 앞뒤
- soeNext 차례, soeRedoDue ↔ soelab.redo_open 날짜
- soeSentences ↔ metrics.sentence_spans, soeSentenceAt ↔ 문장 경계 (좁은 화면 문장 누르기)"""
import json
from datetime import datetime
from pathlib import Path

from canon import labstats, metrics, soelab
from canon.schema import SoeLabel

from .jsvm import needs_node, run_js

FILES = ["app.js", "style.js", "soelab.js"]
FIX = Path(__file__).parent / "fixtures" / "soelab"


@needs_node
def test_verdict_matches_labstats():
    eps = 1e-9
    xs = [0.0, 0.3, 0.5 - eps, 0.5, 0.5 + eps, 0.69, 0.7 - eps, 0.7, 0.7 + eps, 0.9, 1.0]
    cases = [(lo, hi, v) for lo in xs for hi in xs for v in xs if lo <= hi]
    got = run_js(FILES, "data.map(([lo, hi, v]) => soeVerdict(lo, hi, v))", cases)
    assert got == [labstats.verdict(lo, hi, v) for lo, hi, v in cases]
    # 칩 글자는 labstats.VERDICTS 와 같다
    chips = run_js(FILES, "SOE_CHIPS", None)
    assert {k: chips[k][0] for k in labstats.VERDICTS} == labstats.VERDICTS
    assert chips["few"][0] == soelab.CHIP["few"] and chips["tbd"][0] == soelab.CHIP["tbd"]


def _st(**kw):
    base = {"pieces": 60, "judged": 0, "goal": 40, "stopped": False, "inBatch": 0, "queueLeft": 50, "redoDue": 0,
            "held": False, "spareReady": 0, "stale": False, "checkLeft": 0}
    return {**base, **kw}


@needs_node
def test_next_order():
    cases = [
        _st(redoDue=5),                                  # 1. 다시 읽기가 열렸으면 먼저
        _st(redoDue=3, held=True, spareReady=6),         # 열린 다시 읽기가 먼저
        _st(judged=40, goal=40, held=True, spareReady=15),  # 판정 일관성 보류: 예비 열기
        _st(judged=90, goal=90, held=True, spareReady=0),   # 열 예비가 없으면 건너뜀
        _st(judged=34, inBatch=4),                       # 2. 1차 · 중간에 멈춤
        _st(judged=30),
        _st(judged=40),                                  # 3. 1차 끝, 아직 고르지 않음 → 카드가 주 버튼
        _st(judged=45, goal=60, inBatch=5),              # 4. 60개까지
        _st(judged=60, goal=90),
        _st(judged=60, goal=60),                         # 60개 끝 카드
        _st(judged=30, stopped=True, stale=True),        # 멈췄으면 판정을 건너뛰고 다시 채점하기
        _st(judged=90, goal=90, checkLeft=32),           # 다 읽음 → 패턴 확인
        _st(judged=90, goal=90),                         # 그 밖에는 조각 모으기
        _st(pieces=0, judged=0, queueLeft=0),
        _st(judged=12, queueLeft=0, stale=True),         # 대기열이 바닥났으면 판정 건너뜀
    ]
    got = run_js(FILES, "data.map((st) => soeNext(st))", cases)
    assert got == [
        {"kind": "redo", "label": "다시 읽기 5개"},
        {"kind": "redo", "label": "다시 읽기 3개"},
        {"kind": "spare", "label": "다시 읽기 15개 더"},
        {"kind": "collect", "label": "+ 조각 모으기"},
        {"kind": "judge", "label": "판정 이어 하기 (1차 6개 남음)"},
        {"kind": "judge", "label": "판정 10개 하기 (1차 10개 남음)"},
        None,
        {"kind": "judge", "label": "판정 이어 하기 (60개까지 15개 남음)"},
        {"kind": "judge", "label": "판정 10개 하기 (90개까지 30개 남음)"},
        None,
        {"kind": "rescore", "label": "다시 채점하기 · AI 없음"},
        {"kind": "check", "label": "패턴 확인 이어 하기 (32개 남음)"},
        {"kind": "collect", "label": "+ 조각 모으기"},
        {"kind": "collect", "label": "+ 조각 모으기"},
        {"kind": "rescore", "label": "다시 채점하기 · AI 없음"},
    ]


@needs_node
def test_round_and_steps():
    got = run_js(FILES, "data.map(([j, g]) => soeRound(j, g))", [[34, 40], [40, 40], [41, 60], [90, 90]])
    assert got == ["34/40 · 1차", "40/40 · 1차", "41/90", "90/90"]
    sc = {"pieces": 0, "by_origin": {}, "judged": 0, "goal": 40, "stopped": False, "queue_left": 0,
          "redo_state": {"target": 0, "done": 0, "due": 0, "opens": ""}, "report": None}
    steps = run_js(FILES, "soeSteps(data)", sc)
    assert [(s["id"], s["state"], s["right"]) for s in steps] == [
        ("corpus", "now", "비었어요"), ("judge", "todo", "0/40 · 1차"), ("redo", "todo", "0/0"), ("metrics", "todo", "–")]
    sc.update(pieces=60, by_origin={"human": 20, "ai": 40}, judged=34, queue_left=26,
              redo_state={"target": 13, "done": 0, "due": 0, "opens": "2026-11-07"})
    steps = run_js(FILES, "soeSteps(data)", sc)
    assert [(s["state"], s["right"]) for s in steps[:3]] == [("ok", "사람 20 · AI 40"), ("now", "34/40 · 1차"), ("todo", "2026.11.07부터")]
    sc["redo_state"] = {"target": 13, "done": 2, "due": 4, "opens": ""}
    assert run_js(FILES, "soeSteps(data)[2]", sc)["state"] == "warn"


@needs_node
def test_redo_due_matches_server():
    firsts = ["2026-10-31T23:59:00+09:00", "2026-11-01T00:10:00-05:00", "2026-02-25T09:00:00+09:00", "2026-12-28T12:00:00+00:00"]
    todays = ["2026-11-06", "2026-11-07", "2026-11-08", "2026-03-04", "2027-01-04", "2027-01-03"]
    cases = [[f, t] for f in firsts for t in todays]
    got = run_js(FILES, "data.map(([f, t]) => soeRedoDue(f, t))", cases)
    for (f, t), g in zip(cases, got):
        lb = SoeLabel(id="x", at=f, piece="p")
        opens = soelab.redo_open("p", [lb])
        assert g["date"] == opens.isoformat()
        assert g["open"] == (datetime.fromisoformat(t).date() >= opens)


@needs_node
def test_sentences_match_metrics():
    texts = [p.read_text(encoding="utf-8") for p in sorted(FIX.glob("*.txt"))]
    texts += ["", "한 문장", "  앞 빈칸. 뒤에도 빈칸.  ", "그가 말했다. \"정말?\" 그녀가 웃었다…  그래서!\n\n새 문단이다.",
              "끝에 따옴표.” 다음 문장」 그다음… 끝?! 마지막)", "줄\n바꿈\n\n\n여러 번", "숫자 3.14는 문장이 아니다. 하지만 이것은 문장이다."]
    got = run_js(FILES, "data.map((t) => soeSentences(t))", texts)
    assert got == [[list(x) for x in metrics.sentence_spans(t)] for t in texts]
    # 문장 누르기: 모든 글자 자리에서 같은 문장 번호 (문장 사이 빈칸은 -1)
    t = texts[3]
    spans = metrics.sentence_spans(t)
    want = [next((i for i, (a, b) in enumerate(spans) if a <= k < b), -1) for k in range(len(t) + 1)]
    got = run_js(FILES, "(() => { const sp = soeSentences(data); return Array.from({ length: data.length + 1 }, (_, k) => soeSentenceAt(sp, k)); })()", t)
    assert got == want


@needs_node
def test_mark_merge():
    spans = [{"start": 0, "end": 10, "kind": "other"}, {"start": 20, "end": 30, "kind": "cliche"}, {"start": 40, "end": 50, "kind": "other"}]
    got = run_js(FILES, "soeMarkMerge(data.spans, data.add)", {"spans": spans, "add": {"start": 8, "end": 25, "kind": "번역투"}})
    assert [(s["start"], s["kind"]) for s in got] == [(8, "번역투"), (40, "other")]
    got = run_js(FILES, "soeMarkMerge(data.spans, data.add)", {"spans": spans, "add": {"start": 10, "end": 20, "kind": "copy"}})
    assert [s["start"] for s in got] == [0, 10, 20, 40]  # 닿기만 한 표시는 남긴다


def test_kind_ids_match_server():
    """화면 갈래 8 · 칩은 서버 값을 받아 그린다. 서버의 갈래 id 는 metrics.AI_PATTERNS 이름과 cliche · copy · other 다."""
    assert soelab.SPAN_KINDS[:5] == [n for n, _, _ in metrics.AI_PATTERNS]
    assert soelab.SPAN_KINDS[5:] == ["cliche", "copy", "other"]
    assert json.dumps([soelab.KIND_LABELS[k] for k in soelab.SPAN_KINDS], ensure_ascii=False) == json.dumps(
        ["부정 후 재정의", "셋씩 나열", "감정 이름", "번역투", "서식 흔적", "상투 표현", "옮김", "기타"], ensure_ascii=False)
