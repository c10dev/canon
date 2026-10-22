"""canon/style_background.py 만들기. 저작권 만료 작가 코퍼스(fetch_corpus.py)의 2,000자 조각으로
어절 끝 특징 상위 300개의 평균과 표준편차를 잰다. 문체 거리는 이 값으로 특징을 정규화한다.

python scripts/make_style_background.py <코퍼스 폴더> > canon/style_background.py
코퍼스 폴더는 <작가>/<작품>.txt 구조다 (문체 반영도 연구의 fetch_corpus.py 가 위키문헌에서 받는다).
"""
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

TOP = 300


def chunks(text, size=2000):
    out, cur = [], ""
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        cur = f"{cur}\n\n{para}" if cur else para
        if len(cur) >= size:
            out.append(cur)
            cur = ""
    return out


def suffix_counts(t):
    c = Counter()
    for w in re.findall(r"[가-힣]+", t):
        c["1:" + w[-1]] += 1
        if len(w) >= 2:
            c["2:" + w[-2:]] += 1
    return c


root = Path(sys.argv[1])
authors = sorted(d.name for d in root.iterdir() if d.is_dir())
counts = [suffix_counts(c) for d in sorted(root.iterdir()) if d.is_dir()
          for f in sorted(d.glob("*.txt")) for c in chunks(f.read_text(encoding="utf-8"))]
tot = Counter()
for c in counts:
    tot.update(c)
vocab = [k for k, _ in tot.most_common(TOP)]
rows = [[c[k] / (sum(c.values()) or 1) for k in vocab] for c in counts]
cols = list(zip(*rows))
print('"""문체 거리(metrics.style_distance)의 정규화 기준. 자동 생성 파일이라 직접 고치지 않는다.')
print()
print(f"저작권 만료 근대 소설 작가 {len(authors)}명({', '.join(authors)})의 2,000자 조각 {len(counts)}개에서")
print(f"어절 끝 1~2음절 특징 상위 {TOP}개의 상대 빈도 평균과 표준편차를 쟀다. 만든 방법: scripts/make_style_background.py")
print('"""')
print("# (특징, 평균, 표준편차). '1:다' 는 어절 끝 한 음절, '2:었다' 는 두 음절")
print("FEATURES: list[tuple[str, float, float]] = [")
for k, col in zip(vocab, cols):
    print(f"    ({k!r}, {statistics.fmean(col):.6f}, {statistics.pstdev(col):.6f}),")
print("]")
