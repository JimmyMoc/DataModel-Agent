from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import get_settings

settings = get_settings()

# Engine para la BD principal (conversaciones, RAG, esquemas)
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=5,
    max_overflow=10,
)

# Engine para la BD de prueba (validación de migraciones)
test_engine = create_async_engine(
    settings.test_database_url,
    echo=settings.debug,
    pool_size=3,
    max_overflow=5,
)

# Session factories
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
AsyncTestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """Dependency para obtener sesión de BD principal."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_test_db() -> AsyncSession:
    """Dependency para obtener sesión de BD de prueba."""
    async with AsyncTestSession() as session:
        try:
            yield session
        finally:
            await session.close()
