"""참고 메모: 레퍼런스 원고에서 설정 구도 요약을 만들어 작품에 넣는다 (설계는 docs/refs/README.md 5장 · 5-1 · 9-3).

원고는 작품에 연결하지 않는다. AI 가 만든 초안은 작업 결과(미리보기)로만 돌려주고, 작가가 넣기를 눌러야 Project.ref_notes 에 들어간다.
고른 화가 모두 지금 글로 읽혀 있으면(화 카드, canon/refdigest.py) 원문 대신 화 카드를 접어 보내고, 아니면 원문을 앞부터 채워 보낸다.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from . import cancel, context, prompts, refdigest, refs, usage
from .llm import wait_cap
from .schema import Project, RefBeatsDraft, RefNote, RefSetupDraft

STAGE = "plan"
SETUP_NOTE_MAX = 30_000  # 화 카드가 없을 때 보내는 원문 글자 수 (refs.SAMPLE_MAX 와 같은 값)
NOTE_DIGEST_BUDGET = 30_000  # 화 카드를 접어 보내는 글자 수 (prompts.ref_cards_fold)
NOTE_MAX = 2_000  # 메모 하나의 글자 수
NAMES_MAX = 40  # 요청과 겹침 표시에 쓰는 원고 이름 수
OUT_TOKENS = 700  # 응답 토큰 추정
WAIT = 300  # 응답을 기다리는 초
# 화 카드의 인물 칸에 섞여 나오는 호칭 · 직함. 이름이 아니라서 '메모에 쓰지 않을 이름'과 겹침 표시에서 뺀다 (2026-11-12 실제 원고: 매니저 · 이사 · 언니 · 점원 …)
ROLE_WORDS = frozenset("언니 오빠 누나 형 동생 엄마 아빠 어머니 아버지 할머니 할아버지 이모 삼촌 고모 아내 남편 딸 아들 친구 선배 후배 매니저 이사 사장 대표 팀장 부장 과장 실장 "
                       "회장 점원 직원 알바 알바생 기사 의사 간호사 경찰 형사 선생 교수 감독 코치 코디 비서 손님 주인 아저씨 아줌마 아가씨 학생 기자 변호사 팀원 동료 상사".split())
USE_KIND = {"setup": "setup", "write": "beats", "plot": "beats"}  # 쓰임 → 메모 꼴. 설정 메모는 설정 도우미에만, 박자 메모는 집필 · 플롯 초안에
BEAT_LABELS = (("pattern", "한 화의 꼴"), ("beats", "박자"), ("hooks", "끝을 끊는 방식"), ("pacing", "완급"))
LABELS = (("logline_shape", "로그라인 꼴"), ("world_rules", "세계 규칙"), ("cast", "인물 배치"), ("relations", "관계 구도"), ("conflict", "갈등 축"), ("tone", "톤"))


def is_name(word: str) -> bool:
    """화 카드의 인물 칸 낱말이 이름인지 어림한다: 두 글자 넘고, 부름말(refdigest.GENERIC) · 호칭 · 직함(ROLE_WORDS)이 아니고,
    '님'으로 끝나지 않고, 띄어 쓴 낱말 가운데 호칭 · 직함이 없다 ('코디 언니', '편의점 알바')."""
    w = word.strip()
    if len(w) < 2 or w in refdigest.GENERIC or w.endswith("님"):
        return False
    return not any(t in ROLE_WORDS or t in refdigest.GENERIC for t in w.split())


def material(rid: str, orders: list[int]) -> dict:
    """메모를 만들 재료. mode cards: 고른 화가 모두 읽혀 있어 화 카드를 접었다 (folded: 화마다 줄였는지). mode text: 원문을 앞부터
    SETUP_NOTE_MAX 자까지 채웠다 (sent: 보낸 화 수). names 는 겹침 표시에 쓰는 원고의 이름, texts 는 고른 화의 원문 (AI 에 보내지 않는다)."""
    b = refs.load(rid)
    chosen = refs.pick(b, orders)
    fresh = refdigest._fresh(refdigest.load(rid))
    cards = [fresh.get(refdigest.basis(c["text"])) for c in chosen]
    base = {"name": b.name, "eps": refs.span(chosen), "episodes": len(chosen), "texts": [c["text"] for c in chosen]}
    if all(cards):
        rows = [{"n": c["order"], "label": c["label"], **x.digest.model_dump()} for c, x in zip(chosen, cards)]
        fold, lines = prompts.ref_cards_fold(rows, NOTE_DIGEST_BUDGET)
        seen = [n.strip() for r in rows for n in r["cast"]]
        count = {n: seen.count(n) for n in dict.fromkeys(seen) if is_name(n)}
        return {**base, "mode": "cards", "body": "\n\n".join(lines), "fold": fold, "folded": bool(fold), "sent": len(chosen),
                "names": sorted(count, key=lambda n: -count[n])[:NAMES_MAX]}
    parts, used = [], 0
    for c in chosen:
        head = f"## {c['label'] or str(c['order']) + '번째 화'}\n"
        room = SETUP_NOTE_MAX - used - len(head)
        if parts and len(c["text"]) > room:  # 인물과 세계는 앞 화에서 드러나므로 앞부터 채우고, 넘는 화부터는 보내지 않는다
            break
        parts.append(head + c["text"][:max(room, 0)])
        used += len(parts[-1]) + 2
    return {**base, "mode": "text", "body": "\n\n".join(parts), "fold": "", "folded": False, "sent": len(parts),
            "names": refs.proper_words(base["texts"])[:NAMES_MAX]}


def text_of(d: RefSetupDraft | RefBeatsDraft) -> str:
    """응답을 칸 이름 줄을 붙인 글 하나로 (RefNote.text). 빈 칸은 뺀다."""
    out = []
    for key, label in (BEAT_LABELS if isinstance(d, RefBeatsDraft) else LABELS):
        v = getattr(d, key)
        if isinstance(v, list):
            lines = [" ".join(x.split()) for x in v if x and x.strip()]
            if lines:
                out.append(f"{label}:\n" + "\n".join(f"- {x}" for x in lines))
        elif v and v.strip():
            out.append(f"{label}: {' '.join(v.split())}")
    return "\n".join(out)


def _kind(use: str) -> str:
    if use not in USE_KIND:
        raise ValueError(f"모르는 쓰임이에요: {use}")
    return USE_KIND[use]


def _prompt(m: dict, kind: str = "setup") -> str:
    fn = prompts.ref_beats_note_prompt if kind == "beats" else prompts.ref_setup_note_prompt
    return fn(m["body"], m["mode"], m["names"] if m["mode"] == "cards" else None, m["fold"])


def estimate(rid: str, orders: list[int], use: str = "setup") -> dict:
    """참고 메모 한 번의 비용 추정과 보낼 것 (설정의 plan 단계 모델). AI 를 부르지 않는다."""
    from . import settings

    kind = _kind(use)
    m = material(rid, orders)
    provider = "mock" if settings.provider()[0] == "mock" else settings.stage_provider(STAGE, None)[0]
    model = settings.stage_model(STAGE, None)[0] or refdigest.model_name({"provider": provider, "model": ""})
    chars = len(_prompt(m, kind))
    tin = usage.est_input(chars, usage.token_rate(provider if provider != "mock" else "", model), len(prompts.SYSTEM_REVERSE))
    free = provider not in usage.PRICED
    price = None if free else usage.rate(model, date.today().isoformat())
    return {"mode": m["mode"], "episodes": m["episodes"], "sent": m["sent"], "folded": m["folded"], "eps": m["eps"], "chars": chars,
            "input_tokens": round(tin), "output_tokens": OUT_TOKENS, "provider": provider, "model": model,
            "usd": 0.0 if free else (round(usage.cost(price, tin, OUT_TOKENS, 0, False), 3) if price else None)}


def run(rid: str, orders: list[int], llm, project: str = "", use: str = "setup") -> dict:
    """참고 메모 초안을 만든다 (작업 ref_note 의 결과 = 미리보기). 작품에 저장하지 않는다. use setup 은 설정 메모, write · plot 은 박자 메모.
    marks 는 초안에 든 원문 구절(20자 넘게 같음)과 원고의 이름 (refs.overlap). 넣기를 막지는 않는다."""
    from . import pipeline, research

    kind = _kind(use)
    m = material(rid, orders)
    cancel.check()
    with wait_cap(WAIT):
        make = pipeline.ref_beats_note if kind == "beats" else pipeline.ref_setup_note
        d = make(llm, m["body"], m["mode"], m["names"] if m["mode"] == "cards" else None, m["fold"])
    cancel.check()
    text = text_of(d)
    if not text:
        raise ValueError("AI가 빈 메모를 냈어요. 다시 만들어 주세요")
    return {"ref": rid, "project": project, "from_name": m["name"], "from_eps": m["eps"], "orders": sorted(orders), "kind": kind, "use": use,
            "text": text[:NOTE_MAX], "clipped": len(text) > NOTE_MAX, "marks": refs.overlap(text[:NOTE_MAX], m["texts"], m["names"]),
            "mode": m["mode"], "episodes": m["episodes"], "sent": m["sent"], "folded": m["folded"], "model": research._model_name(llm)}


def marks(rid: str, orders: list[int], text: str) -> list[dict]:
    """작가가 고친 메모 글의 겹침 표시를 다시 센다 (AI 없음)."""
    m = material(rid, orders)
    return refs.overlap(text, m["texts"], m["names"])


# ---------- 작품의 참고 메모 ----------

def _clean(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("메모가 비어 있어요")
    if len(text) > NOTE_MAX:
        raise ValueError(f"메모가 너무 길어요 ({len(text):,}자). {NOTE_MAX:,}자까지 넣을 수 있어요")
    return text


def add(p: Project, text: str, from_name: str = "", from_eps: str = "", kind: str = "setup", use: str = "setup") -> RefNote:
    """작가가 미리보기에서 넣기를 누른 메모를 작품에 넣는다. 설정 메모는 설정 도우미에만, 박자 메모는 집필 · 플롯 초안에만 넣는다 (USE_KIND)."""
    if USE_KIND.get(use) != kind:
        raise ValueError("설정 메모는 설정 도우미에만, 박자 메모는 집필과 플롯 초안에만 넣어요")
    n = RefNote(id=uuid.uuid4().hex[:8], from_name=from_name.strip()[:80], from_eps=from_eps.strip()[:40], kind=kind, use=use,
                text=_clean(text), at=datetime.now().isoformat(timespec="seconds"))
    p.ref_notes.append(n)
    return n


def _find(p: Project, nid: str) -> RefNote:
    n = next((x for x in p.ref_notes if x.id == nid), None)
    if n is None:
        raise KeyError(nid)
    return n


def update(p: Project, nid: str, text: str | None = None, on: bool | None = None) -> RefNote:
    n = _find(p, nid)
    if text is not None:
        n.text = _clean(text)
    if on is not None:
        n.on = on
    return n


def remove(p: Project, nid: str) -> None:
    p.ref_notes.remove(_find(p, nid))


def dropped(p: Project) -> list[str]:
    """켰지만 쓰임마다의 예산을 넘어 프롬프트에서 빠지는 메모 id (prompts.ref_notes_fit 과 같은 규칙)."""
    out = []
    for use in USE_KIND:
        kept = {n.id for n in prompts.ref_notes_fit(p, use)[0]}
        out += [n.id for n in p.ref_notes if n.on and n.use == use and n.text.strip() and n.id not in kept]
    return out


def view(p: Project) -> dict:
    """화면 값: 메모 목록, 예산을 넘어 빠지는 메모 id, 상한."""
    return {"notes": [n.model_dump() for n in p.ref_notes], "dropped": dropped(p), "budget": context.BUDGET["ref_notes"], "max": NOTE_MAX,
            "budgets": {use: context.BUDGET[key] for use, key in prompts.REF_NOTE_BUDGET.items()}}
