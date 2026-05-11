from rest_framework.views import exception_handler
from rest_framework.response import Response
from qa.exceptions import QAServiceError
from documents.exceptions import DocumentsServicesError

_HANDLED = (DocumentsServicesError, QAServiceError)

def custom_exception_handler(exc, context):
    if isinstance(exc, _HANDLED):
        return Response(
            {"error": exc.message, "details": exc.details},
            status=exc.status_code,
        )
    return exception_handler(exc, context)