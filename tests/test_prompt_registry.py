"""프롬프트 관리 페이지의 레지스트리(prompts.KINDS · PIECES) 시험과 요청 스냅샷 (mock LLM). 실행: python -m pytest tests/test_prompt_registry.py

스냅샷: 함수 안의 긴 글을 이름 붙은 상수로 꺼내도 요청이 한 글자도 바뀌지 않는지 본다.
단편 · 장편 mock 작품에서 시스템 프롬프트와 요청마다 sha256 앞 16자를 tests/snapshots/prompt_registry.json 과 견준다.
이 값은 상수로 꺼내기 전 코드로 만들었다. 프롬프트 문구를 일부러 바꾸면
CANON_UPDATE_SNAPSHOT=1 python -m pytest tests/test_prompt_registry.py 로 다시 만든다.
"""
import difflib
import hashlib
import json
import os
import random
import tempfile
from pathlib import Path

from canon import llm, naming, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import RewriteRequest
from tests.test_serial import _finish, _plan_arc, _serial

SNAPSHOT = Path(__file__).parent / "snapshots" / "prompt_registry.json"
L = MockLLM()


def _short():
    p = prompts.Project()
    p.meta.title, p.meta.target_episodes = "단편", 6
    pipeline.apply_setup(p, pipeline.suggest_setup(L, p))
    p.arc = pipeline.plan_arc(L, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(L, p, 1, 6))
    for n in (1, 2, 3, 4):
        pipeline.confirm_plot(p, n)
        if n < 4:
            p.episode(n).text = pipeline.write_episode(L, p, n)
            p.episode(n).status = "written"
            pipeline.apply_delta(p, pipeline.extract_state(L, p, n))
    p.episode(4).direction = "비 오는 장면은 소리로만 보여 준다"
    return p


def _long():
    p = _serial()
    _finish(p, _plan_arc(p))
    a = _plan_arc(p)
    p.episode(a.start_ep).direction = "첫 장면은 짧게"
    return p


def _requests(p) -> dict[str, str]:
    """작품 하나의 요청 모음: 작업지시서 갈래 모두(시스템 · 요청 · 응답 형식)와 그 밖의 쓰기 가족 요청."""
    out: dict[str, str] = {}

    def run(key, f):
        random.seed(0)
        naming._rng = lambda rng: rng or random.Random(0)
        try:
            out[key] = f()
        except ValueError as e:  # 이 작품에서 만들 수 없는 갈래도 같은 오류인지 본다
            out[key] = f"ValueError: {e}"

    written = [e.plot.number for e in p.episodes if e.text]
    fresh = min(e.plot.number for e in p.episodes if not e.text)
    for kind in prompts.BRIEF_KINDS:
        k = prompts.BRIEF_KINDS[kind]
        n = written[-1] if k.need == "text" else fresh
        if kind == "plot":
            n = next((e.plot.number for e in p.episodes if e.status == "draft"), fresh)
        run(f"brief:{kind}", lambda: "\n\0".join(map(str, prompts.brief_parts(p, n, kind))))
    for n in sorted({written[0], written[-1], fresh}):
        run(f"episode:{n}", lambda: prompts.episode_prompt(p, n))
        run(f"writer_system:{n}", lambda: prompts.writer_system(p))
    last = written[-1]
    run("polish", lambda: prompts.polish_prompt(p, last, p.episode(last).text))
    run("motion", lambda: prompts.motion_prompt(p, last))
    run("rewrite", lambda: pipeline.rewrite_prompt(p, fresh, RewriteRequest(feedback="더 짧게")))
    run("check_full", lambda: prompts.check_prompt(p, last, "full"))
    run("check_en", lambda: prompts.checker_system("en") + prompts.check_prompt(p, last, lang="en"))
    run("storyboard", lambda: prompts.storyboard_prompt(p, fresh))
    run("static_context", lambda: prompts.static_context(p))
    run("reviser_system", lambda: prompts.reviser_system(p))
    run("with_note", lambda: llm.with_note("요청"))
    return out


def _systems() -> dict[str, str]:
    return {k: getattr(prompts, k) for k in sorted(dir(prompts)) if k.startswith("SYSTEM_") and isinstance(getattr(prompts, k), str)}


def _all() -> dict[str, str]:
    out = {f"sys:{k}": v for k, v in _systems().items()}
    out.update({f"short:{k}": v for k, v in _requests(_short()).items()})
    out.update({f"long:{k}": v for k, v in _requests(_long()).items()})
    return out


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def test_requests_unchanged():
    texts = _all()
    got = {k: _h(v) for k, v in texts.items()}
    if os.environ.get("CANON_UPDATE_SNAPSHOT"):
        SNAPSHOT.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if got != want:
        dump = Path(tempfile.mkdtemp(prefix="prompt-registry-"))
        for k, v in texts.items():
            (dump / (k.replace(":", "_").replace("/", "_") + ".txt")).write_text(v, encoding="utf-8")
        diff = sorted(set(got.items()) ^ set(want.items()))
        assert got == want, f"바뀐 요청 {len(diff)}: {[k for k, _ in diff][:12]} · 지금 전문: {dump}\n" + "\n".join(
            difflib.unified_diff(sorted(want), sorted(got), lineterm=""))


# ---------- 레지스트리 ----------

def _names() -> set[str]:
    out = set()
    for k in prompts.KINDS.values():
        out |= {k.system, k.request, *k.also}
    return out | {pc.source for pc in prompts.PIECES.values()}


def test_every_system_and_request_is_registered():
    """SYSTEM_* 상수와 *_prompt 함수는 모두 KINDS 나 PIECES 에 있다 (새로 만들면 표에도 적는다)."""
    import inspect
    import re

    src = inspect.getsource(prompts)
    systems = set(re.findall(r"^(SYSTEM_[A-Z_]+) = ", src, re.M))
    requests = set(re.findall(r"^def ([a-z_]+_prompt)\(", src, re.M)) - {"system_prompt"}
    assert len(systems) >= 25 and len(requests) >= 70
    missing = sorted((systems | requests) - _names())
    assert not missing, f"레지스트리(prompts.KINDS · PIECES)에 없는 이름: {missing}"


def test_registry_names_resolve():
    bad = sorted(x for x in _names() if prompts.resolve_name(x) is None)
    assert not bad, f"가리키는 이름이 코드에 없어요: {bad}"
    for k, v in prompts.KINDS.items():
        mod, _, fn = v.caller.split(" · ")[0].rpartition(".")
        assert prompts.resolve_name(f"{mod}.{fn}") is not None or mod == "routes", (k, v.caller)


def test_registry_shape():
    from canon import schema, settings

    for k, v in prompts.KINDS.items():
        assert v.group in prompts.KIND_GROUPS, k
        assert v.stage in ("", *settings.STAGES), k
        assert all(x in prompts.PIECES for x in v.pieces), (k, [x for x in v.pieces if x not in prompts.PIECES])
        assert len(set(v.pieces)) == len(v.pieces), k
        for name in filter(None, v.response.split(" · ")):
            assert hasattr(schema, name), (k, name)
    for pid, pc in prompts.PIECES.items():
        assert pc.tags and all(t in prompts.TAGS for t in pc.tags), pid
        assert pc.place in prompts.PLACES, pid
    assert set(prompts.BLOCK_BY_ID) <= set(prompts.PIECES)  # 쓰기 블록 id 는 조각 id 그대로
    assert all(prompts.kinds_of(x) for x in prompts.PIECES if x != "out_format"), [x for x in prompts.PIECES if not prompts.kinds_of(x)]


def test_brief_kinds_is_a_view_of_kinds():
    """BRIEF_KINDS 는 KINDS 에서 고른 보기다. 열쇠 · 값 · 차례가 레지스트리 전과 같다 (작업지시서 · 놀이터가 이 열쇠를 쓴다)."""
    B = prompts.BriefKind
    want = {
        "setup_chat": B("대화로 다듬기 · 설정 도우미", scope="work"),
        "style_chat": B("대화로 다듬기 · 문체", scope="work"),
        "series": B("부 구성", scope="work", form="serial"),
        "arc": B("기승전결 구조 · 다음 아크", scope="work"),
        "heat": B("완급 계획", scope="work"),
        "plots": B("플롯 초안", scope="act"),
        "plot": B("한 화 플롯", need="draft"),
        "agent_plot": B("대화로 다듬기 · 플롯 (대화 에이전트 첫 단계)", scope="work", stage="chat"),
        "storyboard": B("스토리보드", need="confirmed", stage="board"),
        "cue": B("큐 시트", need="confirmed", stage="board"),
        "episode": B("본문 쓰기", stage="write"),
        "passage": B("대화로 다듬기 · 본문 부분 수정", need="text", stage="revise"),
        "check": B("검수", need="text", stage="check"),
        "state": B("상태 변경안", need="text", stage="state"),
    }
    assert list(prompts.BRIEF_KINDS.items()) == list(want.items())
    assert all(prompts.KINDS[k].label == v.label and prompts.KINDS[k].stage == v.stage for k, v in want.items())
    # 1단계 조립 보기: 작업지시서 14갈래 + 서술 다듬기 · 동선 검수 · 다시 생성 (정할 것 5)
    assert {k for k, v in prompts.KINDS.items() if v.view} == set(want) | {"polish", "motion", "rewrite"} == set(want) | set(prompts.VIEW_NEED)


def _examples():
    from canon import promptlab

    return [("short", promptlab.example_project()), ("serial", promptlab.example_serial())]


def test_view_pieces_are_in_the_assembled_request():
    """조립 보기의 조각 글은 조립된 요청에 들어 있다. 조건이 맞지 않아 빈 글이면 건너뛴다.
    늘 들어가는 조각(머리말 · 문체 기본 규칙 · 쓰기 지시 · 검수 목록 등)은 빈 글이 아니어야 한다."""
    from canon import promptlab

    always = {"episode": {"preamble", "prose_rules", "writer_task", "style", "style_profile", "plot", "instructions", "write_style",
                          "write_speech", "write_flow", "ending"},
              "polish": {"polish_rules", "polish_ending", "work"}, "check": {"sys_checker", "check_material", "check_rules", "severity"},
              "motion": {"motion_rules"}, "state": {"state_rules", "attire_state"}, "storyboard": {"board_rules"}}
    for name, p in _examples():
        for k, v in prompts.KINDS.items():
            if not v.view or (v.brief and v.brief.form == "serial" and not p.serial):
                continue
            n = promptlab.default_n(p, k) if k in prompts.BRIEF_KINDS else max(e.plot.number for e in p.episodes if e.text)
            system, prompt, _ = prompts.view_request(p, n, k)
            for pid in v.pieces:
                text = prompts.piece_text(p, n, pid, k, prompt)
                if pid in always.get(k, ()):
                    assert text.strip(), (name, k, pid)
                if text and pid not in ("opening_plot_rule",):  # 여는 화 규칙은 1~3화가 범위에 들 때만 (견본 범위 밖)
                    assert prompts.found_in(text, system, prompt) is not False, (name, k, pid, text[:80])


def test_examples_do_not_save(tmp_path, monkeypatch):
    from canon import promptlab, store

    monkeypatch.setattr(store, "ROOT", tmp_path)
    promptlab.example_serial()
    assert not list(tmp_path.iterdir())


# ---------- 라우트 ----------

def test_routes(client):
    r = client.get("/api/prompts/kinds").json()
    assert len(r["kinds"]) == len(prompts.KINDS) and dict(r["tags"])["style"] == "문체"
    ep = client.get("/api/prompts/kinds/episode").json()
    assert ep["sample"]["project"] == "" and ep["sample"]["n"] == 3 and not ep.get("error")
    rows = {x["id"]: x for x in ep["pieces"]}
    assert rows["prose_rules"]["found"] is True and rows["prose_rules"]["tokens"] > 0
    assert rows["policy_note"]["found"] is None and rows["policy_note"]["text"]
    assert ep["system"].startswith(prompts.PREAMBLE) and ep["prompt"]
    # 장편에만 있는 갈래는 예시 장편으로 조립한다
    se = client.get("/api/prompts/kinds/series").json()
    assert se["sample"]["project"] == ":serial" and se["sample"]["serial"] and not se.get("error")
    assert client.get("/api/prompts/kinds/plot?project=:serial").json()["sample"]["serial"]
    # 조립 보기가 없는 갈래는 표만
    assert "prompt" not in client.get("/api/prompts/kinds/setup").json()
    topic = client.get("/api/prompts/topics/style").json()
    ids = {x["id"] for x in topic["pieces"]}
    assert {"prose_rules", "style", "devices", "echo", "write_style", "ending", "polish_rules"} <= ids  # 왜 필요한가 표의 다섯 자리
    assert next(x for x in topic["pieces"] if x["id"] == "prose_rules")["text"].startswith("[문체 기본 규칙]")
    pc = client.get("/api/prompts/pieces/ending").json()
    assert "열에" in pc["text"] and "episode" in pc["kinds"]
    assert client.get("/api/prompts/kinds/nope").status_code == 404
    assert client.get("/api/prompts/topics/nope").status_code == 404
    assert client.get("/api/prompts/kinds/episode?project=없는작품").status_code == 404
    bad = client.get("/api/prompts/kinds/check?n=5").json()  # 본문이 없는 화
    assert "본문이 없어" in bad["error"]
