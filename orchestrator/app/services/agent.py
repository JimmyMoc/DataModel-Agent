"""
Agent Core: Flujo principal de orquestación.

El agente sigue este loop:
1. Recibe mensaje del usuario (descripción de dominio o refinamiento)
2. Consulta RAG para obtener contexto de buenas prácticas
3. Inspecciona el esquema actual (si existe)
4. Envía al LLM con system prompt + contexto + tools disponibles
5. Si el LLM invoca una tool, la ejecuta y reenvía el resultado
6. Genera esquema JSON + migraciones SQL
7. Valida las migraciones ejecutándolas contra la BD de prueba
8. Retorna respuesta final al usuario

La orquestación maneja un loop de herramientas (hasta 5 iteraciones)
para permitir que el LLM corrija errores de migración.
"""

import json
import re
from typing import Optional

from app.services.ollama_client import ollama_client
from app.rag.engine import rag_engine
from app.mcp_tools.registry import TOOL_DEFINITIONS, dispatch_tool
from app.mcp_tools.schema_introspection import schema_introspector


# ─── System Prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres un experto en modelado de bases de datos PostgreSQL.
Conviertes descripciones en lenguaje natural a esquemas de base de datos.

RESPONDE SIEMPRE con un bloque schema_json como este:

```schema_json
{{
  "entities": [
    {{
      "name": "tabla_plural",
      "columns": ["id", "nombre", "email", "otra_tabla_id"],
      "foreign_keys": [{{"column": "otra_tabla_id", "table": "otra_tabla"}}]
    }}
  ],
  "notes": ["explicación breve"]
}}
```

REGLAS para el schema_json:
- Tablas en plural snake_case (users, orders, order_items)
- Incluir TODAS las columnas necesarias incluyendo FKs (campo_id)
- Relaciones N:M con tabla pivote
- NO generes SQL. Solo genera el JSON schema.

{tools_description}
"""


def build_tools_description() -> str:
    """Construir descripción mínima (no necesitamos que el LLM invoque tools)."""
    return ""


# ─── Agent Class ─────────────────────────────────────────────────────────────

class DataModelAgent:
    """Agente principal de modelado de datos."""

    MAX_TOOL_ITERATIONS = 5

    async def process_message(
        self,
        user_message: str,
        conversation_history: list[dict] = None,
    ) -> dict:
        """
        Procesar un mensaje del usuario y generar respuesta completa.

        Args:
            user_message: Mensaje del usuario
            conversation_history: Historial previo de la conversación

        Returns:
            {
                "message": str,  # Respuesta del agente
                "schema_json": dict | None,  # Esquema generado
                "migration_sql": str | None,  # SQL de migración
                "validation_status": str,  # "valid", "error", "pending"
                "validation_error": str | None,
                "tools_used": list[str],  # Herramientas invocadas
            }
        """
        tools_used = []

        # 1. Obtener contexto RAG
        rag_context = await self._get_rag_context(user_message)

        # 2. Obtener estado actual del esquema
        current_schema = await self._get_current_schema()

        # 3. Construir mensajes para el LLM
        messages = self._build_messages(
            user_message=user_message,
            conversation_history=conversation_history or [],
            rag_context=rag_context,
            current_schema=current_schema,
        )

        # 4. Loop de generación con tool calling
        response_text = await self._agent_loop(messages, tools_used)

        # 5. Extraer esquema JSON de la respuesta del LLM
        schema_json = self._extract_schema_json(response_text)

        # 6. Generar SQL determinísticamente desde el schema JSON
        #    (NO confiamos en el SQL del LLM — lo generamos con código)
        migration_sql = None
        if schema_json:
            try:
                from app.services.schema_to_sql import schema_to_sql
                migration_sql = schema_to_sql(schema_json)
            except Exception as e:
                print(f"⚠️ Error en schema_to_sql: {e}")
                # Fallback: intentar usar el SQL del LLM
                migration_sql = self._extract_migration_sql(response_text)
        else:
            # Sin schema JSON, intentar extraer SQL directamente
            migration_sql = self._extract_migration_sql(response_text)

        # 7. Validar migración ejecutándola contra la BD de prueba
        validation_status = "pending"
        validation_error = None

        if migration_sql:
            validation_result = await self._validate_and_execute_migration(
                migration_sql
            )
            validation_status = "valid" if validation_result["success"] else "error"
            validation_error = validation_result.get("error_detail")
            tools_used.append("execute_migration")

            # Si falló, intentar corregir con el LLM (solo 1 intento)
            if not validation_result["success"]:
                corrected = await self._try_fix_migration(
                    messages, migration_sql, validation_error, tools_used
                )
                if corrected:
                    migration_sql = corrected["migration_sql"]
                    validation_status = corrected["status"]
                    validation_error = corrected.get("error")

        # 8. Limpiar la respuesta para el usuario (remover bloques técnicos internos)
        clean_message = self._clean_response(response_text)

        return {
            "message": clean_message,
            "schema_json": schema_json,
            "migration_sql": migration_sql,
            "validation_status": validation_status,
            "validation_error": validation_error,
            "tools_used": tools_used,
        }

    async def _get_rag_context(self, user_message: str) -> str:
        """Obtener contexto relevante de la base de conocimiento."""
        try:
            return await rag_engine.get_relevant_context(user_message, limit=3)
        except Exception as e:
            print(f"⚠️ Error en RAG: {e}")
            return ""

    async def _get_current_schema(self) -> dict:
        """Obtener el esquema actual de la BD de prueba."""
        try:
            schema = await schema_introspector.get_full_schema()
            if schema["table_count"] == 0:
                return {}
            return schema
        except Exception as e:
            print(f"⚠️ Error obteniendo esquema: {e}")
            return {}

    def _build_messages(
        self,
        user_message: str,
        conversation_history: list[dict],
        rag_context: str,
        current_schema: dict,
    ) -> list[dict]:
        """Construir la lista de mensajes para enviar al LLM."""
        # System prompt con tools
        system = SYSTEM_PROMPT.format(
            tools_description=build_tools_description()
        )

        messages = [{"role": "system", "content": system}]

        # Agregar historial de conversación
        for msg in conversation_history[-4:]:  # Últimos 4 mensajes
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        # Construir el mensaje del usuario con contexto adicional
        user_content_parts = []

        if rag_context:
            user_content_parts.append(f"[CONTEXTO DE BUENAS PRÁCTICAS]\n{rag_context}\n")

        if current_schema:
            schema_summary = self._summarize_schema(current_schema)
            user_content_parts.append(f"[ESQUEMA ACTUAL EN LA BD]\n{schema_summary}\n")

        user_content_parts.append(f"[SOLICITUD DEL USUARIO]\n{user_message}")

        messages.append({
            "role": "user",
            "content": "\n".join(user_content_parts),
        })

        return messages

    async def _agent_loop(
        self, messages: list[dict], tools_used: list[str]
    ) -> str:
        """
        Generar respuesta del LLM. Ya no necesitamos tool calling loop
        porque el SQL se genera determinísticamente desde el JSON schema.
        """
        response_text = await ollama_client.chat(
            messages=messages,
            temperature=0.3,
        )
        return response_text

    async def _validate_and_execute_migration(self, sql: str) -> dict:
        """Ejecutar la migración contra la BD de prueba."""
        result = await dispatch_tool("execute_migration", {"sql": sql})
        return result

    async def _try_fix_migration(
        self,
        original_messages: list[dict],
        failed_sql: str,
        error: str,
        tools_used: list[str],
    ) -> Optional[dict]:
        """
        Intentar que el LLM corrija una migración que falló.

        Returns:
            {"migration_sql": str, "status": str, "error": str | None}
            o None si no pudo corregir
        """
        fix_messages = original_messages.copy()
        fix_messages.append({
            "role": "user",
            "content": (
                f"[ERROR DE VALIDACIÓN]\n"
                f"La migración que generaste falló al ejecutarse contra PostgreSQL.\n\n"
                f"Error de PostgreSQL:\n{error}\n\n"
                f"SQL que falló:\n{failed_sql}\n\n"
                f"INSTRUCCIONES DE CORRECCIÓN:\n"
                f"1. Identifica la sentencia que causó el error y ELIMÍNALA completamente\n"
                f"2. NO intentes arreglarla con sintaxis alternativa\n"
                f"3. Solo usa: CREATE TABLE, CREATE INDEX, ALTER TABLE ADD COLUMN/CONSTRAINT\n"
                f"4. NO uses ALTER TYPE, CREATE TYPE AS INTEGER, ni ninguna sentencia experimental\n"
                f"5. Responde ÚNICAMENTE con el SQL corregido dentro de un bloque ```migration_sql ... ```\n"
                f"6. El SQL debe ser 100% válido en PostgreSQL 16\n"
            ),
        })

        # Intentar corrección
        response = await ollama_client.chat(messages=fix_messages, temperature=0.1)
        corrected_sql = self._extract_migration_sql(response)

        if not corrected_sql:
            return None

        # Validar la corrección
        result = await dispatch_tool("execute_migration", {"sql": corrected_sql})
        tools_used.append("execute_migration")

        if result.get("success"):
            return {
                "migration_sql": corrected_sql,
                "status": "valid",
            }
        else:
            return {
                "migration_sql": corrected_sql,
                "status": "error",
                "error": result.get("error_detail", "Error desconocido"),
            }

    def _extract_tool_calls(self, text: str) -> list[dict]:
        """Extraer invocaciones de herramientas de la respuesta del LLM."""
        tool_calls = []
        # Buscar bloques ```tool_call ... ```
        pattern = r"```tool_call\s*\n?(.*?)\n?```"
        matches = re.findall(pattern, text, re.DOTALL)

        for match in matches:
            try:
                call = json.loads(match.strip())
                if "name" in call:
                    tool_calls.append(call)
            except json.JSONDecodeError:
                continue

        return tool_calls

    def _extract_schema_json(self, text: str) -> Optional[dict]:
        """Extraer el bloque de esquema JSON de la respuesta."""
        # 1. Buscar bloque ```schema_json ... ```
        pattern = r"```schema_json\s*\n?(.*?)\n?```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 2. Buscar bloque ```json ... ``` que contenga "entities"
        pattern = r"```json\s*\n?(.*?)\n?```"
        matches = re.findall(pattern, text, re.DOTALL)
        for m in matches:
            if '"entities"' in m:
                try:
                    return json.loads(m.strip())
                except json.JSONDecodeError:
                    pass

        # 3. Fallback: buscar JSON con estructura de esquema en texto libre
        # Buscar el primer { que precede a "entities"
        entities_pos = text.find('"entities"')
        if entities_pos != -1:
            # Buscar el { que abre este JSON
            start = text.rfind("{", 0, entities_pos)
            if start != -1:
                depth = 0
                end = start
                for i, c in enumerate(text[start:], start):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                try:
                    return json.loads(text[start:end])
                except (json.JSONDecodeError, ValueError):
                    pass

        return None

    def _extract_migration_sql(self, text: str) -> Optional[str]:
        """Extraer el bloque de migración SQL de la respuesta."""
        # Buscar bloque ```migration_sql ... ```
        pattern = r"```migration_sql\s*\n?(.*?)\n?```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback: buscar bloque ```sql ... ``` con CREATE/ALTER
        pattern = r"```sql\s*\n?(.*?)\n?```"
        matches = re.findall(pattern, text, re.DOTALL)
        for m in matches:
            if "CREATE TABLE" in m.upper() or "ALTER TABLE" in m.upper():
                return m.strip()

        return None

    def _summarize_schema(self, schema: dict) -> str:
        """Resumir el esquema actual para incluir en el contexto."""
        if not schema or not schema.get("tables"):
            return "La base de datos está vacía (sin tablas)."

        lines = [f"Base de datos actual tiene {schema['table_count']} tabla(s):"]
        for table in schema["tables"]:
            cols = ", ".join(
                f"{c['name']} ({c['type']})" for c in table["columns"][:8]
            )
            extra = f" ... +{len(table['columns']) - 8} más" if len(table["columns"]) > 8 else ""
            lines.append(f"  - {table['name']}: [{cols}{extra}]")

        if schema.get("relations"):
            lines.append(f"\nRelaciones ({len(schema['relations'])}):")
            for rel in schema["relations"]:
                lines.append(
                    f"  - {rel['from_table']}.{rel['from_column']} → {rel['to_table']}.{rel['to_column']}"
                )

        return "\n".join(lines)

    def _clean_response(self, text: str) -> str:
        """Limpiar la respuesta removiendo bloques de tool_call pero manteniendo el resto."""
        # Remover bloques tool_call (son internos, no para el usuario)
        cleaned = re.sub(r"```tool_call\s*\n?.*?\n?```", "", text, flags=re.DOTALL)
        # Limpiar líneas vacías múltiples
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()


# Instancia singleton
agent = DataModelAgent()
