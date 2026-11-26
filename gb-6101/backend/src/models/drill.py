from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Table, UniqueConstraint
from .base import metadata

# A drill session ("场") groups the copies that one outsourced team practises on.
# Aliases ("代号") are stable for the whole session and are regenerated for a new
# session, so the same original vehicle never keeps the same code name across scenes.
drill_sessions = Table(
    "drill_sessions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", String(48), unique=True, nullable=False),
    Column("tag", String(8), unique=True, nullable=False),
    Column("title", String(120), nullable=False),
    Column("created_by", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
)

# Internal mapping original asset -> public code name. Never exposed to outsource accounts.
drill_aliases = Table(
    "drill_aliases", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", ForeignKey("drill_sessions.id"), nullable=False, index=True),
    Column("original_asset", String(64), nullable=False),
    Column("alias", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    UniqueConstraint("session_id", "original_asset", name="uq_drill_alias_asset"),
    UniqueConstraint("session_id", "alias", name="uq_drill_alias_code"),
    UniqueConstraint("session_id", "ordinal", name="uq_drill_alias_ordinal"),
)

# One drill batch is a copy of one historical run. The copied case carries the
# anonymised payload; the source run id stays server-side only.
drill_batches = Table(
    "drill_batches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", ForeignKey("drill_sessions.id"), nullable=False, index=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, unique=True),
    Column("source_run_id", ForeignKey("runs.id"), nullable=False),
    Column("parameter", Integer, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("kind", String(16), nullable=False),
    Column("state", String(16), nullable=False),
    Column("created_by", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("session_id", "source_run_id", name="uq_drill_source"),
    UniqueConstraint("session_id", "ordinal", name="uq_drill_batch_ordinal"),
)
