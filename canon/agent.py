"""대화 에이전트: 대화로 다듬기를 세션 단위로 두고, AI 가 한 턴에 도구를 몇 번 불러 읽고 고친다.

- 세션(AgentSession)은 작품 하나에 목록 하나다(새 세션 topic 'agent', 옛 'plot' 세션도 같은 목록). 대상(target)과 권한 모드를 기억한다.
- 대상은 화면이 정한다(집필 · 검수 · 상태 승인 'text:N', 설정 도우미 'setup', 문체 'style', 그 밖 ''). 턴을 보낼 때 화면 대상이 오면
  세션 대상을 그 값으로 바꾸고, 작가가 고정(pinned)한 세션은 바꾸지 않는다.
- 한 턴은 백그라운드 작업(jobs.start)으로 돈다. 단계마다 llm.json(PlotAgentStep) 을 한 번 부르고, 그 결과를 저장해 화면이 단계를 본다.
- 쓰기는 권한 모드 안이면 바로 저장하고(WriteRecord, 되돌리기 가능), 밖이면 승인 카드(Approval)를 남기고 턴을 끝낸다.
  막힌 것(본문이 있는 화)은 clean_revision 이 빼고, 까닭을 단계 결과로 AI 에게 돌려준다.
- 쓰기는 지금 적용 함수(pipeline.plot_apply · apply_revision)와 정리 함수(clean_revision)를 감싸기만 한다. 새 계산은 없다.
- 늘 카드로 묻는 도구(CARD_TOOLS, 본문 고치기 agent_text 등)는 몸통을 제 파일에 두고 여기에는 등록 줄만 둔다. 권한 모드와 상관없이 묻는다(ALWAYS_ASK).
  재료나 빠른 요청이 붙은 턴은 에이전트 단계 없이 그 도구를 바로 부른다(지름길, AI 호출 한 번).
대상이 본문 · 설정 · 문체이면 플롯 쓰기는 모두 '다듬을 곳 밖'으로 묻는다.
설정 · 문체 고치기는 04c · 04d 가 도구를 더할 때까지 옛 단발 대화(chat_send)도 쓴다. 옛 'AI에게 고치기' 대화도 그때까지 남긴다.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone

from . import cancel, context, jobs, pipeline, prompts, renumber, store, usage
from . import agent_text
from .llm import LLM, dump, out_cap, wait_cap
from .logline import josa
from .schema import (AgentAsk, AgentSession, AgentTurn, Approval, AskCard, ChatScope, PlotAgentStep, PlotRevision, Project, RenumberOp,
                     StepRecord, TextMaterial, WriteItem, WriteRecord)

TOPICS = ("agent", "plot")  # 'agent' 는 새 세션, 'plot' 은 옛 플롯 대화 세션. 둘 다 같은 목록에 보인다
OTHER_FOCUS = ("text", "setup", "style")  # 화면이 주는 대상 가운데 아직 쓰기 도구가 없는 것 (chat_focus 종류)
# 턴이 실어 오는 화면 이름: 웹 app.js drawApp 의 views 표와 작품 홈('home'). 모르는 이름은 '' (플롯 화면과 같다)로 받는다 (tests/test_agent_js.py)
SCREENS = ("abilities", "arc", "atlas", "auto", "branches", "brief", "cast", "causal", "check", "convert", "cue", "foreshadow",
           "home", "lines", "research", "review", "setup", "stage", "statwin", "style", "timeline", "tofix", "usage", "write")
PLOT_SCREENS = ("arc",)  # 플롯 화면 (구간 · 아크 · 화 플롯 페이지). 여기서는 작품 전체('') 대상도 지금 규칙 그대로다
MAX_STEPS = 8  # 한 번 돌 때 부르는 단계 수. 닿으면 '이어 하기'로 같은 턴을 이어 간다
RESULT_LIMIT = 2500  # 읽기 도구 결과 글자 예산 (프롬프트가 단계마다 커지지 않게)
TITLE_LIMIT = 24
MODE_LABELS = {"ask": "물어보기", "draft": "빈 곳 · 초안만 자동", "all": "모두 자동"}
# 쓰기 한 부분의 종류. '빈 곳 · 초안만 자동'은 draft · next 만 바로 쓰고 나머지는 묻는다
KIND_LABELS = {"draft": "초안 화", "next": "다음 아크 초안", "confirmed": "확정한 화", "arc": "아크 칸", "acts": "구간 · 범위", "parts": "부 구성",
               "renumber": "화 넣기 · 빼기", "outside": "다듬을 곳 밖", "text": "본문 고치기"}
DRAFT_KINDS = ("draft", "next")
READ_TOOLS = ("read_plots", "read_summaries", "find_text", "read_cast")
# 화 넣기 · 빼기. 뒤 화 번호(본문만 있고 반영하지 않은 화 포함, renumber.last_fixed)가 바뀌므로 권한 모드와 상관없이 늘 묻는다
RENUMBER_TOOLS = ("insert_episodes", "remove_episode")
# 늘 카드로 묻는 도구: 도구 이름 → 모듈 (agent_text.py 머리의 이름들을 둔다). 04c · 04d 는 한 줄씩 더한다
CARD_TOOLS = {m.TOOL: m for m in (
    agent_text,
)}
# 권한 모드('모두 자동' 포함)와 '이 세션에서 묻지 않기'(auto_kinds)를 따르지 않고 늘 묻는 쓰기 종류
ALWAYS_ASK = ("renumber", *(m.KIND for m in CARD_TOOLS.values()))
MAX_INSERT = 10  # 한 번에 넣는 새 화 수
# 한 단계의 AI 호출 한도. 보통 5~30초, 길어도 4분 남짓이다(2026-11-03 사용량 기록 13건, 가장 긴 것 263초).
# 응답이 없으면 STEP_WAIT 초 뒤 한 번 다시 부르고, 또 없으면 오류로 턴을 멈춘다 (llm.wait_cap)
STEP_WAIT = 300
# Claude Code(구독) 단계의 한도. 2026-11-05~09 서버의 claude-opus-5-5 high 단계 25건 중 3건이 300초에 끊겼다.
# Opus 출력은 초당 36~100토큰 남짓이라(출력 2천 토큰 넘는 호출 281건) STEP_OUT_TOKENS 를 다 쓰면 455초쯤 걸린다
STEP_WAIT_CLAUDE = 480
STEP_OUT_TOKENS = 16384  # 가장 긴 단계 출력은 생각 포함 약 9,100토큰이었다. 같은 글을 되풀이하면 여기서 끊는다
# 할 일을 예고만 하고 끝낸 답의 끝말. 2026-11-04 '아크 1을 서사 분석' 턴이 첫 단계에서 이 한 문장만 내고 끝났다
# ("…분석해 작가님께 전달합니다.", gemini-4-argon, 출력 81토큰). 이런 답은 한 번 되돌려 내용을 쓰게 한다
PREAMBLE_END = re.compile(r"(겠습니다|겠어요|드릴게요|할게요|드립니다|전달합니다|정리합니다|분석합니다|살펴봅니다|짚어 봅니다)[.!…\s]*$")
PREAMBLE_LIMIT = 300  # 이보다 긴 답은 내용이 있다고 본다
PREAMBLE_TOOL = "reply"  # 되돌린 단계의 도구 칸. 한 턴에 한 번만 되돌린다
EMPTY_ASK_TOOL = "ask_empty"  # 묻는 말도 방향 안도 없는 ask 를 되돌린 단계의 도구 칸. 한 턴에 한 번만
# 2026-11-04 같은 세션 다음 턴은 question · options · reply 가 모두 빈 ask 로 끝나(출력 86토큰), 작가는 답할 것이 없는 '되물음' 줄만 봤다
EMPTY_ASK_NOTE = ("방금 ask 에 묻는 말(question)도 방향 안(options)도 없어 작가에게 보일 것이 없어요. "
                  "물을 것이 있으면 question 을 채워 다시 ask 를 부르고, 없으면 tool 을 비우고 reply 에 답을 바로 다 쓰세요")
EMPTY_ASK_REPLY = "AI가 묻는 말을 비운 채 멈췄어요. 같은 요청을 다시 보내거나 더 구체적으로 말해 주세요."
# 도구 이름만 있고 변경안(edit)이 빈 edit_plot. 2026-11-04 gemini-4-argon 이 같은 단계 프롬프트에 두 번 중 한 번
# {"thought", "tool": "edit_plot"} 만 내고 끝냈다(finish STOP). 같은 턴의 실제 단계는 같은 꼴의 빈 ask 였다
EMPTY_EDIT_TOOL = "edit_empty"
EMPTY_EDIT_NOTE = ("방금 tool 은 edit_plot 인데 edit 칸이 비어 바꿀 것이 없어요. 도구를 고르면 같은 응답 안에서 그 도구의 칸을 채웁니다. "
                   "edit 에 바꿀 것(episodes, acts, arc, parts 중 필요한 것)을 채워 다시 edit_plot 을 부르거나, 방향을 정하지 못했으면 ask 로 물으세요")
PREAMBLE_NOTE = ("방금 reply 는 할 일을 예고만 했어요. 작가는 그 내용을 기다리고, 이 답이 턴의 마지막 말이 됩니다. "
                 "분석 · 검토 · 답을 reply 에 바로 다 쓰세요. 더 읽을 것이 있으면 읽기 도구를 먼저 부르세요")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- 세션 ----------

def sessions(p: Project, topic: str = "agent") -> list[AgentSession]:
    """세션 목록. 'agent' · 'plot' 은 작품 하나의 같은 목록이다 (옛 project.json 의 plot 세션도 보인다)."""
    if topic in TOPICS:
        return [s for s in p.agent_sessions if s.topic in TOPICS]
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


def new_session(p: Project, topic: str = "agent", target: str = "", title: str = "", pinned: bool = False) -> AgentSession:
    if topic not in TOPICS:
        raise ValueError(f"대화 에이전트가 아직 없는 주제예요: {topic}")
    target = pipeline.chat_session_target(p, target)
    s = AgentSession(id=uuid.uuid4().hex[:10], topic=topic, title=title.strip()[:60], target=target, pinned=pinned, created=now(), updated=now())
    p.agent_sessions.append(s)
    return s


def update_session(p: Project, sid: str, *, title: str | None = None, mode: str | None = None,
                   target: str | None = None, archived: bool | None = None, pinned: bool | None = None) -> AgentSession:
    s = session(p, sid)
    if title is not None:
        s.title = title.strip()[:60]
    if mode is not None:
        if mode not in MODE_LABELS:
            raise ValueError(f"모르는 권한 모드예요: {mode}")
        s.mode = mode  # type: ignore[assignment]
    if target is not None:
        s.target = pipeline.chat_session_target(p, target)
    if archived is not None:
        s.archived = archived
    if pinned is not None:
        s.pinned = pinned
    s.updated = now()
    return s


def legacy_count(p: Project, topic: str) -> int:
    """옛 단발 대화(Project.chats) 메시지 수. 화면은 '이전 대화'로 보여 준다. 에이전트 목록('agent')의 이전 대화는 옛 플롯 대화다."""
    topic = "plot" if topic in TOPICS else topic
    return len(next((c.messages for c in p.chats if c.topic == topic), []))


def legacy_chats(p: Project) -> list[tuple[str, int]]:
    """설정 · 문체 · 본문 고치기의 옛 대화 (주제, 메시지 수). 세션 목록 아래 '이전 대화'에 읽기 전용으로 보인다.
    차례는 설정 · 문체 · 화 번호 순이다. 메시지가 없는 주제는 뺀다."""
    def order(topic: str) -> tuple[int, int]:
        if topic.startswith("text:"):
            n = topic[5:]
            return 2, int(n) if n.isdigit() else 0
        return (0 if topic == "setup" else 1), 0
    out = [(c.topic, len(c.messages)) for c in p.chats
           if c.messages and (c.topic in ("setup", "style") or c.topic.startswith("text:"))]
    return sorted(out, key=lambda x: order(x[0]))


def scope_of(p: Project, s: AgentSession, turn: AgentTurn) -> ChatScope:
    target, _ = pipeline.chat_target(p, s.target)
    draft = turn.draft
    if target == "next" and draft is not None and draft.arc.start_ep != pipeline.next_arc_start(p):
        draft = None  # 그 사이 아크가 붙어 초안 자리가 맞지 않는다
    focus = s.target if pipeline.chat_focus(p, s.target)[0] else ""
    return ChatScope(target=target, focus=focus, act=turn.act, episode=turn.episode, mode="options" if turn.mode == "options" else "", draft=draft)


LAB_SID = "promptlab"  # first_step_prompt 의 세션 id. 이름 후보를 세션 id 로 뽑으므로 불러올 때마다 같은 글이 된다


def first_step_prompt(p: Project, message: str, target: str = "") -> str:
    """새 세션 첫 턴에서 run_turn 이 처음 보내는 요청 (프롬프트 놀이터 불러오기). 세션을 작품에 붙이지 않아 작품은 바뀌지 않는다."""
    s = AgentSession(id=LAB_SID, target=target)
    turn = AgentTurn(user=message.strip())
    turn.where = pipeline.chat_where(p, scope_of(p, s, turn))
    s.turns.append(turn)
    return prompts.agent_plot_prompt(p, s, turn, scope_of(p, s, turn), MAX_STEPS)


def add_turn(p: Project, sid: str, message: str, *, mode: str = "", act: str = "", episode: int = 0, draft=None,
             target: str | None = None, screen: str = "", selection: TextMaterial | None = None, preset: str = "") -> int:
    """새 턴을 연다. 돌아가는 턴이나 승인을 기다리는 턴이 있으면 막는다. 턴 번호를 돌려준다.
    target 은 화면이 주는 대상이다. 고정하지 않은 세션이면 세션 대상을 이 값으로 바꾼다.
    screen 은 작가가 보던 화면이다. SCREENS 에 없으면 '' (플롯 화면과 같다)로 남긴다.
    selection(재료: 고른 본문) · preset(빠른 요청)이 있으면 본문 고치기 도구를 바로 부른다 (agent_text.shortcut)."""
    s = session(p, sid)
    message = message.strip()
    if not message:
        raise ValueError("메시지가 비었어요")
    if s.archived:
        raise ValueError("보관한 세션이에요. 꺼낸 뒤 이어서 말하세요")
    if s.turns and s.turns[-1].end == "":
        raise ValueError("아직 돌아가는 턴이 있어요")
    if preset and preset not in prompts.PASSAGE_PRESETS:
        raise ValueError(f"모르는 빠른 요청이에요: {preset}")
    if preset and selection is None:
        raise ValueError("빠른 요청은 본문에서 고칠 부분을 골라 재료로 붙인 뒤 보내세요")
    if selection is not None:
        if not selection.text.strip():
            raise ValueError("고른 부분이 비었어요")
        p.episode(selection.episode)  # 없는 화면 KeyError
    if target is not None and not s.pinned:
        s.target = pipeline.chat_session_target(p, target)
    _compact(s)
    turn = AgentTurn(user=message, mode="options" if mode == "options" else "", act=act, episode=episode, draft=draft, at=now(),
                     screen=screen if screen in SCREENS else "", selection=selection, preset=preset)
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
            t.ended = t.ended or now()
            _strip(t)
            changed = True
    return changed


def _strip(t: AgentTurn) -> None:
    """끝난 턴의 단계 결과는 다음 프롬프트에 넣지 않으므로 지워 project.json 이 커지지 않게 한다."""
    for x in t.steps:
        x.result = ""


UNDO_TURNS = 20  # 세션마다 되돌리기 기록(쓰기 전 · 뒤 값)을 남기는 최근 턴 수
OLD_UNDO = "오래된 턴이라 되돌리기 기록을 지웠어요"


def _compact(s: AgentSession) -> None:
    """최근 UNDO_TURNS 턴보다 오래된 턴의 쓰기 전 · 뒤 값과 초안을 지운다. 세션이 길어져도 project.json 이 끝없이 커지지 않게 한다.
    턴 번호(화면 주소)는 그대로 두고, 그 턴의 아직 되돌리지 않은 부분은 kept 로 까닭을 적는다."""
    for t in s.turns[:-UNDO_TURNS]:
        t.draft = None
        for w in t.writes:
            if w.tool in CARD_TOOLS:
                continue  # 본문 고치기는 되돌리기 값이 수정 기록(Episode.edits)에 있어 이 턴에는 무겁게 남는 것이 없다
            for i in w.items:
                if i.state == "done":
                    i.state, i.reason = "kept", OLD_UNDO
            w.revision = w.before = w.after = None
            if w.op:
                w.op.removed_ep, w.op.inserted = None, []


# ---------- 권한 ----------

def permit(s: AgentSession, kind: str) -> str:
    """'auto' (바로 쓴다) 또는 'ask' (작가에게 묻는다). 막힘은 정리 단계(clean_revision)가 따로 판정한다. ALWAYS_ASK 종류는 늘 묻는다."""
    if kind in ALWAYS_ASK:
        return "ask"
    if kind == "outside":  # 세션이 고른 부 · 화 밖은 '모두 자동'이어도 묻는다 ('이 세션에서 묻지 않기'는 따른다)
        return "auto" if kind in s.auto_kinds else "ask"
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


def outside(p: Project, focus: str, key: str) -> bool:
    """세션이 고른 다듬을 곳(chat_focus) 밖의 쓰기 부분인지. 부를 고르면 그 부 밖의 화, 화를 고르면 그 화 말고 모두.
    대상이 본문 · 설정 · 문체이면 플롯 쓰기는 모두 밖이다 (플롯 도구는 어느 화면에서든 쓰지만 늘 묻는다)."""
    kind, lo, hi, _ = pipeline.chat_focus(p, focus)
    if not kind:
        return False
    if kind in OTHER_FOCUS:
        return True
    if key.isdigit():
        return not lo <= int(key) <= hi
    return kind == "ep"  # 부를 고르면 부 구성 · 그 부의 아크 칸 · 구조는 안이다


def off_plot(focus: str, turn: AgentTurn) -> bool:
    """플롯 화면 밖에서 작품 전체('')를 대상으로 보낸 턴인지. 그러면 플롯 쓰기는 모두 '다듬을 곳 밖'으로 묻는다
    (2026-11-09 사용자 결정, docs/ux/specs/04-one-agent.md 정할 것 7). 화면이 비었거나(옛 클라이언트) 플롯 화면이면 지금 규칙 그대로다."""
    return not focus and bool(turn.screen) and turn.screen not in PLOT_SCREENS


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
    away = off_plot(scope.focus, turn)
    parts = [(k, "outside" if away or outside(p, scope.focus, k) else kind) for k, kind in _parts(p, rev, target)]
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
        what = " · ".join(KIND_LABELS[k] for k in kinds)
        steps.append(StepRecord(kind="wait", tool="edit_plot", label=names,
                                why=f"{what}{josa(what, '은', '는')} 물어보고 바꿔요",
                                result=f"작가에게 물음: {names}. 작가의 답을 기다려야 하므로 턴을 끝냅니다"))
    if not steps:
        steps.append(StepRecord(kind="note", tool="edit_plot", why="바뀌는 것이 없어요", result="바뀌는 것이 없어요"))
    return steps


# ---------- 화 넣기 · 빼기 ----------

def _split(v: str) -> list[str]:
    return [x.strip() for x in str(v or "").replace("\n", "|").split("|")]


def op_from(tool: str, args: dict[str, str]) -> RenumberOp:
    """도구 인자를 화 넣기 · 빼기로 읽는다. insert_episodes: at, count, titles · summaries ('|' 로 나눔). remove_episode: n."""
    def num(k: str) -> int:
        try:
            return int(str(args.get(k, "")).strip().rstrip("화개"))
        except ValueError:
            raise ValueError(f"{k}에 화 번호를 숫자로 넣으세요") from None
    if tool == "remove_episode":
        return RenumberOp(kind="remove", at=num("n"))
    titles = [x for x in _split(args.get("titles", "")) if x]
    try:
        count = num("count") if str(args.get("count", "")).strip() else max(len(titles), 1)
    except ValueError:
        count = max(len(titles), 1)
    if not 1 <= count <= MAX_INSERT:
        raise ValueError(f"한 번에 1~{MAX_INSERT}화까지 넣을 수 있어요")
    summaries = _split(args.get("summaries", ""))
    return RenumberOp(kind="insert", at=num("at"), titles=(titles + [""] * count)[:count], summaries=(summaries + [""] * count)[:count])


def op_label(op: RenumberOp) -> str:
    if op.kind == "remove":
        return f"{op.at}화 빼기"
    c = len(op.titles)
    return f"{op.at}화 앞에 새 화 {c}개 넣기" if c > 1 else f"{op.at}화 앞에 새 화 넣기"


def shift(op: RenumberOp, inverse: bool = False):
    """이 동작이 옛 화 번호를 어디로 옮기는지 (autorun.renumber 에 넘긴다). inverse 는 되돌릴 때."""
    c = len(op.titles) if op.kind == "insert" else -1
    if inverse:
        c = -c
    at = op.at + (len(op.titles) if inverse and op.kind == "insert" else 0)
    return lambda x: x + c if x >= at else x


def dropped(op: RenumberOp, inverse: bool = False) -> list[int]:
    """이 동작이 빼는 옛 화 번호 (store.renumber_side_files 의 gone). 빼기는 그 화, 넣기를 되돌리면 넣었던 화들."""
    if op.kind == "remove":
        return [] if inverse else [op.at]
    return list(range(op.at, op.at + len(op.titles))) if inverse else []


def apply_op(p: Project, op: RenumberOp, move: bool) -> list[str]:
    """화를 넣거나 뺀다 (pipeline.insert_episode · remove_episode). 무엇을 옮겼는지 돌려준다. 못 하면 ValueError 로 p 는 그대로다."""
    if op.kind == "remove":
        ep = p.episode(op.at)
        plot, status, whole = ep.plot.model_copy(deep=True), ep.status, ep.model_copy(deep=True)
        notes = pipeline.remove_episode(p, op.at, move)
        op.removed, op.removed_status, op.removed_ep = plot, status, whole
    else:
        before = p.model_copy(deep=True)
        c = len(op.titles)
        texts = [e.plot.number for e in p.episodes if e.plot.number >= op.at and renumber.has_text(e)]
        q = p.model_copy(deep=True)
        for i, (t, s) in enumerate(zip(op.titles, op.summaries)):
            pipeline.insert_episode(q, op.at + i, t, s, move_text=move)
        for f in Project.model_fields:
            setattr(p, f, getattr(q, f))
        op.inserted = [p.episode(op.at + i).model_copy(deep=True) for i in range(c)]
        moved = [e.plot.number for e in before.episodes if e.plot.number >= op.at]
        head = f"{op.at}~{op.at + c - 1}화에 새 화 {c}개를 넣었어요." if c > 1 else f"{op.at}화에 새 화를 넣었어요."
        if moved:
            head += f" 원래 {moved[0]}~{moved[-1]}화는 {moved[0] + c}~{moved[-1] + c}화가 됐어요."
        notes = [head]
        if texts:
            notes.append(f"본문이 있는 {' · '.join(f'{n}화' for n in texts)}는 {' · '.join(f'{n + c}화' for n in texts)}가 됐어요. "
                         "본문 속 화 번호나 앞 화와 잇는 문장은 그대로라 검수로 다시 보세요.")
        notes += pipeline._renumber_notes(before, p, {})
    op.after_total = len(p.episodes)
    return notes


def preview(p: Project, op: RenumberOp, move: bool, held: list[int]) -> list[str]:
    """쓰지 않고 해 본다. 못 하면 ValueError. held 는 검토를 기다리는 결과가 있는 화 (store.pending_eps)."""
    stuck = [n for n in held if n >= op.at]
    if stuck:
        raise ValueError(f"{', '.join(f'{n}화' for n in stuck)}에 검토를 기다리는 AI 결과나 실패한 작업이 있어 화 번호를 옮길 수 없어요. "
                         "작가가 먼저 확인하거나 버려야 해요")
    return apply_op(p.model_copy(deep=True), op.model_copy(deep=True), move)


def inverse(p: Project, op: RenumberOp, move: bool) -> None:
    """쓴 화 넣기 · 빼기를 되돌린다. 그 뒤 화 번호가 바뀌었거나 넣은 화에 본문이 생겼으면 ValueError (p 는 그대로)."""
    if len(p.episodes) != op.after_total:
        raise ValueError("그 뒤에 화를 넣거나 빼서 번호가 달라졌어요")
    q = p.model_copy(deep=True)
    if op.kind == "insert":
        changed = [x.plot.number for x in op.inserted if p.episode(x.plot.number).model_dump() != x.model_dump()]
        if changed:
            raise ValueError(f"넣은 {', '.join(f'{n}화' for n in changed)}를 그 뒤에 고쳐서 되돌리지 않아요. 직접 빼 주세요")
        for i in reversed(range(len(op.titles))):
            pipeline.remove_episode(q, op.at + i, move)
    else:
        pipeline.insert_episode(q, op.at, move_text=move)
        e = q.episode(op.at)
        if op.removed_ep:  # 뺀 화 전체를 살린다 (스토리보드 · 큐 시트 · 장면 연출 · 고칠 곳 · 다 쓴 사건 체크)
            whole = op.removed_ep.model_copy(deep=True)
            whole.plot.number = op.at
            q.episodes[q.episodes.index(e)] = whole
        elif op.removed:
            e.plot = op.removed.model_copy(update={"number": op.at})
            e.status = op.removed_status or e.status  # type: ignore[assignment]
    for f in Project.model_fields:
        setattr(p, f, getattr(q, f))


def renumber_step(p: Project, turn: AgentTurn, tool: str, args: dict[str, str], move: bool, held: list[int]) -> bool:
    """화 넣기 · 빼기 도구: 해 보고 되면 승인 카드를 남긴다 (True: 턴을 끝내고 답을 기다린다). 안 되면 막힘 단계."""
    try:
        op = op_from(tool, args)
        op.notes = preview(p, op, move, held)
    except (ValueError, KeyError) as e:
        why = str(e).strip("'")
        turn.steps.append(StepRecord(kind="block", tool=tool, label=tool, why=why, result=f"할 수 없어요: {why}"))
        return False
    turn.approval = Approval(tool=tool, op=op, keys=["renumber"], kinds=["renumber"])
    turn.steps.append(StepRecord(kind="wait", tool=tool, label=op_label(op), why="화 번호가 바뀌어 늘 물어보고 해요",
                                 result=f"작가에게 물음: {op_label(op)}. 작가의 답을 기다려야 하므로 턴을 끝냅니다"))
    return True


# ---------- 한 턴 ----------

def _edit(name: str, fn):
    """잠그고, 다시 읽고, 고치고, 저장한다 (web._edit 와 같다). 저장 전에 멈춤 신호를 본다."""
    with jobs.project_lock(name):
        p = store.load(name)
        out = fn(p)
        cancel.check()
        store.save(name, p)
    return out


FILL_NOTE = ("\n\n[이번 단계] 도구 {tool} 을(를) 골랐습니다 (생각: {thought}). 이 도구의 칸만 채웁니다. {what}")
FILL_WHAT = {"ask": "작가에게 물을 question 과, 방향을 묻는다면 서로 다른 방향 options 2~3개를 채웁니다.",
             "edit_plot": "변경안을 [변경안 규칙]대로 채웁니다. reply 는 한 줄 설명입니다."}


def fill(llm: LLM, system: str, prompt: str, step: PlotAgentStep, hint: dict) -> PlotAgentStep:
    """도구 이름만 오고 그 도구의 칸이 빈 단계면, 그 칸만 담은 작은 형식으로 한 번 더 부른다 (같은 단계).
    2026-11-04 gemini-4-argon 이 부 대상 세션의 첫 단계를 6번 중 5번 {thought, tool} 만 내고 끝냈다(출력 86~157토큰).
    프롬프트에 '칸을 채운다'를 더해도 4번 모두 비었고, 같은 프롬프트 뒤에 AgentAsk 로 다시 부르니 2번 모두 묻는 말과
    방향 3안을 냈다. edit_plot 을 PlotRevision 으로 채우게 하면 방향 안(options)만 낼 때가 있어, 그때는 되묻기로 바꾼다."""
    tool = step.tool.strip()
    if (tool == "ask" and not step.question.strip() and not step.options) or (tool == "edit_plot" and empty_edit(step.edit)):
        cancel.say("AI가 빈 칸을 보내 그 칸만 한 번 더 받아요")  # 한 단계가 호출 두 번이 된다. 화면이 까닭을 보인다
        try:
            return _fill(llm, system, prompt, step, hint, tool)
        finally:
            cancel.say("")
    return step


def _fill(llm: LLM, system: str, prompt: str, step: PlotAgentStep, hint: dict, tool: str) -> PlotAgentStep:
    if tool == "ask":
        a = llm.json(system, prompt + FILL_NOTE.format(tool=tool, thought=step.thought.strip(), what=FILL_WHAT["ask"]), AgentAsk,
                     hint={**hint, "fill": "ask"})
        return step.model_copy(update={"question": a.question, "options": a.options, "reply": step.reply or a.reply})
    if tool == "edit_plot":
        rev = llm.json(system, prompt + FILL_NOTE.format(tool=tool, thought=step.thought.strip(), what=FILL_WHAT["edit_plot"]), PlotRevision,
                       hint={**hint, "fill": "edit"})
        if rev.options and empty_edit(rev.model_copy(update={"options": []})):
            return step.model_copy(update={"tool": "ask", "question": rev.reply.strip() or "어느 방향으로 갈까요?", "options": rev.options[:4],
                                           "reply": step.reply or rev.reply})
        return step.model_copy(update={"edit": rev})
    return step


def empty_edit(edit: PlotRevision) -> bool:
    """edit_plot 의 변경안에 바꿀 것이 하나도 없는지 (reply 말고 모든 칸이 기본값)."""
    return edit.model_dump(exclude={"reply"}) == PlotRevision(reply="").model_dump(exclude={"reply"})


def is_preamble(reply: str) -> bool:
    """답이 내용 없이 할 일을 예고만 하는지 ("…분석해 전달합니다", "…살펴보겠습니다")."""
    reply = reply.strip()
    return 0 < len(reply) <= PREAMBLE_LIMIT and bool(PREAMBLE_END.search(reply))


def _preamble_retry(turn: AgentTurn, reply: str) -> bool:
    """쓴 것도 물은 것도 없이 예고만 한 답이면 단계 줄을 남기고 True (턴을 끝내지 않는다). 한 턴에 한 번만."""
    if turn.writes or turn.approval or any(x.tool == PREAMBLE_TOOL for x in turn.steps) or not is_preamble(reply):
        return False
    turn.steps.append(StepRecord(kind="note", tool=PREAMBLE_TOOL, why="예고만 해서 내용을 다시 청했어요", result=PREAMBLE_NOTE))
    return True


def _step(p: Project, sid: str, t: int, step: PlotAgentStep, move: bool = True, held: list[int] | None = None, prepared=None) -> str:
    """AI 의 한 단계를 처리해 턴에 남긴다. 턴을 끝내면 끝 상태를 돌려준다 ('' 이면 다음 단계).
    move · held 는 화 넣기 · 빼기에 쓴다 (store.shares_text 의 반대, store.pending_eps).
    prepared 는 늘 카드로 묻는 도구가 잠금 밖에서 만든 결과다 (CARD_TOOLS 의 prepare)."""
    s, turn = turn_of(p, sid, t)
    args = {a.name: a.value for a in step.args}
    tool = step.tool.strip()
    end = ""
    if not tool:
        reply = step.reply.strip() or step.thought.strip()
        if not _preamble_retry(turn, reply):
            turn.reply = reply
            end = "done"
    elif tool == "ask" and not step.question.strip() and not step.options:
        reply = step.reply.strip()
        if reply and not is_preamble(reply):
            turn.reply, end = reply, "done"  # 묻는 꼴만 빌린 답이다
        elif not any(x.tool == EMPTY_ASK_TOOL for x in turn.steps):
            turn.steps.append(StepRecord(kind="note", tool=EMPTY_ASK_TOOL, why="묻는 말이 비어 다시 청했어요", result=EMPTY_ASK_NOTE))
        else:
            turn.reply, end = reply or EMPTY_ASK_REPLY, "done"
    elif tool == "ask":
        turn.ask = AskCard(question=step.question.strip(), options=step.options[:4])
        turn.reply = step.reply.strip() or step.question.strip()
        turn.steps.append(StepRecord(kind="ask", tool="ask", label=f"방향 {len(turn.ask.options)}안" if turn.ask.options else "되물음",
                                     why="고를 때까지 쓰지 않아요"))
        end = "ask"
    elif tool in READ_TOOLS:
        where, result = read(p, tool, args)
        turn.steps.append(StepRecord(kind="read", tool=tool, label=where, why=step.thought.strip(), result=result))
    elif tool in CARD_TOOLS:
        end = CARD_TOOLS[tool].record(p, s, turn, step, prepared)
    elif tool in RENUMBER_TOOLS:
        if renumber_step(p, turn, tool, args, move, held or []):
            turn.reply = step.reply.strip() or step.thought.strip()
            end = "wait"
    elif tool == "edit_plot" and empty_edit(step.edit):
        if not any(x.tool == EMPTY_EDIT_TOOL for x in turn.steps):
            turn.steps.append(StepRecord(kind="note", tool=EMPTY_EDIT_TOOL, why="고칠 내용이 비어 다시 청했어요", result=EMPTY_EDIT_NOTE))
        else:
            turn.steps.append(StepRecord(kind="note", tool="edit_plot", why="바뀌는 것이 없어요", result="바뀌는 것이 없어요"))
    elif tool == "edit_plot":
        turn.steps += edit_plot(p, s, turn, step.edit)
        if turn.approval and turn.approval.state == "wait":
            turn.reply = step.reply.strip() or step.edit.reply.strip() or step.thought.strip()
            end = "wait"
    else:
        turn.steps.append(StepRecord(kind="note", tool=tool, why="없는 도구예요", result=f"{tool} 라는 도구는 없어요. [도구] 목록에서 고르세요"))
    if end:
        turn.end = end  # type: ignore[assignment]
        turn.ended = now()
        if end in ("done", "ask"):
            _strip(turn)
    s.updated = now()
    return end


def card_shortcut(turn: AgentTurn) -> PlotAgentStep | None:
    """지름길: 재료나 빠른 요청이 붙은 턴의 첫 단계를 에이전트 대신 정한다 (AI 를 부르지 않는다)."""
    if turn.steps:
        return None
    for m in CARD_TOOLS.values():
        if (step := m.shortcut(turn)) is not None:
            return step
    return None


def step_wait(llm: LLM) -> float:
    """한 단계 호출을 기다리는 초. Claude Code(구독)는 STEP_WAIT_CLAUDE, 나머지는 STEP_WAIT."""
    return STEP_WAIT_CLAUDE if usage.backend_of(llm) == "claude" else STEP_WAIT


def run_turn(llm: LLM, name: str, sid: str, t: int, job=None) -> dict:
    """t 번째 턴을 MAX_STEPS 단계까지 돌린다. 단계마다 저장해 화면이 진행을 본다. 끝 상태를 돌려준다."""
    for i in range(MAX_STEPS):
        cancel.check()
        p = store.load(name)
        s, turn = turn_of(p, sid, t)
        if job is not None:
            job.step_at, job.step_wait = time.time(), step_wait(llm)
        step = card_shortcut(turn)
        if step is None:
            scope = scope_of(p, s, turn)
            hint = {**pipeline.plot_chat_hint(p, turn.user, scope), "agent": True, "mode": turn.mode, "aim": pipeline.chat_focus(p, scope.focus)[0],
                    "steps": [x.kind for x in turn.steps], "tools": [x.tool for x in turn.steps]}
            prompt = prompts.agent_plot_prompt(p, s, turn, scope, MAX_STEPS - i)
            with wait_cap(step_wait(llm)), out_cap(STEP_OUT_TOKENS):
                step = llm.json(prompts.SYSTEM_AGENT_PLOT, prompt, PlotAgentStep, hint=hint)
                step = fill(llm, prompts.SYSTEM_AGENT_PLOT, prompt, step, hint)
        prepared = None
        if (card := CARD_TOOLS.get(step.tool.strip())) is not None:
            with wait_cap(step_wait(llm)):  # 도구가 부르는 AI(본문 고치기는 단계 'revise'). 잠금 밖에서 부른다
                prepared = card.prepare(name, p, s, turn, step)
            cancel.check()
        move, held = not store.shares_text(name), store.pending_eps(name)
        end = _edit(name, lambda q: _step(q, sid, t, step, move, held, prepared))
        if job is not None:
            job.done = i + 1
            job.note = step.thought[:60]
        if end:
            return {"end": end, "steps": i + 1}

    def cap(q: Project) -> None:
        _, tq = turn_of(q, sid, t)
        tq.end = "cap"
        tq.ended = now()
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


def decide(p: Project, sid: str, t: int, approve: bool, picked: list[str], remember: bool = False, move: bool = True,
           text: str | None = None) -> None:
    """승인 카드에 답한다. 승인하면 고른 부분을 쓰고, 같은 턴을 이어 가도록 연다 (resume).
    화 넣기 · 빼기 카드는 move 규칙(renumber.last_fixed)으로 쓴다.
    늘 카드로 묻는 도구(CARD_TOOLS)의 카드는 그 모듈의 decide 가 쓰고 턴을 끝낸다 (이어 돌리지 않는다). text 는 작가가 손본 후보다."""
    s, turn = turn_of(p, sid, t)
    a = turn.approval
    if a is None or a.state != "wait" or turn.end != "wait":
        raise ValueError("답할 승인 카드가 없어요")
    if a.tool in CARD_TOOLS:
        CARD_TOOLS[a.tool].decide(p, s, turn, approve, picked, text)
        s.updated = now()
        return
    if approve and a.op:
        op = a.op.model_copy(deep=True)
        notes = apply_op(p, op, move)  # 못 하면 ValueError 로 카드를 그대로 둔다
        s, turn = turn_of(p, sid, t)  # 화 번호를 옮기면 작품 칸이 통째로 바뀌므로 다시 찾는다
        a = turn.approval
        assert a is not None
        op.notes = notes
        turn.writes.append(WriteRecord(tool=a.tool, op=op, items=[WriteItem(key="renumber", label=op_label(op))]))
        a.state, a.picked = "approved", ["renumber"]
        note = StepRecord(kind="note", tool="approval", label=op_label(op), why="작가가 승인했어요",
                          result=f"작가가 승인해 저장함: {op_label(op)}. " + " ".join(notes)
                          + " 새 화 플롯은 제목 · 요약만 있으니 필요하면 edit_plot 으로 채웁니다.")
    elif approve:
        keys = [k for k in picked if k in a.keys] if picked else list(a.keys)
        if not keys:
            raise ValueError("쓸 부분을 고르세요")
        rec = _write(p, s, a.revision, a.target, keys)  # 쓰지 못하면 ValueError 로 카드를 그대로 둔다
        if rec.items:
            turn.writes.append(rec)
        if remember:  # 늘 묻는 종류는 '묻지 않기'에 넣지 않는다
            s.auto_kinds = sorted(set(s.auto_kinds) | (set(a.kinds) - set(ALWAYS_ASK)))
        a.state, a.picked = "approved", [i.key for i in rec.items]
        names = ", ".join(i.label for i in rec.items) or "없음"
        note = StepRecord(kind="note", tool="approval", label=names, why="작가가 승인했어요", result=f"작가가 승인해 저장함: {names}")
    else:
        a.state = "denied"
        note = StepRecord(kind="note", tool="approval", why="작가가 거절했어요", result="작가가 거절해 쓰지 않았어요. 다른 방법을 말하거나 끝냅니다")
    resume(p, sid, t, note)


def undo_ops(p: Project, sid: str, t: int, w: int | None = None, key: str | None = None) -> list[RenumberOp]:
    """undo 가 되돌리려는 화 넣기 · 빼기 (web 이 화 번호를 옮겨도 되는지 먼저 본다)."""
    _, turn = turn_of(p, sid, t)
    recs = [turn.writes[w]] if w is not None and 0 <= w < len(turn.writes) else turn.writes
    return [r.op for r in recs if r.op and any(i.state == "done" and (key is None or i.key == key) for i in r.items)]


def undo(p: Project, sid: str, t: int, w: int | None = None, key: str | None = None, move: bool = True,
         reverted: list[RenumberOp] | None = None) -> tuple[list[str], list[str], list[str]]:
    """바로 쓴 것을 되돌린다. w · key 를 주면 그 부분만, 없으면 그 턴 전체를 뒤에서부터.
    지금 값이 쓴 직후 값과 같은 부분만 돌린다 (pipeline.plot_undo). 화 넣기 · 빼기는 반대 동작(inverse)으로 돌리고,
    돌린 것을 reverted 에 더한다. (되돌린 이름, 남긴 이름, 남긴 까닭)."""
    _, turn = turn_of(p, sid, t)
    if w is not None and not 0 <= w < len(turn.writes):
        raise KeyError("쓴 기록이 없어요")
    order = [w] if w is not None else list(reversed(range(len(turn.writes))))
    done_l: list[str] = []
    kept_l: list[str] = []
    why_l: list[str] = []

    def pick(k: int):
        rec = turn_of(p, sid, t)[1].writes[k]  # 화 번호를 옮기면 작품 칸이 통째로 바뀌므로 매번 다시 찾는다
        return rec, [i for i in rec.items if i.state == "done" and (key is None or i.key == key)]

    for k in order:
        rec, items = pick(k)
        if not items:
            continue
        if rec.tool in CARD_TOOLS:
            d, kp, wy = CARD_TOOLS[rec.tool].undo(p, rec, items)
            done_l += d
            kept_l += kp
            why_l += wy
            continue
        if rec.op:
            try:
                inverse(p, rec.op, move)
                rec, items = pick(k)
            except ValueError as e:
                for i in items:
                    i.state, i.reason = "kept", str(e)
                    kept_l.append(i.label)
                    why_l.append(str(e))
            else:
                for i in items:
                    i.state = "reverted"
                    done_l.append(i.label)
                if reverted is not None:
                    reverted.append(rec.op)
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
