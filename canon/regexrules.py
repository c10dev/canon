"""정규식 규칙 묶음. 작가가 만든 경고(warn) · 고침(fix) 규칙을 묶음으로 저장하고, 작품마다 켠 묶음을 본문에 건다.

묶음 하나가 <CANON_HOME>/.rules/<id>.json 파일 하나다 (CANON_RULES 로 경로 변경). 모양은 canon/library.py 와 같다.
작품은 Settings.rule_bundles 에 묶음 id 만 적는다. 묶음을 고치면 켠 작품 모두에 바로 적용된다.

규칙의 in · out 은 RisuAI 정규식 스크립트와 같은 JavaScript 꼴로 저장한다.
convert_in 이 찾을 정규식을, to_python 이 바꿀 글을 Python re 꼴로 바꾼다 (docs/context/specs/06-regex-rules.md).

규칙 걸기는 오래 사는 자식 프로세스(spawn) 하나에서 돌린다. re 는 도는 동안 GIL 을 놓지 않아 스레드로는 시간 한도를 둘 수 없다.
한 번의 걸기가 TIME_LIMIT 초를 넘으면 자식을 끝내고(다음 걸기 때 새로 띄움) 본문을 걸기 전 그대로 둔다.
"""
from __future__ import annotations

import atexit
import json
import logging
import multiprocessing
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import store
from .schema import ConsistencyIssue, Episode, Project, RegexRule, RuleBundle, RuleBundleVersion, RuleChange, RuleRun

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
VERSION_KEEP = 30  # 묶음마다 남기는 버전 수 (library.VERSION_KEEP 과 같다)
RULE_RUN_KEEP = 50  # 화마다 남기는 규칙 걸기 기록 수 (pipeline.EDIT_KEEP 과 같다)
MAX_IN = 500  # 찾을 정규식 길이 한도
TIME_LIMIT = 2.0  # 규칙 걸기 한 번의 시간 한도 (초). 자식 프로세스를 띄우는 시간은 넣지 않는다
START_LIMIT = 60.0  # 자식 프로세스가 준비될 때까지 기다리는 한도 (초)
FLAG_CHARS = "gimsud"
# re.compile 이 낼 수 있는 오류. a{4294967296} 은 OverflowError, 아주 깊은 묶음은 RecursionError 다
_BAD_PATTERN = (re.error, OverflowError, RecursionError, ValueError)
REFUSE = "이 정규식은 저장할 수 없어요: "

_log = logging.getLogger("canon")


class RuleSkipped(Exception):
    """hits(strict=True) 가 규칙을 걸지 못했을 때 낸다 (시간 한도 · 일꾼 오류 · 없는 규칙). str 은 화면에 보일 이유다.
    걸었는데 맞은 곳이 없으면 내지 않고 빈 목록을 돌려준다."""


# ---------- 저장소 ----------

def root() -> Path:
    return Path(os.environ.get("CANON_RULES") or store.ROOT / ".rules")


def _path(bid: str) -> Path:
    if not ID_RE.match(bid or ""):
        raise KeyError(f"규칙 묶음이 없어요: {bid}")
    return root() / f"{bid}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def exists(bid: str) -> bool:
    return bool(ID_RE.match(bid or "")) and _path(bid).exists()


def load(bid: str) -> RuleBundle:
    path = _path(bid)
    if not path.exists():
        raise KeyError(f"규칙 묶음이 없어요: {bid}")
    return RuleBundle.model_validate_json(path.read_text(encoding="utf-8"))


def _dump(b: RuleBundle) -> str:
    return b.model_dump_json(indent=2, by_alias=True)  # RegexRule.in_ 을 JSON 키 in 으로 쓴다


def save(b: RuleBundle, note: str = "") -> RuleBundle:
    """저장한다. 규칙 목록이 마지막 버전과 다르면 새 버전을 남긴다. 규칙 검사(validate)는 부르는 쪽이 한다."""
    b.name = b.name.strip()
    if not b.name:
        raise ValueError("묶음 이름을 입력해 주세요")
    b.created_at = b.created_at or _now()
    b.updated_at = _now()
    _snapshot(b, note)
    path = _path(b.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    store.write_atomic(path, _dump(b))
    return b


def _snapshot(b: RuleBundle, note: str) -> bool:
    last = b.versions[-1] if b.versions else None
    if last and last.rules == b.rules:
        return False
    if not note:
        note = _change_note(last.rules if last else None, b.rules)
    b.version = max([v.number for v in b.versions], default=0) + 1
    b.versions = (b.versions + [RuleBundleVersion(number=b.version, at=_now(), note=note.strip()[:200],
                                                  rules=[r.model_copy(deep=True) for r in b.rules])])[-VERSION_KEEP:]
    return True


def _label(r: RegexRule) -> str:
    return r.comment or r.in_ or r.id


def _diff(a: list[RegexRule], b: list[RegexRule]) -> dict:
    """a → b 에서 더한 · 뺀 · 고친 규칙 이름."""
    old, new = {r.id: r for r in a}, {r.id: r for r in b}
    return {"added": [_label(r) for r in b if r.id not in old],
            "removed": [_label(r) for r in a if r.id not in new],
            "changed": [_label(r) for r in b if r.id in old and old[r.id] != r]}


def _change_note(a: Optional[list[RegexRule]], b: list[RegexRule]) -> str:
    if a is None:
        return "처음 만듦"
    d = _diff(a, b)
    parts = [f"{', '.join(d[k])} {word}" for k, word in (("added", "더함"), ("removed", "뺌"), ("changed", "고침")) if d[k]]
    return " · ".join(parts) if parts else "차례 바꿈"


def entries() -> list[RuleBundle]:
    d = root()
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json"):
        try:
            out.append(RuleBundle.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue  # 손으로 고치다 깨진 파일은 목록에서만 빠진다
    return sorted(out, key=lambda b: b.updated_at, reverse=True)


def check(rules: list[RegexRule]) -> list[str]:
    """묶음의 규칙 모두를 검사한다. 오류마다 '<규칙 이름> · 이 정규식은 저장할 수 없어요: …'."""
    out = []
    for k, r in enumerate(rules, 1):
        for e in validate(r):
            out.append(f"{r.comment or f'{k}번 규칙'} · {e}")
    return out


def create(name: str, notes: str = "", rules: Optional[list[RegexRule]] = None, note: str = "처음 만듦") -> RuleBundle:
    rules = list(rules or [])
    errors = check(rules)
    if errors:
        raise ValueError("\n".join(errors))
    return save(RuleBundle(id=uuid.uuid4().hex[:12], name=name, notes=notes, rules=rules), note)


def update(bid: str, name: str, notes: str, rules: list[RegexRule], note: str = "") -> RuleBundle:
    errors = check(rules)
    if errors:
        raise ValueError("\n".join(errors))
    b = load(bid)
    b.name, b.notes, b.rules = name, notes, list(rules)
    return save(b, note)


def delete(bid: str) -> None:
    """묶음을 지운다. 켠 작품은 그 id 를 건너뛰고 화면에 '찾을 수 없는 묶음' 으로 알린다."""
    path = _path(bid)
    if not path.exists():
        raise KeyError(f"규칙 묶음이 없어요: {bid}")
    path.unlink()


def versions(b: RuleBundle) -> list[dict]:
    """버전 목록 (최근 것 먼저). 버전마다 바로 앞 버전과 견준 더한 · 뺀 · 고친 규칙 이름을 붙인다."""
    out = []
    for i, v in enumerate(b.versions):
        prev = b.versions[i - 1] if i else None
        out.append({"number": v.number, "at": v.at, "note": v.note, "current": v.number == b.version,
                    "rules": len(v.rules), **(_diff(prev.rules, v.rules) if prev else {"added": [], "removed": [], "changed": []})})
    return out[::-1]


def restore(bid: str, number: int) -> RuleBundle:
    """예전 버전의 규칙 목록으로 되돌린다. 기록은 지우지 않고 되돌린 상태를 새 버전으로 남긴다."""
    b = load(bid)
    v = next((x for x in b.versions if x.number == number), None)
    if v is None:
        raise KeyError(f"{number}번 버전이 없어요 (최근 {VERSION_KEEP}개만 남겨요)")
    if v.rules == b.rules:
        raise ValueError("지금 규칙과 같은 버전이에요")
    b.rules = [r.model_copy(deep=True) for r in v.rules]
    return save(b, f"{number}번 버전으로 되돌림")


def used_by(bid: str) -> list[str]:
    """이 묶음을 켠 작품 폴더 이름들."""
    out = []
    if store.ROOT.exists():
        for d in sorted(store.ROOT.iterdir()):
            f = d / "project.json"
            if not f.exists():
                continue
            try:
                if bid in (json.loads(f.read_text(encoding="utf-8")).get("settings") or {}).get("rule_bundles", []):
                    out.append(d.name)
            except (OSError, ValueError, AttributeError, TypeError):
                continue
    return out


def summary(b: RuleBundle) -> dict:
    """목록 한 줄. warn · fix 는 action 별 규칙 수 (fix 에 내보내기 규칙도 든다), export 는 내보내기 규칙 수, used_by 는 켠 작품 수."""
    return {"id": b.id, "name": b.name, "notes": b.notes, "rules": len(b.rules),
            "warn": sum(r.action == "warn" for r in b.rules), "fix": sum(r.action == "fix" for r in b.rules),
            "export": sum(r.type == "export" for r in b.rules), "used_by": len(used_by(b.id)),
            "version": b.version, "created_at": b.created_at, "updated_at": b.updated_at}


# ---------- 문법 ----------

def convert_in(js: str) -> str:
    """찾을 정규식을 JavaScript 꼴에서 Python 꼴로: (?<이름> → (?P<이름>, \\k<이름> → (?P=이름).
    반복 {n} · {n,} · {n,m} 으로 읽히지 않는 { 는 \\{ 로 바꾼다 (JavaScript 는 글자 그대로 읽고, Python 은 {,3} 을 반복으로 읽는다).
    뒤 보기 (?<= · (?<!, 이스케이프된 글자, [...] 안의 글자는 그대로 둔다."""
    out, i, n, in_class = [], 0, len(js), False
    while i < n:
        c = js[i]
        if c == "\\":
            if not in_class and js.startswith("\\k<", i):
                j = js.find(">", i + 3)
                if j != -1:
                    out.append(f"(?P={js[i + 3:j]})")
                    i = j + 1
                    continue
            out.append(js[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif js.startswith("(?<", i) and i + 3 < n and js[i + 3] not in "=!":
            out.append("(?P<")
            i += 3
            continue
        elif c == "{" and not _brace(js, i):
            out.append("\\{")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def flags(flag: str) -> tuple[int, bool]:
    """플래그 글자를 (re 플래그, 모든 자리) 로. g 는 모든 자리, i · m · s 는 re 값, u · d 와 모르는 글자는 버린다."""
    f = 0
    for c, v in (("i", re.IGNORECASE), ("m", re.MULTILINE), ("s", re.DOTALL)):
        if c in (flag or ""):
            f |= v
    return f, "g" in (flag or "")


_DIGITS = "0123456789"


def to_python(out: str, rx: re.Pattern) -> Callable[[re.Match], str]:
    """바꿀 글(JavaScript String.replace 꼴)을 맞은 곳마다 부를 함수로 바꾼다.
    RisuAI 처럼 $n 을 먼저 모두 줄바꿈으로 바꾸고 ($$n 은 $ + 줄바꿈), {{data}} 를 $& 로 읽는다.
    그 뒤 $$ · $& · $` · $' · $1~$99 · $<이름> 을 JavaScript 와 같게 푼다. 역슬래시는 글자 그대로다."""
    s = out.replace("$n", "\n").replace("{{data}}", "$&")
    count, named = rx.groups, rx.groupindex
    parts: list = []  # 글 조각(str) 또는 ("g", 번호) · ("name", 이름) · ("pre",) · ("post",)
    buf: list[str] = []

    def push(x) -> None:
        if buf:
            parts.append("".join(buf))
            buf.clear()
        parts.append(x)

    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "$" or i + 1 >= n:
            buf.append(c)
            i += 1
            continue
        d = s[i + 1]
        if d == "$":
            buf.append("$")
            i += 2
        elif d == "&":
            push(("g", 0))
            i += 2
        elif d == "`":
            push(("pre",))
            i += 2
        elif d == "'":
            push(("post",))
            i += 2
        elif d in _DIGITS:
            two = s[i + 1:i + 3]
            if len(two) == 2 and two[1] in _DIGITS and 1 <= int(two) <= count:
                push(("g", int(two)))
                i += 3
            elif 1 <= int(d) <= count:
                push(("g", int(d)))
                i += 2
            else:
                buf.append("$")
                i += 1
        elif d == "<" and named and s.find(">", i + 2) != -1:
            j = s.find(">", i + 2)
            push(("name", s[i + 2:j]))
            i = j + 1
        else:
            buf.append("$")
            i += 1
    if buf:
        parts.append("".join(buf))

    def replace(m: re.Match) -> str:
        res = []
        for x in parts:
            if isinstance(x, str):
                res.append(x)
            elif x[0] == "g":
                res.append(m.group(x[1]) or "")
            elif x[0] == "name":
                res.append((m.group(x[1]) or "") if x[1] in named else "")
            elif x[0] == "pre":
                res.append(m.string[:m.start()])
            else:
                res.append(m.string[m.end():])
        return "".join(res)

    return replace


def _python_only(js: str) -> str:
    """JavaScript 에 없고 Python 에만 있는 문법을 찾는다. 없으면 빈 글."""
    i, n, in_class, quantified = 0, len(js), False, False  # quantified: 바로 앞이 반복 기호
    while i < n:
        c = js[i]
        if c == "\\":
            if js[i + 1:i + 2] in ("A", "Z"):
                return f"\\{js[i + 1]}"
            i, quantified = i + 2, False
            continue
        if in_class:
            in_class = c != "]"
            i += 1
            continue
        if js.startswith("(?P", i):
            return "(?P…)"
        if js.startswith("(?>", i):
            return "(?>…)"
        end = _brace(js, i) if c == "{" else 0
        if c in "+*?" or end:
            if quantified and c == "+":
                return "반복 뒤의 +(소유 반복)"
            if quantified and c == "?":  # a+? 는 게으른 반복
                quantified, i = False, i + 1
                continue
            quantified, i = True, end or i + 1
            continue
        quantified = False
        in_class = c == "["
        i += 2 if js.startswith("(?", i) else 1  # (? 의 ? 는 반복이 아니다
    return ""


_BRACE = re.compile(r"\{(\d+)(,(\d*))?\}")


def _brace(js: str, i: int) -> int:
    """i 에서 시작하는 {n} · {n,} · {n,m} 반복의 끝 다음 자리. 반복이 아니면 0."""
    m = _BRACE.match(js, i)
    return m.end() if m else 0


def _nested(js: str) -> bool:
    """겹친 반복: 끝없는 반복(+ · * · {n,})이 든 묶음을 다시 끝없이 반복하거나, 같은 갈래가 둘인 묶음을 끝없이 반복한다.
    예: (a+)+ · (a*)* · (a|a)* · (\\w+\\s?)+"""
    stack: list[dict] = [{"open": -1, "loose": False, "bars": []}]  # loose: 안에 끝없는 반복이 있음
    i, n, in_class, last = 0, len(js), False, None  # last: 바로 앞에서 닫힌 묶음
    while i < n:
        c = js[i]
        if c == "\\":
            i, last = i + 2, None
            continue
        if in_class:
            in_class = c != "]"
            i += 1
            continue
        end = _brace(js, i) if c == "{" else 0
        if c in "+*?" or end:
            if end:
                m = _BRACE.match(js, i)
                loose, nxt = m.group(2) is not None and m.group(3) == "", end
            else:
                loose, nxt = c in "+*", i + 1
            if loose:
                if last is not None and (last["loose"] or len(set(last["branches"])) < len(last["branches"])):
                    return True
                stack[-1]["loose"] = True
            last, i = None, nxt
            continue
        last = None
        if c == "[":
            in_class = True
        elif c == "(":
            stack.append({"open": i, "loose": False, "bars": []})
            if js.startswith("(?", i):  # (?: · (?= · (?<이름> … 의 머리를 건너뛴다
                m = re.match(r"\(\?(?:<[A-Za-z_]\w*>|<[=!]|[:=!])?", js[i:])
                stack[-1]["head"] = m.end()
                i += m.end()
                continue
        elif c == "|":
            stack[-1]["bars"].append(i)
        elif c == ")" and len(stack) > 1:
            g = stack.pop()
            cuts = [g["open"] + g.get("head", 1) - 1] + g["bars"] + [i]
            g["branches"] = [js[a + 1:b] for a, b in zip(cuts, cuts[1:])]
            stack[-1]["loose"] = stack[-1]["loose"] or g["loose"]
            last = g
        i += 1
    return False


def validate(rule: RegexRule) -> list[str]:
    """저장을 막는 오류 목록. 모두 '이 정규식은 저장할 수 없어요: ' 로 시작한다. 찾을 정규식이 빈 규칙은 걸지 않으므로 막지 않는다."""
    out: list[str] = []
    flag = rule.flag or ""
    if "<" in flag or ">" in flag:
        out.append("플래그에 꺾쇠 메타(<order N> · <cbs> 등)는 넣을 수 없어요. 거는 차례는 목록 차례로 정해요")
    else:
        bad = "".join(dict.fromkeys(c for c in flag if c not in FLAG_CHARS))
        if bad:
            extra = " y(sticky) · v(유니코드 집합)는 Python에 맞는 뜻이 없어요." if set(bad) & set("yv") else ""
            out.append(f"받지 않는 플래그예요: {bad}.{extra} g · i · m · s · u · d 만 쓸 수 있어요")
    if rule.out.startswith("@@"):
        out.append("RisuAI 특수 명령(@@…)은 받지 않아요")
    if rule.type == "export" and rule.action == "warn":
        out.append("내보내기 규칙은 고침으로만 쓸 수 있어요")
    pat = rule.in_
    if pat:
        if len(pat) > MAX_IN:
            out.append(f"찾을 정규식은 {MAX_IN}자까지예요 (지금 {len(pat)}자)")
        else:
            only = _python_only(pat)
            if only:
                out.append(f"Python에만 있는 문법은 쓸 수 없어요: {only}. JavaScript 정규식 꼴로 적어 주세요")
            try:
                re.compile(convert_in(pat), flags(flag)[0])
            except _BAD_PATTERN as e:
                if "\\p{" in pat or "\\P{" in pat:
                    out.append("\\p{…}는 쓸 수 없어요. 한글은 [가-힣], 글자 전체는 [^\\W\\d_] 처럼 바꿔 적어 주세요")
                elif isinstance(e, OverflowError):
                    out.append("정규식 문법이 틀렸어요 (반복 횟수가 너무 커요)")
                elif isinstance(e, RecursionError):
                    out.append("정규식 문법이 틀렸어요 (묶음이 너무 깊이 겹쳤어요)")
                else:
                    out.append(f"정규식 문법이 틀렸어요 ({e})")
            else:
                if not only and _nested(pat):
                    out.append("반복 안에 또 반복이 있어 아주 느려질 수 있어요 (예: (a+)+). 바깥 반복을 빼거나 안쪽 반복을 줄여 주세요")
    return [REFUSE + e for e in out]


_MACRO = re.compile(r"\{\{(?!data\}\})")


def notices(rule: RegexRule) -> list[str]:
    """저장은 막지 않는 알림."""
    out = []
    if rule.action == "fix" and _MACRO.search(rule.out):
        out.append("바꿀 글의 {{…}}는 풀지 않고 글자 그대로 넣어요")
    return out


# ---------- 자식 프로세스 ----------
# 부모 → 자식: (op, text, steps). steps 는 (묶음 이름, 찾을 정규식(Python 꼴), re 플래그, 모든 자리, 바꿀 글) 튜플 목록
# 자식 → 부모: ("ready",) 한 번, 걸기마다 ("at", 묶음 이름) 여러 번 뒤 ("done", 결과)

def _touch(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """두 자리 [시작, 끝) 이 겹치는지. 빈 자리(지우기 뒤 · 끼워 넣기)는 다른 자리 안쪽에 있거나 같은 점일 때 겹친다."""
    (s1, e1), (s2, e2) = a, b
    if s1 < e1 and s2 < e2:
        return s1 < e2 and s2 < e1
    if s1 == e1 and s2 == e2:
        return s1 == s2
    x, (s, e) = (s1, b) if s1 == e1 else (s2, a)
    return s < x < e


def _fix(text: str, steps: list, conn) -> tuple[str, list]:
    """고침 규칙을 차례로 건다. 돌려주는 바뀐 곳은 [규칙 차례 목록, start, before, after] 이고 start 순서다.
    바뀐 곳들은 마지막 본문 안에서 서로 겹치지 않는다. start 는 마지막 본문 안 자리, before 는 걸기 전 본문의 그 자리 글이다.
    뒤 규칙이 맞은 곳이 앞서 바뀐 곳과 겹치면 둘을 바뀐 곳 하나로 합친다: 두 자리를 합친 구역의 걸기 전 글 → 지금 글.
    그래서 바뀐 곳 하나를 되돌려도, 한 번 전체를 되돌려도 걸기 전 글이 그대로 돌아온다. 합쳐서 전후 글이 같아지면 뺀다."""
    changes: list[list] = []  # [규칙 차례 목록, start, before, after]. 지금 본문 안 자리, start 순서, 겹치지 않음
    at = None
    for k, (name, pat, fl, glob, out) in enumerate(steps):
        if name != at:
            at = name
            conn.send(("at", name))
        try:
            rx = re.compile(pat, fl)
        except _BAD_PATTERN:
            continue
        rep = to_python(out, rx)
        new = []  # (start, end, after): 이 규칙 걸기 전 본문 안 자리
        for m in rx.finditer(text):
            after = rep(m)
            if after != m.group(0):
                new.append((m.start(), m.end(), after))
            if not glob:
                break
        if not new:
            continue
        # 앞서 바뀐 곳(E)과 이번에 맞은 곳(N)을 시작 자리 순서로 늘어놓고, 서로 겹치는 것끼리 한 구역으로 묶는다
        items = sorted([("E", c[1], c[1] + len(c[3]), c) for c in changes] + [("N", s0, e0, a) for s0, e0, a in new],
                       key=lambda x: (x[1], x[2]))
        groups: list[list] = []
        for it in items:
            g = groups[-1] if groups else None
            if g and any(o[0] != it[0] and _touch((o[1], o[2]), (it[1], it[2])) for o in g):
                g.append(it)
            else:
                groups.append([it])
        merged, pieces, last, delta = [], [], 0, 0
        for g in groups:
            us, ue = min(x[1] for x in g), max(x[2] for x in g)
            olds = [x for x in g if x[0] == "E"]
            news = [x for x in g if x[0] == "N"]
            region, orig, pos = [], [], us  # region: 이번 규칙 뒤 글, orig: 걸기 전 글
            for x in sorted(news, key=lambda x: (x[1], x[2])):
                region += [text[pos:x[1]], x[3]]
                pos = x[2]
            region.append(text[pos:ue])
            pos = us
            for x in olds:
                orig += [text[pos:x[1]], x[3][2]]
                pos = x[2]
            orig.append(text[pos:ue])
            region_s, orig_s = "".join(region), "".join(orig)
            pieces += [text[last:us], region_s]
            last = ue
            if not news:
                c = olds[0][3]
                merged.append([c[0], us + delta, c[2], c[3]])
            elif orig_s != region_s:
                ks = list(dict.fromkeys([i for x in olds for i in x[3][0]] + [k]))
                merged.append([ks, us + delta, orig_s, region_s])
            delta += len(region_s) - (ue - us)
        pieces.append(text[last:])
        text = "".join(pieces)
        changes = merged
    return text, changes


def _hits(text: str, steps: list, conn) -> list:
    """경고 규칙마다 맞은 곳의 시작 자리 (규칙 차례, start)."""
    out, at = [], None
    for k, (name, pat, fl, glob, _) in enumerate(steps):
        if name != at:
            at = name
            conn.send(("at", name))
        try:
            rx = re.compile(pat, fl)
        except _BAD_PATTERN:
            continue
        for m in rx.finditer(text):
            out.append((k, m.start()))
            if not glob:
                break
    return out


def _serve(conn) -> None:
    """자식 프로세스 본체. 부모가 None 을 보내거나 파이프를 닫으면 끝난다."""
    conn.send(("ready",))
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        op, text, steps = msg
        try:
            conn.send(("done", (_fix if op == "fix" else _hits)(text, steps, conn)))
        except Exception as e:  # noqa: BLE001 — 부모는 이것을 시간 초과처럼 다룬다
            conn.send(("error", repr(e)))


_lock = threading.Lock()
_proc = None
_conn = None


def _discard() -> None:
    global _proc, _conn
    if _proc is not None:
        try:
            _proc.kill()
            _proc.join(5)
        except (OSError, ValueError, AssertionError):
            pass
    if _conn is not None:
        try:
            _conn.close()
        except OSError:
            pass
    _proc = _conn = None


def _ensure():
    """살아 있는 자식 프로세스의 파이프. 없으면 띄우고 준비될 때까지 기다린다. 못 띄우면 None."""
    global _proc, _conn
    if _proc is not None and _proc.is_alive():
        return _conn
    _discard()
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_serve, args=(child,), daemon=True, name="canon-regexrules")
    try:
        proc.start()
    except (OSError, RuntimeError) as e:
        _log.warning("정규식 규칙 일꾼을 띄우지 못했어요: %s", e)
        return None
    child.close()
    _proc, _conn = proc, parent
    try:
        if parent.poll(START_LIMIT) and parent.recv() == ("ready",):
            return parent
    except (EOFError, OSError):
        pass
    _log.warning("정규식 규칙 일꾼이 준비되지 않았어요")
    _discard()
    return None


def worker_alive() -> bool:
    """자식 프로세스가 떠 있는지 (시험용)."""
    return _proc is not None and _proc.is_alive()


def shutdown() -> None:
    """자식 프로세스를 닫는다. 프로세스가 끝날 때 atexit 로 부른다."""
    with _lock:
        if _conn is not None:
            try:
                _conn.send(None)
                _proc.join(1)
            except (OSError, ValueError, AttributeError):
                pass
        _discard()


atexit.register(shutdown)


def _call(op: str, text: str, steps: list):
    """자식 프로세스에 걸기 한 번을 맡긴다. (결과, '') 또는 시간 한도를 넘거나 자식이 죽었으면 (None, 멈춘 묶음 이름)."""
    with _lock:
        at = steps[0][0]
        conn = _ensure()
        if conn is None:
            return None, at
        try:
            conn.send((op, text, steps))
            deadline = time.monotonic() + TIME_LIMIT
            while True:
                left = deadline - time.monotonic()
                if left <= 0 or not conn.poll(left):
                    break
                kind, value = conn.recv()
                if kind == "at":
                    at = value
                elif kind == "done":
                    return value, ""
                else:
                    _log.warning("정규식 규칙 일꾼 오류: %s", value)
                    break
        except (EOFError, OSError, ValueError):
            pass
        _discard()  # 한도를 넘었거나 죽은 일꾼은 버리고, 다음 걸기 때 새로 띄운다
        return None, at


# ---------- 걸기 ----------

def bundles_of(p: Project) -> list[RuleBundle]:
    """작품이 켠 묶음 (Settings.rule_bundles 차례). 없거나 깨진 묶음은 건너뛴다."""
    out = []
    for bid in p.settings.rule_bundles:
        try:
            out.append(load(bid))
        except (KeyError, ValueError):
            continue
    return out


def missing(p: Project) -> list[str]:
    """작품이 켰는데 찾을 수 없는 묶음 id."""
    return [bid for bid in p.settings.rule_bundles if not exists(bid)]


def _steps(pairs: list[tuple[RuleBundle, RegexRule]]) -> list:
    out = []
    for b, r in pairs:
        fl, glob = flags(r.flag)
        out.append((b.name, convert_in(r.in_), fl, glob, r.out))
    return out


def _pick(bundles: list[RuleBundle], type_: str, action: str) -> list[tuple[RuleBundle, RegexRule]]:
    return [(b, r) for b in bundles for r in b.rules if r.enabled and r.in_ and r.type == type_ and r.action == action]


def _apply(pairs: list[tuple[RuleBundle, RegexRule]], text: str) -> tuple[str, list[RuleChange], str]:
    """(바뀐 본문, 바뀐 곳, 멈춘 묶음 이름). 멈추면 본문은 그대로다."""
    if not pairs or not text:
        return text, [], ""
    res, at = _call("fix", text, _steps(pairs))
    if res is None:
        _log.warning("규칙 묶음 '%s' 을 거는 데 %s초가 넘게 걸려 건너뛰었어요", at, TIME_LIMIT)
        return text, [], at
    new, raw = res
    changes = []
    for ks, start, before, after in raw:
        b, r = pairs[ks[-1]]  # 합친 곳은 마지막에 건 규칙 것으로 둔다
        name = " · ".join(dict.fromkeys(pairs[i][1].comment for i in ks if pairs[i][1].comment))
        changes.append(RuleChange(bundle=b.id, version=b.version, rule=r.id, name=name, start=start, before=before, after=after))
    return new, changes, ""


def run(p: Project, text: str, kind: str) -> tuple[str, Optional[RuleRun]]:
    """작품이 켠 묶음의 고침 규칙(type output)을 차례로 건다. (바뀐 본문, 기록).
    바뀐 곳이 없고 건너뛰지도 않았으면 기록은 None. 시간 한도를 넘으면 본문은 그대로, 기록의 skipped 에 묶음 이름.
    바뀐 곳의 start 는 마지막 본문 안 자리다 (_fix). 기록 id 는 화에 넣을 때 add_runs 가 붙인다."""
    if not p.settings.rule_bundles or not text:
        return text, None
    new, changes, skipped = _apply(_pick(bundles_of(p), "output", "fix"), text)
    if not changes and not skipped:
        return text, None
    return new, RuleRun(at=_now(), kind=kind, changes=changes, skipped=skipped)  # type: ignore[arg-type]


def export_text(p: Project, text: str) -> str:
    """내보내기 규칙(type export)을 건다. 기록하지 않는다 (publish.export)."""
    if not p.settings.rule_bundles or not text:
        return text
    return _apply(_pick(bundles_of(p), "export", "fix"), text)[0]


_SENT = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…][\"'”’」』)])\s+|\n+")


def _sentence(text: str, at: int) -> str:
    """at 자리를 품은 문장 (줄바꿈과 문장 끝 부호 뒤 빈칸에서 끊는다)."""
    start = 0
    for m in _SENT.finditer(text):
        if m.end() > at:
            if m.start() <= at:  # 끊는 빈칸 위에서 맞았으면 다음 문장
                start = m.end()
                continue
            return text[start:m.start()].strip()
        start = m.end()
    return text[start:].strip()


def _issues(pairs: list[tuple[RuleBundle, RegexRule]], text: str, n: int, strict: bool = False) -> list[ConsistencyIssue]:
    if not pairs or not text:
        return []
    res, at = _call("hits", text, _steps(pairs))
    if res is None:
        _log.warning("규칙 묶음 '%s' 의 경고 규칙을 찾는 데 %s초가 넘게 걸려 건너뛰었어요", at, TIME_LIMIT)
        if strict:
            raise RuleSkipped(f"경고 규칙을 거는 데 시간 한도({TIME_LIMIT:g}초)를 넘겨 건너뛰었어요 (묶음: {at})")
        return []
    out, seen = [], set()
    for k, start in res:
        b, r = pairs[k]
        quote = _sentence(text, start)
        key = (b.id, r.id, quote)
        if not quote or key in seen:
            continue
        seen.add(key)
        out.append(ConsistencyIssue(type="표기", description=r.comment or "정규식 규칙에 걸렸어요", source_episode=n,
                                    source_quote=r.in_, current_quote=quote, severity="low", origin="regex",
                                    regex_rule=f"{b.id}/{r.id}"))
    return out


RULE_GONE = "그 경고 규칙을 찾을 수 없어요. 묶음을 껐거나 규칙을 지우거나 고쳤을 수 있어요"


def hits(p: Project, text: str, n: int, only: str = "", strict: bool = False) -> list[ConsistencyIssue]:
    """작품이 켠 경고 규칙(type output)이 본문에 걸린 곳. 걸린 문장마다 지적 하나 (같은 규칙 · 같은 문장은 하나).
    only 를 주면 그 규칙('<묶음 id>/<규칙 id>')만 건다.
    strict 가 거짓이면 시간 한도를 넘거나 일꾼이 죽어도, only 규칙이 없어도 빈 목록이다.
    strict 가 참이면 그때 RuleSkipped 를 낸다. 그래서 빈 목록은 '걸었는데 맞은 곳이 없음' 만 뜻한다 (다시 검수가 쓴다).
    only 규칙이 없음: 묶음을 껐거나 지웠음, 규칙을 지웠거나 껐음, 경고 규칙이 아니게 됨, 찾을 정규식이 비었음."""
    if not text:
        return []
    pairs = _pick(bundles_of(p), "output", "warn") if p.settings.rule_bundles else []
    if only:
        pairs = [(b, r) for b, r in pairs if f"{b.id}/{r.id}" == only]
        if not pairs and strict:
            raise RuleSkipped(RULE_GONE)
    return _issues(pairs, text, n, strict)


def trial(rules: list[RegexRule], text: str, bid: str = "", name: str = "시험") -> dict:
    """규칙 시험 (저장하지 않음): 고침 규칙을 건 본문 · 바뀐 곳 · 그 본문의 경고 지적 · 내보내기 규칙까지 건 글."""
    b = RuleBundle(id=bid or "0" * 12, name=name, rules=list(rules))
    text2, changes, skipped = _apply(_pick([b], "output", "fix"), text)
    issues = [] if skipped else _issues(_pick([b], "output", "warn"), text2, 0)
    exported = text2 if skipped else _apply(_pick([b], "export", "fix"), text2)[0]
    return {"text": text2, "changes": [c.model_dump() for c in changes], "hits": [i.model_dump() for i in issues],
            "exported": exported, "skipped": skipped}


# ---------- 기록 · 되돌리기 ----------

def add_runs(runs: list[RuleRun], new: list[RuleRun]) -> list[RuleRun]:
    """runs 뒤에 new 를 붙인다. id 가 빈 기록에 r<N> 을 붙이고 최근 RULE_RUN_KEEP 개만 남긴다. new 는 그 자리에서 고친다."""
    nums = [int(r.id[1:]) for r in runs if r.id[1:].isdigit()]
    top = max(nums, default=0)
    for r in new:
        if not r.id:
            top += 1
            r.id = f"r{top}"
        r.at = r.at or _now()
    return (list(runs) + list(new))[-RULE_RUN_KEEP:]


def _run_of(ep: Episode, rid: str) -> RuleRun:
    r = next((x for x in ep.rule_runs if x.id == rid), None)
    if r is None:
        raise KeyError(f"규칙 걸기 기록이 없어요: {rid}")
    return r


def _undo(ep: Episode, run: RuleRun, c: RuleChange) -> None:
    """바뀐 곳 하나를 되돌리고, 같은 기록의 아직 되돌리지 않은 뒤쪽 바뀐 곳 자리를 글 길이 차이만큼 민다.
    기록의 바뀐 곳은 자리 순서이고 겹치지 않으므로(_fix) 목록에서 c 뒤에 있는 곳만 민다. 같은 자리의 빈 곳이 여럿이어도 차례가 맞다.
    지우기 규칙이 바꾼 곳(after 가 빈 글)은 locate 로 찾지 못해 자리가 맞아야 되돌릴 수 있다."""
    from . import pipeline

    if c.undone:
        raise ValueError("이미 되돌린 곳이에요")
    if c.after:
        at = pipeline.locate(ep.text, c.after, c.start)
        span = (at, at + len(c.after))
        if at != c.start and any(o is not c and not o.undone and _touch(span, (o.start, o.start + len(o.after))) for o in run.changes):
            raise ValueError("되돌릴 자리를 찾을 수 없어요")  # 가까운 같은 글이 같은 기록의 다른 바뀐 곳이다 (작가가 그 자리를 고쳤다)
    elif c.start <= len(ep.text):  # 지우기 규칙이 바꾼 곳은 그 자리에 다시 넣는다
        at = c.start
    else:
        raise ValueError("되돌릴 자리를 찾을 수 없어요")
    pipeline.before_change(ep)
    ep.text = ep.text[:at] + c.before + ep.text[at + len(c.after):]
    c.undone = True
    k = next(i for i, o in enumerate(run.changes) if o is c)
    for o in run.changes[k + 1:]:
        if not o.undone and o.start >= at + len(c.after):
            o.start += len(c.before) - len(c.after)


def undo_change(p: Project, n: int, rid: str, k: int) -> RuleChange:
    """규칙이 바꾼 곳 하나를 되돌린다 (pipeline.undo_edit 과 같은 길). 기록은 지우지 않고 undone 으로 둔다."""
    from . import pipeline

    ep = pipeline._editable(p, n)
    r = _run_of(ep, rid)
    if not 0 <= k < len(r.changes):
        raise KeyError(f"규칙 걸기 기록에 그 바뀐 곳이 없어요: {rid} · {k}")
    c = r.changes[k]
    _undo(ep, r, c)
    return c


def undo_run(p: Project, n: int, rid: str) -> tuple[list[RuleChange], list[RuleChange]]:
    """규칙 걸기 한 번을 거꾸로 하나씩 되돌린다. 그 뒤에 같은 자리를 또 고쳐 찾지 못한 곳은 남긴다. (되돌린 것, 남긴 것)."""
    from . import pipeline

    ep = pipeline._editable(p, n)
    r = _run_of(ep, rid)
    todo = [c for c in r.changes if not c.undone]
    if not todo:
        raise ValueError("이미 모두 되돌렸어요")
    done, left = [], []
    for c in reversed(todo):
        try:
            _undo(ep, r, c)
            done.append(c)
        except ValueError:
            left.append(c)
    if not done:
        raise ValueError("규칙으로 고친 뒤 같은 자리를 또 고쳐 되돌릴 수 없어요")
    return done, left
