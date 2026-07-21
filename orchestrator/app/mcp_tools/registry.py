"""
MCP Tools Registry

Define las herramientas disponibles para el agente en un formato que el LLM pueda
entender y que el orquestador pueda despachar. Cada tool tiene:
- name: identificador único
- description: qué hace (para el LLM)
- parameters: qué espera recibir
- handler: función que ejecuta la acción real
"""

from typing import Any, Callable, Awaitable

from app.mcp_tools.schema_introspection import schema_introspector
from app.mcp_tools.migration_executor import migration_executor


# ─── Tool Definitions (lo que ve el LLM) ────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "inspect_schema",
        "description": (
            "Inspecciona el esquema actual de la base de datos de prueba. "
            "Devuelve todas las tablas existentes, sus columnas, tipos de datos, "
            "relaciones (foreign keys) e índices. Usa esta herramienta ANTES de "
            "generar migraciones para saber qué ya existe."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Nombre de tabla específica (opcional, si se omite devuelve todo el esquema)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "execute_migration",
        "description": (
            "Ejecuta sentencias SQL de migración (CREATE TABLE, ALTER TABLE, CREATE INDEX) "
            "contra la base de datos de prueba y reporta si se ejecutaron correctamente. "
            "Usa esta herramienta para VALIDAR que las migraciones generadas son correctas "
            "antes de entregarlas al usuario."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Sentencia(s) SQL a ejecutar (CREATE TABLE, ALTER TABLE, etc.)",
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "validate_migration",
        "description": (
            "Valida que una migración SQL es sintácticamente correcta ejecutándola "
            "y luego haciendo rollback (no persiste cambios). Útil para verificar "
            "sintaxis sin modificar el estado de la BD."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Sentencia(s) SQL a validar",
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "reset_database",
        "description": (
            "Resetea la base de datos de prueba eliminando todas las tablas y tipos. "
            "Usa esta herramienta cuando el usuario quiere empezar de cero con un "
            "esquema nuevo."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ─── Tool Handlers (lo que ejecuta el orquestador) ──────────────────────────

async def handle_inspect_schema(table_name: str = None) -> dict:
    """Handler para inspect_schema."""
    if table_name:
        result = await schema_introspector.get_table_info(table_name)
        if result is None:
            return {"error": f"Tabla '{table_name}' no encontrada en la BD de prueba"}
        return result
    return await schema_introspector.get_full_schema()


async def handle_execute_migration(sql: str) -> dict:
    """Handler para execute_migration."""
    result = await migration_executor.execute_migration(sql)
    return result.to_dict()


async def handle_validate_migration(sql: str) -> dict:
    """Handler para validate_migration."""
    result = await migration_executor.execute_and_rollback(sql)
    return result.to_dict()


async def handle_reset_database() -> dict:
    """Handler para reset_database."""
    result = await migration_executor.reset_test_database()
    return result.to_dict()


# ─── Dispatcher ──────────────────────────────────────────────────────────────

TOOL_HANDLERS: dict[str, Callable[..., Awaitable[Any]]] = {
    "inspect_schema": handle_inspect_schema,
    "execute_migration": handle_execute_migration,
    "validate_migration": handle_validate_migration,
    "reset_database": handle_reset_database,
}


async def dispatch_tool(tool_name: str, arguments: dict) -> dict:
    """
    Despachar una llamada de herramienta.

    Args:
        tool_name: Nombre de la herramienta a invocar
        arguments: Parámetros para la herramienta

    Returns:
        Resultado de la ejecución
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"Herramienta desconocida: '{tool_name}'"}

    try:
        return await handler(**arguments)
    except Exception as e:
        return {
            "error": f"Error ejecutando '{tool_name}': {type(e).__name__}: {str(e)}"
        }
