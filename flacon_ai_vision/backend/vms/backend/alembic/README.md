# Alembic Migrations (Skeleton)

This directory contains the Alembic baseline setup for backend schema migrations.

## Preconditions

1. Install dev dependencies:
   `pip install -r requirements-dev.txt`
2. Set the database URL:
   `set DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/dbname`
   (PowerShell: `$env:DATABASE_URL='postgresql+psycopg://user:pass@localhost:5432/dbname'`)

## Common commands (run from repository root)

1. Create a new migration:
   `alembic revision --autogenerate -m "describe_change"`
2. Apply all migrations:
   `alembic upgrade head`
3. Roll back one revision:
   `alembic downgrade -1`
4. Show current revision:
   `alembic current`

## Notes

- `env.py` loads SQLAlchemy metadata from `vms.backend.core.database.Base`.
- `DATABASE_URL` overrides the fallback URL from `alembic.ini`.
- Migration files are stored in `vms/backend/alembic/versions/`.
