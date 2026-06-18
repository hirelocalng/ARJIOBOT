"""SQLAlchemy models for ArjioBot's optional PostgreSQL persistence.

Only used when DATABASE_URL is set - see database/session.py. Without it,
the app keeps using the original data/*.json file-based persistence
unchanged; this module is purely additive.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class BotSetting(Base):
    """One row per arjiobot.api.dependencies.DEFAULT_SETTINGS key.

    Generic key/value rather than one column per setting, since the set of
    settings keys has changed multiple times already and a JSON value column
    avoids a schema migration every time a new one is added. Also used to
    persist the credential vault's active_account_id under the reserved key
    "_vault_active_account_id" (see database/store.py) - a real column would
    have meant a third table the schema doesn't otherwise need.
    """

    __tablename__ = "bot_settings"

    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=True)


class ExchangeAccountRow(Base):
    """One row per saved exchange account.

    account_data mirrors the existing in-memory/JSON-file account record
    dict exactly (everything except the encrypted credential blob, which
    gets its own column) - matching the JSON file's structure so callers in
    accounts.py/bitget.py/control_plane.py need no changes at all; only
    account_vault.py's load_vault()/save_vault() know this table exists.
    """

    __tablename__ = "exchange_accounts"

    account_id = Column(String, primary_key=True)
    account_data = Column(JSON, nullable=False)
    encrypted_credentials = Column(JSON, nullable=True)
