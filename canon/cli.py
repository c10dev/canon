"""명령줄 인터페이스.

  python -m canon new 내소설           설정 도우미 (질문에 답하면 AI 가 빈칸 제안)
  python -m canon style 내소설 sample.txt   예시 텍스트로 스타일 프로필 생성 (--save 이름: 라이브러리에도 저장)
  python -m canon style 내소설 --library ID   문체 라이브러리 항목을 작품에 적용
  python -m canon styles [add 이름 파일 | show ID | rm ID | versions ID | restore ID 번호]   문체 라이브러리 (작품과 따로 저장, 버전 기록)
  python -m canon learn 내소설 [--pick 1,3 | -y] [--push]   본문 수정 기록에서 문체 규칙 후보 찾기 (고른 것만 반영)
  python -m canon stylechat 내소설 "대사를 더 짧게" [--ep 3] [--pick 1,2 | -y] [--push]   대화로 문체 다듬기 (--example 이면 지금 문체로 예시 글)
  python -m canon arc 내소설            기승전결 구간 설계 (단편)
  python -m canon series 내소설         장편: 총 화수를 부로 나누는 부 구성 제안
  python -m canon convert 내소설 --episodes 200 [--ending keep|reopen]   단편을 장편으로 전환 (--undo 로 되돌리기)
  python -m canon convert 내소설 --episodes 200 --rebuild [--span 36] [--ending-at arc|part|series]   단편을 씨앗으로 앞부분 재구성
  python -m canon rework 내소설 3                     재구성에서 다듬기로 고른 화 고치기
  python -m canon nextarc 내소설 [--len 15 --note "..." --redo]   장편: 다음 아크 하나 기획 (--redo 는 마지막 아크를 지우고 다시)
  python -m canon arcs 내소설           장편: 부와 아크 진행 보기
  python -m canon recap 내소설 [arc|part 번호]   장편: 끝난 아크·부 요약 (승인 후 저장)
  python -m canon plot 내소설 [--from 1 --to 16]   화별 플롯 초안 (장편은 기본으로 플롯이 빈 아크)
  python -m canon pov 내소설 [6-12 ally --mode 1인칭 | --clear]   화별 서술 시점 보기 · 정하기 (남주 → 여주 시점 전환 등)
  python -m canon revise 내소설 "3화 전개가 너무 빨라"   말로 구조와 플롯 고치기 (변경안 확인 후 반영, 대화는 웹과 같이 저장)
  python -m canon causal 내소설 [list | add | show ID | impact ID | rm ID]   인과율: 요소·설정·사건을 더하고 영향 분석
  python -m canon lines 내소설 [map | suggest | add | tag ID 4,5 | rm ID]   이야기 줄기: 서브플롯 · 과거 회상 · 외전 노선도와 제안
  python -m canon insert 내소설 30 [--title "외전" --summary "..." --line sl-02 --ai | --remove]   안 쓴 화 앞에 새 화 넣기 · 빼기 (뒤 화 번호를 함께 옮김)
  python -m canon confirm 내소설 all|3  플롯 확정
  python -m canon write 내소설 3        본문 생성
  python -m canon fix 내소설 3 "고칠 문장" [--ask "더 짧게" --preset less_ai]   본문 일부를 AI 후보로 고치기 (고른 후보만 반영)
  python -m canon edits 내소설 [3] [--undo e2 | --jsonl]   본문 부분 수정 기록 보기, 되돌리기, 고치기 전후 쌍 내보내기
  python -m canon check 내소설 3        본문 검수 (앞선 본문·설정과의 모순, 근거 인용)
  python -m canon stats 내소설 [3]      문체 지표를 레퍼런스와 비교
  python -m canon foreshadows 내소설     복선 센터: 심은 문장 · 회수한 문장, 회수율, 끊어진 연결
  python -m canon statwin 내소설 hero   상태창 수치와 화별 변화 (--set 레벨=1 로 만들고 고치기)
  python -m canon time 내소설           작품 속 시간: 화별로 끝난 시점과 기한 (--start, --add '축제@7', --close ID)
  python -m canon map 내소설            지도: 장소, 인물별로 옮겨 다닌 길, 장소와 맞지 않은 위치 글
  python -m canon map 내소설 gen --size 보통 --water 강   마을 생성기로 마을 만들기 (--seed, --roads, --fields, --forest, --move, --ai)
  python -m canon update 내소설 3       상태 변경안 확인 후 반영
  python -m canon run 내소설            확정된 화를 순서대로 write → check → update
  python -m canon auto 내소설 --to 12 [--batch]   목표 화까지 자동 집필 (정책에 걸리면 멈춤, --resume 으로 이어 가기)
  python -m canon compare 내소설 3 [--a gemini --b local]   같은 화를 두 백엔드로 써서 이름을 가리고 비교
  python -m canon compare 내소설 3 --pick 2   고른 쪽을 본문으로 쓰고 어느 백엔드였는지 공개
  python -m canon openings 내소설 1 [--plot | --use 2] [--ways in_medias_res,lack_turn]   1~3화를 여는 방식마다 써서 가려 고르기 (--plot 은 플롯 안)
  python -m canon hook 내소설 1 [--draft 2]   1~3화 흡입력 판정 (근거 인용, 초반 지표와 함께)
  python -m canon brief 내소설 3        구독형 채팅 앱용 작업지시서 출력 (--state, --check)
  python -m canon import 내소설 3 본문.txt   다른 곳에서 쓴 본문 가져오기
  python -m canon export 내소설 [--from 1 --to 3 --format blank|compact|indent|raw -o 파일.txt]   다른 곳에 붙여 넣을 본문
  python -m canon illust 내소설 3 ["그릴 문장"] [--ask "뒷모습으로" --model v5-full | --list]   NovelAI 삽화 프롬프트 (문장이 없으면 AI 가 장면을 고름)
  python -m canon look 내소설 hero [-y]   인물 설정을 삽화 외형 태그로 옮겨 저장 (화마다 같은 모습)
  python -m canon voice 내소설 heroine [--ask "..." | --set "..."]   이 인물 시점 화의 서술 말투 (AI 초안 또는 직접)
  python -m canon show 내소설 [섹션]       섹션 rel 은 관계 역학을 보여 준다
  python -m canon view 내소설 numbers|words   관계를 숫자로 볼지 말로 볼지
  python -m canon adjust 내소설 a b --warmth 0.3 --trust 0.6   a 가 b 를 보는 관계를 직접 보정
  python -m canon revert 내소설 3       3화 상태 반영 직후로 되돌리기
  python -m canon recalc 내소설         계수(params)를 바꾼 뒤 사건 로그로 관계 재계산
  python -m canon usage [--days 30 | --all] [--project 내소설] [--prices]   AI 사용량과 추정 비용 (가격표 보기)
  python -m canon serve [--port 8000]    웹 UI (브라우저 자동 열기, 끄려면 --no-browser)
  python -m canon upgrade               main 의 새 코드 받기 (serve 는 시작할 때와 10분마다 알아서 받는다)
설정은 projects/<이름>/project.json 을 직접 고쳐도 된다.
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys
from pathlib import Path

from . import (autorun, cast, dynamics, elements, genres, illust, library, logline, metrics, naming, pipeline, prompts, publish, research, store,
               storylines, updater, usage)
from .llm import dump, get_llm
from .schema import ConsistencyReport, LoglineParts, Meta, Project, RewriteRequest, Selection, StateDelta, StoryElement, Storyline, StorylineProposal
from . import atlas, citygen, foreshadows, statwin, timeline, towngen
from .schema import ArcProposal, ChatScope, Deadline, MapPlace, StatValue, StoryArc


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
    print("\n로그라인을 다섯 칸으로 나눠 써요. 모르는 칸은 비워 두세요.")
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
        sys.exit(f"이미 있는 프로젝트예요: {a.name}")
    print("기본 설정을 입력하세요. 모르는 칸은 비워 두면 AI 가 제안해요.\n")
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
        if confirm(f"라이브러리 문체 '{e.name}' 을 적용할까요? 지금 작품의 문체는 바뀌어요.", a.yes):
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
    if a.action == "versions":
        if len(a.args) != 1:
            sys.exit("사용법: python -m canon styles versions ID")
        e = library.load(a.args[0])
        for v in library.versions(e):
            print(f"{v['number']:>3}번  {v['at'][:16]}  {v['note']}{'  (지금)' if v['current'] else ''}")
            for c in v["changes"]:
                if "added" in c:
                    print(f"       {c['label']}: " + ", ".join([f"+{x[:40]}" for x in c["added"]] + [f"-{x[:40]}" for x in c["removed"]]))
                else:
                    print(f"       {c['label']}: {c['before'][:40] or '(비어 있음)'} → {c['after'][:40] or '(비어 있음)'}")
        return
    if a.action == "restore":
        if len(a.args) != 2 or not a.args[1].isdigit():
            sys.exit("사용법: python -m canon styles restore ID 번호")
        e = library.load(a.args[0])
        if confirm(f"'{e.name}' 을 {a.args[1]}번 버전으로 되돌릴까요? 지금 상태도 버전으로 남아요.", a.yes):
            e = library.restore(e.id, int(a.args[1]))
            print(f"되돌렸어요. 지금 {e.version}번 버전 (쓰는 작품은 style --library 로 다시 적용해야 바뀌어요)")
        return
    if a.action in ("show", "rm"):
        if len(a.args) != 1:
            sys.exit(f"사용법: python -m canon styles {a.action} ID")
        e = library.load(a.args[0])
        if a.action == "show":
            print(f"{e.name} ({e.id})  {e.version}번 버전  출처: {e.source or '-'}  원문 {len(e.sample):,}자")
            print(dump(e.profile))
            return
        used = library.used_by(e.id)
        note = f" 쓰는 작품({', '.join(used)})은 복사해 둔 문체를 그대로 써요." if used else ""
        if confirm(f"'{e.name}' 을 라이브러리에서 지울까요?{note}", a.yes):
            library.delete(e.id)
            print("지웠어요")
        return
    rows = library.entries()
    if not rows:
        print("문체 라이브러리가 비어 있어요. styles add 이름 원문.txt 로 추가하세요.")
    for e in rows:
        used = library.used_by(e.id)
        print(f"{e.id}  {e.name}  {e.profile.narration_pov or '-'} / {e.profile.tense or '-'}"
              f"  원문 {len(e.sample):,}자  작품 {len(used)}개{'  (' + ', '.join(used) + ')' if used else ''}")
    print(f"\n저장 위치: {library.root()}")


RULE_KIND_TEXT = {"do": "지킬 것", "dont": "피할 것", "banned": "금지 표현", "marker": "문체 표지", "device": "가끔 쓰는 장치"}


def cmd_learn(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    st = pipeline.edit_stats(p)
    print(f"수정 기록 {st['total']}건 중 배울 수 있는 것 {st['usable']}건")
    r = pipeline.learn_style(get_llm("plan"), p)
    print(f"\n{r.summary}\n")
    if not r.suggestions:
        print("두 번 이상 되풀이된 고침을 찾지 못했어요")
        return
    for i, s in enumerate(r.suggestions, 1):
        extra = f"  (상황: {s.note}, 글자: {', '.join(s.cues)}, {s.every}화에 한 번)" if s.kind == "device" else ""
        print(f"{i}. [{RULE_KIND_TEXT[s.kind]}] {s.text}{extra}")
        if s.replaces:
            print(f"   바꿀 규칙: {s.replaces}")
        print(f"   {s.reason}  근거: {', '.join(s.evidence)}")
        for x in s.pairs[:2]:
            print(f"     {x.ref}  {x.before[:50]}  →  {x.after[:50]}")
    if a.pick:
        picks = [int(x) - 1 for x in a.pick.split(",") if x.strip()]
    elif a.yes:
        picks = list(range(len(r.suggestions)))
    else:
        raw = ask("\n넣을 번호 (쉼표로, 비우면 넣지 않음)")
        picks = [int(x) - 1 for x in raw.split(",") if x.strip().isdigit()]
    p.style_learning = r
    if picks:
        done, notes = pipeline.apply_learning(p, picks)
        print(f"규칙 {len(done)}개를 작품 문체에 넣었어요")
        for n in notes:
            print(f"알림: {n}")
        if a.push and p.style_id and library.exists(p.style_id):
            e = library.push_project(p, f"수정 기록에서 배운 규칙 {len(done)}개 반영")
            print(f"라이브러리 '{e.name}' 을 {e.version}번 버전으로 올렸어요")
    print(f"저장: {store.save(a.name, p)}")


def _style_value_text(v) -> str:
    if isinstance(v, list):
        return " / ".join(library._item(x) for x in v) or "(비움)"
    return v or "(비움)"


def cmd_stylechat(a: argparse.Namespace) -> None:
    """대화로 문체 다듬기. --example 이면 지금 문체로 예시 글을 쓴다."""
    p = store.load(a.name)
    if a.example:
        ex = pipeline.style_example(get_llm("write"), p, a.message or "", a.ep or 0)
        if ex.source:
            print(f"[{ex.episode}화 원래 대목]\n{ex.source}\n")
        print(ex.text)
        p.style_example = ex
        print(f"\n저장: {store.save(a.name, p)}")
        return
    if not a.message:
        sys.exit("바라는 것을 적어 주세요 (예: stylechat 작품 \"대사를 더 짧게\")")
    rev = pipeline.revise_style(get_llm("plan"), p, a.message, a.ep or 0)
    msg = pipeline.record_style_chat(p, a.message, a.ep or 0, rev)
    print(rev.reply)
    for k, e in enumerate(rev.edits, 1):
        label = prompts.STYLE_KEY_LABELS.get(e.key, e.key)
        print(f"\n{k}. [{label}]{f' {e.why}' if e.why else ''}\n   지금: {_style_value_text(getattr(p.style, e.key))}"
              f"\n   바꾸면: {_style_value_text(pipeline.style_value(e))}")
    if rev.preview:
        print(f"\n[시험 문단]\n{rev.preview}")
    i = len(p.chat("style").messages) - 1
    if msg.style:
        if a.pick:
            keys = [rev.edits[int(x) - 1].key for x in a.pick.split(",") if x.strip().isdigit() and 0 < int(x) <= len(rev.edits)]
        elif confirm("이 변경안을 모두 적용할까요?", a.yes):
            keys = [e.key for e in rev.edits]
        else:
            keys = []
        if keys:
            pipeline.apply_style_chat(p, i, keys)
            print(f"적용했어요: {', '.join(prompts.STYLE_KEY_LABELS[k] for k in keys)}")
            if a.push and p.style_id and library.exists(p.style_id):
                e = library.push_project(p, f"대화로 다듬음: {a.message[:60]}")
                print(f"라이브러리 '{e.name}' 을 {e.version}번 버전으로 올렸어요")
    print(f"저장: {store.save(a.name, p)}")


def cmd_arc(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if p.serial:
        sys.exit("장편 연재는 작품 전체 기승전결 대신 부 구성(series)과 아크(nextarc)로 나눠요")
    plan = pipeline.plan_arc(get_llm("plan"), p, a.note or "")
    for act in plan.acts:
        print(f"[{act.name}] {act.start_ep}~{act.end_ep}화  목표: {act.goal}  / 전환점: {act.key_turn}{_act_pov(act)}")
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
            sys.exit(f"플롯이 빈 아크가 없어요. 다음 아크를 먼저 기획하세요: nextarc {a.name}")
        start, end = todo.start_ep, todo.end_ep
        print(f"아크 {todo.number} {todo.title} ({start}~{end}화) 플롯을 만들어요")
    else:
        start, end = a.start or 1, a.end or (p.planned_until() if p.serial else p.meta.target_episodes)
    batch = pipeline.draft_plots(get_llm("plan"), p, start, end, a.note or "")
    for e in batch.episodes:
        print(f"\n{e.number}화 [{e.act}] {e.title}\n  {e.summary}\n  사건: {' / '.join(e.events)}\n  훅: {e.ending_hook}{_plot_pov(e)}")
    pipeline.apply_plots(p, batch)
    _print_candidates(p)
    print(f"\n초안 저장: {store.save(a.name, p)}  (수정 후 confirm 으로 확정)")


def _print_candidates(p) -> None:
    for c in p.cast_candidates:
        eps = [e.plot.number for e in p.episodes if c.id in e.plot.characters]
        print(f"\n새 인물 후보: {c.name}({c.id}) · {c.role} · {'단역' if c.tier == 'minor' else '조연'} · {', '.join(map(str, eps))}화"
              f"\n  {c.personality or c.goal}  / 말투: {c.speech_style}\n  그 화를 확정하면 인물로 등록돼요. 빼려면 플롯의 등장 인물에서 지우세요")
    for x in p.place_candidates:
        eps = [e.plot.number for e in p.episodes if elements.mentioned(x, elements.plot_text(e))]
        print(f"\n새 장소 후보: {x.name}{f' ({x.kind})' if x.kind else ''} · {', '.join(map(str, eps))}화\n  {x.description}"
              "\n  그 화를 확정하면 인과율에 장소로 등록돼요. 빼려면 플롯에서 이름을 지우세요")


def _act_pov(act) -> str:
    return f"  / 시점: {act.pov}" if act.pov else ""


def _plot_pov(e) -> str:
    return f"\n  시점: {' '.join(x for x in [e.pov, e.pov_mode] if x)}" if e.pov or e.pov_mode else ""


def cmd_pov(a: argparse.Namespace) -> None:
    """화별 서술 시점 보기 · 정하기. 범위만 주면 보기, 인물이나 --mode 를 주면 그 화들에 적는다."""
    p = store.load(a.name)
    nums = sorted(e.plot.number for e in p.episodes)
    if a.range:
        lo, _, hi = a.range.partition("-")
        lo_n = int(lo)
        nums = [n for n in nums if lo_n <= n <= int(hi or lo)]
    if a.character or a.mode is not None or a.clear:
        if a.character and not any(a.character in (c.id, c.name) for c in p.characters):
            sys.exit(f"인물을 찾지 못했어요: {a.character} (인물 id 나 이름)")
        cid = next((c.id for c in p.characters if a.character in (c.id, c.name)), "") if a.character else ""
        done, skipped = [], []
        for n in nums:
            e = p.episode(n)
            if e.status in ("written", "finalized"):
                skipped.append(n)
                continue
            e.plot.pov, e.plot.pov_mode = ("", "") if a.clear else (cid or e.plot.pov, e.plot.pov_mode if a.mode is None else a.mode)
            done.append(n)
        if skipped:
            print(f"본문이 있는 화는 플롯을 바꾸지 않아요: {skipped}화")
        print(f"시점 {'지움' if a.clear else '적음'}: {done}화")
        store.save(a.name, p)
    print(f"작품 기본 시점: {p.style.narration_pov or '정하지 않음'}")
    prev = prompts.pov_of(p, nums[0] - 1)[0] if nums and nums[0] > 1 else None
    for n in nums:
        key, text = prompts.pov_of(p, n)
        print(f"  {n:>3}화  {text or '작품 기본'}{'  ← 시점 바뀜' if prev is not None and key != prev else ''}")
        prev = key


def cmd_revise(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    target = "next" if a.next else f"arc:{a.arc}" if a.arc else ""
    target, focus = pipeline.chat_target(p, target)
    scope = ChatScope(target=target, mode="options" if a.options else "")
    rev = pipeline.revise_plot(get_llm("plan"), p, a.message, scope)
    msg = pipeline.record_chat(p, "plot", a.message, rev, scope)
    print(rev.reply)
    for i, o in enumerate(rev.options, 1):
        print(f"\n{i}안 {o.title}\n  {o.idea}" + "".join(f"\n  - {x}" for x in o.changes) + (f"\n  얻고 잃는 것: {o.tradeoff}" if o.tradeoff else ""))
    if rev.options:
        print(f"\n고른 방향으로 다시 청하세요: revise {a.name} \"2안 방향으로 변경안을 만들어 줘\"" + (f" --arc {focus.number}" if focus else " --next" if target == "next" else ""))
    for x in rev.parts:
        print(f"\n[부 구성] {x.number}부 {x.title} ({x.start_ep}~{x.end_ep}화)  목표: {x.goal}  / 전환점: {x.key_turn}")
    if rev.arc.title:
        print(f"\n[{'다음 아크' if target == 'next' else f'아크 {focus.number} 칸'}] {rev.arc.title}{f' (끝 화 {rev.arc.end_ep}화)' if rev.arc.end_ep else ''}"
              f"\n  목표: {rev.arc.goal}\n  갈등: {rev.arc.conflict}\n  보상: {rev.arc.payoff}"
              + (f"\n  주요 인물: {', '.join(rev.arc.cast)}" if rev.arc.cast else "") + (f"\n  회수할 복선: {', '.join(rev.arc.payoffs)}" if rev.arc.payoffs else ""))
    if rev.total_episodes:
        print(f"\n총 화수: {p.meta.target_episodes}화 → {rev.total_episodes}화")
    for act in rev.acts:
        print(f"[{act.name}] {act.start_ep}~{act.end_ep}화  목표: {act.goal}  / 전환점: {act.key_turn}{_act_pov(act)}")
    for e in rev.episodes:
        cur = next((x for x in p.episodes if x.plot.number == e.number), None)
        mark = f" ({cur.status})" if cur else " (새 화)"
        print(f"\n{e.number}화{mark} {e.title}\n  {e.summary}\n  사건: {' / '.join(e.events)}\n  훅: {e.ending_hook}{_plot_pov(e)}")
    for c in rev.new_characters:
        print(f"\n새 인물: {c.name}({c.id}) · {c.role} · {'단역' if c.tier == 'minor' else '조연'}  / 말투: {c.speech_style}")
    for x in rev.new_places:
        print(f"\n새 장소: {x.name}{f' ({x.kind})' if x.kind else ''}  {x.description}")
    if msg.revision and rev.has_changes() and confirm("이 변경안을 모두 반영할까요? (확정된 화는 초안으로 돌아가요)", a.yes):
        msg.applied = pipeline.apply_revision(p, rev, True, [e.number for e in rev.episodes], arc=True, parts=True, target=target)
        if target == "next" and rev.arc.title:  # 화면은 초안에 두지만 명령줄은 바로 다음 아크로 붙인다
            fields = rev.arc.model_dump(exclude={"end_ep"})
            start = pipeline.next_arc_start(p)
            arc = StoryArc(number=len(p.story_arcs) + 1, start_ep=start, end_ep=rev.arc.end_ep, acts=rev.acts, **fields)
            pipeline.apply_arc(p, ArcProposal(arc=arc, new_characters=rev.new_characters))
            msg.applied = ["arc"] + msg.applied
            _print_arc(arc)
        msg.outcome = "applied"
        _print_candidates(p)
    elif msg.revision and rev.has_changes():
        msg.outcome = "dismissed"
    print(f"저장: {store.save(a.name, p)}")


def _print_arc(x) -> None:
    print(f"\n아크 {x.number} {x.title} ({x.start_ep}~{x.end_ep}화, {x.end_ep - x.start_ep + 1}화)")
    print(f"  목표: {x.goal}\n  갈등: {x.conflict}\n  보상: {x.payoff}")
    if x.pov:
        print(f"  서술 시점: {x.pov}")
    for act in x.acts:
        print(f"  [{act.name}] {act.start_ep}~{act.end_ep}화  {act.goal}  / 전환점: {act.key_turn}{_act_pov(act)}")
    if x.cast:
        print(f"  주요 인물: {', '.join(x.cast)}")
    if x.payoffs:
        print(f"  회수할 복선: {', '.join(x.payoffs)}")


def _need_serial(p: Project) -> None:
    if not p.serial:
        sys.exit("장편 연재 작품이 아니에요. project.json 의 meta.form 을 \"serial\" 로 바꾸거나 new --serial 로 만드세요")


def cmd_series(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _need_serial(p)
    plan = pipeline.plan_series(get_llm("plan"), p, a.note or "")
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
        print(f"아크 {gone.number}({gone.start_ep}~{gone.end_ep}화)를 지우고 다시 기획해요")
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
        print(f"! {'아크' if kind == 'arc' else '부'} {num} 이 끝났어요. 요약하세요: recap {a.name} {kind} {num}")
    if p.planned_until() < p.meta.target_episodes:
        print(f"\n다음: nextarc {a.name}  ({p.planned_until() + 1}화부터)")


def cmd_recap(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _need_serial(p)
    todo = [(a.kind, a.number)] if a.kind else pipeline.pending_recaps(p)
    if not todo:
        print("요약할 아크나 부가 없어요 (모든 화가 반영된 아크·부만 요약해요)")
        return
    for kind, num in todo:
        r = pipeline.recap(get_llm("state"), p, kind, num)
        print(f"\n[{'아크' if kind == 'arc' else '부'} {num} 요약]\n{r.summary}")
        if confirm("이 요약을 저장할까요? (앞으로 이 구간 대신 프롬프트에 들어가요)", a.yes):
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
            sys.exit("되돌릴 수 없어요: " + " / ".join(why))
        if confirm(f"전환 전 단편({p.conversion.from_total}화)으로 되돌릴까요? 전환한 뒤 고친 설정과 플롯도 함께 돌아가요", a.yes):
            store.save(a.name, pipeline.undo_conversion(p, backup))
            store.drop_backup(a.name, pipeline.BACKUP_TAG)
            print("단편으로 되돌렸어요")
        return
    lo, hi = pipeline.convert_range(p)
    total = a.episodes or int(ask(f"장편 총 화수 ({lo}~{hi})", str(max(lo, 200))))
    if a.rebuild:
        _rebuild(a, p, total)
        return
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
    if confirm("이대로 장편으로 전환할까요? (전환 전 작품은 따로 남겨 convert --undo 로 되돌릴 수 있어요)", a.yes):
        before = pipeline.apply_conversion(p, prop)
        store.save_backup(a.name, pipeline.BACKUP_TAG, before)
        print(f"저장: {store.save(a.name, p)}")
        print(f"다음: nextarc {a.name}  ({p.planned_until() + 1}화부터)" if p.story_arcs else f"다음: nextarc {a.name}")


REBUILD_USE = {"keep": "그대로", "revise": "다듬기", "rewrite": "새로 쓰기", "new": "새 화"}


def _rebuild(a: argparse.Namespace, p, total: int) -> None:
    """재구성: 단편을 씨앗으로 장편 앞부분을 다시 짠다. 화 번호가 바뀌고 상태는 1화 시작 전으로 돌아간다."""
    prop = pipeline.propose_rebuild(get_llm("plan"), p, total, a.span or 0, a.ending_at or "", a.note or "")
    print(prop.reply)
    where = {"arc": "첫 아크 끝", "part": "1부 끝", "series": "작품 끝"}[prop.ending_at]
    print(f"\n총 {prop.total_episodes}화 · 앞 {prop.arcs[-1].end_ep}화를 다시 짬 · 단편 결말 → {where}")
    for arc in prop.arcs:
        _print_arc(arc)
    for x in prop.parts:
        print(f"\n{x.number}부 {x.title} ({x.start_ep}~{x.end_ep}화)\n  목표: {x.goal}")
    print("\n화 지도:")
    for x in prop.episodes:
        src = f" ← 단편 {', '.join(map(str, x.sources))}화" if x.sources else ""
        print(f"  {x.number:3d}화 [{REBUILD_USE[x.use]}]{src} {x.title}: {x.summary}" + (f"\n        메모: {x.note}" if x.note else ""))
    if prop.dropped:
        print(f"  쓰지 않는 단편 화: {prop.dropped}")
    for f in prop.foreshadows:
        print(f"  새 떡밥 {f.id} ({f.scope}, {f.planted_ep}화): {f.description}")
    for t in prop.tiers:
        print(f"  비중 {t.id} → {t.tier}  {t.reason}")
    if confirm("이대로 재구성할까요? 상태와 관계는 1화 시작 전으로 돌아가요 (convert --undo 로 되돌릴 수 있어요)", a.yes):
        before, notes = pipeline.apply_rebuild(p, prop)
        store.save_backup(a.name, pipeline.BACKUP_TAG, before)
        print(f"저장: {store.save(a.name, p)}")
        for n in notes:
            print(f"  ※ {n}")
        print(f"다음: plot {a.name} 로 새 화 플롯 초안을 만들고, 다듬기 화는 rework {a.name} N 으로 고치세요")


def cmd_rework(a: argparse.Namespace) -> None:
    """재구성에서 다듬기로 고른 화의 옛 본문을 새 자리에 맞게 고친다."""
    p = store.load(a.name)
    rw = pipeline.propose_rework(get_llm("revise"), p, a.ep)
    if rw.reply:
        print(rw.reply)
    print(f"\n----- 고친 {a.ep}화 -----\n{rw.text}\n")
    if confirm("이 본문으로 바꿀까요?", a.yes):
        pipeline.accept_rework(p, a.ep, rw.text)
        print(f"저장: {store.save(a.name, p)}")


def cmd_lines(a: argparse.Namespace) -> None:
    """이야기 줄기: 메인에서 갈라졌다 합류하는 서브플롯, 과거 회상, 외전, 인물 이야기."""
    p = store.load(a.name)
    act, args = a.action, a.args
    if act == "map":
        if not p.storylines:
            print(f"이야기 줄기가 없어요. python -m canon lines {a.name} suggest --note \"도현의 과거\" 로 제안을 받거나 add 로 더하세요")
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
                raise ValueError(f"종류는 {', '.join(storylines.KINDS)} 중 하나예요")
            prop = StorylineProposal(storyline=Storyline(
                id=storylines.new_id(p), kind=kind, title=a.title or ask("이름"), focus=[c for c in (a.focus or "").split(",") if c],
                when=a.when or "", goal=a.goal or "", branch_ep=a.branch, join_ep=a.join, rejoin=a.rejoin or ""))
            prop.episodes = _numbers(a.eps)
            prop.threads = _numbers(a.scenes)
        print(storylines.describe(p, prop.storyline))
        print(f"  붙일 화: {', '.join(map(str, prop.episodes)) or '없음'} / 장면을 끼울 화: {', '.join(map(str, prop.threads)) or '없음'}")
        if confirm("이 줄기를 더할까요? (화 플롯 내용은 바뀌지 않아요)", a.yes):
            x = pipeline.apply_storyline(p, prop)
            print(f"저장: {store.save(a.name, p)}  ({x.id})")
        return
    if not args:
        raise ValueError(f"줄기 id 를 적으세요 (python -m canon lines {a.name})")
    sid = "" if args[0] == "main" else storylines.get(p, args[0]).id
    if act == "rm":
        pipeline.remove_storyline(p, sid)
        print(f"지웠어요: {sid} (붙은 화는 메인으로 돌아가요)")
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
            print("요소가 없어요. python -m canon causal 이름 add --kind 과거사건 --title 이름 --desc 설명")
        return
    if act == "add":
        kind = (a.kind or "기타").replace(" ", "")
        kind = next((k for k in elements.KINDS if k.replace(" ", "") == kind), None)
        if kind is None:
            raise ValueError(f"종류는 {', '.join(elements.KINDS)} 중 하나예요")
        el = StoryElement(id=elements.new_id(p), kind=kind, name=a.title or ask("이름"), description=a.desc or ask("설명"),
                          characters=[c for c in (a.chars or "").split(",") if c], since_ep=a.since,
                          episodes=[int(x) for x in (a.eps or "").split(",") if x.strip()], reveal_ep=a.reveal)
        p.elements.append(el)
        elements.stamp(p)
        store.save(a.name, p)
        print(f"더했어요: {el.id} {el.name} ({elements.timing(el)})")
        if el.added_after:
            print(f"{el.added_after}화까지 쓴 뒤에 더했어요. 영향을 보려면: python -m canon causal {a.name} impact {el.id}")
        return
    if not args:
        raise ValueError("요소 id 를 적으세요 (python -m canon causal 이름 list)")
    el = elements.get(p, args[0])
    if act == "rm":
        p.elements = [x for x in p.elements if x.id != el.id]
        store.save(a.name, p)
        print(f"지웠어요: {el.id}")
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
    if (rep.episodes or rep.patches or rep.new_facts) and confirm("모두 반영할까요? (확정된 화는 초안으로, 본문은 위처럼 바뀌어요)", a.yes):
        done = pipeline.apply_impact(p, el.id, [e.number for e in rep.episodes], list(range(len(rep.patches))), list(range(len(rep.new_facts))))
        print(f"반영: {', '.join(done)}")
    print(f"저장: {store.save(a.name, p)}")


def cmd_insert(a: argparse.Namespace) -> None:
    """아직 안 쓴 화 앞에 새 화(외전, 중간 이야기)를 넣거나(--remove 면 빼고) 뒤 화 번호를 함께 옮긴다."""
    p = store.load(a.name)
    lo, hi = pipeline.insert_range(p)
    if a.n is None:
        print(f"새 화는 {lo}~{hi}화 자리에 넣을 수 있어요 ({hi}화는 마지막 화 뒤). 예: insert {a.name} {lo} --title \"외전\" --ai")
        return
    autorun.check_renumber(a.name)
    n = a.n
    trial = p.model_copy(deep=True)
    if a.remove:
        notes = pipeline.remove_episode(trial, n)
        end = (lambda x: x - 1 if x >= n else x)
    else:
        notes = pipeline.insert_episode(trial, n, a.title or "", a.summary or "", a.line or "")
        end = (lambda x: x + 1 if x >= n else x)
    print("\n".join(notes))
    if not confirm("이대로 반영할까요?", a.yes):
        return
    autorun.renumber(a.name, end)
    p = trial
    if a.ai and not a.remove:
        batch = pipeline.draft_episode(get_llm("plan"), p, n)
        e = batch.episodes[0]
        print(f"\n{e.number}화 [{e.act}] {e.title}\n  {e.summary}\n  사건: {' / '.join(e.events)}\n  훅: {e.ending_hook}{_plot_pov(e)}")
        pipeline.apply_plots(p, batch)
        _print_candidates(p)
    print(f"저장: {store.save(a.name, p)}" + ("" if a.remove else f"  ({n}화는 초안이에요. 다듬은 뒤 confirm {a.name} {n})"))


def cmd_confirm(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    targets = [e for e in p.episodes if a.which == "all" or e.plot.number == int(a.which)]
    places = len(p.elements)
    added = [c for e in targets for c in pipeline.confirm_plot(p, e.plot.number)]
    print(f"확정: {[e.plot.number for e in targets]}화")
    if added:
        print(f"새 인물 등록: {', '.join(c.name or c.id for c in p.characters if c.id in added)}")
    if len(p.elements) > places:
        print(f"새 장소 등록 (인과율): {', '.join(el.name for el in p.elements[places:])}")
    store.save(a.name, p)


def cmd_write(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _write(a.name, p, a.n)


def _write(name: str, p: Project, n: int) -> None:
    print(f"{n}화 생성 중...")
    text = pipeline.write_episode(get_llm("write"), p, n)
    pipeline.replace_text(p.episode(n), text)  # 지금 본문이 있으면 '이전 판'에 남는다
    store.save(name, p)
    print(f"{n}화 저장: {store.project_dir(name) / 'episodes' / f'{n:02d}.md'} ({len(text)}자)")
    for w in pipeline.style_drift(p, n)[1]:
        print(f"! 문체: {w}")
    _print_opening(p, n)


def cmd_rewrite(a: argparse.Namespace) -> None:
    """다시 생성: 피드백 · 빠른 요청 · 재료로 새 판을 만들고, 지금 본문과 바꿀지 고른다. 이전 판도 보고 되돌린다."""
    p = store.load(a.name)
    ep = p.episode(a.n)
    if a.versions:
        for v in ep.versions:
            how = "바꾸기 전" if v.kind == "previous" else "고르지 않은 새 판"
            print(f"{v.id} [{how}] {v.at} {len(v.text):,}자 {_rewrite_label(v.request)}\n  {v.text[:80]}")
        if ep.candidate:
            print(f"{ep.candidate.id} [고르기 대기] {len(ep.candidate.text):,}자 {_rewrite_label(ep.candidate.request)}")
        return
    if a.restore:
        pipeline.restore_version(p, a.n, a.restore)
        print(f"{a.n}화를 {a.restore} 판으로 되돌렸어요 (지금 본문은 이전 판에 남김). 저장: {store.save(a.name, p)}")
        return
    if a.adopt or a.drop:
        (pipeline.adopt_candidate if a.adopt else pipeline.drop_candidate)(p, a.n)
        print(f"{a.n}화 새 판을 {'본문으로 썼어요' if a.adopt else '버렸어요'}. 저장: {store.save(a.name, p)}")
        return
    req = RewriteRequest(feedback=a.ask or "", presets=_csv(a.preset), materials=_csv(a.use),  # type: ignore[arg-type]
                         mode="revise" if a.revise else "fresh", keep=a.keep or [])
    req = pipeline.clean_rewrite(req)
    print(f"{a.n}화 다시 생성 중... ({'지난 판 고쳐 쓰기' if req.mode == 'revise' else '처음부터 새로'})")
    text = pipeline.rewrite_episode(get_llm("write"), p, a.n, req)
    pipeline.set_candidate(p, a.n, text, req)
    print(f"\n{text[:600]}{'…' if len(text) > 600 else ''}\n\n지금 판 {len(ep.text):,}자 → 새 판 {len(text):,}자")
    if confirm("새 판으로 바꿀까요? (지금 본문은 이전 판에 남아요)", a.yes):
        pipeline.adopt_candidate(p, a.n)
        for w in pipeline.style_drift(p, a.n)[1]:
            print(f"! 문체: {w}")
        _print_opening(p, a.n)
    else:
        print(f"새 판은 고르기 대기로 남겼어요. 웹 집필 화면에서 비교하거나 rewrite {a.name} {a.n} --adopt / --drop")
    print(f"저장: {store.save(a.name, p)}")


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _rewrite_label(r: RewriteRequest | None) -> str:
    if r is None:
        return ""
    bits = [prompts.REWRITE_PRESETS[x][0] for x in r.presets if x in prompts.REWRITE_PRESETS]
    if r.feedback:
        bits.append(r.feedback[:40])
    return f"({' · '.join(bits)})" if bits else ""


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
    print("\nnew --genre '로맨스 판타지, 회귀' 처럼 쓰고, 목록에 없는 장르도 그대로 적을 수 있어요.")


def cmd_names(a: argparse.Namespace) -> None:
    """세계관에 맞는 이름·지명 후보. --ai 면 '이름·지명' 단계 모델이 골라 이유를 붙인다."""
    p = store.load(a.name)
    if a.style and a.style not in naming.STYLE_IDS:
        raise ValueError(f"이름 스타일은 {' | '.join(sorted(naming.STYLE_IDS))} 중 하나예요")
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
        raise ValueError(f"--pick 은 1~{len(picks)} 사이예요")
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
    print("반영했어요.")


def cmd_stats(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    base = pipeline.style_baseline(p)
    rows = [("기준", base, [])]
    rows += [(f"{e.plot.number}화", *pipeline.style_drift(p, e.plot.number))
             for e in p.episodes if e.text and (a.n is None or e.plot.number == a.n)]
    print(f"{'':>5} {'문장평균':>7} {'변화폭':>6} {'문단평균':>7} {'대사':>5} {'과거형':>6} {'어휘':>6} "
          f"{'쉼표':>5} {'짧은끝':>6} {'대명사':>6} {'거리':>5}  경고")
    for label, m, warns in rows:
        print(f"{label:>5} {m.sentence_len_mean:>7} {m.sentence_len_cv:>6} {m.paragraph_len_mean:>7} "
              f"{m.dialogue_ratio:>5} {_num(m.past_tense_ratio):>6} {_num(m.mattr):>6} "
              f"{_num(m.comma_sentence_ratio):>5} {_num(m.short_ending_ratio):>6} {_num(m.pronoun_per_1k):>6} {_num(m.style_distance):>5}  {len(warns) or ''}")
        for w in warns:
            print(f"      ! {w}")
        if label.endswith("화"):
            _print_opening(p, int(label[:-1]), indent="      ")
    if not p.style_baseline:
        print("\n(기준은 문체 예시 발췌로 잰 값이에요. style 명령을 다시 실행하면 원문 전체로 재요.)")
        return
    if base.comma_sentence_ratio is None:
        print("\n(기준값이 예전 버전이라 쉼표, 짧은끝, 대명사, 거리는 비교하지 않았어요. style 명령을 다시 실행하면 비교해요.)")
    elif not base.style_centroid:
        print("\n(거리: 기준 원문이 6,000자보다 짧거나 예전 기준값이라 재지 않았어요. 원문을 2만 자쯤 넣고 style 을 다시 실행하면 재요.)")
    else:
        print(f"\n(거리: 원문 대목끼리 떨어진 만큼이 1.0 이에요. {metrics.STYLE_DISTANCE_WARN} 를 넘으면 다른 작가 글 수준이라 경고해요. 한 화 값보다 흐름을 보세요.)")


def _print_delta(d: StateDelta) -> None:
    print(f"\n=== {d.episode}화 상태 변경안 ===\n요약: {d.summary}")
    for c in d.character_updates:
        print(f"- 인물 {c.character_id}: 감정={c.emotional_state} 목표={c.current_goal} 위치={c.location}"
              + (f" 차림={c.attire}" if c.attire else "") + f" 새로 앎={c.knows}")
        if c.stats:
            print(f"  · 상태창: {', '.join(f'{x.name} {x.value or "지움"}' for x in c.stats)}")
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
    for c in d.foreshadow_clues:
        print(f"  · 복선 {c.foreshadow} {'회수' if c.kind == 'payoff' else '심음'} 문장: \"{c.quote}\"")
    for x in d.new_places:
        print(f"- 새 장소 {x.name}{f' ({x.kind})' if x.kind else ''}: {x.description}")
    if timeline.known(d.time):
        print(f"- 끝난 시점: {timeline.fmt(d.time)}")
    for x in d.deadlines_added:
        print(f"- 기한 {x.id}: {x.what}{f' ({x.day}일째)' if x.day else ''}{f' · {x.note}' if x.note else ''}")
    for x in d.deadlines_done:
        print(f"- 기한 닫힘: {x}")
    for w in d.warnings:
        print(f"! 경고: {w}")


def _print_relation_preview(p: Project, d: StateDelta) -> None:
    """변경안을 복사본에 반영해 계산된 관계를 미리 보여 준다."""
    sim = p.model_copy(deep=True)
    pipeline.apply_delta(sim, d)
    text = dynamics.describe_relations(sim, numbers=p.settings.show_numbers)
    if text:
        print(f"\n--- 반영하면 이렇게 계산돼요 ---\n{text}")


def cmd_update(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _update(a.name, p, a.n, a.yes, a.from_json)


def _update(name: str, p: Project, n: int, yes: bool, from_json: str | None = None) -> bool:
    if from_json:
        delta = StateDelta.model_validate_json(_strip_fence(Path(from_json).read_text(encoding="utf-8")))
        delta.episode = n
        pipeline.clean_delta(p, delta)
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
            print(f"{n}화 플롯이 확정되지 않아 멈춰요.")
            return
        if ep.status == "confirmed":
            _write(a.name, p, n)
            if not a.no_check:
                _check(a.name, p, n)
        if not _update(a.name, p, n, a.yes):
            print("상태 반영을 보류해 멈춰요.")
            return
    if p.serial and p.planned_until() < p.meta.target_episodes:
        for kind, num in pipeline.pending_recaps(p):
            print(f"{'아크' if kind == 'arc' else '부'} {num} 이 끝났어요. 요약: recap {a.name} {kind} {num}")
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
        print("자동 집필을 중지했어요. 기다리던 배치 작업이 있으면 취소했어요.")
        return
    if a.status:
        run = autorun.get_run(a.name)
        if run is None:
            print("자동 집필 기록이 없어요.")
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
            print(f"플롯이 없는 화: {est['missing']} (그 화에서 멈춰요)")
        if not confirm("시작할까요?", a.yes):
            return

    def on_int(*_: object) -> None:
        print("\n지금 단계가 끝나면 멈춰요 (배치는 기다리기를 바로 멈추고 작업은 남겨 둬요)...")
        autorun.request(a.name, "pause")

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, on_int)
    if a.resume:
        run = autorun.resume(a.name, approve=a.approve, rewrite=a.rewrite, foreground=True, echo=print)
    else:
        run = autorun.start(a.name, a.to or p.meta.target_episodes, a.batch, policy, foreground=True, echo=print)
    if run.status == "review":
        print(f"\n{run.ep}화 검토가 필요해요. 고르세요:")
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
        print(f"{a.pick}번은 {r['picked']} 였어요 (다른 쪽: {', '.join(r['others'])}). {a.n}화 본문으로 저장했어요.")
        print("지금까지 고른 횟수: " + ", ".join(f"{prov} {cnt}" for prov, cnt in sorted(r["wins"].items())))
        return
    if a.a == a.b:
        sys.exit("--a 와 --b 가 같아요")
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
            sys.exit(f"{a.n}화 플롯 안이 없어요. 먼저 openings {a.name} {a.n} --plot")
        opts = OpeningPlots.model_validate_json(saved.read_text(encoding="utf-8")).options
        if not 1 <= a.use <= len(opts):
            sys.exit(f"1~{len(opts)} 중에서 고르세요")
        pipeline.apply_opening(p, a.n, opts[a.use - 1].plot)
        store.save(a.name, p)
        print(f"{a.n}화 플롯을 {a.use}번 안({prompts.OPENING_APPROACHES.get(opts[a.use - 1].approach, ('?',))[0]})으로 바꿨어요. 확인 후 confirm {a.name} {a.n}")
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
    pipeline.replace_text(p.episode(a.n), Path(a.file).read_text(encoding="utf-8").strip())  # 지금 본문은 '이전 판'에 남는다
    store.save(a.name, p)
    print(f"{a.n}화 본문을 가져왔어요. 다음: update {a.name} {a.n}  (또는 brief --state 로 채팅 앱에서 정리 후 update --from-json)")


def cmd_fix(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    text = p.episode(a.n).text
    if a.quote not in text:
        sys.exit(f"{a.n}화 본문에 그 문장이 없어요: {a.quote}")
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
            print(f"{a.n}화에 {pick}번 후보를 넣었어요 (되돌리기: edits {a.name} {a.n} --undo {edit.id})")
        else:
            msg.outcome = "dismissed"
    print(f"저장: {store.save(a.name, p)}")


def cmd_edits(a: argparse.Namespace) -> None:
    import json

    p = store.load(a.name)
    eps = [p.episode(a.n)] if a.n else p.episodes
    if a.undo:
        if not a.n:
            sys.exit("--undo 는 화 번호와 함께 써요")
        edit = pipeline.undo_edit(p, a.n, a.undo)
        print(f"{a.n}화 {edit.id} 수정을 되돌렸어요. 저장: {store.save(a.name, p)}")
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


def cmd_export(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    nums = [e.plot.number for e in p.episodes if e.text and (not a.start or e.plot.number >= a.start)
            and (not a.end or e.plot.number <= a.end)]
    out = publish.export(p, nums, a.format, not a.no_title)
    if a.output:
        Path(a.output).write_text(out["text"], encoding="utf-8")
        print(f"{', '.join(map(str, out['episodes']))}화를 저장했어요: {a.output}")
    else:
        sys.stdout.write(out["text"])


def _print_illust(p: Project, ill) -> None:
    label = illust.model_info(ill.model)[0]
    print(f"[{ill.id}] {label} · rating:{ill.rating} · {ill.draft.scene}")
    print(f"  장면: {ill.draft.quote}")
    print(f"\n기본 프롬프트\n{ill.base}")
    for cp in ill.characters:
        print(f"\n인물 프롬프트 · {cp.name or '이름 없는 인물'}{f' ({cp.position})' if cp.position else ''}\n{cp.prompt}")
        if cp.negative:
            print(f"  인물 부정: {cp.negative}")
    print(f"\n부정 프롬프트 (Undesired Content)\n{ill.negative}")
    if ill.characters:
        print(f"\n한 칸에 붙여 넣기\n{ill.combined}")
    for note in ill.notes:
        print(f"※ {note}")
    names = {c.id: c.name for c in p.characters}
    if ill.missing_look:
        print(f"※ 외형 태그가 저장되지 않아 AI 태그를 썼어요: {', '.join(names.get(i, i) for i in ill.missing_look)}"
              f" (고정하려면: look {{작품}} <인물 id>)")


def cmd_illust(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    ep = p.episode(a.n)
    if a.list:
        for ill in ep.illustrations:
            _print_illust(p, ill)
            print()
        if not ep.illustrations:
            print(f"{a.n}화에 저장한 삽화 프롬프트가 없어요")
        return
    sel = None
    if a.quote:
        if a.quote not in ep.text:
            sys.exit(f"{a.n}화 본문에 그 문장이 없어요: {a.quote}")
        sel = Selection(start=ep.text.index(a.quote), text=a.quote)
    ill = pipeline.illustrate(get_llm("illustration"), p, a.n, sel, a.ask or "", a.model or "")
    pipeline.add_illustration(p, a.n, ill)
    _print_illust(p, ill)
    print(f"\n저장: {store.save(a.name, p)}")


def cmd_voice(a: argparse.Namespace) -> None:
    """시점 서술 말투: 지금 값을 보이고, AI 초안을 받아 저장하거나 --set 으로 직접 적는다."""
    p = store.load(a.name)
    c = next((x for x in p.characters if a.cid in (x.id, x.name)), None)
    if c is None:
        sys.exit(f"인물을 찾지 못했어요: {a.cid} (인물 id 나 이름)")
    if c.narration_voice:
        print(f"지금 {c.name} 시점 서술 말투:\n{c.narration_voice}\n")
    if a.set is not None:
        c.narration_voice = a.set.strip()
        print(f"저장: {store.save(a.name, p)}")
        return
    s = pipeline.suggest_voice(get_llm("plan"), p, c.id, a.ask or "")
    print(f"제안:\n{s.voice}")
    if s.note:
        print(f"\n{s.note}")
    if confirm(f"{c.name} 시점 화의 서술 말투로 저장할까요?", a.yes):
        c.narration_voice = s.voice
        print(f"저장: {store.save(a.name, p)}")


def cmd_look(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    s = pipeline.suggest_look(get_llm("illustration"), p, a.cid)
    v = p.visual(a.cid)
    if v and (v.look or v.outfit):
        print(f"지금: {', '.join(v.look)}{' / 옷: ' + ', '.join(v.outfit) if v.outfit else ''}")
    print(f"제안 ({s.subject}): {', '.join(s.look)}\n옷: {', '.join(s.outfit)}")
    if s.note:
        print(s.note)
    if confirm("이 태그를 외형 태그로 저장할까요?", a.yes):
        pipeline.save_look(p, a.cid, s.look, s.outfit, s.subject)
        print(f"저장: {store.save(a.name, p)}")


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
        print("실행 중인 serve 는 다시 켜야 반영돼요 (자동 업데이트를 켜 두었다면 알아서 다시 시작해요)")


def cmd_cast(a: argparse.Namespace) -> None:
    """인물 보기. 인물을 주면 설정, 지금 상태와 관계, 화별 타임라인. 없으면 인물 목록과 등장 화수."""
    p = store.load(a.name)
    numbers = a.numbers or p.settings.show_numbers
    if a.character:
        try:
            print(cast.describe(p, a.character, numbers))
        except KeyError as e:
            sys.exit(str(e.args[0]))
        return
    apps = cast.appearances(p)
    tiers = {"main": "주역", "support": "조연", "minor": "단역"}
    for c in sorted(p.characters, key=lambda c: (list(tiers).index(c.tier), c.first_ep)):
        rows = apps.get(c.id, [])
        pov = sum(1 for r in rows if r["pov"])
        span = f"{rows[0]['n']}~{rows[-1]['n']}화" if rows else "등장 화 없음"
        print(f"  {c.name} ({c.id}) · {tiers[c.tier]} · {c.role} · 등장 {len(rows)}화 {span}{f' · 시점 {pov}화' if pov else ''}")
    print("\n인물 하나를 자세히 보려면: cast <작품> <인물 id 나 이름>")


def _map_option(key: str, value: str | None, kind: str = "village") -> str | None:
    """--size 보통 처럼 화면 이름이나 id(medium)를 받아 id 로. kind: 지도 종류 (도시는 길 모양 칸이 없다)."""
    if not value:
        return None
    opts = atlas.MAKERS[kind][1].OPTIONS.get(key)
    if opts is None:
        raise ValueError(f"--{key} 는 {atlas.MAKERS[kind][0]}에 쓰지 않아요")
    for oid, label in opts.items():
        if value in (oid, label.split(" (")[0]):
            return oid
    raise ValueError(f"--{key} 는 {', '.join(label.split(' (')[0] for label in opts.values())} 중 하나예요")


def cmd_map(a: argparse.Namespace) -> None:
    """지도 보기: 장소와 지도에 놓았는지, 인물별로 옮겨 다닌 길, 장소와 맞지 않은 위치 글.
    gen: 마을 · 도시 생성기로 지도를 만든다 (미리보기를 보여 주고 확인을 받아 적용)."""
    p = store.load(a.name)
    folder = store.project_dir(a.name) / "map"
    if a.action != "gen":
        print(atlas.describe(p, atlas.load_layout(folder, p)))
        return
    base = atlas.default_spec(p)
    sug = pipeline.suggest_map(get_llm("plan"), p, base) if a.ai else None
    kind = a.kind or (sug["kind"] if sug else base.kind)
    opts = atlas.MAKERS[kind][1].OPTIONS
    change = {k: v for k, v in ((k, _map_option(k, getattr(a, k), kind)) for k in towngen.OPTIONS) if v}
    if sug:  # AI 제안을 채우고, 직접 적은 칸(--size 등)이 이긴다
        print(f"AI 제안: {sug['reason']}" if sug["reason"] else "AI 제안을 받았어요")
        for g in sug["places"]:
            if g["note"]:
                print(f"  {g['name']}: {g['note']}")
        mine = {x.key: x for x in base.places}
        places = [*(MapPlace(key=g["key"], kind=g["kind"], put=g["put"]) for g in sug["places"]),
                  *(x for k, x in mine.items() if k not in {g["key"] for g in sug["places"]})]
        change = {**{k: sug[k] for k in towngen.OPTIONS}, "places": places, **change}
    if kind == "city" and change.get("water", base.water) == "lake":
        change["water"] = "river"  # 도시 생성기는 호수를 강으로 본다
    spec = base.model_copy(update={**change, "kind": kind, "seed": a.seed if a.seed is not None else random.randrange(1, 2**31 - 1)})
    word = atlas.MAKERS[kind][0]
    out = atlas.generate(p, spec)
    info = out["info"]
    walls = f" · 구역 {info['wards']}곳 · 성문 {info['gates']}곳" if kind == "city" else ""
    print(f"{word} (시드 {spec.seed}): 집 {info['houses']}채 · 건물 {info['buildings']}채 · 길 {info['roads']}개"
          f"{f' · 다리 {info['bridges']}개' if info['bridges'] else ''}{walls} · 약 {info['width_m']}×{info['height_m']}m")
    print("  " + " · ".join(opts[k][getattr(spec, k)].split(" (")[0] for k in ("size", "roads", "water", "fields", "forest") if k in opts))
    kinds = {cid: label for cid, label, _ in towngen.CATEGORIES}
    take = [s["place"] for s in out["pins"] if a.move or not s["had"]]
    for s in out["pins"]:
        note = "" if s["place"] in take else " (지도에 놓은 자리가 있어 그대로 둬요. 옮기려면 --move)"
        print(f"  {s['name']} → {kinds.get(s['kind'], s['kind'])} 자리{note}")
    for m in out["missing"]:
        print(f"  {m['name']}: 놓지 못했어요. {m['reason']}")
    for b in out["blocked"]:
        print(f"  {b['name']}: 지금 자리가 새 {word}의 건물이나 물 위예요. 웹 지도 화면에서 옮겨 주세요")
    if not confirm(f"이 {word}{'을' if kind == 'village' else '를'} 적용할까요? 지금 지도 데이터는 바뀌어요", a.yes):
        return
    old = atlas.apply_generated(folder, p, spec, take)
    print(f"저장: {store.save(a.name, p)}")
    if old and (folder / old).is_file():
        (folder / old).unlink()


def cmd_view(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    p.settings.show_numbers = a.mode == "numbers"
    store.save(a.name, p)
    print("관계를 " + ("숫자로" if p.settings.show_numbers else "말로") + " 보여 줘요")


def cmd_adjust(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if a.warmth is None and a.trust is None:
        sys.exit("--warmth 나 --trust 중 하나는 필요해요")
    pipeline.adjust_tie(p, a.source, a.target, a.warmth, a.trust)
    store.save(a.name, p)
    print(dynamics.describe_relations(p, [a.source, a.target], numbers=p.settings.show_numbers))


def cmd_revert(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    if not confirm(f"{a.n}화 상태 반영 직후로 되돌릴까요? 이후 화의 상태 반영이 취소돼요 (본문은 유지)", a.yes):
        return
    pipeline.revert(p, a.n)
    print(f"되돌림 완료: {store.save(a.name, p)}")


def cmd_recalc(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    pipeline.recalc(p)
    store.save(a.name, p)
    print(dynamics.describe_relations(p, numbers=p.settings.show_numbers) or "관계 없음")


STAGE_LABELS = {"plan": "계획", "write": "본문", "check": "검수", "state": "상태 변경안", "name": "이름 추천",
                "revise": "부분 수정", "illustration": "삽화 프롬프트", "research": "연구"}


def _usd(x: float | None) -> str:
    return "가격 모름" if x is None else (f"${x:,.2f}" if x >= 0.995 or x == 0 else f"${x:.4f}")


def cmd_claude(a: argparse.Namespace) -> None:
    """Claude Code 설치와 구독 로그인 상태. 로그인은 Claude Code 가 직접 한다 (claude.py)."""
    from . import claude

    st = claude.status()
    if not st["installed"]:
        print(st["message"])
        return
    print(f"Claude Code {st['version']} ({st['path']})")
    acct = ", ".join(f"{k}={v}" for k, v in st["account"].items() if k != "loggedIn")
    print(f"로그인: {'됨' if st['logged_in'] else '안 됨'}{f' ({acct})' if acct else ''}")
    print(st["message"])
    if st["api_key_ignored"]:
        print("환경 변수 ANTHROPIC_API_KEY 는 구독 호출에 넘기지 않아요 (claude-api 백엔드에서만 씀).")
    print("구독으로 쓰기: CANON_LLM=claude (단계별은 CANON_LLM_WRITE=claude 등), API 키로 쓰기: CANON_LLM=claude-api")


def cmd_usage(a: argparse.Namespace) -> None:
    if a.prices:
        t = usage.price_table()
        print(f"USD / 100만 토큰. 기본값은 {t['checked']} Google 가격표 ({t['url']})")
        print(f"{'모델':<26}{'적용':>11}{'입력':>8}{'출력':>8}{'캐시':>8}{'배치입력':>9}{'배치출력':>9}")
        for r in t["rows"]:
            mark = " (사용자 수정)" if r["custom"] else (" (예고)" if r["upcoming"] else "")
            print(f"{r['model']:<26}{r['since'] or '처음부터':>11}{r['input']:>8g}{r['output']:>8g}{r['cached'] if r['cached'] is not None else r['input']:>8g}"
                  f"{r['batch_input'] if r['batch_input'] is not None else r['input'] / 2:>9g}"
                  f"{r['batch_output'] if r['batch_output'] is not None else r['output'] / 2:>9g}{mark}")
        print("고치려면 웹 설정 화면의 'AI 요금 가격표'에서 고친다. 로컬 모델은 0원으로 센다.")
        return
    s = usage.summary(None if a.all else a.days, a.project or None)
    t = s["total"]
    span = "전체 기간" if a.all else f"최근 {a.days}일"
    print(f"{span}{' · ' + a.project if a.project else ''}: 호출 {t['calls']}번, 추정 비용 {_usd(t['cost'])}")
    print(f"  입력 {t['in']:,} 토큰 (캐시 {t['cached']:,}), 출력 {t['out']:,} 토큰 (생각 토큰 포함)")
    if t["batch"]:
        print(f"  배치 {t['batch']}번으로 아낀 비용 {_usd(t['saved'])}")
    if t["failed"] or t["retries"]:
        print(f"  실패 {t['failed']}번, 다시 요청 {t['retries']}번 (여기에 쓴 비용 {_usd(t['wasted'])})")
    for title, key, label in (("작품별", "by_project", lambda r: r["project"] or "(작품 밖)"),
                              ("단계별", "by_stage", lambda r: STAGE_LABELS.get(r["stage"], r["stage"] or "기타")),
                              ("모델별", "by_model", lambda r: f"{r['model']} ({r['backend']})"),
                              ("날짜별", "by_day", lambda r: r["day"])):
        rows = s[key]
        if rows:
            print(f"\n{title}")
            for r in rows:
                print(f"  {label(r):<32} {r['calls']:>5}번 {_usd(r['cost']):>10}")
    if s["unpriced"]:
        print(f"\n! 가격표에 없는 모델: {', '.join(s['unpriced'])}. 이 호출은 비용에서 빠졌어요 (웹 설정에서 가격 추가).")
    print(f"\n추정치예요. 실제 청구 금액은 Google AI Studio 사용량 화면에서 확인하세요: {s['billing_url']}")


def cmd_foreshadows(a: argparse.Namespace) -> None:
    """복선 센터. --prune 은 본문을 고쳐 사라진 문장에 걸린 연결을 지운다."""
    p = store.load(a.name)
    if a.prune:
        k = foreshadows.prune(p)
        store.save(a.name, p)
        print(f"끊어진 연결 {k}개를 지웠습니다.\n")
    print(foreshadows.describe(p, a.all))


def cmd_statwin(a: argparse.Namespace) -> None:
    """상태창 보기와 고치기. --set 레벨=13 HP=+20 스킬= (빈 값은 항목 지우기)."""
    p = store.load(a.name)
    if not a.character:
        rows = [(c, p.state_of(c.id)) for c in p.characters]
        have = [(c, s) for c, s in rows if s and s.stats]
        for c, s in have:
            print(f"  {c.name} ({c.id}): {', '.join(f'{x.name} {x.value}' for x in s.stats)}")
        print("" if have else "상태창을 만든 인물이 없습니다.", "\n인물 하나를 보거나 만들려면: statwin <작품> <인물 id> [--set 레벨=1 힘=10]")
        return
    c = next((x for x in p.characters if x.id == a.character or x.name == a.character), None)
    if c is None:
        sys.exit(f"인물이 없습니다: {a.character}")
    if a.set:
        st = p.state_of(c.id)
        rows = {x.name: x.value for x in (st.stats if st else [])}
        for kv in a.set:
            k, eq, v = (x.strip() for x in kv.partition("="))
            if not k or not eq:
                sys.exit(f"항목=값 으로 적어 주세요: {kv}")
            if v:
                rows[k] = v  # +3 같은 값은 set_stats 가 이전 값에 더한다
            else:
                rows.pop(k, None)
        statwin.set_stats(p, c.id, [StatValue(name=k, value=v) for k, v in rows.items()])
        store.save(a.name, p)
    print(statwin.describe(p, c.id))


def cmd_time(a: argparse.Namespace) -> None:
    """작품 속 시간 보기와 고치기. --add '축제 첫날@7' 은 7일째에 오는 기한."""
    p = store.load(a.name)
    changed = False
    if a.on or a.off:
        p.timeline.enabled, changed = bool(a.on), True
    if a.start is not None:
        p.timeline.start, changed = a.start.strip(), True
    for x in a.add or []:
        what, _, day = x.rpartition("@") if "@" in x else (x, "", "")
        if day and not day.strip().isdigit():
            sys.exit(f"'무엇@날수' 로 적어 주세요 (예: 축제 첫날@7): {x}")
        d = timeline.upsert(p, Deadline(id="", what=what, day=int(day or 0)))
        print(f"기한을 더했어요: {d.id}")
        changed = True
    for i in a.close or []:
        d = next((x for x in p.timeline.deadlines if x.id == i), None)
        if d is None:
            sys.exit(f"없는 기한이에요: {i}")
        timeline.upsert(p, d.model_copy(update={"done_ep": max(timeline.last_done(p), d.set_ep)}))
        changed = True
    for i in a.drop or []:
        timeline.remove(p, i)
        changed = True
    if changed:
        store.save(a.name, p)
    print(timeline.describe(p))


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
    sp = add("arc", cmd_arc)
    sp.add_argument("--note", help="AI 에게 바라는 것 (예: 3화 안에 첫 반전)")
    sp = add("series", cmd_series)
    sp.add_argument("--note", help="AI 에게 바라는 것")
    sp = add("convert", cmd_convert)
    sp.add_argument("--episodes", type=int, help="장편 총 화수")
    sp.add_argument("--ending", choices=["keep", "reopen"], help="keep 닫고 다음 이야기로 / reopen 결말 다시 열기 (비우면 AI 가 고름)")
    sp.add_argument("--note", help="장편에 바라는 것")
    sp.add_argument("--undo", action="store_true", help="전환 전 단편으로 되돌리기")
    sp.add_argument("--rebuild", action="store_true", help="이어 쓰기 대신 재구성: 단편을 씨앗으로 장편 앞부분을 다시 짠다")
    sp.add_argument("--span", type=int, help="재구성: 다시 짤 앞부분 화수")
    sp.add_argument("--ending-at", choices=["arc", "part", "series"], help="재구성: 단편 결말이 갈 곳 (첫 아크 끝 / 1부 끝 / 작품 끝)")
    sp = add("rework", cmd_rework)
    sp.add_argument("ep", type=int)
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
    sp.add_argument("--note", help="AI 에게 바라는 것")
    sp = add("revise", cmd_revise, "message")
    sp.add_argument("--arc", type=int, help="장편: 고칠 아크 번호 (비우면 본문이 없는 첫 아크)")
    sp.add_argument("--next", action="store_true", help="장편: 다음 아크를 대화로 짜기 (적용하면 바로 아크로 붙여요)")
    sp.add_argument("--options", action="store_true", help="변경안 대신 서로 다른 방향 2~3개 받기")
    sp = add("pov", cmd_pov, yes=False)
    sp.add_argument("range", nargs="?", help="화 범위 (예: 6-12, 7). 비우면 전체")
    sp.add_argument("character", nargs="?", help="시점 인물 id 나 이름")
    sp.add_argument("--mode", help="서술 방식 (1인칭, 3인칭 제한, 3인칭 전지). 빈 문자열이면 작품 기본")
    sp.add_argument("--clear", action="store_true", help="범위의 화 시점을 지워 구간 · 작품 기본으로 되돌림")
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
    sp = add("insert", cmd_insert)
    sp.add_argument("n", type=int, nargs="?", help="이 화 자리에 넣는다 (지금 이 화부터 뒤로 밀림). 비우면 넣을 수 있는 자리")
    sp.add_argument("--title", help="새 화 제목")
    sp.add_argument("--summary", help="새 화에서 일어날 일 (AI 초안의 씨앗)")
    sp.add_argument("--line", help="새 화가 따라갈 이야기 줄기 id (외전, 과거 회상 등)")
    sp.add_argument("--ai", action="store_true", help="앞뒤 화에 맞춰 AI 가 새 화 플롯을 채움")
    sp.add_argument("--remove", action="store_true", help="넣는 대신 아직 안 쓴 n 화를 빼고 뒤 화를 당김")
    add("confirm", cmd_confirm, "which", yes=False)
    add("write", cmd_write, "n", yes=False)
    sp = add("rewrite", cmd_rewrite, "n")
    sp.add_argument("--ask", help="피드백 (예: 서윤이 더 망설이게)")
    sp.add_argument("--preset", help="빠른 요청, 쉼표로: " + ", ".join(prompts.REWRITE_PRESETS))
    sp.add_argument("--use", help="함께 넣을 것, 쉼표로: " + ", ".join(prompts.REWRITE_MATERIALS))
    sp.add_argument("--revise", action="store_true", help="처음부터 새로 쓰지 않고 지난 판을 넣어 고쳐 쓰기")
    sp.add_argument("--keep", action="append", help="살릴 부분 (본문 글 그대로, 여러 번)")
    sp.add_argument("--adopt", action="store_true", help="고르기 대기 중인 새 판을 본문으로")
    sp.add_argument("--drop", action="store_true", help="고르기 대기 중인 새 판을 버림")
    sp.add_argument("--versions", action="store_true", help="이전 판 목록")
    sp.add_argument("--restore", metavar="ID", help="이 판으로 되돌림 (예: v2)")
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
    sp = add("learn", cmd_learn)
    sp.add_argument("--pick", help="넣을 후보 번호, 쉼표로 (예: 1,3)")
    sp.add_argument("--push", action="store_true", help="연결된 라이브러리 항목에도 새 버전으로 올림")
    sp = add("stylechat", cmd_stylechat)
    sp.add_argument("message", nargs="?", help="AI 에게 바라는 것 (예: 대사를 더 짧게). --example 이면 바라는 장면")
    sp.add_argument("--ep", type=int, help="참고할 화 (본문이 있는 화). --example 이면 이 화 한 대목을 고쳐 씀")
    sp.add_argument("--pick", help="적용할 칸 번호, 쉼표로 (예: 1,3)")
    sp.add_argument("--push", action="store_true", help="연결된 라이브러리 항목에도 새 버전으로 올림")
    sp.add_argument("--example", action="store_true", help="지금 문체로 예시 글 쓰기")
    sp = add("edits", cmd_edits, yes=False)
    sp.add_argument("n", type=int, nargs="?")
    sp.add_argument("--undo", metavar="ID", help="이 수정을 되돌림 (예: e2)")
    sp.add_argument("--jsonl", action="store_true", help="고치기 전후 쌍을 JSON Lines 로 출력")
    sp = add("export", cmd_export, yes=False)
    sp.add_argument("--from", dest="start", type=int, default=0)
    sp.add_argument("--to", dest="end", type=int, default=0)
    sp.add_argument("--format", default="blank", choices=list(publish.FORMATS), help="줄바꿈 형식 (기본: 문단 사이 빈 줄)")
    sp.add_argument("--no-title", action="store_true", help="'N화. 제목' 줄을 넣지 않음 (한 화만 낼 때)")
    sp.add_argument("-o", "--output", help="저장할 .txt 파일 (없으면 화면에 출력)")
    sp = add("illust", cmd_illust, "n", yes=False)
    sp.add_argument("quote", nargs="?", help="그릴 본문 문장 (비우면 AI 가 이 화에서 장면을 고름)")
    sp.add_argument("--ask", help="바라는 것 (예: 뒷모습, 비 오는 밤)")
    sp.add_argument("--model", choices=list(illust.MODELS), help="NovelAI 모델 (기본: 작품 설정)")
    sp.add_argument("--list", action="store_true", help="저장한 삽화 프롬프트 보기")
    add("look", cmd_look, "cid")
    sp = add("voice", cmd_voice, "cid")
    sp.add_argument("--ask", help="AI 에게 바라는 것 (예: 더 수다스럽게)")
    sp.add_argument("--set", help="AI 없이 직접 적기 (빈 문자열이면 지움)")
    sp = add("show", cmd_show, yes=False)
    sp.add_argument("section", nargs="?")

    sub.add_parser("genres", help="장르 목록").set_defaults(fn=cmd_genres)
    sp = sub.add_parser("styles", help="문체 라이브러리")
    sp.add_argument("action", nargs="?", choices=["list", "add", "show", "rm", "versions", "restore"], default="list")
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
    sp = sub.add_parser("usage", help="AI 사용량과 추정 비용")
    sp.add_argument("--days", type=int, default=30, help="최근 며칠 (기본 30)")
    sp.add_argument("--all", action="store_true", help="전체 기간")
    sp.add_argument("--project", help="이 작품만")
    sp.add_argument("--prices", action="store_true", help="가격표 보기")
    sp.set_defaults(fn=cmd_usage)
    sub.add_parser("claude", help="Claude Code 구독 로그인 상태와 안내").set_defaults(fn=cmd_claude)

    sp = add("foreshadows", cmd_foreshadows, yes=False)
    sp.add_argument("--all", action="store_true", help="회수한 복선도 보기")
    sp.add_argument("--prune", action="store_true", help="끊어진 연결 지우기")
    sp = add("statwin", cmd_statwin, yes=False)
    sp.add_argument("character", nargs="?", help="인물 id 나 이름. 비우면 상태창이 있는 인물 목록")
    sp.add_argument("--set", nargs="+", action="extend", metavar="항목=값", help="값을 바꾸거나 더한다. +3 은 더하기, 빈 값은 항목 지우기")
    sp = add("time", cmd_time, yes=False)
    sp.add_argument("--start", help="1일째가 언제인지 (예: '2024년 3월 2일 토요일, 늦겨울'). 빈 값이면 지움")
    sp.add_argument("--on", action="store_true", help="작품 속 시간 기록 켜기")
    sp.add_argument("--off", action="store_true", help="끄기 (상태 변경안에 시점을 적지 않고, 쓰기 · 검수에 시간 블록을 넣지 않음)")
    sp.add_argument("--add", nargs="+", action="extend", metavar="무엇@날수", help="기한 더하기 (날수를 모르면 @ 없이)")
    sp.add_argument("--close", nargs="+", action="extend", metavar="ID", help="기한 닫기 (마지막으로 반영한 화에)")
    sp.add_argument("--drop", nargs="+", action="extend", metavar="ID", help="기한 지우기")
    sp = add("cast", cmd_cast, yes=False)
    sp.add_argument("character", nargs="?", help="인물 id 나 이름. 비우면 인물 목록")
    sp.add_argument("--numbers", action="store_true", help="관계를 숫자로")
    sp = add("map", cmd_map)
    sp.add_argument("action", nargs="?", choices=["gen"], help="gen: 마을 · 도시 생성기로 지도 만들기. 비우면 지도 보기")
    sp.add_argument("kind", nargs="?", choices=list(atlas.MAKERS), help="만들 지도: village 마을, city 도시. 비우면 지난번 지도 종류 (--ai 면 AI 제안)")
    sp.add_argument("--seed", type=int, help="같은 시드면 같은 지도. 비우면 새로 뽑는다")
    for key, opts in towngen.OPTIONS.items():
        city = citygen.OPTIONS.get(key)
        sp.add_argument(f"--{key}", help=", ".join(label.split(" (")[0] for label in opts.values()) + ("" if city else " (마을만)"))
    sp.add_argument("--move", action="store_true", help="이미 지도에 놓은 장소도 생성기가 고른 자리로 옮기기")
    sp.add_argument("--ai", action="store_true", help="AI가 작품 설정과 장소 설명을 보고 설정 칸 · 장소 종류를 제안 (직접 적은 칸이 이긴다)")
    sp = add("view", cmd_view, yes=False)
    sp.add_argument("mode", choices=["numbers", "words"])
    sp = add("adjust", cmd_adjust, "source", "target", yes=False)
    sp.add_argument("--warmth", type=float, help="-1 ~ 1")
    sp.add_argument("--trust", type=float, help="0 ~ 1")
    add("revert", cmd_revert, "n")
    add("recalc", cmd_recalc, yes=False)

    a = ap.parse_args(argv)
    ep = getattr(a, "n", None) if getattr(a, "n", None) is not None else getattr(a, "ep", None)
    try:
        with usage.scope(project=getattr(a, "name", None), episode=ep if isinstance(ep, int) else None,
                         source="cli", task=a.cmd, stage="research" if a.cmd == "compare" else None):
            a.fn(a)
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
        sys.exit(f"오류: {e}")
