"""
MCP Tool: Migration Executor

Ejecuta scripts SQL completos (CREATE TABLE, CREATE FUNCTION, DO blocks, triggers, etc.)
contra la base de datos de prueba utilizando el Simple Query Protocol de asyncpg.

Diseño:
- Usa conexión directa asyncpg (NO SQLAlchemy) para ejecución de migraciones.
- El Simple Query Protocol de PostgreSQL soporta nativamente múltiples statements,
  dollar-quoted strings, funciones, triggers, DO blocks, y cualquier construcción SQL válida.
- SQLAlchemy se mantiene para el resto del flujo transaccional del orchestrator.

SEGURIDAD: Se ejecuta SOLO contra la BD de prueba (dma_test), nunca contra producción.
La BD de prueba se puede resetear en cualquier momento sin consecuencias.
"""

import re
from typing import Optional
from dataclasses import dataclass, field

import asyncpg

from app.core.config import get_settings

settings = get_settings()


@dataclass
class MigrationResult:
    """Resultado de la ejecución de una migración."""
    success: bool
    sql_executed: str
    error_message: Optional[str] = None
    error_detail: Optional[str] = None
    tables_created: list[str] = field(default_factory=list)
    tables_modified: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "sql_executed": self.sql_executed,
            "error_message": self.error_message,
            "error_detail": self.error_detail,
            "tables_created": self.tables_created,
            "tables_modified": self.tables_modified,
        }


def _parse_dsn(sqlalchemy_url: str) -> str:
    """
    Convertir URL de SQLAlchemy (postgresql+asyncpg://...) a DSN de asyncpg (postgresql://...).
    """
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class MigrationExecutor:
    """
    Ejecutor de migraciones SQL usando asyncpg Simple Query Protocol.

    El Simple Query Protocol de PostgreSQL permite enviar scripts completos
    con múltiples statements separados por ';', incluyendo:
    - CREATE TABLE, ALTER TABLE, CREATE INDEX
    - CREATE FUNCTION / PROCEDURE con cuerpos dollar-quoted ($$...$$)
    - CREATE TRIGGER
    - DO $$ ... $$ blocks
    - CREATE VIEW / MATERIALIZED VIEW
    - CREATE TYPE / CREATE EXTENSION
    - Comentarios de una línea (--) y multilínea (/* */)
    - Strings que contienen ';'
    - Múltiples INSERT para seeds
    - Transacciones explícitas (BEGIN/COMMIT)
    """

    # Sentencias explícitamente prohibidas (seguridad)
    BLOCKED_PATTERNS = [
        r"\bDROP\s+DATABASE\b",
        r"\bDROP\s+SCHEMA\b",
    ]

    # Sentencias permitidas (al menos una debe estar presente)
    ALLOWED_PATTERNS = [
        r"\bCREATE\s+TABLE\b",
        r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b",
        r"\bALTER\s+TABLE\b",
        r"\bCREATE\s+TYPE\b",
        r"\bCREATE\s+EXTENSION\b",
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\b",
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b",
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\b",
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b",
        r"\bCREATE\s+MATERIALIZED\s+VIEW\b",
        r"\bCOMMENT\s+ON\b",
        r"\bDO\s+\$",
        r"\bINSERT\s+INTO\b",
        r"\bDROP\s+TABLE\b",
        r"\bDROP\s+TYPE\b",
        r"\bDROP\s+FUNCTION\b",
        r"\bDROP\s+TRIGGER\b",
        r"\bDROP\s+INDEX\b",
        r"\bDROP\s+VIEW\b",
        r"\bGRANT\b",
        r"\bREVOKE\b",
    ]

    def __init__(self):
        self._dsn = _parse_dsn(settings.test_database_url)

    async def _get_connection(self) -> asyncpg.Connection:
        """Obtener una conexión directa asyncpg a la BD de prueba."""
        return await asyncpg.connect(self._dsn)

    async def execute_migration(self, sql: str) -> MigrationResult:
        """
        Ejecutar un script SQL completo contra la BD de prueba.

        Usa el Simple Query Protocol de asyncpg que envía el script íntegro
        a PostgreSQL. El servidor se encarga del parsing, soportando nativamente
        todas las construcciones SQL (dollar-quoting, funciones, triggers, etc.).

        La ejecución es transaccional: si cualquier statement falla, se hace
        rollback de todo el script.

        Args:
            sql: Script SQL completo (puede contener múltiples statements)

        Returns:
            MigrationResult con éxito/error y metadata
        """
        # Validar seguridad antes de ejecutar
        validation_error = self._validate_sql(sql)
        if validation_error:
            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message="Validación fallida",
                error_detail=validation_error,
            )

        conn = await self._get_connection()
        try:
            # Envolver en transacción explícita para atomicidad
            # El Simple Query Protocol de asyncpg (execute sin args)
            # soporta múltiples statements nativamente
            await conn.execute(f"BEGIN;\n{sql}\nCOMMIT;")

            return MigrationResult(
                success=True,
                sql_executed=sql,
                tables_created=self._extract_created_tables(sql),
                tables_modified=self._extract_modified_tables(sql),
            )

        except asyncpg.PostgresError as e:
            # Intentar rollback en caso de error
            try:
                await conn.execute("ROLLBACK;")
            except Exception:
                pass

            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message=f"Error de PostgreSQL: {type(e).__name__}",
                error_detail=str(e),
            )

        except Exception as e:
            try:
                await conn.execute("ROLLBACK;")
            except Exception:
                pass

            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message=f"Error inesperado: {type(e).__name__}",
                error_detail=str(e),
            )

        finally:
            await conn.close()

    async def execute_and_rollback(self, sql: str) -> MigrationResult:
        """
        Ejecutar migración en una transacción y hacer rollback.
        Útil para validar sintaxis sin persistir cambios.

        Args:
            sql: Script SQL a validar

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

        conn = await self._get_connection()
        try:
            # Ejecutar en transacción y hacer rollback siempre
            await conn.execute("BEGIN;")
            await conn.execute(sql)
            await conn.execute("ROLLBACK;")

            return MigrationResult(
                success=True,
                sql_executed=sql,
                tables_created=self._extract_created_tables(sql),
                tables_modified=self._extract_modified_tables(sql),
            )

        except asyncpg.PostgresError as e:
            try:
                await conn.execute("ROLLBACK;")
            except Exception:
                pass

            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message=f"Error de PostgreSQL: {type(e).__name__}",
                error_detail=str(e),
            )

        except Exception as e:
            try:
                await conn.execute("ROLLBACK;")
            except Exception:
                pass

            return MigrationResult(
                success=False,
                sql_executed=sql,
                error_message=f"Error inesperado: {type(e).__name__}",
                error_detail=str(e),
            )

        finally:
            await conn.close()

    async def reset_test_database(self) -> MigrationResult:
        """
        Resetear la BD de prueba: eliminar todas las tablas, tipos y funciones
        del schema public. Útil para comenzar una conversación limpia.
        """
        reset_script = """
            -- Eliminar todas las tablas
            DO $$ 
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                    EXECUTE 'DROP TABLE IF EXISTS "' || r.tablename || '" CASCADE';
                END LOOP;
            END $$;

            -- Eliminar todos los tipos enum custom
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN (
                    SELECT typname FROM pg_type 
                    WHERE typnamespace = 'public'::regnamespace 
                    AND typtype = 'e'
                ) LOOP
                    EXECUTE 'DROP TYPE IF EXISTS "' || r.typname || '" CASCADE';
                END LOOP;
            END $$;

            -- Eliminar todas las funciones custom
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN (
                    SELECT p.proname, pg_get_function_identity_arguments(p.oid) as args
                    FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public'
                    AND p.prokind IN ('f', 'p')
                ) LOOP
                    EXECUTE 'DROP FUNCTION IF EXISTS "' || r.proname || '"(' || r.args || ') CASCADE';
                END LOOP;
            END $$;
        """

        conn = await self._get_connection()
        try:
            await conn.execute(reset_script)

            return MigrationResult(
                success=True,
                sql_executed="[RESET: dropped all tables, types, and functions]",
            )

        except Exception as e:
            return MigrationResult(
                success=False,
                sql_executed="[RESET]",
                error_message=f"Error reseteando BD: {type(e).__name__}",
                error_detail=str(e),
            )

        finally:
            await conn.close()

    def _validate_sql(self, sql: str) -> Optional[str]:
        """
        Validar que el SQL es seguro para ejecutar.

        Returns:
            None si es válido, mensaje de error si no
        """
        sql_upper = sql.upper()

        # Verificar sentencias bloqueadas
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, sql, re.IGNORECASE):
                return f"Sentencia no permitida detectada: {pattern}"

        # Verificar que al menos una sentencia permitida está presente
        has_allowed = any(
            re.search(pattern, sql, re.IGNORECASE)
            for pattern in self.ALLOWED_PATTERNS
        )
        if not has_allowed:
            return (
                "El SQL no contiene sentencias de migración válidas. "
                "Debe contener al menos un CREATE, ALTER, INSERT, DO, o similar."
            )

        return None

    def _extract_created_tables(self, sql: str) -> list[str]:
        """Extraer nombres de tablas creadas del SQL."""
        pattern = r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?"
        return re.findall(pattern, sql, re.IGNORECASE)

    def _extract_modified_tables(self, sql: str) -> list[str]:
        """Extraer nombres de tablas modificadas del SQL."""
        pattern = r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:\")?(\w+)(?:\")?"
        return re.findall(pattern, sql, re.IGNORECASE)


# Instancia singleton
migration_executor = MigrationExecutor()
