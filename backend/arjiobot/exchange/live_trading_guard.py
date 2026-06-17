"""Central live trading safety gate."""

from __future__ import annotations

from dataclasses import dataclass

from arjiobot.exchange.credential_models import ExchangeAccount, VerificationStatus
from arjiobot.exchange.exchange_models import ExchangeMode
from arjiobot.risk.risk_models import TradePlan, TradePlanStatus


@dataclass(frozen=True, slots=True)
class LiveTradingGuardResult:
    allowed: bool
    reasons: tuple[str, ...]


def evaluate_live_trading_guard(
    *,
    live_trading_enabled: bool,
    adapter_mode: ExchangeMode,
    selected_account: ExchangeAccount | None,
    risk_trade_plan: TradePlan | None,
    execution_instruction_validated: bool,
    explicit_manual_live_confirmation: bool,
) -> LiveTradingGuardResult:
    """Return whether all future live-trading gates are satisfied."""
    reasons: list[str] = []
    if not live_trading_enabled:
        reasons.append("LIVE_TRADING_ENABLED is not true")
    if adapter_mode is not ExchangeMode.LIVE_ENABLED:
        reasons.append("ADAPTER_MODE is not LIVE_ENABLED")
    if selected_account is None:
        reasons.append("selected account is required")
    else:
        if not selected_account.trading_enabled:
            reasons.append("selected account trading_enabled is false")
        if selected_account.verification_status is not VerificationStatus.VERIFIED:
            reasons.append("API credentials are not verified")
    if risk_trade_plan is None or risk_trade_plan.approval_status is not TradePlanStatus.APPROVED:
        reasons.append("Risk Engine approved trade plan is required")
    if not execution_instruction_validated:
        reasons.append("Execution Engine instruction validation is required")
    if not explicit_manual_live_confirmation:
        reasons.append("explicit manual live confirmation flag is required")
    return LiveTradingGuardResult(allowed=not reasons, reasons=tuple(reasons))
