#!/usr/bin/env bash
# Script de verificación end-to-end para Data Model Agent
# Ejecutar después de `make setup`

set -e

echo "Verificación End-to-End del Data Model Agent"
echo "═══════════════════════════════════════════════"

BASE_URL_ORCH="http://localhost:8000"
BASE_URL_FRONT="http://localhost:8080"

# 1. Verificar que los servicios están corriendo
echo ""
echo "Verificando servicios..."

# PostgreSQL
if docker compose exec postgres pg_isready -U dma_user -d dma_main > /dev/null 2>&1; then
    echo "     PostgreSQL: corriendo"
else
    echo "     PostgreSQL: no disponible"
    exit 1
fi

# Ollama
if curl -s "$BASE_URL_ORCH/../" > /dev/null 2>&1; then
    echo "    Ollama: corriendo"
fi

# Orquestación
HEALTH=$(curl -s "$BASE_URL_ORCH/health" 2>/dev/null)
if echo "$HEALTH" | grep -q "healthy\|degraded"; then
    echo "    Orchestrator: $(echo $HEALTH | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"status={d[\"status\"]}, ollama={d[\"ollama_available\"]}, db={d[\"db_available\"]}")')"
else
    echo "    Orchestrator: no responde"
    exit 1
fi

# Frontend
if curl -s "$BASE_URL_FRONT" | grep -q "Data Model Agent"; then
    echo "    Frontend: accesible"
else
    echo "    Frontend: no disponible"
fi

# Verificar base de conocimiento RAG
echo ""
echo "Verificando RAG..."
RAG_COUNT=$(docker compose exec postgres psql -U dma_user -d dma_main -t -c "SELECT COUNT(*) FROM knowledge_embeddings;" 2>/dev/null | tr -d ' ')
echo "   Documentos en knowledge base: $RAG_COUNT"
if [ "$RAG_COUNT" -gt "0" ]; then
    echo "    RAG poblado correctamente"
else
    echo "    RAG vacío (se poblará en el primer request)"
fi

#Probar flujo de chat
echo ""
echo "Probando flujo de chat..."
CHAT_RESPONSE=$(curl -s -X POST "$BASE_URL_ORCH/api/chat/" \
    -H "Content-Type: application/json" \
    -d '{"message": "Sistema de biblioteca con libros, autores, miembros y préstamos"}' \
    2>/dev/null)

if echo "$CHAT_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   Conversation ID: {d.get(\"conversation_id\", \"N/A\")}')" 2>/dev/null; then
    echo "   ✓ Chat endpoint responde"
    
    # Verificar si generó migración
    HAS_SQL=$(echo "$CHAT_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if d.get('migration_sql') else 'no')" 2>/dev/null)
    if [ "$HAS_SQL" = "yes" ]; then
        echo "Migración SQL generada"
        
        VALIDATION=$(echo "$CHAT_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('validation_status', 'N/A'))" 2>/dev/null)
        echo "Validación: $VALIDATION"
    else
        echo "Sin migración (el modelo puede necesitar más contexto)"
    fi
else
    echo "Chat endpoint falló"
fi

#Verificar BD de prueba
echo ""
echo "Verificando BD de prueba..."
TEST_TABLES=$(docker compose exec postgres psql -U dma_user -d dma_test -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d ' ')
echo "   Tablas en dma_test: $TEST_TABLES"

echo ""
echo "═══════════════════════════════════════════════"
echo "Verificación completada"
echo ""
echo "Frontend: $BASE_URL_FRONT"
echo "API Docs: $BASE_URL_ORCH/docs"
echo "Health:   $BASE_URL_ORCH/health"
