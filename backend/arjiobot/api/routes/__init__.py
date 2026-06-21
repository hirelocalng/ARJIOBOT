"""API route registration."""

from arjiobot.api.routes import account_status, accounts, auth, backtesting, bitget, control_plane, execution, health, live_automation, live_trading, mobile, monitoring, pairs, radar, reports, risk, settings, setups, signals, system, trades

ROUTERS = (
    auth.router,
    health.router,
    account_status.router,
    accounts.router,
    bitget.router,
    monitoring.router,
    live_automation.router,
    live_trading.router,
    control_plane.router,
    system.router,
    pairs.router,
    settings.router,
    radar.router,
    setups.router,
    signals.router,
    risk.router,
    execution.router,
    trades.router,
    mobile.router,
    backtesting.router,
    reports.router,
)
