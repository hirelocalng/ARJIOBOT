import { useEffect, useState } from 'react';
import { deleteAccount, disableTrading, enableTrading, generateVaultKey, getVaultKeyStatus, reconnectAccount, refreshAccount, saveVaultKey, selectActiveAccount, testAndSaveBitgetAccount, testConnection } from '../api/accounts';
import { TextInput } from '../components/forms/TextInput';
import { DataTable } from '../components/tables/DataTable';
import type { ControlPlaneSnapshot } from '../types/controlPlane';
import type { ExchangeAccount } from '../types/accounts';
import { confirmDangerousAction } from '../utils/safety';

export function AccountManager({ accounts, onRefresh, controlPlane }: { accounts: ExchangeAccount[]; onRefresh: () => Promise<void>; controlPlane: ControlPlaneSnapshot | null }) {
  const [accountName, setAccountName] = useState('Primary Bitget');
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [passphrase, setPassphrase] = useState('');
  const [reconnectId, setReconnectId] = useState<string | null>(null);
  const [vaultKey, setVaultKey] = useState('');
  const [vaultStatus, setVaultStatus] = useState<{ configured: boolean; source: string; secret_returned: boolean } | null>(null);
  const [status, setStatus] = useState('No account test run yet');

  useEffect(() => {
    void refreshVaultStatus();
  }, []);

  async function refreshVaultStatus() {
    try {
      setVaultStatus(await getVaultKeyStatus());
    } catch {
      setVaultStatus({ configured: false, source: 'ERROR', secret_returned: false });
    }
  }

  async function submit() {
    try {
      setStatus('Saving Bitget credentials to local vault...');
      if (reconnectId) {
        await reconnectAccount(reconnectId, { account_name: accountName, nickname: accountName, api_key: apiKey, api_secret: apiSecret, passphrase, permissions: ['READ', 'TRADE'] });
      } else {
        await testAndSaveBitgetAccount({ account_name: accountName, nickname: accountName, api_key: apiKey, api_secret: apiSecret, passphrase, permissions: ['READ', 'TRADE'] });
      }
      setApiSecret('');
      setPassphrase('');
      setApiKey('');
      setReconnectId(null);
      setStatus('Bitget account saved. Click Test on the saved row to verify live Bitget API access.');
      await refreshVaultStatus();
      await onRefresh();
    } catch (error) {
      setStatus(error instanceof Error ? `Account save failed: ${error.message}` : 'Account save failed');
    }
  }

  async function setupVaultKey(generate = false) {
    try {
      setStatus(generate ? 'Generating local credential vault key...' : 'Saving local credential vault key...');
      const next = generate ? await generateVaultKey() : await saveVaultKey(vaultKey);
      setVaultKey('');
      setVaultStatus(next);
      setStatus('Credential vault is ready. You can now save the Bitget account.');
    } catch (error) {
      setStatus(error instanceof Error ? `Vault setup failed: ${error.message}` : 'Vault setup failed');
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold text-ink">Accounts</h1>
      <div className="grid gap-3 md:grid-cols-4">
        <StatusCard label="Connection" value={String(controlPlane?.active_account.connection_status ?? 'NOT CONNECTED')} />
        <StatusCard label="Credential Type" value={String(controlPlane?.active_account.credential_type ?? 'LIVE')} />
        <StatusCard label="Last API Ping" value={String(controlPlane?.active_account.last_successful_api_ping_time ?? 'None')} />
        <StatusCard label="Environment Lock" value={String(controlPlane?.active_exchange_mode.environment_lock_verified ?? 'NO')} />
      </div>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-4">
        <StatusCard label="Credential Vault" value={vaultStatus?.configured ? 'READY' : 'NOT SET'} />
        <StatusCard label="Vault Source" value={vaultStatus?.source ?? 'LOADING'} />
        <div className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-muted md:col-span-2">
          This is not your Bitget passphrase. It is a local key ArjioBot uses to encrypt your saved Bitget credentials on this computer. It is never returned to the browser.
        </div>
        <TextInput label="Optional Custom Vault Key" value={vaultKey} type="password" onChange={setVaultKey} placeholder="Leave blank and click Generate" />
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" onClick={() => void setupVaultKey(true)}>Generate & Save Vault Key</button>
        <button className="rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-ink" disabled={!vaultKey} onClick={() => void setupVaultKey(false)}>Save Custom Vault Key</button>
        <button className="rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-ink" onClick={() => void refreshVaultStatus()}>Refresh Vault Status</button>
      </div>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-4">
        <TextInput label="Nickname" value={accountName} onChange={setAccountName} />
        <TextInput label="API Key" value={apiKey} onChange={setApiKey} />
        <TextInput label="API Secret" value={apiSecret} type="password" onChange={setApiSecret} />
        <TextInput label="Passphrase" value={passphrase} type="password" onChange={setPassphrase} />
        {reconnectId && <div className="rounded-md border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-100 md:col-span-4">Reconnect mode active for {reconnectId}. Enter fresh credentials and save. Use Test after saving to verify Bitget access.</div>}
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950 md:col-span-4" onClick={submit}>{reconnectId ? 'SAVE RECONNECTED BITGET ACCOUNT' : 'SAVE BITGET ACCOUNT'}</button>
        <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 md:col-span-4">{status}</div>
      </div>
      <DataTable
        rows={accounts}
        emptyLabel="No Bitget accounts"
        columns={[
          { header: 'Name', render: (row) => row.account_name },
          { header: 'Masked API Key', render: (row) => row.api_key },
          { header: 'Active', render: (row) => row.is_default ? 'YES' : <button className="text-action" onClick={async () => { await selectActiveAccount(row.account_id); await onRefresh(); }}>Select Active</button> },
          { header: 'Trading', render: (row) => row.trading_enabled ? 'Enabled' : 'Disabled' },
          { header: 'Connection', render: (row) => row.is_default ? String(controlPlane?.active_account.connection_status ?? row.verification_status) : row.verification_status },
          { header: 'Balance', render: (row) => row.is_default ? String(controlPlane?.active_account.balance ?? row.balance ?? 'Unavailable') : String(row.balance ?? 'Unavailable') },
          { header: 'Available Margin', render: (row) => row.is_default ? String(controlPlane?.active_account.available_margin ?? row.available_margin ?? 'Unavailable') : String(row.available_margin ?? 'Unavailable') },
          { header: 'Last Success', render: (row) => String(row.last_successful_api_ping_time ?? 'None') },
          { header: 'Last Failed', render: (row) => String(row.last_failed_check_time ?? 'None') },
          { header: 'Last Error', render: (row) => String(row.last_error ?? 'None') },
          { header: 'Refresh', render: (row) => <button className="text-action" onClick={async () => { await refreshAccount(row.account_id); await onRefresh(); }}>Refresh</button> },
          { header: 'Verify', render: (row) => <button className="text-action" onClick={async () => { await testConnection(row.account_id); await onRefresh(); }}>Test</button> },
          { header: 'Reconnect', render: (row) => <button className="text-warning" onClick={() => { setReconnectId(row.account_id); setAccountName(row.account_name); setStatus(`Reconnect ${row.account_name}`); }}>Reconnect</button> },
          { header: 'Toggle', render: (row) => <button className="text-warning" onClick={async () => { if (confirmDangerousAction('Change trading flag?')) { row.trading_enabled ? await disableTrading(row.account_id) : await enableTrading(row.account_id); await onRefresh(); } }}>{row.trading_enabled ? 'Disable' : 'Enable'}</button> },
          { header: 'Delete', render: (row) => <button className="text-danger" onClick={async () => { if (confirmDangerousAction(`Delete ${row.account_name}?`)) { await deleteAccount(row.account_id); await onRefresh(); } }}>Delete</button> }
        ]}
      />
      <div className="rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-danger">Full API secrets and passphrases are never displayed after submission.</div>
    </div>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-800 bg-panel p-4"><div className="text-xs text-muted">{label}</div><div className="text-lg text-ink">{value}</div></div>;
}
