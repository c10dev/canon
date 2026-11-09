"""삽화 그리기: 저장한 삽화 프롬프트(Illustration)를 ComfyUI 에 보내 그림을 받아 작품 폴더에 둔다.

LLM 을 부르지 않는다. 사용량 기록(usage.record)은 LLM 토큰만 세므로 여기서는 부르지 않는다.
ComfyUI 는 따로 띄운 서버다 (GPU 서버에서 돌리고 SSH 터널로 잇는다). 주소는 CANON_COMFY_URL, 'mock' 이면 가짜 서버.

워크플로는 ComfyUI 에서 'Export (API)' 로 내보낸 JSON 을 틀로 쓴다 (CANON_COMFY_WORKFLOW). 틀의 글 칸에 적은 자리표를 채운다.
- {{prompt}} · {{negative}}: 긍정 · 부정 프롬프트. "masterpiece, {{prompt}}" 처럼 앞뒤에 고정 태그를 둘 수 있다
- {{seed}} · {{width}} · {{height}}: 칸 값이 자리표 하나뿐이면 정수로 바꾼다
- {{checkpoint}}: CANON_COMFY_CKPT (기본 틀이 쓴다)
- {{main}} · {{char1}} · {{char2}} · {{char3}}: 인물을 영역별로 나눠 그리는 틀(리저널)의 기본 칸과 인물 칸.
  인물이 둘 이상이고 틀에 인물 칸이 둘 이상 있으면 인물을 자리 순(왼쪽 → 오른쪽)으로 인물 칸에 넣고, 기본 칸에는 장면만 둔다.
  그렇지 않으면 기본 칸에 모두 넣고 인물 칸은 비운다. 인물 칸보다 인물이 많으면 남는 인물은 기본 칸에 넣는다
- {{multi:A:B}}: 인물을 인물 칸에 나눠 넣으면 A, 아니면 B (예: 리저널 모드 번호 {{multi:3:1}})
자리표 {{prompt}} 가 없으면 positive · negative 입력을 받는 노드(KSampler 등)를 따라가 그 글 칸(text)을 채우고, seed · noise_seed 칸에 시드를 넣는다.
틀을 정하지 않으면 SDXL 체크포인트 하나로 그리는 기본 틀(DEFAULT_WORKFLOW)을 쓴다.

프롬프트는 NovelAI 용으로 조립한 것(illust.assemble)을 SD 태그 한 줄로 옮긴다(prompt_of).
- 인물 칸이 없는 틀에는 인물 칸을 한 줄로 합친다. 인물 칸의 girl / boy / other 는 인물 수 태그(1girl 등)와 겹쳐 뺀다
- 가중치 1.2::tag :: 는 (tag:1.2), {tag} · [tag] 는 1.05 배씩 · 1/1.05 배씩으로. 0 이하 가중치 태그는 뺀다
- source# · target# · mutual# 를 뗀다. 태그 속 괄호는 \\( \\) 로 막는다
- rating:general · sensitive · explicit 는 같은 낱말, questionable 은 nsfw 로 (Danbooru 등급 태그)
- '품질 태그 직접 넣기' 로 붙은 NovelAI 품질 태그는 뺀다 (모델마다 달라 틀에 적는다)
"""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import cancel, illust, store
from .schema import Illustration, IllustImage, Project

DEFAULT_SIZE = (832, 1216)
DEFAULT_TIMEOUT = 600  # 그림 하나를 기다리는 초
IMAGES_KEEP = 8  # 삽화 프롬프트 하나에 남기는 그림 수
FOLDER = "illust"  # 작품 폴더 안 그림 폴더
_FILE = re.compile(r"^[0-9a-f]{16}\.png$")
CLIENT = "canon"

# SDXL 체크포인트 하나로 그리는 기본 틀 (ComfyUI API 형식)
DEFAULT_WORKFLOW: dict = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{{checkpoint}}"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{negative}}", "clip": ["4", 1]}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": "{{width}}", "height": "{{height}}", "batch_size": 1}},
    "3": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}", "steps": 28, "cfg": 5.0, "sampler_name": "euler_ancestral",
                                               "scheduler": "normal", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0],
                                               "negative": ["7", 0], "latent_image": ["5", 0]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "canon", "images": ["8", 0]}},
}

_RATING = {"general": "general", "sensitive": "sensitive", "questionable": "nsfw", "explicit": "explicit"}
_WEIGHT = re.compile(r"^(-?\d+(?:\.\d+)?)::(.*?)(?:::)?$")
_BRACE = re.compile(r"^(\{+|\[+)(.*?)(\}+|\]+)$")
_ACT = re.compile(r"^(source|target|mutual)#")
_SLOT = re.compile(r"\{\{(\w+)\}\}")
_MULTI = re.compile(r"\{\{multi:([^:{}]*):([^:{}]*)\}\}")
_CHAR_SLOT = re.compile(r"\{\{char([1-9])\}\}")
_ORDER = {"왼쪽": 0, "가운데": 1, "": 1, "오른쪽": 2}  # 인물 칸에 넣는 차례 (illust.POSITIONS 의 이름)
_SUBJECT = {"girl", "boy", "other"}


class ComfyError(RuntimeError):
    """ComfyUI 에 닿지 않거나 ComfyUI 가 그리지 못했다."""


# ---------- 설정 ----------

def url() -> str:
    return os.environ.get("CANON_COMFY_URL", "").strip()


def size() -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+)\s*", os.environ.get("CANON_COMFY_SIZE", ""))
    return (int(m[1]), int(m[2])) if m else DEFAULT_SIZE


def timeout() -> float:
    try:
        return float(os.environ.get("CANON_COMFY_TIMEOUT", "") or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT


def status() -> dict:
    """화면이 그리기 버튼을 보일지 정하는 값. ComfyUI 에 묻지 않는다 (꺼져 있으면 그리기 작업이 알린다)."""
    path = os.environ.get("CANON_COMFY_WORKFLOW", "").strip()
    return {"on": bool(url()), "mock": url() == "mock", "workflow": Path(path).name if path else "",
            "checkpoint": os.environ.get("CANON_COMFY_CKPT", "").strip()}


def template() -> dict:
    """워크플로 틀. CANON_COMFY_WORKFLOW 파일, 없으면 기본 틀."""
    path = os.environ.get("CANON_COMFY_WORKFLOW", "").strip()
    if not path:
        return copy.deepcopy(DEFAULT_WORKFLOW)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ComfyError(f"ComfyUI 워크플로 파일을 읽지 못했어요({path}): {e}") from e
    except ValueError as e:
        raise ComfyError(f"ComfyUI 워크플로 파일이 JSON이 아니에요({path}): {e}") from e
    if isinstance(data, dict) and "nodes" in data and "links" in data:
        raise ComfyError("ComfyUI 화면용 워크플로예요. ComfyUI 메뉴의 'Export (API)'로 내보낸 JSON을 쓰세요")
    if not isinstance(data, dict) or not all(isinstance(v, dict) and "class_type" in v for v in data.values()):
        raise ComfyError("ComfyUI API 형식 워크플로가 아니에요. 'Export (API)'로 내보낸 JSON을 쓰세요")
    return data


# ---------- 프롬프트 ----------

def _split(text: str) -> list[str]:
    return [t.strip() for t in str(text or "").split(",") if t.strip()]


def sd_tag(tag: str) -> str:
    """NovelAI 태그 하나를 SD(ComfyUI) 태그로. 뺄 태그는 빈 글."""
    t = tag.strip()
    w: float | None = None
    m = _WEIGHT.match(t)
    if m:
        w, t = float(m[1]), m[2].strip()
    else:
        b = _BRACE.match(t)
        if b and len(b[1]) == len(b[3]) and b[1][0] + b[3][0] in ("{}", "[]"):
            k = len(b[1])
            w, t = round(1.05 ** k if b[1][0] == "{" else 1.05 ** -k, 2), b[2].strip()
    t = _ACT.sub("", t.replace("::", "").strip()).strip()
    if not t or (w is not None and w <= 0):
        return ""
    t = t.replace("(", r"\(").replace(")", r"\)")
    return f"({t}:{w:g})" if w is not None and w != 1 else t


@dataclass
class Parts:
    """SD 태그로 옮긴 삽화 프롬프트 조각. base 는 인물 수 · 화풍 · 장면 · 등급, chars 는 자리 순 인물 태그."""
    base: list[str] = field(default_factory=list)
    chars: list[list[str]] = field(default_factory=list)
    caption: str = ""
    negative: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    people: int = 0  # 그림에 보이는 인물 수 (인물 칸이 없는 V3 로 조립했어도 센다)

    def main(self, extra: list[list[str]] | None = None) -> str:
        """기본 칸 글. extra 는 기본 칸에 함께 넣을 인물 태그."""
        out: list[str] = []
        for t in self.base + [t for c in (extra or []) for t in c]:
            if t not in out:
                out.append(t)
        return ", ".join(out + ([self.caption] if self.caption else []))

    def flat(self) -> str:
        return self.main(self.chars)


def _sd_tags(raw: list[str], quality: set[str]) -> tuple[list[str], int]:
    """NovelAI 태그 목록을 SD 태그 목록으로. (태그, 뺀 0 이하 가중치 수)."""
    out: list[str] = []
    dropped = 0
    for t in raw:
        low = t.lower()
        if low in _SUBJECT or low in quality:
            continue
        if low.startswith("rating:"):
            t = _RATING.get(low.split(":", 1)[1].strip(), "")
            if not t:
                continue
        tag = sd_tag(t)
        if not tag:
            dropped += 1
        elif tag not in out:
            out.append(tag)
    return out, dropped


def parts_of(p: Project, ill: Illustration) -> Parts:
    """저장한 삽화 프롬프트를 SD 태그 조각으로 옮긴다."""
    caption = ill.draft.caption.strip().rstrip(".")
    caption = caption if caption and caption in ill.base else ""  # 영어 문장을 넣는 모델로 조립했을 때만
    quality = set(_split(illust.model_info(ill.model)[1])) if p.illust.quality else set()
    base, dropped = _sd_tags([t for t in _split(ill.base) if not caption or t not in _split(caption)], quality)
    ordered = sorted(ill.characters, key=lambda cp: _ORDER.get(cp.position, 1))
    chars: list[list[str]] = []
    for cp in ordered:
        tags, k = _sd_tags(_split(cp.prompt), quality)
        dropped += k
        if tags:
            chars.append(tags)
    neg: list[str] = []
    for t in _split(ill.negative) + [t for cp in ill.characters for t in _split(cp.negative)]:
        tag = sd_tag(t)
        if tag and tag not in neg:
            neg.append(tag)
    notes = [f"가중치가 0 이하인 태그 {dropped}개는 ComfyUI에 보내지 않았어요"] if dropped else []
    people = len([c for c in ill.draft.characters if c.id or c.subject])
    return Parts(base=base, chars=chars, caption=caption.replace("(", r"\(").replace(")", r"\)"),
                 negative=neg, notes=notes, people=people)


MIXED = "ComfyUI에는 인물을 나눠 넣지 않고 한 줄로 합쳐 보내요. 인물 외형이 섞일 수 있어요"


def prompt_of(p: Project, ill: Illustration) -> tuple[str, str, list[str]]:
    """저장한 삽화 프롬프트를 (긍정, 부정, 알릴 것) SD 태그 한 줄로 옮긴다 (인물 칸이 없는 틀)."""
    parts = parts_of(p, ill)
    return parts.flat(), ", ".join(parts.negative), parts.notes + ([MIXED] if parts.people > 1 else [])


# ---------- 워크플로 ----------

def _fill(node, slots: dict, found: set):
    if isinstance(node, dict):
        return {k: _fill(v, slots, found) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, slots, found) for v in node]
    if isinstance(node, str) and "{{" in node:
        def pick(m: re.Match) -> str:
            found.add("multi")
            return m[1] if slots.get("multi") else m[2]
        multi = _MULTI.fullmatch(node.strip())
        if multi:
            v = pick(multi)
            return int(v) if v.strip().lstrip("-").isdigit() else v
        node = _MULTI.sub(pick, node)
        whole = _SLOT.fullmatch(node.strip())
        if whole and whole[1] in slots and isinstance(slots[whole[1]], int):
            found.add(whole[1])
            return slots[whole[1]]

        def put(m: re.Match) -> str:
            if m[1] not in slots:
                return m[0]
            found.add(m[1])
            return str(slots[m[1]])
        return _SLOT.sub(put, node)
    return node


def workflow(positive: str, negative: str, seed: int, tpl: dict | None = None) -> dict:
    """틀에 한 줄 프롬프트 · 시드 · 크기를 채운 ComfyUI API 워크플로 (인물을 나누지 않는다)."""
    return fill(Parts(base=[positive] if positive else [], negative=[negative] if negative else []), seed, tpl)[0]


def fill(parts: Parts, seed: int, tpl: dict | None = None) -> tuple[dict, str, list[str]]:
    """틀에 프롬프트 조각 · 시드 · 크기를 채운다. (ComfyUI API 워크플로, 보낸 긍정 프롬프트 요약, 알릴 것)."""
    tpl = template() if tpl is None else tpl
    w, h = size()
    negative = ", ".join(parts.negative)
    notes = list(parts.notes)
    slot_n = len(set(_CHAR_SLOT.findall(json.dumps(tpl, ensure_ascii=False))))
    regional = slot_n >= 2 and len(parts.chars) >= 2
    if regional:
        put, extra = parts.chars[:slot_n], parts.chars[slot_n:]
        main = parts.main(extra)
        if extra:
            notes.append(f"인물 칸이 {slot_n}개라 뒤의 {len(extra)}명은 기본 칸에 넣었어요. 외형이 섞일 수 있어요")
        sent = " | ".join([main] + [", ".join(c) for c in put])
    else:
        put, main = [], parts.flat()
        sent = main
        if parts.people > 1:
            notes.append(MIXED)
    slots: dict = {"prompt": parts.flat(), "main": main, "negative": negative, "seed": seed, "width": w, "height": h,
                   "checkpoint": os.environ.get("CANON_COMFY_CKPT", "").strip(), "multi": regional}
    for i in range(1, 10):
        slots[f"char{i}"] = ", ".join(put[i - 1]) if i <= len(put) else ""
    found: set[str] = set()
    wf = _fill(tpl, slots, found)
    if "checkpoint" in found and not slots["checkpoint"]:
        raise ComfyError("기본 워크플로는 체크포인트 이름이 필요해요. CANON_COMFY_CKPT에 ComfyUI models/checkpoints의 파일 이름을 적으세요")
    if found & {"prompt", "main"}:
        return wf, sent, notes
    positive = parts.flat()
    # 자리표가 없는 틀: positive · negative 입력을 따라가 글 칸을 채운다
    filled = False
    for node in wf.values():
        ins = node.get("inputs", {})
        for key, text in (("positive", positive), ("negative", negative)):
            link = ins.get(key)
            src = wf.get(str(link[0])) if isinstance(link, list) and link else None
            if src and isinstance(src.get("inputs", {}).get("text"), str):
                src["inputs"]["text"] = text
                filled = filled or key == "positive"
        for key in ("seed", "noise_seed"):
            if isinstance(ins.get(key), int):
                ins[key] = seed
    if not filled:
        raise ComfyError("워크플로에서 프롬프트 칸을 찾지 못했어요. 긍정 프롬프트 칸에 {{prompt}}, 부정 칸에 {{negative}}를 적어 두세요")
    return wf, positive, notes


# ---------- ComfyUI 호출 ----------

def _http(method: str, path: str, body: dict | None = None, wait: float = 30) -> bytes:
    base = url()
    if not base:
        raise ComfyError("ComfyUI 주소가 없어요. CANON_COMFY_URL에 ComfyUI 주소를 적으세요 (예: http://127.0.0.1:18188)")
    if base == "mock":
        return _fake(method, path, body)
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=wait) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise ComfyError(f"ComfyUI가 그리기를 받지 않았어요({e.code}): {_reason(e.read())}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        why = getattr(e, "reason", e)
        raise ComfyError(f"ComfyUI에 닿지 않아요({base}). GPU 서버의 ComfyUI와 SSH 터널이 켜져 있는지 보세요: {why}") from e


def _reason(raw: bytes) -> str:
    """ComfyUI 오류 응답에서 사람이 읽을 부분."""
    try:
        d = json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")[:300]
    err = d.get("error") if isinstance(d, dict) else None
    parts = [err.get("message", "") if isinstance(err, dict) else str(err or "")]
    for nid, ne in (d.get("node_errors") or {}).items() if isinstance(d, dict) else []:
        for x in (ne or {}).get("errors", [])[:2]:
            parts.append(f"노드 {nid} {ne.get('class_type', '')}: {x.get('message', '')} {x.get('details', '')}".strip())
    return " / ".join(t for t in parts if t)[:500]


def _drop(pid: str) -> None:
    """멈춘 그리기를 ComfyUI 대기열에서 빼고, 그리는 중이면 끊는다. 실패해도 넘긴다."""
    for path, body in (("/queue", {"delete": [pid]}), ("/interrupt", {})):
        try:
            _http("POST", path, body, wait=5)
        except ComfyError:
            pass


FINAL_TITLES = ("최종", "final")  # 그림을 여러 번 저장하는 틀에서 받을 저장 노드의 제목에 든 낱말


def _image_of(outputs: dict, wf: dict | None = None) -> dict | None:
    """결과에서 받을 그림 하나. 제목에 '최종' · 'final' 이 든 노드, 다음은 저장 노드(type output)를 고른다."""
    def imgs(out) -> list[dict]:
        return [im for im in (out or {}).get("images", []) if isinstance(im, dict)]
    for nid, out in outputs.items():
        title = str(((wf or {}).get(str(nid)) or {}).get("_meta", {}).get("title", "")).lower()
        if any(w in title for w in FINAL_TITLES) and imgs(out):
            return imgs(out)[0]
    every = [im for out in outputs.values() for im in imgs(out)]
    return next((im for im in every if im.get("type") == "output"), every[0] if every else None)


def render(p: Project, ill: Illustration, seed: int | None = None, poll: float = 1.0) -> tuple[bytes, IllustImage]:
    """삽화 프롬프트 하나를 ComfyUI 로 그린다. (PNG, 그림 기록). 저장하지 않는다."""
    parts = parts_of(p, ill)
    if not parts.flat():
        raise ComfyError("ComfyUI에 보낼 프롬프트가 비었어요")
    seed = secrets.randbelow(2 ** 32) if seed is None else seed
    wf, pos, notes = fill(parts, seed)
    neg = ", ".join(parts.negative)
    cancel.check()
    sent = json.loads(_http("POST", "/prompt", {"prompt": wf, "client_id": CLIENT}))
    pid = sent.get("prompt_id")
    if not pid:
        raise ComfyError(f"ComfyUI가 그리기 번호를 주지 않았어요: {_reason(json.dumps(sent).encode())}")
    end = time.monotonic() + timeout()
    try:
        while True:
            cancel.check()
            h = json.loads(_http("GET", f"/history/{urllib.parse.quote(pid)}")).get(pid)
            st = (h or {}).get("status") or {}
            if st.get("status_str") == "error":
                msg = next((m[1].get("exception_message", "") for m in st.get("messages", [])
                            if isinstance(m, list) and len(m) > 1 and m[0] == "execution_error" and isinstance(m[1], dict)), "")
                raise ComfyError(f"ComfyUI가 그리다 멈췄어요: {msg.strip() or '오류 내용 없음'}")
            if h and (st.get("completed") or h.get("outputs")):
                break
            if time.monotonic() > end:
                _drop(pid)
                raise ComfyError(f"ComfyUI가 {int(timeout())}초 안에 그리지 못했어요. 대기열이 길거나 서버가 멈췄을 수 있어요")
            cancel.say("ComfyUI가 그리는 중이에요")
            time.sleep(poll)
    except cancel.Cancelled:
        _drop(pid)
        raise
    im = _image_of(h.get("outputs") or {}, wf)
    if im is None:
        raise ComfyError("ComfyUI가 그림을 내지 않았어요. 워크플로에 그림 저장 노드(SaveImage)가 있는지 보세요")
    q = urllib.parse.urlencode({k: im.get(k, "") for k in ("filename", "subfolder", "type")})
    data = _http("GET", f"/view?{q}", wait=120)
    if not data.startswith(b"\x89PNG"):
        raise ComfyError("ComfyUI가 PNG가 아닌 파일을 돌려줬어요")
    tpl = status()["workflow"] or "기본 틀"
    return data, IllustImage(file="", at=_now(), seed=seed, prompt=pos, negative=neg, workflow=tpl, notes=notes)


# ---------- 작품 폴더 ----------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def folder(name: str) -> Path:
    return store.project_dir(name) / FOLDER


def image_path(name: str, file: str) -> Path:
    """그림 파일 경로. 이름 규칙에 맞지 않으면 KeyError (경로 넘기 막기)."""
    if not _FILE.match(file or ""):
        raise KeyError(f"그림이 없어요: {file}")
    path = folder(name) / file
    if not path.is_file():
        raise KeyError(f"그림이 없어요: {file}")
    return path


def save_image(name: str, data: bytes) -> str:
    d = folder(name)
    d.mkdir(parents=True, exist_ok=True)
    file = f"{secrets.token_hex(8)}.png"
    (d / file).write_bytes(data)
    return file


def find(p: Project, n: int, iid: str) -> Illustration:
    ill = next((x for x in p.episode(n).illustrations if x.id == iid), None)
    if ill is None:
        raise KeyError(f"삽화 프롬프트가 없어요: {iid}")
    return ill


def add_image(p: Project, n: int, iid: str, img: IllustImage) -> None:
    """그림 기록을 삽화에 더한다. 오래된 것부터 IMAGES_KEEP 개만 남긴다 (파일은 prune 이 지운다)."""
    ill = find(p, n, iid)
    ill.images = (ill.images + [img])[-IMAGES_KEEP:]


def remove_image(p: Project, n: int, iid: str, file: str) -> None:
    ill = find(p, n, iid)
    if not any(im.file == file for im in ill.images):
        raise KeyError(f"그림이 없어요: {file}")
    ill.images = [im for im in ill.images if im.file != file]


def prune(name: str, p: Project) -> int:
    """작품 데이터가 가리키지 않는 그림 파일을 지운다 (지운 삽화 · 밀려난 그림). 지운 수."""
    d = folder(name)
    if not d.is_dir():
        return 0
    used = {im.file for e in p.episodes for x in e.illustrations for im in x.images}
    gone = 0
    for f in d.iterdir():
        if _FILE.match(f.name) and f.name not in used:
            f.unlink(missing_ok=True)
            gone += 1
    return gone


# ---------- 가짜 ComfyUI (CANON_COMFY_URL=mock) ----------

_FAKE: dict[str, dict] = {}


def _png(w: int, h: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _fake(method: str, path: str, body: dict | None) -> bytes:
    """ComfyUI 의 /prompt · /history · /view · /queue · /interrupt 를 흉내 낸다. 시드로 색을 정한 작은 PNG 를 준다."""
    if method == "POST" and path == "/prompt":
        wf = (body or {}).get("prompt") or {}
        seeds = [v for node in wf.values() for k, v in node.get("inputs", {}).items() if k in ("seed", "noise_seed") and isinstance(v, int)]
        pid = secrets.token_hex(8)
        _FAKE[pid] = {"seed": seeds[0] if seeds else 0}
        return json.dumps({"prompt_id": pid, "number": len(_FAKE)}).encode()
    if method == "GET" and path.startswith("/history/"):
        pid = urllib.parse.unquote(path.split("/history/", 1)[1])
        if pid not in _FAKE:
            return b"{}"
        out = {"9": {"images": [{"filename": f"canon_{pid}.png", "subfolder": "", "type": "output"}]}}
        return json.dumps({pid: {"status": {"status_str": "success", "completed": True}, "outputs": out}}).encode()
    if method == "GET" and path.startswith("/view?"):
        q = urllib.parse.parse_qs(path.split("?", 1)[1])
        pid = q.get("filename", [""])[0].removeprefix("canon_").removesuffix(".png")
        s = _FAKE.get(pid, {}).get("seed", 0)
        return _png(64, 96, (s % 200 + 40, (s // 7) % 200 + 40, (s // 49) % 200 + 40))
    if method == "POST" and path in ("/queue", "/interrupt"):
        return b"{}"
    raise ComfyError(f"가짜 ComfyUI가 모르는 요청이에요: {method} {path}")
