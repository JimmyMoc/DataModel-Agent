"""
RAG Engine: Embedding + Búsqueda Semántica con pgvector.

Responsabilidades:
- Generar embeddings de texto usando sentence-transformers
- Almacenar y buscar en la tabla knowledge_embeddings
- Proporcionar contexto relevante al agente antes de generar esquemas
"""

import json
from typing import Optional

import numpy as np
from sqlalchemy import text
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal

settings = get_settings()


class RAGEngine:
    """Motor de Retrieval-Augmented Generation con pgvector."""

    def __init__(self):
        self._model: Optional[SentenceTransformer] = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy loading del modelo de embeddings."""
        if self._model is None:
            print(f"📥 Cargando modelo de embeddings: {settings.embedding_model}")
            self._model = SentenceTransformer(settings.embedding_model)
            print("✅ Modelo cargado")
        return self._model

    def embed(self, text: str) -> list[float]:
        """Generar embedding de un texto."""
        embedding = self.model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generar embeddings para múltiples textos."""
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    async def search(
        self,
        query: str,
        limit: int = 5,
        category: Optional[str] = None,
        similarity_threshold: float = 0.3,
    ) -> list[dict]:
        """
        Buscar documentos similares en la base de conocimiento.

        Args:
            query: Texto de búsqueda
            limit: Máximo de resultados
            category: Filtrar por categoría (pattern, antipattern, best_practice)
            similarity_threshold: Umbral mínimo de similitud (0-1)

        Returns:
            Lista de documentos relevantes con score de similitud
        """
        query_embedding = self.embed(query)
        embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"

        # Construir query con filtro opcional
        sql = """
            SELECT 
                content,
                category,
                metadata,
                1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM knowledge_embeddings
            WHERE 1 - (embedding <=> CAST(:embedding AS vector)) > :threshold
        """

        params = {
            "embedding": embedding_str,
            "threshold": similarity_threshold,
        }

        if category:
            sql += " AND category = :category"
            params["category"] = category

        sql += " ORDER BY similarity DESC LIMIT :limit"
        params["limit"] = limit

        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()

        return [
            {
                "content": row[0],
                "category": row[1],
                "metadata": row[2] if isinstance(row[2], dict) else json.loads(row[2]) if row[2] else {},
                "similarity": round(float(row[3]), 4),
            }
            for row in rows
        ]

    async def get_relevant_context(self, user_message: str, limit: int = 5) -> str:
        """
        Obtener contexto relevante formateado para incluir en el prompt del agente.

        Args:
            user_message: Mensaje del usuario (descripción del dominio)
            limit: Máximo de documentos a incluir

        Returns:
            Texto formateado con las buenas prácticas relevantes
        """
        results = await self.search(user_message, limit=limit)

        if not results:
            return ""

        context_parts = ["## Buenas prácticas relevantes para este diseño:\n"]
        for i, doc in enumerate(results, 1):
            category_label = {
                "pattern": "✅ Patrón",
                "antipattern": "⚠️ Anti-patrón a evitar",
                "best_practice": "💡 Recomendación",
            }.get(doc["category"], "📝 Nota")

            context_parts.append(f"{i}. [{category_label}] {doc['content']}\n")

        return "\n".join(context_parts)

    async def populate_knowledge_base(self, documents: list[dict]) -> int:
        """
        Poblar la base de conocimiento con documentos.

        Args:
            documents: Lista de {"content": str, "category": str, "metadata": dict}

        Returns:
            Número de documentos insertados
        """
        if not documents:
            return 0

        # Verificar si ya hay datos
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM knowledge_embeddings")
            )
            count = result.scalar()
            if count and count > 0:
                print(f"ℹ️  Base de conocimiento ya tiene {count} documentos, omitiendo carga")
                return 0

        # Generar embeddings
        texts = [doc["content"] for doc in documents]
        embeddings = self.embed_batch(texts)

        # Insertar en BD
        inserted = 0
        async with AsyncSessionLocal() as session:
            async with session.begin():
                for doc, embedding in zip(documents, embeddings):
                    embedding_str = f"[{','.join(str(x) for x in embedding)}]"
                    metadata_json = json.dumps(doc.get("metadata", {}))

                    await session.execute(
                        text("""
                            INSERT INTO knowledge_embeddings (content, category, metadata, embedding)
                            VALUES (:content, :category, CAST(:metadata AS jsonb), CAST(:embedding AS vector))
                        """),
                        {
                            "content": doc["content"],
                            "category": doc["category"],
                            "metadata": metadata_json,
                            "embedding": embedding_str,
                        },
                    )
                    inserted += 1

        print(f"✅ Base de conocimiento poblada: {inserted} documentos")
        return inserted

    async def is_populated(self) -> bool:
        """Verificar si la base de conocimiento ya tiene datos."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM knowledge_embeddings")
            )
            count = result.scalar()
            return count is not None and count > 0


# Instancia singleton
rag_engine = RAGEngine()
