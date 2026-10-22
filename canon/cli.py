"""명령줄 인터페이스.

  python -m canon new 내소설           설정 도우미 (질문에 답하면 AI 가 빈칸 제안)
  python -m canon style 내소설 sample.txt   예시 텍스트로 스타일 프로필 생성
  python -m canon arc 내소설            기승전결 구간 설계
  python -m canon plot 내소설 [--from 1 --to 16]   화별 플롯 초안
  python -m canon confirm 내소설 all|3  플롯 확정
  python -m canon write 내소설 3        본문 생성
  python -m canon check 내소설 3        본문 검수 (앞선 본문·설정과의 모순, 근거 인용)
  python -m canon stats 내소설 [3]      문체 지표를 레퍼런스와 비교
  python -m canon update 내소설 3       상태 변경안 확인 후 반영
  python -m canon run 내소설            확정된 화를 순서대로 write → check → update
  python -m canon compare 내소설 3 [--a gemini --b local]   같은 화를 두 백엔드로 써서 이름을 가리고 비교
  python -m canon compare 내소설 3 --pick 2   고른 쪽을 본문으로 쓰고 어느 백엔드였는지 공개
  python -m canon brief 내소설 3        구독형 채팅 앱용 작업지시서 출력 (--state, --check)
  python -m canon import 내소설 3 본문.txt   다른 곳에서 쓴 본문 가져오기
  python -m canon show 내소설 [섹션]       섹션 rel 은 관계 역학을 보여 준다
  python -m canon view 내소설 numbers|words   관계를 숫자로 볼지 말로 볼지
  python -m canon adjust 내소설 a b --warmth 0.3 --trust 0.6   a 가 b 를 보는 관계를 직접 보정
  python -m canon revert 내소설 3       3화 상태 반영 직후로 되돌리기
  python -m canon recalc 내소설         계수(params)를 바꾼 뒤 사건 로그로 관계 재계산
  python -m canon serve [--port 8000]    웹 UI (브라우저 자동 열기, 끄려면 --no-browser)
설정은 projects/<이름>/project.json 을 직접 고쳐도 된다.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import dynamics, genres, metrics, pipeline, prompts, research, store
from .llm import dump, get_llm
from .schema import ConsistencyReport, Meta, Project, StateDelta


def ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes", "ㅛ")


# ---------- 명령 ----------

def cmd_new(a: argparse.Namespace) -> None:
    if store.exists(a.name):
        sys.exit(f"이미 있는 프로젝트입니다: {a.name}")
    print("기본 설정을 입력하세요. 모르는 칸은 비워 두면 AI 가 제안합니다.\n")
    genre_ids = genres.parse(a.genre or ask("장르 (쉼표로 여러 개, 목록: python -m canon genres)", "현대 드라마"))
    meta = Meta(
        title=a.title or ask("제목"),
        genres=genre_ids,
        genre=" · ".join(genres.names(genre_ids)),
        adult=a.adult,
        logline=a.logline or ask("로그라인 (누가, 무엇을 원하고, 무엇이 막는가)"),
        tone=ask("분위기/톤") if a.interactive else "",
        target_episodes=int(a.episodes or ask("총 화수 (10~20)", "16")),
        words_per_episode=int(ask("화당 분량(자)", "5000") if a.interactive else 5000),
    )
    p = Project(meta=meta)
    if a.interactive:
        hero = ask("주인공 이름과 한 줄 설명 (예: 서윤 - 사라진 오빠를 찾는 고등학생)")
        if hero:
            p.meta.notes = f"주인공: {hero}"
    store.save(a.name, p)
    if not a.no_suggest:
        _suggest(a.name, p, a.yes)


def _suggest(name: str, p: Project, yes: bool) -> None:
    print("\nAI 가 설정을 제안하는 중...")
    s = pipeline.suggest_setup(get_llm("plan"), p)
    print(dump(s))
    if confirm("이 제안을 반영할까요? (반영 후 project.json 에서 수정 가능)", yes):
        pipeline.apply_setup(p, s)
        print(f"저장: {store.save(name, p)}")


def cmd_suggest(a: argparse.Namespace) -> None:
    _suggest(a.name, store.load(a.name), a.yes)


def cmd_style(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    sample = Path(a.file).read_text(encoding="utf-8")
    profile = pipeline.analyze_style(get_llm("plan"), sample)
    print(dump(profile))
    if confirm("이 스타일 프로필을 저장할까요?", a.yes):
        p.style = profile
        p.style_baseline = metrics.measure(sample)
        print(f"저장: {store.save(a.name, p)}")


def cmd_arc(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    plan = pipeline.plan_arc(get_llm("plan"), p)
    for act in plan.acts:
        print(f"[{act.name}] {act.start_ep}~{act.end_ep}화  목표: {act.goal}  / 전환점: {act.key_turn}")
    if confirm("이 구조로 확정할까요?", a.yes):
        p.arc = plan.acts
        print(f"저장: {store.save(a.name, p)}")


def cmd_plot(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    start, end = a.start or 1, a.end or p.meta.target_episodes
    batch = pipeline.draft_plots(get_llm("plan"), p, start, end)
    for e in batch.episodes:
        print(f"\n{e.number}화 [{e.act}] {e.title}\n  {e.summary}\n  사건: {' / '.join(e.events)}\n  훅: {e.ending_hook}")
    pipeline.apply_plots(p, batch)
    print(f"\n초안 저장: {store.save(a.name, p)}  (수정 후 confirm 으로 확정)")


def cmd_confirm(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    targets = [e for e in p.episodes if a.which == "all" or e.plot.number == int(a.which)]
    for e in targets:
        if e.status == "draft":
            e.status = "confirmed"
    print(f"확정: {[e.plot.number for e in targets]}화")
    store.save(a.name, p)


def cmd_write(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _write(a.name, p, a.n)


def _write(name: str, p: Project, n: int) -> None:
    print(f"{n}화 생성 중...")
    text = pipeline.write_episode(get_llm("write"), p, n)
    ep = p.episode(n)
    ep.text, ep.status = text, "written"
    store.save(name, p)
    print(f"{n}화 저장: {store.project_dir(name) / 'episodes' / f'{n:02d}.md'} ({len(text)}자)")
    for w in pipeline.style_drift(p, n)[1]:
        print(f"! 문체: {w}")


def _strip_fence(raw: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw.strip())


def cmd_check(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if a.from_json:
        report = ConsistencyReport.model_validate_json(_strip_fence(Path(a.from_json).read_text(encoding="utf-8")))
        report.episode = a.n
        pipeline.apply_check(p, report)
        store.save(a.name, p)
    else:
        _check(a.name, p, a.n)
    _print_issues(p, a.n)


def _check(name: str, p: Project, n: int) -> None:
    print(f"{n}화 검수 중...")
    pipeline.apply_check(p, pipeline.check_episode(get_llm("check"), p, n))
    store.save(name, p)


def _print_issues(p: Project, n: int) -> None:
    issues = p.episode(n).issues
    if not issues:
        print(f"{n}화 검수: 모순 없음")
        return
    print(f"\n=== {n}화 검수: {len(issues)}건 ===")
    for i in issues:
        src = f"{i.source_episode}화" if i.source_episode else "설정"
        print(f"! [{i.type}] {i.description}\n    {src} 근거: {i.source_quote}\n    {n}화: {i.current_quote}")
        if i.suggestion:
            print(f"    제안: {i.suggestion}")


def _num(v: float | None) -> str:
    return "-" if v is None else str(v)


def cmd_genres(a: argparse.Namespace) -> None:
    for kind in ("장르", "요소"):
        print(f"[{kind}]")
        for g in genres.CATALOG:
            if g.kind == kind:
                print(f"  {g.name} ({g.id}): {g.summary}")
    print("\nnew --genre '로맨스 판타지, 회귀' 처럼 쓰고, 목록에 없는 장르도 그대로 적을 수 있습니다.")


def cmd_stats(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    base = pipeline.style_baseline(p)
    rows = [("기준", base, [])]
    rows += [(f"{e.plot.number}화", *pipeline.style_drift(p, e.plot.number))
             for e in p.episodes if e.text and (a.n is None or e.plot.number == a.n)]
    print(f"{'':>5} {'문장평균':>7} {'변화폭':>6} {'문단평균':>7} {'대사':>5} {'과거형':>6} {'어휘':>6} "
          f"{'쉼표':>5} {'짧은끝':>6} {'대명사':>6}  경고")
    for label, m, warns in rows:
        print(f"{label:>5} {m.sentence_len_mean:>7} {m.sentence_len_cv:>6} {m.paragraph_len_mean:>7} "
              f"{m.dialogue_ratio:>5} {_num(m.past_tense_ratio):>6} {_num(m.mattr):>6} "
              f"{_num(m.comma_sentence_ratio):>5} {_num(m.short_ending_ratio):>6} {_num(m.pronoun_per_1k):>6}  {len(warns) or ''}")
        for w in warns:
            print(f"      ! {w}")
    if not p.style_baseline:
        print("\n(기준은 문체 예시 발췌로 잰 값입니다. style 명령을 다시 실행하면 원문 전체로 잽니다.)")
    elif base.comma_sentence_ratio is None:
        print("\n(기준값이 예전 버전이라 쉼표, 짧은끝, 대명사는 비교하지 않았습니다. style 명령을 다시 실행하면 비교합니다.)")


def _print_delta(d: StateDelta) -> None:
    print(f"\n=== {d.episode}화 상태 변경안 ===\n요약: {d.summary}")
    for c in d.character_updates:
        print(f"- 인물 {c.character_id}: 감정={c.emotional_state} 목표={c.current_goal} 위치={c.location} 새로 앎={c.knows}")
    for e in d.events:
        extra = f" (목격: {', '.join(e.witnesses)})" if e.witnesses else ""
        secret = f" [비밀 {e.reveals_secret} 드러남]" if e.reveals_secret else ""
        print(f"- 사건 {e.actor} → {e.target}: {e.kind} 강도 {e.intensity}{extra}{secret}  \"{e.quote}\"")
    for r in d.relationship_updates:
        nums = "" if d.events else f": 호감 {r.affinity}, 긴장 {r.tension}"
        print(f"- 관계 {r.a}↔{r.b} ({r.type}){nums}  {r.description}")
    for s in d.secrets_added:
        print(f"- 새 비밀 {s.id} ({s.owner}): {s.content} / 모르는 인물 {s.hidden_from}")
    for f in d.new_facts:
        print(f"- 확정 사실: {f}")
    for f in d.foreshadow_planted:
        print(f"- 복선 심음 {f.id}: {f.description}")
    for f in d.foreshadow_resolved:
        print(f"- 복선 회수: {f}")
    for w in d.warnings:
        print(f"! 경고: {w}")


def _print_relation_preview(p: Project, d: StateDelta) -> None:
    """변경안을 복사본에 반영해 계산된 관계를 미리 보여 준다."""
    sim = p.model_copy(deep=True)
    pipeline.apply_delta(sim, d)
    text = dynamics.describe_relations(sim, numbers=p.settings.show_numbers)
    if text:
        print(f"\n--- 반영하면 이렇게 계산됩니다 ---\n{text}")


def cmd_update(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _update(a.name, p, a.n, a.yes, a.from_json)


def _update(name: str, p: Project, n: int, yes: bool, from_json: str | None = None) -> bool:
    if from_json:
        delta = StateDelta.model_validate_json(_strip_fence(Path(from_json).read_text(encoding="utf-8")))
        delta.episode = n
    else:
        print(f"{n}화 상태 추출 중...")
        delta = pipeline.extract_state(get_llm("state"), p, n)
    _print_delta(delta)
    _print_relation_preview(p, delta)
    if p.episode(n).issues:
        _print_issues(p, n)
    for w in pipeline.style_drift(p, n)[1]:
        print(f"! 문체: {w}")
    if not confirm("이 변경을 반영할까요? (아니오면 project.json 수정 후 다시 update)", yes):
        return False
    pipeline.apply_delta(p, delta)
    store.save(name, p)
    print(f"{n}화 확정 완료")
    return True


def cmd_run(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    for ep in p.episodes:
        n = ep.plot.number
        if ep.status == "finalized":
            continue
        if ep.status == "draft":
            print(f"{n}화 플롯이 확정되지 않아 멈춥니다.")
            return
        if ep.status == "confirmed":
            _write(a.name, p, n)
            if not a.no_check:
                _check(a.name, p, n)
        if not _update(a.name, p, n, a.yes):
            print("상태 반영을 보류해 멈춥니다.")
            return
    print("모든 화 완료")


def cmd_compare(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if a.pick:
        r = research.pick_compare(a.name, p, a.n, a.pick)
        store.save(a.name, p)
        print(f"{a.pick}번은 {r['picked']} 였습니다 (다른 쪽: {', '.join(r['others'])}). {a.n}화 본문으로 저장했습니다.")
        print("지금까지 고른 횟수: " + ", ".join(f"{prov} {cnt}" for prov, cnt in sorted(r["wins"].items())))
        return
    if a.a == a.b:
        sys.exit("--a 와 --b 가 같습니다")
    print(f"{a.n}화를 {a.a}, {a.b} 로 각각 쓰는 중...")
    c = research.run_compare(a.name, p, a.n, research.Backend(provider=a.a), research.Backend(provider=a.b))
    print(f"\n{'':>3} {'글자':>6} {'문장평균':>7} {'대사':>5} {'어휘':>6}  문체 경고")
    for d in c["drafts"]:
        print(f"{d['n']:>3} {d['chars']:>6} {d['sentence_len_mean']:>7} {d['dialogue_ratio']:>5} {_num(d['mattr']):>6}  {len(d['warnings']) or ''}")
        for w in d["warnings"]:
            print(f"      ! {w}")
    out = research.compare_dir(a.name, a.n)
    print(f"\n저장: {out}/1.md, 2.md (key.json 은 열지 마세요)\n읽어 보고 고르세요: compare {a.name} {a.n} --pick 1|2")


def cmd_brief(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    kind = "state" if a.state else "check" if a.check else "episode"
    text = {"state": prompts.state_brief, "check": prompts.check_brief, "episode": prompts.episode_brief}[kind](p, a.n)
    out = store.project_dir(a.name) / "briefs" / f"{a.n:02d}-{kind}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"작업지시서 저장: {out}\n(Claude / Gemini / ChatGPT 채팅에 그대로 붙여 넣으세요)")


def cmd_import(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    ep = p.episode(a.n)
    ep.text, ep.status = Path(a.file).read_text(encoding="utf-8").strip(), "written"
    store.save(a.name, p)
    print(f"{a.n}화 본문을 가져왔습니다. 다음: update {a.name} {a.n}  (또는 brief --state 로 채팅 앱에서 정리 후 update --from-json)")


def cmd_show(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if a.section == "rel":
        print(dynamics.describe_relations(p, numbers=p.settings.show_numbers) or "관계 없음")
        return
    if a.section:
        print(dump(getattr(p, a.section)))
        return
    m = p.meta
    print(f"《{m.title}》 {genres.label(m)}{' · 성인' if m.adult else ''} / {m.target_episodes}화\n로그라인: {m.logline}\n")
    print("인물:", ", ".join(f"{c.name}({c.id})" for c in p.characters) or "없음")
    print("스타일:", "있음" if p.style.sample_passages or p.style.narration_pov else "없음")
    for act in p.arc:
        print(f"[{act.name}] {act.start_ep}~{act.end_ep}화: {act.goal}")
    for e in p.episodes:
        print(f"  {e.plot.number:>2}화 {e.status:<9} {e.plot.title}")
    print(f"열린 복선: {sum(f.status == 'open' for f in p.foreshadows)}  확정 사실: {len(p.facts)}")


def cmd_serve(a: argparse.Namespace) -> None:
    from .web import serve

    serve(a.host, a.port, open_browser=not a.no_browser)


def cmd_view(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    p.settings.show_numbers = a.mode == "numbers"
    store.save(a.name, p)
    print("관계를 " + ("숫자로" if p.settings.show_numbers else "말로") + " 보여 줍니다")


def cmd_adjust(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if a.warmth is None and a.trust is None:
        sys.exit("--warmth 나 --trust 중 하나는 필요합니다")
    pipeline.adjust_tie(p, a.source, a.target, a.warmth, a.trust)
    store.save(a.name, p)
    print(dynamics.describe_relations(p, [a.source, a.target], numbers=p.settings.show_numbers))


def cmd_revert(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if not confirm(f"{a.n}화 상태 반영 직후로 되돌릴까요? 이후 화의 상태 반영이 취소됩니다 (본문은 유지)", a.yes):
        return
    pipeline.revert(p, a.n)
    print(f"되돌림 완료: {store.save(a.name, p)}")


def cmd_recalc(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    pipeline.recalc(p)
    store.save(a.name, p)
    print(dynamics.describe_relations(p, numbers=p.settings.show_numbers) or "관계 없음")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="canon", description="데이터 기반 AI 소설 생성기 (MVP)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, *args: str, yes: bool = True):
        sp = sub.add_parser(name)
        sp.add_argument("name")
        for arg in args:
            sp.add_argument(arg, type=int if arg == "n" else str)
        if yes:
            sp.add_argument("-y", "--yes", action="store_true", help="확인 없이 반영")
        sp.set_defaults(fn=fn)
        return sp

    sp = add("new", cmd_new)
    sp.add_argument("--title", default="")
    sp.add_argument("--genre", default="", help="쉼표로 여러 개 (python -m canon genres 로 목록)")
    sp.add_argument("--adult", action="store_true", help="성인 독자 대상 작품")
    sp.add_argument("--logline", default="")
    sp.add_argument("--episodes", default="")
    sp.add_argument("--no-suggest", action="store_true")
    sp.add_argument("-i", "--interactive", action="store_true", help="톤, 분량, 주인공까지 질문")
    add("suggest", cmd_suggest)
    add("style", cmd_style, "file")
    add("arc", cmd_arc)
    sp = add("plot", cmd_plot, yes=False)
    sp.add_argument("--from", dest="start", type=int)
    sp.add_argument("--to", dest="end", type=int)
    add("confirm", cmd_confirm, "which", yes=False)
    add("write", cmd_write, "n", yes=False)
    sp = add("update", cmd_update, "n")
    sp.add_argument("--from-json", help="채팅 앱에서 받은 상태 변경 JSON 파일")
    sp = add("check", cmd_check, "n", yes=False)
    sp.add_argument("--from-json", help="채팅 앱에서 받은 검수 결과 JSON 파일")
    sp = add("stats", cmd_stats, yes=False)
    sp.add_argument("n", type=int, nargs="?")
    sp = add("run", cmd_run)
    sp.add_argument("--no-check", action="store_true", help="화마다 검수 호출을 건너뜀")
    sp = add("compare", cmd_compare, "n", yes=False)
    sp.add_argument("--a", default="gemini", choices=["gemini", "local", "mock"])
    sp.add_argument("--b", default="local", choices=["gemini", "local", "mock"])
    sp.add_argument("--pick", type=int, choices=[1, 2], help="고른 번호. 본문으로 저장하고 백엔드를 공개")
    sp = add("brief", cmd_brief, "n", yes=False)
    sp.add_argument("--state", action="store_true", help="상태 정리용 작업지시서")
    sp.add_argument("--check", action="store_true", help="검수용 작업지시서")
    add("import", cmd_import, "n", "file", yes=False)
    sp = add("show", cmd_show, yes=False)
    sp.add_argument("section", nargs="?")

    sub.add_parser("genres", help="장르 목록").set_defaults(fn=cmd_genres)

    sp = sub.add_parser("serve", help="웹 UI 실행")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음 (서버에서 상시 실행할 때)")
    sp.set_defaults(fn=cmd_serve)

    sp = add("view", cmd_view, yes=False)
    sp.add_argument("mode", choices=["numbers", "words"])
    sp = add("adjust", cmd_adjust, "source", "target", yes=False)
    sp.add_argument("--warmth", type=float, help="-1 ~ 1")
    sp.add_argument("--trust", type=float, help="0 ~ 1")
    add("revert", cmd_revert, "n")
    add("recalc", cmd_recalc, yes=False)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
        sys.exit(f"오류: {e}")
