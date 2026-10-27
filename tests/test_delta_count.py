"""상태 승인 화면(static/app.js)이 변경안 항목을 빠짐없이 세는지. 화면의 'n건 중'과 반영 확인창의 '0건'이 같은 목록(DELTA_LISTS)을 쓴다."""
import json
import re
import shutil
import subprocess
import typing
from pathlib import Path

import pytest

from canon.schema import StateDelta

APP = Path(__file__).resolve().parent.parent / "canon" / "static" / "app.js"


def _source(name):
    src = APP.read_text(encoding="utf-8")
    m = re.search(rf"^const {name} = .*?;$", src, re.M)
    assert m, f"app.js 에 {name} 가 없어요"
    return m.group(0)


def test_delta_lists_cover_state_delta():
    lists = re.findall(r"'(\w+)'", _source("DELTA_LISTS"))
    want = {k for k, f in StateDelta.model_fields.items() if typing.get_origin(f.annotation) is list} - {"warnings"}
    assert set(lists) == want
    assert len(lists) == len(set(lists))


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_delta_count_counts_clues():
    js = _source("DELTA_LISTS") + "\n" + _source("deltaCount") + """
process.stdout.write(JSON.stringify([
  deltaCount({ foreshadow_clues: [{}, {}] }),
  deltaCount({ new_facts: ['a'], events: [{}], foreshadow_clues: [{}], warnings: ['w'] }),
  deltaCount({}),
]));"""
    run = subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [2, 3, 0]
