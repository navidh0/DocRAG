from __future__ import annotations
from typing import TYPE_CHECKING, Any
from rest_framework import status


class QAServiceError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, status_code: int | None = None, details=None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any]= details or {}
        if status_code is not None:
            self.status_code = status_code


class EmbeddingGenerationError(QAServiceError):
    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE


class DocumentRetrievalError(QAServiceError):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR


class RerankingError(QAServiceError):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR


class QuestionActivityNotFoundError(QAServiceError):
    status_code: int = status.HTTP_404_NOT_FOUND