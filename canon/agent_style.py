"""대화 에이전트의 문체 도구 'edit_style' (docs/ux/specs/04-one-agent.md 04d): 문체 대화의 변경안을 승인 카드로 묻는다.

- 에이전트가 edit_style(args: request, episode)을 고르면 prepare 가 잠금 밖에서 pipeline.revise_style(LLM 단계 'plan')을 부른다.
  옛 문체 대화와 같은 프롬프트 · 정리(clean_style_revision)다.
- record 가 잠근 작품에서 변경안을 다시 정리하고 문체 변경안 카드(Approval.style)를 남긴 뒤 턴을 끝낸다. 바꿀 칸이 없으면 편집자 답으로 끝낸다.
  권한 모드와 상관없이 늘 묻고, '이 세션에서 묻지 않기'(auto_kinds)도 받지 않는다 (agent.ALWAYS_ASK, 2026-11-09 사용자 결정).
- decide 는 작가가 고른 칸만 pipeline.apply_style_edits 로 넣고 넣기 전 문체를 WriteRecord.style 에 남긴다. 답하면 턴을 끝낸다 (AI 를 더 부르지 않는다).
  undo 는 pipeline.undo_style_edits 로 그 뒤에 다시 고치지 않은 칸만 돌린다. 오래된 턴의 넣기 전 문체는 compact 가 지운다.
- 지름길은 없다. 참고할 화 칩은 지울 때까지 남는 칩이라 말 하나의 뜻을 정하지 않는다 (문체 대상의 말도 에이전트가 도구를 고른다).
- 옛 문체 대화(Project.chats 'style')에는 남기지 않는다. 옛 기록은 '이전 대화'에서 읽기만 한다 (정할 것 6).
agent.py 의 CARD_TOOLS 가 이 모듈을 등록한다 (훅 이름은 agent_text.py 머리).
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import pipeline
from .prompts import STYLE_KEY_LABELS
from .schema import AgentSession, AgentTurn, Approval, PlotAgentStep, Project, StepRecord, StyleCard, WriteItem, WriteRecord

TOOL = "edit_style"
KIND = "style"  # 승인 카드의 종류 (agent.KIND_LABELS). agent.ALWAYS_ASK 에 들어 늘 묻는다
LABEL = "문체 고치기"
KEPT = "그 뒤에 다시 고친 칸이라 그대로 뒀어요"
# 화면에 보이는 칸 이름 (stylechat.js STYLE_KEYS 와 같다). 프롬프트는 prompts.STYLE_KEY_LABELS 를 그대로 쓴다
STYLE_LABELS = {**STYLE_KEY_LABELS, "markers": "문체 버릇"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def label(key: str) -> str:
    return STYLE_LABELS.get(key, key)


def shortcut(turn: AgentTurn) -> PlotAgentStep | None:
    """문체 도구는 지름길이 없다 (모듈 머리 참고)."""
    return None


def ref_episode(p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep) -> int:
    """참고할 화. 도구 인자 episode 가 먼저이고, 비었으면 문체 대상 턴이 실어 온 화(turn.episode, 화면의 '참고할 화' 칩)를 쓴다."""
    raw = str({a.name: a.value for a in step.args}.get("episode", "")).strip().rstrip("화")
    if raw.isdigit():
        return int(raw)
    return turn.episode if pipeline.chat_focus(p, s.target)[0] == "style" else 0


def _ref_text(p: Project, n: int) -> str:
    ep = next((e for e in p.episodes if e.plot.number == n), None) if n else None
    return ep.text if ep else ""


def prepare(name: str, p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep) -> StyleCard | str:
    """잠금 밖에서 문체 변경안을 받는다 (AI 호출 한 번, 단계 'plan'). 받지 못하면 까닭(글)을 돌려준다 (본문이 없는 화를 참고로 고름 등)."""
    from .llm import get_llm

    request = str({a.name: a.value for a in step.args}.get("request", "")).strip() or turn.user.strip()
    episode = ref_episode(p, s, turn, step)
    try:
        rev = pipeline.revise_style(get_llm("plan"), p, request, episode)
    except ValueError as e:
        return str(e)
    return StyleCard(revision=rev, episode=episode)


def record(p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep, prepared: StyleCard | str | None) -> str:
    """잠근 작품에서 변경안을 다시 정리하고 카드를 남긴다. 턴 끝 상태('wait' · 'done') 또는 '' (막혀서 에이전트가 이어 간다)."""
    if not isinstance(prepared, StyleCard):
        why = prepared or "문체 변경안을 받지 못했어요"
        turn.steps.append(StepRecord(kind="block", tool=TOOL, label="문체", why=why, result=f"할 수 없어요: {why}"))
        return ""
    # AI 를 기다리는 동안 작가가 고친 칸은 다시 거른다 (지금 값과 같아진 칸은 빠진다)
    rev = pipeline.clean_style_revision(p, prepared.revision.model_copy(deep=True), _ref_text(p, prepared.episode))
    turn.reply = rev.reply.strip() or step.reply.strip() or step.thought.strip()
    if not rev.edits:
        turn.steps.append(StepRecord(kind="note", tool=TOOL, label="문체", why="바꿀 칸 없이 답했어요"))
        return "done"
    keys = [e.key for e in rev.edits]
    names = " · ".join(label(k) for k in keys)
    turn.approval = Approval(tool=TOOL, style=StyleCard(revision=rev, episode=prepared.episode), keys=keys, kinds=[KIND])
    turn.steps.append(StepRecord(kind="wait", tool=TOOL, label=names, why="문체는 늘 물어보고 바꿔요",
                                 result=f"작가에게 물음: {names}. 작가의 답을 기다려야 하므로 턴을 끝냅니다"))
    return "wait"


def decide(p: Project, s: AgentSession, turn: AgentTurn, approve: bool, picked: list[str], text: str | None = None) -> None:
    """카드에 답한다. 승인하면 고른 칸만 넣는다(고른 칸이 없으면 ValueError, 카드는 그대로). 어느 쪽이든 턴을 끝낸다.
    picked 가 비면 카드의 모든 칸이다 (agent.decide 의 다른 카드와 같다). text 는 본문 고치기 것이라 쓰지 않는다."""
    a = turn.approval
    assert a is not None and a.style is not None
    if approve:
        keys = [k for k in picked if k in a.keys] if picked else list(a.keys)
        applied, before = pipeline.apply_style_edits(p, a.style.revision, keys, a.style.episode)
        done = StyleCard(revision=a.style.revision.model_copy(deep=True), episode=a.style.episode, applied=applied, before=before)
        turn.writes.append(WriteRecord(tool=TOOL, style=done, items=[WriteItem(key=k, label=label(k)) for k in applied]))
        a.state, a.picked = "approved", applied
        turn.steps.append(StepRecord(kind="note", tool="approval", label=", ".join(label(k) for k in applied), why="작가가 고른 칸만 적용했어요"))
    else:
        a.state = "denied"
        turn.steps.append(StepRecord(kind="note", tool="approval", why="작가가 적용하지 않았어요"))
    turn.end, turn.ended = "done", _now()
    for x in turn.steps:
        x.result = ""


def undo(p: Project, rec: WriteRecord, items: list[WriteItem]) -> tuple[list[str], list[str], list[str]]:
    """적용한 문체 칸(items)을 되돌린다. 그 뒤에 다시 고친 칸은 남긴다. (되돌린 이름, 남긴 이름, 남긴 까닭)."""
    card = rec.style
    if card is None or card.before is None:
        return [], [], []
    done, kept = pipeline.undo_style_edits(p, card.revision, [i.key for i in items], card.before)
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
    """오래된 턴의 넣기 전 문체 · 변경안을 지운다 (agent._compact). 아직 되돌리지 않은 칸은 kept 로 남긴다."""
    for i in rec.items:
        if i.state == "done":
            i.state, i.reason = "kept", reason
    rec.style = None
