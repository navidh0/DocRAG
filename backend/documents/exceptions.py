from __future__ import annotations
from typing import Any
from rest_framework import status

class DocumentsServicesError(Exception):
    """Base exception class for all document service specific errors."""
    status_code = status.HTTP_400_BAD_REQUEST
    
    def __init__(self, message: str, status_code: int | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        if status_code is not None:
            self.status_code = status_code

class DocumentNotFoundError(DocumentsServicesError):
    """Raised when a specific document ID cannot be found."""
    status_code: int = status.HTTP_404_NOT_FOUND

class DocumentProcessingError(DocumentsServicesError):
    """Raised when document processing fails (e.g., file format invalid)."""
    status_code: int = status.HTTP_400_BAD_REQUEST
