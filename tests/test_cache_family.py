"""캐시 가족: 같은 앞부분을 쓰는 호출이 그 앞부분으로 시작하고, 끝을 PREFIX_HINT 로 넘기는지 본다."""

from canon import pipeline, prompts
from canon.llm import PREFIX_HINT
from canon.mock import MockLLM
from tests.test_serial import _finish, _plan_arc, _serial


class Recorder(MockLLM):
    """가족을 받는 백엔드처럼 굴며 받은 요청과 hint 를 남긴다."""
    family_cache = True

    def __init__(self):
        super().__init__()
        self.seen: list[tuple[str, str, dict]] = []

    def json(self, system, prompt, schema, hint=None):
        self.seen.append((system, prompt, dict(hint or {})))
        return super().json(system, prompt, schema, hint)

    def text(self, system, prompt, hint=None):
        self.seen.append((system, prompt, dict(hint or {})))
        return super().text(system, prompt)


def _next(p):
    """다음에 쓸 화. 앞 화는 모두 끝낸 것으로 둔다."""
    for e in p.episodes:
        if e.text:
            e.status = "finalized"
    return min(e.plot.number for e in p.episodes if not e.text)


def _project():
    p = _serial()
    _finish(p, _plan_arc(p), text="직전 화 본문 " + "다" * 400)
    _plan_arc(p)
    return p


def test_write_family_shares_head():
    p = _project()
    n = _next(p)
    head = prompts.write_head(p, n)
    assert head and head.endswith(p.episode(n - 1).text[-50:])  # 직전 화 본문 원문 끝에서 끝난다
    assert prompts.storyboard_prompt(p, n).startswith(head)

    rec = Recorder()
    b = pipeline.make_storyboard(rec, p, n)
    assert rec.seen[-1][2][PREFIX_HINT] == len(head)
    pipeline.set_storyboard(p, n, b, by="ai")
    assert prompts.write_head(p, n) == head  # 스토리보드를 넣어도 앞부분은 그대로다

    pipeline.make_cue_sheet(rec, p, n)
    assert rec.seen[-1][1].startswith(head)
    assert rec.seen[-1][2][PREFIX_HINT] == len(head)

    pipeline.write_episode(rec, p, n)
    system, prompt, hint = rec.seen[-1]
    assert prompt.startswith(head) and hint[PREFIX_HINT] == len(head)
    assert system == prompts.writer_system(p)  # 시스템 프롬프트는 백엔드가 가족 공통 글로 바꾼다


def test_short_has_no_write_head():
    from tests.test_char_context import _short

    assert prompts.write_head(_short(), 4) == ""


def test_state_does_not_start_with_check_material():
    # 검수 자료로 시작하는 상태 변경안은 뺐다 (2026-11-09 실측: 입력 2배, 느리고 연속성 경고를 덜 잡음). 가족 백엔드도 예전 모양이다
    p = _project()
    n = max(e.plot.number for e in p.episodes if e.text)
    rec = Recorder()
    pipeline.extract_state(rec, p, n)
    _, prompt, hint = rec.seen[-1]
    assert prompt == prompts.state_prompt(p, n) and prompt.startswith(f"{n}화 본문을 읽고") and PREFIX_HINT not in hint


def test_check_passes_material_boundary():
    p = _project()
    n = max(e.plot.number for e in p.episodes if e.text)
    rec = Recorder()
    pipeline.check_episode(rec, p, n, widen=False, motion=False)
    first = next(x for x in rec.seen if x[0] == prompts.SYSTEM_CHECKER)
    material = prompts.check_material(p, n)
    cut = first[2][PREFIX_HINT]
    assert cut == prompts.check_cache_cut(material, n) and material[cut:].startswith(f"\n\n# {n}화 본문 (검수 대상)\n")


def test_cache_cut_survives_text_edit():
    # 고침안이나 작가가 본문을 고쳐도 경계 앞(본문 앞까지)은 그대로라 검수 가족이 같은 캐시를 읽는다
    p = _project()
    n = max(e.plot.number for e in p.episodes if e.text)
    before = prompts.check_material(p, n)
    p.episode(n).text = p.episode(n).text.replace(p.episode(n).text[:5], "고친 글", 1)
    after = prompts.check_material(p, n)
    assert before != after
    assert before[:prompts.check_cache_cut(before, n)] == after[:prompts.check_cache_cut(after, n)]
    assert prompts.check_cache_cut("본문 블록이 없는 자료", n) == len("본문 블록이 없는 자료")
