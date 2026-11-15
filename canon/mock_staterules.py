"""가짜 응답: 대화 에이전트의 상태 규칙 제안 'propose_rule' (canon/agent_staterules.py, docs/context/specs/07-rules.md 의 7c).

mock._agent_step 이 부른다. 말이 '상태 규칙' 으로 시작하면 도구 인자를 지어 낸다.
- '상태 규칙 <인물> <항목> <op> <값> => <인물> <항목> <새 값>': 상태창 조건 하나와 상태창 바꾸기 하나
- '상태 규칙 <인물> <항목> <op> <값> => 회수 <복선 id>': 상태창 조건 하나와 복선 회수 하나
- '상태 규칙 rule=<id> 끄기': 그 규칙 끄기
- '상태 규칙 깨진': when 에 JSON 이 아닌 글 (막힘 시험)
도구가 막혀 돌아오면(이미 propose_rule 을 불렀으면) 답만 한다.
"""
from __future__ import annotations

import json
import re

from .schema import PlotAgentStep, ToolArg

HEAD = "상태 규칙"
_RULE = re.compile(r"상태 규칙 (\S+) (\S+) (ge|le|gt|lt|eq|ne|has) (\S+) => (?:회수 (\S+)|(\S+) (\S+) (\S*))")


def agent_step(hint: dict) -> PlotAgentStep | None:
    msg, tools = hint["message"], hint.get("tools", [])
    if not msg.startswith(HEAD):
        return None
    if "propose_rule" in tools:  # 막혀서 카드 없이 돌아왔다 (카드를 남기면 턴이 끝난다)
        return PlotAgentStep(reply="상태 규칙을 만들지 못했어요. 막힌 까닭을 보고 다시 말해 주세요.")
    reply = "상태 규칙을 만들어 봤어요. 적용할지 골라 주세요."
    if hit := re.search(r"rule=(\S+) 끄기", msg):
        return PlotAgentStep(thought="규칙을 꺼요", tool="propose_rule", reply=reply,
                             args=[ToolArg(name="rule", value=hit.group(1)), ToolArg(name="on", value="false")])
    if "깨진" in msg:
        return PlotAgentStep(thought="규칙을 제안해요", tool="propose_rule", reply=reply,
                             args=[ToolArg(name="when", value="마력이 0 이하"), ToolArg(name="changes", value="[]")])
    m = _RULE.search(msg)
    if not m:
        return None
    who, stat, op, value, fs, cid, name, new = m.groups()
    when = [{"kind": "stat", "character": who, "name": stat, "op": op, "value": value}]
    changes = [{"kind": "resolve", "foreshadow_id": fs}] if fs else [{"kind": "stat", "character_id": cid, "stat": name, "value": new}]
    return PlotAgentStep(thought="상태 규칙을 제안해요", tool="propose_rule", reply=reply,
                         args=[ToolArg(name="name", value=f"{stat} {value} {op}"), ToolArg(name="when", value=json.dumps(when, ensure_ascii=False)),
                               ToolArg(name="changes", value=json.dumps(changes, ensure_ascii=False))])
