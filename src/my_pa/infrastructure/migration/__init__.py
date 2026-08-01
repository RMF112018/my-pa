"""Legacy-SQLite to PostgreSQL target-schema generation.

`generator.generate` reads the source profile and the disposition registry and
emits the PostgreSQL DDL for the tables the registry says to create, split into
the three steps the load needs: tables, then foreign keys, then indexes.
"""

from my_pa.infrastructure.migration.generator import GeneratedSchema, GenerationReport, generate

__all__ = ["GeneratedSchema", "GenerationReport", "generate"]
