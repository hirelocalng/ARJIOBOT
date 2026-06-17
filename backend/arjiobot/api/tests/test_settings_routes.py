"""Settings route tests."""

from arjiobot.api import dependencies
from arjiobot.api.tests.helpers import client


def test_settings_update(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "SETTINGS_PATH", tmp_path / "runtime_settings.json")
    api = client()

    settings = api.patch(
        "/api/settings",
        json={
            "max_open_trades": 3,
            "max_leverage": "5",
            "default_timeframe_profile": "PROFILE_15_10_5",
            "default_backtesting_profile": "PROFILE_RECOVERED_HIGH_WINRATE",
            "selected_rr_profile": "RR_1_5",
            "refresh_interval_seconds": "30",
            "paper_mode_display": False,
            "api_base_url": "http://localhost:8000",
            "adapter_mode": "BITGET_LIVE",
        },
    ).json()["data"]

    assert settings["max_open_trades"] == 3
    assert settings["max_leverage"] == "5"
    assert settings["default_timeframe_profile"] == "PROFILE_15_10_5"
    assert settings["default_backtesting_profile"] == "PROFILE_RECOVERED_HIGH_WINRATE"
    assert settings["selected_rr_profile"] == "RR_1_5"
    assert settings["refresh_interval_seconds"] == "30"
    assert settings["paper_mode_display"] is False
    assert settings["api_base_url"] == "http://localhost:8000"
    assert settings["adapter_mode"] == "BITGET_LIVE"
    assert "live_trading_enabled" in api.get("/api/settings").json()["data"]


def test_settings_persist_after_state_reload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "SETTINGS_PATH", tmp_path / "runtime_settings.json")
    api = client()

    api.patch(
        "/api/settings",
        json={
            "default_backtesting_profile": "PROFILE_RECOVERED_HIGH_WINRATE",
            "default_timeframe_profile": "PROFILE_15_10_5",
            "selected_rr_profile": "RR_1_5",
            "refresh_interval_seconds": "45",
            "paper_mode_display": False,
            "api_base_url": "http://127.0.0.1:9000",
        },
    )
    reloaded = dependencies.reset_state().settings

    assert reloaded["default_backtesting_profile"] == "PROFILE_RECOVERED_HIGH_WINRATE"
    assert reloaded["default_timeframe_profile"] == "PROFILE_15_10_5"
    assert reloaded["selected_rr_profile"] == "RR_1_5"
    assert reloaded["refresh_interval_seconds"] == "45"
    assert reloaded["paper_mode_display"] is False
    assert reloaded["api_base_url"] == "http://127.0.0.1:9000"


def test_invalid_settings_options_are_rejected() -> None:
    api = client()

    assert api.patch("/api/settings", json={"default_backtesting_profile": "PROFILE_G"}).status_code == 400
    assert api.patch("/api/settings", json={"active_strategy_profile": "UNKNOWN_PROFILE"}).status_code == 400
    assert api.patch("/api/settings", json={"default_timeframe_profile": "PROFILE_20_15_10"}).status_code == 400
    assert api.patch("/api/settings", json={"selected_rr_profile": "RR_1_3"}).status_code == 400
    assert api.patch("/api/settings", json={"selected_rr_profile": "RR_" + "1_1"}).status_code == 400
    assert api.patch("/api/settings", json={"adapter_mode": "PAPER"}).status_code == 400


def test_leg_target_research_tp_model_can_be_saved(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "SETTINGS_PATH", tmp_path / "runtime_settings.json")
    api = client()

    response = api.patch("/api/settings", json={"selected_rr_profile": "LEG_TARGET_RESEARCH"})

    assert response.status_code == 200
    assert response.json()["data"]["selected_rr_profile"] == "LEG_TARGET_RESEARCH"
    assert dependencies.reset_state().settings["selected_rr_profile"] == "LEG_TARGET_RESEARCH"


def test_quarantined_profile_is_rejected_as_backtesting_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "SETTINGS_PATH", tmp_path / "runtime_settings.json")
    api = client()

    response = api.patch("/api/settings", json={"default_backtesting_profile": "STRICT_PROFILE"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROFILE_FROZEN"


def test_recovered_profile_is_accepted_as_active_strategy_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "SETTINGS_PATH", tmp_path / "runtime_settings.json")
    api = client()

    response = api.patch("/api/settings", json={"active_strategy_profile": "PROFILE_RECOVERED_HIGH_WINRATE"})
    assert response.status_code == 200
    assert response.json()["data"]["active_strategy_profile"] == "PROFILE_RECOVERED_HIGH_WINRATE"


def test_profile_f_is_rejected_as_active_strategy_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "SETTINGS_PATH", tmp_path / "runtime_settings.json")
    api = client()

    response = api.patch("/api/settings", json={"active_strategy_profile": "PROFILE_F_VOLUME"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROFILE_FROZEN"


def test_settings_active_account_id_updates_global_active_account(tmp_path, monkeypatch) -> None:
    from arjiobot.api.routes import settings as settings_route

    monkeypatch.setattr(dependencies, "SETTINGS_PATH", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(settings_route, "save_vault", lambda accounts, encrypted, active: None)
    api = client()
    state = dependencies.get_state()
    state.live_accounts["acct_main"] = {
        "account_id": "acct_main",
        "account_name": "MAIN BITGET",
        "api_key": "bg_6****7fdb",
        "connection_status": "CONNECTED",
        "verification_status": "VERIFIED",
        "is_default": False,
        "is_active": False,
    }

    response = api.patch("/api/settings", json={"active_account_id": "acct_main"})
    control = api.get("/api/control-plane").json()["data"]

    assert response.status_code == 200
    assert dependencies.get_state().active_live_account_id == "acct_main"
    assert dependencies.get_state().live_accounts["acct_main"]["is_active"] is True
    assert control["active_account"]["account_name"] == "MAIN BITGET"

