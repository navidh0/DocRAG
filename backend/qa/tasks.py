from __future__ import annotations

from celery import shared_task


@shared_task
def process_question_task(
    question: str,
    user_id: str,
    doc_id: str | None,
    page_filter: int | None,
) -> dict:
    from qa.services.process import ProcessQuestionService  # deferred to avoid circular import

    return ProcessQuestionService.execute(
        question=question,
        user_id=user_id,
        doc_id=doc_id,
        page_filter=page_filter,
    )