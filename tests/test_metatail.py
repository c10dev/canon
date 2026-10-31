"""본문 앞뒤 작업 설명 떼기 (canon/metatail.py, pipeline._write · style_drift). LLM 은 가짜로 바꾼다."""
import pytest

from canon import metatail, pipeline

BODY = "\n\n".join([
    "코미는 복도 한가운데 그대로 서 있었다.",
    "딸기 우유 캔을 쥔 손가락에 하얗게 힘이 들어갔다.",
    "\"…코미 양?\" 타다노가 불렀다.",
    "차가운 물방울이 캔 표면을 타고 손목으로 흘러내렸다.",
])
TAIL = ("마지막으로 짚어 둘 것이 있습니다. 스타일 프로필은 시점을 주인공에게 고정하라고 하지만, "
        "마지막 장면만큼은 다른 쪽 장면으로 넘어가 썼습니다.")


def test_strips_trailing_note_and_preamble():
    body, cut = metatail.split(BODY + "\n\n" + TAIL)
    assert body == BODY and cut == [TAIL]
    body, cut = metatail.split("네, 25화 본문입니다.\n\n" + BODY)
    assert body == BODY and cut == ["네, 25화 본문입니다."]
    body, cut = metatail.split(BODY + "\n\n---\n\n" + "요청하신 분량에 맞춰 작성했습니다. 원하시면 다음 화도 써 드릴게요.")
    assert body == BODY and len(cut) == 2  # 구분선도 함께 뗀다


def test_keeps_story_paragraphs():
    # 따옴표 대사는 작업 낱말이 있어도 그대로
    quoted = BODY + "\n\n\"이번 화 원고는 내일까지 보내 주세요.\" 편집자가 말했습니다."
    assert metatail.split(quoted) == (quoted, [])
    # 존댓말로 끝나도 작업 낱말이 없으면 그대로 (편지 · 다짐)
    letter = BODY + "\n\n어머니께. 저는 잘 지내고 있습니다. 곧 찾아뵙겠습니다."
    assert metatail.split(letter) == (letter, [])
    # 서술이 원래 존댓말인 작품은 작업 낱말 하나로는 떼지 않는다
    tale = "\n\n".join(["옛날 옛적에 한 소년이 살았습니다.", "소년은 매일 산에 올랐답니다.",
                        "어느 날 소년은 이상한 돌을 주웠어요.", "그 돌이 이번 화의 주인공이랍니다."])
    assert metatail.split(tale) == (tale, [])
    # 본문 가운데는 보지 않는다
    middle = "\n\n".join([BODY, TAIL, BODY])
    assert metatail.split(middle) == (middle, [])
    assert metatail.split("짧은 글이에요.") == ("짧은 글이에요.", [])


MID = "\n\n".join(["비가 그쳤다. 골목은 젖은 냄새로 가득했다.", "윤서는 우산을 접고 계단을 올랐다. 문 앞에 작은 상자가 놓여 있었다.",
                   "상자 안에는 낡은 만년필 하나가 들어 있었다."])


@pytest.mark.parametrize("edge", [
    "선생님, 보내 주신 원고는 잘 받았습니다. 다음 화도 기다리겠습니다.",  # 편지
    "이것으로 이 이야기는 끝입니다. 여러분이 원하시면 언젠가 또 들려 드리죠.",  # 이야기꾼의 맺음말
    "띠링. 메인 퀘스트 ‘첫 원고’를 완료했습니다. 보상이 지급됩니다.",  # 시스템 알림
    "[퀘스트 완료: 이번 화의 목표를 달성했습니다]",
    "그는 고개를 숙였다. “작가님, 원고는 내일까지 드릴게요. 정말이에요.”",  # 서술 뒤 대사
    "— 원하시면 그렇게 하세요. 저는 상관없어요.",  # 줄표 대사
    "오후 내내 기획서 초안을 수정했어요. 팀장님이 원하시면 또 고쳐 드려야죠.",  # 해요체 서술
])
def test_keeps_in_story_endings(edge):
    for text in (MID + "\n\n" + edge, edge + "\n\n" + MID):
        assert metatail.split(text) == (text, []), edge
    assert not metatail.whole(MID + "\n\n" + edge)


@pytest.mark.parametrize("head", ["다음은 원고 차례였다. 편집장은 서류철을 넘겼다.", "아래는 그가 남긴 초안의 첫 문장이다.",
                                  "네, 이번 화 마감은 지켰어요. 윤서는 전화를 끊었다."])
def test_keeps_story_openings(head):
    text = head + "\n\n" + MID
    assert metatail.split(text) == (text, [])


def test_strips_memo_block_english_note_and_colon_preamble():
    memo = MID + "\n\n## 작가 메모\n\n- 시점을 타다노에게 고정했어요.\n\n- 분량은 약 5,200자예요."
    assert metatail.split(memo) == (MID, ["## 작가 메모", "- 시점을 타다노에게 고정했어요.", "- 분량은 약 5,200자예요."])
    assert metatail.split(MID + "\n\nNote: I kept the POV on Tadano as requested.")[0] == MID
    assert metatail.split("25화 본문:\n\n" + MID)[0] == MID
    lines = "비가 그쳤다.\n윤서는 계단을 올랐다.\n상자가 있었다.\n마지막으로 짚어 둘 것이 있습니다. 스타일 프로필을 따랐습니다."
    assert metatail.split(lines)[0] == "비가 그쳤다.\n윤서는 계단을 올랐다.\n상자가 있었다."  # 빈 줄 없는 글은 줄 단위


def test_whole_refusal_and_warnings():
    refusal = "\n\n".join([
        "이번 화는 쓰기 어렵습니다. 플롯의 핵심 장면을 그대로 그릴 수 없습니다.",
        "대신 아래 방향이라면 같은 분량과 문체로 바로 쓸 수 있습니다.",
        "1. 대련 장면 위주로 쓰기",
        "원하시는 방향을 알려 주시면 그에 맞춰 본문만 출력하겠습니다.",
    ])
    assert metatail.whole(refusal)
    assert metatail.whole("죄송하지만 이 장면은 쓸 수 없습니다. 다른 방향으로 쓸까요?")  # 한 문단 거절
    writer_story = "\n\n".join(["편집장은 원고를 넘겼다. 다음 화 마감은 사흘 뒤였다.", "윤서는 초안을 고치며 밤을 새웠다.",
                                   "회차가 쌓일수록 분량 압박도 커졌다.", "작가님이라는 말이 아직도 낯설었다."])
    assert not metatail.whole(writer_story)  # 작가물 서술
    assert not metatail.whole(BODY) and not metatail.whole(BODY + "\n\n" + TAIL)
    # 존댓말 조건이 모자라 떼지 않은 작업 낱말 문단은 경고만
    soft = BODY + "\n\n이번 화 끝. 다음 화에 이어진다."
    assert metatail.split(soft)[1] == []
    assert metatail.warnings(soft) == ["이번 화 끝. 다음 화에 이어진다."]
    assert metatail.warnings(BODY) == []


class _Seq:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def text(self, system, prompt):
        self.calls += 1
        return self.replies.pop(0)


@pytest.fixture()
def project():
    from canon.schema import Episode, EpisodePlot, Project
    p = Project()
    p.episodes = [Episode(plot=EpisodePlot(number=1, act="기", title="t", summary="s", events=["e"], characters=[],
                                           emotional_shift="", ending_hook=""), status="confirmed")]
    return p


def test_write_strips_tail_and_retries_whole(project):
    refusal = "\n\n".join(["이번 화는 쓰기 어렵습니다. 플롯을 그대로 쓸 수 없습니다.",
                           "원하시면 다른 방향으로 본문을 써 드릴게요.", "알려 주세요."])
    llm = _Seq([refusal, BODY + "\n\n" + TAIL])
    assert pipeline._write(llm, project, 1, "쓰기") == BODY and llm.calls == 2
    llm = _Seq([refusal] * pipeline.WRITE_TRIES)
    with pytest.raises(ValueError, match="작업 설명이나 거절 문구 3번"):
        pipeline._write(llm, project, 1, "쓰기")


def test_style_drift_warns_soft_tail(project):
    project.episode(1).text = BODY + "\n\n이번 화 끝. 다음 화에 이어진다."
    _, warns = pipeline.style_drift(project, 1)
    assert any(w.startswith("본문이 아닌 작업 설명처럼 보이는 앞뒤 문단 1개") for w in warns)
    project.episode(1).text = BODY
    assert not any("작업 설명" in w for w in pipeline.style_drift(project, 1)[1])
