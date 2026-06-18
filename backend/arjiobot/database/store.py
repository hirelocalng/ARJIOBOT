"""Thin read/write primitives for the optional database tables.

No business logic here (e.g. resetting connection_status on load, filtering
out secret fields before save) - that lives in api/dependencies.py and
exchange/account_vault.py exactly as it already did for the data/*.json
file path, so both persistence backends share the exact same transformation
logic and can't silently diverge. Every function here returns None/False on
any failure (database unset or unreachable) rather than raising - callers
fall back to the JSON file path in that case.
"""

from __future__ import annotations

import logging

from arjiobot.database.models import BotSetting, ExchangeAccountRow
from arjiobot.database.session import get_session

logger = logging.getLogger(__name__)


def read_all_settings() -> dict[str, object] | None:
    """All bot_settings rows as a dict, or None if the database is
    unavailable. An empty dict (not None) means the database is reachable
    but genuinely has no rows yet - i.e. first run."""
    session = get_session()
    if session is None:
        return None
    try:
        return {row.key: row.value for row in session.query(BotSetting).all()}
    except Exception:
        logger.exception("Failed to read bot_settings from the database")
        return None
    finally:
        session.close()


def write_settings(settings: dict[str, object]) -> bool:
    session = get_session()
    if session is None:
        return False
    try:
        for key, value in settings.items():
            row = session.get(BotSetting, key)
            if row is None:
                session.add(BotSetting(key=key, value=value))
            else:
                row.value = value
        session.commit()
        return True
    except Exception:
        logger.exception("Failed to write bot_settings to the database")
        session.rollback()
        return False
    finally:
        session.close()


def read_setting(key: str) -> object | None:
    session = get_session()
    if session is None:
        return None
    try:
        row = session.get(BotSetting, key)
        return row.value if row is not None else None
    except Exception:
        logger.exception("Failed to read bot_settings[%r] from the database", key)
        return None
    finally:
        session.close()


def read_all_accounts() -> tuple[dict[str, dict], dict[str, dict]] | None:
    """(account_id -> account_data, account_id -> encrypted_credentials), or
    None if the database is unavailable."""
    session = get_session()
    if session is None:
        return None
    try:
        rows = session.query(ExchangeAccountRow).all()
        accounts = {row.account_id: dict(row.account_data) for row in rows}
        encrypted = {row.account_id: dict(row.encrypted_credentials) for row in rows if row.encrypted_credentials}
        return accounts, encrypted
    except Exception:
        logger.exception("Failed to read exchange_accounts from the database")
        return None
    finally:
        session.close()


def write_accounts(accounts: dict[str, dict], encrypted: dict[str, dict]) -> bool:
    """Replaces the full exchange_accounts table contents with `accounts` /
    `encrypted` - already sanitized by the caller, no filtering done here."""
    session = get_session()
    if session is None:
        return False
    try:
        existing_ids = {row.account_id for row in session.query(ExchangeAccountRow.account_id).all()}
        for account_id in existing_ids - set(accounts.keys()):
            row = session.get(ExchangeAccountRow, account_id)
            if row is not None:
                session.delete(row)
        for account_id, account_data in accounts.items():
            row = session.get(ExchangeAccountRow, account_id)
            if row is None:
                session.add(ExchangeAccountRow(account_id=account_id, account_data=account_data, encrypted_credentials=encrypted.get(account_id)))
            else:
                row.account_data = account_data
                row.encrypted_credentials = encrypted.get(account_id)
        session.commit()
        return True
    except Exception:
        logger.exception("Failed to write exchange_accounts to the database")
        session.rollback()
        return False
    finally:
        session.close()
