"""JSON 파일 저장소. projects/<이름>/project.json 에 상태를 보관하고(스냅샷만 snapshots/ 에 따로),
본문은 읽기 편하도록 episodes/NN.md 로도 내보낸다 (화가 100화를 넘으면 NNN.md, ep_file)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from . import cancel
from .dynamics import seed_ties
from .schema import BranchInfo, CueLab, PlayInfo, Project, Snapshot

ROOT = Path(os.environ.get("CANON_HOME", "projects"))

# 지금 저장하는 화면(브라우저 탭) id. 웹 요청이 정하고, 백그라운드 작업 · 자동 집필 · CLI 는 빈 값이다.
# 화면이 저장하면 Project.edit_rev 를 올리고 saved_by 에 남긴다. 빈 값이면 디스크의 두 값을 그대로 둔다
writer: ContextVar[str] = ContextVar("writer", default="")

# 이번 웹 요청이 저장한 작품의 판 {이름: tag}. 웹 미들웨어가 요청마다 빈 dict 를 두고, 저장 응답에 판을 붙인다
# (화면이 저장 응답을 받은 작품으로 보관해 다음 GET 이 304 가 되게). 작업 스레드는 문맥을 복사해도 같은 dict 를 본다
saved: ContextVar[dict | None] = ContextVar("saved", default=None)


def project_dir(name: str) -> Path:
    return ROOT / name


def exists(name: str) -> bool:
    return (project_dir(name) / "project.json").exists()


def tag(path: Path) -> str:
    """파일의 판: 바뀌면 달라지는 값 (작품 GET 의 ETag)."""
    return _tag(path.stat())


def _tag(st: os.stat_result) -> str:
    return f'"{st.st_mtime_ns:x}-{st.st_size:x}"'


# 읽은 작품 캐시 {이름: (파일 판, Project)}. 화면 이동마다 여러 요청이 장편 project.json(수 MB)을 읽는데, JSON 검증만 0.1초쯤 걸린다.
# 파일 판(수정 시각 · 크기 · inode)이 같으면 전에 읽은 것을 쓴다. 저장은 바꿔치기(os.replace)라 판이 늘 바뀐다.
# load 는 고쳐 써도 되는 깊은 복사본(0.03초), load_view 는 캐시 것을 돌려준다. 저장하면 저장한 내용을 바로 캐시에 둔다 (_remember)
_view_lock = threading.Lock()
_views: dict[str, tuple[tuple[int, int, int], Project]] = {}
_VIEWS_MAX = 4


def _key(st: os.stat_result) -> tuple[int, int, int]:
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _keep(name: str, key: tuple[int, int, int], p: Project) -> None:
    with _view_lock:
        _views.pop(name, None)
        _views[name] = (key, p)
        while len(_views) > _VIEWS_MAX:
            _views.pop(next(iter(_views)))


def load_view(name: str) -> Project:
    """읽기 전용 load. 돌려준 Project 는 여러 요청이 함께 쓰므로 고치지 않는다. 고쳐 저장할 작품은 load 로 읽는다."""
    path = project_dir(name) / "project.json"
    # 판을 읽기 전에 잰다. 읽는 사이 바뀌면 새 내용이 옛 판으로 남을 뿐이고, 다음 호출은 새 판을 보고 다시 읽는다
    try:
        st = path.stat()
    except FileNotFoundError:
        raise FileNotFoundError(f"프로젝트가 없어요: {path}") from None
    with _view_lock:
        hit = _views.get(name)
    if hit and hit[0] == _key(st):
        return hit[1]
    p = read_disk(path)
    seed_ties(p)  # 관계 역학 이전의 project.json 은 affinity 로 방향 관계를 만든다
    _keep(name, _key(st), p)
    return p


# ---------- 스냅샷 파일 ----------
# 스냅샷은 작품의 절반 가까이라(장편) project.json 이 아니라 snapshots/<화>-<내용 해시>.json 에 하나씩 둔다.
# project.json 맨 앞의 "snapshot_files" 가 차례대로 파일 이름을 적는다. 내용이 같으면 이름도 같아 다시 쓰지 않는다.
# 새 파일을 먼저 쓰고 project.json 을 바꾼 뒤, 어느 판(project.json · prev · backups)도 적지 않은 파일만 지운다.
# "snapshot_files" 가 없는 옛 project.json 은 안에 든 snapshots 를 그대로 읽는다. Project 는 모르는 칸을 버리므로 이 칸은 store 만 본다.
SNAP_DIR = "snapshots"
_SNAP_HEAD = re.compile(r'^\{"snapshot_files":(\[[^\]]*\])')


def _snap_refs(path: Path) -> list[str] | None:
    """project.json 맨 앞의 스냅샷 파일 목록. 옛 모양이면 None."""
    try:
        with path.open("rb") as f:
            head = f.read(64 * 1024).decode("utf-8", errors="ignore")
    except OSError:
        return None
    m = _SNAP_HEAD.match(head)
    return json.loads(m.group(1)) if m else None


def read_disk(path: Path, tries: int = 3) -> Project:
    """디스크의 project.json 을 스냅샷 파일과 함께 읽는다 (캐시를 거치지 않음)."""
    for left in range(tries, 0, -1):
        text = path.read_text(encoding="utf-8")
        p = Project.model_validate_json(text)
        m = _SNAP_HEAD.match(text[:64 * 1024])
        if not m:
            return p
        sdir = path.parent / SNAP_DIR
        try:
            p.snapshots = [Snapshot.model_validate_json((sdir / f).read_text(encoding="utf-8")) for f in json.loads(m.group(1))]
            return p
        except FileNotFoundError:  # 읽는 사이 다른 저장이 project.json 을 바꾸고 옛 파일을 지웠다. 새 판을 다시 읽는다
            if left == 1:
                raise
    raise AssertionError("unreachable")


# 지난 저장의 스냅샷과 파일 이름 {작품 폴더: {화: [(스냅샷, 이름)]}}. 스냅샷은 캐시에 둔 검증 사본(_remember)이라 아무도 고치지 않는다.
# 같은 스냅샷이면(비교는 직렬화보다 열 배쯤 빠르다) 다시 직렬화하지 않고 이름을 그대로 쓴다
_snap_written: dict[Path, dict[int, list[tuple[Snapshot, str]]]] = {}


def _write_snapshots(d: Path, p: Project) -> list[str]:
    sdir = d / SNAP_DIR
    seen = _snap_written.get(d, {})
    refs = []
    for s in p.snapshots:
        f = next((ref for old, ref in seen.get(s.episode, ()) if old == s and (sdir / ref).exists()), None)
        if f:
            refs.append(f)
            continue
        body = s.model_dump_json()
        f = f"{s.episode}-{hashlib.sha1(body.encode()).hexdigest()[:12]}.json"
        refs.append(f)
        if not (sdir / f).exists():
            sdir.mkdir(exist_ok=True)
            tmp = sdir / f"{f}.{os.getpid()}.{threading.get_ident()}.tmp"
            tmp.write_text(body, encoding="utf-8")
            os.replace(tmp, sdir / f)
    return refs


def _drop_old_snapshots(d: Path) -> None:
    sdir = d / SNAP_DIR
    if not sdir.is_dir():
        return
    keep: set[str] = set()
    for f in [d / "project.json", d / "project.prev.json", *(d / BACKUP_DIR).glob("project.*.json")]:
        keep |= set(_snap_refs(f) or ())
    for f in sdir.glob("*.json"):
        if f.name not in keep:
            f.unlink(missing_ok=True)


def load(name: str) -> Project:
    """작품을 읽는다. 고쳐 써도 되는 사본이다."""
    return load_view(name).model_copy(deep=True)


def _remember(name: str, st: os.stat_result, p: Project) -> Project:
    """방금 저장한 작품을 캐시에 둔다 (저장 직후 첫 읽기도 JSON 을 다시 검증하지 않게).
    디스크에서 읽은 것과 같도록 저장한 값을 다시 검증하고 seed_ties 를 거친다 (검증기가 범위를 자르는 칸 등)."""
    fresh = Project.model_validate(p.model_dump())
    seed_ties(fresh)
    _keep(name, _key(st), fresh)
    return fresh


# 내보낸 본문 파일 {경로: (내용 해시, 수정 시각)}. 작가가 파일을 고쳤거나 지웠으면 시각이 달라 다시 쓴다
_md_written: dict[Path, tuple[int, int]] = {}


def _mtime(f: Path) -> int:
    try:
        return f.stat().st_mtime_ns
    except FileNotFoundError:
        return -1


_PRESET = re.compile(r'"model_preset":\s*("(?:[^"\\]|\\.)*")')
_preset_seen: dict[Path, tuple[tuple[int, int], str]] = {}


def model_preset(name: str) -> str:
    """작품이 고른 단계 프리셋 id (Settings.model_preset). 없으면 "".
    AI 를 부를 때마다 묻으므로 작품 전체를 읽지 않고 그 칸만 찾고, 파일이 그대로면 앞서 찾은 값을 쓴다."""
    path = project_dir(name) / "project.json"
    try:
        st = path.stat()
    except OSError:
        return ""
    key = (st.st_mtime_ns, st.st_size)
    seen = _preset_seen.get(path)
    if seen and seen[0] == key:
        return seen[1]
    try:
        m = _PRESET.search(path.read_text(encoding="utf-8"))
        value = str(json.loads(m[1])) if m else ""
    except (OSError, ValueError):
        value = ""
    _preset_seen[path] = (key, value)
    return value


_MARK = re.compile(r'"edit_rev":\s*(\d+),\s*"saved_by":\s*("(?:[^"\\]|\\.)*")')


def _saved_mark(path: Path) -> tuple[int, str]:
    """디스크 작품의 (edit_rev, saved_by). 두 칸은 Project 의 마지막 필드라 파일 끝만 읽는다 (장편도 저장마다 전체를 읽지 않게).
    끝에서 찾지 못하면(필드 차례가 바뀐 옛 파일, 아주 긴 saved_by) 파일 전체를 읽는다. 0 으로 돌려주면 충돌 검사가 꺼진다.
    tests/test_store_backup.py 가 두 칸이 마지막 필드인지 본다."""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 4096))
        tail = f.read().decode("utf-8", errors="ignore")
    if m := _MARK.search(tail):
        return int(m.group(1)), json.loads(m.group(2))
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0, ""
    return int(d.get("edit_rev") or 0), str(d.get("saved_by") or "")


# ---------- 저장 전 백업 ----------
# project.prev.json: 직전 판 하나. backups/project.<날짜-시>.json: 시간마다 첫 저장 직전 판, 최근 BACKUP_KEEP 개.
# 저장은 늘 새 파일로 바꿔치기(os.replace)하므로 옛 판은 하드 링크로 붙잡으면 복사하지 않아도 그대로 남는다.
BACKUP_DIR = "backups"
BACKUP_KEEP = 24


def _hold(src: Path, dst: Path) -> None:
    """src 를 dst 로 남긴다. 하드 링크가 되면 복사하지 않는다 (파일 크기와 관계없이 바로 끝난다)."""
    tmp = dst.with_name(f"{dst.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        os.link(src, tmp)
    except OSError:  # 하드 링크를 지원하지 않는 파일 시스템
        shutil.copy(src, tmp)
    os.replace(tmp, dst)


def _backup(d: Path, path: Path) -> None:
    _hold(path, d / "project.prev.json")
    bdir = d / BACKUP_DIR
    dst = bdir / f"project.{datetime.now():%Y%m%d-%H}.json"
    if dst.exists():
        return
    bdir.mkdir(exist_ok=True)
    _hold(path, dst)
    for old in sorted(bdir.glob("project.*.json"))[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)


def backups(name: str) -> list[Path]:
    """남아 있는 시간별 백업, 오래된 것부터."""
    return sorted((project_dir(name) / BACKUP_DIR).glob("project.*.json"))


def ep_file(d: Path, n: int, last: int) -> Path:
    """n화 본문을 내보낼 파일. 마지막 화가 100화 이상이면 세 자리로 써서 파일 이름 차례가 화 차례와 같다."""
    return d / "episodes" / f"{n:0{3 if last >= 100 else 2}d}.md"


# ---------- 검토를 기다리는 AI 결과와 실패한 작업 ----------
# projects/<이름>/pending.json. 작업 결과(제안)는 화면 메모리에만 있어 새로고침 · 다른 기기에서 사라졌다.
# 작업이 끝나면 여기에 남기고, 화면이 반영하거나 버리면 지운다. 작품 데이터(project.json)는 바꾸지 않는다.
# { "results": { "<kind>:<ep>": {...} }, "failures": { "<kind>:<ep>": {...} } }

_pending_lock = threading.Lock()


def _pending_path(name: str) -> Path:
    return project_dir(name) / "pending.json"


def load_pending(name: str) -> dict:
    path = _pending_path(name)
    try:
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:  # 깨진 파일은 없는 것으로 본다 (다시 받으면 된다)
        d = {}
    return {"results": d.get("results", {}), "failures": d.get("failures", {})}


def pending_eps(name: str, first: int = 1) -> list[int]:
    """first 화부터 검토를 기다리는 AI 결과나 실패한 작업이 있는 화. 화 번호를 옮기기 전에 막는 데 쓴다."""
    d = load_pending(name)
    return sorted({r.get("ep") or 0 for r in [*d["results"].values(), *d["failures"].values()] if (r.get("ep") or 0) >= max(first, 1)})


def edit_pending(name: str, fn) -> dict:
    """pending.json 을 읽어 fn(d) 로 고치고 저장한다."""
    cancel.check()
    with _pending_lock:
        d = load_pending(name)
        fn(d)
        path = _pending_path(name)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return d


def save(name: str, p: Project) -> Path:
    cancel.check()  # 멈춘 작업은 저장하지 않는다
    d = project_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "project.json"
    if path.exists():
        rev, by = _saved_mark(path)
        if writer.get():
            p.edit_rev, p.saved_by = rev + 1, writer.get()
        else:  # 작업이 오래전에 읽은 사본을 저장해도 화면 저장 기록은 디스크 것을 잇는다
            p.edit_rev, p.saved_by = rev, by
        _backup(d, path)  # 직전 판과 시간별 백업을 남긴다
    # 다른 스레드(자동 집필, 백그라운드 작업)가 쓰는 도중에 읽어도 빈 파일을 보지 않게 바꿔치기로 쓴다
    # 들여쓰기 없이 쓴다: 장편은 들여쓰기만으로 1MB 넘게 커지고 저장마다 0.015초 더 걸린다 (2026-11-02 실측)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    refs = _write_snapshots(d, p)  # 스냅샷 파일을 먼저 쓴다. project.json 이 바뀌기 전에는 아무도 새 파일을 적지 않는다
    body = p.model_dump_json(exclude={"snapshots"})
    tmp.write_text('{"snapshot_files":' + json.dumps(refs) + "," + body[1:], encoding="utf-8")
    st = tmp.stat()  # 바꿔치기는 inode 와 수정 시각을 그대로 옮긴다. 바꾼 뒤 다른 스레드가 또 써도 이 판은 이 내용이다
    os.replace(tmp, path)
    _drop_old_snapshots(d)
    fresh = _remember(name, st, p)
    memo: dict[int, list[tuple[Snapshot, str]]] = {}
    for s, ref in zip(fresh.snapshots, refs):
        memo.setdefault(s.episode, []).append((s, ref))
    _snap_written[d] = memo
    if (got := saved.get()) is not None:
        got[name] = _tag(st)

    ep_dir = d / "episodes"
    last = max((e.plot.number for e in p.episodes), default=0)
    for ep in p.episodes:
        if ep.text:
            ep_dir.mkdir(exist_ok=True)
            f = ep_file(d, ep.plot.number, last)
            body = f"# {ep.plot.number}화. {ep.plot.title}\n\n{ep.text}\n"
            if _md_written.get(f) != (hash(body), _mtime(f)):  # 지난번에 쓴 그대로면 다시 쓰지 않는다
                f.write_text(body, encoding="utf-8")
                _md_written[f] = (hash(body), _mtime(f))
    if ep_dir.is_dir():  # 본문을 지운 화나 빠진 화, 자릿수가 바뀐 옛 이름의 내보낸 파일은 지운다 (숫자.md 만, 작가가 둔 다른 파일은 그대로)
        have = {ep_file(d, e.plot.number, last).name for e in p.episodes if e.text}
        for f in ep_dir.glob("*.md"):
            if f.stem.isdigit() and f.name not in have:
                f.unlink(missing_ok=True)
    return path


# ---------- 갈래 정보 (canon/branches.py) ----------
# projects/<이름>/branch.json. project.json 밖에 둬서 화면이 작품을 통째로 저장해도 덮지 않는다.

def _branch_path(name: str) -> Path:
    return project_dir(name) / "branch.json"


def load_branch(name: str) -> BranchInfo | None:
    """갈래 정보. 파일이 없거나 깨졌으면 갈래가 없는 작품으로 본다."""
    path = _branch_path(name)
    if not path.exists():
        return None
    try:
        return BranchInfo.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def save_branch(name: str, b: BranchInfo) -> Path:
    path = _branch_path(name)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(b.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def drop_branch(name: str) -> None:
    _branch_path(name).unlink(missing_ok=True)


# ---------- 플레이 정보 (canon/play.py) ----------
# projects/<이름>/play.json. 갈래 정보처럼 project.json 밖에 둔다. 파일이 있으면 플레이 사본이다.

def _play_path(name: str) -> Path:
    return project_dir(name) / "play.json"


def shares_text(name: str) -> bool:
    """앞 화 본문을 다른 작품과 함께 쓰는 작품(갈래 집안, 플레이 사본). 본문이 있는 화의 번호를 옮기지 않는다 (renumber.last_fixed)."""
    return load_branch(name) is not None or load_play(name) is not None


def load_play(name: str) -> PlayInfo | None:
    """플레이 정보. 파일이 없거나 깨졌으면 플레이가 아닌 작품으로 본다."""
    path = _play_path(name)
    if not path.exists():
        return None
    try:
        return PlayInfo.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def save_play(name: str, info: PlayInfo) -> Path:
    path = _play_path(name)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(info.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def drop_play(name: str) -> None:
    _play_path(name).unlink(missing_ok=True)



# ---------- 큐 시트 실험 (canon/cue.py) ----------
# projects/<이름>/cuelab/<화>.json. 작품 데이터가 아니라서 project.json 밖에 둔다.

def _cuelab_path(name: str, n: int) -> Path:
    return project_dir(name) / "cuelab" / f"{n}.json"


def load_cuelab(name: str, n: int) -> CueLab:
    """n화 큐 시트 실험. 없거나 깨졌으면 빈 실험."""
    path = _cuelab_path(name, n)
    if path.exists():
        try:
            return CueLab.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return CueLab(episode=n)


def save_cuelab(name: str, lab: CueLab) -> Path:
    path = _cuelab_path(name, lab.episode)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(lab.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def cuelab_episodes(name: str) -> list[int]:
    """큐 시트 실험 파일이 있는 화."""
    d = project_dir(name) / "cuelab"
    return sorted(int(x.stem) for x in d.glob("*.json") if x.stem.isdigit()) if d.exists() else []

def backup_path(name: str, tag: str) -> Path:
    return project_dir(name) / f"{tag}.json"


def save_backup(name: str, tag: str, p: Project) -> Path:
    """되돌리기용으로 작품 전체를 따로 남긴다 (예: 단편 → 장편 전환 직전, tag='before-serial')."""
    path = backup_path(name, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_backup(name: str, tag: str) -> Project | None:
    path = backup_path(name, tag)
    if not path.exists():
        return None
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def drop_backup(name: str, tag: str) -> None:
    backup_path(name, tag).unlink(missing_ok=True)
