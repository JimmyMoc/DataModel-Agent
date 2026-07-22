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

SYSTEM_PROMPT = """Eres un agente experto en modelado de bases de datos PostgreSQL.
Tu trabajo es convertir descripciones en lenguaje natural en esquemas de base de datos ejecutables.

## Reglas de SQL que SIEMPRE sigues:
- SOLO genera SQL estándar de PostgreSQL que puedas garantizar es 100% válido
- Toda tabla tiene `id SERIAL PRIMARY KEY`
- Toda tabla tiene `created_at TIMESTAMP DEFAULT NOW()` y `updated_at TIMESTAMP DEFAULT NOW()`
- Foreign keys siempre tienen un índice (CREATE INDEX separado)
- Relaciones N:M usan tabla pivote con composite PRIMARY KEY y ambas FK indexadas
- Usar tipos nativos de PostgreSQL: INTEGER, SERIAL, VARCHAR(n), TEXT, NUMERIC(p,s), BOOLEAN, DATE, TIMESTAMP, TIMESTAMPTZ, UUID
- Naming: tablas en plural snake_case, columnas en singular snake_case, FK como tabla_singular_id
- Constraints CHECK donde aplique (valores positivos, rangos válidos)
- NOT NULL por defecto, NULL solo cuando tiene sentido semántico
- Para enums usar: CREATE TYPE nombre AS ENUM ('valor1', 'valor2')
- Usar IF NOT EXISTS en CREATE TABLE para idempotencia

## PROHIBIDO — NUNCA generes esto:
- NUNCA uses ALTER TYPE columna TYPE ... (no existe esa sintaxis)
- NUNCA uses CREATE TYPE nombre AS INTEGER/VARCHAR/etc (no es válido, usa CREATE DOMAIN si necesitas alias)
- NUNCA pongas ';' dentro de un CREATE TABLE (el ; va solo al final del statement)
- NUNCA inventes sintaxis SQL. Si no estás seguro de una sentencia, NO la incluyas
- NUNCA generes migraciones que modifiquen tipos de columna a menos que el usuario lo pida explícitamente
- NUNCA mezcles DDL y ALTER TYPE en el mismo script de creación inicial

## Formato de migración SQL correcto:
```migration_sql
CREATE TABLE IF NOT EXISTS nombre_tabla (
    id SERIAL PRIMARY KEY,
    columna1 TIPO NOT NULL,
    columna2 TIPO,
    otra_tabla_id INTEGER NOT NULL REFERENCES otra_tabla(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nombre_tabla_otra_tabla_id ON nombre_tabla(otra_tabla_id);
```

## Herramientas disponibles:
Puedes invocar herramientas usando este formato EXACTO en tu respuesta:
```tool_call
{{"name": "nombre_herramienta", "arguments": {{...}}}}
```

Herramientas:
{tools_description}

## Formato de respuesta:
Cuando generes un esquema, incluye SIEMPRE estos bloques:

1. **Explicación** en lenguaje natural de las decisiones de diseño
2. **Esquema JSON** en un bloque:
```schema_json
{{
  "entities": [...],
  "relations": [...],
  "notes": [...]
}}
```
3. **Migraciones SQL** en un bloque:
```migration_sql
CREATE TABLE IF NOT EXISTS ...
```

IMPORTANTE: El bloque migration_sql debe contener SOLO sentencias CREATE TABLE, CREATE INDEX, CREATE TYPE AS ENUM, y ALTER TABLE ADD. Nada más. Si el usuario pide un cambio incremental, genera solo la migración ALTER necesaria.
"""


def build_tools_description() -> str:
    """Construir descripción de herramientas para el system prompt."""
    parts = []
    for tool in TOOL_DEFINITIONS:
        params_desc = ""
        props = tool["parameters"].get("properties", {})
        if props:
            params_desc = ", ".join(
                f'{k}: {v.get("description", "")}'
                for k, v in props.items()
            )
        parts.append(
            f"- **{tool['name']}**({params_desc}): {tool['description']}"
        )
    return "\n".join(parts)


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

        # 5. Extraer esquema y migración de la respuesta
        schema_json = self._extract_schema_json(response_text)
        migration_sql = self._extract_migration_sql(response_text)

        # 6. Validar migración si se generó
        validation_status = "pending"
        validation_error = None

        if migration_sql:
            validation_result = await self._validate_and_execute_migration(
                migration_sql
            )
            validation_status = "valid" if validation_result["success"] else "error"
            validation_error = validation_result.get("error_detail")
            tools_used.append("execute_migration")

            # Si falló, intentar corregir con el LLM
            if not validation_result["success"]:
                corrected = await self._try_fix_migration(
                    messages, migration_sql, validation_error, tools_used
                )
                if corrected:
                    migration_sql = corrected["migration_sql"]
                    validation_status = corrected["status"]
                    validation_error = corrected.get("error")

        # 7. Limpiar la respuesta para el usuario (remover bloques técnicos internos)
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
            return await rag_engine.get_relevant_context(user_message, limit=5)
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
        for msg in conversation_history[-10:]:  # Últimos 10 mensajes
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
        Loop del agente: generar respuesta, ejecutar tools si las invoca, repetir.
        """
        for iteration in range(self.MAX_TOOL_ITERATIONS):
            # Generar respuesta del LLM
            response_text = await ollama_client.chat(
                messages=messages,
                temperature=0.2,
            )

            # Buscar tool calls en la respuesta
            tool_calls = self._extract_tool_calls(response_text)

            if not tool_calls:
                # No hay tool calls, la respuesta es final
                return response_text

            # Ejecutar cada tool call
            for tool_call in tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("arguments", {})

                print(f"🔧 Tool call [{iteration+1}]: {tool_name}({tool_args})")
                tools_used.append(tool_name)

                result = await dispatch_tool(tool_name, tool_args)

                # Agregar resultado al contexto
                messages.append({
                    "role": "assistant",
                    "content": response_text,
                })
                messages.append({
                    "role": "user",
                    "content": f"[RESULTADO DE {tool_name}]\n{json.dumps(result, indent=2, default=str)}",
                })

        # Si llegamos aquí, agotamos las iteraciones
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
        pattern = r"```schema_json\s*\n?(.*?)\n?```"
        match = re.search(pattern, text, re.DOTALL)

        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Fallback: buscar JSON con structure de esquema
        pattern = r'\{[^{}]*"entities"\s*:\s*\[.*?\]\s*[,}]'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                # Intentar parsear un bloque JSON más amplio
                start = text.find("{", match.start())
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
