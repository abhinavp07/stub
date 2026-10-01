"""Create the database named in DATABASE_URL if it doesn't exist (used by the e2e setup)."""

import asyncio
import sys

import asyncpg
from sqlalchemy.engine import make_url

from app.config import get_settings


async def main() -> None:
    url = make_url(get_settings().database_url)
    name = url.database
    if not name or not name.replace("_", "").isalnum():
        sys.exit(f"Refusing to create database with unexpected name: {name!r}")
    conn = await asyncpg.connect(
        user=url.username, password=url.password, host=url.host, port=url.port, database="postgres"
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
            print(f"Created database {name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
