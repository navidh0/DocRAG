from __future__ import annotations

from celery import shared_task


@shared_task(bind=True)
def process_question_task(
    self,
    question: str,
    user_id: str,
    doc_id: str | None,
    page_filter: int | None,
) -> dict:
    from qa.services.process import ProcessQuestionService

    return ProcessQuestionService.execute(
        question=question,
        user_id=user_id,
        doc_id=doc_id,
        page_filter=page_filter,
        task_id=self.request.id,
    )