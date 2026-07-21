"""
MCP Tool: Schema Introspection

Conecta a la base de datos de prueba y devuelve el esquema actual:
tablas, columnas, tipos, constraints, relaciones (foreign keys), e índices.

Esto permite al agente:
- Saber qué ya existe antes de proponer cambios
- Generar migraciones ALTER (no solo CREATE)
- Verificar que las relaciones propuestas no conflictan con el estado actual
"""

from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncTestSession


class SchemaIntrospector:
    """Herramienta para inspeccionar el esquema de la BD de prueba."""

    async def get_full_schema(self, schema_name: str = "public") -> dict:
        """
        Obtener el esquema completo de la BD de prueba.

        Returns:
            {
                "tables": [...],
                "relations": [...],
                "indexes": [...]
            }
        """
        async with AsyncTestSession() as session:
            tables = await self._get_tables(session, schema_name)
            relations = await self._get_relations(session, schema_name)
            indexes = await self._get_indexes(session, schema_name)

        return {
            "schema": schema_name,
            "tables": tables,
            "relations": relations,
            "indexes": indexes,
            "table_count": len(tables),
        }

    async def get_table_info(self, table_name: str, schema_name: str = "public") -> Optional[dict]:
        """Obtener información detallada de una tabla específica."""
        async with AsyncTestSession() as session:
            columns = await self._get_columns(session, table_name, schema_name)
            if not columns:
                return None

            constraints = await self._get_constraints(session, table_name, schema_name)
            fk_relations = await self._get_table_relations(session, table_name, schema_name)

            return {
                "table_name": table_name,
                "columns": columns,
                "constraints": constraints,
                "relations": fk_relations,
            }

    async def _get_tables(self, session: AsyncSession, schema_name: str) -> list[dict]:
        """Listar todas las tablas con sus columnas."""
        result = await session.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = :schema
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """),
            {"schema": schema_name},
        )
        tables = []
        for row in result.fetchall():
            table_name = row[0]
            columns = await self._get_columns(session, table_name, schema_name)
            tables.append({
                "name": table_name,
                "columns": columns,
            })
        return tables

    async def _get_columns(self, session: AsyncSession, table_name: str, schema_name: str) -> list[dict]:
        """Obtener columnas de una tabla."""
        result = await session.execute(
            text("""
                SELECT
                    column_name,
                    data_type,
                    character_maximum_length,
                    is_nullable,
                    column_default,
                    udt_name
                FROM information_schema.columns
                WHERE table_schema = :schema
                AND table_name = :table
                ORDER BY ordinal_position
            """),
            {"schema": schema_name, "table": table_name},
        )
        return [
            {
                "name": row[0],
                "type": row[1],
                "max_length": row[2],
                "nullable": row[3] == "YES",
                "default": row[4],
                "pg_type": row[5],
            }
            for row in result.fetchall()
        ]

    async def _get_constraints(self, session: AsyncSession, table_name: str, schema_name: str) -> list[dict]:
        """Obtener constraints de una tabla."""
        result = await session.execute(
            text("""
                SELECT
                    tc.constraint_name,
                    tc.constraint_type,
                    kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = :schema
                AND tc.table_name = :table
                ORDER BY tc.constraint_type, kcu.ordinal_position
            """),
            {"schema": schema_name, "table": table_name},
        )
        return [
            {
                "name": row[0],
                "type": row[1],
                "column": row[2],
            }
            for row in result.fetchall()
        ]

    async def _get_relations(self, session: AsyncSession, schema_name: str) -> list[dict]:
        """Obtener todas las foreign keys del esquema."""
        result = await session.execute(
            text("""
                SELECT
                    tc.table_name AS from_table,
                    kcu.column_name AS from_column,
                    ccu.table_name AS to_table,
                    ccu.column_name AS to_column,
                    tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.table_schema = ccu.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = :schema
            """),
            {"schema": schema_name},
        )
        return [
            {
                "from_table": row[0],
                "from_column": row[1],
                "to_table": row[2],
                "to_column": row[3],
                "constraint_name": row[4],
            }
            for row in result.fetchall()
        ]

    async def _get_table_relations(self, session: AsyncSession, table_name: str, schema_name: str) -> list[dict]:
        """Obtener foreign keys de/hacia una tabla específica."""
        result = await session.execute(
            text("""
                SELECT
                    tc.table_name AS from_table,
                    kcu.column_name AS from_column,
                    ccu.table_name AS to_table,
                    ccu.column_name AS to_column,
                    tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.table_schema = ccu.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = :schema
                AND (tc.table_name = :table OR ccu.table_name = :table)
            """),
            {"schema": schema_name, "table": table_name},
        )
        return [
            {
                "from_table": row[0],
                "from_column": row[1],
                "to_table": row[2],
                "to_column": row[3],
                "constraint_name": row[4],
            }
            for row in result.fetchall()
        ]

    async def _get_indexes(self, session: AsyncSession, schema_name: str) -> list[dict]:
        """Obtener índices del esquema."""
        result = await session.execute(
            text("""
                SELECT
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = :schema
                ORDER BY tablename, indexname
            """),
            {"schema": schema_name},
        )
        return [
            {
                "table": row[0],
                "index_name": row[1],
                "definition": row[2],
            }
            for row in result.fetchall()
        ]


# Instancia singleton
schema_introspector = SchemaIntrospector()
