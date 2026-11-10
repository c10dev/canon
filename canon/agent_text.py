"""대화 에이전트의 본문 고치기 도구 'revise_text' (docs/ux/specs/04-one-agent.md 04b).

- 지금 'AI에게 고치기'와 같은 함수를 부른다: 후보는 pipeline.revise_passage (LLM 단계 'revise'), 기록은 record_passage,
  넣기는 apply_passage. 그래서 후보와 넣은 것은 그 화의 부분 수정 대화('text:N')와 수정 기록(Episode.edits)에 그대로 남는다.
- 결과는 후보 2~3개가 든 승인 카드다. 권한 모드와 상관없이 늘 묻고('모두 자동'도), '이 세션에서 묻지 않기'를 열지 않는다
  (agent.ALWAYS_ASK). 작가가 카드에서 고른 후보 하나만 본문에 들어간다. 답하면 턴을 끝낸다 (에이전트를 다시 돌리지 않는다).
- 지름길: 턴에 재료(고른 본문)나 빠른 요청이 붙으면 에이전트 단계 없이 이 도구를 바로 부른다. AI 호출은 한 번이다.
- 자동 집필이 돌거나 그 화를 쓰는 작업이 돌면 고치지 않는다 (web._text_guard 와 같은 검사).

agent.py 의 CARD_TOOLS 가 이 모듈을 등록한다. 늘 카드로 묻는 도구 모듈은 아래 이름을 둔다:
TOOL · KIND · LABEL, shortcut(turn) · prepare(name, p, s, turn, step) · record(p, s, turn, step, prepared) · decide(p, s, turn, approve, picked, text) · undo(p, rec, items).
prepare 는 잠금 밖에서 AI 를 부르고, record · decide · undo 는 잠금 안에서 작품을 고친다.
되돌리기 값을 턴(WriteRecord)에 두는 도구는 compact(rec, reason) 도 둔다 (agent._compact 가 오래된 턴에서 부른다, 설정 도구 agent_setup).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from . import jobs, pipeline, prompts
from .llm import get_llm
from .schema import (AgentSession, AgentTurn, Approval, PassageRevision, PlotAgentStep, Project, RuleRun, Selection, StepRecord, ToolArg,
                     WriteItem, WriteRecord)

TOOL = "revise_text"
KIND = "text"  # 승인 카드의 종류 (agent.KIND_LABELS)
LABEL = "본문 고치기"
QUOTE_LIMIT = 40  # 단계 줄에 보일 고른 부분 글자 수


@dataclass
class Prepared:
    """prepare 의 결과. error 가 있으면 고치지 못한 까닭이다 (단계 줄 · AI 에게 돌려준다)."""
    n: int = 0
    sel: Selection | None = None
    message: str = ""
    preset: str = ""
    rev: PassageRevision | None = None
    error: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= QUOTE_LIMIT else text[:QUOTE_LIMIT] + "…"


def is_shortcut(turn: AgentTurn) -> bool:
    """재료(고른 본문)나 빠른 요청이 붙은 턴인지. 그러면 에이전트 단계를 건너뛴다."""
    return turn.selection is not None or bool(turn.preset)


def shortcut(turn: AgentTurn) -> PlotAgentStep | None:
    """지름길이면 에이전트 단계 대신 쓸 단계 (AI 를 부르지 않는다)."""
    if not is_shortcut(turn):
        return None
    return PlotAgentStep(thought="고른 본문을 바로 고쳐요", tool=TOOL, args=[ToolArg(name="request", value=turn.user)])


def _guard(name: str, n: int) -> str:
    """고치면 안 되는 때의 까닭 (web._text_guard 와 같다). 괜찮으면 빈 글."""
    from . import autorun  # 무거운 모듈이라 쓸 때 부른다

    if autorun.active(name):
        return "자동 집필이 도는 중이에요. 일시정지한 뒤에 고치세요"
    if any(j.status == "running" and n in j.owned for j in jobs.listing(name)):
        return f"{n}화 본문을 쓰는 작업이 도는 중이에요. 끝난 뒤에 고치세요"
    return ""


def _focus_ep(p: Project, s: AgentSession) -> int:
    kind, lo, _, _ = pipeline.chat_focus(p, s.target)
    return lo if kind == "text" else 0


def _message(turn: AgentTurn, preset: str) -> str:
    """AI 에게 줄 작가의 말. 빠른 요청 이름만 보냈으면 비운다 (빠른 요청 지시가 이미 들어간다)."""
    said = turn.user.strip()
    label = prompts.PASSAGE_PRESETS[preset][0] if preset in prompts.PASSAGE_PRESETS else ""
    return "" if label and said in (label, "/" + label) else said


def _resolve(p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep) -> Prepared:
    """고칠 화 · 부분 · 요청을 정한다. 재료가 있으면 재료, 없으면 AI 가 적은 quote 를 그 화 본문에서 찾는다."""
    args = {a.name: a.value for a in step.args}
    preset = turn.preset or args.get("preset", "").strip()
    if preset and preset not in prompts.PASSAGE_PRESETS:
        return Prepared(error=f"모르는 빠른 요청이에요: {preset}")
    if turn.selection is not None:
        n, quote, start = turn.selection.episode, turn.selection.text, turn.selection.start
        message = _message(turn, preset)
    else:
        n = int(args["n"]) if args.get("n", "").strip().isdigit() else _focus_ep(p, s)
        quote, start = args.get("quote", ""), 0
        message = args.get("request", "").strip() or turn.user.strip()
    if not n:
        return Prepared(error="고칠 화를 몰라요. 집필 화면에서 본문을 고르거나 n 에 화 번호를 적으세요")
    try:
        ep = p.episode(n)
    except KeyError:
        return Prepared(error=f"{n}화가 없어요")
    if not quote.strip():
        return Prepared(n=n, error="고칠 부분이 비었어요. 본문에서 고르거나 quote 에 원문 그대로 적으세요")
    try:
        sel = Selection(start=pipeline.locate(ep.text, quote, start), text=quote)
    except ValueError as e:
        return Prepared(n=n, error=str(e) if turn.selection is not None else
                        "quote 가 본문에 없어요. find_text 로 찾은 단락에서 원문 그대로 옮겨 적으세요")
    return Prepared(n=n, sel=sel, message=message, preset=preset)


def prepare(name: str, p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep) -> Prepared:
    """잠금 밖에서 후보를 만든다 (AI 호출 한 번, 단계 'revise'). 저장하지 않는다."""
    out = _resolve(p, s, turn, step)
    if out.error:
        return out
    if why := _guard(name, out.n):
        out.error = why
        return out
    try:
        out.rev = pipeline.revise_passage(get_llm("revise"), p, out.n, out.sel, out.message, out.preset, rules=True)  # 'AI에게 고치기'와 같이 후보에 고침 규칙을 건다
    except (ValueError, KeyError) as e:
        out.error = str(e).strip("'")
    return out


def record(p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep, prepared: Prepared) -> str:
    """잠금 안에서 후보를 부분 수정 대화에 남기고 승인 카드를 연다. 턴 끝 상태를 돌려준다 ('' 이면 에이전트가 이어 간다)."""
    short = is_shortcut(turn)
    if prepared.error:
        turn.steps.append(StepRecord(kind="block", tool=TOOL, label=f"{prepared.n}화 본문" if prepared.n else LABEL,
                                     why=prepared.error, result=f"고치지 못했어요: {prepared.error}"))
        if short:  # 지름길은 에이전트를 부르지 않으므로 까닭을 답으로 남기고 끝낸다
            turn.reply = prepared.error
            return "done"
        return ""
    n, sel, rev = prepared.n, prepared.sel, prepared.rev
    assert sel is not None and rev is not None
    msg = pipeline.record_passage(p, n, sel, prepared.message, prepared.preset, rev)
    where = f"{n}화 «{_clip(sel.text)}»"
    if not rev.candidates:  # 원문과 다른 후보가 없거나 본문이 맞다는 답: 고를 것이 없다
        turn.steps.append(StepRecord(kind="note", tool=TOOL, label=where, why="후보가 없어요", result=f"후보 없음. 편집자 답: {rev.reply}"))
        turn.reply = rev.reply
        return "done"
    turn.approval = Approval(tool=TOOL, keys=[str(k) for k in range(len(rev.candidates))], kinds=[KIND], passage=rev, selection=sel,
                             episode=n, preset=prepared.preset, at=msg.at)
    turn.reply = rev.reply or step.reply.strip()
    turn.steps.append(StepRecord(kind="wait", tool=TOOL, label=where, why=f"후보 {len(rev.candidates)}개 · 고른 것만 넣어요",
                                 result="작가에게 후보를 보이고 고르기를 기다립니다. 턴을 끝냅니다"))
    return "wait"


def _chat_index(p: Project, a: Approval) -> int:
    """카드가 남긴 부분 수정 대화의 답 번호. 대화가 잘려 없으면 -1."""
    msgs = p.chat(f"text:{a.episode}").messages
    for i in range(len(msgs) - 1, -1, -1):
        m = msgs[i]
        if m.role == "assistant" and m.at == a.at and m.passage is not None and m.selection is not None and m.selection.text == a.selection.text:
            return i
    return -1


def decide(p: Project, s: AgentSession, turn: AgentTurn, approve: bool, picked: list[str], text: str | None = None) -> None:
    """카드에 답한다. 승인하면 고른 후보 하나(text 를 주면 작가가 손본 글)를 본문에 넣고 수정 기록에 남긴다. 어느 쪽이든 턴을 끝낸다."""
    a = turn.approval
    assert a is not None and a.passage is not None and a.selection is not None
    n = a.episode
    i = _chat_index(p, a)
    msgs = p.chat(f"text:{n}").messages
    if approve:
        keys = [k for k in picked if k in a.keys]
        if len(keys) != 1:
            raise ValueError("넣을 후보 하나를 고르세요")
        k = int(keys[0])
        if i >= 0:
            edit = pipeline.apply_passage(p, n, i, k, text)  # 'AI에게 고치기'의 넣기와 같다. 못 넣으면 ValueError 로 카드를 그대로 둔다
        else:
            cands = a.passage.candidates
            after = (text if text is not None else cands[k].text).strip()
            if not after:
                raise ValueError("넣을 글이 비었어요")
            edit = pipeline.edit_text(p, n, a.selection, after, "ai", instruction=turn.user, preset=a.preset, proposed=cands[k].text,
                                      rejected=[c.text for j, c in enumerate(cands) if j != k])
            cand = cands[k].text  # 넣은 글에 아직 남은 규칙 고침만 apply_passage 처럼 기록한다
            spots = pipeline.still_ruled(cands[k].ruled, after, after == cand.strip(), -(len(cand) - len(cand.lstrip())))
            if spots:
                pipeline.add_run(p.episode(n), RuleRun(kind="passage", changes=[c.model_copy(update={"start": edit.start + c.start}) for c in spots]))
        name = f"{n}화 본문 · {k + 1}번 후보{' (손봄)' if text is not None and text.strip() != a.passage.candidates[k].text else ''}"
        turn.writes.append(WriteRecord(tool=TOOL, episode=n, edit=edit.id, items=[WriteItem(key="text", label=name)]))
        a.state, a.picked = "approved", [str(k)]
        turn.steps.append(StepRecord(kind="note", tool="approval", label=name, why="작가가 골라 넣었어요"))
    else:
        if i >= 0 and not msgs[i].outcome:
            msgs[i].outcome = "dismissed"
        a.state = "denied"
        turn.steps.append(StepRecord(kind="note", tool="approval", why="작가가 넣지 않았어요"))
    turn.end = "done"
    turn.ended = _now()
    for x in turn.steps:
        x.result = ""


def undo(p: Project, rec: WriteRecord, items: list[WriteItem]) -> tuple[list[str], list[str], list[str]]:
    """넣은 후보를 되돌린다 (수정 기록의 되돌리기와 같다). 그 뒤에 같은 자리를 또 고쳤으면 남기고 까닭을 적는다."""
    done, kept, why = [], [], []
    try:
        pipeline.undo_edit(p, rec.episode, rec.edit)
    except (ValueError, KeyError) as e:
        reason = str(e).strip("'")
        for x in items:
            x.state, x.reason = "kept", reason
            kept.append(x.label)
            why.append(reason)
    else:
        for x in items:
            x.state = "reverted"
            done.append(x.label)
    return done, kept, why
