"""
Base de conocimiento curada para el RAG.

Contiene patrones de diseño, anti-patrones, y buenas prácticas de modelado
de bases de datos relacionales. El agente consulta esto para:
- Validar esquemas propuestos
- Sugerir mejoras de normalización
- Detectar anti-patrones comunes
- Recomendar índices y constraints
"""

KNOWLEDGE_BASE = [
    # ═══════════════════════════════════════════════════════════════════════════
    # PATRONES DE DISEÑO (buenas prácticas)
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "content": (
            "Patrón: Surrogate Key (Clave subrogada). "
            "Siempre usar un ID autoincremental o UUID como clave primaria en lugar de "
            "claves naturales (como email o DNI). Las claves naturales pueden cambiar con "
            "el tiempo, causar problemas de rendimiento por ser strings largos, y complicar "
            "las relaciones. Ejemplo: usar 'id SERIAL PRIMARY KEY' o 'id UUID PRIMARY KEY "
            "DEFAULT gen_random_uuid()' en PostgreSQL."
        ),
        "category": "pattern",
        "metadata": {"topic": "primary_keys", "priority": "high"},
    },
    {
        "content": (
            "Patrón: Timestamps automáticos. "
            "Toda tabla debe incluir columnas 'created_at TIMESTAMP DEFAULT NOW()' y "
            "'updated_at TIMESTAMP DEFAULT NOW()'. Esto permite auditoría, debugging, "
            "y sincronización. En PostgreSQL se puede usar un trigger para actualizar "
            "updated_at automáticamente."
        ),
        "category": "pattern",
        "metadata": {"topic": "audit_columns", "priority": "high"},
    },
    {
        "content": (
            "Patrón: Soft Delete. "
            "En lugar de DELETE físico, agregar 'deleted_at TIMESTAMP NULL'. Si es NULL, "
            "el registro está activo. Si tiene fecha, está 'eliminado'. Permite recuperar "
            "datos y mantener integridad referencial. Agregar índice parcial: "
            "'CREATE INDEX idx_active ON table WHERE deleted_at IS NULL'."
        ),
        "category": "pattern",
        "metadata": {"topic": "deletion", "priority": "medium"},
    },
    {
        "content": (
            "Patrón: Tabla pivote para N:M (Many-to-Many). "
            "Para relaciones muchos-a-muchos, crear una tabla intermedia con foreign keys "
            "a ambas tablas. Ejemplo: 'student_courses' con student_id y course_id. "
            "La PK debe ser compuesta (student_id, course_id) o un ID propio si la tabla "
            "pivote tiene atributos adicionales (ej: enrollment_date, grade). "
            "Siempre indexar ambas FK individualmente."
        ),
        "category": "pattern",
        "metadata": {"topic": "relationships", "priority": "high"},
    },
    {
        "content": (
            "Patrón: Índices en Foreign Keys. "
            "PostgreSQL NO crea índices automáticamente en columnas foreign key (a diferencia "
            "de MySQL). SIEMPRE crear un índice en cada columna que sea FK. Sin esto, los "
            "JOINs y ON DELETE CASCADE serán lentos. Ejemplo: "
            "'CREATE INDEX idx_orders_customer_id ON orders(customer_id)'."
        ),
        "category": "pattern",
        "metadata": {"topic": "indexes", "priority": "high"},
    },
    {
        "content": (
            "Patrón: Enums como tipos PostgreSQL o tablas lookup. "
            "Para campos con valores fijos (status, role, category), usar CREATE TYPE enum "
            "para pocos valores estables, o una tabla de lookup para valores que pueden "
            "crecer. Tabla lookup es preferible cuando: hay más de 10 valores posibles, "
            "los valores pueden cambiar sin deploy, o necesitas metadata adicional por valor."
        ),
        "category": "pattern",
        "metadata": {"topic": "enums", "priority": "medium"},
    },
    {
        "content": (
            "Patrón: Normalización hasta 3NF. "
            "Primera Forma Normal (1NF): sin campos multivaluados ni repetidos. "
            "Segunda Forma Normal (2NF): todos los atributos dependen de toda la PK. "
            "Tercera Forma Normal (3NF): no hay dependencias transitivas. "
            "En la práctica, 3NF es suficiente para la mayoría de aplicaciones. "
            "Desnormalizar solo cuando hay problemas de rendimiento medidos, no preventivamente."
        ),
        "category": "pattern",
        "metadata": {"topic": "normalization", "priority": "high"},
    },
    {
        "content": (
            "Patrón: Constraints como documentación. "
            "Usar CHECK, NOT NULL, UNIQUE, y DEFAULT generosamente. Los constraints no solo "
            "protegen la integridad sino que documentan las reglas del negocio directamente "
            "en el esquema. Ejemplo: 'CHECK (price >= 0)', 'CHECK (status IN (...))', "
            "'UNIQUE (email)', 'NOT NULL' en campos obligatorios."
        ),
        "category": "pattern",
        "metadata": {"topic": "constraints", "priority": "high"},
    },
    {
        "content": (
            "Patrón: Naming conventions consistentes. "
            "Usar snake_case para nombres de tablas y columnas. Tablas en plural (users, orders). "
            "FK con formato: tabla_singular_id (user_id, order_id). Tabla pivote: "
            "alphabetical order (course_student, NO student_course). "
            "Índices: idx_tabla_columna. Constraints: chk_tabla_regla, uq_tabla_columna."
        ),
        "category": "pattern",
        "metadata": {"topic": "naming", "priority": "medium"},
    },
    {
        "content": (
            "Patrón: Polimorfismo con tabla por tipo (Table per Type). "
            "Cuando hay herencia (ej: Users → Doctors, Patients), crear tabla base con "
            "atributos comunes y tablas hijas con FK a la base. Ejemplo: "
            "'users' (id, name, email) → 'doctors' (user_id FK, specialty) y "
            "'patients' (user_id FK, insurance_number). Evita columnas NULL y mantiene 3NF."
        ),
        "category": "pattern",
        "metadata": {"topic": "inheritance", "priority": "medium"},
    },
    {
        "content": (
            "Patrón: JSONB para datos semi-estructurados. "
            "Usar JSONB en PostgreSQL cuando: los atributos varían por registro (configuración, "
            "metadata), no necesitas JOIN sobre esos datos, o son datos importados de APIs "
            "externas con estructura variable. Indexar con GIN: "
            "'CREATE INDEX idx_metadata ON table USING GIN(metadata)'. "
            "NO usar JSONB para datos que sí deberían ser columnas relacionales."
        ),
        "category": "pattern",
        "metadata": {"topic": "semi_structured", "priority": "medium"},
    },
    {
        "content": (
            "Patrón: Índices compuestos para queries frecuentes. "
            "Si un query filtra por (status, created_at), crear un índice compuesto: "
            "'CREATE INDEX idx_orders_status_created ON orders(status, created_at DESC)'. "
            "El orden importa: la columna más selectiva primero. Un índice en (A, B) "
            "sirve para queries que filtran por A, o por A y B, pero NO solo por B."
        ),
        "category": "pattern",
        "metadata": {"topic": "indexes", "priority": "medium"},
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # ANTI-PATRONES (qué evitar)
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "content": (
            "Anti-patrón: God Table (Tabla Dios). "
            "Una tabla con 30+ columnas que mezcla conceptos diferentes. Señales: muchas "
            "columnas NULL, prefijos en columnas (shipping_address, billing_address), "
            "columnas que solo aplican a ciertos registros. Solución: descomponer en tablas "
            "separadas con relaciones claras. Una tabla debe representar UNA entidad."
        ),
        "category": "antipattern",
        "metadata": {"topic": "normalization", "priority": "high"},
    },
    {
        "content": (
            "Anti-patrón: Entity-Attribute-Value (EAV). "
            "Usar una tabla (entity_id, attribute_name, attribute_value) para almacenar "
            "datos dinámicos. Problemas: no hay tipos de datos, no hay constraints, queries "
            "complejos con muchos JOINs, rendimiento terrible. Alternativas: JSONB para "
            "datos variables, tabla por tipo para herencia, o tablas de lookup."
        ),
        "category": "antipattern",
        "metadata": {"topic": "schema_design", "priority": "high"},
    },
    {
        "content": (
            "Anti-patrón: Columnas multivaluadas (CSV en un campo). "
            "Guardar múltiples valores en una sola columna separados por comas: "
            "'tags: \"php,python,java\"'. Imposible hacer JOINs, indexar, o mantener "
            "integridad referencial. Solución: crear tabla separada con relación N:M. "
            "Ejemplo: tabla 'tags' + tabla pivote 'article_tags'."
        ),
        "category": "antipattern",
        "metadata": {"topic": "normalization", "priority": "high"},
    },
    {
        "content": (
            "Anti-patrón: Polymorphic Association sin constraint. "
            "Usar (reference_type, reference_id) como 'FK genérica' que apunta a diferentes "
            "tablas según el tipo. PostgreSQL no puede hacer FOREIGN KEY sobre esto. "
            "No hay integridad referencial real. Solución: tabla intermedia por tipo, "
            "o constraint con TRIGGER, o rediseñar la relación."
        ),
        "category": "antipattern",
        "metadata": {"topic": "relationships", "priority": "high"},
    },
    {
        "content": (
            "Anti-patrón: Datos redundantes (denormalización prematura). "
            "Guardar el nombre del cliente directamente en la tabla de órdenes 'para no hacer "
            "JOIN'. Si el cliente cambia de nombre, queda inconsistente. Solo desnormalizar "
            "cuando: hay métricas de rendimiento que lo justifican, el dato es histórico "
            "(precio al momento de la compra), o es un cache materializado."
        ),
        "category": "antipattern",
        "metadata": {"topic": "normalization", "priority": "medium"},
    },
    {
        "content": (
            "Anti-patrón: Tabla sin Primary Key. "
            "Toda tabla DEBE tener una clave primaria. Sin PK: no puedes identificar registros "
            "únicos, no puedes hacer UPDATE/DELETE preciso, la replicación puede fallar, "
            "y los ORM no pueden funcionar. Siempre agregar al menos 'id SERIAL PRIMARY KEY'."
        ),
        "category": "antipattern",
        "metadata": {"topic": "primary_keys", "priority": "high"},
    },
    {
        "content": (
            "Anti-patrón: Float para dinero. "
            "Usar FLOAT o DOUBLE para almacenar valores monetarios causa errores de "
            "redondeo (0.1 + 0.2 ≠ 0.3). Solución: usar NUMERIC(precision, scale) o "
            "DECIMAL. Ejemplo: 'price NUMERIC(10, 2)' para hasta 99,999,999.99. "
            "O almacenar centavos como INTEGER."
        ),
        "category": "antipattern",
        "metadata": {"topic": "data_types", "priority": "high"},
    },
    {
        "content": (
            "Anti-patrón: VARCHAR(255) everywhere. "
            "Usar VARCHAR(255) por defecto en todas las columnas de texto sin pensar. "
            "En PostgreSQL, VARCHAR(n) y TEXT tienen el mismo rendimiento. Usar TEXT "
            "cuando no hay límite lógico, y VARCHAR(n) con el límite real del negocio "
            "(email: 254, country_code: 3, phone: 20)."
        ),
        "category": "antipattern",
        "metadata": {"topic": "data_types", "priority": "medium"},
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # BEST PRACTICES (recomendaciones generales)
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "content": (
            "Best practice: Cascade con cuidado. "
            "ON DELETE CASCADE es útil en tablas dependientes (mensajes cuando se borra una "
            "conversación). Pero NUNCA usar cascade en tablas importantes de negocio. "
            "Para relaciones donde la eliminación del padre no debe eliminar hijos, usar "
            "ON DELETE RESTRICT o ON DELETE SET NULL."
        ),
        "category": "best_practice",
        "metadata": {"topic": "relationships", "priority": "high"},
    },
    {
        "content": (
            "Best practice: Migraciones incrementales e idempotentes. "
            "Las migraciones deben: (1) Usar IF NOT EXISTS / IF EXISTS para ser re-ejecutables, "
            "(2) Ser incrementales (ALTER, no DROP+CREATE), (3) No destruir datos existentes, "
            "(4) Tener un nombre descriptivo con timestamp, (5) Ser reversibles cuando sea "
            "posible (tener un rollback definido)."
        ),
        "category": "best_practice",
        "metadata": {"topic": "migrations", "priority": "high"},
    },
    {
        "content": (
            "Best practice: Tipos de datos apropiados en PostgreSQL. "
            "Email → VARCHAR(254). UUID → UUID (no VARCHAR). IP → INET. "
            "Fecha → DATE. Timestamp → TIMESTAMPTZ (con timezone). Booleano → BOOLEAN "
            "(no INTEGER 0/1). Dinero → NUMERIC(precision,scale). Teléfono → VARCHAR(20). "
            "JSON dinámico → JSONB (no JSON ni TEXT)."
        ),
        "category": "best_practice",
        "metadata": {"topic": "data_types", "priority": "high"},
    },
    {
        "content": (
            "Best practice: Diseño para queries comunes. "
            "Antes de modelar, listar los 5-10 queries más frecuentes que la aplicación hará. "
            "El esquema debe facilitar esos queries sin JOINs excesivos. Si un query necesita "
            "4+ JOINs para datos que se muestran juntos frecuentemente, considerar si la "
            "estructura puede simplificarse."
        ),
        "category": "best_practice",
        "metadata": {"topic": "schema_design", "priority": "medium"},
    },
    {
        "content": (
            "Best practice: Índices para columns en WHERE, JOIN, ORDER BY. "
            "Regla general: si una columna aparece frecuentemente en WHERE, JOIN ON, "
            "u ORDER BY, necesita un índice. No indexar columnas con baja cardinalidad "
            "(ej: boolean con 90% TRUE) excepto con índice parcial. "
            "Monitorear con EXPLAIN ANALYZE."
        ),
        "category": "best_practice",
        "metadata": {"topic": "indexes", "priority": "high"},
    },
    {
        "content": (
            "Best practice: Separar configuración de datos. "
            "Las tablas de configuración o catálogo (roles, status, categories) deben "
            "estar separadas de las tablas transaccionales (orders, payments). "
            "Las tablas de catálogo son pocas filas y cambian raramente; las "
            "transaccionales crecen constantemente. Esto facilita caching y backups."
        ),
        "category": "best_practice",
        "metadata": {"topic": "schema_design", "priority": "medium"},
    },
]
