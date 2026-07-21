from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Configuración central del orquestador."""

    # Base de datos principal
    database_url: str = "postgresql+asyncpg://dma_user:dma_secret@postgres:5432/dma_main"

    # Base de datos de prueba (donde se validan migraciones)
    test_database_url: str = "postgresql+asyncpg://dma_user:dma_secret@postgres:5432/dma_test"

    # Ollama
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2"

    # Embedding model (para RAG)
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # App
    app_name: str = "Data Model Agent"
    debug: bool = True

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
