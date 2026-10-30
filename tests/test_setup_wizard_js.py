"""설정 도우미 새 작품 마법사(static/setup.js)의 순수 함수: 필수 칸, 걸음 상태, 세계 종류 · 시대 고르기.
node 가 있을 때만 돈다."""
from canon.schema import Character, Project, Relationship

from .jsvm import dump, needs_node, run_js

FILES = ["app.js", "home.js", "setup.js"]


def full() -> Project:
    p = Project()
    p.meta.title = "소금 정원의 계약"
    p.meta.genres = ["romance_fantasy"]
    p.meta.logline = "서윤이 염전을 되찾으려 한다."
    p.world.setting = "북방 왕국"
    p.characters = [Character(id="hero", name="서윤", role="주인공"), Character(id="char2", name="이헌", role="상대역")]
    p.relationships = [Relationship(a="hero", b="char2", type="계약 부부")]
    return p


@needs_node
def test_reqs_follow_each_field():
    blank = Project()
    one_name = full()
    one_name.characters[1].name = "  "
    self_rel = full()
    self_rel.relationships = [Relationship(a="hero", b="hero", type="")]
    ghost_rel = full()
    ghost_rel.relationships = [Relationship(a="hero", b="gone", type="")]
    got = run_js(FILES, "data.map((p) => setupReqs(p))", [dump(p) for p in (blank, full(), one_name, self_rel, ghost_rel)])
    assert got == [
        [False] * 6,
        [True] * 6,
        [True, True, True, True, False, True],
        [True, True, True, True, True, False],
        [True, True, True, True, True, False],
    ]


@needs_node
def test_first_gap_and_step_state():
    blank = Project()
    no_world = full()
    no_world.world.setting = ""
    expr = """[wizFirstGap(data[0]), wizFirstGap(data[1]), wizFirstGap(data[2]),
      [0, 1, 2, 3, 4, 5].map((i) => wizStepState(data[1], i, [0, 1, 2])),
      [0, 1, 2, 3, 4, 5].map((i) => wizStepState(data[0], i, [0]))]"""
    got = run_js(FILES, expr, [dump(blank), dump(no_world), dump(full())])
    assert got[:3] == [0, 2, 5]
    # 세계를 비웠다: 들른 세계 걸음은 주황, 들르지 않은 마무리는 아직
    assert got[3] == ["done", "done", "miss", "done", "done", ""]
    # 빈 작품: 지금 걸음(0)도 들른 걸음이라 주황, 나머지는 아직
    assert got[4] == ["miss", "", "", "", "", ""]


@needs_node
def test_world_kind_keeps_written_text():
    expr = """(() => {
      const a = withWorldKind('', '서양풍 제국');
      const b = withWorldKind(a + ' 북쪽 끝에 염전이 있다.', '중세 판타지 왕국');
      const c = withWorldKind(b, '중세 판타지 왕국');
      const d = withWorldKind('직접 쓴 배경.', '현대 한국');
      return [a, worldKindOf(a), b, worldKindOf(b), c, worldKindOf(c), d, worldKindOf('아무 글')];
    })()"""
    assert run_js(FILES, expr, None) == [
        "귀족과 황실이 다스리는 서양풍 제국.", "서양풍 제국",
        "검과 마법이 있는 중세풍 왕국. 북쪽 끝에 염전이 있다.", "중세 판타지 왕국",
        "북쪽 끝에 염전이 있다.", "",
        "지금의 한국. 직접 쓴 배경.", "",
    ]


@needs_node
def test_world_recs_follow_genre_order():
    expr = "[worldRecs(['romance_fantasy', 'fantasy'], 0), worldRecs(['romance_fantasy', 'fantasy'], 1), worldRecs(['bl'], 0), worldRecs([], 1)]"
    assert run_js(FILES, expr, None) == [
        ["서양풍 제국", "중세 판타지 왕국"], ["중세풍", "근세풍"], [], [],
    ]


@needs_node
def test_recs_name_real_choices():
    """추천 표는 세계 종류 · 시대 목록에 있는 말과 genres.CATALOG 에 있는 id 만 쓴다."""
    from canon.genres import CATALOG

    expr = """[Object.keys(WORLD_REC), Object.values(WORLD_REC).flatMap((r) => r[0]).filter((x) => !WORLD_KINDS.some(([l]) => l === x)),
      Object.values(WORLD_REC).flatMap((r) => r[1]).filter((x) => !ERAS.includes(x))]"""
    ids, bad_world, bad_era = run_js(FILES, expr, None)
    assert set(ids) <= {g.id for g in CATALOG}
    assert bad_world == [] and bad_era == []


@needs_node
def test_doc_status_marks_sections():
    """기획서 목차: 필수를 채웠고 볼 것이 없는 구역만 ✓, 빈 칸 있는 인물 · 볼 관계는 주황 글."""
    done = full()
    done.characters[0].goal = "염전을 되찾는다"
    for c in done.characters:
        c.wound, c.speech_style, c.goal = "약점", "짧게 말한다", c.goal or "원한다"
    done.relationships[0].a_view = ["믿는다"]
    gaps = full()
    gaps.relationships.append(Relationship(a="char2", b="hero", type=""))  # 같은 쌍 · 사이 없음
    gaps.meta.theme = "주제"
    got = run_js(FILES, "data.map((p) => docStatus(p))", [dump(done), dump(gaps), dump(Project())])
    assert [x["done"] for x in got[0]] == [True, True, True, True, True, False]
    assert got[0][3]["text"] == "2명" and got[0][4]["text"] == "1개" and got[0][5]["text"] == "0/3"
    # 인물 둘 다 빈 칸, 관계 둘 다 볼 것(첫째는 보는 방식 없음, 둘째는 같은 쌍 · 사이 없음)
    assert got[1][3] == {"done": False, "text": "빈 칸 2명", "warn": True}
    assert got[1][4] == {"done": False, "text": "확인 2", "warn": True}
    assert got[1][5]["text"] == "1/3"
    # 빈 작품: 로그라인 비어 있음, 인물 · 관계는 필수가 비어 주황
    assert got[2][1] == {"done": False, "text": "비어 있음", "warn": True}
    assert got[2][3]["warn"] and got[2][4]["warn"]


@needs_node
def test_rel_issue_and_summary():
    p = full()
    p.relationships += [Relationship(a="hero", b="hero", type=""), Relationship(a="char2", b="hero", type="동료")]
    no_cast = Project()
    no_cast.meta.title = "제목"
    no_world = full()
    no_world.world.setting = ""
    expr = """[data[0].relationships.map((r, i) => relIssue(data[0], r, i)), data.map(docSummary)]"""
    issues, sums = run_js(FILES, expr, [dump(p), dump(no_cast), dump(no_world)])
    assert issues == [2, "same", 0]  # 같은 쌍은 서로를 가리킨다
    assert sums[0] == "필수 여섯 칸을 다 채웠어요. 남은 것: 인물 빈 칸 2명, 관계 확인 3"
    assert sums[1].startswith("인물이 없어요.")
    assert sums[2] == "필수 칸이 1개 남았어요: 세계 배경"
