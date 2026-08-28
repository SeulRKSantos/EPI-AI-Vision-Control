#!/usr/bin/env sh
# Applies pending migrations before the application accepts connections,
# then hands off to the process passed as CMD.
set -e

echo "Waiting for database at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
until python -c "
import asyncio, sys, asyncpg, os
async def check():
    try:
        conn = await asyncpg.connect(
            host=os.getenv('POSTGRES_HOST', 'db'),
            port=int(os.getenv('POSTGRES_PORT', 5432)),
            user=os.getenv('POSTGRES_USER', 'epi'),
            password=os.getenv('POSTGRES_PASSWORD', 'changeme'),
            database=os.getenv('POSTGRES_DB', 'epi_access'),
        )
        await conn.close()
    except Exception:
        sys.exit(1)
asyncio.run(check())
" 2>/dev/null; do
  sleep 1
done

echo "Applying migrations..."
alembic upgrade head

exec "$@"
