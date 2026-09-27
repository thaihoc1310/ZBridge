"""Fail when the ORM and the migrated database disagree on columns.

The test suite builds its schema from the models on SQLite, so a model column
without a migration (or the reverse) passes CI and only breaks production:
that is how the debt reminder dispatcher crashed after 5d16b16. CI runs this
against a real Postgres after `alembic upgrade head`.
"""

import asyncio
import sys

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  registers every table on the metadata
from app.core.config import settings
from app.db.database import Base


def _diff(connection) -> list[str]:
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    problems = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            problems.append(f"{table.name}: table missing from migrations")
            continue
        database = {column["name"] for column in inspector.get_columns(table.name)}
        models = {column.name for column in table.columns}
        for name in sorted(models - database):
            problems.append(f"{table.name}.{name}: in the model, not in the database")
        for name in sorted(database - models):
            problems.append(f"{table.name}.{name}: in the database, not in the model")
    return problems


async def main() -> int:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        problems = await connection.run_sync(_diff)
    await engine.dispose()
    for problem in problems:
        print(f"SCHEMA_DRIFT {problem}")
    print(f"schema drift check: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
