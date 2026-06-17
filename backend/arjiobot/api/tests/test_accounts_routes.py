"""Live Bitget account route tests."""

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.exchange import account_vault


def test_no_connected_account_when_account_list_empty() -> None:
    api = client()
    state = get_state()
    state.live_accounts.clear()
    state.encrypted_live_credentials.clear()
    state.active_live_account_id = None

    listed = api.get("/api/accounts").json()["data"]
    control = api.get("/api/control-plane").json()["data"]

    assert listed == []
    assert control["active_account"]["connection_status"] == "NOT CONNECTED"
    assert control["active_account"]["account_name"] == "None"


def test_bitget_account_save_does_not_call_signed_test(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY", "test-key")
    monkeypatch.setattr(account_vault, "VAULT_PATH", tmp_path / "accounts.vault.json")
    api = client()
    state = get_state()
    state.live_accounts.clear()
    state.encrypted_live_credentials.clear()
    state.active_live_account_id = None
    monkeypatch.setattr(
        state.bitget_environment,
        "test_connection",
        lambda symbol="BTCUSDT": (_ for _ in ()).throw(AssertionError("save must not call live Bitget test")),
    )

    response = api.post(
        "/api/accounts/bitget/test-and-save",
        json={"nickname": "Primary", "api_key": "abc123456xyz", "api_secret": "secret", "passphrase": "pass"},
    )

    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["connection_status"] == "NEEDS_VERIFICATION"
    assert saved["verification_status"] == "NEEDS_VERIFICATION"
    assert saved["last_error"] == "Saved locally. Click Test to verify Bitget private API access."


def test_bitget_save_adds_pending_account_without_secret_exposure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY", "test-key")
    monkeypatch.setattr(account_vault, "VAULT_PATH", tmp_path / "accounts.vault.json")
    api = client()
    state = get_state()

    response = api.post(
        "/api/accounts/bitget/test-and-save",
        json={"nickname": "Primary", "api_key": "abc123456xyz", "api_secret": "secret", "passphrase": "pass"},
    )
    listed = api.get("/api/accounts").json()["data"]
    control = api.get("/api/control-plane").json()["data"]

    assert response.status_code == 200
    assert listed[0]["api_key"] == "abc1****6xyz"
    assert "api_secret" not in listed[0]
    assert "passphrase" not in listed[0]
    assert listed[0]["connection_status"] == "NEEDS_VERIFICATION"
    assert listed[0]["balance"] == "N/A"
    assert control["active_account"]["connection_status"] == "NEEDS_VERIFICATION"
    assert control["active_account"]["balance"] == "N/A"


def test_account_persists_after_backend_restart_as_needs_verification(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY", "test-key")
    monkeypatch.setattr(account_vault, "VAULT_PATH", tmp_path / "accounts.vault.json")
    api = client()
    state = get_state()

    saved = api.post(
        "/api/accounts/bitget/test-and-save",
        json={"nickname": "Primary", "api_key": "abc123456xyz", "api_secret": "secret", "passphrase": "pass"},
    ).json()["data"]

    restarted = client()
    listed = restarted.get("/api/accounts").json()["data"]
    active = restarted.get("/api/accounts/active").json()["data"]

    assert listed[0]["account_id"] == saved["account_id"]
    assert listed[0]["connection_status"] == "NEEDS_VERIFICATION"
    assert active["account_id"] == saved["account_id"]
    assert "api_secret" not in listed[0]
    assert "passphrase" not in listed[0]


def test_account_save_blocked_without_encryption_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(account_vault, "VAULT_PATH", tmp_path / "accounts.vault.json")
    monkeypatch.setattr(account_vault, "LOCAL_KEY_PATH", tmp_path / ".credential_encryption_key")
    api = client()

    response = api.post(
        "/api/accounts/bitget/test-and-save",
        json={"nickname": "Primary", "api_key": "abc123456xyz", "api_secret": "secret", "passphrase": "pass"},
    )

    assert response.status_code == 400
    assert "encryption key missing" in str(response.json())


def test_vault_key_can_be_generated_from_ui_without_returning_secret(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(account_vault, "VAULT_PATH", tmp_path / "accounts.vault.json")
    monkeypatch.setattr(account_vault, "LOCAL_KEY_PATH", tmp_path / ".credential_encryption_key")
    api = client()

    generated = api.post("/api/accounts/vault-key/generate").json()["data"]
    status = api.get("/api/accounts/vault-key").json()["data"]

    assert generated["configured"] is True
    assert generated["source"] == "LOCAL_BACKEND_FILE"
    assert generated["secret_returned"] is False
    assert "key" not in generated
    assert status["configured"] is True
    assert account_vault.LOCAL_KEY_PATH.exists()


def test_vault_key_can_be_saved_from_ui_without_returning_secret(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(account_vault, "VAULT_PATH", tmp_path / "accounts.vault.json")
    monkeypatch.setattr(account_vault, "LOCAL_KEY_PATH", tmp_path / ".credential_encryption_key")
    api = client()

    saved = api.post("/api/accounts/vault-key", json={"encryption_key": "local-ui-vault-key-value-123456789"}).json()["data"]

    assert saved["configured"] is True
    assert saved["source"] == "LOCAL_BACKEND_FILE"
    assert saved["secret_returned"] is False
    assert "local-ui-vault-key-value" not in str(saved)


def test_reconnect_updates_existing_account_without_exposing_secrets(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY", "test-key")
    monkeypatch.setattr(account_vault, "VAULT_PATH", tmp_path / "accounts.vault.json")
    api = client()
    state = get_state()

    saved = api.post(
        "/api/accounts/bitget/test-and-save",
        json={"nickname": "Primary", "api_key": "abc123456xyz", "api_secret": "secret", "passphrase": "pass"},
    ).json()["data"]
    reconnected = api.post(
        f"/api/accounts/{saved['account_id']}/reconnect",
        json={"nickname": "Primary Updated", "api_key": "newkey1234abcd", "api_secret": "newsecret", "passphrase": "newpass"},
    ).json()["data"]

    assert reconnected["account_id"] == saved["account_id"]
    assert reconnected["account_name"] == "Primary Updated"
    assert reconnected["api_key"] == "newk****abcd"
    assert reconnected["connection_status"] == "NEEDS_VERIFICATION"
    assert "api_secret" not in reconnected
    assert "passphrase" not in reconnected
