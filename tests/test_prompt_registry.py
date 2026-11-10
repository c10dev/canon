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
