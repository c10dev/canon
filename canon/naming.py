"""이름·지명 무작위 생성과 출연진 이름 점검. LLM 을 부르지 않는 계산이다.

LLM 에게 이름을 맡기면 몇 개 이름으로 몰리고(서윤, 도현), 인물의 나이와 시대를 이름에 반영하지 못한다.
그래서 후보는 코드가 세계관(이름 스타일)과 나이에 맞춰 뽑고, AI 는 그중에서 인물에 맞는 것을 고르기만 한다
(pipeline.suggest_names). 작가가 정한 이름은 건드리지 않고 점검 결과만 알려 준다.

이름 스타일은 WorldSetting.name_style 로 고정할 수 있고, 비어 있으면 장르와 배경 글에서 짐작한다.
자료와 출처는 naming_data.py.
"""
from __future__ import annotations

import datetime
import random
import re
from itertools import combinations

from pydantic import BaseModel

from . import naming_data as D
from .logline import josa
from .schema import Character, Project


def _j(word: str, with_final: str, without_final: str) -> str:
    return word + josa(word, with_final, without_final)


def _known(word: str) -> bool:
    """받침을 알 수 있는 끝 글자다 (한글이나 숫자). 로마자 이름은 '과(와)' 대신 조사 없는 문형을 쓴다."""
    return "(" not in josa(word, "이", "가")


def _pair(a: str, b: str) -> str:
    """두 이름을 문장 주어로: '서윤과 도현은', 로마자가 끼면 'Elena', 'Elise' 두 인물은."""
    return f"{_j(a, '과', '와')} {_j(b, '은', '는')}" if _known(a) and _known(b) else f"'{a}', '{b}' 두 인물은"


def _topic(word: str) -> str:
    """이름 하나를 주제로: '서윤은', 로마자면 'Elena' 인물은."""
    return _j(word, "은", "는") if _known(word) else f"'{word}' 인물은"


class NameStyle(BaseModel):
    id: str
    label: str
    summary: str


STYLES: list[NameStyle] = [
    NameStyle(id="korea_modern", label="현대 한국", summary="성씨 인구 비율과 출생 연대별 흔한 이름으로 뽑아요. 나이를 적으면 그 시대 이름이 나와요."),
    NameStyle(id="joseon", label="조선 · 사극", summary="양반가 이름, 아명·평민 이름, 고을·나루·주막 같은 옛 지명."),
    NameStyle(id="wuxia", label="무협 (중원)", summary="복성 포함 중원식 성명과 별호, 문파, 중원 지역과 산·곡·객잔."),
    NameStyle(id="western_fantasy", label="서양풍 판타지", summary="음절을 조합한 이름과 가문명, 왕국·영지·요새. 흔한 판타지 이름은 빼요."),
    NameStyle(id="japan", label="일본", summary="흔한 일본 성씨와 이름, 동네·학교·역 이름."),
    NameStyle(id="sf", label="SF · 우주", summary="여러 언어권이 섞인 이름과 정거장·콜로니·행성."),
]
STYLE_IDS = {s.id for s in STYLES}


class Candidate(BaseModel):
    name: str
    note: str = ""   # 왜 이 후보인지 (예: "1980년대생에 흔한 이름", "고개")
    kind: str = ""   # 지명일 때 종류


def style_label(style_id: str) -> str:
    return next((s.label for s in STYLES if s.id == style_id), style_id)


# ---------- 이름 스타일 짐작 ----------

_KEYWORDS = [
    ("wuxia", r"무협|무림|강호|중원|문파|무공|협객|선협|선계"),
    ("joseon", r"조선|고려|한양|사극|궁궐|양반|삼국|신라|백제|고구려|임금|세자|대감"),
    ("japan", r"일본|도쿄|오사카|교토|홋카이도|에도|사무라이|〜군|고교 생활"),
    ("sf", r"우주|행성|콜로니|함선|은하|안드로이드|사이보그|정거장"),
    ("western_fantasy", r"왕국|제국|공작|백작|기사단|마탑|마법사|엘프|드워프|영지|황녀|황태자|아카데미"),
]
_GENRE_STYLE = {"martial_arts": "wuxia", "sf": "sf", "fantasy": "western_fantasy", "romance_fantasy": "western_fantasy",
                "alt_history": "joseon"}


def _world_text(p: Project) -> str:
    w = p.world
    return " ".join([w.setting, w.era, *w.rules, *w.locations, p.meta.logline, p.meta.notes])


def detect_style(p: Project) -> str:
    """배경 글의 낱말이 장르보다 먼저다 (현대 일본 학원물은 '일본', 동양풍 로판은 '무협' 쪽)."""
    text = _world_text(p)
    for sid, pat in _KEYWORDS:
        if re.search(pat, text):
            return sid
    for g in p.meta.genres:
        if g in _GENRE_STYLE:
            return _GENRE_STYLE[g]
    return "korea_modern"


def resolve_style(p: Project, override: str | None = None) -> str:
    for v in (override, p.world.name_style):
        if v and v in STYLE_IDS:
            return v
    return detect_style(p)


# ---------- 나이와 출생 연도 ----------

def _ref_year(era: str) -> int:
    m = re.search(r"(1[5-9]\d\d|20\d\d)", era or "")
    return int(m.group(1)) if m else datetime.date.today().year


def age_years(age: str) -> int | None:
    """'17세 (고1)', '45', '40대 초반', '중2' 같은 글에서 나이를 어림한다."""
    a = age or ""
    if m := re.search(r"(\d{1,3})\s*(?:세|살)", a):
        return int(m.group(1))
    if m := re.search(r"(\d)0\s*대\s*(초반|중반|후반)?", a):
        return int(m.group(1)) * 10 + {"초반": 2, "후반": 8}.get(m.group(2) or "", 5)
    for pat, base in ((r"고\s*(\d)", 15), (r"중\s*(\d)", 12), (r"초\s*(\d)", 6)):
        if m := re.search(pat, a):
            return base + int(m.group(1))
    if m := re.fullmatch(r"\s*(\d{1,3})\s*", a):
        return int(m.group(1))
    return None


def birth_year(age: str, era: str = "") -> int | None:
    years = age_years(age)
    return None if years is None else _ref_year(era) - years


def _bucket(year: int) -> int:
    return min(2020, max(1940, year // 10 * 10))


# ---------- 공통 ----------

def _rng(rng: random.Random | None) -> random.Random:
    return rng or random.Random()


def _pick(rng: random.Random, weights: dict[str, int]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _gender(g: str) -> str:
    g = (g or "").strip()
    if g[:1] in ("남", "M", "m") or g.startswith("소년"):
        return "남"
    if g[:1] in ("여", "F", "f") or g.startswith("소녀"):
        return "여"
    return ""


def _collect(make, n: int, exclude: set[str], tries: int = 400) -> list[Candidate]:
    """make() 가 내놓는 후보를 이름이 겹치지 않게 n 개 모은다."""
    out: list[Candidate] = []
    seen = set(exclude)
    for _ in range(tries):
        if len(out) >= n:
            break
        c = make()
        if c and c.name not in seen:
            seen.add(c.name)
            out.append(c)
    return out


# ---------- 인물 이름 ----------

def _syllable_combo(rng: random.Random, names: list[str]) -> str:
    """같은 시대 이름의 첫 글자와 끝 글자를 섞어 목록에 없는 이름을 만든다."""
    two = [x for x in names if len(x) == 2]
    a, b = rng.choice(two)[0], rng.choice(two)[1]
    return "" if a == b else a + b


def _korean(rng: random.Random, gender: str, year: int | None) -> Candidate:
    g = gender or rng.choice(["남", "여"])
    if year is None:
        bucket = rng.choice(list(D.KO_GIVEN))
    else:  # 그 시대가 대부분, 가끔 앞뒤 10년
        bucket = _bucket(year + rng.choice([0, 0, 0, 0, -10, 10]))
    names = D.KO_GIVEN[bucket][g]
    if rng.random() < 0.3:
        given, note = _syllable_combo(rng, names), f"{bucket}년대생 이름 결로 조합"
    else:
        given, note = rng.choice(names), f"{bucket}년대생에 흔한 이름"
    if not given or given in D.AI_OVERUSED:
        return None  # type: ignore[return-value]
    return Candidate(name=_pick(rng, D.KO_SURNAMES) + given, note=f"{g} · {note}")


def _joseon(rng: random.Random, gender: str) -> Candidate:
    g = gender or rng.choice(["남", "여"])
    common = rng.random() < 0.3
    if g == "남":
        if common:
            return Candidate(name=rng.choice(D.JOSEON_COMMON_MALE), note="남 · 아명·평민 이름")
        a, b = rng.sample(D.JOSEON_MALE_SYL, 2)
        return Candidate(name=_pick(rng, D.KO_SURNAMES) + a + b, note="남 · 양반가 이름 결")
    if common:
        return Candidate(name=rng.choice(D.JOSEON_COMMON_FEMALE), note="여 · 아명·평민 이름")
    return Candidate(name=_pick(rng, D.KO_SURNAMES) + rng.choice(D.JOSEON_FEMALE), note="여 · 이야기용 여인 이름")


def _wuxia(rng: random.Random, gender: str) -> Candidate:
    g = gender or rng.choice(["남", "여"])
    syl = D.WUXIA_MALE_SYL if g == "남" else D.WUXIA_FEMALE_SYL
    sur = _pick(rng, D.WUXIA_SURNAMES)
    given = "".join(rng.sample(syl, 1 if len(sur) == 2 and rng.random() < 0.4 else 2))
    alias = rng.choice(D.WUXIA_ALIAS_HEAD) + rng.choice(D.WUXIA_ALIAS_MID) + (rng.choice(D.WUXIA_ALIAS_TAIL) if rng.random() < 0.6 else "")
    return Candidate(name=sur + given, note=f"{g} · 별호 예: {alias}")


def _western_given(rng: random.Random, g: str) -> str:
    end = D.WEST_MALE_END if g == "남" else D.WEST_FEMALE_END
    head = rng.choice(D.WEST_HEAD)
    name = head + (rng.choice(D.WEST_MID) if len(head) == 1 else "") + rng.choice(end)
    return "" if name in D.WEST_CLICHE or len(name) > 4 else name


def _western(rng: random.Random, gender: str) -> Candidate:
    g = gender or rng.choice(["남", "여"])
    given = _western_given(rng, g)
    if not given:
        return None  # type: ignore[return-value]
    house = rng.choice(D.WEST_HOUSE_HEAD) + rng.choice(D.WEST_HOUSE_END)
    particle = rng.choice(["", "", " 폰", " 드"])
    return Candidate(name=f"{given}{particle} {house}", note=f"{g} · 이름 + 가문명")


def _japan(rng: random.Random, gender: str) -> Candidate:
    g = gender or rng.choice(["남", "여"])
    given = rng.choice(D.JA_MALE if g == "남" else D.JA_FEMALE)
    return Candidate(name=f"{rng.choice(D.JA_SURNAMES)} {given}", note=f"{g} · 성 + 이름")


def _sf(rng: random.Random, gender: str, year: int | None) -> Candidate:
    if rng.random() < 0.35:  # 한국계 인물도 섞는다
        c = _korean(rng, gender, year)
        return c and Candidate(name=c.name, note=c.note.split(" · ")[0] + " · 한국계")  # type: ignore[return-value]
    return Candidate(name=f"{rng.choice(D.SF_GIVEN)} {rng.choice(D.SF_FAMILY)}", note="여러 언어권 이름")


def generate_people(style: str, n: int = 8, gender: str = "", year: int | None = None,
                    exclude: set[str] | None = None, rng: random.Random | None = None) -> list[Candidate]:
    r = _rng(rng)
    g = _gender(gender)
    make = {
        "korea_modern": lambda: _korean(r, g, year),
        "joseon": lambda: _joseon(r, g),
        "wuxia": lambda: _wuxia(r, g),
        "western_fantasy": lambda: _western(r, g),
        "japan": lambda: _japan(r, g),
        "sf": lambda: _sf(r, g, year),
    }[style]
    return _collect(make, n, exclude or set())


# ---------- 지명 ----------

def _place(rng: random.Random, style: str, kind: str = "") -> Candidate:
    def fit(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return [x for x in pairs if x[1] == kind] or [x for x in pairs if kind and kind in x[1]] or pairs

    if style in ("korea_modern", "joseon"):
        two = lambda: "".join(rng.sample(D.KO_PLACE_SYL, 2))  # noqa: E731
        groups = [(0.3, D.KO_NATIVE_TAIL, lambda: rng.choice(D.KO_NATIVE_HEAD), "순우리말 땅이름 짜임"),
                  (0.7, D.KO_TOWN_KIND + D.KO_NATURE_KIND + (D.KO_SPOT_KIND if style == "korea_modern" else []), two, "한자 지명 짜임")]
        if style == "joseon":
            groups.append((0.6, D.JOSEON_PLACE_KIND, two, "옛 지명"))
        if kind:  # 그 종류가 있는 묶음만
            groups = [g for g in groups if any(k == kind for _, k in g[1])] or groups
        _, pairs, head, note = rng.choices(groups, weights=[g[0] for g in groups])[0]
        suf, k = rng.choice(fit(pairs))
        return Candidate(name=head() + suf, kind=k, note=note)
    if style == "wuxia":
        roll = rng.random()
        if (kind and "문파" in kind) or (not kind and roll < 0.3):
            if rng.random() < 0.3:
                return Candidate(name=rng.choice(D.WUXIA_FACTION_REAL), kind="문파", note="실제 장르 공용 문파")
            return Candidate(name="".join(rng.sample(D.WUXIA_PLACE_SYL, 2)) + rng.choice(D.WUXIA_FACTION_TAIL), kind="문파", note="가상 문파")
        suf, k = rng.choice(fit(D.WUXIA_PLACE_KIND))
        return Candidate(name="".join(rng.sample(D.WUXIA_PLACE_SYL, 2)) + suf, kind=k,
                         note=f"{rng.choice(D.WUXIA_REGIONS)} 지방")
    if style == "western_fantasy":
        suf, k = rng.choice(fit(D.WEST_PLACE_TAIL))
        head = rng.choice(D.WEST_HEAD)
        return Candidate(name=head + (rng.choice(D.WEST_MID) if len(head) == 1 else "") + suf, kind=k, note="음절 조합")
    if style == "japan":
        suf, k = rng.choice(fit(D.JA_PLACE_KIND))
        return Candidate(name=rng.choice(D.JA_PLACE_HEAD) + rng.choice(D.JA_PLACE_TAIL) + suf, kind=k, note="일본 땅이름 짜임")
    suf, k = rng.choice(fit(D.SF_PLACE_KIND))
    code = rng.choice(["", "", f"-{rng.randint(2, 9)}", f" {rng.choice('ABCDE')}"])
    return Candidate(name=rng.choice(D.SF_PLACE_HEAD) + code + suf, kind=k, note="천체 이름 + 시설")


def generate_places(style: str, n: int = 8, kind: str = "", exclude: set[str] | None = None,
                    rng: random.Random | None = None) -> list[Candidate]:
    r = _rng(rng)
    return _collect(lambda: _place(r, style, kind), n, exclude or set())


def place_kinds(style: str) -> list[str]:
    """화면에서 고를 수 있는 지명 종류."""
    pairs = {
        "korea_modern": D.KO_TOWN_KIND + D.KO_NATURE_KIND + D.KO_SPOT_KIND,
        "joseon": D.JOSEON_PLACE_KIND + D.KO_NATIVE_TAIL,
        "wuxia": D.WUXIA_PLACE_KIND + [("", "문파")],
        "western_fantasy": D.WEST_PLACE_TAIL,
        "japan": D.JA_PLACE_KIND,
        "sf": D.SF_PLACE_KIND,
    }[style]
    return list(dict.fromkeys(k for _, k in pairs))


# ---------- 작품 기준 후보 ----------

def _given(name: str, style: str) -> str:
    """성을 뺀 이름. 한국·무협은 앞의 성씨, 일본은 띄어 쓴 뒤쪽, 서양·SF 는 첫 낱말."""
    name = name.strip()
    if name in D.JOSEON_COMMON_MALE or name in D.JOSEON_COMMON_FEMALE:
        return name
    if style in ("korea_modern", "joseon", "wuxia"):
        for sur in sorted({*D.KO_SURNAMES, *D.WUXIA_SURNAMES}, key=len, reverse=True):
            if name.startswith(sur) and len(name) - len(sur) >= 1 and len(name) >= 3:
                return name[len(sur):]
        return name
    parts = name.split()
    if style == "japan" and len(parts) >= 2:
        return parts[-1]
    return parts[0] if parts else name


def _confusable(a: str, b: str, style: str = "korea_modern", bare: bool = False) -> str:
    """헷갈리는 이름이면 무엇이 같은지('첫 글자', '끝 글자', '앞 두 글자', '끝 두 글자'), 아니면 빈 글.
    서양 · SF 이름은 흔한 어미(-a, -n 등)를 한 글자로 비교하면 거의 다 걸려서 두 글자로 본다.
    성을 떼지 못한 두 글자 한국 · 무협 이름(bare: 성을 뗀 이름이 아니라 이름 전체)은 첫 글자가 성이라 첫 글자 비교를 하지 않는다."""
    if not (a and b) or a == b:
        return ""
    if style in ("western_fantasy", "sf"):
        if len(a) >= 2 and len(b) >= 2 and a[:2] == b[:2]:
            return "앞 두 글자"
        if len(a) >= 3 and len(b) >= 3 and a[-2:] == b[-2:]:
            return "끝 두 글자"
        return ""
    surname = bare and style in ("korea_modern", "joseon", "wuxia") and len(a) == 2 and len(b) == 2 and a[0] in {*D.KO_SURNAMES, *D.WUXIA_SURNAMES}
    if a[0] == b[0] and not surname:
        return "첫 글자"
    if len(a) > 1 and len(b) > 1 and a[-1] == b[-1]:
        return "끝 글자"
    return ""


def character_candidates(p: Project, c: Character, n: int = 8, style: str | None = None,
                         rng: random.Random | None = None) -> list[Candidate]:
    """이 인물에게 줄 후보. 다른 인물과 헷갈리는 이름은 먼저 빼고, 모자라면 채운다."""
    sid = resolve_style(p, style)
    others = [_given(o.name, sid) for o in p.characters if o is not c and o.id != c.id and o.name]
    pool = generate_people(sid, n * 3, c.gender, birth_year(c.age, p.world.era),
                           exclude={o.name for o in p.characters}, rng=rng)
    clear = [x for x in pool if not any(_confusable(_given(x.name, sid), o, sid) or _given(x.name, sid) == o for o in others)]
    return (clear + [x for x in pool if x not in clear])[:n]


def location_candidates(p: Project, n: int = 8, kind: str = "", style: str | None = None,
                        rng: random.Random | None = None) -> list[Candidate]:
    return generate_places(resolve_style(p, style), n, kind, exclude=set(known_places(p)), rng=rng)


# ---------- 이미 있는 장소와 비슷한 이름 ----------
# 연재가 길어지면 같은 곳을 '흑송촌', '흑송마을', '흑송 마을'처럼 흔들려 쓴다. 띄어쓰기와 같은 갈래의 끝말(마을 · 촌 · 리)만
# 다른 이름을 비슷하다고 본다. '흑송산'과 '흑송촌'처럼 갈래가 다르면 다른 곳으로 둔다.

PLACE_TAILS = [
    ("마을", "부락", "촌", "리", "동", "읍", "면", "골"),
    ("고개", "산", "봉", "령", "재", "악"),
    ("강", "천", "내", "호", "못", "늪"),
    ("숲", "림"),
    ("성", "궁", "전", "각", "루", "관", "원"),
    ("객잔", "주막", "여관", "여각"),
]


def place_key(name: str) -> str:
    """띄어쓰기와 가운뎃점, 따옴표를 뺀 비교용 이름."""
    return re.sub(r"[\s·・\-_'\"“”‘’]+", "", name)


def place_base(x: str) -> str:
    """설정 장소 칸의 '등대: 설명' 이면 '등대'."""
    return re.split(r"[:(（\-–—,]", x, maxsplit=1)[0].strip()


def known_places(p: Project) -> list[str]:
    """이미 있는 장소 이름: 설정의 장소 칸과 인과율 '장소' 요소의 이름 · 다른 이름."""
    out = [place_base(x) for x in p.world.locations]
    for el in p.elements:
        if el.kind == "장소":
            out += [el.name, *el.aliases]
    return [x for x in dict.fromkeys(x.strip() for x in out) if x]


def _tail(key: str) -> tuple[str, int]:
    """(끝말을 뺀 이름, 끝말 갈래). 갈래가 없으면 -1."""
    for i, group in enumerate(PLACE_TAILS):
        for t in sorted(group, key=len, reverse=True):
            if key.endswith(t) and len(key) - len(t) >= 2:
                return key[:-len(t)], i
    return key, -1


def similar_place(name: str, known: list[str]) -> str:
    """name 과 같은 곳을 달리 쓴 듯한 이미 있는 장소 이름. 없으면 빈 문자열. 완전히 같은 이름은 여기서 보지 않는다."""
    k = place_key(name)
    core, g = _tail(k)
    for other in known:
        o = place_key(other)
        if not o or o == k:
            continue
        oc, og = _tail(o)
        if len(core) >= 2 and core == oc and (g == og or -1 in (g, og)):
            return other
    return ""


def similar_warning(name: str, other: str) -> str:
    return f"새 장소 '{name}'{josa(name, '은', '는')} 이미 있는 '{other}'{josa(other, '과', '와')} 이름이 비슷해요. 같은 곳이면 한 이름으로 맞추세요"


# ---------- 점검 ----------

def _era_of(given: str) -> list[int]:
    return sorted({b for b, by in D.KO_GIVEN.items() for names in by.values() if given in names})


ISSUE_KINDS = {"same": "같은 이름", "given": "성을 뺀 이름이 같음", "confusable": "헷갈리는 이름", "era": "나이와 맞지 않는 이름",
               "style": "이름 스타일과 다름", "overused": "흔한 이름"}


def cast_issues(p: Project) -> list[dict]:
    """이름 점검. 막지 않고 알려만 준다. 인물과 인물 후보(cast_candidates)를 함께 본다.
    {kind, level(warn | info), text, ids} 목록이다. 같은 이름 · 같은 경고는 한 줄로 묶는다."""
    sid = resolve_style(p)
    people = [c for c in p.characters if c.name.strip()]
    have = {c.id for c in people}
    people += [c for c in p.cast_candidates if c.name.strip() and c.id not in have]

    def who(c) -> str:  # 같은 이름은 id 대신 역할 · 나이로 가른다
        tag = ", ".join(x for x in (c.role, c.age) if x)
        return f"{c.name}({tag})" if tag else c.name

    out: list[dict] = []
    by_name: dict[str, list] = {}
    for c in people:
        by_name.setdefault(c.name.strip(), []).append(c)
    for name, cs in by_name.items():
        if len(cs) > 1:
            out.append({"kind": "same", "level": "warn", "ids": [c.id for c in cs],
                        "text": f"'{name}' 이름이 {len(cs)}명에게 있어요: {' · '.join(who(c) for c in cs)}"})
    for a, b in combinations(people, 2):
        if a.name.strip() == b.name.strip():
            continue
        ga, gb = _given(a.name, sid), _given(b.name, sid)
        if ga == gb:
            out.append({"kind": "given", "level": "warn", "ids": [a.id, b.id],
                        "text": f"{_pair(a.name, b.name)} 성을 뺀 이름이 같아 독자가 헷갈려요."})
        elif same := _confusable(ga, gb, sid, bare=ga == a.name.strip() and gb == b.name.strip()):
            out.append({"kind": "confusable", "level": "info", "ids": [a.id, b.id],
                        "text": f"{_pair(a.name, b.name)} 이름 {same}{josa(same, '이', '가')} 같아 헷갈리기 쉬워요."})
    common = [c for c in people if _given(c.name, sid) in D.AI_OVERUSED or _given(c.name, sid) in D.WEST_CLICHE]
    if common:
        out.append({"kind": "overused", "level": "info", "ids": [c.id for c in common],
                    "text": f"AI가 자주 짓는 이름이라 다른 작품과 겹치기 쉬워요: {', '.join(dict.fromkeys(c.name for c in common))}"})
    for c in people:
        g = _given(c.name, sid)
        if sid == "korea_modern":
            year, eras = birth_year(c.age, p.world.era), _era_of(g)
            if year and eras and all(abs(e + 5 - year) > 20 for e in eras):
                span = f"{eras[0]}년대" if len(eras) == 1 else f"{eras[0]}~{eras[-1]}년대"
                out.append({"kind": "era", "level": "info", "ids": [c.id],
                            "text": f"{_topic(c.name)} {year}년생 무렵인데 '{g}'{josa(g, '은', '는')} {span} 출생에 흔한 이름이에요."})
        name = c.name.strip()
        if (sid in ("korea_modern", "joseon", "wuxia") and len(name) >= 3 and " " not in name
                and not any(name.startswith(s) for s in {*D.KO_SURNAMES, *D.WUXIA_SURNAMES})
                and name not in D.JOSEON_COMMON_MALE and name not in D.JOSEON_COMMON_FEMALE):
            out.append({"kind": "style", "level": "info", "ids": [c.id],
                        "text": f"'{name}'{josa(name, '은', '는') if _known(name) else ' 이름은'} 지금 이름 스타일({style_label(sid)})과 달라요. 의도했다면 세계관의 이름 규칙에 적어 두세요."})
    return out


def cast_warnings(p: Project) -> list[str]:
    """이름 점검 글만 (명령줄). 화면은 cast_issues 로 종류 · 인물별로 묶어 보인다."""
    return [i["text"] for i in cast_issues(p)]


# ---------- 프롬프트 블록 ----------

def _new_people(p: Project, sid: str, r: random.Random, n: int = 8) -> list[str]:
    """아직 없는 인물에 쓸 남녀 이름 후보 줄."""
    taken = {c.name for c in p.characters + p.cast_candidates}
    lines = []
    for g in ("남", "여"):
        year = None if sid != "korea_modern" else _ref_year(p.world.era) - r.choice([17, 24, 29, 35, 45])
        cands = generate_people(sid, n, g, year, exclude=taken, rng=r)
        if sid == "korea_modern":
            cands += generate_people(sid, n // 2, g, None, exclude=taken | {x.name for x in cands}, rng=r)
        lines.append(f"- 새 {g}자 인물 후보: {', '.join(x.name for x in cands)}")
    return lines


def new_cast_hint(p: Project, rng: random.Random | None = None) -> str:
    """플롯이 새 인물을 들일 때 쓰는 짧은 이름 안내 (지명 후보는 넣지 않는다)."""
    r = _rng(rng)
    sid = resolve_style(p)
    lines = [f"이름 스타일: {style_label(sid)}", *_new_people(p, sid, r, 6)]
    avoid = sorted(D.WEST_CLICHE if sid == "western_fantasy" else D.AI_OVERUSED)[:12]
    lines.append(f"- 피할 이름 (AI 가 자주 짓는 이름): {', '.join(avoid)}")
    if p.world.name_rules:
        lines.append("- 이 세계의 이름 규칙: " + " / ".join(p.world.name_rules))
    return "\n".join(lines)


def prompt_block(p: Project, rng: random.Random | None = None) -> str:
    """설정 도우미에 넣는 [이름·지명 후보]. 이름이 빈 인물은 인물별로, 없으면 성별별로 뽑는다."""
    r = _rng(rng)
    sid = resolve_style(p)
    lines = [f"이름 스타일: {style_label(sid)} (코드가 통계와 조합 규칙으로 무작위로 뽑은 후보입니다)"]
    blank = [c for c in p.characters if not c.name.strip()]
    for c in blank:
        cands = character_candidates(p, c, 6, rng=r)
        lines.append(f"- {c.id} ({c.role or '인물'}{', ' + c.age if c.age else ''}): {', '.join(x.name for x in cands)}")
    if not blank:
        lines += _new_people(p, sid, r)
    places = location_candidates(p, 6, rng=r)
    lines.append(f"- 장소 후보: {', '.join(f'{x.name}({x.kind})' for x in places)}")
    avoid = sorted(D.WEST_CLICHE if sid == "western_fantasy" else D.AI_OVERUSED)[:12]
    lines.append(f"- 피할 이름 (AI 가 자주 짓는 이름): {', '.join(avoid)}")
    if p.world.name_rules:
        lines.append("- 이 세계의 이름 규칙: " + " / ".join(p.world.name_rules))
    return "\n".join(lines)
