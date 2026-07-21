-- Habilitar extensión pgvector en la base principal
CREATE EXTENSION IF NOT EXISTS vector;

-- Crear base de datos de prueba para validar migraciones
CREATE DATABASE dma_test;

-- Conectar a la BD de prueba y habilitar pgvector también
\c dma_test;
CREATE EXTENSION IF NOT EXISTS vector;

-- Volver a la BD principal
\c dma_main;

-- ─── Tabla para embeddings de conocimiento RAG ──────────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    category VARCHAR(50) NOT NULL,  -- 'pattern', 'antipattern', 'best_practice'
    metadata JSONB DEFAULT '{}',
    embedding vector(384) NOT NULL,  -- dimensión para all-MiniLM-L6-v2
    created_at TIMESTAMP DEFAULT NOW()
);

-- Índice HNSW para búsqueda rápida de similitud
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding 
    ON knowledge_embeddings 
    USING hnsw (embedding vector_cosine_ops);

-- ─── Tabla para historial de conversaciones ─────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,  -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',  -- esquema generado, migraciones, etc.
    created_at TIMESTAMP DEFAULT NOW()
);

-- ─── Tabla para esquemas generados ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS generated_schemas (
    id SERIAL PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    schema_json JSONB NOT NULL,
    migration_sql TEXT,
    validation_status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'valid', 'error'
    validation_error TEXT,
    version INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW()
);
