"""대화 에이전트의 설정 도구 'edit_setup' (docs/ux/specs/04-one-agent.md 04c): 설정 도우미 대화의 변경안을 승인 카드로 묻는다.

- 에이전트가 edit_setup(args: request)을 고르면 prepare 가 잠금 밖에서 pipeline.revise_setup(LLM 단계 'plan')을 부른다.
  옛 설정 대화와 같은 프롬프트 · 정리(setupchat.clean)다. 방향 여러 안은 에이전트의 ask 가 묻으므로 mode 는 늘 비운다.
  대화 기록은 이 세션의 지난 턴이다 (prompts.setup_session_history: 지난 설정 카드의 부분 값, 작가의 결정, 되돌린 부분, 되물음).
- record 가 잠근 작품에서 변경안을 다시 정리하고 승인 카드(Approval tool 'edit_setup')를 남긴 뒤 턴을 끝낸다.
  권한 모드와 상관없이 늘 묻고, '이 세션에서 묻지 않기'(auto_kinds)도 받지 않는다 (agent.ALWAYS_ASK, 2026-11-09 사용자 결정).
- 카드가 처음 체크해 두는 부분(defaults)은 서버가 정한다. 이미 채운 칸과 인물 칸(인물 설정 바꾸기)은 꺼 두고, 빈 칸 · 새 인물 · 새 관계만 켠다.
- decide 는 작가가 고른 부분만 setupchat.apply_revision 으로 넣고 쓰기 전 설정을 WriteRecord.setup_before 에 남긴다. 답하면 턴을 끝낸다.
  undo 는 setupchat.undo_revision 으로 그 뒤에 다시 고치지 않은 부분만 돌린다.
- 관계 수치(affinity · tension)는 AI 가 적지 않는다. 새 관계의 수치는 0 으로 두고, 시작 관계는 보는 방식(a_view · b_view)으로 계산한다.
agent.py 의 CARD_TOOLS 가 이 모듈을 등록한다 (훅 이름은 agent_text.py 머리). 오래된 턴의 쓰기 전 설정은 compact 가 지운다.
옛 단발 설정 대화의 보내기(chat_send 'setup')는 04e 에서 지웠다. setupchat.record · apply · undo 는 명령줄(cli.py)과 옛 기록의 적용 취소가 쓰므로 남긴다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import pipeline, prompts, setupchat
from .schema import AgentSession, AgentTurn, Approval, PlotAgentStep, Project, SetupRevision, StepRecord, WriteItem, WriteRecord

TOOL = "edit_setup"
KIND = "setup"  # 승인 카드의 종류 (agent.KIND_LABELS). agent.ALWAYS_ASK 에 들어 늘 묻는다
LABEL = "설정 고치기"
KEPT = "그 뒤에 다시 고쳤거나 이미 쓰이는 새 인물이라 그대로 뒀어요"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def request(turn: AgentTurn, step: PlotAgentStep) -> str:
    """설정 편집자에게 넘길 말. 비면 작가의 이번 말을 쓴다. 지난 턴은 prepare 가 대화 기록으로 따로 넘긴다."""
    args = {a.name: a.value for a in step.args}
    return str(args.get("request", "")).strip() or turn.user.strip()


def shortcut(turn: AgentTurn) -> PlotAgentStep | None:
    """설정 도구는 지름길이 없다 (재료 · 빠른 요청은 본문 고치기 것이다)."""
    return None


def prepare(name: str, p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep) -> SetupRevision | str:
    """잠금 밖에서 설정 변경안을 받는다 (AI 호출 한 번, 단계 'plan'). 받지 못하면 까닭(글)을 돌려준다. AI 오류는 그대로 올려 턴을 멈춘다."""
    from .llm import get_llm

    history = prompts.setup_session_history(p, [t for t in s.turns if t is not turn])
    try:
        return pipeline.revise_setup(get_llm("plan"), p, request(turn, step), history=history)
    except ValueError as e:
        return str(e)


def defaults(p: Project, rev: SetupRevision) -> list[str]:
    """카드가 처음 체크해 두는 부분. 사용자가 채운 칸은 AI 제안이 덮지 않게 꺼 둔다(setupchat.js 와 같은 규칙).
    인물 칸은 빈 칸이어도 인물 설정 바꾸기라 꺼 둔다. 새 인물과 새 관계는 켠다."""
    out = [e.key for e in rev.edits if not _filled(setupchat.key_value(p, e.key))]
    out += [f"new:{c.id}" for c in rev.new_characters]
    out += [setupchat.rel_id(r) for r in rev.relationships if setupchat._pair(p.relationships, r.a, r.b) is None]
    order = setupchat.part_ids(rev)
    return sorted(out, key=order.index)


def _filled(v) -> bool:
    return bool(v) if isinstance(v, list) else bool(str(v or "").strip())


def _no_numbers(p: Project, rev: SetupRevision) -> None:
    """새 관계에 AI 가 적은 호감 · 긴장 수치를 지운다 (있는 관계는 setupchat.clean 이 지금 수치를 지킨다)."""
    for r in rev.relationships:
        if setupchat._pair(p.relationships, r.a, r.b) is None:
            r.affinity, r.tension = 0, 0


def record(p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep, prepared: SetupRevision | str | None) -> str:
    """잠근 작품에서 변경안을 다시 정리하고 승인 카드를 남긴다. 턴 끝 상태('wait') 또는 '' (에이전트가 이어 간다)."""
    if not isinstance(prepared, SetupRevision):
        why = prepared or "설정 변경안을 받지 못했어요"
        turn.steps.append(StepRecord(kind="block", tool=TOOL, label="설정", why=why, result=f"할 수 없어요: {why}"))
        return ""
    rev = setupchat.clean(p, prepared.model_copy(deep=True))  # AI 를 기다리는 동안 작가가 고친 칸은 다시 거른다
    _no_numbers(p, rev)
    keys = setupchat.part_ids(rev)
    if not keys:
        said = rev.reply.strip() or "없음"
        turn.steps.append(StepRecord(kind="note", tool=TOOL, label="설정", why="바뀌는 칸이 없어요",
                                     result=f"설정 편집자가 바꿀 칸을 내지 않았어요. 편집자의 말: {said}"))
        return ""
    turn.approval = Approval(tool=TOOL, setup=rev, keys=keys, kinds=[KIND], defaults=defaults(p, rev))
    names = ", ".join(setupchat.label(p, rev, k) for k in keys)
    turn.steps.append(StepRecord(kind="wait", tool=TOOL, label=f"설정 {len(keys)}곳", why="설정은 늘 칸마다 물어보고 바꿔요",
                                 result=f"작가에게 물음: {names}. 작가의 답을 기다려야 하므로 턴을 끝냅니다"))
    turn.reply = rev.reply.strip() or step.reply.strip() or step.thought.strip()
    return "wait"


def decide(p: Project, s: AgentSession, turn: AgentTurn, approve: bool, picked: list[str], text: str | None = None) -> None:
    """카드에 답한다. 승인하면 작가가 고른 부분만 설정에 넣는다. 고른 것이 없거나 넣지 못하면 ValueError 로 카드를 그대로 둔다.
    어느 쪽이든 턴을 끝낸다 (에이전트를 다시 부르지 않는다). text 는 본문 고치기 것이라 쓰지 않는다."""
    a = turn.approval
    assert a is not None and a.setup is not None
    if approve:
        want = [k for k in a.keys if k in set(picked)]
        if not want:
            raise ValueError("적용할 칸을 고르세요")
        before, done = setupchat.apply_revision(p, a.setup, want)  # 못 하면 설정을 바꾸기 전에 ValueError
        turn.writes.append(WriteRecord(tool=TOOL, setup=a.setup.model_copy(deep=True), setup_before=before,
                                       items=[WriteItem(key=k, label=setupchat.label(p, a.setup, k)) for k in done]))
        a.state, a.picked = "approved", done
        names = ", ".join(setupchat.label(p, a.setup, k) for k in done)
        turn.steps.append(StepRecord(kind="note", tool="approval", label=names, why="작가가 고른 칸만 적용했어요"))
    else:
        a.state = "denied"
        turn.steps.append(StepRecord(kind="note", tool="approval", why="작가가 적용하지 않았어요"))
    turn.end = "done"
    turn.ended = _now()
    for x in turn.steps:
        x.result = ""


def undo(p: Project, rec: WriteRecord, items: list[WriteItem]) -> tuple[list[str], list[str], list[str]]:
    """설정 도구로 쓴 부분(items)을 되돌린다. (되돌린 이름, 남긴 이름, 남긴 까닭)."""
    if rec.setup is None or rec.setup_before is None:
        return [], [], []
    done, kept = setupchat.undo_revision(p, rec.setup, rec.setup_before, [i.key for i in items])
    out: tuple[list[str], list[str], list[str]] = ([], [], [])
    for i in items:
        if i.key in done:
            i.state = "reverted"
            out[0].append(i.label)
        elif i.key in kept:
            i.state, i.reason = "kept", KEPT
            out[1].append(i.label)
            out[2].append(KEPT)
    return out


def compact(rec: WriteRecord, reason: str) -> None:
    """오래된 턴의 쓰기 전 설정 · 변경안을 지운다 (agent._compact). 아직 되돌리지 않은 부분은 kept 로 남긴다."""
    for i in rec.items:
        if i.state == "done":
            i.state, i.reason = "kept", reason
    rec.setup = rec.setup_before = None
