import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationSummary,
    ValidationStatus,
)
from app.services.agent import agent

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Endpoint principal: recibe mensaje del usuario y devuelve respuesta del agente.
    El agente analiza la solicitud, consulta RAG, genera esquema/migraciones,
    y las valida ejecutándolas contra la BD de prueba.
    """
    # Crear o recuperar conversación
    conversation_id = request.conversation_id
    if not conversation_id:
        result = await db.execute(
            text("INSERT INTO conversations (title) VALUES (:title) RETURNING id"),
            {"title": request.message[:100]},
        )
        conversation_id = str(result.scalar())
        await db.commit()

    # Guardar mensaje del usuario
    await db.execute(
        text(
            "INSERT INTO messages (conversation_id, role, content) VALUES (:cid, 'user', :content)"
        ),
        {"cid": conversation_id, "content": request.message},
    )
    await db.commit()

    # Obtener historial de conversación
    history_result = await db.execute(
        text("""
            SELECT role, content FROM messages
            WHERE conversation_id = :cid
            ORDER BY created_at ASC
        """),
        {"cid": conversation_id},
    )
    conversation_history = [
        {"role": row[0], "content": row[1]}
        for row in history_result.fetchall()
    ]
    # Excluir el último mensaje (ya es el actual del usuario)
    conversation_history = conversation_history[:-1]

    # Procesar con el agente
    try:
        result = await agent.process_message(
            user_message=request.message,
            conversation_history=conversation_history,
        )
    except Exception as e:
        # Si el agente falla, devolver error gracefully
        result = {
            "message": f"Error procesando tu solicitud: {str(e)}. Por favor intenta de nuevo.",
            "schema_json": None,
            "migration_sql": None,
            "validation_status": "error",
            "validation_error": str(e),
            "tools_used": [],
        }

    # Guardar respuesta del asistente
    metadata = {
        "schema_json": result.get("schema_json"),
        "migration_sql": result.get("migration_sql"),
        "validation_status": result.get("validation_status"),
        "tools_used": result.get("tools_used", []),
    }
    await db.execute(
        text(
            "INSERT INTO messages (conversation_id, role, content, metadata) "
            "VALUES (:cid, 'assistant', :content, CAST(:metadata AS jsonb))"
        ),
        {
            "cid": conversation_id,
            "content": result["message"],
            "metadata": json.dumps(metadata),
        },
    )

    # Guardar esquema generado si existe
    if result.get("schema_json") or result.get("migration_sql"):
        await db.execute(
            text("""
                INSERT INTO generated_schemas 
                    (conversation_id, schema_json, migration_sql, validation_status, validation_error)
                VALUES (:cid, CAST(:schema AS jsonb), :sql, :status, :error)
            """),
            {
                "cid": conversation_id,
                "schema": json.dumps(result.get("schema_json") or {}),
                "sql": result.get("migration_sql"),
                "status": result.get("validation_status", "pending"),
                "error": result.get("validation_error"),
            },
        )

    await db.commit()

    return ChatResponse(
        message=result["message"],
        conversation_id=conversation_id,
        schema_json=result.get("schema_json"),
        migration_sql=result.get("migration_sql"),
        validation_status=ValidationStatus(result.get("validation_status", "pending")),
        validation_error=result.get("validation_error"),
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    """Listar todas las conversaciones."""
    result = await db.execute(
        text("""
            SELECT c.id, c.title, c.created_at, COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT 50
        """)
    )
    rows = result.fetchall()
    return [
        ConversationSummary(
            id=str(row.id),
            title=row.title,
            created_at=row.created_at,
            message_count=row.message_count,
        )
        for row in rows
    ]


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """Obtener mensajes de una conversación."""
    result = await db.execute(
        text("""
            SELECT role, content, metadata, created_at
            FROM messages
            WHERE conversation_id = :cid
            ORDER BY created_at ASC
        """),
        {"cid": conversation_id},
    )
    rows = result.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    return [
        {
            "role": row.role,
            "content": row.content,
            "metadata": row.metadata,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """Eliminar una conversación y todos sus mensajes."""
    # Check it exists
    result = await db.execute(
        text("SELECT id FROM conversations WHERE id = :cid"),
        {"cid": conversation_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    # Delete (CASCADE handles messages and schemas)
    await db.execute(
        text("DELETE FROM conversations WHERE id = :cid"),
        {"cid": conversation_id},
    )
    await db.commit()
    return {"success": True, "deleted": conversation_id}
