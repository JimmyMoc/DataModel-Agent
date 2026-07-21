"""
Loader: Popula la base de conocimiento RAG al iniciar el servicio.

Se ejecuta una sola vez (verifica si ya hay datos antes de insertar).
"""

from app.rag.engine import rag_engine
from app.rag.knowledge_base import KNOWLEDGE_BASE


async def load_knowledge_base() -> int:
    """
    Cargar la base de conocimiento en pgvector.

    Returns:
        Número de documentos cargados (0 si ya existían)
    """
    print("🧠 Verificando base de conocimiento RAG...")

    if await rag_engine.is_populated():
        print("ℹ️  Base de conocimiento ya está poblada")
        return 0

    print(f"📚 Cargando {len(KNOWLEDGE_BASE)} documentos en pgvector...")
    count = await rag_engine.populate_knowledge_base(KNOWLEDGE_BASE)
    return count
