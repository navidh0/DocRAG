from __future__ import annotations

from core.exceptions import AppError
from rest_framework import status


class QAServiceError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST

class EmbeddingGenerationError(QAServiceError):
    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE


class DocumentRetrievalError(QAServiceError):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR


class RerankingError(QAServiceError):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR


class QuestionActivityNotFoundError(QAServiceError):
    status_code: int = status.HTTP_404_NOT_FOUND
    
class OllamaUnavailableError(QAServiceError):
    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE