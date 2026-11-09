"""보낸 집필 프롬프트 기록: 본문으로 채택한 집필 호출이 실제로 보낸 요청을 작품 폴더의 sent/<화>.json.gz 에 남긴다.

웹의 프롬프트 보기 · /context 는 지금 데이터로 프롬프트를 다시 만든다. 상태를 반영한 뒤에는 그 화가 실제로 받은 것과 다르다.
이 기록은 그 화가 받은 그대로를 남긴다. project.json 에는 넣지 않는다 (화당 수만 자라 작품 파일을 키운다).

- 무엇을: 시스템 프롬프트, 요청 글, 캐시 앞부분 경계(head_chars), 모델, 받은 시도 번호, 다시 부른 까닭.
- 언제: 본문을 실제로 저장할 때만 (keep). 다시 생성 · 다듬기 새 판은 hold 로 대기 칸에 두고, 작가가 고르면(adopt) 지금 기록이 된다.
  pipeline._write 는 재료(SentPrompt)만 채운다. write_scored · play_cues · 비교 · 실험 호출은 기록하지 않는다.
- 맞춤: 기록은 저장한 본문의 지문(basis, pipeline.text_basis)을 품는다. 작가가 고치거나 판 · 백업을 되돌려 본문이 바뀌면
  matches 가 거짓이 되어 화면이 '그 뒤로 본문이 바뀌었어요'를 알린다. 화를 넣거나 빼면 store.renumber_side_files 가 함께 옮긴다.
- 비밀 값: 설정의 API 키 값과 키 모양 글(AIza…, sk-ant-…)은 쓰기 전에 가린다 (masked 에 수를 적는다).
- 압축: gzip. 실제 작품 9화(요청 3.4만~5만 자, JSON 70~104KB)가 24~32KB 로 약 3배 줄었다 (2026-11-09).

LLM 을 부르지 않는다. 쓰기는 부르는 쪽이 jobs.project_lock 안에서 한다.
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import settings, store

_KEY_LIKE = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|sk-ant-[0-9A-Za-z_\-]{16,}")
MASK = "[가린 값]"


class SentRetry(BaseModel):
    """받지 않고 다시 부른 호출 하나."""
    call: int  # 이 집필의 몇 번째 호출이었나 (1부터)
    reason: Literal["cut", "thought", "meta", "polish", "tics"]  # 끊김 · 한글 적음 · 작업 설명뿐 · 대사 줄 바뀜 · 말줄임 늘어남
    note: str = ""


class SentPrompt(BaseModel):
    """본문 한 판을 낳은 집필 요청."""
    at: str = ""
    kind: Literal["write", "rewrite", "polish"] = "write"
    model: str = ""  # usage.model_id ('<백엔드>:<모델>')
    system: str = ""
    prompt: str = ""
    head_chars: int = 0  # prompt 앞 몇 글자가 캐시 앞부분(prompts.write_head)이었나. 0 이면 경계 없이 보냈다
    family: bool = False  # 백엔드가 캐시 가족 경계를 받았다 (Claude 는 시스템을 prompts.FAMILY_SYSTEM 으로 바꾸고 system 을 요청 앞에 둔다)
    tail: str = ""  # 실제 백엔드가 요청 끝에 붙이는 정책 줄 (llm.with_note). 가짜 응답(mock)은 붙이지 않는다
    attempt: int = 1  # 받은 호출 번호
    retries: list[SentRetry] = Field(default_factory=list)
    basis: str = ""  # 이 요청으로 저장한 본문의 지문 (pipeline.text_basis)
    chars: int = 0  # 그 본문 글자 수
    version: str = ""  # 새 판으로 둘 때 그 판 id (TextVersion.id)
    masked: int = 0  # 가린 비밀 값 수

    @property
    def head(self) -> str:
        return self.prompt[:self.head_chars]


class SentFile(BaseModel):
    episode: int
    current: Optional[SentPrompt] = None  # 지금 본문을 낳은 요청
    candidate: Optional[SentPrompt] = None  # 고르기를 기다리는 새 판을 낳은 요청


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _secrets() -> list[str]:
    out = []
    for get in (settings.api_key, settings.anthropic_key, settings.local_key):
        try:
            v = get()[0]
        except Exception:  # 설정 파일을 못 읽어도 기록은 남긴다 (모양 검사는 그대로 한다)
            continue
        if v and len(v) >= 8:
            out.append(v)
    return out


def mask(text: str) -> tuple[str, int]:
    """설정의 API 키 값과 키 모양 글을 가린다. (가린 글, 가린 수)."""
    count = 0
    for v in _secrets():
        if v in text:
            count += text.count(v)
            text = text.replace(v, MASK)
    text, k = _KEY_LIKE.subn(MASK, text)
    return text, count + k


def record(llm, system: str, prompt: str, head: str, attempt: int, retries: list[SentRetry]) -> SentPrompt:
    """pipeline._write 가 받은 응답의 요청을 기록 재료로 만든다. 저장하지 않는다."""
    from . import llm as llm_mod
    from . import usage

    family = bool(head and prompt.startswith(head) and getattr(llm, "family_cache", False))
    model = usage.model_id(llm)
    tail = "" if model == "mock:mock" else llm_mod.with_note(prompt)[len(prompt.rstrip()):]  # 가짜 응답은 정책 줄을 붙이지 않는다
    sent_head = prompt.startswith(head) and head
    system, a = mask(system)
    prompt, b = mask(prompt)
    head, _ = mask(head)  # 가린 뒤 길이로 경계를 잰다
    head_chars = len(head) if sent_head and prompt.startswith(head) else 0
    return SentPrompt(at=_now(), model=model, system=system, prompt=prompt, head_chars=head_chars,
                      family=family, tail=tail,
                      attempt=attempt, retries=list(retries), masked=a + b)


def path(name: str, n: int) -> Path:
    return store.sent_path(name, n)


def _read(name: str, n: int) -> SentFile:
    f = path(name, n)
    if f.exists():
        try:
            data = SentFile.model_validate_json(gzip.decompress(f.read_bytes()))
        except (OSError, EOFError, ValueError):
            pass
        else:  # 화를 넣고 빼면 파일만 옮긴다 (store.renumber_side_files). 안의 번호보다 파일 자리를 믿는다
            data.episode = n
            return data
    return SentFile(episode=n)


def _write(name: str, data: SentFile) -> None:
    f = path(name, data.episode)
    if data.current is None and data.candidate is None:
        f.unlink(missing_ok=True)
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data.model_dump(), ensure_ascii=False).encode("utf-8")
    store.write_atomic(f, gzip.compress(raw, mtime=0))


def _stamp(rec: SentPrompt, text: str, version: str = "") -> SentPrompt:
    from .pipeline import text_basis

    return rec.model_copy(update={"basis": text_basis(text), "chars": len(text.strip()), "version": version})


def _one(rec: SentPrompt | list[SentPrompt] | None) -> SentPrompt | None:
    """pipeline 이 채운 목록(sent=)을 그대로 받는다. 빈 목록은 None."""
    if isinstance(rec, list):
        return rec[0] if rec else None
    return rec


def keep(name: str, n: int, rec: SentPrompt | list[SentPrompt] | None, text: str) -> None:
    """n화 본문 text 를 rec 요청으로 저장했다. 지금 기록을 바꾼다. rec 이 없으면(기록 없이 쓴 본문) 아무것도 하지 않는다."""
    rec = _one(rec)
    if rec is None:
        return
    data = _read(name, n)
    data.current = _stamp(rec, text)
    _write(name, data)


def hold(name: str, n: int, rec: SentPrompt | list[SentPrompt] | None, text: str, version: str) -> None:
    """n화 새 판(version)을 낳은 요청을 대기 칸에 둔다. 앞 대기 기록은 버린다."""
    rec = _one(rec)
    data = _read(name, n)
    data.candidate = _stamp(rec, text, version) if rec is not None else None
    _write(name, data)


def adopt(name: str, n: int, version: str) -> None:
    """새 판 version 을 본문으로 골랐다. 대기 기록이 그 판 것이면 지금 기록으로 옮긴다."""
    data = _read(name, n)
    if data.candidate is None:
        return
    if data.candidate.version == version:
        data.current = data.candidate
    data.candidate = None
    _write(name, data)


def drop_candidate(name: str, n: int) -> None:
    """새 판을 버렸다. 대기 기록을 지운다."""
    data = _read(name, n)
    if data.candidate is not None:
        data.candidate = None
        _write(name, data)


def set_aside(name: str, n: int) -> str:
    """n화 본문을 지웠다 (화는 남김). 기록을 sent/removed/ 로 옮긴다. 옮긴 자리(작품 폴더 기준)나 빈 글."""
    return store.set_aside_side(name, "sent", n)


def read(name: str, n: int) -> SentPrompt | None:
    """n화 지금 본문을 낳은 요청 기록. 없으면 None. 본문과 맞는지는 matches 로 본다 (검수 지적 원인 진단이 읽는다)."""
    return _read(name, n).current


def matches(rec: SentPrompt, text: str) -> bool:
    """기록이 지금 본문 text 를 낳은 요청인가 (그 뒤 작가가 고치거나 판을 바꾸지 않았나)."""
    from .pipeline import text_basis

    return bool(rec.basis) and rec.basis == text_basis(text)


def episodes(name: str) -> list[int]:
    """기록이 있는 화."""
    return sorted(n for kind, n, _ in store.side_files(name) if kind == "sent")


RETRY_LABEL = {"cut": "끊김", "thought": "한글이 적은 응답", "meta": "작업 설명뿐인 응답", "polish": "대사 줄이 바뀐 다듬기",
               "tics": "말줄임을 늘린 다듬기"}


def retry_text(rec: SentPrompt) -> str:
    """다시 부른 까닭 요약: '끊김 1번 · 한글이 적은 응답 1번'. 없으면 빈 글."""
    counts: dict[str, int] = {}
    for r in rec.retries:
        counts[r.reason] = counts.get(r.reason, 0) + 1
    return " · ".join(f"{RETRY_LABEL[k]} {v}번" for k, v in counts.items())

