import os

def get_vector_store_connection():
    raw_url = os.getenv("DATABASE_URL", "postgresql://raguser:ragpassword@localhost:5432/ragdb")
    connection = raw_url.replace("postgres://", "postgresql://").replace("postgresql://", "postgresql+psycopg://")
    return connection