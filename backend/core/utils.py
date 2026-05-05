from django.conf import settings

def get_vector_store_connection() -> str:
    return settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")