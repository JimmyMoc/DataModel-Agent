# Data Model Agent: De lenguaje natural a esquemas ejecutables

## Contexto del proyecto
Estoy construyendo un agente especializado para el reto "Agentes Especializados" 
de un hackathon (Código Facilito x AWS Kiro). El agente reemplaza el modelado 
manual de bases de datos (diagramas arrastrando cajas) por una conversación: 
el usuario describe su dominio en lenguaje natural, el agente itera con él, 
genera migraciones, y las valida ejecutándolas contra una base de datos real 
antes de entregarlas.

## Problema que resuelve
El modelado de datos es un cuello de botella real en cualquier proyecto de 
software: normalmente lo hace un dev senior a mano, y los errores de 
normalización o relaciones mal diseñadas se pagan caro después en forma de 
migraciones destructivas y refactors. Las herramientas actuales (dbdiagram.io, 
MySQL Workbench, ERBuilder) son visuales y manuales, no conversacionales ni 
autovalidantes.

## Flujo funcional
1. El usuario describe su dominio en lenguaje natural (ej. "sistema de citas 
   médicas con doctores, pacientes, horarios y especialidades")
2. El agente propone un esquema: entidades, atributos, tipos de datos, 
   relaciones (1:N, N:M)
3. Valida el esquema contra buenas prácticas (normalización, redundancias, 
   índices necesarios) usando una base de conocimiento curada (RAG)
4. Genera las migraciones ejecutables
5. Ejecuta las migraciones contra una base de datos de prueba real para 
   confirmar que corren sin errores antes de entregarlas
6. El usuario puede iterar conversacionalmente ("un doctor puede tener varias 
   especialidades") y el agente regenera solo la parte afectada

## Arquitectura técnica (100% open source, sin dependencia de proveedores de nube)
- **UI**: Laravel (interfaz web donde el usuario describe su dominio y ve el 
  esquema/migraciones generadas)
- **Orquestador**: FastAPI (Python) en Docker, expone una API REST que Laravel 
  consume, coordina todo el flujo del agente
- **LLM**: Ollama corriendo un modelo abierto local (ej. Llama 3.2 o Mistral) 
  como motor de razonamiento
- **MCP tools** (Python):
  - Una tool que introspecciona un esquema de base de datos existente (si el 
    usuario ya tiene uno)
  - Una tool que ejecuta una migración contra una base de datos de prueba y 
    devuelve el resultado (éxito/error) para validación real
- **Base de datos**: PostgreSQL con extensión pgvector — funciona como base de 
  conocimiento para RAG (patrones de diseño y anti-patrones curados) y como 
  base de datos de prueba donde se validan las migraciones generadas
- **Despliegue**: docker-compose con tres servicios (Laravel, FastAPI, 
  PostgreSQL), pensado para correr en cualquier VPS gratuito sin necesitar 
  tarjeta de crédito ni servicios gestionados de pago

## Requisitos del reto que debe cumplir
- Ser un agente especializado que use un modelo de IA como motor principal 
  más herramientas adicionales para un problema específico
- Publicarse para que cualquiera pueda usarlo (disponible en producción 
  mínimo 7 días)
- Hacer uso creativo de RAG y MCPs (no solo decorativo — cada tool call debe 
  resolver algo que el LLM solo no podría verificar con certeza)
- Enfocarse en un problema real, no una herramienta genérica

## Entregables esperados
- Repositorio público en GitHub con README claro
- Demo en línea funcional
- Video de presentación (máx. 5 min) mostrando objetivos, componentes 
  principales, y una demo real
