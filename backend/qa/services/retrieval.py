from __future__ import annotations

from django.conf import settings
from langchain_postgres import PGVector

from core.utils import get_vector_store_connection
from documents.selectors import completed_document_ids_for_user


def retrieve_documents(
    *,
    query_vector: list[float],
    user_id: str,
    doc_id: str | None = None,
    k: int,
    page_filter: int | None = None,
) -> list:
    """
    Single source of truth for vector retrieval.
    Used by both ProcessQuestionService (Celery) and StreamQuestionService.

    page_filter is 1-based (as received from the API); converted to 0-based
    internally before the DB filter is applied, consistent with how pages are
    stored in PGVector metadata.
    """
    store = PGVector(
        collection_name="rag_collection",
        connection=get_vector_store_connection(),
        embeddings=None,  # type: ignore
        use_jsonb=True,
    )

    if doc_id:
        search_filter: dict = {
            "user_id": str(user_id),
            "document_id": str(doc_id),
        }
        if page_filter is not None:
            search_filter["page"] = int(page_filter) - 1  # API is 1-based, DB is 0-based
        return store.similarity_search_by_vector(
            embedding=query_vector,
            k=k,
            filter=search_filter,
        )

    docs = []
    for d_id in completed_document_ids_for_user(user_id=user_id):
        docs.extend(
            store.similarity_search_by_vector(
                embedding=query_vector,
                k=settings.TOP_K_CHUNKS_PER_DOC,
                filter={
                    "user_id": str(user_id),
                    "document_id": str(d_id),
                },
            )
        )
    return docs