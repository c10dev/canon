"""작품 도구 화면 셋(static/auto.js · write.js viewBrief · branches.js)이 공용 목차 틀로 그려지는지와 순수 함수.
node 가 있을 때만 돈다."""
import re

from canon.schema import Meta, Project

from .jsvm import STATIC, dump, episode, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
TEXT = "첫 문단.\n\n같은 문단.\n\n끝 문단."


def project():
    eps = [episode(n, status="finalized", text=TEXT, plot={"title": f"{n}화 제목"}, summary="요약") for n in range(1, 4)]
    eps[2].auto = True
    eps.append(episode(4, status="written", text=TEXT, plot={"title": "넷째"}))
    eps.append(episode(5, status="confirmed", plot={"title": "다섯째"}))
    return Project(meta=Meta(title="t", target_episodes=6), episodes=eps)


RUN = {
    "target": 6, "batch": False, "status": "review", "ep": 4, "step": "review", "halt": "review", "restarts": 0,
    "reasons": ["검수에서 어긋난 곳 2개 (보통 2)", "관계가 크게 움직였어요: 서윤→강혁 온기 +0.10, 신뢰 -0.42", "상태 변경안 경고 1개: 무엇"],
    "pending": {"episode": 4, "summary": "s"}, "pending_text": TEXT, "batches": {}, "applied": [3],
    "tokens_in": 328000, "tokens_out": 31900, "cost": 1.84, "started": "2026-10-31T01:00:00+00:00", "updated": "2026-10-31T01:16:00+00:00",
    "policy": {"check": True, "max_issues": 0, "ignore_minor": False, "stop_on_critical": True, "max_shift": 0.3, "stop_on_stage": False,
               "stop_on_warnings": False, "confirm_plots": False, "review_every": 0, "hand_pick_opening": True, "storyboard": True,
               "stop_on_board_warnings": True, "cue_sheet": True},
    "log": [
        {"at": "2026-10-30T01:00:00+00:00", "step": "start", "level": "info", "message": "지난 실행"},
        {"at": "2026-10-30T01:01:00+00:00", "ep": 2, "step": "write", "level": "info", "message": "2화 본문", "tokens_in": 9, "tokens_out": 9},
        {"at": "2026-10-31T01:00:00+00:00", "step": "start", "level": "info", "message": "6화까지 자동 집필을 시작했어요"},
        {"at": "2026-10-31T01:02:00+00:00", "ep": 3, "step": "write", "level": "info", "message": "3화 본문", "tokens_in": 100, "tokens_out": 10, "seconds": 70},
        {"at": "2026-10-31T01:03:00+00:00", "ep": 3, "step": "write", "level": "warn", "message": "문체: 문장 끝 '-었다' 71%"},
        {"at": "2026-10-31T01:04:00+00:00", "ep": 3, "step": "applied", "level": "info", "message": "3화를 반영했어요"},
        {"at": "2026-10-31T01:06:00+00:00", "ep": 4, "step": "write", "level": "info", "message": "4화 본문", "tokens_in": 200, "tokens_out": 20},
    ],
}


@needs_node
def test_auto_view_and_helpers():
    got = run_js(FILES, """(() => {
      S.project = data.p; S.name = 't'; S.route = ['p', 't', 'auto'];
      S.auto = { run: data.run, active: false, batch_stages: [] };
      const est = { episodes: 2, from: 5, to: 6, missing: [], drafts: [], calls: { write: 2, check: 2, state: 2 }, stages: {}, cost: 0, tokens_in: 1, tokens_out: 1, seconds_min: 60, model: 'm' };
      S.autoEst = { off: est, on: est };
      const view = viewAuto();
      S.autoRunPolicyOpen = true;
      const edit = viewAuto();
      S.auto = { run: null, active: false, batch_stages: [] }; S.autoForm = null;
      const fresh = viewAuto();
      S.autoEst = { off: { episodes: 0, from: 7, to: 6, missing: [], drafts: [], calls: {}, stages: {} }, on: {} };
      const none = viewAuto();
      return {
        view, edit, fresh, none,
        cells: autoCells(data.p, data.run).map((c) => [c.n, c.cls]),
        big: autoCells({ episodes: [] }, { target: 300, ep: 120, status: 'running', applied: [] }).map((c) => c.n),
        groups: autoLogGroups(data.run.log).map((g) => [g.ep, g.lines, g.warns.length, g.tin]),
        links: data.run.reasons.map((x) => autoReasonLink(x, 4)),
        summary: autoPolicySummary(data.run.policy),
      };
    })()""", {"p": dump(project()), "run": RUN})
    v = got["view"]
    assert 'id="au-toc"' in v and 'data-action="autoGo" data-arg="halt"' in v  # 목차
    assert v.count("btn primary") == 1 and 'data-action="autoOpenReview"' in v  # 머리 주 버튼 하나
    assert 'href="#/p/t/check/4">4화 검수 결과 보기' in v and 'href="#/p/t/cast">관계도 보기' in v  # 이유마다 갈 곳
    assert "pf-dl" in v and 'data-action="autoPolicyEdit"' in v and 'data-auto-run=' not in v  # 정책은 읽기 먼저
    assert 'data-auto-run="policy.check"' in got["edit"] and "고치는 중" in got["edit"]
    assert got["cells"] == [[1, "finalized"], [2, "finalized"], [3, "auto"], [4, "written cur"], [5, "confirmed"], [6, ""]]
    assert got["big"][0] == 111 and len(got["big"]) == 40
    assert got["groups"] == [[4, ["4화 본문"], 0, 200], [3, ["3화 본문 1분", "3화를 반영했어요"], 1, 100]]  # 이번 실행만, 최신 화부터
    assert got["links"][0]["href"] == "#/p/t/check/4" and got["links"][1]["href"] == "#/p/t/cast" and got["links"][2] is None
    assert got["summary"][1] == ["멈추는 때", "검수 어긋남 1개부터 · 치명 지적 · 관계 0.3 넘게 움직임 · 1~3화 직접 고름"]
    assert 'id="au-toc"' not in got["fresh"] and 'data-action="autoStart"' in got["fresh"] and "btn primary" in got["fresh"]
    assert "card empty" in got["none"] and "마지막 화까지 모두 반영했어요" in got["none"] and 'data-auto="target"' not in got["none"]


@needs_node
def test_brief_view_steps():
    got = run_js(FILES, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'brief', '4'];
      S.briefTab = 'check'; S.briefText = '지시서 글';
      const check = viewBrief(4);
      S.route = ['p', 't', 'brief', '5']; S.briefTab = 'state';
      const blocked = viewBrief(5);
      S.briefTab = 'episode';
      const body = viewBrief(5);
      return { check, blocked, body, json: ['', '```json\\n{"a": 1}\\n```', '{"a":'].map((x) => briefJsonState(x).ok) };
    })()""", dump(project()))
    c = got["check"]
    assert 'id="brief-toc"' in c and '<h1>4화 넷째</h1>' in c and 'role="tab"' not in c
    assert 'aria-current="step"' in c and '<span class="n ok">✓</span><span class="tl">본문 작성</span><span class="st">끝남</span>' in c
    assert c.count("btn primary") == 1 and 'data-action="importCheck" data-arg="4"' in c and "pre class=\"brief mono fold\"" in c
    assert "card empty" in got["blocked"] and "5화 본문이 아직 없어 상태 승인 지시서를" in got["blocked"] and "btn primary\" data-action=\"importJson" not in got["blocked"]
    assert '<span class="tl">검수</span><span class="st">본문 뒤</span>' in got["body"]
    assert 'data-action="importText" data-arg="5" disabled' in got["body"]  # 4화 반영 전이라 순서에 막힘
    assert got["json"] == [None, True, False]


FAM = {"main": "t", "members": [
    {"name": "t", "title": "등대", "info": {"id": "a", "family": "f", "parent": "", "from_ep": 0, "label": ""}, "parent_name": "", "depth": 0, "finalized": 3, "planned": 6, "episodes": 6},
    {"name": "t-b", "title": "등대", "info": {"id": "b", "family": "f", "parent": "a", "from_ep": 2, "label": "B안"}, "parent_name": "t", "depth": 1, "finalized": 3, "planned": 6, "episodes": 6, "shared_edited": True},
]}
DIFF = {"from_ep": 2, "episode": 3, "ready_a": True, "ready_b": True, "with": "t", "text_a": "첫 문단.\n\nB의 문단.\n\n끝 문단.", "text_b": TEXT,
        "episodes": [{"number": 2, "a": {"title": "가", "status": "finalized", "summary": "요"}, "b": {"title": "나", "status": "finalized", "summary": "약"}},
                     {"number": 3, "a": {"title": "다", "status": "finalized", "summary": ""}, "b": {"title": "라", "status": "finalized", "summary": ""}},
                     {"number": 6, "a": {"title": "", "status": "draft", "summary": ""}, "b": {"title": "", "status": "draft", "summary": ""}}],
        "rows": [{"kind": "character", "who": "서윤", "field": "목표", "a": "떠난다", "b": "지킨다"}]}


@needs_node
def test_branch_compare_and_place():
    got = run_js(FILES, """(() => {
      S.project = data.p; S.name = 't-b'; S.route = ['p', 't-b', 'branches'];
      S.branchFam = { ...data.fam, name: 't-b' }; S.branchDiff = data.diff;
      const view = viewBranches();
      const strip = branchStrip('write');
      const placed = branchPlace('write', '<header class="page-head"><h1>x</h1></header><section>본문</section>');
      const bare = branchPlace('write', '<div class="w-stick">x</div>');
      const onPage = branchStrip('branches');
      S.branchForm = { name: 't-b', from: '2', label: '', to: 't-b-갈래', mode: 'clear', err: null };
      const form = branchFormCard();
      S.branchFam = null; S.branchForm = null;
      const empty = viewBranches();
      return { view, strip, placed, bare, onPage, form, empty,
        diff: bcParaDiff('첫.\\n\\nA만.\\n\\n끝.', '첫.\\n\\nB만.\\n\\nB둘.\\n\\n끝.') };
    })()""", {"p": dump(project()), "fam": FAM, "diff": DIFF})
    v = got["view"]
    assert 'id="bc-toc"' in v and 'href="#/p/t-b/branches/t" style="--depth:0" aria-current="true"' in v  # 견줄 작품은 목차 줄
    assert '<select id="bc-with"' not in v and 'class="bc-row on"' in v and "6화는 양쪽 모두 플롯 초안이라 뺐어요" in v
    assert v.count('class="bc-pair"') == 1 and 'only-a' in v and "같은 문단 2개를 접었어요" in v  # 다른 문단만
    assert 'data-action="menuToggle" data-arg="bm-t-b"' in v and "끊기" not in v  # 본편으로 올리기 · 끊기는 ⋯ 메뉴 안
    assert got["strip"].startswith('<div class="note info branch-strip"') and "B안" in got["strip"] and "따로" not in got["strip"]
    assert got["placed"].index("branch-strip") > got["placed"].index("</header>")  # 머리 아래
    assert got["bare"].index("branch-strip") < got["bare"].index("w-stick")
    assert "branch-strip" not in got["onPage"] and "1화를 고쳤어요" in got["onPage"]  # 비교 화면은 경고만
    assert 'class="br-cells"' in got["form"] and "2화부터 갈래 만들기" in got["form"] and '<details class="br-folder">' in got["form"]
    assert "card empty" in got["empty"] and 'data-action="branchOpen">갈래 만들기' in got["empty"]
    assert got["diff"] == [{"a": "첫.", "b": "첫.", "same": True}, {"a": "A만.", "b": "B만.", "same": False},
                           {"a": None, "b": "B둘.", "same": False}, {"a": "끝.", "b": "끝.", "same": True}]
