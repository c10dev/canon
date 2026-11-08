"""JSON 파일 저장소. projects/<이름>/project.json 에 상태를 보관하고(스냅샷만 snapshots/ 에 따로),
본문은 읽기 편하도록 episodes/NN.md 로도 내보낸다 (화가 100화를 넘으면 NNN.md, ep_file)."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

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


def write_atomic(path: Path, text: str | bytes, mode: int | None = None, fsync: bool = False) -> os.stat_result:
    """text(글 또는 바이트) 를 path 에 바꿔치기로 쓴다: 이 프로세스 · 스레드만 쓰는 tmp 파일에 다 쓴 뒤 os.replace 로 바꿔 넣는다.
    중간에 멈춰도 path 는 옛 내용 그대로다. mode 를 주면 tmp 를 처음부터 그 권한으로 만든다 (키 파일).
    fsync 면 내용과 폴더를 디스크에 내린다 (전원이 끊겨도 빈 파일이 남지 않게). 돌려주는 것: 바꿔 넣기 직전 tmp 의 stat (판)."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666 if mode is None else mode)
        with (os.fdopen(fd, "wb") if isinstance(text, bytes) else os.fdopen(fd, "w", encoding="utf-8")) as f:
            if mode is not None:
                os.fchmod(f.fileno(), mode)  # 죽은 프로세스가 남긴 같은 이름의 tmp 는 만들 때의 권한을 따르지 않는다
            f.write(text)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        st = tmp.stat()
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if fsync:
        with contextlib.suppress(OSError):
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    return st


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


def peek(name: str) -> Project:
    """작품 목록 카드용 가벼운 읽기. 캐시에 같은 판이 있으면 그것, 없으면 스냅샷 파일 없이 project.json 만 검증한다.
    스냅샷이 빠진 Project 라 캐시에 두지 않고, 고치거나 저장하지 않는다. seed_ties 도 거치지 않는다."""
    path = project_dir(name) / "project.json"
    st = path.stat()
    with _view_lock:
        hit = _views.get(name)
    if hit and hit[0] == _key(st):
        return hit[1]
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


# ---------- 스냅샷 파일 ----------
# 스냅샷은 작품의 절반 가까이라(장편) project.json 이 아니라 snapshots/<화>-<내용 해시>.json 에 하나씩 둔다.
# project.json 맨 앞의 "snapshot_files" 가 차례대로 파일 이름을 적는다. 내용이 같으면 이름도 같아 다시 쓰지 않는다.
# 새 파일을 먼저 쓰고 project.json 을 바꾼 뒤, 어느 판(project.json · prev · backups)도 적지 않은 파일만 지운다.
# "snapshot_files" 가 없는 옛 project.json 은 안에 든 snapshots 를 그대로 읽는다. Project 는 모르는 칸을 버리므로 이 칸은 store 만 본다.
SNAP_DIR = "snapshots"
_SNAP_HEAD = re.compile(r'^\{"snapshot_files":(\[[^\]]*\])')


class SnapRefsUnreadable(Exception):
    """판 파일의 스냅샷 목록을 읽지 못했다. 옛 모양(목록 없음)과 다르다."""


def _snap_refs(path: Path) -> list[str] | None:
    """project.json 맨 앞의 스냅샷 파일 목록. 옛 모양이면 None, 파일이 없으면 [].
    읽지 못하면(OSError, 빈 파일, JSON 객체가 아닌 머리, 64KB 안에서 닫히지 않는 목록) SnapRefsUnreadable."""
    try:
        with path.open("rb") as f:
            head = f.read(64 * 1024).decode("utf-8", errors="ignore")
    except FileNotFoundError:  # 없는 판은 아무 파일도 적지 않는다
        return []
    except OSError as e:
        raise SnapRefsUnreadable(f"{path}: {e}") from e
    m = _SNAP_HEAD.match(head)
    if m:
        try:
            refs = json.loads(m.group(1))
        except ValueError as e:
            raise SnapRefsUnreadable(f"{path}: 스냅샷 목록이 JSON이 아니에요") from e
        if not all(isinstance(r, str) for r in refs):
            raise SnapRefsUnreadable(f"{path}: 스냅샷 목록 모양이 달라요")
        return refs
    if head.startswith('{"snapshot_files"'):
        raise SnapRefsUnreadable(f"{path}: 스냅샷 목록이 앞 64KB 안에서 닫히지 않아요")
    if not head.lstrip().startswith("{"):
        raise SnapRefsUnreadable(f"{path}: 빈 파일이거나 JSON 객체가 아니에요")
    return None


def read_disk(path: Path, tries: int = 3, home: Path | None = None) -> Project:
    """디스크의 project.json 을 스냅샷 파일과 함께 읽는다 (캐시를 거치지 않음).
    home 은 스냅샷 폴더가 있는 작품 폴더다. 비우면 path 가 든 폴더 (backups/ 안의 판은 작품 폴더를 넘긴다)."""
    for left in range(tries, 0, -1):
        text = path.read_text(encoding="utf-8")
        p = Project.model_validate_json(text)
        m = _SNAP_HEAD.match(text[:64 * 1024])
        if not m:
            return p
        sdir = (home or path.parent) / SNAP_DIR
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
            write_atomic(sdir / f, body, fsync=True)  # project.json 이 이 파일을 적기 전에 디스크까지 내린다
    return refs


# 이 시간(초) 안에 쓴 스냅샷 파일은 아무 판도 적지 않아도 지우지 않는다.
# 잠금(_disk_lock)을 쓰지 않는 옛 프로세스가 막 쓰고 아직 project.json 에 적지 않은 파일을 지키는 두 번째 울타리다
SNAP_GRACE = 60.0


def _drop_old_snapshots(d: Path) -> None:
    sdir = d / SNAP_DIR
    if not sdir.is_dir():
        return
    keep: set[str] = set()
    for f in [d / "project.json", d / "project.prev.json", *(d / BACKUP_DIR).glob("*.json")]:
        try:
            keep |= set(_snap_refs(f) or ())
        except SnapRefsUnreadable as e:
            # Canon 이 쓰지 않은 backups/ 파일(시간별 · 되돌리기 전 이름이 아닌 것)은 스냅샷을 적지 않으므로 넘긴다.
            # 이런 파일은 아무도 지우지 않아 정리가 영영 멈출 수 있다
            if f.parent.name == BACKUP_DIR and not (_HOURLY.match(f.name) or _RESTORE.match(f.name)):
                continue
            # 읽지 못한 판이 적은 파일을 모르므로 이번 정리는 건너뛴다
            logging.getLogger("canon").warning("스냅샷 정리를 건너뛰었어요. 판을 읽지 못했어요: %s", e)
            return
    fresh = time.time() - SNAP_GRACE
    for f in sdir.glob("*.json"):
        if f.name in keep:
            continue
        try:
            if f.stat().st_mtime > fresh:
                continue
        except FileNotFoundError:
            continue
        f.unlink(missing_ok=True)


_held = threading.local()


@contextlib.contextmanager
def _disk_lock(d: Path) -> Iterator[None]:
    """작품 폴더의 .lock 에 거는 프로세스 사이 잠금 (명령줄과 웹 서버가 같은 작품을 함께 저장해도 섞이지 않게).
    flock 은 연 파일마다 걸려서 같은 프로세스의 다른 스레드도 기다린다. 한 스레드 안에서는 다시 잡아도 된다."""
    held: set[Path] = getattr(_held, "dirs", None) or set()
    _held.dirs = held
    if d in held:
        yield
        return
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / ".lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        held.add(d)
        try:
            yield
        finally:
            held.discard(d)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


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
# project.prev.json: 직전 판 하나. backups/project.<날짜-시>.json: 시간마다 첫 저장 직전 판 (보관 규칙은 backup_prune).
# backups/before-restore.<날짜-시분초>.json: 백업에서 되돌리기 직전 판 (최근 RESTORE_KEEP 개).
# 저장은 늘 새 파일로 바꿔치기(os.replace)하므로 옛 판은 하드 링크로 붙잡으면 복사하지 않아도 그대로 남는다.
BACKUP_DIR = "backups"
BACKUP_HOURS = 24  # 최근 시간별 백업을 이만큼 모두 남긴다
BACKUP_DAYS = 14  # 그보다 오래된 시간별 백업은 최근 이 날수 동안 하루에 하나(그날 마지막 것)만 남긴다
RESTORE_KEEP = 10
_HOURLY = re.compile(r"^project\.(\d{8})-(\d{2})\.json$")
_RESTORE = re.compile(r"^before-restore\.(\d{8}-\d{6})\.json$")


def _hold(src: Path, dst: Path) -> None:
    """src 를 dst 로 남긴다. 하드 링크가 되면 복사하지 않는다 (파일 크기와 관계없이 바로 끝난다)."""
    tmp = dst.with_name(f"{dst.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        os.link(src, tmp)
    except OSError:  # 하드 링크를 지원하지 않는 파일 시스템
        shutil.copy(src, tmp)
    os.replace(tmp, dst)


def backup_prune(names: list[str], now: datetime) -> list[str]:
    """시간별 백업 파일 이름 중 지울 것. 최근 BACKUP_HOURS 개는 모두 남기고,
    그보다 오래된 것은 now 부터 BACKUP_DAYS 날 안의 날마다 그날 마지막 것 하나만 남긴다. 시간별 이름이 아닌 파일은 건드리지 않는다."""
    hourly = sorted(n for n in names if _HOURLY.match(n))
    old = hourly[:-BACKUP_HOURS] if BACKUP_HOURS else hourly
    first = now.date().toordinal() - BACKUP_DAYS + 1
    keep: dict[str, str] = {}
    for n in old:  # 차례대로 보므로 날마다 마지막 것이 남는다
        day = _HOURLY.match(n).group(1)  # type: ignore[union-attr]
        if datetime.strptime(day, "%Y%m%d").date().toordinal() >= first:
            keep[day] = n
    return [n for n in old if n not in keep.values()]


def _backup(d: Path, path: Path) -> None:
    _hold(path, d / "project.prev.json")
    bdir = d / BACKUP_DIR
    now = datetime.now()
    dst = bdir / f"project.{now:%Y%m%d-%H}.json"
    if dst.exists():
        return
    bdir.mkdir(exist_ok=True)
    _hold(path, dst)
    for old in backup_prune([f.name for f in bdir.glob("project.*.json")], now):
        (bdir / old).unlink(missing_ok=True)


def backups(name: str) -> list[Path]:
    """남아 있는 시간별 백업, 오래된 것부터."""
    return sorted(f for f in (project_dir(name) / BACKUP_DIR).glob("project.*.json") if _HOURLY.match(f.name))


# 백업 목록의 화 수 · 반영한 마지막 화 {경로: (판, (화 수, 반영한 마지막 화, 제목))}. 하드 링크로 남긴 판은 바뀌지 않는다
_brief_seen: dict[Path, tuple[tuple[int, int, int], tuple[int, int, str]]] = {}


def _brief(f: Path, st: os.stat_result) -> tuple[int, int, str]:
    key = _key(st)
    seen = _brief_seen.get(f)
    if seen and seen[0] == key:
        return seen[1]
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        eps = d.get("episodes") or []
        done = [int((e.get("plot") or {}).get("number") or 0) for e in eps if e.get("status") == "finalized"]
        got = (len(eps), max(done, default=0), str((d.get("meta") or {}).get("title") or ""))
    except (OSError, ValueError, AttributeError, TypeError):
        got = (-1, 0, "")  # 깨진 파일
    _brief_seen[f] = (key, got)
    return got


def _backup_files(name: str) -> list[tuple[str, str, Path]]:
    """되돌릴 수 있는 백업 (id, 종류, 경로). id 는 작품 폴더 안 상대 경로다."""
    d = project_dir(name)
    out: list[tuple[str, str, Path]] = []
    bdir = d / BACKUP_DIR
    if bdir.is_dir():
        for f in bdir.glob("*.json"):
            kind = "hourly" if _HOURLY.match(f.name) else "restore" if _RESTORE.match(f.name) else ""
            if kind:
                out.append((f"{BACKUP_DIR}/{f.name}", kind, f))
    if (d / "project.prev.json").exists():
        out.append(("project.prev.json", "prev", d / "project.prev.json"))
    for f in d.glob("before-*.json"):
        kind = "delete" if re.fullmatch(r"before-delete-\d+\.json", f.name) else "serial" if f.name == "before-serial.json" else ""
        if kind:
            out.append((f.name, kind, f))
    return out


def backup_list(name: str) -> list[dict]:
    """되돌릴 수 있는 백업 목록, 새것부터. 시각(at)은 그 판을 저장한 때(파일 수정 시각, UTC)다.
    episodes 는 화 수(깨진 파일이면 -1), finalized 는 반영한 마지막 화, ep 는 화를 지우기 전 백업이면 지운 화."""
    rows = []
    for fid, kind, f in _backup_files(name):
        try:
            st = f.stat()
        except FileNotFoundError:
            continue
        n_eps, last, title = _brief(f, st)
        m = re.fullmatch(r"before-delete-(\d+)\.json", f.name)
        rows.append({"id": fid, "kind": kind, "at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                     "episodes": n_eps, "finalized": last, "title": title, "ep": int(m.group(1)) if m else None})
    return sorted(rows, key=lambda r: r["at"], reverse=True)


def restore_backup(name: str, fid: str) -> Project:
    """백업 하나(fid 는 backup_list 의 id)로 작품을 되돌린다. 지금 판은 먼저 backups/before-restore.<시각>.json 으로 남긴다.
    backup_list 에 없는 id 는 FileNotFoundError."""
    found = next((f for i, _, f in _backup_files(name) if i == fid), None)
    if found is None or not found.exists():
        raise FileNotFoundError(f"백업이 없어요: {fid}")
    d = project_dir(name)
    with _disk_lock(d):
        p = read_disk(found, home=d)
        seed_ties(p)
        path = d / "project.json"
        if path.exists():
            bdir = d / BACKUP_DIR
            bdir.mkdir(exist_ok=True)
            _hold(path, bdir / f"before-restore.{datetime.now():%Y%m%d-%H%M%S}.json")
            for old in sorted(f for f in bdir.glob("before-restore.*.json") if _RESTORE.match(f.name))[:-RESTORE_KEEP]:
                old.unlink(missing_ok=True)
        save(name, p)
    return p


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
        write_atomic(_pending_path(name), json.dumps(d, ensure_ascii=False, indent=1))
        return d


def save(name: str, p: Project) -> Path:
    cancel.check()  # 멈춘 작업은 저장하지 않는다
    d = project_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "project.json"
    # 판 기록 읽기부터 옛 스냅샷 지우기까지 한 잠금 안에서 한다. 다른 프로세스의 저장이 사이에 끼면
    # 그 저장이 이쪽이 막 쓴(아직 project.json 에 적지 않은) 스냅샷 파일을 지워 작품을 못 읽게 된다
    with _disk_lock(d):
        if path.exists():
            rev, by = _saved_mark(path)
            if writer.get():
                p.edit_rev, p.saved_by = rev + 1, writer.get()
            else:  # 작업이 오래전에 읽은 사본을 저장해도 화면 저장 기록은 디스크 것을 잇는다
                p.edit_rev, p.saved_by = rev, by
            _backup(d, path)  # 직전 판과 시간별 백업을 남긴다
        # 다른 스레드(자동 집필, 백그라운드 작업)가 쓰는 도중에 읽어도 빈 파일을 보지 않게 바꿔치기로 쓴다
        # 들여쓰기 없이 쓴다: 장편은 들여쓰기만으로 1MB 넘게 커지고 저장마다 0.015초 더 걸린다 (2026-11-02 실측)
        refs = _write_snapshots(d, p)  # 스냅샷 파일을 먼저 쓴다. project.json 이 바뀌기 전에는 아무도 새 파일을 적지 않는다
        body = p.model_dump_json(exclude={"snapshots"})
        # 바꿔치기 직전 tmp 의 판을 받는다. 바꿔치기는 inode 와 수정 시각을 그대로 옮기므로 바꾼 뒤 다른 스레드가 또 써도 이 판은 이 내용이다
        # fsync 는 3MB 에 1.4ms 쯤 더 든다 (2026-11-05 실측). 전원이 끊겨도 빈 project.json 이 남지 않게 한다
        st = write_atomic(path, '{"snapshot_files":' + json.dumps(refs) + "," + body[1:], fsync=True)
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
                write_atomic(f, body)
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
    write_atomic(path, b.model_dump_json(indent=2))
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
    write_atomic(path, info.model_dump_json(indent=2))
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
    write_atomic(path, lab.model_dump_json(indent=2))
    return path


def cuelab_episodes(name: str) -> list[int]:
    """큐 시트 실험 파일이 있는 화."""
    d = project_dir(name) / "cuelab"
    return sorted(int(x.stem) for x in d.glob("*.json") if x.stem.isdigit()) if d.exists() else []


def compare_dir(name: str, n: int) -> Path:
    """n화 블라인드 비교본 폴더 (research.compare_dir). projects/<이름>/compare/<화 두 자리>/."""
    return project_dir(name) / "compare" / f"{n:02d}"


# 화 번호로 이름 붙인 바깥 파일: 큐 시트 실험 cuelab/<화>.json, 블라인드 비교본 compare/<화>/.
# 화를 넣거나 빼면 project.json 안의 번호와 함께 옮겨야 다른 화의 실험 · 비교본이 새 번호의 화에 붙지 않는다.
SIDE_REMOVED = "removed"
_SIDE_LABEL = {"cuelab": "큐 시트 실험", "compare": "블라인드 비교본"}


def _side_files(name: str) -> list[tuple[str, int, Path]]:
    """(종류, 화, 경로). cuelab 은 <화>.json 파일, compare 는 <화> 폴더."""
    d = project_dir(name)
    out = []
    if (d / "cuelab").is_dir():
        out += [("cuelab", int(f.stem), f) for f in (d / "cuelab").glob("*.json") if f.stem.isdigit()]
    if (d / "compare").is_dir():
        out += [("compare", int(f.name), f) for f in (d / "compare").iterdir() if f.is_dir() and f.name.isdigit()]
    return out


def _side_path(name: str, kind: str, n: int) -> Path:
    return _cuelab_path(name, n) if kind == "cuelab" else compare_dir(name, n)


def _set_aside(f: Path, n: int, stamp: str) -> Path:
    """f 를 같은 폴더의 removed/<화>.<시각>(.json) 으로 옮긴다. 지우지 않는다."""
    root = f.parent / SIDE_REMOVED
    root.mkdir(exist_ok=True)
    dest, i = root / f"{n}.{stamp}{f.suffix}", 1
    while dest.exists():
        dest, i = root / f"{n}.{stamp}-{i}{f.suffix}", i + 1
    os.replace(f, dest)
    return dest


def renumber_side_files(name: str, shift, gone=(), aside: list[str] | None = None) -> list[str]:
    """화를 넣거나 뺀 뒤 큐 시트 실험 · 블라인드 비교본을 새 화 번호로 옮긴다. shift 는 옛 번호 → 새 번호(autorun.renumber 와 같은 규칙).
    gone 화(뺀 화)의 파일은 지우지 않고 removed/<화>.<시각> 으로 남긴다. 옮기는 파일은 임시 이름을 거쳐 서로 덮어쓰지 않는다.
    큐 시트 실험 파일 안의 episode 도 고친다 (save_cuelab 이 그 번호로 쓴다). 무엇을 옮겼는지 설명을 돌려준다.
    aside 를 주면 gone 화의 파일을 남긴 자리(작품 폴더 기준 경로)를 더한다 (restore_side_files 로 되돌린다)."""
    gone = set(gone)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    notes: list[str] = []
    moving = []
    for kind, n, f in sorted(_side_files(name), key=lambda x: (x[0], x[1])):
        if n in gone:
            dest = _set_aside(f, n, stamp)
            if aside is not None:
                aside.append(dest.relative_to(project_dir(name)).as_posix())
            notes.append(f"뺀 {n}화의 {_SIDE_LABEL[kind]}은 {kind}/{SIDE_REMOVED}/{dest.name} 으로 남겨 뒀어요.")
            continue
        new = shift(n)
        if new != n:
            tmp = f.with_name(f".renum-{n}{f.suffix}")
            os.replace(f, tmp)
            moving.append((kind, n, new, tmp))
    for kind, n, new, tmp in moving:
        dest = _side_path(name, kind, new)
        if dest.exists():  # 옮길 자리에 남은 파일이 있으면 덮지 않고 따로 둔다
            _set_aside(dest, new, stamp)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
        if kind == "cuelab":
            try:
                data = json.loads(dest.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if isinstance(data, dict):
                data["episode"] = new
                write_atomic(dest, json.dumps(data, ensure_ascii=False, indent=2))
    for kind in ("cuelab", "compare"):
        pairs = [f"{n}→{new}화" for k, n, new, _ in moving if k == kind]
        if pairs:
            notes.append(f"{_SIDE_LABEL[kind]}도 새 화 번호로 옮겼어요({', '.join(pairs)}).")
    return notes


def restore_side_files(name: str, paths, n: int) -> list[str]:
    """renumber_side_files 가 removed/ 에 남긴 파일(aside 경로)을 n화 자리로 되돌린다. 화 빼기를 되돌릴 때 쓴다.
    그 자리에 이미 파일이 있거나 남긴 파일이 없으면 옮기지 않고 그대로 둔다. 무엇을 했는지 설명을 돌려준다."""
    root = project_dir(name)
    notes: list[str] = []
    for rel in paths:
        parts = Path(rel).parts
        if len(parts) != 3 or parts[0] not in _SIDE_LABEL or parts[1] != SIDE_REMOVED or parts[2].startswith("."):
            continue
        kind, src = parts[0], root.joinpath(*parts)
        dest = _side_path(name, kind, n)
        if not src.exists():
            continue
        if dest.exists():
            notes.append(f"{n}화 자리에 {_SIDE_LABEL[kind]}이 이미 있어서 {rel} 은 그대로 뒀어요.")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dest)
        if kind == "cuelab":
            try:
                data = json.loads(dest.read_text(encoding="utf-8"))
            except ValueError:
                data = None
            if isinstance(data, dict) and data.get("episode") != n:
                data["episode"] = n
                write_atomic(dest, json.dumps(data, ensure_ascii=False, indent=2))
        notes.append(f"{n}화의 {_SIDE_LABEL[kind]}도 {rel} 에서 되돌렸어요.")
    return notes

def backup_path(name: str, tag: str) -> Path:
    return project_dir(name) / f"{tag}.json"


def save_backup(name: str, tag: str, p: Project) -> Path:
    """되돌리기용으로 작품 전체를 따로 남긴다 (예: 단편 → 장편 전환 직전, tag='before-serial')."""
    path = backup_path(name, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, p.model_dump_json(indent=2), fsync=True)  # 되돌리기의 유일한 판이라 디스크까지 내린다
    return path


def load_backup(name: str, tag: str) -> Project | None:
    path = backup_path(name, tag)
    if not path.exists():
        return None
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def drop_backup(name: str, tag: str) -> None:
    backup_path(name, tag).unlink(missing_ok=True)
