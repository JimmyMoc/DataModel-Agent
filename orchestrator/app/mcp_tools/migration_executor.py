"""
MCP Tool: Migration Executor

Ejecuta sentencias SQL (CREATE TABLE, ALTER TABLE, etc.) contra la base de datos
de prueba y reporta el resultado. Esto permite al agente:
- Validar que las migraciones generadas son sintácticamente correctas
- Verificar que no hay conflictos con el esquema existente
- Dar feedback inmediato al usuario sobre si la migración funciona

SEGURIDAD: Se ejecuta SOLO contra la BD de prueba (dma_test), nunca contra producción.
La BD de prueba se puede resetear en cualquier momento sin consecuencias.
"""

import re
import traceback
from typing import Optional
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncTestSession

settings = get_settings()


@dataclass
class MigrationResult:
    """Resultado de la ejecución de una migración."""
    success: bool
    sql_executed: str
    error_message: Optional[str] = None
    error_detail: Optional[str] = None
    tables_created: list[str] = None
    tables_modified: list[str] = None

    def __post_init__(self):
        if self.tables_created is None:
            self.tables_created = []
        if self.tables_modified is None:
            self.tables_modified = []

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "sql_executed": self.sql_executed,
            "error_message": self.error_message,
            "error_detail": self.error_detail,
            "tables_created": self.tables_created,
            "tables_modified": self.tables_modified,
        }


class MigrationExecutor:
    """Herramienta para ejecutar y validar migraciones SQL."""

    # Sentencias permitidas (whitelist para seguridad)
    ALLOWED_STATEMENTS = {
        "CREATE TABLE",
        "CREATE INDEX",
        "CREATE UNIQUE INDEX",
        "ALTER TABLE",
        "CREATE TYPE",
        "CREATE EXTENSION",
        "COMMENT ON",
    }

    # Sentencias explícitamente prohibidas
    BLOCKED_STATEMENTS = {
        "DROP DATABASE",
        "DROP SCHEMA",
        "TRUNCATE",
        "DELETE FROM",
        "UPDATE ",
        "INSERT INTO",
    }

    async def execute_migration(self, sql: str) -> MigrationResult:
        """
        Ejecutar una migración SQL contra la BD de prueba.

        Args:
            sql: Sentencia(s) SQL a ejecutar

        Returns:
            MigrationResult con éxito/error y detalles
        """
        # Validar que no hay sentencias peligrosas
        validation_error = self._validate_sql(sql)
        if validation_error:
            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message="Validación fallida",
                error_detail=validation_error,
            )

        # Ejecutar contra la BD de prueba
        try:
            async with AsyncTestSession() as session:
                async with session.begin():
                    await session.execute(text(sql))

            # Analizar qué se creó/modificó
            tables_created = self._extract_created_tables(sql)
            tables_modified = self._extract_modified_tables(sql)

            return MigrationResult(
                success=True,
                sql_executed=sql,
                tables_created=tables_created,
                tables_modified=tables_modified,
            )

        except Exception as e:
            error_msg = str(e)
            # Extraer el mensaje de error de PostgreSQL
            if hasattr(e, "orig"):
                error_msg = str(e.orig)

            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message=f"Error de PostgreSQL: {type(e).__name__}",
                error_detail=error_msg,
            )

    async def execute_and_rollback(self, sql: str) -> MigrationResult:
        """
        Ejecutar migración en una transacción y hacer rollback.
        Útil para validar sin dejar cambios permanentes.

        Returns:
            MigrationResult (success=True si la sintaxis es válida)
        """
        validation_error = self._validate_sql(sql)
        if validation_error:
            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message="Validación fallida",
                error_detail=validation_error,
            )

        try:
            async with AsyncTestSession() as session:
                async with session.begin():
                    await session.execute(text(sql))
                    # Rollback explícito: validamos sintaxis sin persistir
                    await session.rollback()

            return MigrationResult(
                success=True,
                sql_executed=sql,
                tables_created=self._extract_created_tables(sql),
                tables_modified=self._extract_modified_tables(sql),
            )

        except Exception as e:
            error_msg = str(e)
            if hasattr(e, "orig"):
                error_msg = str(e.orig)

            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message=f"Error de PostgreSQL: {type(e).__name__}",
                error_detail=error_msg,
            )

    async def reset_test_database(self) -> MigrationResult:
        """
        Resetear la BD de prueba: eliminar todas las tablas del schema public.
        Útil para comenzar una conversación limpia.
        """
        try:
            async with AsyncTestSession() as session:
                async with session.begin():
                    # Obtener todas las tablas
                    result = await session.execute(text("""
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public'
                    """))
                    tables = [row[0] for row in result.fetchall()]

                    if tables:
                        # DROP CASCADE para eliminar todo
                        drop_sql = ", ".join(f'"{t}"' for t in tables)
                        await session.execute(
                            text(f"DROP TABLE IF EXISTS {drop_sql} CASCADE")
                        )

                    # Eliminar tipos custom
                    result = await session.execute(text("""
                        SELECT typname FROM pg_type
                        WHERE typnamespace = 'public'::regnamespace
                        AND typtype = 'e'
                    """))
                    types = [row[0] for row in result.fetchall()]
                    for t in types:
                        await session.execute(text(f'DROP TYPE IF EXISTS "{t}" CASCADE'))

            return MigrationResult(
                success=True,
                sql_executed="[RESET: dropped all tables and types]",
                tables_modified=tables if tables else [],
            )

        except Exception as e:
            return MigrationResult(
                success=False,
                sql_executed="[RESET]",
                error_message=f"Error reseteando BD: {type(e).__name__}",
                error_detail=str(e),
            )

    def _validate_sql(self, sql: str) -> Optional[str]:
        """
        Validar que el SQL es seguro para ejecutar.

        Returns:
            None si es válido, mensaje de error si no
        """
        sql_upper = sql.upper().strip()

        # Verificar sentencias bloqueadas
        for blocked in self.BLOCKED_STATEMENTS:
            if blocked in sql_upper:
                return f"Sentencia no permitida: '{blocked}' detectada en el SQL"

        # Verificar que al menos una sentencia permitida está presente
        has_allowed = any(
            allowed in sql_upper for allowed in self.ALLOWED_STATEMENTS
        )
        if not has_allowed:
            return (
                f"El SQL no contiene sentencias de migración válidas. "
                f"Permitidas: {', '.join(sorted(self.ALLOWED_STATEMENTS))}"
            )

        return None

    def _extract_created_tables(self, sql: str) -> list[str]:
        """Extraer nombres de tablas creadas del SQL."""
        pattern = r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?"
        matches = re.findall(pattern, sql, re.IGNORECASE)
        return matches

    def _extract_modified_tables(self, sql: str) -> list[str]:
        """Extraer nombres de tablas modificadas del SQL."""
        pattern = r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?"
        matches = re.findall(pattern, sql, re.IGNORECASE)
        return matches


# Instancia singleton
migration_executor = MigrationExecutor()
