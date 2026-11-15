"""대화 에이전트의 상태 규칙 제안 도구 'propose_rule' (docs/context/specs/07-rules.md 의 7c, 정할 것 9).

- 06b 의 propose_regex(agent_regex.py) 꼴을 따른다. 에이전트 단계(PlotAgentStep)가 도구 인자(args)로 규칙을 채우고 prepare 는 AI 를 부르지 않는다.
  LLM 호출은 에이전트의 'chat' 단계 하나다. 새 get_llm 단계를 두지 않는다.
- 인자: rule(고칠 규칙 id, 비우면 새 규칙) · name · note · on · when · changes.
  when 은 조건(Condition) JSON 배열, changes 는 제안할 변경(RuleProposalSpec) JSON 배열이다. 고치기에서 비운 인자는 지금 값을 둔다.
  인물 칸에는 id 대신 이름을 적어도 받아 id 로 바꾼다. changes 의 kind 는 stat · resolve 뿐이라 관계 수치는 제안할 수 없다 (Q27).
- 도구 한 번에 규칙 하나를 더하거나 고친다. 지우기는 하지 않는다(상태 규칙 쪽에서 작가가 지운다). 끄기는 on=false 고치기다.
- prepare 가 검사한다: JSON 꼴, 없는 인물 · 복선 · 관계 수치 이름, 빈 changes, 바뀌는 칸 없음, 같은 규칙. 막히면 카드 없이 까닭을 AI 에게 돌려준다.
  통과하면 마지막으로 반영한 화 뒤 상태로 조건이 지금 맞는지(holds_now)를 카드에 적는다.
- record 가 카드(Approval.state_rule, schema.StateRuleCard)를 남기고 턴을 끝낸다. 권한 모드와 상관없이 늘 묻는다 (종류 rule, agent.ALWAYS_ASK, Q29).
- decide 가 승인하면 Project.state_rules 에 규칙 하나를 넣는다(새 규칙은 끝에, id 는 staterules.fill_ids). 고칠 규칙이 카드를 만든 뒤 바뀌었으면 막는다.
- undo 는 지금 규칙이 적용 뒤 값과 같을 때만 돌린다: 새 규칙은 빼고, 고치기는 적용 전 규칙으로. 오래된 턴의 전 · 뒤 값은 compact 가 지운다.
- 에이전트는 상태 승인 화면의 규칙 제안(StateDelta.rule_proposals)을 만들거나 반영하지 않는다.
agent.py 의 CARD_TOOLS 가 이 모듈을 등록한다 (훅 이름은 agent_text.py 머리).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import ValidationError

from . import context, statwin
from .schema import (TIE_NAMES, AgentSession, AgentTurn, Approval, Condition, PlotAgentStep, Project, RuleProposalSpec, StateRule,
                     StateRuleCard, StepRecord, WriteItem, WriteRecord)

TOOL = "propose_rule"
KIND = "rule"  # 승인 카드의 종류 (agent.KIND_LABELS '규칙'). 06b 의 propose_regex 와 함께 쓴다. agent.ALWAYS_ASK 에 들어 늘 묻는다
LABEL = "상태 규칙 제안"
KEPT = "그 뒤에 다시 고친 규칙이라 그대로 뒀어요"
GONE = "그 규칙을 찾을 수 없어 그대로 뒀어요"
TRUE = ("true", "1", "yes", "on", "켬", "참")
FALSE = ("false", "0", "no", "off", "끔", "거짓")
WHEN_HELP = ('when 은 JSON 배열이에요. 예: [{"kind": "stat", "character": "hero", "name": "마력", "op": "le", "value": "0"}, '
             '{"kind": "tie", "character": "hero", "target": "ally", "name": "trust", "op": "ge", "value": "0.7"}, '
             '{"kind": "episode", "from_ep": 3, "to_ep": 10}, {"kind": "foreshadow", "foreshadow": "fs-1", "status": "open"}, '
             '{"kind": "in_plot", "character": "hero"}]')
CHANGES_HELP = ('changes 는 JSON 배열이에요. 예: [{"kind": "stat", "character_id": "hero", "stat": "상태", "value": "기절"}, '
                '{"kind": "resolve", "foreshadow_id": "fs-1"}]. kind 는 stat(상태창 값 바꾸기) · resolve(복선 회수) 뿐이에요')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rule_label(r: StateRule) -> str:
    return r.name.strip() or r.id or "이름 없는 규칙"


def shortcut(turn: AgentTurn) -> PlotAgentStep | None:
    """상태 규칙 제안은 지름길이 없다. 늘 에이전트 단계가 인자를 채운다."""
    return None


def _args(step: PlotAgentStep) -> dict[str, str]:
    return {a.name.strip().lower(): a.value for a in step.args}


def _who(p: Project, x: str) -> str:
    """인물 칸 값: id 그대로, 아니면 이름이 같은 인물의 id. 못 찾으면 그대로 (검사가 막는다)."""
    x = x.strip()
    if not x or any(c.id == x for c in p.characters):
        return x
    return next((c.id for c in p.characters if c.name == x), x)


def _list(raw: str, model, help_text: str) -> list | str:
    """JSON 배열 하나를 모델 목록으로. 꼴이 틀리면 까닭(글)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"JSON 으로 읽지 못했어요({e.msg}). {help_text}"
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        return help_text
    try:
        return [model.model_validate(x) for x in data]
    except ValidationError as e:
        bad = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:3])
        return f"칸 값이 맞지 않아요({bad}). {help_text}"


def _fields(p: Project, args: dict[str, str]) -> dict | str:
    out: dict = {}
    for k in ("name", "note"):
        if args.get(k, "").strip():
            out[k] = args[k].strip()
    if v := args.get("on", "").strip().lower():
        if v not in TRUE + FALSE:
            return f"on 은 true · false 가운데 하나예요: {v}"
        out["on"] = v in TRUE
    if args.get("when", "").strip():
        when = _list(args["when"], Condition, WHEN_HELP)
        if isinstance(when, str):
            return when
        for c in when:
            c.character, c.target = _who(p, c.character), _who(p, c.target)
        out["when"] = when
    if args.get("changes", "").strip():
        changes = _list(args["changes"], RuleProposalSpec, CHANGES_HELP)
        if isinstance(changes, str):
            return changes
        for c in changes:
            c.character_id = _who(p, c.character_id)
            c.stat, c.value = c.stat.strip(), c.value.strip()
        out["changes"] = changes
    return out


def _missing(p: Project, r: StateRule) -> list[str]:
    """없는 인물 · 복선, 모르는 관계 수치 이름, 빈 상태창 항목 이름. 상태 규칙 쪽의 condMissing · specMissing 과 같은 뜻이다."""
    chars = {c.id for c in p.characters}
    fs = {f.id for f in p.foreshadows}
    out: list[str] = []
    for c in r.when:
        if c.kind in ("stat", "tie", "in_plot") and c.character not in chars:
            out.append(f"조건의 인물이 없어요: {c.character or '(빈칸)'}")
        if c.kind == "tie" and c.target not in chars:
            out.append(f"관계 조건의 상대 인물이 없어요: {c.target or '(빈칸)'}")
        if c.kind == "tie" and c.name not in TIE_NAMES:
            out.append(f"관계 수치 이름은 {' · '.join(TIE_NAMES)} 가운데 하나예요: {c.name or '(빈칸)'}")
        if c.kind == "stat" and not c.name.strip():
            out.append("상태창 조건의 항목 이름(name)이 비었어요")
        if c.kind == "foreshadow" and c.foreshadow not in fs:
            out.append(f"조건의 복선이 없어요: {c.foreshadow or '(빈칸)'}")
    for x in r.changes:
        if x.kind == "stat" and x.character_id not in chars:
            out.append(f"바꿀 인물이 없어요: {x.character_id or '(빈칸)'}")
        if x.kind == "stat" and not x.stat:
            out.append("바꿀 상태창 항목 이름(stat)이 비었어요")
        if x.kind == "resolve" and x.foreshadow_id not in fs:
            out.append(f"회수할 복선이 없어요: {x.foreshadow_id or '(빈칸)'}")
    return out


def _same(a: StateRule, b: StateRule) -> bool:
    return [c.model_dump() for c in a.when] == [c.model_dump() for c in b.when] and \
        [x.model_dump() for x in a.changes] == [x.model_dump() for x in b.changes]


def prepare(name: str, p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep) -> StateRuleCard | str:
    """잠금 밖에서 규칙을 만들고 검사한다 (AI 를 부르지 않는다). 막히면 까닭(글)을 돌려준다."""
    args = _args(step)
    rid = args.get("rule", "").strip()
    before = next((r for r in p.state_rules if r.id == rid), None) if rid else None
    if rid and before is None:
        have = ", ".join(f"{r.id}('{rule_label(r)}')" for r in p.state_rules) or "없음"
        return f"상태 규칙 {rid} 을(를) 찾을 수 없어요. 지금 규칙: {have}. read_state_rules 로 id 를 보세요"
    fields = _fields(p, args)
    if isinstance(fields, str):
        return fields
    if before is not None:
        rule = before.model_copy(update=fields, deep=True)
        if rule == before:
            return f"규칙 '{rule_label(before)}' 에서 바뀌는 칸이 없어요. 바꿀 인자만 채워 다시 부르세요"
    else:
        rule = StateRule(**fields)
    if not rule.changes:
        return f"제안할 변경(changes)이 비었어요. {CHANGES_HELP}"
    if bad := _missing(p, rule):
        chars = ", ".join(f"{c.id}({c.name})" for c in p.characters) or "없음"
        return "\n".join([*bad, f"인물 id: {chars}. 복선 · 상태창 항목은 read_state_rules 로 보세요"])
    dup = next((r for r in p.state_rules if r.id != rule.id and _same(r, rule)), None)
    if dup is not None:
        return f"같은 조건과 변경의 규칙이 이미 있어요: id {dup.id} ('{rule_label(dup)}'). 고치려면 rule 에 그 id 를 넣으세요"
    card = StateRuleCard(rule=rule, before=before, project=name)
    last = statwin.last_done(p)
    if last:
        card.holds_ep, card.holds_now = last, context.all_hold(p, last, rule.when, context.view_now(p))
    if not rule.when:
        card.notices.append("조건이 없어 상태 변경안마다 제안해요")
    if not rule.on:
        card.notices.append("꺼 둔 규칙이라 켜기 전에는 제안하지 않아요")
    return card


def record(p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep, prepared: StateRuleCard | str | None) -> str:
    """잠근 작품에서 카드를 남기고 턴을 끝낸다 ('wait'). 막혔으면 까닭을 막힘 단계로 남기고 '' (에이전트가 이어 간다)."""
    if not isinstance(prepared, StateRuleCard):
        why = prepared or "규칙을 만들지 못했어요"
        turn.steps.append(StepRecord(kind="block", tool=TOOL, label="상태 규칙", why=why, result=f"할 수 없어요: {why}"))
        return ""
    card = prepared
    name = f"상태 규칙 · {rule_label(card.rule)}"
    turn.approval = Approval(tool=TOOL, state_rule=card, keys=["rule"], kinds=[KIND])
    turn.reply = step.reply.strip() or step.thought.strip() or "상태 규칙을 만들었어요. 카드에서 적용할지 골라 주세요."
    turn.steps.append(StepRecord(kind="wait", tool=TOOL, label=name, why="규칙은 늘 물어보고 넣어요",
                                 result=f"작가에게 물음: {name}. 작가의 답을 기다려야 하므로 턴을 끝냅니다"))
    return "wait"


def _find(p: Project, rid: str) -> StateRule | None:
    return next((r for r in p.state_rules if r.id == rid), None) if rid else None


def decide(p: Project, s: AgentSession, turn: AgentTurn, approve: bool, picked: list[str], text: str | None = None) -> None:
    """카드에 답한다. 승인하면 규칙 하나를 넣는다. 고칠 규칙이 바뀌었으면 ValueError 로 카드를 그대로 둔다. 답하면 턴을 끝낸다."""
    from . import staterules  # staterules → pipeline 을 늦게 부른다
    a = turn.approval
    assert a is not None and a.state_rule is not None
    card = a.state_rule
    if approve:
        if card.before is None:
            rule = card.rule.model_copy(deep=True, update={"id": ""})
            p.state_rules.append(rule)
            staterules.fill_ids(p.state_rules)
        else:
            now = _find(p, card.before.id)
            if now is None:
                raise ValueError("그 규칙을 찾을 수 없어요. 다시 요청해 주세요")
            if now != card.before:
                raise ValueError("그 사이 규칙이 바뀌었어요. 다시 요청해 주세요")
            rule = card.rule.model_copy(deep=True, update={"id": card.before.id})
            p.state_rules[p.state_rules.index(now)] = rule
        done = card.model_copy(deep=True, update={"rule": rule.model_copy(deep=True)})
        label = f"상태 규칙 · {rule_label(rule)}"
        turn.writes.append(WriteRecord(tool=TOOL, state_rule=done, items=[WriteItem(key="rule", label=label)]))
        a.state, a.picked = "approved", ["rule"]
        turn.steps.append(StepRecord(kind="note", tool="approval", label=label,
                                     why="작가가 적용했어요. 다음 상태 변경안부터 조건이 맞으면 제안해요"))
    else:
        a.state = "denied"
        turn.steps.append(StepRecord(kind="note", tool="approval", why="작가가 적용하지 않았어요"))
    turn.end, turn.ended = "done", _now()
    for x in turn.steps:
        x.result = ""


def undo(p: Project, rec: WriteRecord, items: list[WriteItem]) -> tuple[list[str], list[str], list[str]]:
    """적용한 규칙 하나를 되돌린다. 지금 규칙이 적용 뒤 값과 같을 때만: 새 규칙은 빼고, 고치기는 적용 전 규칙으로. (되돌린 이름, 남긴 이름, 남긴 까닭)."""
    card = rec.state_rule
    out: tuple[list[str], list[str], list[str]] = ([], [], [])

    def keep(reason: str) -> tuple[list[str], list[str], list[str]]:
        for i in items:
            i.state, i.reason = "kept", reason
            out[1].append(i.label)
            out[2].append(reason)
        return out

    if card is None:
        return out
    now = _find(p, card.rule.id)
    if now is None:
        return keep(GONE)
    if now != card.rule:
        return keep(KEPT)
    at = p.state_rules.index(now)
    if card.before is None:
        p.state_rules.pop(at)
    else:
        p.state_rules[at] = card.before.model_copy(deep=True)
    for i in items:
        i.state = "reverted"
        out[0].append(i.label)
    return out


def compact(rec: WriteRecord, reason: str) -> None:
    """오래된 턴의 규칙 전 · 뒤 값을 지운다 (agent._compact). 아직 되돌리지 않은 것은 kept 로 남긴다."""
    for i in rec.items:
        if i.state == "done":
            i.state, i.reason = "kept", reason
    rec.state_rule = None


def read(p: Project) -> tuple[str, str]:
    """read_state_rules 도구: 상태 규칙(조건 · 변경), 조건을 단 이야기 요소, 상태창 항목 이름, 열린 복선. (단계 줄 이름, 결과 글)."""
    stats = {s.character_id: [x.name for x in s.stats] for s in p.states if s.stats}
    data = {
        "state_rules": [r.model_dump() for r in p.state_rules],
        "element_conditions": [{"id": el.id, "name": el.name, "when": [c.model_dump() for c in el.activation.conditions]}
                               for el in p.elements if el.activation.conditions],
        "characters": [{"id": c.id, "name": c.name, "stats": stats.get(c.id, [])} for c in p.characters],
        "open_foreshadows": [{"id": f.id, "description": f.description[:60]} for f in p.foreshadows if f.status == "open"],
        "tie_names": list(TIE_NAMES),
    }
    return f"상태 규칙 {len(p.state_rules)}개", json.dumps(data, ensure_ascii=False)
