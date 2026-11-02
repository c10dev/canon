"""JSON 파일 저장소. projects/<이름>/project.json 하나에 모든 상태를 보관하고,
본문은 읽기 편하도록 episodes/NN.md 로도 내보낸다."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from contextvars import ContextVar
from pathlib import Path

from . import cancel
from .dynamics import seed_ties
from .schema import BranchInfo, CueLab, PlayInfo, Project

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
    p = Project.model_validate_json(path.read_text(encoding="utf-8"))
    seed_ties(p)  # 관계 역학 이전의 project.json 은 affinity 로 방향 관계를 만든다
    _keep(name, _key(st), p)
    return p


def load(name: str) -> Project:
    """작품을 읽는다. 고쳐 써도 되는 사본이다."""
    return load_view(name).model_copy(deep=True)


def _remember(name: str, st: os.stat_result, p: Project) -> None:
    """방금 저장한 작품을 캐시에 둔다 (저장 직후 첫 읽기도 JSON 을 다시 검증하지 않게).
    디스크에서 읽은 것과 같도록 저장한 값을 다시 검증하고 seed_ties 를 거친다 (검증기가 범위를 자르는 칸 등)."""
    fresh = Project.model_validate(p.model_dump())
    seed_ties(fresh)
    _keep(name, _key(st), fresh)


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
    """디스크 작품의 (edit_rev, saved_by). 두 칸은 Project 의 마지막 필드라 파일 끝만 읽는다 (장편도 저장마다 전체를 읽지 않게)."""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 4096))
        tail = f.read().decode("utf-8", errors="ignore")
    m = _MARK.search(tail)
    return (int(m.group(1)), json.loads(m.group(2))) if m else (0, "")


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
        shutil.copy(path, d / "project.prev.json")  # 직전 버전 하나는 남겨 둔다
    # 다른 스레드(자동 집필, 백그라운드 작업)가 쓰는 도중에 읽어도 빈 파일을 보지 않게 바꿔치기로 쓴다
    # 들여쓰기 없이 쓴다: 장편은 들여쓰기만으로 1MB 넘게 커지고 저장마다 0.015초 더 걸린다 (2026-11-02 실측)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(p.model_dump_json(), encoding="utf-8")
    st = tmp.stat()  # 바꿔치기는 inode 와 수정 시각을 그대로 옮긴다. 바꾼 뒤 다른 스레드가 또 써도 이 판은 이 내용이다
    os.replace(tmp, path)
    _remember(name, st, p)
    if (got := saved.get()) is not None:
        got[name] = _tag(st)

    ep_dir = d / "episodes"
    for ep in p.episodes:
        if ep.text:
            ep_dir.mkdir(exist_ok=True)
            f = ep_dir / f"{ep.plot.number:02d}.md"
            body = f"# {ep.plot.number}화. {ep.plot.title}\n\n{ep.text}\n"
            if _md_written.get(f) != (hash(body), _mtime(f)):  # 지난번에 쓴 그대로면 다시 쓰지 않는다
                f.write_text(body, encoding="utf-8")
                _md_written[f] = (hash(body), _mtime(f))
    if ep_dir.is_dir():  # 본문을 지운 화나 빠진 화의 내보낸 파일은 지운다 (NN.md 만, 작가가 둔 다른 파일은 그대로)
        have = {e.plot.number for e in p.episodes if e.text}
        for f in ep_dir.glob("*.md"):
            if f.stem.isdigit() and int(f.stem) not in have:
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
