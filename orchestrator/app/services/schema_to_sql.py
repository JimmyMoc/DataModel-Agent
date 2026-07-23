"""
Schema to SQL Generator: Conversión determinística de JSON Schema a PostgreSQL DDL.

Este módulo toma el esquema JSON generado por el LLM y produce SQL válido garantizado.
Elimina la dependencia del LLM para generar SQL, evitando errores de sintaxis.

Formatos de entrada soportados (el LLM genera variaciones):

Formato 1 (simple):
{
    "entities": [
        {"name": "users", "columns": ["id", "name", "email"], "relations": ["role"]}
    ]
}

Formato 2 (detallado):
{
    "entities": [
        {
            "name": "users",
            "columns": [
                {"name": "id", "type": "SERIAL PRIMARY KEY"},
                {"name": "email", "type": "VARCHAR(255) NOT NULL UNIQUE"},
                {"name": "role_id", "type": "INTEGER NOT NULL REFERENCES roles(id)"}
            ],
            "relations": [{"table": "roles", "column": "id"}]
        }
    ]
}
"""

import re
from typing import Optional
from dataclasses import dataclass, field


# ─── Column Definition ───────────────────────────────────────────────────────

@dataclass
class ColumnDef:
    """Definición normalizada de una columna."""
    name: str
    type: str = "VARCHAR(255)"
    nullable: bool = False
    unique: bool = False
    default: Optional[str] = None
    check: Optional[str] = None
    references: Optional[str] = None  # "tabla(columna)"
    is_pk: bool = False


@dataclass
class TableDef:
    """Definición normalizada de una tabla."""
    name: str
    columns: list[ColumnDef] = field(default_factory=list)
    is_pivot: bool = False
    composite_pk: list[str] = field(default_factory=list)  # Para tablas pivote


# ─── Type inference ──────────────────────────────────────────────────────────

# Mapeo de nombres de columna → tipos PostgreSQL más apropiados
COLUMN_TYPE_HINTS = {
    "id": "SERIAL",
    "email": "VARCHAR(254)",
    "password": "VARCHAR(255)",
    "phone": "VARCHAR(20)",
    "name": "VARCHAR(255)",
    "title": "VARCHAR(255)",
    "description": "TEXT",
    "content": "TEXT",
    "comment": "TEXT",
    "body": "TEXT",
    "bio": "TEXT",
    "address": "TEXT",
    "url": "VARCHAR(2048)",
    "image": "VARCHAR(2048)",
    "avatar": "VARCHAR(2048)",
    "price": "NUMERIC(10, 2)",
    "total": "NUMERIC(10, 2)",
    "total_price": "NUMERIC(10, 2)",
    "subtotal": "NUMERIC(10, 2)",
    "amount": "NUMERIC(10, 2)",
    "salary": "NUMERIC(10, 2)",
    "cost": "NUMERIC(10, 2)",
    "balance": "NUMERIC(10, 2)",
    "discount": "NUMERIC(5, 2)",
    "tax": "NUMERIC(5, 2)",
    "rating": "SMALLINT",
    "score": "SMALLINT",
    "age": "SMALLINT",
    "quantity": "INTEGER",
    "stock": "INTEGER",
    "count": "INTEGER",
    "order": "INTEGER",
    "position": "INTEGER",
    "sort_order": "INTEGER",
    "weight": "NUMERIC(8, 2)",
    "height": "NUMERIC(8, 2)",
    "width": "NUMERIC(8, 2)",
    "is_active": "BOOLEAN",
    "is_admin": "BOOLEAN",
    "is_verified": "BOOLEAN",
    "active": "BOOLEAN",
    "verified": "BOOLEAN",
    "published": "BOOLEAN",
    "visible": "BOOLEAN",
    "date": "DATE",
    "birth_date": "DATE",
    "start_date": "DATE",
    "end_date": "DATE",
    "due_date": "DATE",
    "scheduled_at": "TIMESTAMPTZ",
    "published_at": "TIMESTAMPTZ",
    "expires_at": "TIMESTAMPTZ",
    "deleted_at": "TIMESTAMPTZ",
    "status": "VARCHAR(50)",
    "role": "VARCHAR(50)",
    "type": "VARCHAR(50)",
    "category": "VARCHAR(100)",
    "slug": "VARCHAR(255)",
    "token": "VARCHAR(255)",
    "code": "VARCHAR(50)",
    "color": "VARCHAR(7)",
    "isbn": "VARCHAR(17)",
    "sku": "VARCHAR(50)",
    "credits": "INTEGER",
    "creditos": "INTEGER",
    "calificacion": "NUMERIC(4, 2)",
    "nota": "NUMERIC(4, 2)",
    "grade": "NUMERIC(4, 2)",
    "edad": "SMALLINT",
    "year": "SMALLINT",
    "semester": "SMALLINT",
    "semestre": "SMALLINT",
    "grado": "SMALLINT",
}


def _pluralize(word: str) -> str:
    """Pluralización simple para nombres de tabla en español e inglés."""
    if not word:
        return word
    # Ya es plural (termina en s pero no en ss/us/is)
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word
    # Excepciones comunes que se mantienen
    irregular = {
        "person": "people", "child": "children", "man": "men",
        "woman": "women", "foot": "feet", "tooth": "teeth",
    }
    if word.lower() in irregular:
        return irregular[word.lower()]
    # Inglés: category → categories, company → companies
    if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    # Inglés: class → classes, box → boxes, bus → buses, status → statuses
    if word.endswith(("ss", "us", "is", "x", "z", "ch", "sh")):
        return word + "es"
    # Default: agregar s (funciona para inglés y mayoría de español)
    return word + "s"


def infer_column_type(col_name: str) -> str:
    """Inferir el tipo PostgreSQL más apropiado según el nombre de la columna."""
    name_lower = col_name.lower()

    # FK pattern: tabla_id → INTEGER (match first, highest priority)
    if name_lower.endswith("_id"):
        return "INTEGER"

    # Buscar match exacto
    if name_lower in COLUMN_TYPE_HINTS:
        return COLUMN_TYPE_HINTS[name_lower]

    # Default
    return "VARCHAR(255)"


def infer_nullable(col_name: str) -> bool:
    """Inferir si una columna debería ser nullable."""
    nullable_patterns = [
        "description", "comment", "bio", "notes", "avatar",
        "image", "phone", "address", "deleted_at", "middle_name",
        "secondary", "optional", "url", "subtitle", "summary",
    ]
    name_lower = col_name.lower()
    return any(p in name_lower for p in nullable_patterns)


def infer_unique(col_name: str, table_name: str) -> bool:
    """Inferir si una columna debería tener constraint UNIQUE."""
    name_lower = col_name.lower()
    # Campos que siempre son únicos
    always_unique = {"email", "slug", "code", "sku", "isbn", "token", "username", "dni", "rfc", "curp"}
    if name_lower in always_unique:
        return True
    # "name" es unique en tablas de catálogo/lookup (roles, categories, statuses, etc.)
    catalog_tables = {"roles", "categories", "statuses", "types", "permissions",
                      "tags", "countries", "currencies", "languages", "priorities"}
    if name_lower == "name" and table_name.lower() in catalog_tables:
        return True
    return False


def infer_check_constraint(col_name: str, col_type: str) -> Optional[str]:
    """Inferir CHECK constraints apropiados."""
    name_lower = col_name.lower()

    if name_lower == "rating":
        return "rating >= 1 AND rating <= 5"
    if name_lower == "score":
        return "score >= 0 AND score <= 100"
    if name_lower in ("price", "total", "total_price", "amount", "cost",
                      "salary", "balance", "subtotal", "tax"):
        return f"{col_name} >= 0"
    if name_lower in ("quantity", "stock", "count"):
        return f"{col_name} >= 0"
    if name_lower in ("age", "edad"):
        return f"{col_name} >= 0 AND {col_name} <= 150"
    if name_lower in ("discount", "descuento"):
        return f"{col_name} >= 0 AND {col_name} <= 100"
    if name_lower in ("percentage", "porcentaje"):
        return f"{col_name} >= 0 AND {col_name} <= 100"
    if name_lower in ("credits", "creditos"):
        return f"{col_name} >= 0"

    return None


# ─── Schema Parser ───────────────────────────────────────────────────────────

def parse_schema(schema: dict) -> list[TableDef]:
    """
    Parsear el JSON schema del LLM y producir una lista normalizada de TableDef.
    Soporta múltiples formatos de entrada.
    """
    entities = schema.get("entities", [])
    tables: list[TableDef] = []

    for entity in entities:
        table_name = entity.get("name", "")
        if not table_name:
            continue

        raw_columns = entity.get("columns", [])
        relations = entity.get("relations", [])
        foreign_keys = entity.get("foreign_keys", [])

        table_def = TableDef(name=table_name)

        # Detectar si es formato simple (lista de strings) o detallado (lista de dicts)
        if raw_columns and isinstance(raw_columns[0], str):
            table_def.columns = _parse_simple_columns(raw_columns, table_name, relations)
        elif raw_columns and isinstance(raw_columns[0], dict):
            table_def.columns = _parse_detailed_columns(raw_columns, table_name)
        else:
            # Sin columnas definidas, generar mínimas
            table_def.columns = _generate_minimal_columns(table_name)

        # Aplicar foreign_keys explícitas del JSON (formato: [{"column": "x", "table": "y"}])
        if foreign_keys:
            _apply_foreign_keys(table_def, foreign_keys)

        # Asegurar que siempre tenga id, created_at, updated_at
        _ensure_standard_columns(table_def)

        # Detectar si es tabla pivote (tiene exactamente 2 FKs y pocos campos propios)
        fk_cols = [c for c in table_def.columns if c.references]
        non_meta_cols = [c for c in table_def.columns
                        if c.name not in ("id", "created_at", "updated_at") and not c.references]
        if len(fk_cols) == 2 and len(non_meta_cols) <= 2:
            table_def.is_pivot = True
            table_def.composite_pk = [c.name for c in fk_cols]

        tables.append(table_def)

    return tables


def _apply_foreign_keys(table_def: TableDef, foreign_keys: list[dict]):
    """
    Aplicar foreign_keys explícitas del JSON al TableDef.
    Formato: [{"column": "role_id", "table": "roles"}]
    """
    col_map = {c.name: c for c in table_def.columns}
    for fk in foreign_keys:
        col_name = fk.get("column", "")
        ref_table = fk.get("table", "")
        ref_col = fk.get("references", "id")  # Default a id
        if col_name and ref_table and col_name in col_map:
            col = col_map[col_name]
            col.references = f"{ref_table}({ref_col})"
            col.type = "INTEGER"
            col.nullable = False


def _parse_simple_columns(columns: list[str], table_name: str, relations) -> list[ColumnDef]:
    """Parsear formato simple: ["id", "name", "email", "role_id"]"""
    result = []
    for col_name in columns:
        if col_name in ("id", "created_at", "updated_at"):
            continue  # Se agregan automáticamente

        col = ColumnDef(name=col_name)
        col.type = infer_column_type(col_name)
        col.nullable = infer_nullable(col_name)
        col.check = infer_check_constraint(col_name, col.type)

        # Detectar FK por nombre
        if col_name.endswith("_id"):
            ref_table = _pluralize(col_name[:-3])  # user_id → users
            col.references = f"{ref_table}(id)"
            col.nullable = False

        # Detectar unique
        if infer_unique(col_name, table_name):
            col.unique = True

        result.append(col)

    return result


def _parse_detailed_columns(columns: list[dict], table_name: str) -> list[ColumnDef]:
    """Parsear formato detallado: [{"name": "email", "type": "VARCHAR(255) NOT NULL UNIQUE"}]"""
    result = []
    for col_dict in columns:
        col_name = col_dict.get("name", "")
        col_type_raw = col_dict.get("type", "")

        if col_name in ("id", "created_at", "updated_at"):
            continue  # Se agregan automáticamente

        col = ColumnDef(name=col_name)

        # Parsear el type string completo
        if col_type_raw:
            col = _parse_type_string(col_name, col_type_raw)
        else:
            col.type = infer_column_type(col_name)
            col.nullable = infer_nullable(col_name)
            col.check = infer_check_constraint(col_name, col.type)

        result.append(col)

    return result


def _parse_type_string(col_name: str, type_str: str) -> ColumnDef:
    """Parsear un string tipo 'VARCHAR(255) NOT NULL UNIQUE REFERENCES users(id)'"""
    col = ColumnDef(name=col_name)
    upper = type_str.upper()

    # Extraer REFERENCES
    ref_match = re.search(r"REFERENCES\s+(\w+\([\w,\s]+\))", type_str, re.IGNORECASE)
    if ref_match:
        col.references = ref_match.group(1)
        type_str = type_str[:ref_match.start()].strip()
        upper = type_str.upper()

    # Extraer CHECK
    check_match = re.search(r"CHECK\s*\((.+?)\)", type_str, re.IGNORECASE)
    if check_match:
        col.check = check_match.group(1)
        type_str = type_str[:check_match.start()].strip()
        upper = type_str.upper()

    # Extraer modificadores
    col.unique = "UNIQUE" in upper
    col.nullable = "NOT NULL" not in upper
    col.is_pk = "PRIMARY KEY" in upper

    # Limpiar el tipo base
    base_type = type_str
    for remove in ["NOT NULL", "NULL", "UNIQUE", "PRIMARY KEY"]:
        base_type = re.sub(r"\b" + remove + r"\b", "", base_type, flags=re.IGNORECASE)
    base_type = base_type.strip()

    if base_type:
        col.type = base_type
    else:
        col.type = infer_column_type(col_name)

    # Si el tipo incluye SERIAL, es el PK
    if "SERIAL" in col.type.upper():
        col.is_pk = True

    return col


def _generate_minimal_columns(table_name: str) -> list[ColumnDef]:
    """Generar columnas mínimas si no se proporcionaron."""
    return [ColumnDef(name="name", type="VARCHAR(255)", nullable=False)]


def _ensure_standard_columns(table_def: TableDef):
    """Asegurar que la tabla tenga id, created_at, updated_at."""
    col_names = {c.name for c in table_def.columns}

    # Verificar que no haya un PK duplicado
    has_pk = any(c.is_pk or c.name == "id" for c in table_def.columns)

    if "id" not in col_names and not has_pk:
        table_def.columns.insert(0, ColumnDef(name="id", type="SERIAL", is_pk=True))

    if "created_at" not in col_names:
        table_def.columns.append(ColumnDef(
            name="created_at", type="TIMESTAMP", default="NOW()", nullable=True
        ))

    if "updated_at" not in col_names:
        table_def.columns.append(ColumnDef(
            name="updated_at", type="TIMESTAMP", default="NOW()", nullable=True
        ))


# ─── SQL Generator ───────────────────────────────────────────────────────────

def generate_sql(tables: list[TableDef]) -> str:
    """
    Generar SQL DDL válido de PostgreSQL a partir de las definiciones de tablas.
    Ordena las tablas por dependencias (tablas referenciadas primero).
    """
    # Ordenar tablas por dependencias
    ordered = _topological_sort(tables)

    parts = []
    index_parts = []

    for table in ordered:
        # Generar CREATE TABLE
        sql = _generate_create_table(table)
        parts.append(sql)

        # Generar CREATE INDEX para FKs
        for col in table.columns:
            if col.references and col.name != "id":
                idx_name = f"idx_{table.name}_{col.name}"
                index_parts.append(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table.name}({col.name});"
                )

    # Combinar: tablas primero, luego índices
    result = "\n\n".join(parts)
    if index_parts:
        result += "\n\n-- Índices en Foreign Keys\n" + "\n".join(index_parts)

    return result


def _generate_create_table(table: TableDef) -> str:
    """Generar el CREATE TABLE para una tabla."""
    lines = []

    for col in table.columns:
        line = f"    {col.name}"

        # Tipo
        if col.is_pk and col.name == "id":
            line += " SERIAL PRIMARY KEY"
        else:
            line += f" {col.type}"

            # NOT NULL
            if not col.nullable and not col.is_pk:
                line += " NOT NULL"

            # UNIQUE
            if col.unique:
                line += " UNIQUE"

            # DEFAULT
            if col.default:
                line += f" DEFAULT {col.default}"

            # CHECK
            if col.check:
                line += f" CHECK ({col.check})"

            # REFERENCES
            if col.references:
                line += f" REFERENCES {col.references}"

        lines.append(line)

    # Composite PK para tablas pivote
    pk_line = ""
    if table.is_pivot and table.composite_pk:
        # Remover el id SERIAL PRIMARY KEY si es tabla pivote
        lines = [l for l in lines if "SERIAL PRIMARY KEY" not in l]
        pk_line = f"    PRIMARY KEY ({', '.join(table.composite_pk)})"
        lines.append(pk_line)

    columns_sql = ",\n".join(lines)

    return (
        f"CREATE TABLE IF NOT EXISTS {table.name} (\n"
        f"{columns_sql}\n"
        f");"
    )


def _topological_sort(tables: list[TableDef]) -> list[TableDef]:
    """
    Ordenar tablas topológicamente: las tablas que son referenciadas
    por otras se crean primero.
    """
    table_map = {t.name: t for t in tables}
    visited = set()
    result = []

    def visit(table_name: str):
        if table_name in visited:
            return
        visited.add(table_name)

        table = table_map.get(table_name)
        if not table:
            return

        # Visitar dependencias primero
        for col in table.columns:
            if col.references:
                ref_table = col.references.split("(")[0]
                if ref_table in table_map:
                    visit(ref_table)

        result.append(table)

    for table in tables:
        visit(table.name)

    return result


# ─── Lookup Table Detection ──────────────────────────────────────────────────

# Columns that should be converted to lookup table references
LOOKUP_CANDIDATES = {
    "status": ["pending", "active", "inactive", "completed", "cancelled"],
    "order_status": ["pending", "processing", "shipped", "delivered", "cancelled"],
    "payment_status": ["pending", "paid", "failed", "refunded"],
    "role": ["admin", "user", "moderator"],
    "priority": ["low", "medium", "high", "urgent"],
    "type": [],  # Generic, seeds depend on context
}


def _detect_and_create_lookups(tables: list[TableDef]) -> tuple[list[TableDef], list[TableDef]]:
    """
    Detectar columnas VARCHAR que deberían ser lookup tables.
    Retorna (lookup_tables_nuevas, tables_modificadas).
    """
    lookup_tables = []
    existing_table_names = {t.name for t in tables}

    for table in tables:
        cols_to_modify = []
        for col in table.columns:
            name_lower = col.name.lower()
            # Solo convertir si es VARCHAR y no es ya una FK
            if col.references or col.name.endswith("_id"):
                continue
            if name_lower in LOOKUP_CANDIDATES and "VARCHAR" in col.type.upper():
                # Crear nombre de lookup table
                lookup_name = f"{name_lower}_types" if name_lower == "type" else f"{name_lower}es" if name_lower.endswith("s") else f"{name_lower}s"
                # Evitar si ya existe
                if lookup_name not in existing_table_names:
                    lookup_table = TableDef(name=lookup_name, columns=[
                        ColumnDef(name="id", type="SERIAL", is_pk=True),
                        ColumnDef(name="name", type="VARCHAR(50)", nullable=False, unique=True),
                        ColumnDef(name="description", type="VARCHAR(255)", nullable=True),
                    ])
                    lookup_tables.append(lookup_table)
                    existing_table_names.add(lookup_name)

                # Modificar la columna original a FK
                cols_to_modify.append((col, lookup_name))

        for col, lookup_name in cols_to_modify:
            col.type = "INTEGER"
            col.references = f"{lookup_name}(id)"
            col.name = f"{col.name}_id" if not col.name.endswith("_id") else col.name
            col.check = None  # Remove CHECK since it's now a FK

    return lookup_tables, tables


# ─── Smart Index Generation ──────────────────────────────────────────────────

# Columns frequently used in WHERE clauses that benefit from indexes
SMART_INDEX_COLUMNS = {
    "email", "username", "slug", "status_id", "type_id",
    "is_active", "active", "verified", "published",
}


def _generate_smart_indexes(tables: list[TableDef]) -> list[str]:
    """
    Generar índices inteligentes para columnas frecuentemente filtradas,
    además de los índices en FK que ya se generan.
    """
    indexes = []
    for table in tables:
        for col in table.columns:
            # Skip if it already has FK index
            if col.references:
                continue
            if col.name.lower() in SMART_INDEX_COLUMNS:
                idx_name = f"idx_{table.name}_{col.name}"
                indexes.append(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table.name}({col.name});"
                )
            # Composite index for (status_id, created_at) pattern on transactional tables
            if col.name.lower() in ("status_id",):
                has_created_at = any(c.name == "created_at" for c in table.columns)
                if has_created_at:
                    idx_name = f"idx_{table.name}_{col.name}_created_at"
                    indexes.append(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table.name}({col.name}, created_at DESC);"
                    )
    return indexes


# ─── Soft Delete Support ─────────────────────────────────────────────────────

def _add_soft_delete(tables: list[TableDef], enable: bool = True):
    """Agregar deleted_at a todas las tablas para soft delete."""
    if not enable:
        return
    for table in tables:
        col_names = {c.name for c in table.columns}
        if "deleted_at" not in col_names and not table.is_pivot:
            table.columns.append(ColumnDef(
                name="deleted_at", type="TIMESTAMPTZ", nullable=True, default=None
            ))


def _generate_soft_delete_indexes(tables: list[TableDef]) -> list[str]:
    """Generar índices parciales para soft delete (WHERE deleted_at IS NULL)."""
    indexes = []
    for table in tables:
        has_deleted_at = any(c.name == "deleted_at" for c in table.columns)
        if has_deleted_at and not table.is_pivot:
            idx_name = f"idx_{table.name}_active"
            indexes.append(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table.name}(id) WHERE deleted_at IS NULL;"
            )
    return indexes


# ─── Seed Data Generation ────────────────────────────────────────────────────

CATALOG_SEEDS = {
    "roles": [
        {"name": "admin", "description": "Administrador del sistema"},
        {"name": "user", "description": "Usuario regular"},
        {"name": "moderator", "description": "Moderador de contenido"},
    ],
    "categories": [
        {"name": "General"},
    ],
    "statuses": [
        {"name": "pending"},
        {"name": "active"},
        {"name": "inactive"},
        {"name": "completed"},
        {"name": "cancelled"},
    ],
    "order_statuses": [
        {"name": "pending"},
        {"name": "processing"},
        {"name": "shipped"},
        {"name": "delivered"},
        {"name": "cancelled"},
    ],
    "payment_statuses": [
        {"name": "pending"},
        {"name": "paid"},
        {"name": "failed"},
        {"name": "refunded"},
    ],
    "priorities": [
        {"name": "low"},
        {"name": "medium"},
        {"name": "high"},
        {"name": "urgent"},
    ],
}


def _generate_seeds(tables: list[TableDef]) -> str:
    """Generar INSERT statements para datos de catálogo iniciales."""
    seed_parts = []
    table_names = {t.name for t in tables}

    for table_name, rows in CATALOG_SEEDS.items():
        if table_name not in table_names:
            continue

        table = next((t for t in tables if t.name == table_name), None)
        if not table:
            continue

        # Determinar qué columnas tienen los seeds
        seed_columns = list(rows[0].keys())
        # Filtrar solo columnas que existen en la tabla
        table_col_names = {c.name for c in table.columns}
        valid_cols = [c for c in seed_columns if c in table_col_names]

        if not valid_cols:
            continue

        cols_str = ", ".join(valid_cols)
        values = []
        for row in rows:
            vals = []
            for c in valid_cols:
                v = row.get(c)
                if v is None:
                    vals.append("NULL")
                else:
                    vals.append(f"'{v}'")
            values.append(f"({', '.join(vals)})")

        values_str = ",\n    ".join(values)
        seed_parts.append(
            f"INSERT INTO {table_name} ({cols_str}) VALUES\n"
            f"    {values_str}\n"
            f"ON CONFLICT (name) DO NOTHING;"
        )

    return "\n\n".join(seed_parts)


# ─── Relationship Validation ─────────────────────────────────────────────────

def _validate_relationships(tables: list[TableDef]) -> list[str]:
    """
    Validar integridad de relaciones:
    - Toda FK debe referenciar una tabla que existe en el schema
    - No debe haber relaciones huérfanas
    Retorna lista de warnings (no bloquea la generación).
    """
    warnings = []
    table_names = {t.name for t in tables}

    for table in tables:
        for col in table.columns:
            if col.references:
                ref_table = col.references.split("(")[0]
                if ref_table not in table_names:
                    warnings.append(
                        f"-- WARNING: {table.name}.{col.name} references "
                        f"'{ref_table}' which is not in the schema"
                    )

    return warnings


# ─── Enhanced SQL Generator ──────────────────────────────────────────────────

def generate_sql_enhanced(tables: list[TableDef], options: dict = None) -> str:
    """
    Generar SQL DDL completo con todas las mejoras:
    - Lookup tables auto-generadas
    - Smart indexes
    - Soft deletes
    - Seeds
    - Validation warnings
    """
    if options is None:
        options = {
            "soft_delete": True,
            "smart_indexes": True,
            "lookup_tables": True,
            "seeds": True,
        }

    # 1. Detectar y crear lookup tables
    lookup_tables = []
    if options.get("lookup_tables"):
        lookup_tables, tables = _detect_and_create_lookups(tables)

    # 2. Agregar soft delete
    if options.get("soft_delete"):
        all_tables = lookup_tables + tables
        # Ensure standard columns on lookup tables
        for lt in lookup_tables:
            _ensure_standard_columns(lt)
        _add_soft_delete(all_tables)
    else:
        all_tables = lookup_tables + tables
        for lt in lookup_tables:
            _ensure_standard_columns(lt)

    # 3. Ordenar todas las tablas topológicamente
    ordered = _topological_sort(all_tables)

    # 4. Generar CREATE TABLEs
    parts = []

    # Validation warnings como comentarios
    warnings = _validate_relationships(all_tables)
    if warnings:
        parts.append("\n".join(warnings))

    for table in ordered:
        sql = _generate_create_table(table)
        parts.append(sql)

    # 5. Generar índices FK
    fk_indexes = []
    for table in ordered:
        for col in table.columns:
            if col.references and col.name != "id":
                idx_name = f"idx_{table.name}_{col.name}"
                fk_indexes.append(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table.name}({col.name});"
                )

    if fk_indexes:
        parts.append("-- Índices en Foreign Keys\n" + "\n".join(fk_indexes))

    # 6. Smart indexes
    if options.get("smart_indexes"):
        smart_idxs = _generate_smart_indexes(ordered)
        if smart_idxs:
            parts.append("-- Índices para queries frecuentes\n" + "\n".join(smart_idxs))

    # 7. Soft delete partial indexes
    if options.get("soft_delete"):
        sd_indexes = _generate_soft_delete_indexes(ordered)
        if sd_indexes:
            parts.append("-- Índices parciales para soft delete\n" + "\n".join(sd_indexes))

    # 8. Seeds
    seed_sql = ""
    if options.get("seeds"):
        seed_sql = _generate_seeds(ordered)

    result = "\n\n".join(parts)
    if seed_sql:
        result += "\n\n-- Datos iniciales de catálogo\n" + seed_sql

    return result


# ─── Public API ──────────────────────────────────────────────────────────────

def schema_to_sql(schema_json: dict) -> str:
    """
    Función principal: convierte un esquema JSON del LLM en SQL DDL válido.

    Incluye automáticamente:
    - Ordenamiento topológico (dependencias primero)
    - UNIQUE en campos críticos (email, slug, name en catálogos)
    - CHECK constraints (rating, price, quantity, etc.)
    - Lookup tables para status/type/role columns
    - Smart indexes para columnas frecuentemente filtradas
    - Soft delete (deleted_at) en todas las tablas
    - Seeds para tablas de catálogo
    - Validación de relaciones huérfanas

    Args:
        schema_json: Esquema JSON generado por el LLM

    Returns:
        String con SQL DDL válido de PostgreSQL
    """
    tables = parse_schema(schema_json)
    return generate_sql_enhanced(tables)
