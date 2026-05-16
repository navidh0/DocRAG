from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from documents.exceptions import DocumentNotFoundError
from documents.selectors import document_exists_for_user

if TYPE_CHECKING:
    from accounts.models import User


class AskQuestionService:
    @staticmethod
    def execute(*, user: User, validated_data: dict) -> dict:
        from qa.tasks import process_question_task  # deferred to avoid circular import

        doc_id = validated_data.get("document_id")

        if doc_id is not None and not document_exists_for_user(doc_id=doc_id, user=user):
            raise DocumentNotFoundError(
                "Document not found or does not belong to you.",
                details={"document_id": str(doc_id)},
            )

        celery_task = cast(Any, process_question_task)
        task = celery_task.delay(
            question=validated_data["question"],
            user_id=str(user.id),
            doc_id=str(doc_id) if doc_id else None,
            page_filter=validated_data.get("page"),
        )
        return {"task_id": str(task.id), "status": "processing"}