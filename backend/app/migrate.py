from sqlalchemy import inspect, text

from app.database import Base, engine


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_add_missing_indexes)


def _add_missing_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    wanted = {
        "users": [("avatar_url", "VARCHAR(500)")],
        "conversations": [("avatar_url", "VARCHAR(500)")],
    }
    for table, columns in wanted.items():
        if table not in inspector.get_table_names():
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns:
            if name not in existing:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _add_missing_indexes(sync_conn) -> None:
    """create_all only builds indexes for new tables; add them to existing ones."""
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_messages_conversation_id_id ON messages (conversation_id, id)",
        "CREATE INDEX IF NOT EXISTS ix_messages_conversation_id_created_at ON messages (conversation_id, created_at)",
    ):
        sync_conn.execute(text(statement))
