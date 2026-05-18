from core.settings.env import env

def get_vector_store_connection() -> str:
    url = env("DATABASE_URL", default="postgresql://raguser:ragpassword@localhost:5432/ragdb")
    return url.replace("postgresql://", "postgresql+psycopg://")