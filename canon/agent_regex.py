"""대화 에이전트의 정규식 규칙 제안 도구 'propose_regex' (docs/context/specs/06b-rule-propose.md).

- 에이전트 단계(PlotAgentStep)가 도구 인자(args)로 규칙 칸을 채운다. prepare 는 AI 를 부르지 않는다 (정할 것 3).
  인자: bundle(묶음 id) · rule(고칠 규칙 id, 비우면 새 규칙) · comment · in · out · action · type · flag · enabled.
  고치기에서 비운 인자는 지금 값을 두고, 새 규칙에서 비운 인자는 RegexRule 기본값(warn · output · g)을 쓴다.
- prepare 가 잠금 밖에서 규칙을 만들고, 넣을 묶음을 이 작품이 켠 묶음 가운데서 고르고, regexrules.validate · check 로 검사하고,
  규칙 하나만 지금 본문에 걸어 본다 (regexrules.trial(strict=True)). 막히면 카드 없이 까닭을 AI 에게 돌려주고 턴을 잇는다.
  끄기만 하는 카드는 검사하지 않고, 끄기 카드는 시험이 시간 한도를 넘어도 막지 않는다 (카드에 timed_out).
- 통과하면 record 가 카드(Approval.regex, schema.RegexCard)를 남기고 턴을 끝낸다. 권한 모드와 상관없이 늘 묻고,
  '이 세션에서 묻지 않기'(auto_kinds)도 받지 않는다 (종류 rule, agent.ALWAYS_ASK).
- decide 는 묶음을 다시 읽어 규칙 하나만 넣는다 (regexrules.set_rule). 켠 묶음이 없어 새 묶음을 만드는 카드면 만들고 이 작품에서 켠다.
  답하면 턴을 끝낸다 (AI 를 더 부르지 않는다). 이미 쓴 화의 본문에는 다시 걸지 않는다 (정할 것 12).
- undo 는 지금 규칙이 적용 뒤 값과 같을 때만 그 규칙 하나를 돌린다. 오래된 턴의 전 · 뒤 값은 compact 가 지운다.
- 규칙 묶음 파일(.rules/<id>.json)은 작품 밖이라 작품 잠금이 막지 않는다. 규칙 화면과 함께 고치면 나중 저장이 이긴다 (정할 것 14).
agent.py 의 CARD_TOOLS 가 이 모듈을 등록한다 (훅 이름은 agent_text.py 머리).
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import pipeline, regexrules
from .schema import (AgentSession, AgentTurn, Approval, ConsistencyIssue, PlotAgentStep, Project, RegexCard, RegexRule, RuleBundle,
                     RuleChange, StepRecord, WriteItem, WriteRecord)

TOOL = "propose_regex"
KIND = "rule"  # 승인 카드의 종류 (agent.KIND_LABELS). agent.ALWAYS_ASK 에 들어 늘 묻는다
LABEL = "정규식 규칙 제안"
KEPT = "그 뒤에 다시 고친 규칙이라 그대로 뒀어요"
GONE = "그 묶음이나 규칙을 찾을 수 없어 그대로 뒀어요"
CARD_LIMIT = 10  # 카드에 남기는 바뀐 곳 · 걸린 곳 수 (시작 값, 정할 것 11)
APPLY_NOTE = "대화 에이전트 제안: "
UNDO_NOTE = "대화 에이전트 제안 되돌림"
ARGS = ("bundle", "rule", "comment", "in", "out", "action", "type", "flag", "enabled")
ACTIONS = {"warn": "warn", "경고": "warn", "fix": "fix", "고침": "fix"}
TYPES = {"output": "output", "본문": "output", "export": "export", "내보내기": "export"}
TRUE = ("true", "1", "yes", "on", "켬", "참")
FALSE = ("false", "0", "no", "off", "끔", "거짓")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rule_label(r: RegexRule) -> str:
    """규칙 이름 (화면 · 단계 줄). 이름이 없으면 찾을 정규식."""
    return r.comment.strip() or r.in_ or r.id


def effect(r: RegexRule) -> str:
    """적용하면 언제부터 걸리는지 (정할 것 12, 카드와 적용 뒤 단계 줄)."""
    if not r.enabled:
        return "규칙을 꺼서 다음 걸기부터 걸리지 않아요"
    if r.type == "export":
        return "다음 내보내기부터 걸려요"
    if r.action == "fix":
        return "다음에 본문을 쓸 때부터 걸려요. 이미 쓴 화의 본문에는 다시 걸지 않아요"
    return "다음 검수부터 이미 쓴 화에도 걸려요"


def turned_off(card: RegexCard) -> bool:
    """켠 규칙을 끄는 카드인지. 그러면 시험 결과는 적용 전 규칙으로 건 '더 걸리지 않을 곳'이다 (정할 것 11)."""
    return card.before is not None and card.before.enabled and not card.rule.enabled


def shortcut(turn: AgentTurn) -> PlotAgentStep | None:
    """규칙 제안은 지름길이 없다. 늘 에이전트 단계가 인자를 채운다."""
    return None


def _args(step: PlotAgentStep) -> dict[str, str]:
    """도구 인자. 'in_' 도 'in' 으로 받는다. 이름은 작게 맞춘다."""
    out: dict[str, str] = {}
    for a in step.args:
        k = a.name.strip().lower()
        out["in" if k == "in_" else k] = a.value
    return out


def _fields(args: dict[str, str]) -> dict | str:
    """채운 인자를 RegexRule 칸으로 읽는다. 모르는 값이면 까닭(글). in · out 은 빈칸도 뜻이 있어 다듬지 않는다."""
    out: dict = {}
    if args.get("comment", "").strip():
        out["comment"] = args["comment"].strip()
    if args.get("in", ""):
        out["in_"] = args["in"]
    if args.get("out", ""):
        out["out"] = args["out"]
    if args.get("flag", "").strip():
        out["flag"] = args["flag"].strip()
    if v := args.get("action", "").strip().lower():
        if v not in ACTIONS:
            return f"action 은 warn(경고) · fix(고침) 가운데 하나예요: {v}"
        out["action"] = ACTIONS[v]
    if v := args.get("type", "").strip().lower():
        if v not in TYPES:
            return f"type 은 output(쓴 본문) · export(내보내기) 가운데 하나예요: {v}"
        out["type"] = TYPES[v]
    if v := args.get("enabled", "").strip().lower():
        if v not in TRUE + FALSE:
            return f"enabled 는 true · false 가운데 하나예요: {v}"
        out["enabled"] = v in TRUE
    return out


def _same(a: RegexRule, b: RegexRule) -> bool:
    """같은 규칙인지 (같은 in · out · action · type · flag)."""
    return (a.in_, a.out, a.action, a.type, a.flag) == (b.in_, b.out, b.action, b.type, b.flag)


def _names(bundles: list[RuleBundle]) -> str:
    return ", ".join(f"'{b.name}'(id {b.id})" for b in bundles)


def _trial_episode(p: Project, s: AgentSession, turn: AgentTurn) -> int:
    """시험할 화: 세션 대상이 본문(text:N)이면 그 화, 아니면 턴이 실어 온 화, 아니면 본문이 있는 가장 뒤 화. 본문이 없는 화는 건너뛴다."""
    written = {e.plot.number for e in p.episodes if e.text.strip()}
    kind, lo, _, _ = pipeline.chat_focus(p, s.target)
    for n in (lo if kind == "text" else 0, turn.episode):
        if n and n in written:
            return n
    return max(written, default=0)


def _target(p: Project, name: str, args: dict[str, str]) -> tuple[RuleBundle | None, RegexRule | None, str]:
    """넣을 묶음과 고칠 규칙 (정할 것 6). 새 묶음이면 묶음이 None. 막히면 세 번째 값이 까닭이다."""
    bundles = regexrules.bundles_of(p)
    want = args.get("bundle", "").strip()
    rid = args.get("rule", "").strip()
    pick = None
    if want:
        pick = next((b for b in bundles if b.id == want), None) or next((b for b in bundles if b.name == want), None)
        if pick is None:
            have = f" 켠 묶음: {_names(bundles)}" if bundles else " 이 작품이 켠 묶음이 없어요. bundle 을 비우면 새 묶음을 만들어요"
            return None, None, f"이 작품이 켠 묶음이 아니에요: {want}.{have}"
    if rid:
        for b in [pick] if pick else bundles:
            r = next((x for x in b.rules if x.id == rid), None)
            if r is not None:
                return b, r, ""
        return None, None, f"규칙 {rid} 을(를) 이 작품이 켠 묶음에서 찾을 수 없어요. read_rules 로 규칙 id 를 보세요"
    if pick:
        return pick, None, ""
    if len(bundles) > 1:
        return None, None, (f"이 작품이 켠 묶음이 {len(bundles)}개라 넣을 곳을 정해야 해요: {_names(bundles)}. "
                            "bundle 에 묶음 id 를 넣거나 작가에게 물으세요(ask)")
    return (bundles[0] if bundles else None), None, ""


def prepare(name: str, p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep) -> RegexCard | str:
    """잠금 밖에서 규칙을 만들고 검사하고 지금 본문에 걸어 본다 (AI 를 부르지 않는다). 막히면 까닭(글)을 돌려준다."""
    args = _args(step)
    fields = _fields(args)
    if isinstance(fields, str):
        return fields
    b, before, why = _target(p, name, args)
    if why:
        return why
    if before is not None:
        rule = before.model_copy(update=fields, deep=True)
        if rule == before:
            return f"규칙 '{rule_label(before)}' 에서 바뀌는 칸이 없어요. 바꿀 인자만 채워 다시 부르세요"
    else:
        rule = RegexRule(**fields)
    if not rule.in_:
        return "찾을 정규식(in)이 비었어요. 빈 규칙은 걸리지 않아요"
    off_only = regexrules.switched_off(before, rule)  # 끄기만 하면 검사하지 않는다. 지금 검사에 걸리는 옛 규칙도 끌 수 있다
    if not off_only and (errors := regexrules.validate(rule)):
        return "\n".join([*errors, "JavaScript 정규식 꼴로 고쳐 다시 부르세요"])
    rules = list(b.rules) if b else []
    dup = next((r for r in rules if r.id != rule.id and _same(r, rule)), None)
    if dup is not None:
        return f"같은 규칙이 이미 있어요: id {dup.id} ('{rule_label(dup)}'). 고치려면 rule 에 그 id 를 넣으세요"
    after = [rule if r.id == rule.id else r for r in rules] if before is not None else rules + [rule]
    if errors := regexrules.check(after, {rule.id} if off_only else ()):
        return "\n".join(errors)
    bid = b.id if b else ""
    card = RegexCard(bundle=bid, bundle_name=b.name if b else f"{p.meta.title.strip() or name} 규칙", new_bundle=b is None,
                     project=name, used_by=[x for x in regexrules.used_by(bid) if x != name] if bid else [],
                     rule=rule, before=before, notices=regexrules.notices(rule))
    n = _trial_episode(p, s, turn)
    if n:
        # 끄기는 켠 규칙만 거는 _pick 이라 늘 0 이다. 그래서 적용 전 규칙을 걸어 '더 걸리지 않을 곳'을 보인다
        tried = before if turned_off(card) else rule
        res = regexrules.trial([tried], p.episode(n).text, bid, card.bundle_name, strict=True)
        if res["skipped"] and turned_off(card):  # 느린 규칙을 끄는 카드는 막지 않는다. 끄면 그 규칙은 더 걸리지 않는다
            card.episode, card.timed_out = n, True
            return card
        if res["skipped"]:
            return (f"이 규칙을 {n}화에 걸어 보니 시간 한도({regexrules.TIME_LIMIT:g}초)를 넘었어요. "
                    "반복을 줄이거나 더 좁게 찾는 정규식으로 다시 적으세요")
        card.episode = n
        card.change_count, card.hit_count = len(res["changes"]), len(res["hits"])
        card.changes = [RuleChange(**c) for c in res["changes"][:CARD_LIMIT]]
        card.hits = [ConsistencyIssue(**h) for h in res["hits"][:CARD_LIMIT]]
        card.export_changed = tried.type == "export" and res["exported"] != res["text"]
    return card


def record(p: Project, s: AgentSession, turn: AgentTurn, step: PlotAgentStep, prepared: RegexCard | str | None) -> str:
    """잠근 작품에서 카드를 남기고 턴을 끝낸다 ('wait'). 막혔으면 까닭을 막힘 단계로 남기고 '' (에이전트가 이어 간다)."""
    if not isinstance(prepared, RegexCard):
        why = prepared or "규칙을 만들지 못했어요"
        turn.steps.append(StepRecord(kind="block", tool=TOOL, label="정규식 규칙", why=why, result=f"할 수 없어요: {why}"))
        return ""
    card = prepared
    where = f"새 묶음 {card.bundle_name}" if card.new_bundle else card.bundle_name
    name = f"{where} · {rule_label(card.rule)}"
    turn.approval = Approval(tool=TOOL, regex=card, keys=["rule"], kinds=[KIND])
    turn.reply = step.reply.strip() or step.thought.strip() or "규칙을 만들었어요. 카드에서 적용할지 골라 주세요."
    turn.steps.append(StepRecord(kind="wait", tool=TOOL, label=name, why="규칙은 늘 물어보고 넣어요",
                                 result=f"작가에게 물음: 정규식 규칙 {name}. 작가의 답을 기다려야 하므로 턴을 끝냅니다"))
    return "wait"


def _find(b: RuleBundle, rid: str) -> RegexRule | None:
    return next((r for r in b.rules if r.id == rid), None)


def decide(p: Project, s: AgentSession, turn: AgentTurn, approve: bool, picked: list[str], text: str | None = None) -> None:
    """카드에 답한다. 승인하면 묶음을 다시 읽어 규칙 하나를 넣는다. 못 넣으면 ValueError 로 카드를 그대로 둔다 (정할 것 14).
    어느 쪽이든 답하면 턴을 끝낸다. picked · text 는 다른 카드 것이라 쓰지 않는다."""
    a = turn.approval
    assert a is not None and a.regex is not None
    card = a.regex
    if approve:
        rule = card.rule
        note = (APPLY_NOTE + rule_label(rule))[:200]
        if card.new_bundle:
            b = regexrules.create(card.bundle_name, rules=[rule], note=note)  # 검사(check)를 다시 거친다
            p.settings.rule_bundles.append(b.id)  # 새로 만든 묶음만 켠다 (정할 것 8)
        else:
            if not regexrules.exists(card.bundle):
                raise ValueError("그 묶음을 찾을 수 없어요")
            if card.bundle not in p.settings.rule_bundles:
                raise ValueError("이 작품에서 그 묶음을 껐어요")
            now = _find(regexrules.load(card.bundle), rule.id)
            if now != card.before:  # 고칠 규칙이 카드를 만든 뒤 바뀌었거나, 새 규칙 id 가 그 사이 생겼다
                raise ValueError("그 사이 규칙이 바뀌었어요. 다시 요청해 주세요")
            b = regexrules.set_rule(card.bundle, rule.id, rule, note)
        card.bundle = b.id
        done = card.model_copy(deep=True, update={"version": b.version})
        label = f"정규식 규칙 · {rule_label(rule)}"
        turn.writes.append(WriteRecord(tool=TOOL, regex=done, items=[WriteItem(key="rule", label=label)]))
        a.state, a.picked = "approved", ["rule"]
        turn.steps.append(StepRecord(kind="note", tool="approval", label=label, why=f"작가가 적용했어요. {effect(rule)}"))
    else:
        a.state = "denied"
        turn.steps.append(StepRecord(kind="note", tool="approval", why="작가가 적용하지 않았어요"))
    turn.end, turn.ended = "done", _now()
    for x in turn.steps:
        x.result = ""


def undo(p: Project, rec: WriteRecord, items: list[WriteItem]) -> tuple[list[str], list[str], list[str]]:
    """적용한 규칙 하나를 되돌린다 (정할 것 13). 지금 규칙이 적용 뒤 값과 같을 때만 돌린다: 새 규칙은 빼고, 고치기는 적용 전 규칙으로.
    새로 만든 묶음이면 이 작품에서 끄고, 그 규칙만 남았고 다른 작품이 켜지 않았으면 묶음 파일도 지운다. (되돌린 이름, 남긴 이름, 남긴 까닭)."""
    card = rec.regex
    out: tuple[list[str], list[str], list[str]] = ([], [], [])

    def keep(reason: str) -> tuple[list[str], list[str], list[str]]:
        for i in items:
            i.state, i.reason = "kept", reason
            out[1].append(i.label)
            out[2].append(reason)
        return out

    if card is None:
        return out
    bid, rule = card.bundle, card.rule
    if not regexrules.exists(bid):
        return keep(GONE)
    b = regexrules.load(bid)
    now = _find(b, rule.id)
    if now is None:
        return keep(GONE)
    if now != rule:
        return keep(KEPT)
    try:
        if card.new_bundle:
            # 디스크의 이 작품(p 를 읽은 그대로)이 켰으면 한 곳을 뺀다. 복제 · 이름 바꾸기로 폴더 이름이 card.project 와 달라도 맞다
            others = len(regexrules.used_by(bid)) - (bid in p.settings.rule_bundles)
            if [r.id for r in b.rules] == [rule.id] and not others:
                regexrules.delete(bid)
            else:
                regexrules.set_rule(bid, rule.id, None, UNDO_NOTE)
            if bid in p.settings.rule_bundles:
                p.settings.rule_bundles.remove(bid)
        else:
            regexrules.set_rule(bid, rule.id, card.before, UNDO_NOTE)
    except (KeyError, ValueError) as e:
        return keep(str(e).strip("'"))
    for i in items:
        i.state = "reverted"
        out[0].append(i.label)
    return out


def compact(rec: WriteRecord, reason: str) -> None:
    """오래된 턴의 규칙 전 · 뒤 값을 지운다 (agent._compact). 아직 되돌리지 않은 것은 kept 로 남긴다."""
    for i in rec.items:
        if i.state == "done":
            i.state, i.reason = "kept", reason
    rec.regex = None
