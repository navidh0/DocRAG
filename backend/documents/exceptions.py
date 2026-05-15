from __future__ import annotations
from core.exceptions import AppError
from rest_framework import status

class DocumentServicesError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST

class DocumentNotFoundError(DocumentServicesError):
    """Raised when a specific document ID cannot be found."""
    status_code: int = status.HTTP_404_NOT_FOUND

class DocumentProcessingError(DocumentServicesError):
    """Raised when document processing fails (e.g., file format invalid)."""
    status_code: int = status.HTTP_400_BAD_REQUEST
