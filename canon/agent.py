"""대화 에이전트: 대화로 다듬기를 세션 단위로 두고, AI 가 한 턴에 도구를 몇 번 불러 읽고 고친다.

- 세션(AgentSession)은 주제마다 여럿이고, 기본 대상(ChatScope.target)과 권한 모드를 기억한다.
- 한 턴은 백그라운드 작업(jobs.start)으로 돈다. 단계마다 llm.json(PlotAgentStep) 을 한 번 부르고, 그 결과를 저장해 화면이 단계를 본다.
- 쓰기는 권한 모드 안이면 바로 저장하고(WriteRecord, 되돌리기 가능), 밖이면 승인 카드(Approval)를 남기고 턴을 끝낸다.
  막힌 것(본문이 있는 화)은 clean_revision 이 빼고, 까닭을 단계 결과로 AI 에게 돌려준다.
- 쓰기는 지금 적용 함수(pipeline.plot_apply · apply_revision)와 정리 함수(clean_revision)를 감싸기만 한다. 새 계산은 없다.
지금은 플롯 대화(topic 'plot')만 에이전트로 돈다. 설정 · 문체 · 본문 대화는 옛 단발 대화(chat_send)를 쓴다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from . import cancel, context, jobs, pipeline, prompts, store
from .llm import LLM, dump
from .schema import (AgentSession, AgentTurn, Approval, AskCard, ChatScope, PlotAgentStep, PlotRevision, Project, StepRecord,
                     WriteItem, WriteRecord)

TOPICS = ("plot",)
MAX_STEPS = 8  # 한 번 돌 때 부르는 단계 수. 닿으면 '이어 하기'로 같은 턴을 이어 간다
RESULT_LIMIT = 2500  # 읽기 도구 결과 글자 예산 (프롬프트가 단계마다 커지지 않게)
TITLE_LIMIT = 24
MODE_LABELS = {"ask": "물어보기", "draft": "빈 곳 · 초안만 자동", "all": "모두 자동"}
# 쓰기 한 부분의 종류. '빈 곳 · 초안만 자동'은 draft · next 만 바로 쓰고 나머지는 묻는다
KIND_LABELS = {"draft": "초안 화", "next": "다음 아크 초안", "confirmed": "확정한 화", "arc": "아크 칸", "acts": "구간 · 범위", "parts": "부 구성"}
DRAFT_KINDS = ("draft", "next")
READ_TOOLS = ("read_plots", "read_summaries", "find_text", "read_cast")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- 세션 ----------

def sessions(p: Project, topic: str) -> list[AgentSession]:
    return [s for s in p.agent_sessions if s.topic == topic]


def session(p: Project, sid: str) -> AgentSession:
    s = next((x for x in p.agent_sessions if x.id == sid), None)
    if s is None:
        raise KeyError("대화 세션이 없어요")
    return s


def turn_of(p: Project, sid: str, t: int) -> tuple[AgentSession, AgentTurn]:
    s = session(p, sid)
    if not 0 <= t < len(s.turns):
        raise KeyError("대화 턴이 없어요")
    return s, s.turns[t]


def new_session(p: Project, topic: str, target: str = "", title: str = "") -> AgentSession:
    if topic not in TOPICS:
        raise ValueError(f"대화 에이전트가 아직 없는 주제예요: {topic}")
    target, _ = pipeline.chat_target(p, target)
    s = AgentSession(id=uuid.uuid4().hex[:10], topic=topic, title=title.strip()[:60], target=target, created=now(), updated=now())
    p.agent_sessions.append(s)
    return s


def update_session(p: Project, sid: str, *, title: str | None = None, mode: str | None = None,
                   target: str | None = None, archived: bool | None = None) -> AgentSession:
    s = session(p, sid)
    if title is not None:
        s.title = title.strip()[:60]
    if mode is not None:
        if mode not in MODE_LABELS:
            raise ValueError(f"모르는 권한 모드예요: {mode}")
        s.mode = mode  # type: ignore[assignment]
    if target is not None:
        s.target, _ = pipeline.chat_target(p, target)
    if archived is not None:
        s.archived = archived
    s.updated = now()
    return s


def legacy_count(p: Project, topic: str) -> int:
    """옛 단발 대화(Project.chats) 메시지 수. 화면은 '이전 대화'로 보여 준다."""
    return len(next((c.messages for c in p.chats if c.topic == topic), []))


def scope_of(p: Project, s: AgentSession, turn: AgentTurn) -> ChatScope:
    target, _ = pipeline.chat_target(p, s.target)
    draft = turn.draft
    if target == "next" and draft is not None and draft.arc.start_ep != pipeline.next_arc_start(p):
        draft = None  # 그 사이 아크가 붙어 초안 자리가 맞지 않는다
    return ChatScope(target=target, act=turn.act, episode=turn.episode, mode="options" if turn.mode == "options" else "", draft=draft)


def add_turn(p: Project, sid: str, message: str, *, mode: str = "", act: str = "", episode: int = 0, draft=None) -> int:
    """새 턴을 연다. 돌아가는 턴이나 승인을 기다리는 턴이 있으면 막는다. 턴 번호를 돌려준다."""
    s = session(p, sid)
    message = message.strip()
    if not message:
        raise ValueError("메시지가 비었어요")
    if s.archived:
        raise ValueError("보관한 세션이에요. 꺼낸 뒤 이어서 말하세요")
    if s.turns and s.turns[-1].end == "":
        raise ValueError("아직 돌아가는 턴이 있어요")
    turn = AgentTurn(user=message, mode="options" if mode == "options" else "", act=act, episode=episode, draft=draft, at=now())
    turn.where = pipeline.chat_where(p, scope_of(p, s, turn))
    if s.turns and s.turns[-1].approval and s.turns[-1].approval.state == "wait":
        s.turns[-1].approval.state = "denied"  # 답하지 않고 새로 말하면 묻던 쓰기는 하지 않는다
        s.turns[-1].steps.append(StepRecord(kind="note", tool="approval", why="작가가 답하지 않고 새로 말해서 쓰지 않았어요"))
    if not s.title:
        s.title = message.splitlines()[0][:TITLE_LIMIT]
    s.turns.append(turn)
    s.updated = now()
    return len(s.turns) - 1


def reconcile(p: Project) -> bool:
    """돌아가는 중으로 남았지만 작업이 없는 턴(멈춤 · 오류 · 서버 재시작)을 끝낸다. 바뀐 것이 있으면 True."""
    changed = False
    for s in p.agent_sessions:
        for t in s.turns:
            if t.end:
                continue
            j = jobs.get(t.job) if t.job else None
            if j is not None and j.status == "running":
                continue
            if j is not None and j.status == "error":
                t.end, t.error = "error", j.error
            elif j is None and t.job:
                t.end, t.error = "stopped", "서버가 다시 시작돼 멈췄어요"
            elif j is None:
                continue  # 작업을 띄우기 직전이다
            else:
                t.end = "stopped" if j.status == "cancelled" else "done"
            _strip(t)
            changed = True
    return changed


def _strip(t: AgentTurn) -> None:
    """끝난 턴의 단계 결과는 다음 프롬프트에 넣지 않으므로 지워 project.json 이 커지지 않게 한다."""
    for x in t.steps:
        x.result = ""


# ---------- 권한 ----------

def permit(s: AgentSession, kind: str) -> str:
    """'auto' (바로 쓴다) 또는 'ask' (작가에게 묻는다). 막힘은 정리 단계(clean_revision)가 따로 판정한다."""
    if s.mode == "all" or kind in s.auto_kinds:
        return "auto"
    if s.mode == "ask":
        return "ask"
    return "auto" if kind in DRAFT_KINDS else "ask"


def _parts(p: Project, rev: PlotRevision, target: str) -> list[tuple[str, str]]:
    """변경안을 쓰기 부분 (key, 종류) 으로 나눈다. 다음 아크 칸과 구조는 화면 초안 한 덩어리('draft')다."""
    _, focus = pipeline.chat_target(p, target)
    by_no = {e.plot.number: e for e in p.episodes}
    limit = p.planned_until() if p.serial else p.meta.target_episodes
    out: list[tuple[str, str]] = []
    if rev.parts:
        out.append(("parts", "parts"))
    if target == "next":
        if rev.arc.title:
            out.append(("draft", "next"))
    else:
        if rev.arc.title:
            out.append(("arc", "arc"))
        if rev.acts:
            out.append(("acts", "acts"))
    for e in rev.episodes:
        cur = by_no.get(e.number)
        if e.number > limit:
            kind = "acts"  # 화수나 범위를 늘려야 생기는 화는 구조와 함께 간다
        elif cur and cur.status == "confirmed":
            kind = "confirmed"
        else:
            kind = "draft"
        out.append((str(e.number), kind))
    return out


def _groups(p: Project, rev: PlotRevision, target: str, keys: list[str]) -> list[str]:
    """함께 써야 하는 부분을 묶는다: 끝 화가 바뀌는 아크 칸과 구조, 구조와 범위 밖 화."""
    _, focus = pipeline.chat_target(p, target)
    keys = list(keys)
    if focus and rev.arc.end_ep and ({"arc", "acts"} & set(keys)):
        keys += [k for k in ("arc", "acts") if k not in keys and (k != "acts" or rev.acts)]
    return keys


def label(p: Project, key: str, target: str) -> str:
    _, focus = pipeline.chat_target(p, target)
    if key.isdigit():
        return f"{key}화 플롯"
    return {"parts": "부 구성", "draft": "다음 아크 초안",
            "arc": f"아크 {focus.number} 칸" if focus else "아크 칸",
            "acts": f"아크 {focus.number} 기승전결" if focus else "기승전결 구조"}.get(key, key)


# ---------- 도구 ----------

def _range(p: Project, args: dict[str, str]) -> tuple[int, int]:
    def num(k: str, d: int) -> int:
        try:
            return int(str(args.get(k, "")).strip().rstrip("화") or d)
        except ValueError:
            return d
    last = max([e.plot.number for e in p.episodes] or [1])
    a, b = num("from", 1), num("to", last)
    return min(a, b), max(a, b)


def _cut(text: str) -> str:
    return text if len(text) <= RESULT_LIMIT else text[:RESULT_LIMIT] + f"\n… (예산 {RESULT_LIMIT}자에서 잘랐어요)"


def read(p: Project, tool: str, args: dict[str, str]) -> tuple[str, str]:
    """읽기 도구. (화면에 보일 대상, AI 에게 줄 결과)."""
    if tool == "read_plots":
        a, b = _range(p, args)
        eps = [{"status": e.status, **e.plot.model_dump()} for e in p.episodes if a <= e.plot.number <= b]
        return f"{a}~{b}화", _cut(dump(eps)) if eps else "그 범위에 플롯이 없어요"
    if tool == "read_summaries":
        a, b = _range(p, args)
        lines = [f"{e.plot.number}화: {e.summary}" for e in p.episodes if a <= e.plot.number <= b and e.summary]
        return f"{a}~{b}화", _cut("\n".join(lines)) if lines else "그 범위에 쓴 화가 없어요"
    if tool == "find_text":
        q = str(args.get("query", "")).strip()
        written = [e.plot.number for e in p.episodes if e.text]
        if not q or not written:
            return f"«{q}»", "찾을 말이 없거나 쓴 본문이 없어요"
        hits = context.recall(p, max(written) + 1, q, RESULT_LIMIT, set())
        out = "\n".join(f"[{n}화] {x}" for n, paras in hits for x in paras)
        return f"«{q}» · {len(hits)}개 화", _cut(out) if out else "겹치는 단락이 없어요"
    if tool == "read_cast":
        ids = [x.strip() for x in str(args.get("ids", "")).split(",") if x.strip()]
        chars = [c for c in p.characters if c.id in ids or c.name in ids] or p.characters
        return ", ".join(c.name for c in chars[:4]) + (f" 외 {len(chars) - 4}명" if len(chars) > 4 else ""), _cut(dump(chars))
    raise KeyError(tool)


def _write(p: Project, s: AgentSession, rev: PlotRevision, target: str, keys: list[str]) -> WriteRecord:
    """고른 부분(keys)을 쓴다. 다음 아크 초안('draft')은 작품을 바꾸지 않고 기록만 해 화면이 초안에 놓는다."""
    keys = _groups(p, rev, target, keys)
    eps = [int(k) for k in keys if k.isdigit()]
    rec = WriteRecord(target=target, revision=rev.model_copy(deep=True))
    if eps or {"acts", "arc", "parts"} & set(keys):
        done, before, after = pipeline.plot_apply(p, rev, target, "acts" in keys, eps, arc="arc" in keys, parts="parts" in keys)
        rec.items = [WriteItem(key=k, label=label(p, k, target)) for k in done]
        rec.before, rec.after = (before, after) if done else (None, None)
    if "draft" in keys:
        rec.items.append(WriteItem(key="draft", label=label(p, "draft", target)))
    return rec


def edit_plot(p: Project, s: AgentSession, turn: AgentTurn, edit: PlotRevision) -> list[StepRecord]:
    """edit_plot 도구: 정리한 뒤 권한 안의 부분은 바로 쓰고, 밖의 부분은 승인 카드로 남긴다. 단계 기록을 돌려준다."""
    scope = scope_of(p, s, turn)
    target = scope.target
    raw = [e.number for e in edit.episodes]
    rev = pipeline.clean_revision(p, edit.model_copy(deep=True), scope.model_copy(update={"mode": ""}))
    rev.options = []
    kept = {e.number for e in rev.episodes}
    by_no = {e.plot.number: e for e in p.episodes}
    blocked = [n for n in raw if n not in kept]
    steps: list[StepRecord] = []
    parts = _parts(p, rev, target)
    auto = [k for k, kind in parts if permit(s, kind) == "auto"]
    ask = [k for k, kind in parts if k not in auto]
    linked = set(_groups(p, rev, target, ask))  # 함께 써야 하는 부분 하나라도 물으면 함께 묻는다
    auto = [k for k in auto if k not in linked]
    ask = [k for k, _ in parts if k not in auto]
    if auto:
        try:
            rec = _write(p, s, rev, target, auto)
        except ValueError as e:
            steps.append(StepRecord(kind="block", tool="edit_plot", label=", ".join(label(p, k, target) for k in auto),
                                    why=str(e), result=f"쓰지 못했어요: {e}"))
        else:
            if rec.items:
                turn.writes.append(rec)
                names = ", ".join(i.label for i in rec.items)
                steps.append(StepRecord(kind="write", tool="edit_plot", label=names, why="권한 안이라 바로 썼어요",
                                        result=f"바로 저장함: {names}"))
    if blocked:
        why = ", ".join(f"{n}화({'본문이 있음' if n in by_no and by_no[n].status in pipeline.LOCKED else '범위 밖'})" for n in blocked)
        steps.append(StepRecord(kind="block", tool="edit_plot", label=", ".join(f"{n}화" for n in blocked),
                                why=f"바꿀 수 없어요: {why}", result=f"막힘: {why}. 본문이 있는 화는 대화로 바꿀 수 없어요"))
    if ask:
        kinds = sorted({kind for k, kind in parts if k in ask})
        turn.approval = Approval(target=target, revision=rev, keys=ask, kinds=kinds)
        names = ", ".join(label(p, k, target) for k in ask)
        steps.append(StepRecord(kind="wait", tool="edit_plot", label=names,
                                why=f"{' · '.join(KIND_LABELS[k] for k in kinds)}은(는) 물어보고 바꿔요",
                                result=f"작가에게 물음: {names}. 작가의 답을 기다려야 하므로 턴을 끝냅니다"))
    if not steps:
        steps.append(StepRecord(kind="note", tool="edit_plot", why="바뀌는 것이 없어요", result="바뀌는 것이 없어요"))
    return steps


# ---------- 한 턴 ----------

def _edit(name: str, fn):
    """잠그고, 다시 읽고, 고치고, 저장한다 (web._edit 와 같다). 저장 전에 멈춤 신호를 본다."""
    with jobs.project_lock(name):
        p = store.load(name)
        out = fn(p)
        cancel.check()
        store.save(name, p)
    return out


def _step(p: Project, sid: str, t: int, step: PlotAgentStep) -> str:
    """AI 의 한 단계를 처리해 턴에 남긴다. 턴을 끝내면 끝 상태를 돌려준다 ('' 이면 다음 단계)."""
    s, turn = turn_of(p, sid, t)
    args = {a.name: a.value for a in step.args}
    tool = step.tool.strip()
    end = ""
    if not tool:
        turn.reply = step.reply.strip() or step.thought.strip()
        end = "done"
    elif tool == "ask":
        turn.ask = AskCard(question=step.question.strip(), options=step.options[:4])
        turn.reply = step.reply.strip() or step.question.strip()
        turn.steps.append(StepRecord(kind="ask", tool="ask", label=f"방향 {len(turn.ask.options)}안" if turn.ask.options else "되물음",
                                     why="고를 때까지 쓰지 않아요"))
        end = "ask"
    elif tool in READ_TOOLS:
        where, result = read(p, tool, args)
        turn.steps.append(StepRecord(kind="read", tool=tool, label=where, why=step.thought.strip(), result=result))
    elif tool == "edit_plot":
        turn.steps += edit_plot(p, s, turn, step.edit)
        if turn.approval and turn.approval.state == "wait":
            turn.reply = step.reply.strip() or step.edit.reply.strip() or step.thought.strip()
            end = "wait"
    else:
        turn.steps.append(StepRecord(kind="note", tool=tool, why="없는 도구예요", result=f"{tool} 라는 도구는 없어요. [도구] 목록에서 고르세요"))
    if end:
        turn.end = end  # type: ignore[assignment]
        if end in ("done", "ask"):
            _strip(turn)
    s.updated = now()
    return end


def run_turn(llm: LLM, name: str, sid: str, t: int, job=None) -> dict:
    """t 번째 턴을 MAX_STEPS 단계까지 돌린다. 단계마다 저장해 화면이 진행을 본다. 끝 상태를 돌려준다."""
    for i in range(MAX_STEPS):
        cancel.check()
        p = store.load(name)
        s, turn = turn_of(p, sid, t)
        scope = scope_of(p, s, turn)
        hint = {**pipeline.plot_chat_hint(p, turn.user, scope), "agent": True, "mode": turn.mode,
                "steps": [x.kind for x in turn.steps], "tools": [x.tool for x in turn.steps]}
        step = llm.json(prompts.SYSTEM_AGENT_PLOT, prompts.agent_plot_prompt(p, s, turn, scope, MAX_STEPS - i), PlotAgentStep, hint=hint)
        end = _edit(name, lambda q: _step(q, sid, t, step))
        if job is not None:
            job.done = i + 1
            job.note = step.thought[:60]
        if end:
            return {"end": end, "steps": i + 1}

    def cap(q: Project) -> None:
        _, tq = turn_of(q, sid, t)
        tq.end = "cap"
    _edit(name, cap)
    return {"end": "cap", "steps": MAX_STEPS}


def resume(p: Project, sid: str, t: int, note: StepRecord | None = None) -> None:
    """승인 · 거절 · 이어 하기 뒤 같은 턴을 다시 돌릴 수 있게 연다."""
    s, turn = turn_of(p, sid, t)
    if turn.end not in ("wait", "cap", "stopped", "error"):
        raise ValueError("이어 할 수 있는 턴이 아니에요")
    if s.turns[-1] is not turn:
        raise ValueError("마지막 턴만 이어 할 수 있어요")
    if note:
        turn.steps.append(note)
    turn.end, turn.error = "", ""


def decide(p: Project, sid: str, t: int, approve: bool, picked: list[str], remember: bool = False) -> None:
    """승인 카드에 답한다. 승인하면 고른 부분을 쓰고, 같은 턴을 이어 가도록 연다 (resume)."""
    s, turn = turn_of(p, sid, t)
    a = turn.approval
    if a is None or a.state != "wait" or turn.end != "wait":
        raise ValueError("답할 승인 카드가 없어요")
    if approve:
        keys = [k for k in picked if k in a.keys] if picked else list(a.keys)
        if not keys:
            raise ValueError("쓸 부분을 고르세요")
        rec = _write(p, s, a.revision, a.target, keys)  # 쓰지 못하면 ValueError 로 카드를 그대로 둔다
        if rec.items:
            turn.writes.append(rec)
        if remember:
            s.auto_kinds = sorted(set(s.auto_kinds) | set(a.kinds))
        a.state, a.picked = "approved", [i.key for i in rec.items]
        names = ", ".join(i.label for i in rec.items) or "없음"
        note = StepRecord(kind="note", tool="approval", label=names, why="작가가 승인했어요", result=f"작가가 승인해 저장함: {names}")
    else:
        a.state = "denied"
        note = StepRecord(kind="note", tool="approval", why="작가가 거절했어요", result="작가가 거절해 쓰지 않았어요. 다른 방법을 말하거나 끝냅니다")
    resume(p, sid, t, note)


def undo(p: Project, sid: str, t: int, w: int | None = None, key: str | None = None) -> tuple[list[str], list[str], list[str]]:
    """바로 쓴 것을 되돌린다. w · key 를 주면 그 부분만, 없으면 그 턴 전체를 뒤에서부터.
    지금 값이 쓴 직후 값과 같은 부분만 돌린다 (pipeline.plot_undo). (되돌린 이름, 남긴 이름, 남긴 까닭)."""
    _, turn = turn_of(p, sid, t)
    if w is not None and not 0 <= w < len(turn.writes):
        raise KeyError("쓴 기록이 없어요")
    recs = [turn.writes[w]] if w is not None else list(reversed(turn.writes))
    done_l: list[str] = []
    kept_l: list[str] = []
    why_l: list[str] = []
    for rec in recs:
        items = [i for i in rec.items if i.state == "done" and (key is None or i.key == key)]
        if not items:
            continue
        keys = [i.key for i in items if i.key != "draft"]
        done, kept, why = pipeline.plot_undo(p, keys, rec.before, rec.after) if keys and rec.before and rec.after else ([], [], [])
        reasons = dict(zip(kept, why))
        for i in items:
            if i.key == "draft" or i.key in done:
                i.state = "reverted"
                done_l.append(i.label)
            elif i.key in reasons:
                i.state, i.reason = "kept", reasons[i.key]
                kept_l.append(i.label)
                why_l.append(reasons[i.key])
    if not (done_l or kept_l):
        raise ValueError("되돌릴 것이 없어요")
    return done_l, kept_l, why_l
