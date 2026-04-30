from rest_framework.views import exception_handler
from rest_framework.response import Response
from documents.services import DocumentsServicesError
from qa.exceptions import QAServiceError


def custom_exception_handler(exc, context):
    if isinstance(exc, DocumentsServicesError):
        return Response(
            {"error": exc.message, "details": exc.details},
            status=exc.status_code,
        )
    

    if isinstance(exc, QAServiceError):
            return Response(
                {"error": exc.message, "details": exc.details},
                status=exc.status_code,
            )

    return exception_handler(exc, context)