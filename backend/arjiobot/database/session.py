"""Optional PostgreSQL persistence via DATABASE_URL.

If DATABASE_URL is unset, or the database turns out to be unreachable, every
function here degrades to returning None, and api/dependencies.py /
exchange/account_vault.py fall back to their original data/*.json
file-based persistence. A database problem must never prevent the app from
starting or from saving settings locally - this module never raises.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from arjiobot.database.models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_engine_failed = False
_session_factory: sessionmaker | None = None
_tables_ready = False


def _normalized_database_url() -> str | None:
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        return None
    # SQLAlchemy 1.4+ rejects the legacy "postgres://" scheme some platforms
    # (Heroku-style) still hand out; psycopg2 needs "postgresql://".
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    return raw


def is_database_configured() -> bool:
    return _normalized_database_url() is not None


def get_session() -> Session | None:
    """A new Session ready to use, or None if the database isn't configured
    or isn't reachable right now. Tables are created on first successful
    connection. Caller is responsible for closing the returned session."""
    global _engine, _engine_failed, _session_factory, _tables_ready
    url = _normalized_database_url()
    if url is None:
        return None
    if _engine_failed:
        return None
    if _engine is None:
        try:
            _engine = create_engine(url, pool_pre_ping=True)
        except Exception:
            logger.exception("Failed to create database engine for DATABASE_URL")
            _engine_failed = True
            return None
    if not _tables_ready:
        try:
            Base.metadata.create_all(_engine)
            _tables_ready = True
            logger.info("Database tables ready (bot_settings, exchange_accounts)")
        except Exception:
            logger.exception("Failed to create database tables; falling back to JSON file persistence for this call")
            return None
    if _session_factory is None:
        _session_factory = sessionmaker(bind=_engine)
    try:
        return _session_factory()
    except Exception:
        logger.exception("Failed to open a database session; falling back to JSON file persistence for this call")
        return None
