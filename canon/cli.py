"""명령줄 인터페이스.

  python -m canon new 내소설           설정 도우미 (질문에 답하면 AI 가 빈칸 제안)
  python -m canon style 내소설 sample.txt   예시 텍스트로 스타일 프로필 생성 (--save 이름: 라이브러리에도 저장)
  python -m canon style 내소설 --library ID   문체 라이브러리 항목을 작품에 적용
  python -m canon styles [add 이름 파일 | show ID | rm ID]   문체 라이브러리 (작품과 따로 저장)
  python -m canon arc 내소설            기승전결 구간 설계
  python -m canon plot 내소설 [--from 1 --to 16]   화별 플롯 초안
  python -m canon revise 내소설 "3화 전개가 너무 빨라"   말로 구조와 플롯 고치기 (변경안 확인 후 반영, 대화는 웹과 같이 저장)
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
  python -m canon upgrade               main 의 새 코드 받기 (serve 는 시작할 때와 10분마다 알아서 받는다)
설정은 projects/<이름>/project.json 을 직접 고쳐도 된다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from . import dynamics, genres, library, logline, metrics, naming, pipeline, prompts, research, store, updater
from .llm import dump, get_llm
from .schema import ConsistencyReport, LoglineParts, Meta, Project, StateDelta


def ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes", "ㅛ")


def ask_logline(genre_ids: list[str]) -> LoglineParts:
    """로그라인을 다섯 칸으로 묻는다. 고른 장르의 예시를 먼저 보여 준다."""
    examples = [ex for gid in genre_ids if gid in genres.BY_ID for ex in genres.BY_ID[gid].logline][:2]
    print("\n로그라인을 다섯 칸으로 나눠 씁니다. 모르는 칸은 비워 두세요.")
    for ex in examples:
        print(f"  예: {logline.compose(ex)}")
    parts = LoglineParts(
        who=ask("누가 (이름보다 특징이 먼저 보이게, 예: 사진관을 하는 채은)"),
        why=ask("무엇 때문에 (이야기를 시작하게 만드는 일)"),
        goal=ask("무엇을 하려 하나 (눈에 보이는 행동, '~한다'로 끝내기)"),
        block=ask("무엇이 막나 (사람이나 힘)"),
        stake=ask("무엇이 걸렸나 (선택)"),
    )
    if not logline.is_empty(parts):
        print(f"\n로그라인: {logline.compose(parts)}")
        for ok, label in logline.checks(parts):
            print(f"  {'✓' if ok else '·'} {label}")
    return parts


# ---------- 명령 ----------

def cmd_new(a: argparse.Namespace) -> None:
    if store.exists(a.name):
        sys.exit(f"이미 있는 프로젝트입니다: {a.name}")
    print("기본 설정을 입력하세요. 모르는 칸은 비워 두면 AI 가 제안합니다.\n")
    genre_ids = genres.parse(a.genre or ask("장르 (쉼표로 여러 개, 목록: python -m canon genres)", "현대 드라마"))
    title = a.title or ask("제목")
    parts = LoglineParts()
    if a.logline:
        line = a.logline
    elif a.interactive:
        parts = ask_logline(genre_ids)
        line = logline.compose(parts)
    else:
        line = ask("로그라인 (누가, 무엇 때문에, 무엇을 하려 하고, 무엇이 막는가)")
    meta = Meta(
        title=title,
        genres=genre_ids,
        genre=" · ".join(genres.names(genre_ids)),
        adult=a.adult,
        logline=line,
        logline_parts=parts,
        theme=ask("주제 (이 이야기가 끝까지 묻는 질문 하나, 예: 떠난 사람을 이해하면 용서할 수 있나?)") if a.interactive else "",
        tone=ask("분위기/톤 (예: 조금 어둡고 진지하고 호흡이 느리다)") if a.interactive else "",
        target_episodes=int(a.episodes or ask("총 화수 (10~20)", "16")),
        words_per_episode=int(ask("화당 분량(자)", "5000") if a.interactive else 5000),
    )
    p = Project(meta=meta)
    if a.interactive:
        hero = ask("주인공 이름과 한 줄 설명 (예: 채은 - 사라진 오빠를 찾는 고등학생)")
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
    if a.library:
        e = library.load(a.library)
        print(dump(e.profile))
        if confirm(f"라이브러리 문체 '{e.name}' 을 적용할까요? 지금 작품의 문체는 바뀝니다.", a.yes):
            library.apply(p, e)
            print(f"저장: {store.save(a.name, p)}")
        return
    if not a.file:
        sys.exit("예시 원문 파일이나 --library ID 를 주세요 (라이브러리 목록: python -m canon styles)")
    sample = Path(a.file).read_text(encoding="utf-8")
    profile = pipeline.analyze_style(get_llm("plan"), sample)
    print(dump(profile))
    if confirm("이 스타일 프로필을 저장할까요?", a.yes):
        p.style = profile
        p.style_baseline = metrics.measure(sample)
        p.style_id = ""
        if a.save:
            e = library.from_project(p, a.save, sample)
            print(f"라이브러리에 저장: {e.name} ({e.id})")
        print(f"저장: {store.save(a.name, p)}")


def cmd_styles(a: argparse.Namespace) -> None:
    if a.action == "add":
        if not a.args or len(a.args) != 2:
            sys.exit("사용법: python -m canon styles add 이름 원문.txt")
        name, file = a.args
        sample = Path(file).read_text(encoding="utf-8")
        profile = pipeline.analyze_style(get_llm("plan"), sample)
        print(dump(profile))
        if confirm("이 문체를 라이브러리에 저장할까요?", a.yes):
            e = library.create(name, profile, sample, a.source)
            print(f"저장: {e.name} ({e.id})")
        return
    if a.action in ("show", "rm"):
        if len(a.args) != 1:
            sys.exit(f"사용법: python -m canon styles {a.action} ID")
        e = library.load(a.args[0])
        if a.action == "show":
            print(f"{e.name} ({e.id})  출처: {e.source or '-'}  원문 {len(e.sample):,}자")
            print(dump(e.profile))
            return
        used = library.used_by(e.id)
        note = f" 쓰는 작품({', '.join(used)})은 복사해 둔 문체를 그대로 씁니다." if used else ""
        if confirm(f"'{e.name}' 을 라이브러리에서 지울까요?{note}", a.yes):
            library.delete(e.id)
            print("지웠습니다")
        return
    rows = library.entries()
    if not rows:
        print("문체 라이브러리가 비어 있습니다. styles add 이름 원문.txt 로 추가하세요.")
    for e in rows:
        used = library.used_by(e.id)
        print(f"{e.id}  {e.name}  {e.profile.narration_pov or '-'} / {e.profile.tense or '-'}"
              f"  원문 {len(e.sample):,}자  작품 {len(used)}개{'  (' + ', '.join(used) + ')' if used else ''}")
    print(f"\n저장 위치: {library.root()}")


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


def cmd_revise(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    rev = pipeline.revise_plot(get_llm("plan"), p, a.message)
    msg = pipeline.record_chat(p, "plot", a.message, rev)
    print(rev.reply)
    if rev.total_episodes:
        print(f"\n총 화수: {p.meta.target_episodes}화 → {rev.total_episodes}화")
    for act in rev.acts:
        print(f"[{act.name}] {act.start_ep}~{act.end_ep}화  목표: {act.goal}  / 전환점: {act.key_turn}")
    for e in rev.episodes:
        cur = next((x for x in p.episodes if x.plot.number == e.number), None)
        mark = f" ({cur.status})" if cur else " (새 화)"
        print(f"\n{e.number}화{mark} {e.title}\n  {e.summary}\n  사건: {' / '.join(e.events)}\n  훅: {e.ending_hook}")
    if msg.revision and confirm("이 변경안을 모두 반영할까요? (확정된 화는 초안으로 돌아갑니다)", a.yes):
        msg.applied = pipeline.apply_revision(p, rev, True, [e.number for e in rev.episodes])
        msg.outcome = "applied"
    elif msg.revision:
        msg.outcome = "dismissed"
    print(f"저장: {store.save(a.name, p)}")


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


def cmd_names(a: argparse.Namespace) -> None:
    """세계관에 맞는 이름·지명 후보. --ai 면 '이름·지명' 단계 모델이 골라 이유를 붙인다."""
    p = store.load(a.name)
    if a.style and a.style not in naming.STYLE_IDS:
        raise ValueError(f"이름 스타일은 {' | '.join(sorted(naming.STYLE_IDS))} 중 하나입니다")
    sid = naming.resolve_style(p, a.style)
    if a.check:
        warns = naming.cast_warnings(p)
        print("\n".join(f"  ! {w}" for w in warns) or "  이름 점검: 문제 없음")
        return
    target = f"인물 {a.character}" if a.character else f"지명{f' ({a.place})' if a.place else ''}"
    print(f"[{naming.style_label(sid)}] {target}")
    if a.ai:
        cands, opts = pipeline.suggest_names(get_llm("name"), p, a.character, a.place or "", a.n, a.style)
        picks = [o.name for o in opts.options]
        for i, o in enumerate(opts.options, 1):
            print(f"  {i}. {o.name}  - {o.reason}")
    else:
        cands = pipeline.name_candidates(p, a.character, a.place or "", a.n, a.style)
        picks = [c.name for c in cands]
        for i, c in enumerate(cands, 1):
            print(f"  {i}. {c.name}" + (f" ({c.kind})" if c.kind else "") + (f"  - {c.note}" if c.note else ""))
    if not a.pick:
        return
    if not 1 <= a.pick <= len(picks):
        raise ValueError(f"--pick 은 1~{len(picks)} 사이입니다")
    chosen = picks[a.pick - 1]
    if a.character:
        c = next(x for x in p.characters if x.id == a.character)
        if not confirm(f"{c.id} 의 이름을 '{c.name or '(없음)'}' 에서 '{chosen}' 로 바꿀까요?", a.yes):
            return
        c.name = chosen
    else:
        if not confirm(f"장소에 '{chosen}' 을 추가할까요?", a.yes):
            return
        p.world.locations.append(chosen)
    store.save(a.name, p)
    print("반영했습니다.")


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

    no_browser = a.no_browser or bool(os.environ.pop("CANON_NO_BROWSER", ""))
    if not a.no_update:
        r = updater.update()
        print(f"[업데이트] {r.message}")
        if r.updated:  # 이미 읽은 모듈은 옛 코드라 새로 시작한다
            updater.restart(no_browser=no_browser)
    interval = 0 if a.no_update else a.update_interval * 60
    serve(a.host, a.port, open_browser=not no_browser, update_interval=interval)


def cmd_upgrade(a: argparse.Namespace) -> None:
    r = updater.update()
    print(r.message)
    if r.updated:
        print("실행 중인 serve 는 다시 켜야 반영됩니다 (자동 업데이트를 켜 두었다면 알아서 다시 시작합니다)")


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
    sp = add("names", cmd_names)
    sp.add_argument("--character", default="", help="인물 id. 비우면 지명 후보")
    sp.add_argument("--place", default="", help="지명 종류 (예: 마을, 산, 고개, 문파, 왕국)")
    sp.add_argument("--n", type=int, default=8)
    sp.add_argument("--style", default="", help="이름 스타일 (비우면 세계관 설정 또는 자동 감지)")
    sp.add_argument("--ai", action="store_true", help="'이름·지명' 단계 모델이 후보에서 골라 이유를 붙임")
    sp.add_argument("--pick", type=int, help="고른 번호를 반영 (인물 이름 바꾸기 / 장소 추가)")
    sp.add_argument("--check", action="store_true", help="출연진 이름 점검만")
    sp = add("style", cmd_style)
    sp.add_argument("file", nargs="?")
    sp.add_argument("--library", help="문체 라이브러리 항목 id 를 적용 (파일 대신)")
    sp.add_argument("--save", metavar="이름", help="분석한 문체를 라이브러리에도 저장")
    add("arc", cmd_arc)
    sp = add("plot", cmd_plot, yes=False)
    sp.add_argument("--from", dest="start", type=int)
    sp.add_argument("--to", dest="end", type=int)
    add("revise", cmd_revise, "message")
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
    sp = sub.add_parser("styles", help="문체 라이브러리")
    sp.add_argument("action", nargs="?", choices=["list", "add", "show", "rm"], default="list")
    sp.add_argument("args", nargs="*")
    sp.add_argument("--source", default="", help="add: 원문 출처 메모")
    sp.add_argument("-y", "--yes", action="store_true", help="확인 없이 반영")
    sp.set_defaults(fn=cmd_styles)

    sp = sub.add_parser("serve", help="웹 UI 실행")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음 (서버에서 상시 실행할 때)")
    sp.add_argument("--no-update", action="store_true", help="main 의 새 코드를 자동으로 받지 않음")
    sp.add_argument("--update-interval", type=float, default=10, help="실행 중 새 코드 확인 간격(분), 기본 10")
    sp.set_defaults(fn=cmd_serve)
    sub.add_parser("upgrade", help="main 의 새 코드 받기 (git pull)").set_defaults(fn=cmd_upgrade)

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
