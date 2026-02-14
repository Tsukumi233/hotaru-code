import asyncio

import pytest

from hotaru.question import Question, QuestionInfo, QuestionOption, RejectedError


def _sample_question() -> QuestionInfo:
    return QuestionInfo(
        question="Continue?",
        header="Confirm",
        options=[
            QuestionOption(label="Yes", description="Proceed"),
            QuestionOption(label="No", description="Stop"),
        ],
    )


@pytest.mark.anyio
async def test_question_roundtrip_reply() -> None:
    Question.reset()

    task = asyncio.create_task(
        Question.ask(
            session_id="session_test",
            questions=[_sample_question()],
        )
    )

    await asyncio.sleep(0)
    pending = await Question.list_pending()
    assert len(pending) == 1

    await Question.reply(pending[0].id, [["Yes"]])
    answers = await task
    assert answers == [["Yes"]]


@pytest.mark.anyio
async def test_question_reject_raises() -> None:
    Question.reset()

    task = asyncio.create_task(
        Question.ask(
            session_id="session_test",
            questions=[_sample_question()],
        )
    )

    await asyncio.sleep(0)
    pending = await Question.list_pending()
    assert len(pending) == 1

    await Question.reject(pending[0].id)
    with pytest.raises(RejectedError):
        await task

