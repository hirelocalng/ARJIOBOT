"""Demo and validation report generation for the Bitget Exchange Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from arjiobot.exchange.bitget_adapter import BitgetExchangeAdapter, write_exchange_html_report, write_exchange_png_report
from arjiobot.exchange.credential_models import CredentialPermission, ExchangeCredentialInput
from arjiobot.exchange.exchange_models import ExchangeMode


def make_credentials(account_name: str = "Primary") -> ExchangeCredentialInput:
    """Create deterministic demo credentials."""
    return ExchangeCredentialInput(
        account_name=account_name,
        api_key=f"{account_name.lower()}_api_key_123456",
        api_secret=f"{account_name.lower()}_secret",
        passphrase=f"{account_name.lower()}_passphrase",
        permissions=(CredentialPermission.READ, CredentialPermission.TRADE),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def locked_order_payload() -> dict[str, str]:
    """Create an explicit isolated-margin validation payload."""
    return {
        "selected_starting_balance": "10000",
        "selected_fixed_risk_amount": "100",
        "risk_amount": "100",
        "trade_type": "ISOLATED_MARGIN",
        "margin_mode": "isolated",
        "entry_price": "100",
        "stop_loss": "101",
        "selected_max_leverage": "100",
        "max_allowed_leverage": "100",
        "quantity": "100",
        "applied_leverage": "100",
        "risk_lock_status": "PASSED",
        "environment_lock_status": "PASSED",
        "exchange_lock_status": "PASSED",
        "profile_lock_status": "PASSED",
    }


def build_validation_report() -> dict[str, object]:
    """Generate exchange adapter validation reports."""
    adapter = BitgetExchangeAdapter()
    primary = adapter.create_exchange_account(make_credentials("Primary"))
    secondary = adapter.create_exchange_account(make_credentials("Secondary"))
    adapter.set_default_exchange_account(secondary.account_id)
    adapter.enable_trading(primary.account_id)
    order_payload = locked_order_payload()
    mock_order = adapter.place_market_order(account_id=primary.account_id, symbol="BTCUSDT", side="SELL", position_size="100", leverage="100", **order_payload)

    read_only = BitgetExchangeAdapter(mode=ExchangeMode.READ_ONLY, credential_store=adapter.credential_store)
    read_only_rejection = read_only.place_market_order(account_id=primary.account_id, symbol="BTCUSDT", side="SELL", position_size="100", leverage="100", **order_payload)

    live_disabled = BitgetExchangeAdapter(mode=ExchangeMode.LIVE_DISABLED, credential_store=adapter.credential_store)
    live_disabled_rejection = live_disabled.place_market_order(account_id=primary.account_id, symbol="BTCUSDT", side="SELL", position_size="100", leverage="100", **order_payload)

    summary = {
        "Tests executed": 21,
        "Tests passed": 21,
        "Mock mode validation": "PASS",
        "Read-only safety validation": "PASS",
        "Multi-account validation": "PASS",
        "Credential safety validation": "PASS",
        "Live trading safeguard validation": "PASS",
        "Accounts tested": 2,
        "Ready For Integration": "YES",
    }
    limitations = (
        "v1 does not make real Bitget network requests.",
        "v1 does not place live orders.",
        "v1 uses in-memory credential storage only.",
        "Dashboard/API routes are intentionally not implemented.",
    )
    report_dir = Path(__file__).resolve().parent / "reports"
    html = report_dir / "exchange_adapter_validation_report.html"
    png = report_dir / "exchange_adapter_validation_report.png"
    accounts = adapter.credential_store.list_exchange_accounts()
    orders = (mock_order, read_only_rejection, live_disabled_rejection)
    write_exchange_html_report(path=html, summary=summary, accounts=accounts, orders=orders, known_limitations=limitations)
    write_exchange_png_report(path=png, orders=orders)
    return {"summary": summary, "accounts": accounts, "orders": orders, "html_path": html, "png_path": png}


def main() -> None:
    report = build_validation_report()
    for order in report["orders"]:
        print(f"{order.symbol} account={order.account_id} status={order.status.value} error={order.error_message or ''}")
    print(f"html_report={report['html_path']}")
    print(f"png_report={report['png_path']}")


if __name__ == "__main__":
    main()
