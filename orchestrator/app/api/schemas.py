from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum


# ─── Enums ───────────────────────────────────────────────────────────────────

class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class ValidationStatus(str, Enum):
    pending = "pending"
    valid = "valid"
    error = "error"


# ─── Request Models ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Mensaje del usuario al agente."""
    message: str
    conversation_id: Optional[str] = None


class SchemaValidationRequest(BaseModel):
    """Solicitud de validación de migración SQL."""
    migration_sql: str
    conversation_id: Optional[str] = None


# ─── Response Models ─────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    """Respuesta del agente al usuario."""
    message: str
    conversation_id: str
    schema_json: Optional[dict] = None
    migration_sql: Optional[str] = None
    validation_status: Optional[ValidationStatus] = None
    validation_error: Optional[str] = None


class ConversationSummary(BaseModel):
    """Resumen de una conversación."""
    id: str
    title: Optional[str] = None
    created_at: datetime
    message_count: int = 0


class HealthResponse(BaseModel):
    """Respuesta de health check."""
    status: str
    service: str
    ollama_available: bool = False
    db_available: bool = False


class SchemaEntity(BaseModel):
    """Entidad en un esquema de BD."""
    name: str
    columns: list[dict]
    primary_key: str = "id"
    indexes: list[str] = []


class SchemaRelation(BaseModel):
    """Relación entre entidades."""
    from_entity: str
    to_entity: str
    relation_type: str  # "one_to_many", "many_to_many", "one_to_one"
    foreign_key: Optional[str] = None
    pivot_table: Optional[str] = None


class GeneratedSchema(BaseModel):
    """Esquema completo generado por el agente."""
    entities: list[SchemaEntity]
    relations: list[SchemaRelation]
    notes: list[str] = []
