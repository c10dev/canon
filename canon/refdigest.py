"""레퍼런스 원고 전체 읽히기: 화마다 화 카드(사건 · 인물 · 장소 · 끝맺음 · 성격 · 긴장 · 끝맺음 방식)를 만들어 둔다.

원고 폴더의 digest.json (RefDigestBook) 에 화 글의 지문과 함께 둔다. 작품에는 들어가지 않는다.
작가가 '전체 읽히기'를 눌러야 돌고, 읽히지 않았거나 글 · 프롬프트 판이 바뀐 화만 부른다. 설계는 docs/refs/README.md 9장.
"""
from __future__ import annotations

import contextvars
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from . import cancel, prompts, refs, store, usage
from .llm import wait_cap
from .schema import REF_DIGEST_HOOKS, REF_DIGEST_KINDS, RefBook, RefDigest, RefDigestBook, RefDigestItem, RevAI

STAGE = "plan"  # 설정을 따를 때 쓰는 단계 (사용량 기록에도 이 단계로 남는다)
WORKERS = 4  # 함께 보내는 화 수. CoralBricks 계정의 동시 요청 한도가 5개였다 (2026-11-11)
TEXT_MAX = 30_000  # 한 화에서 보내는 글자 수. 넘으면 가운데를 줄인다
HEAD_SHARE = 0.6  # 줄일 때 앞에 남기는 몫 (나머지는 끝)
FAIL_STOP = 5  # 연달아 이만큼 실패하면 멈춘다 (키 · 잔액 · 한도 문제를 화 수만큼 되풀이하지 않게)
ARCS_WAIT = 600  # 아크 나누기 한 번의 응답을 기다리는 초
WAIT = 180  # 화 하나의 응답을 기다리는 초. 넘으면 그 화만 실패로 둔다 (2026-11-11 응답 없이 900초를 기다린 호출이 있었다)
OUT_TOKENS = 450  # 화 카드 하나의 응답 토큰 추정 (2026-11-11 실측 평균 372)
LINE_MAX = 300  # 사건 줄 · 끝맺음 한 줄의 글자 수
EVENTS_MAX = 6  # 사건 줄 상한. 줄이 6~8개로 늘면 어긋난 화가 늘었다 (2026-11-11: 10화 중 4화)
CAST_MAX = 30
PROVIDERS = ("gemini", "claude", "claude-api", "coralbricks", "local")  # 직접 고를 수 있는 백엔드 (revlab.AI_PROVIDERS 와 같다)

_lock = threading.Lock()  # digest.json 은 화 하나가 끝날 때마다 읽고 고쳐 쓴다


def _path(rid: str):
    return refs._dir(rid) / "digest.json"


def load(rid: str) -> RefDigestBook:
    f = _path(rid)
    if not f.exists():
        return RefDigestBook()
    return RefDigestBook.model_validate_json(f.read_text(encoding="utf-8"))


def _save(rid: str, d: RefDigestBook) -> None:
    store.write_atomic(_path(rid), d.model_dump_json(indent=1))


def basis(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def clip(text: str) -> tuple[str, int]:
    """(보낼 글, 줄인 글자 수). TEXT_MAX 를 넘는 화는 앞 HEAD_SHARE 와 끝을 남기고 가운데를 줄인다."""
    if len(text) <= TEXT_MAX:
        return text, 0
    head = int(TEXT_MAX * HEAD_SHARE)
    cut = len(text) - TEXT_MAX
    return f"{text[:head]}\n\n(가운데 {cut:,}자 줄임)\n\n{text[-(TEXT_MAX - head):]}", cut


def _texts(b: RefBook) -> list[dict]:
    """읽힐 수 있는 화 [{order, label, text, basis}] (제외 화와 빈 화는 뺀다)."""
    orders = [e.order for e in b.eps]
    try:
        chosen = refs.pick(b, orders)
    except ValueError:
        return []
    return [{"order": c["order"], "label": c["label"], "text": c["text"], "basis": basis(c["text"])} for c in chosen]


def _fresh(d: RefDigestBook) -> dict[str, RefDigestItem]:
    return {x.basis: x for x in d.items if x.version == prompts.REF_DIGEST_VERSION}


def state(b: RefBook, d: RefDigestBook | None = None, texts: list[dict] | None = None) -> dict:
    """읽힌 정도: total 읽힐 화 · read 지금 글로 읽힌 화 · stale 글이나 프롬프트 판이 바뀐 화 · todo 읽힐 차례들 · at 마지막으로 읽힌 때."""
    d = d if d is not None else load(b.id)
    texts = texts if texts is not None else _texts(b)
    fresh = _fresh(d)
    todo = [t["order"] for t in texts if t["basis"] not in fresh]
    read = len(texts) - len(todo)
    # 낡음: 읽힌 적은 있는데 글이나 프롬프트 판이 바뀐 화 (차례로 어림한다. 경계를 고치면 차례가 밀려 조금 어긋날 수 있다)
    seen = set(d.read_orders)
    stale = sum(1 for o in todo if o in seen)
    return {"total": len(texts), "read": read, "stale": stale, "todo": todo,
            "at": max((x.at for x in fresh.values() if x.basis in {t["basis"] for t in texts}), default="")}


def _norm(g: RefDigest) -> RefDigest:
    """모델 응답을 저장할 꼴로: 빈 줄을 빼고 길이를 자르고, 모르는 성격 · 끝맺음 방식은 비우고, 긴장은 1~5 로."""
    events = [" ".join(x.split())[:LINE_MAX] for x in g.events if x and x.strip()][:EVENTS_MAX]
    cast = list(dict.fromkeys(x.strip()[:40] for x in g.cast if x and x.strip()))[:CAST_MAX]
    return RefDigest(events=events, cast=cast, place=" ".join(g.place.split())[:LINE_MAX], ending=" ".join(g.ending.split())[:LINE_MAX],
                     kind=g.kind.strip() if g.kind.strip() in REF_DIGEST_KINDS else "",
                     tension=min(5, max(1, int(g.tension or 1))), hook=g.hook.strip() if g.hook.strip() in REF_DIGEST_HOOKS else "")


# ---------- 읽힐 AI ----------

def ai_choice(d: RefDigestBook) -> dict:
    """쓸 백엔드와 모델 {provider, model, source}. source: mock(설정이 mock) · book(이 원고에서 고름) · settings(계획 단계를 따름)."""
    from . import settings

    if settings.provider()[0] == "mock":
        return {"provider": "mock", "model": "", "source": "mock"}
    if d.ai.provider:
        return {"provider": d.ai.provider, "model": d.ai.model, "source": "book"}
    return {"provider": settings.stage_provider(STAGE, None)[0], "model": settings.stage_model(STAGE, None)[0], "source": "settings"}


def model_name(c: dict) -> str:
    from . import revlab

    return c["model"] or revlab.default_model(c["provider"])


def llm_for(rid: str):
    """읽힐 LLM. 키가 없으면 여기서 바로 오류를 낸다 (웹은 작업을 시작하기 전에 부른다)."""
    from .llm import make_llm

    c = ai_choice(load(rid))
    llm = make_llm(c["provider"], c["model"] or None)
    llm.stage = STAGE  # type: ignore[attr-defined]  # 사용량 기록이 단계를 적는다
    return llm


def set_ai(rid: str, provider: str = "", model: str = "") -> dict:
    """이 원고를 읽힐 AI 를 고른다. 모두 비우면 설정의 계획 단계를 따른다. 다음 읽히기부터 쓴다."""
    provider, model = provider.strip().lower(), model.strip()
    if provider and provider not in PROVIDERS:
        raise ValueError(f"고를 수 없는 AI예요: {provider}")
    refs.load(rid)  # 없는 원고면 KeyError
    with _lock:
        d = load(rid)
        d.ai = RevAI(provider=provider, model=model if provider else "")
        _save(rid, d)
    return ai_view(d)


def ai_view(d: RefDigestBook) -> dict:
    from . import settings

    use = ai_choice(d)
    follow = ai_choice(RefDigestBook())
    return {"provider": d.ai.provider, "model": d.ai.model, "use": {**use, "name": model_name(use)},
            "follow": {**follow, "name": model_name(follow)}, "providers": list(PROVIDERS),
            "coral": bool(settings.coral_key()[0])}  # 키가 있으면 화면이 싼 CoralBricks 모델을 권한다


# ---------- 비용 추정 ----------

def estimate(rid: str) -> dict:
    """읽힐 화 수와 비용 추정. 캐시와 생각 토큰은 넣지 않는다."""
    b = refs.load(rid)
    d = load(rid)
    texts = _texts(b)
    st = state(b, d, texts)
    todo = set(st["todo"])
    c = ai_choice(d)
    model = model_name(c)
    price = usage.rate(model, date.today().isoformat()) if c["provider"] in usage.PRICED else None
    rate = usage.token_rate(c["provider"] if c["provider"] != "mock" else "", model)
    once = {t["basis"]: t for t in texts if t["order"] in todo}  # 글이 같은 화는 한 번만 보낸다
    chars = [len(prompts.ref_digest_prompt(clip(t["text"])[0])) for t in once.values()]
    tin = sum(usage.est_input(n, rate, len(prompts.SYSTEM_REVERSE)) for n in chars)
    tout = OUT_TOKENS * len(chars)
    free = c["provider"] not in usage.PRICED
    return {"calls": len(chars), "chars": sum(chars), "input_tokens": round(tin), "output_tokens": tout,
            "provider": c["provider"], "model": model, "priced": free or price is not None,
            "usd": 0.0 if free else (round(usage.cost(price, tin, tout, 0, False), 3) if price else None),
            "long": sum(1 for t in once.values() if len(t["text"]) > TEXT_MAX), "workers": WORKERS}


# ---------- 읽히기 ----------

def run(rid: str, llm, job=None) -> dict:
    """읽히지 않았거나 낡은 화를 WORKERS 개씩 읽힌다. 화 하나가 끝날 때마다 저장해 멈춰도 읽힌 화는 남는다.
    실패한 화는 건너뛰고 끝에 알린다. 연달아 FAIL_STOP 번 실패하면 남은 화를 보내지 않는다.
    돌려주는 값: {read 읽힌 화 수, failed 못 읽힌 차례들, error 마지막 오류 글, stopped 연달아 실패해 멈췄는지}."""
    from . import pipeline, research
    from .llm import MissingKey, wait_cap

    b = refs.load(rid)
    texts = _texts(b)
    todo = set(state(b, load(rid), texts)["todo"])
    same: dict[str, list[int]] = {}  # 글이 같은 화는 한 번만 보낸다: 지문 → 차례들
    for t in texts:
        if t["order"] in todo:
            same.setdefault(t["basis"], []).append(t["order"])
    work = [t for t in texts if t["order"] in todo and same[t["basis"]][0] == t["order"]]
    model = research._model_name(llm)
    if job is not None:
        job.total, job.done = max(1, len(todo)), 0
    with _lock:  # 지금 원고에 없는 글의 카드는 버린다 (경계를 고쳐 사라진 화)
        d0 = load(rid)
        live = {t["basis"] for t in texts}
        if any(x.basis not in live for x in d0.items):
            d0.items = [x for x in d0.items if x.basis in live]
            _save(rid, d0)
    done: list[int] = []
    failed: list[int] = []
    box = {"streak": 0, "error": "", "fatal": None}

    def one(t: dict) -> None:
        if box["fatal"] or box["streak"] >= FAIL_STOP:
            return
        orders = same[t["basis"]]
        text, cut = clip(t["text"])
        try:
            cancel.check()
            with wait_cap(WAIT):
                g = _norm(pipeline.ref_digest(llm, text))
        except (cancel.Cancelled, MissingKey) as e:  # 멈춤, 키 없음 · 틀림: 남은 화도 같은 결과라 바로 끝낸다
            box["fatal"] = box["fatal"] or e
            return
        except Exception as e:  # 화 하나의 실패 (형식 오류 · 서버 오류). 다음 화는 계속 읽힌다
            with _lock:
                failed.extend(orders)
                box["streak"] += 1
                box["error"] = str(getattr(e, "message", None) or e)[:300]
            return
        if not g.events:
            with _lock:
                failed.extend(orders)
                box["streak"] += 1
                box["error"] = "사건 줄이 비어 있었어요"
            return
        item = RefDigestItem(basis=t["basis"], order=t["order"], at=datetime.now().isoformat(timespec="seconds"), model=model,
                             version=prompts.REF_DIGEST_VERSION, cut=cut, digest=g)
        with _lock:
            d = load(rid)
            d.items = [x for x in d.items if x.basis != item.basis] + [item]
            d.read_orders = sorted({*d.read_orders, *orders})
            _save(rid, d)
            done.extend(orders)
            box["streak"] = 0
            if job is not None:
                job.done = len(done)
                job.note = f"{t['label'] or str(t['order']) + '번째'}까지 읽혔어요" + (f" · {len(failed)}화 실패" if failed else "")

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(work)))) as pool:
        for f in [pool.submit(contextvars.copy_context().run, one, t) for t in work]:
            f.result()
    if box["fatal"]:
        raise box["fatal"]
    return {"read": len(done), "failed": sorted(failed), "error": box["error"], "stopped": box["streak"] >= FAIL_STOP,
            "left": len(todo) - len(done)}


# ---------- 화면 값 ----------

def view(rid: str) -> dict:
    """화면 값: 읽힌 정도, 화마다 카드(지금 글로 읽힌 화만), 읽힐 AI."""
    b = refs.load(rid)
    d = load(rid)
    texts = _texts(b)
    fresh = _fresh(d)
    cards = {}
    for t in texts:
        x = fresh.get(t["basis"])
        if x:
            cards[str(t["order"])] = {**x.digest.model_dump(), "at": x.at, "model": x.model, "cut": x.cut}
    st = state(b, d, texts)
    return {"id": rid, **{k: v for k, v in st.items() if k != "todo"}, "todo": len(st["todo"]), "cards": cards, "ai": ai_view(d),
            "kinds": list(REF_DIGEST_KINDS), "hooks": list(REF_DIGEST_HOOKS)}


# ---------- 구조 보기 (AI 없음) ----------

PACE_BLOCKS = 12  # 긴장 곡선을 나누는 구간 수 어림
PACE_STEP = 5  # 구간의 화 수는 이 배수로 맞춘다
PEAK = 5  # 이 긴장인 화를 정점 화로 본다
CAST_TOP = 12  # 인물 표에 보이는 수
GENERIC = {"서술자", "화자", "주인공", "남자", "여자", "나", "그", "그녀", "소년", "소녀", "남주", "여주"}  # 이름이 아닌 부름말
ARCS_MIN = 8  # 아크를 나누는 가장 적은 화 수
ARCS_OUT_TOKENS = 3000  # 아크 응답 토큰 추정 (revlab.ARCS_OUT_TOKENS 와 같다)


def _rows(b: RefBook, d: RefDigestBook) -> list[dict]:
    """지금 글로 읽힌 화 [{n 차례, label, chars, dialogue, kind, tension, hook, events, ending, cast, basis}] (원고 차례)."""
    fresh = _fresh(d)
    names = {e["order"]: e for e in refs.episodes(b)}
    out = []
    for t in _texts(b):
        x = fresh.get(t["basis"])
        if x:
            e = names.get(t["order"], {})
            out.append({"n": t["order"], "label": t["label"], "chars": e.get("chars", 0), "dialogue": e.get("dialogue", 0.0),
                        "basis": t["basis"], **x.digest.model_dump()})
    return out


def cast_table(rows: list[dict]) -> list[dict]:
    """화 카드의 인물을 모은다 [{name, episodes 나온 화 수, first 처음 나온 차례}]. 부름말(GENERIC)은 빼고,
    성을 뗀 이름('지아')은 그 이름으로 끝나는 더 긴 이름('서지아') 가운데 가장 많이 나온 쪽으로 합친다."""
    seen: dict[str, set[int]] = {}
    for r in rows:
        for n in r["cast"]:
            n = n.strip()
            if len(n) >= 2 and n not in GENERIC:
                seen.setdefault(n, set()).add(r["n"])
    for short in sorted(seen, key=len):
        longer = [n for n in seen if n != short and n.endswith(short) and len(n) <= len(short) + 2]
        if longer:  # 후보가 여럿이면 가장 많이 나온 이름으로
            seen[max(longer, key=lambda n: len(seen[n]))] |= seen.pop(short)
    table = [{"name": n, "episodes": len(v), "first": min(v)} for n, v in seen.items()]
    return sorted(table, key=lambda x: (-x["episodes"], x["first"]))


def pace(rid: str) -> dict:
    """화 카드만으로 본 구조: 구간별 평균 긴장 · 성격, 정점 화, 성격 · 긴장 분포, 인물이 처음 나온 화. AI 를 부르지 않는다.
    끝맺음 방식(hook)은 모델마다 달라 넣지 않는다 (2026-11-11: 20화 중 9화만 일치)."""
    b = refs.load(rid)
    d = load(rid)
    rows = _rows(b, d)
    if not rows:
        return {"episodes": 0, "blocks": [], "peaks": [], "kinds": [], "tension": [], "cast": []}
    size = max(PACE_STEP, -(-len(rows) // PACE_BLOCKS // PACE_STEP) * PACE_STEP)
    blocks = []
    for i in range(0, len(rows), size):
        part = rows[i:i + size]
        kinds: dict[str, int] = {}
        for r in part:
            if r["kind"]:
                kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        blocks.append({"start": part[0]["n"], "end": part[-1]["n"], "from": part[0]["label"], "to": part[-1]["label"], "episodes": len(part),
                       "tension": round(sum(r["tension"] for r in part) / len(part), 2), "peaks": sum(r["tension"] >= PEAK for r in part),
                       "dialogue": round(sum(r["dialogue"] for r in part) / len(part), 2),
                       "kinds": sorted(kinds.items(), key=lambda kv: -kv[1])[:3]})
    count = lambda key: sorted(((k, sum(1 for r in rows if r[key] == k)) for k in {r[key] for r in rows} if k), key=lambda kv: -kv[1])  # noqa: E731
    return {"episodes": len(rows), "block_size": size, "blocks": blocks,
            "peaks": [{"order": r["n"], "label": r["label"]} for r in rows if r["tension"] >= PEAK],
            "kinds": count("kind"), "tension": sorted(count("tension")), "cast": cast_table(rows)[:CAST_TOP]}


# ---------- 아크 · 부 나누기 (큰 모델 한 번) ----------

def _arcs_basis(rows: list[dict]) -> str:
    return basis("|".join(r["basis"] for r in rows))


def arcs_ready(rid: str) -> tuple[list[dict], list[str]]:
    """아크를 나눌 화 카드와 인물 이름. 읽히지 않은 화가 있거나 화가 너무 적으면 ValueError."""
    b = refs.load(rid)
    d = load(rid)
    st = state(b, d)
    rows = _rows(b, d)
    if st["todo"]:
        raise ValueError(f"아직 읽히지 않은 화가 {len(st['todo'])}개 있어요. 전체 읽히기를 먼저 끝내 주세요")
    if len(rows) < ARCS_MIN:
        raise ValueError(f"화가 {ARCS_MIN}개는 있어야 아크를 나눠요")
    return rows, [c["name"] for c in cast_table(rows)[:CAST_TOP * 2]]


def arcs_estimate(rid: str) -> dict:
    """아크 나누기 한 번의 비용 추정 (설정의 plan 단계 모델)."""
    from . import settings

    rows, names = arcs_ready(rid)
    provider = "mock" if settings.provider()[0] == "mock" else settings.stage_provider(STAGE, None)[0]
    model = settings.stage_model(STAGE, None)[0] or model_name({"provider": provider, "model": ""})
    prompt = prompts.ref_arcs_prompt(rows, names)
    rate = usage.token_rate(provider if provider != "mock" else "", model)
    tin = usage.est_input(len(prompt), rate, len(prompts.SYSTEM_REVERSE))
    free = provider not in usage.PRICED
    price = None if free else usage.rate(model, date.today().isoformat())
    return {"episodes": len(rows), "chars": len(prompt), "input_tokens": round(tin), "output_tokens": ARCS_OUT_TOKENS, "provider": provider,
            "model": model, "usd": 0.0 if free else (round(usage.cost(price, tin, ARCS_OUT_TOKENS, 0, False), 3) if price else None),
            "folded": "화마다 첫 사건" in prompt}


def run_arcs(rid: str, llm) -> dict:
    """화 카드를 접어 아크 · 부로 나누고 digest.json 에 둔다 (작품에는 넣지 않는다). 화 번호는 원고의 차례다."""
    from types import SimpleNamespace

    from . import pipeline, research, revlab

    rows, names = arcs_ready(rid)
    cancel.check()
    with wait_cap(ARCS_WAIT):
        out = pipeline.ref_arcs(llm, rows, names)
    cancel.check()
    stand = SimpleNamespace(episodes=[SimpleNamespace(number=rows[0]["n"]), SimpleNamespace(number=rows[-1]["n"])],
                            cast=[SimpleNamespace(name=n) for n in names])
    plan = revlab.clean_arcs(stand, out, "ai", research._model_name(llm))
    with _lock:
        d = load(rid)
        d.arcs, d.arcs_basis = plan, _arcs_basis(rows)
        _save(rid, d)
    return {"arcs": len(plan.arcs), "parts": len(plan.parts)}


def clear_arcs(rid: str) -> None:
    refs.load(rid)
    with _lock:
        d = load(rid)
        d.arcs, d.arcs_basis = None, ""
        _save(rid, d)


def arcs_view(rid: str) -> dict:
    """화면 값: 나눈 아크 · 부(없으면 None), 화 카드가 그 뒤 바뀌었는지(stale), 차례 → 화 이름."""
    b = refs.load(rid)
    d = load(rid)
    rows = _rows(b, d)
    return {"plan": d.arcs.model_dump() if d.arcs else None, "stale": bool(d.arcs) and d.arcs_basis != _arcs_basis(rows),
            "labels": {str(r["n"]): r["label"] for r in rows}}
