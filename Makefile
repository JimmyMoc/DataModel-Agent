.PHONY: up down build logs ps setup pull-model

# Levantar todo el stack
up:
	docker compose up -d

# Detener todo
down:
	docker compose down

# Reconstruir imágenes
build:
	docker compose build

# Ver logs de todos los servicios
logs:
	docker compose logs -f

# Ver estado de los contenedores
ps:
	docker compose ps

# Setup inicial: build + pull modelo + levantar
setup: build up pull-model
	@echo "Stack completo levantado"
	@echo "Frontend: http://localhost:8080"
	@echo "Orchestrator: http://localhost:8000/docs"
	@echo "PostgreSQL: localhost:5432"

# Descargar modelo de Ollama
pull-model:
	@echo " Descargando modelo LLM (puede tardar unos minutos)..."
	docker compose exec ollama ollama pull llama3.2
	@echo " Modelo descargado"

# Reiniciar solo el orquestador (útil en desarrollo)
restart-orch:
	docker compose restart orchestrator

# Limpiar todo (incluyendo volúmenes)
clean:
	docker compose down -v
	@echo "Volúmenes eliminados"
