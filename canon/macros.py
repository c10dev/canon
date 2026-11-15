"""CBS 읽기 매크로 (docs/context/specs/05-macros.md). LLM 을 부르지 않고 Project 를 바꾸지 않는다.

작가가 이야기 요소 설명과 작가 메모(Meta.notes)에 적은 {{user}} · {{char}} · {{getvar::인물.스탯}} · {{episode}} 를
프롬프트를 조립할 때 그 화의 값으로 바꾼다. 저장한 글은 그대로다. 매크로는 값을 읽기만 한다(Q11).
- 이름은 RisuAI CBS 를 따른다(Q20). {{bot}} 은 {{char}} 와 같다. 함수 이름은 대소문자를 가리지 않는다.
- 모르는 함수, {{chatindex}}, setvar 무리, {{#…}} … {{/…}} 블록은 그대로 두고 경고한다(Q25).
- 겹친 매크로는 안쪽부터 펼치고 최대 MAX_PASSES 번 돈다. 펼쳐 넣은 값은 다시 훑지 않는다.
- 값은 MacroEnv 로 받는다. prompts.macro_env 가 만들고 이 모듈은 prompts 를 부르지 않는다(돌아 불러오기를 막는다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel

MAX_PASSES = 3
_INNER = re.compile(r"\{\{([^{}]*)\}\}")  # 안에 중괄호가 없는 가장 안쪽 쌍
_BLOCK_OPEN = re.compile(r"\{\{#\s*([^{}:\s]*)")  # 여는 표시의 앞. 안에 매크로가 겹칠 수 있어 끝은 _close 가 찾는다
_SETVAR = re.compile(r"^(set|add|setdefault|settemp)var$")
_MARK = "\x00{}\x00"  # 펼친 자리표 (펼친 값을 다시 훑지 않게)
_MARKS = re.compile(r"\x00(\d+)\x00")
STRIP = re.compile(r"\{\{[^{}]*\}\}")  # 매크로를 떼고 볼 때 (echoes._canon_text)


class MacroUse(BaseModel):
    """매크로 쓰임 하나 (프롬프트 보기). value 가 비면 펼치지 않았다."""
    where: str = ""
    raw: str = ""
    value: str = ""
    note: str = ""


@dataclass
class MacroEnv:
    """펼칠 값 묶음 (저장하지 않는다). dynamic 이 거짓이면 화마다 바뀌는 매크로를 펼치지 않는다 (앞쪽 블록의 작가 메모, 정할 것 11)."""
    user: str = ""
    pov: str = ""
    pov_fallback: bool = False
    names: list[tuple[str, str]] = field(default_factory=list)
    episode: int = 0
    stats: list[tuple[str, str, str, str]] = field(default_factory=list)  # (인물 id, 인물 이름, 스탯 이름, 값)
    dynamic: bool = True
    note: str = ""  # 값의 시점 알림 (n-1화 스냅샷이 없어 지금 값을 씀, context.view_before)
    uses: list[MacroUse] = field(default_factory=list)  # 이 묶음으로 펼친 쓰임을 모은다 (elements.describe 가 더한다)

    def name_of(self, cid: str) -> str:
        return next((n for i, n in self.names if i == cid), "")


def has(text: str) -> bool:
    return "{{" in (text or "")


def _front(raw: str) -> str:
    return f"메모 칸은 매 화 같은 앞쪽 블록이라 '{raw}'를 펼치지 않았어요."


def _getvar(arg: str, env: MacroEnv) -> tuple[str | None, str]:
    """(값, 경고). 값이 None 이면 그대로 둔다. 인물 id · 이름 가운데 인자 앞부분과 '.' 까지 맞는 가장 긴 것을 고르고 나머지를 스탯 이름으로 본다 (정할 것 7)."""
    arg = arg.strip()
    keys = sorted({k for pair in env.names for k in pair if k}, key=len, reverse=True)
    who = next((k for k in keys if arg.startswith(k + ".")), "")
    if not who:
        return None, f"'{arg}'에서 인물을 찾지 못해 그대로 보냈어요. '인물.스탯' 꼴로 적어요."
    cid = next(i for i, n in env.names if who in (i, n))
    name, stat = env.name_of(cid) or cid, arg[len(who) + 1:].strip()
    hit = next((v for i, _, s, v in env.stats if i == cid and s == stat), None)
    if hit is None:
        return None, f"{name}의 상태창에 '{stat}'이(가) 없어 그대로 보냈어요."
    if not hit.strip():
        return "", f"{name}의 상태창 '{stat}' 값이 비어 빈 글을 넣었어요."
    return hit, env.note


def _one(body: str, raw: str, env: MacroEnv, char: str) -> tuple[str | None, str]:
    """매크로 하나의 (값, 경고). 값이 None 이면 그대로 둔다."""
    name, _, arg = body.partition("::")
    key = name.strip().lower()
    if key == "user":
        return (env.user, "") if env.user else (None, "주인공이 없어 '{{user}}'를 그대로 보냈어요.")
    if key in ("char", "bot"):
        if not env.dynamic:
            return None, _front(raw)
        if char:
            return char, ""
        if env.pov:
            return env.pov, "시점 인물이 없어 '{{char}}'에 주인공을 넣었어요." if env.pov_fallback else ""
        return None, "이어진 인물도 시점 인물도 없어 '{{char}}'를 그대로 보냈어요."
    if key == "getvar":
        if not env.dynamic:
            return None, _front(raw)
        return _getvar(arg, env)
    if key == "episode":
        return (str(env.episode), "") if env.dynamic else (None, _front(raw))
    if key == "chatindex":
        return None, "'{{chatindex}}' 대신 '{{episode}}'를 쓰세요. 그대로 보냈어요."
    if _SETVAR.match(key):
        return None, f"'{{{{{key}}}}}'로는 값을 바꾸지 않아요. Canon 매크로는 값을 읽기만 해요."
    return None, f"'{raw}'은(는) Canon이 모르는 매크로라 그대로 보냈어요."


def _token_end(text: str, start: int) -> int:
    """start 의 '{{' 로 연 표시가 닫히는 '}}' 뒤 자리 (안에 겹친 {{…}} 를 센다). 닫히지 않으면 글 끝."""
    depth, i = 0, start
    while i < len(text) - 1:
        two = text[i:i + 2]
        if two == "{{":
            depth, i = depth + 1, i + 2
        elif two == "}}":
            depth, i = depth - 1, i + 2
            if depth == 0:
                return i
        else:
            i += 1
    return len(text)


def expand(text: str, env: MacroEnv, where: str = "", char: str = "") -> tuple[str, list[MacroUse]]:
    """펼친 글과 쓰임 목록. 매크로가 없으면 글을 그대로 돌려준다. char 는 {{char}} 에 넣을 항목의 인물 이름 (비면 시점 인물)."""
    if not has(text):
        return text, []
    uses: list[MacroUse] = []
    slots: list[tuple[str, str]] = []  # 자리표마다 (원문, 펼친 글)

    def mark(raw: str, out: str) -> str:
        slots.append((raw, out))
        return _MARK.format(len(slots) - 1)

    def raw_of(s: str) -> str:
        return _MARKS.sub(lambda m: slots[int(m.group(1))][0], s)

    def out_of(s: str) -> str:
        return _MARKS.sub(lambda m: slots[int(m.group(1))][1], s)

    # 블록: 여는 표시부터 맞는 닫는 표시까지 통째로 그대로 둔다 (정할 것 5). 닫는 표시가 없으면 여는 표시만 둔다
    work, pos = "", 0
    for m in _BLOCK_OPEN.finditer(text):
        if m.start() < pos:
            continue
        head_end = _token_end(text, m.start())
        close = re.search(r"\{\{/\s*" + re.escape(m.group(1)) + r"[^{}]*\}\}", text[head_end:]) if m.group(1) else None
        end = head_end + close.end() if close else head_end
        block = text[m.start():end]
        uses.append(MacroUse(where=where, raw=block if len(block) <= 80 else block[:79] + "…",
                             note=f"'{{{{#{m.group(1)}}}}}' 조건 블록은 쓰지 않아요. 블록을 그대로 보냈어요."))
        work += text[pos:m.start()] + mark(block, block)
        pos = end
    work += text[pos:]
    for _ in range(MAX_PASSES):
        found = False

        def one(m: re.Match) -> str:
            nonlocal found
            found = True
            raw = raw_of(m.group(0))
            value, note = _one(out_of(m.group(1)), raw, env, char)
            uses.append(MacroUse(where=where, raw=raw, value=value or "", note=note))
            return mark(raw, raw if value is None else value)

        work = _INNER.sub(one, work)
        if not found:
            break
    return out_of(work), uses
