"""명령줄 인터페이스.

  python -m canon new 내소설           설정 도우미 (질문에 답하면 AI 가 빈칸 제안)
  python -m canon style 내소설 sample.txt   예시 텍스트로 스타일 프로필 생성 (--save 이름: 라이브러리에도 저장)
  python -m canon style 내소설 --library ID   문체 라이브러리 항목을 작품에 적용
  python -m canon styles [add 이름 파일 | show ID | rm ID]   문체 라이브러리 (작품과 따로 저장)
  python -m canon arc 내소설            기승전결 구간 설계 (단편)
  python -m canon series 내소설         장편: 총 화수를 부로 나누는 부 구성 제안
  python -m canon convert 내소설 --episodes 200 [--ending keep|reopen]   단편을 장편으로 전환 (--undo 로 되돌리기)
  python -m canon nextarc 내소설 [--len 15 --note "..." --redo]   장편: 다음 아크 하나 기획 (--redo 는 마지막 아크를 지우고 다시)
  python -m canon arcs 내소설           장편: 부와 아크 진행 보기
  python -m canon recap 내소설 [arc|part 번호]   장편: 끝난 아크·부 요약 (승인 후 저장)
  python -m canon plot 내소설 [--from 1 --to 16]   화별 플롯 초안 (장편은 기본으로 플롯이 빈 아크)
  python -m canon revise 내소설 "3화 전개가 너무 빨라"   말로 구조와 플롯 고치기 (변경안 확인 후 반영, 대화는 웹과 같이 저장)
  python -m canon causal 내소설 [list | add | show ID | impact ID | rm ID]   인과율: 요소·설정·사건을 더하고 영향 분석
  python -m canon lines 내소설 [map | suggest | add | tag ID 4,5 | rm ID]   이야기 줄기: 서브플롯 · 과거 회상 · 외전 노선도와 제안
  python -m canon confirm 내소설 all|3  플롯 확정
  python -m canon write 내소설 3        본문 생성
  python -m canon fix 내소설 3 "고칠 문장" [--ask "더 짧게" --preset less_ai]   본문 일부를 AI 후보로 고치기 (고른 후보만 반영)
  python -m canon edits 내소설 [3] [--undo e2 | --jsonl]   본문 부분 수정 기록 보기, 되돌리기, 고치기 전후 쌍 내보내기
  python -m canon check 내소설 3        본문 검수 (앞선 본문·설정과의 모순, 근거 인용)
  python -m canon stats 내소설 [3]      문체 지표를 레퍼런스와 비교
  python -m canon update 내소설 3       상태 변경안 확인 후 반영
  python -m canon run 내소설            확정된 화를 순서대로 write → check → update
  python -m canon auto 내소설 --to 12 [--batch]   목표 화까지 자동 집필 (정책에 걸리면 멈춤, --resume 으로 이어 가기)
  python -m canon compare 내소설 3 [--a gemini --b local]   같은 화를 두 백엔드로 써서 이름을 가리고 비교
  python -m canon compare 내소설 3 --pick 2   고른 쪽을 본문으로 쓰고 어느 백엔드였는지 공개
  python -m canon openings 내소설 1 [--plot | --use 2] [--ways in_medias_res,lack_turn]   1~3화를 여는 방식마다 써서 가려 고르기 (--plot 은 플롯 안)
  python -m canon hook 내소설 1 [--draft 2]   1~3화 흡입력 판정 (근거 인용, 초반 지표와 함께)
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

from . import (autorun, dynamics, elements, genres, library, logline, metrics, naming, pipeline, prompts, research, store, storylines,
               updater)
from .llm import dump, get_llm
from .schema import ConsistencyReport, LoglineParts, Meta, Project, Selection, StateDelta, StoryElement, Storyline, StorylineProposal


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
        target_episodes=int(a.episodes or ask("총 화수 (단편 10~20, 장편 연재 100~300)", "300" if a.serial else "16")),
        words_per_episode=int(ask("화당 분량(자)", "5000") if a.interactive else 5000),
        form="serial" if a.serial else "short",
        arc_length=a.arc_length or 0,
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
    if p.serial:
        sys.exit("장편 연재는 작품 전체 기승전결 대신 부 구성(series)과 아크(nextarc)로 나눕니다")
    plan = pipeline.plan_arc(get_llm("plan"), p)
    for act in plan.acts:
        print(f"[{act.name}] {act.start_ep}~{act.end_ep}화  목표: {act.goal}  / 전환점: {act.key_turn}")
    if confirm("이 구조로 확정할까요?", a.yes):
        p.arc = plan.acts
        print(f"저장: {store.save(a.name, p)}")


def cmd_plot(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if p.serial and not (a.start or a.end):
        have = {e.plot.number for e in p.episodes}
        todo = next((s for s in sorted(p.story_arcs, key=lambda s: s.start_ep)
                     if any(n not in have for n in range(s.start_ep, s.end_ep + 1))), None)
        if todo is None:
            sys.exit(f"플롯이 빈 아크가 없습니다. 다음 아크를 먼저 기획하세요: nextarc {a.name}")
        start, end = todo.start_ep, todo.end_ep
        print(f"아크 {todo.number} {todo.title} ({start}~{end}화) 플롯을 만듭니다")
    else:
        start, end = a.start or 1, a.end or (p.planned_until() if p.serial else p.meta.target_episodes)
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


def _print_arc(x) -> None:
    print(f"\n아크 {x.number} {x.title} ({x.start_ep}~{x.end_ep}화, {x.end_ep - x.start_ep + 1}화)")
    print(f"  목표: {x.goal}\n  갈등: {x.conflict}\n  보상: {x.payoff}")
    for act in x.acts:
        print(f"  [{act.name}] {act.start_ep}~{act.end_ep}화  {act.goal}  / 전환점: {act.key_turn}")
    if x.cast:
        print(f"  주요 인물: {', '.join(x.cast)}")
    if x.payoffs:
        print(f"  회수할 복선: {', '.join(x.payoffs)}")


def _need_serial(p: Project) -> None:
    if not p.serial:
        sys.exit("장편 연재 작품이 아닙니다. project.json 의 meta.form 을 \"serial\" 로 바꾸거나 new --serial 로 만드세요")


def cmd_series(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _need_serial(p)
    plan = pipeline.plan_series(get_llm("plan"), p)
    for x in plan.parts:
        print(f"\n{x.number}부 {x.title} ({x.start_ep}~{x.end_ep}화)\n  목표: {x.goal}\n  전환점: {x.key_turn}")
        for idea in x.arc_ideas:
            print(f"  - {idea}")
    if confirm("이 부 구성으로 저장할까요?", a.yes):
        pipeline.apply_series(p, plan)
        print(f"저장: {store.save(a.name, p)}")


def cmd_nextarc(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _need_serial(p)
    if a.redo:
        gone = pipeline.remove_last_arc(p)
        print(f"아크 {gone.number}({gone.start_ep}~{gone.end_ep}화)를 지우고 다시 기획합니다")
    prop = pipeline.plan_next_arc(get_llm("plan"), p, a.len or 0, a.note or "")
    if prop.reply:
        print(prop.reply)
    _print_arc(prop.arc)
    for c in prop.new_characters:
        print(f"  새 인물: {c.name}({c.id}) {c.role} - {c.speech_style}")
    if confirm("이 아크를 반영할까요? (반영 후 plot 으로 화별 플롯)", a.yes):
        arc = pipeline.apply_arc(p, prop)
        print(f"저장: {store.save(a.name, p)}\n다음: plot {a.name}  ({arc.start_ep}~{arc.end_ep}화)")


def cmd_arcs(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _need_serial(p)
    status = {e.plot.number: e.status for e in p.episodes}
    print(f"《{p.meta.title}》 총 {p.meta.target_episodes}화 · 기획 {p.planned_until()}화까지 · "
          f"반영 {sum(s == 'finalized' for s in status.values())}화")
    parts = p.parts or []
    for x in parts or [None]:
        if x:
            print(f"\n{x.number}부 {x.title} ({x.start_ep}~{x.end_ep}화){'  요약 있음' if x.summary else ''}\n  목표: {x.goal}")
        for s in p.story_arcs:
            if x and not x.start_ep <= s.start_ep <= x.end_ep:
                continue
            nums = range(s.start_ep, s.end_ep + 1)
            done = sum(status.get(n) == "finalized" for n in nums)
            plotted = sum(n in status for n in nums)
            print(f"  아크 {s.number:>2} {s.start_ep:>3}~{s.end_ep:<3}화 {s.title}  플롯 {plotted}/{len(nums)} 반영 {done}/{len(nums)}"
                  f"{'  요약 있음' if s.summary else ''}")
    for kind, num in pipeline.pending_recaps(p):
        print(f"! {'아크' if kind == 'arc' else '부'} {num} 이 끝났습니다. 요약하세요: recap {a.name} {kind} {num}")
    if p.planned_until() < p.meta.target_episodes:
        print(f"\n다음: nextarc {a.name}  ({p.planned_until() + 1}화부터)")


def cmd_recap(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _need_serial(p)
    todo = [(a.kind, a.number)] if a.kind else pipeline.pending_recaps(p)
    if not todo:
        print("요약할 아크나 부가 없습니다 (모든 화가 반영된 아크·부만 요약합니다)")
        return
    for kind, num in todo:
        r = pipeline.recap(get_llm("state"), p, kind, num)
        print(f"\n[{'아크' if kind == 'arc' else '부'} {num} 요약]\n{r.summary}")
        if confirm("이 요약을 저장할까요? (앞으로 이 구간 대신 프롬프트에 들어갑니다)", a.yes):
            pipeline.apply_recap(p, kind, num, r.summary)
            store.save(a.name, p)
    print("저장 완료")


def cmd_convert(a: argparse.Namespace) -> None:
    """단편을 장편 연재로 바꾼다. 단편 전체가 아크 1이 되고, 전환 직전 작품은 before-serial.json 에 남는다."""
    p = store.load(a.name)
    if a.undo:
        backup = store.load_backup(a.name, pipeline.BACKUP_TAG)
        why = pipeline.undo_blockers(p, backup)
        if why:
            sys.exit("되돌릴 수 없습니다: " + " / ".join(why))
        if confirm(f"전환 전 단편({p.conversion.from_total}화)으로 되돌릴까요? 전환한 뒤 고친 설정과 플롯도 함께 돌아갑니다", a.yes):
            store.save(a.name, pipeline.undo_conversion(p, backup))
            store.drop_backup(a.name, pipeline.BACKUP_TAG)
            print("단편으로 되돌렸습니다")
        return
    lo, hi = pipeline.convert_range(p)
    total = a.episodes or int(ask(f"장편 총 화수 ({lo}~{hi})", str(max(lo, 200))))
    prop = pipeline.propose_conversion(get_llm("plan"), p, total, a.ending or "", a.note or "")
    print(prop.reply)
    print(f"\n결말 처리: {'닫고 다음 이야기로' if prop.ending == 'keep' else '결말 다시 열기'} · 총 {prop.total_episodes}화")
    if p.arc:
        _print_arc(prop.arc)
        if prop.arc.summary:
            print(f"  요약: {prop.arc.summary}")
    for x in prop.parts:
        print(f"\n{x.number}부 {x.title} ({x.start_ep}~{x.end_ep}화)\n  목표: {x.goal}")
        for idea in x.arc_ideas:
            print(f"  - {idea}")
    for f in prop.foreshadows:
        print(f"  새 떡밥 {f.id} ({f.scope}, {f.planted_ep}화): {f.description}")
    for s in prop.scopes:
        print(f"  복선 범위 {s.id} → {s.scope}  {s.reason}")
    for fact in prop.facts:
        print(f"  더할 사실: {fact}")
    for t in prop.tiers:
        print(f"  비중 {t.id} → {t.tier}  {t.reason}")
    for e in prop.episodes:
        print(f"  {e.number}화 플롯 수정: {e.title} / {e.summary} / 훅: {e.ending_hook}")
    if confirm("이대로 장편으로 전환할까요? (전환 전 작품은 따로 남겨 convert --undo 로 되돌릴 수 있습니다)", a.yes):
        before = pipeline.apply_conversion(p, prop)
        store.save_backup(a.name, pipeline.BACKUP_TAG, before)
        print(f"저장: {store.save(a.name, p)}")
        print(f"다음: nextarc {a.name}  ({p.planned_until() + 1}화부터)" if p.story_arcs else f"다음: nextarc {a.name}")


def cmd_lines(a: argparse.Namespace) -> None:
    """이야기 줄기: 메인에서 갈라졌다 합류하는 서브플롯, 과거 회상, 외전, 인물 이야기."""
    p = store.load(a.name)
    act, args = a.action, a.args
    if act == "map":
        if not p.storylines:
            print(f"이야기 줄기가 없습니다. python -m canon lines {a.name} suggest --note \"도현의 과거\" 로 제안을 받거나 add 로 더하세요")
            return
        print(storylines.ascii_map(p))
        print("\n● 그 줄기를 따라가는 화  · 메인 화에 끼어드는 장면  ╰ 갈라지는 화  ╯ 합류하는 화\n")
        for x in p.storylines:
            print(storylines.describe(p, x) + ("" if storylines.is_open(p, x) else "\n  (합류함)"))
        return
    if act in ("suggest", "add"):
        if act == "suggest":
            prop = pipeline.suggest_storyline(get_llm("plan"), p, a.note or "", a.kind or "")
            if prop.reply:
                print(prop.reply)
        else:
            kind = a.kind or "서브플롯"
            if kind not in storylines.KINDS:
                raise ValueError(f"종류는 {', '.join(storylines.KINDS)} 중 하나입니다")
            prop = StorylineProposal(storyline=Storyline(
                id=storylines.new_id(p), kind=kind, title=a.title or ask("이름"), focus=[c for c in (a.focus or "").split(",") if c],
                when=a.when or "", goal=a.goal or "", branch_ep=a.branch, join_ep=a.join, rejoin=a.rejoin or ""))
            prop.episodes = _numbers(a.eps)
            prop.threads = _numbers(a.scenes)
        print(storylines.describe(p, prop.storyline))
        print(f"  붙일 화: {', '.join(map(str, prop.episodes)) or '없음'} / 장면을 끼울 화: {', '.join(map(str, prop.threads)) or '없음'}")
        if confirm("이 줄기를 더할까요? (화 플롯 내용은 바뀌지 않습니다)", a.yes):
            x = pipeline.apply_storyline(p, prop)
            print(f"저장: {store.save(a.name, p)}  ({x.id})")
        return
    if not args:
        raise ValueError(f"줄기 id 를 적으세요 (python -m canon lines {a.name})")
    sid = "" if args[0] == "main" else storylines.get(p, args[0]).id
    if act == "rm":
        pipeline.remove_storyline(p, sid)
        print(f"지웠습니다: {sid} (붙은 화는 메인으로 돌아갑니다)")
    else:  # tag: 화를 줄기에 붙인다. 줄기 id 대신 main 이면 메인으로 되돌린다
        eps = _numbers(",".join(args[1:]))
        if not eps:
            raise ValueError("붙일 화를 적으세요 (예: lines 이름 tag sl-01 4,5)")
        for n in eps:
            if sid:
                storylines.tag(p, n, sid, "thread" if a.scene else "main")
            else:
                p.episode(n).plot.storyline = ""
        print(f"{', '.join(map(str, eps))}화 → {sid or '메인'}{' (장면)' if a.scene else ''}")
    store.save(a.name, p)


def _numbers(text: str | None) -> list[int]:
    return [int(x) for x in re.split(r"[,\s]+", text or "") if x.strip().isdigit()]


def cmd_causal(a: argparse.Namespace) -> None:
    """인과율: 요소, 특징, 설정, 사건을 더하고, 이미 쓴 화와 정해 둔 플롯에 주는 영향을 본다."""
    p = store.load(a.name)
    act, args = a.action, a.args
    if act == "list":
        for el in p.elements:
            imp = (el.impact.outcome or "결정 전") + (" (요소를 고친 뒤라 지난 분석)" if elements.stale(el) else "") if el.impact else "분석 전"
            print(f"{el.id}  [{el.kind}] {el.name}  ({elements.timing(el)})  영향 분석: {imp}")
        if not p.elements:
            print("요소가 없습니다. python -m canon causal 이름 add --kind 과거사건 --title 이름 --desc 설명")
        return
    if act == "add":
        kind = (a.kind or "기타").replace(" ", "")
        kind = next((k for k in elements.KINDS if k.replace(" ", "") == kind), None)
        if kind is None:
            raise ValueError(f"종류는 {', '.join(elements.KINDS)} 중 하나입니다")
        el = StoryElement(id=elements.new_id(p), kind=kind, name=a.title or ask("이름"), description=a.desc or ask("설명"),
                          characters=[c for c in (a.chars or "").split(",") if c], since_ep=a.since,
                          episodes=[int(x) for x in (a.eps or "").split(",") if x.strip()], reveal_ep=a.reveal)
        p.elements.append(el)
        elements.stamp(p)
        store.save(a.name, p)
        print(f"더했습니다: {el.id} {el.name} ({elements.timing(el)})")
        if el.added_after:
            print(f"{el.added_after}화까지 쓴 뒤에 더했습니다. 영향을 보려면: python -m canon causal {a.name} impact {el.id}")
        return
    if not args:
        raise ValueError("요소 id 를 적으세요 (python -m canon causal 이름 list)")
    el = elements.get(p, args[0])
    if act == "rm":
        p.elements = [x for x in p.elements if x.id != el.id]
        store.save(a.name, p)
        print(f"지웠습니다: {el.id}")
        return
    if act == "show":
        print(elements.describe(p, el))
        print("\n관련 화 (AI 없이 찾음)")
        for lk in elements.links(p, el):
            why = ", ".join(filter(None, ["언급: " + "/".join(lk.terms) if lk.terms else "", "인물" if lk.characters else "", "나올 화" if lk.planned else ""]))
            print(f"  {lk.episode}화 ({lk.status}) {why}  {lk.snippet}")
        return
    rep = pipeline.analyze_impact(get_llm("plan"), p, el.id)
    pipeline.record_impact(p, el.id, rep)
    print(rep.summary)
    for c in rep.conflicts:
        print(f"\n[{c.target}{f' {c.episode}화' if c.episode else ''}] {c.problem}  → {c.fix}\n  \"{c.quote}\"")
    for e in rep.episodes:
        print(f"\n{e.number}화 플롯 변경: {e.title}\n  {e.summary}\n  사건: {' / '.join(e.events)}")
    for t in rep.patches:
        print(f"\n{t.episode}화 본문 수정\n  - {t.quote}\n  + {t.replacement}")
    for f in rep.new_facts:
        print(f"\n확정 사실 더하기: {f}")
    if (rep.episodes or rep.patches or rep.new_facts) and confirm("모두 반영할까요? (확정된 화는 초안으로, 본문은 위처럼 바뀝니다)", a.yes):
        done = pipeline.apply_impact(p, el.id, [e.number for e in rep.episodes], list(range(len(rep.patches))), list(range(len(rep.new_facts))))
        print(f"반영: {', '.join(done)}")
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
    _print_opening(p, n)


def _print_opening(p: Project, n: int, text: str | None = None, indent: str = "") -> None:
    if prompts.is_opening(n):
        for w in pipeline.opening_metrics(p, n, text)[1]:
            print(f"{indent}! 초반: {w}")


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
        if label.endswith("화"):
            _print_opening(p, int(label[:-1]), indent="      ")
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
    if p.serial and p.planned_until() < p.meta.target_episodes:
        for kind, num in pipeline.pending_recaps(p):
            print(f"{'아크' if kind == 'arc' else '부'} {num} 이 끝났습니다. 요약: recap {a.name} {kind} {num}")
        print(f"기획한 {p.planned_until()}화까지 완료. 다음 아크: nextarc {a.name}")
        return
    print("모든 화 완료")


def _duration(s: float) -> str:
    return f"{s / 3600:.1f}시간" if s >= 3600 else f"{max(1, round(s / 60))}분"


def cmd_auto(a: argparse.Namespace) -> None:
    """목표 화까지 자동 집필. Ctrl-C 를 누르면 지금 단계가 끝난 뒤 멈춘다 (배치는 계속 돌고 --resume 으로 받아 온다)."""
    import signal
    import threading

    p = store.load(a.name)
    if a.stop:
        autorun.request(a.name, "stop")
        print("자동 집필을 중지했습니다. 기다리던 배치 작업이 있으면 취소했습니다.")
        return
    if a.status:
        run = autorun.get_run(a.name)
        if run is None:
            print("자동 집필 기록이 없습니다.")
            return
        print(f"상태: {run.status}  ({run.target}화까지, 배치 {'켬' if run.batch else '끔'}, 지금 {run.ep or '-'}화 {run.step})")
        for r in run.reasons:
            print(f"  ! {r}")
        print(f"토큰 입력 {run.tokens_in:,} / 출력 {run.tokens_out:,}, 비용 약 ${run.cost:.2f}")
        for e in run.log[-15:]:
            print(f"  {e.at[11:19]} [{e.ep or '-'}화] {e.message}")
        return
    policy = autorun.Policy(check=not a.no_check, max_issues=a.max_issues, max_shift=a.max_shift,
                            stop_on_stage=a.stop_on_stage, stop_on_warnings=a.stop_on_warnings,
                            confirm_plots=a.confirm_plots, review_every=a.review_every,
                            hand_pick_opening=not a.auto_opening)
    if not a.resume:
        target = a.to or p.meta.target_episodes
        est = autorun.estimate(p, target, a.batch, policy, a.name)
        cost = f"약 ${est['cost']:.2f}" if est["cost"] is not None else "모델 가격을 몰라 계산하지 못함"
        when = (f"{_duration(est['seconds_min'])}~{_duration(est['seconds_max'])} (배치 {est['batch_rounds']}번 대기, 최악은 배치마다 24시간)"
                if est["batch_rounds"] else f"약 {_duration(est['seconds_min'])}")
        print(f"{est['from'] or '-'}~{target}화 {est['episodes']}화 남음. 토큰 입력 {est['tokens_in']:,} / 출력 {est['tokens_out']:,} (추정)")
        print(f"비용 {cost}, 시간 {when}")
        if est["missing"]:
            print(f"플롯이 없는 화: {est['missing']} (그 화에서 멈춥니다)")
        if not confirm("시작할까요?", a.yes):
            return

    def on_int(*_: object) -> None:
        print("\n지금 단계가 끝나면 멈춥니다 (배치는 기다리기를 바로 멈추고 작업은 남겨 둡니다)...")
        autorun.request(a.name, "pause")

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, on_int)
    if a.resume:
        run = autorun.resume(a.name, approve=a.approve, rewrite=a.rewrite, foreground=True, echo=print)
    else:
        run = autorun.start(a.name, a.to or p.meta.target_episodes, a.batch, policy, foreground=True, echo=print)
    if run.status == "review":
        print(f"\n{run.ep}화 검토가 필요합니다. 고르세요:")
        print(f"  update {a.name} {run.ep}            변경안을 보고 반영한 뒤 auto {a.name} --resume")
        print(f"  auto {a.name} --resume --approve    변경안을 그대로 반영하고 이어 가기")
        print(f"  auto {a.name} --resume --rewrite    {run.ep}화를 다시 쓰기")
    elif run.status in ("paused", "error"):
        print(f"\n이어 가려면: auto {a.name} --resume")


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


def cmd_openings(a: argparse.Namespace) -> None:
    """1~3화를 여는 방식마다 하나씩. --plot 은 플롯 안(저장해 두고 --use 로 반영), 아니면 본문 안(compare --pick 으로 고름)."""
    import json

    p = store.load(a.name)
    ways = [w.strip() for w in (a.ways or "").split(",") if w.strip()] or None
    saved = research.compare_dir(a.name, a.n) / "plots.json"
    if a.use:
        from .schema import OpeningPlots

        if not saved.exists():
            sys.exit(f"{a.n}화 플롯 안이 없습니다. 먼저 openings {a.name} {a.n} --plot")
        opts = OpeningPlots.model_validate_json(saved.read_text(encoding="utf-8")).options
        if not 1 <= a.use <= len(opts):
            sys.exit(f"1~{len(opts)} 중에서 고르세요")
        pipeline.apply_opening(p, a.n, opts[a.use - 1].plot)
        store.save(a.name, p)
        print(f"{a.n}화 플롯을 {a.use}번 안({prompts.OPENING_APPROACHES.get(opts[a.use - 1].approach, ('?',))[0]})으로 바꿨습니다. 확인 후 confirm {a.name} {a.n}")
        return
    if a.plot:
        print(f"{a.n}화 플롯을 여는 방식별로 만드는 중...")
        out = pipeline.suggest_openings(get_llm("plan"), p, a.n, ways)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(out.model_dump_json(), encoding="utf-8")
        for i, o in enumerate(out.options, 1):
            e = o.plot
            print(f"\n[{i}] {prompts.OPENING_APPROACHES[o.approach][0]} · {e.title}\n  {o.pitch}\n  여는 장면: {e.opening}"
                  f"\n  사건: {' / '.join(e.events)}\n  훅: {e.ending_hook}\n  독자 질문: {e.reader_question}")
        print(f"\n쓸 안을 고르세요: openings {a.name} {a.n} --use 번호")
        return
    print(f"{a.n}화를 여는 방식마다 쓰는 중...")
    c = research.run_opening_compare(a.name, p, a.n, get_llm("write"), ways)
    research.record(a.name, "compare", {"episode": a.n, "kind": "opening", "backends": sorted(json.loads(
        (research.compare_dir(a.name, a.n) / "key.json").read_text(encoding="utf-8"))["order"])})  # 고르기 전이라 순서는 남기지 않는다
    for d in c["drafts"]:
        print(f"\n[{d['n']}] {d['chars']:,}자 · 대사 {d['dialogue_ratio']}")
        for w in d["opening"] + d["warnings"]:
            print(f"    ! {w}")
    nums = "|".join(str(d["n"]) for d in c["drafts"])
    print(f"\n저장: {research.compare_dir(a.name, a.n)}/*.md (key.json 은 열지 마세요)"
          f"\n판정을 보려면: hook {a.name} {a.n} --draft 번호\n고르세요: compare {a.name} {a.n} --pick {nums}")


def cmd_hook(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    text = research.compare_text(a.name, a.n, a.draft) if a.draft else None
    print(f"{a.n}화{f' 비교본 {a.draft}번' if a.draft else ''} 흡입력 판정 중...")
    rep = pipeline.check_hook(get_llm("check"), p, a.n, text)
    if a.draft:
        research.save_compare_hook(a.name, a.n, a.draft, rep)
    else:
        pipeline.apply_hook(p, rep)
        store.save(a.name, p)
    print(f"\n다음 화를 누를까: {'예' if rep.next_click else '아니오'} · {rep.reason}")
    if rep.reader_question:
        print(f"독자가 들고 갈 질문: {rep.reader_question}")
    print(f"전제가 나오는 곳: {f'{rep.premise_at:,}자' if rep.premise_at >= 0 else '찾지 못함'}")
    for it in rep.items:
        print(f"  {it.aspect:<6} {'●' * it.score}{'○' * (5 - it.score)}  {it.note}")
        if it.quote:
            print(f"         \"{it.quote}\"")
    _print_opening(p, a.n, text)


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


def cmd_fix(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    text = p.episode(a.n).text
    if a.quote not in text:
        sys.exit(f"{a.n}화 본문에 그 문장이 없습니다: {a.quote}")
    sel = Selection(start=text.index(a.quote), text=a.quote)
    rev = pipeline.revise_passage(get_llm("revise"), p, a.n, sel, a.ask or "", a.preset or "")
    msg = pipeline.record_passage(p, a.n, sel, a.ask or "", a.preset or "", rev)
    print(rev.reply)
    for k, c in enumerate(rev.candidates, 1):
        print(f"\n[{k}] {c.note}\n{c.text}")
    i = len(p.chat(f"text:{a.n}").messages) - 1
    if msg.passage:
        pick = "1" if a.yes else ask(f"넣을 후보 번호 (1~{len(rev.candidates)}, 비우면 넣지 않음)")
        if pick.isdigit() and 1 <= int(pick) <= len(rev.candidates):
            edit = pipeline.apply_passage(p, a.n, i, int(pick) - 1)
            print(f"{a.n}화에 {pick}번 후보를 넣었습니다 (되돌리기: edits {a.name} {a.n} --undo {edit.id})")
        else:
            msg.outcome = "dismissed"
    print(f"저장: {store.save(a.name, p)}")


def cmd_edits(a: argparse.Namespace) -> None:
    import json

    p = store.load(a.name)
    eps = [p.episode(a.n)] if a.n else p.episodes
    if a.undo:
        if not a.n:
            sys.exit("--undo 는 화 번호와 함께 씁니다")
        edit = pipeline.undo_edit(p, a.n, a.undo)
        print(f"{a.n}화 {edit.id} 수정을 되돌렸습니다. 저장: {store.save(a.name, p)}")
        return
    for e in eps:
        for x in e.edits:
            if a.jsonl:  # 선호 · 미세 조정 자료: 고치기 전후와 고르지 않은 후보, 그 자리 앞뒤 문맥
                text = e.text
                at = text.find(x.after) if x.after and not x.undone else -1
                ctx = (text[max(0, at - 300):at], text[at + len(x.after):at + len(x.after) + 300]) if at >= 0 else ("", "")
                print(json.dumps({"episode": e.plot.number, **x.model_dump(), "context_before": ctx[0], "context_after": ctx[1]},
                                 ensure_ascii=False))
                continue
            mark = " (되돌림)" if x.undone else ""
            how = {"manual": "직접", "ai": "AI", "typed": "본문 저장"}[x.source]
            print(f"{e.plot.number}화 {x.id} [{how}]{mark} {x.instruction}\n  - {x.before[:80]}\n  + {x.after[:80]}")


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
    if p.serial:
        print(f"장편 연재: 부 {len(p.parts)}개, 아크 {len(p.story_arcs)}개, {p.planned_until()}화까지 기획 (자세히: arcs {a.name})")
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
    sp.add_argument("--serial", action="store_true", help="장편 연재: 부 → 아크 → 화로 나눠 아크씩 기획")
    sp.add_argument("--arc-length", type=int, default=0, help="장편: 아크 하나의 기본 화수 (기본은 AI 가 정함)")
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
    add("series", cmd_series)
    sp = add("convert", cmd_convert)
    sp.add_argument("--episodes", type=int, help="장편 총 화수")
    sp.add_argument("--ending", choices=["keep", "reopen"], help="keep 닫고 다음 이야기로 / reopen 결말 다시 열기 (비우면 AI 가 고름)")
    sp.add_argument("--note", help="장편에 바라는 것")
    sp.add_argument("--undo", action="store_true", help="전환 전 단편으로 되돌리기")
    sp = add("nextarc", cmd_nextarc)
    sp.add_argument("--len", type=int, help="아크 화수")
    sp.add_argument("--note", help="이번 아크에 바라는 것")
    sp.add_argument("--redo", action="store_true", help="마지막 아크(아직 확정 전)를 지우고 다시 기획")
    add("arcs", cmd_arcs, yes=False)
    sp = add("recap", cmd_recap)
    sp.add_argument("kind", nargs="?", choices=["arc", "part"])
    sp.add_argument("number", nargs="?", type=int)
    sp = add("plot", cmd_plot, yes=False)
    sp.add_argument("--from", dest="start", type=int)
    sp.add_argument("--to", dest="end", type=int)
    add("revise", cmd_revise, "message")
    sp = add("lines", cmd_lines)
    sp.add_argument("action", nargs="?", choices=["map", "suggest", "add", "tag", "rm"], default="map")
    sp.add_argument("args", nargs="*")
    sp.add_argument("--note", help="suggest: 바라는 것 (예: 도현의 과거를 7화쯤에)")
    sp.add_argument("--kind", help="suggest, add: " + ", ".join(storylines.KINDS))
    sp.add_argument("--title", help="add: 줄기 이름")
    sp.add_argument("--focus", help="add: 중심 인물 id, 쉼표로")
    sp.add_argument("--when", help="add: 이야기 속 시점 (예: 10년 전). 메인과 같으면 비움")
    sp.add_argument("--goal", help="add: 풀어 갈 것")
    sp.add_argument("--from", dest="branch", type=int, default=0, help="add: 갈라지는 화")
    sp.add_argument("--to", dest="join", type=int, default=0, help="add: 합류하는 화")
    sp.add_argument("--rejoin", help="add: 합류할 때 메인에 남기는 것")
    sp.add_argument("--eps", help="add: 이 줄기를 따라갈 화, 쉼표로")
    sp.add_argument("--scenes", help="add: 장면을 끼울 화, 쉼표로")
    sp.add_argument("--scene", action="store_true", help="tag: 그 화를 따라가지 않고 장면만 끼운다")
    sp = add("causal", cmd_causal)
    sp.add_argument("action", nargs="?", choices=["list", "add", "show", "impact", "rm"], default="list")
    sp.add_argument("args", nargs="*")
    sp.add_argument("--kind", help="add: " + ", ".join(elements.KINDS))
    sp.add_argument("--title", help="add: 이름")
    sp.add_argument("--desc", help="add: 설명")
    sp.add_argument("--chars", help="add: 관련 인물 id, 쉼표로")
    sp.add_argument("--since", type=int, default=0, help="add: n화부터 생김 (0 이면 처음부터 사실)")
    sp.add_argument("--eps", help="add: 나올 화, 쉼표로")
    sp.add_argument("--reveal", type=int, default=0, help="add: 독자에게 드러나는 화")
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
    sp = add("auto", cmd_auto)
    sp.add_argument("--to", type=int, help="목표 화 (기본: 총 화수)")
    sp.add_argument("--batch", action="store_true", help="Gemini Batch API 로 (비용 절반, 단계마다 몇 분~최대 24시간)")
    sp.add_argument("--no-check", action="store_true", help="검수를 건너뜀")
    sp.add_argument("--max-issues", type=int, default=0, help="검수 어긋남이 이보다 많으면 멈춤 (기본 0)")
    sp.add_argument("--max-shift", type=float, default=0.3, help="관계 온기·신뢰가 한 화에 이보다 많이 바뀌면 멈춤 (0: 안 봄)")
    sp.add_argument("--stop-on-stage", action="store_true", help="관계 단계가 바뀌면 멈춤")
    sp.add_argument("--stop-on-warnings", action="store_true", help="상태 변경안 경고가 있으면 멈춤")
    sp.add_argument("--auto-opening", action="store_true", help="1~3화도 멈추지 않고 정책대로 반영 (기본은 1~3화에서 멈춤)")
    sp.add_argument("--confirm-plots", action="store_true", help="초안 플롯을 자동 확정하고 진행")
    sp.add_argument("--review-every", type=int, default=0, help="N화마다 멈춤")
    sp.add_argument("--resume", action="store_true", help="멈춘 실행 이어 가기")
    sp.add_argument("--approve", action="store_true", help="--resume: 검토 대기 변경안을 그대로 반영")
    sp.add_argument("--rewrite", action="store_true", help="--resume: 검토 대기 화를 다시 쓰기")
    sp.add_argument("--status", action="store_true", help="진행 상태와 최근 로그")
    sp.add_argument("--stop", action="store_true", help="중지 (기다리던 배치 취소)")
    sp = add("compare", cmd_compare, "n", yes=False)
    sp.add_argument("--a", default="gemini", choices=["gemini", "local", "mock"])
    sp.add_argument("--b", default="local", choices=["gemini", "local", "mock"])
    sp.add_argument("--pick", type=int, help="고른 번호. 본문으로 저장하고 백엔드(여는 방식)를 공개")
    sp = add("openings", cmd_openings, "n", yes=False)
    sp.add_argument("--plot", action="store_true", help="본문 대신 플롯 안을 만든다")
    sp.add_argument("--use", type=int, help="저장해 둔 플롯 안 가운데 이 번호를 그 화 플롯으로")
    sp.add_argument("--ways", help="여는 방식 id 2~4개, 쉼표로: " + ", ".join(prompts.OPENING_APPROACHES))
    sp = add("hook", cmd_hook, "n", yes=False)
    sp.add_argument("--draft", type=int, default=0, help="그 화 본문 대신 비교본 번호를 판정")
    sp = add("brief", cmd_brief, "n", yes=False)
    sp.add_argument("--state", action="store_true", help="상태 정리용 작업지시서")
    sp.add_argument("--check", action="store_true", help="검수용 작업지시서")
    add("import", cmd_import, "n", "file", yes=False)
    sp = add("fix", cmd_fix, "n", "quote")
    sp.add_argument("--ask", help="AI 에게 바라는 것 (예: 대사로 풀어 줘)")
    sp.add_argument("--preset", choices=list(prompts.PASSAGE_PRESETS), help="빠른 요청")
    sp = add("edits", cmd_edits, yes=False)
    sp.add_argument("n", type=int, nargs="?")
    sp.add_argument("--undo", metavar="ID", help="이 수정을 되돌림 (예: e2)")
    sp.add_argument("--jsonl", action="store_true", help="고치기 전후 쌍을 JSON Lines 로 출력")
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
