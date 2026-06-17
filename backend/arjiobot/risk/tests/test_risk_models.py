"""Risk model tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from arjiobot.risk.risk_models import AccountSnapshot, OpenRiskState, RiskConfig, RiskRejectionReason, TradePlanStatus, build_assessment_id, build_trade_plan_id, trade_plan_to_record
from arjiobot.risk.demo_risk import default_context, make_signal
from arjiobot.risk.risk_engine import RiskEngine


def test_risk_config_account_snapshot_open_state_creation() -> None:
    config, snapshot, state = default_context()

    assert config.risk_amount_per_trade == Decimal("100")
    assert snapshot.available_margin == Decimal("10000")
    assert state.open_trade_count == 0


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError, match="risk_amount"):
        RiskConfig(account_equity=Decimal("10000"), risk_amount_per_trade=Decimal("0"))
    with pytest.raises(ValueError, match="account_equity is required"):
        RiskConfig(fixed_risk_amount=Decimal("100"))


def test_deterministic_ids_and_record() -> None:
    evaluated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert build_assessment_id("sig", evaluated_at) == build_assessment_id("sig", evaluated_at)
    assert build_trade_plan_id("sig", evaluated_at).startswith("tpl_")
    config, snapshot, state = default_context()
    plan = RiskEngine().create_trade_plan(make_signal(), config, snapshot, state)
    record = trade_plan_to_record(plan)
    assert record["approval_status"] == TradePlanStatus.APPROVED.value
    assert RiskRejectionReason.MISSING_ENTRY_REFERENCE_PRICE.value
