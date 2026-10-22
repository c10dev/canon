"""명령줄 인터페이스.

  python -m canon new 내소설           설정 도우미 (질문에 답하면 AI 가 빈칸 제안)
  python -m canon style 내소설 sample.txt   예시 텍스트로 스타일 프로필 생성
  python -m canon arc 내소설            기승전결 구간 설계
  python -m canon plot 내소설 [--from 1 --to 16]   화별 플롯 초안
  python -m canon confirm 내소설 all|3  플롯 확정
  python -m canon write 내소설 3        본문 생성
  python -m canon update 내소설 3       상태 변경안 확인 후 반영
  python -m canon run 내소설            확정된 화를 순서대로 write → update
  python -m canon brief 내소설 3        구독형 채팅 앱용 작업지시서 출력
  python -m canon import 내소설 3 본문.txt   다른 곳에서 쓴 본문 가져오기
  python -m canon show 내소설 [섹션]
설정은 projects/<이름>/project.json 을 직접 고쳐도 된다.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import pipeline, prompts, store
from .llm import dump, get_llm
from .schema import Meta, Project, StateDelta


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
    meta = Meta(
        title=a.title or ask("제목"),
        genre=a.genre or ask("장르", "현대 드라마"),
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
    s = pipeline.suggest_setup(get_llm(), p)
    print(dump(s))
    if confirm("이 제안을 반영할까요? (반영 후 project.json 에서 수정 가능)", yes):
        pipeline.apply_setup(p, s)
        print(f"저장: {store.save(name, p)}")


def cmd_suggest(a: argparse.Namespace) -> None:
    _suggest(a.name, store.load(a.name), a.yes)


def cmd_style(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    sample = Path(a.file).read_text(encoding="utf-8")
    profile = pipeline.analyze_style(get_llm(), sample)
    print(dump(profile))
    if confirm("이 스타일 프로필을 저장할까요?", a.yes):
        p.style = profile
        print(f"저장: {store.save(a.name, p)}")


def cmd_arc(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    plan = pipeline.plan_arc(get_llm(), p)
    for act in plan.acts:
        print(f"[{act.name}] {act.start_ep}~{act.end_ep}화  목표: {act.goal}  / 전환점: {act.key_turn}")
    if confirm("이 구조로 확정할까요?", a.yes):
        p.arc = plan.acts
        print(f"저장: {store.save(a.name, p)}")


def cmd_plot(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    start, end = a.start or 1, a.end or p.meta.target_episodes
    batch = pipeline.draft_plots(get_llm(), p, start, end)
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
    text = pipeline.write_episode(get_llm(), p, n)
    ep = p.episode(n)
    ep.text, ep.status = text, "written"
    store.save(name, p)
    print(f"{n}화 저장: {store.project_dir(name) / 'episodes' / f'{n:02d}.md'} ({len(text)}자)")


def _print_delta(d: StateDelta) -> None:
    print(f"\n=== {d.episode}화 상태 변경안 ===\n요약: {d.summary}")
    for c in d.character_updates:
        print(f"- 인물 {c.character_id}: 감정={c.emotional_state} 목표={c.current_goal} 위치={c.location} 새로 앎={c.knows}")
    for r in d.relationship_updates:
        print(f"- 관계 {r.a}↔{r.b} ({r.type}): 호감 {r.affinity}, 긴장 {r.tension}  {r.description}")
    for f in d.new_facts:
        print(f"- 확정 사실: {f}")
    for f in d.foreshadow_planted:
        print(f"- 복선 심음 {f.id}: {f.description}")
    for f in d.foreshadow_resolved:
        print(f"- 복선 회수: {f}")
    for w in d.warnings:
        print(f"! 경고: {w}")


def cmd_update(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    _update(a.name, p, a.n, a.yes, a.from_json)


def _update(name: str, p: Project, n: int, yes: bool, from_json: str | None = None) -> bool:
    if from_json:
        raw = Path(from_json).read_text(encoding="utf-8")
        raw = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw.strip())
        delta = StateDelta.model_validate_json(raw)
        delta.episode = n
    else:
        print(f"{n}화 상태 추출 중...")
        delta = pipeline.extract_state(get_llm(), p, n)
    _print_delta(delta)
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
        if not _update(a.name, p, n, a.yes):
            print("상태 반영을 보류해 멈춥니다.")
            return
    print("모든 화 완료")


def cmd_brief(a: argparse.Namespace) -> None:
    p = store.load(a.name)
    text = prompts.state_brief(p, a.n) if a.state else prompts.episode_brief(p, a.n)
    kind = "state" if a.state else "episode"
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
    if a.section:
        print(dump(getattr(p, a.section)))
        return
    m = p.meta
    print(f"《{m.title}》 {m.genre} / {m.target_episodes}화\n로그라인: {m.logline}\n")
    print("인물:", ", ".join(f"{c.name}({c.id})" for c in p.characters) or "없음")
    print("스타일:", "있음" if p.style.sample_passages or p.style.narration_pov else "없음")
    for act in p.arc:
        print(f"[{act.name}] {act.start_ep}~{act.end_ep}화: {act.goal}")
    for e in p.episodes:
        print(f"  {e.plot.number:>2}화 {e.status:<9} {e.plot.title}")
    print(f"열린 복선: {sum(f.status == 'open' for f in p.foreshadows)}  확정 사실: {len(p.facts)}")


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
    sp.add_argument("--genre", default="")
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
    add("run", cmd_run)
    sp = add("brief", cmd_brief, "n", yes=False)
    sp.add_argument("--state", action="store_true", help="상태 정리용 작업지시서")
    add("import", cmd_import, "n", "file", yes=False)
    sp = add("show", cmd_show, yes=False)
    sp.add_argument("section", nargs="?")

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (ValueError, KeyError, FileNotFoundError) as e:
        sys.exit(f"오류: {e}")
