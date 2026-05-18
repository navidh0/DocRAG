from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth import get_user_model
from django.db.models import F
from celery.result import AsyncResult

from documents.selectors import document_exists_for_user
from qa.exceptions import QAServiceError, QuestionActivityNotFoundError
from qa.selectors import QuestionActivityListFilters, question_activity_list
from qa.models import QuestionActivity

if TYPE_CHECKING:
    from accounts.models import User

class QuestionActivityCreateService:
    @staticmethod
    def execute(
        *,
        user_id: str,
        doc_id: str | None,
        question: str,
        answer: str,
        sources: list,
        response_time_ms: int,
        status: str,
        task_id: str | None = None,
    ) -> QuestionActivity:
        return QuestionActivity.objects.create(
            user_id=user_id,
            document_id=doc_id,
            question=question,
            answer=answer,
            sources=sources,
            response_time_ms=response_time_ms,
            status=status,
            task_id=task_id,
        )
        
class IncrementQuestionCountService:
    @staticmethod
    def execute(*, user_id: str) -> None:
        get_user_model().objects.filter(id=user_id).update(
            question_count=F("question_count") + 1
        )


class GetQuestionResultService:
    @staticmethod
    def execute(*, task_id: str) -> dict:
        result = AsyncResult(task_id)

        if result.state in ("PENDING", "STARTED"):
            return {"task_id": task_id, "status": "processing"}

        if result.state == "SUCCESS":
            return {"task_id": task_id, **result.result}

        if result.state == "FAILURE":
            raise QAServiceError(
                "Question processing failed.",
                status_code=500,
                details={"error": str(result.result)},
            )

        raise QAServiceError(
            f"Unexpected task state: {result.state}",
            status_code=500,
            details={"task_id": task_id, "state": result.state},
        )


class QuestionActivityListService:
    @staticmethod
    def execute(*, user: User, filters: QuestionActivityListFilters | None = None):
        raw: dict[str, Any] = cast(dict[str, Any], filters) if filters else {}
        doc_id = raw.get("document_id")

        if doc_id and not document_exists_for_user(doc_id=doc_id, user=user):
            raise QuestionActivityNotFoundError(
                "Document not found or does not belong to you.",
                details={"document_id": str(doc_id)},
            )

        return question_activity_list(user=user, filters=filters)