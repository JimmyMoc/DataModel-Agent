from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.api.routes import router as chat_router
from app.rag.loader import load_knowledge_base


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida: inicio y apagado del servicio."""
    # Startup
    print(f" {settings.app_name} El orquestador está arrancando...")
    print(f"   Ollama: {settings.ollama_base_url}")
    print(f"   Model: {settings.ollama_model}")
    print(f"   DB: {settings.database_url.split('@')[1] if '@' in settings.database_url else 'configurado'}")

    # Cargar base de conocimiento RAG (solo la primera vez)
    try:
        await load_knowledge_base()
    except Exception as e:
        print(f" Error cargando knowledge base (continuando sin RAG): {e}")

    yield

    # Apagando
    await engine.dispose()
    print(" El orquestador se está cerrando ")


app = FastAPI(
    title="Data Model Agent - Orchestrator",
    description=(
        "Agente especializado que convierte lenguaje natural en esquemas "
        "de base de datos validados mediante ejecución real de migraciones."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enrutadores
app.include_router(chat_router)


# ─── Health Check ────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    """Health check con verificación de dependencias."""
    status = {
        "status": "healthy",
        "service": "orchestrator",
        "ollama_available": False,
        "db_available": False,
    }

    # Verificar Ollama
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            status["ollama_available"] = resp.status_code == 200
    except Exception:
        pass

    # Verificar PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            status["db_available"] = True
    except Exception:
        pass

    # Si alguna dependencia no está disponible, marcar como degradado
    if not status["ollama_available"] or not status["db_available"]:
        status["status"] = "degraded"

    return status
